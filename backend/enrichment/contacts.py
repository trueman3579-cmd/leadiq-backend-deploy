"""
backend/enrichment/contacts.py — Contact inference from public profiles.
Extracts email patterns, infers company domains, finds Twitter/LinkedIn handles.
Zero-cost: only public GitHub / Hacker News APIs.
"""
from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

COMMON_DOMAINS = {
    "google.com", "microsoft.com", "apple.com", "amazon.com",
    "meta.com", "facebook.com", "netflix.com", "uber.com",
    "stripe.com", "airbnb.com", "shopify.com", "slack.com",
    "twilio.com", "atlassian.com", "datadog.com", "zoom.us",
}


def extract_domain(email: str) -> str | None:
    """Extract domain from email address."""
    if "@" in email:
        return email.split("@")[-1].lower()
    return None


def infer_company_domain(author: str, bio: str | None) -> str | None:
    """Infer company domain from author bio or handle."""
    if bio:
        # Look for work@domain.com or similar
        email_match = re.search(r"[\w.+-]+@([\w.-]+\.[a-zA-Z]{2,})", bio)
        if email_match:
            return email_match.group(1).lower()

        # Look for "@CompanyName" in bio
        company_mention = re.search(r"@(\w+(?:\s\w+)*)\b", bio)
        if company_mention:
            name = company_mention.group(1).replace(" ", "").lower()
            return f"{name}.com"

    return None


async def enrich_github_contacts(username: str) -> dict:
    """Fetch GitHub profile and extract contact info."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://api.github.com/users/{username}")
            if resp.status_code != 200:
                return {}

            profile = resp.json()
            bio = profile.get("bio", "") or ""
            company = profile.get("company", "") or ""
            blog = profile.get("blog", "") or ""
            email = profile.get("email", "") or ""
            hireable = profile.get("hireable", False)
            location = profile.get("location", "")

            contacts = {
                "github_handle": username,
                "name": profile.get("name", ""),
                "bio": bio,
                "company": company,
                "location": location,
                "blog": blog,
                "email": email,
                "hireable": hireable,
                "public_repos": profile.get("public_repos", 0),
                "followers": profile.get("followers", 0),
            }

            # Infer email patterns
            if not email and company:
                # Try common patterns: first.last@company.com, etc.
                name_parts = (profile.get("name") or username).lower().split()
                if name_parts:
                    domain = extract_domain(company) or f"{company.lower().replace(' ', '')}.com"
                    contacts["inferred_email"] = f"{name_parts[0]}.{name_parts[-1]}@{domain}"

            return contacts
    except Exception as e:
        logger.warning("GitHub contact enrichment failed for %s: %s", username, e)
        return {}


async def enrich_hn_contacts(username: str) -> dict:
    """Fetch HN user profile and extract contact info."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://hacker-news.firebaseio.com/v0/user/{username}.json")
            if resp.status_code != 200:
                return {}

            profile = resp.json()
            about = profile.get("about", "") or ""

            contacts = {
                "hn_handle": username,
                "about": about,
                "karma": profile.get("karma", 0),
            }

            # Look for GitHub, Twitter, or email in about section
            github_match = re.search(r"github\.com/(\w+)", about)
            if github_match:
                contacts["github_handle"] = github_match.group(1)

            twitter_match = re.search(r"(?:twitter|x)\.com/(\w+)", about)
            if twitter_match:
                contacts["twitter_handle"] = twitter_match.group(1)

            email_match = re.search(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", about)
            if email_match:
                contacts["email"] = email_match.group(0)

            return contacts
    except Exception as e:
        logger.warning("HN contact enrichment failed for %s: %s", username, e)
        return {}


def infer_persona(post_text: str, author: str | None) -> dict:
    """Infer buyer persona from post text and author info."""
    roles = {
        "cto": "Technical Decision Maker",
        "vp engineering": "Technical Decision Maker",
        "head of engineering": "Technical Decision Maker",
        "engineering manager": "Technical Influencer",
        "senior engineer": "Technical Influencer",
        "founder": "Executive Decision Maker",
        "ceo": "Executive Decision Maker",
        "product manager": "Product Influencer",
        "devops": "Operations Decision Maker",
    }

    lower_text = post_text.lower()
    matched_roles = []
    for keyword, persona in roles.items():
        if keyword in lower_text:
            matched_roles.append(persona)

    return {
        "inferred_roles": list(set(matched_roles)) if matched_roles else ["Unknown"],
        "buyer_journey_stage": "Awareness" if "research" in lower_text else "Consideration",
    }
