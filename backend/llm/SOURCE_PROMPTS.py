"""
backend/llm/SOURCE_PROMPTS.py — Source-Specific Extraction Templates

Karpathy's context engineering principle: every source needs its own prompt.
Generic prompts lead to hallucinations; specific prompts ground the extraction.

Each prompt includes:
1. Source context (what this data source is)
2. Field extraction instructions (where to find each field)
3. Confidence ceiling (maximum trust for this source)
4. Gotchas (common mistakes to avoid)

Usage:
    from backend.llm.SOURCE_PROMPTS import SOURCE_PROMPTS, get_generic_prompt

    prompt = SOURCE_PROMPTS["tracxn"]
"""
from typing import Any

# ── Source-Specific Prompts ─────────────────────────────────────────────────────

SOURCE_PROMPTS = {
    "tracxn": """
Tracxn startup profile page extraction.

SOURCE CONTEXT:
Tracxn is a startup intelligence database with company profiles, funding data,
and team information. Data is aggregated from multiple sources and may not be
100% current.

FIELD EXTRACTION INSTRUCTIONS:
- company_name: Found in H1 header or page title. Strip any " - Tracxn" suffix.
- industry: Listed under "Industry" or "Sector" section. Map to standard categories.
- location: "Headquarters" or "Location" field. Format as "City, Country".
- company_size: "Employees" field. Map to: 1-10/11-50/51-200/201-500/500+
- funding_stage: "Funding Stage" field. Map to: bootstrapped/pre-seed/seed/series-a/series-b/series-c/public
- funding_amount: "Total Funding" with currency. Keep original format (e.g., "$15M").
- tech_stack: "Technology Stack" section. List as array.
- email: Check "Contact" section. Often hidden or requires login. Use null if not visible.
- linkedin_url: "LinkedIn" link in social section.
- founded_year: "Founded" field. Extract year as integer.
- founders: "Founders" or "Team" section. List names and titles.

CONFIDENCE CEILING: 0.70 (aggregated data, verify independently)

GOTCHAS:
- Funding amounts may be outdated. ALWAYS include year if available.
- Email addresses are often hidden. Use null, never guess.
- Company size ranges may be estimates. Use the range as-is.
- Multiple locations may be listed. Use headquarters (first listed).
""",

    "indimart": """
IndiaMART B2B supplier listing extraction.

SOURCE CONTEXT:
IndiaMART is a B2B marketplace connecting buyers with suppliers in India.
Data is user-submitted and often outdated. Company profiles are basic.

FIELD EXTRACTION INSTRUCTIONS:
- company_name: H1 heading or page title. Often includes " - IndiaMART" suffix to strip.
- industry: "Business Type" field. Map to standard industry categories.
- location: "City" and "State" fields. Format as "City, State, India".
- company_size: "Number of Employees" field. Use exact range from page.
- funding_stage: NOT AVAILABLE on IndiaMART. Always use null.
- tech_stack: NOT AVAILABLE. Use "Products" field as proxy for capabilities.
- email: Check contact section. May require login to view. Use null if hidden.
- annual_revenue: "Annual Turnover" field. Keep format (e.g., "₹10-50 Cr").
- phone: Phone number if visible.

CONFIDENCE CEILING: 0.50 (user-submitted, often stale)

GOTCHAS:
- Company size and revenue are self-reported and may be inaccurate.
- Email addresses are frequently hidden behind login.
- Many profiles are outdated (companies may have closed).
- Use "Products" as proxy for industry/tech_stack.
""",

    "github_profile": """
GitHub user or organization profile extraction.

SOURCE CONTEXT:
GitHub profiles contain developer and company information. This is HIGH CONFIDENCE
data because developers self-report and maintain their profiles.

FIELD EXTRACTION INSTRUCTIONS:
- company_name: "company" field in bio. Strip "@" prefix if present (indicates org).
- email: "email" field. HIGHEST CONFIDENCE (0.95) - verified by GitHub.
- location: "location" field. Format as "City, Country" or use as-is.
- company_size: NOT directly available. Estimate from org member count if available.
- tech_stack: Top repository languages. Array of programming languages.
- title: Extract from "bio" field if job title mentioned (e.g., "CTO at", "Founder of").
- linkedin_url: Check "blog" or "twitter" fields - may contain LinkedIn URL.
- founded_year: "created_at" field for organization accounts.
- hireable: "hireable" boolean field. If true, add "open_to_work" to intent_signals.
- repos_count: "public_repos" count. High count suggests active developer.

CONFIDENCE CEILING: 0.95 (verified API, developer confirms email)

GOTCHAS:
- Company names starting with "@" are GitHub organizations, not companies.
- Bio field may contain marketing text, not actual job title.
- Location may be "Remote" - use as-is.
- If "blog" URL is a personal site, it may have more info than GitHub.
""",

    "yourstory": """
YourStory startup article or profile extraction.

SOURCE CONTEXT:
YourStory is an Indian startup news publication with editorial content.
Data comes from journalist research and company submissions.

FIELD EXTRACTION INSTRUCTIONS:
- company_name: Article headline or H1. Often includes " - YourStory" suffix to strip.
- industry: Article tags or categories. May be multiple - use first primary.
- location: "Headquarters" or mentioned in article body. Format as "City, India".
- company_size: "Team Size" or employee count mentioned in article.
- funding_stage: Article body mentions funding round. Map to standard stages.
- funding_amount: Funding amount with currency. Include date if available.
- founded_year: "Founded in" or "Started in" mention in article.
- founders: "Founded by" section or mentions in article. List names with titles.
- email: Rare in articles. Check author byline for contact info.
- linkedin_url: May be linked in article or company profile page.

CONFIDENCE CEILING: 0.75 (editorial source, generally accurate)

GOTCHAS:
- Funding amounts may be in INR or USD. Note currency.
- Article dates matter for funding freshness. Extract date.
- Founders section may have multiple people. List all.
- Some articles are press releases - verify claims independently.
""",

    "producthunt": """
ProductHunt product listing extraction.

SOURCE CONTEXT:
ProductHunt is a product discovery platform where makers launch new products.
Data is self-posted by founders with community voting.

FIELD EXTRACTION INSTRUCTIONS:
- company_name: Product name (H1). Often the company name.
- industry: "Categories" tags. May be multiple - use primary.
- company_size: NOT AVAILABLE. Use "Team" section if visible.
- funding_stage: NOT directly shown. Check "Backed by" for investor signals.
- tech_stack: "Tech Stack" tag if available. Often incomplete.
- founded_year: "Launched" date. Extract year.
- email: "Made by" section may have founder Twitter/LinkedIn. Email rarely visible.
- upvotes: Upvote count. >500 indicates strong traction.
- hunters: Person who submitted. Often the founder.

CONFIDENCE CEILING: 0.72 (self-posted but fields often incomplete)

GOTCHAS:
- Product name may differ from company name. Check "Made by" for company.
- Email addresses are almost never shown. Use Twitter/LinkedIn for contact.
- "Featured" badge indicates editorial pick - higher visibility.
- Launch date may not equal founding year.
""",

    "hacker_news": """
HackerNews "Ask HN: Who is hiring?" or "Show HN" post extraction.

SOURCE CONTEXT:
HackerNews is a community-driven news site. Hiring posts are self-posted by
companies or founders, making this HIGH CONFIDENCE for job/intent data.

FIELD EXTRACTION INSTRUCTIONS:
- company_name: Often in ALL CAPS or quoted at start of first line.
- industry: Check post tags or article content.
- location: "Location:" or "Remote:" keyword in post body.
- company_size: NOT directly shown. Estimate from hiring volume.
- funding_stage: May be mentioned in company description.
- tech_stack: EXPLICITLY LISTED in job requirements. Array of technologies.
- email: Apply email or founder contact. HIGHEST QUALITY if founder-posted.
- remote_friendly: Check for "REMOTE" or "ONSITE" keywords.
- job_title: Position being hired for. Often multiple positions.
- intent_signals: Add "hiring" to intent_signals array.

CONFIDENCE CEILING: 0.82 (self-posted by founders, accurate but incomplete)

GOTCHAS:
- Company name may be in first line or subject.
- Multiple positions may be listed - create lead per position or note all.
- Email is often hidden - look for "apply at" or "contact" keywords.
- Remote/Onsite may be specified for each position.
""",

    "dpiit": """
DPIIT Startup India government registry extraction.

SOURCE CONTEXT:
DPIIT (Department for Promotion of Industry and Internal Trade) maintains
the official Startup India registry. This is GOVERNMENT VERIFIED data -
HIGH CONFIDENCE for company legitimacy.

FIELD EXTRACTION INSTRUCTIONS:
- company_name: "Entity Name" or "Startup Name" field.
- industry: "Sector" field. Map to standard categories.
- location: "State" and "City" fields. Format as "City, State, India".
- company_size: NOT in registry. Use null.
- funding_stage: "Stage" field may have: Ideation/Validation/Early Traction/Scaling.
- founded_year: "Date of Incorporation" or "Inception Date". Extract year.
- website: "Website" field.
- description: "Brief about startup" field.
- recognized: "DPIIT Recognition Number" and date.

CONFIDENCE CEILING: 0.78 (government registry, verified)

GOTCHAS:
- This is government data - company MUST be legitimate.
- Funding information is NOT provided. Use null.
- Stage field refers to startup stage, not funding stage.
- Use "Sector" for industry classification.
- No contact information in registry - must find externally.
""",

    "mca21": """
MCA21 Ministry of Corporate Affairs company filing extraction.

SOURCE CONTEXT:
MCA21 is the official Indian corporate registry (Ministry of Corporate Affairs).
ALL registered companies must file here. GOLD STANDARD for company legitimacy.

FIELD EXTRACTION INSTRUCTIONS:
- company_name: "Company Name" field. Official legal name.
- industry: "Principal Business Activity" field. May use NIC code.
- location: "Registered Office Address". Extract city and state.
- company_size: NOT directly shown. Check "Authorized Capital" for scale.
- funding_stage: NOT in filings. Infer from "Paid-up Capital".
- founded_year: "Date of Incorporation". Extract year.
- directors: "Directors" section. List names with DIN (Director ID Number).
- cin: "Corporate Identity Number" - unique company identifier.
- status: "Company Status" - Active/Strike Off/Dormant.

CONFIDENCE CEILING: 0.85 (official government registry)

GOTCHAS:
- Company names are LEGAL names - may differ from trading name.
- Authorized/Paid-up Capital indicate scale but not funding stage.
- Directors list is comprehensive - all directors must be listed.
- Status matters: only "Active" companies are operating.
- Address is REGISTERED office, may differ from operational.
""",
}


def get_generic_prompt() -> str:
    """Default prompt for unknown sources."""
    return """
Generic company/lead information extraction.

Extract all available company information from the provided content.
If a field cannot be found, use null (never guess or make assumptions).

FIELDS TO EXTRACT:
- company_name: Company or organization name
- industry: Business sector or industry
- location: City, State/Province, Country
- company_size: Employee count range
- funding_stage: Funding stage if mentioned
- tech_stack: Technologies used
- email: Contact email
- website: Company website
- founded_year: Year founded
- founders: Founder names and titles
- intent_signals: Any buying or hiring signals

CONFIDENCE CEILING: 0.40 (generic LLM extraction, needs validation)
"""


# ── Extraction Examples (Few-shot learning) ───────────────────────────────────
# Each example provides a concrete input/output pair for a source.
# Used by gemini_service.py to improve extraction quality via in-context learning.

EXTRACTION_EXAMPLES: dict[str, list[dict[str, Any]]] = {
    "tracxn": [
        {
            "input": "CloudScale Technologies | Tracxn\nSector: Cloud Infrastructure\nLocation: Hyderabad, India\nEmployees: 51-200\nFunding Stage: Series A\nTotal Funding: $12M\nTech Stack: Kubernetes, Terraform, AWS\nFounded: 2021\n",
            "output": {
                "company_name": "CloudScale Technologies",
                "industry": "Cloud Infrastructure",
                "location": "Hyderabad, India",
                "company_size": "51-200",
                "funding_stage": "series-a",
                "tech_stack": ["Kubernetes", "Terraform", "AWS"],
                "email": None,
                "website": None,
                "founded_year": 2021,
            }
        }
    ],
    "github_profile": [
        {
            "input": "# Stripe\n@stripe\nPayments infrastructure for the internet.\nSan Francisco, CA | 5000+ employees\nLanguages: Ruby, Go, TypeScript\nWebsite: https://stripe.com\nEmail: press@stripe.com",
            "output": {
                "company_name": "Stripe",
                "industry": "Fintech",
                "location": "San Francisco, CA",
                "company_size": "500+",
                "funding_stage": "public",
                "tech_stack": ["Ruby", "Go", "TypeScript"],
                "email": "press@stripe.com",
                "website": "https://stripe.com",
            }
        }
    ],
    "producthunt": [
        {
            "input": "Supabase — Open source Firebase alternative\nLaunched on Product Hunt\nMade by @kiwicopple\nCategories: Developer Tools, Open Source\nTech Stack: PostgreSQL, Elixir, Go\nUpvotes: 2,341",
            "output": {
                "company_name": "Supabase",
                "industry": "Developer Tools",
                "location": None,
                "company_size": None,
                "funding_stage": None,
                "tech_stack": ["PostgreSQL", "Elixir", "Go"],
                "email": None,
                "website": None,
            }
        }
    ],
    "hacker_news": [
        {
            "input": "Ask HN: Who is hiring? (April 2025)\n\nCloudScale Technologies | Hyderabad, India | Remote OK\nWe are a Series A cloud infrastructure startup building Kubernetes tools.\nTech: Go, Kubernetes, AWS\nPositions: Backend Engineer, SRE\nApply: jobs@cloudscale.io",
            "output": {
                "company_name": "CloudScale Technologies",
                "industry": "Cloud Infrastructure",
                "location": "Hyderabad, India",
                "company_size": None,
                "funding_stage": "series-a",
                "tech_stack": ["Go", "Kubernetes", "AWS"],
                "email": "jobs@cloudscale.io",
                "website": None,
            }
        }
    ],
    "yourstory": [
        {
            "input": "How HealthPlus Tech is transforming healthcare in India\nHeadquarters: Delhi NCR, India\nFounded: 2020\nTeam Size: 51-100\nSector: Healthcare IT\nFunding: Raised $5M in Seed round\nTech Stack: Vue.js, Django, AWS\nContact: hello@healthplus.tech",
            "output": {
                "company_name": "HealthPlus Tech",
                "industry": "Healthcare IT",
                "location": "Delhi NCR, India",
                "company_size": "51-100",
                "funding_stage": "seed",
                "tech_stack": ["Vue.js", "Django", "AWS"],
                "email": "hello@healthplus.tech",
                "website": None,
                "founded_year": 2020,
            }
        }
    ],
    "dpiit": [
        {
            "input": "Startup Name: AgriTech Solutions\nSector: Agriculture\nState: Punjab, India\nDPIIT Recognition Number: DIPP12345\nDate of Incorporation: 15-03-2022\nStage: Early Traction\nWebsite: www.agritechsolutions.in",
            "output": {
                "company_name": "AgriTech Solutions",
                "industry": "Agriculture",
                "location": "Punjab, India",
                "company_size": None,
                "funding_stage": None,
                "tech_stack": [],
                "email": None,
                "website": "www.agritechsolutions.in",
                "founded_year": 2022,
            }
        }
    ],
    "mca21": [
        {
            "input": "Company Name: INNOVATECH PRIVATE LIMITED\nCIN: U72200MH2021PTC123456\nPrincipal Business Activity: Software Development\nRegistered Office: Mumbai, Maharashtra\nDate of Incorporation: 10-01-2021\nDirectors: Rajesh Kumar (DIN: 01234567)\nStatus: Active",
            "output": {
                "company_name": "INNOVATECH PRIVATE LIMITED",
                "industry": "Software Development",
                "location": "Mumbai, Maharashtra",
                "company_size": None,
                "funding_stage": None,
                "tech_stack": [],
                "email": None,
                "website": None,
                "founded_year": 2021,
            }
        }
    ],
    "indimart": [
        {
            "input": "Shri Ganesh Enterprises - Manufacturer\nBusiness Type: Manufacturer, Supplier\nCity: Ahmedabad, Gujarat\nNumber of Employees: 11-50\nAnnual Turnover: ₹10-50 Cr\nProducts: Industrial Valves, Pipe Fittings",
            "output": {
                "company_name": "Shri Ganesh Enterprises",
                "industry": "Manufacturing",
                "location": "Ahmedabad, Gujarat",
                "company_size": "11-50",
                "funding_stage": None,
                "tech_stack": [],
                "email": None,
                "website": None,
            }
        }
    ],
}


# ── India-Specific Intent Signals (Karpathy: source vocabulary first) ───────────
# These are NOT LLM-generated. They're domain knowledge encoded as lookups.
# Used by _build_prompt() to inject source-specific context.

INDIA_SIGNALS_LOOKUP: dict[str, dict[str, list[str]]] = {
    "tracxn": {
        "high_intent": [
            "funding",
            "acquired",
            "Series",
            "valuation",
        ],
        "company_stage": [
            "Seed",
            "Series A",
            "Series B",
            "Growth",
        ],
        "funding_keywords": [
            "million",
            "billion",
            "valuation",
        ],
    },
    "indimart": {
        "high_intent": [
            "manufacturer",
            "supplier",
            "exporter",
            "wholesaler",
        ],
        "company_stage": [
            "SME",
            "MSME",
            "micro enterprise",
            "small enterprise",
        ],
        "funding_keywords": [
            "turnover",
            "annual revenue",
        ],
    },
    "github_profile": {
        "high_intent": [
            "hireable",
            "open to opportunities",
            "freelance",
            "available for work",
        ],
        "company_stage": [
            "organization",
            "personal",
            "company",
        ],
        "funding_keywords": [
            "sponsor",
            "funding",
            "backed by",
        ],
    },
    "yourstory": {
        "high_intent": [
            "raised",
            "funding",
            "Series",
            "valuation",
            "investors",
        ],
        "company_stage": [
            "seed stage",
            "Series A",
            "growth stage",
            "unicorn",
        ],
        "funding_keywords": [
            "$",
            "million",
            "crore",
            "funding round",
        ],
    },
    "producthunt": {
        "high_intent": [
            "launching",
            "new product",
            "beta",
            "waitlist",
        ],
        "company_stage": [
            "launching",
            "launched",
            "featured",
        ],
        "funding_keywords": [
            "backed by",
            "investors",
        ],
    },
    "hacker_news": {
        "high_intent": [
            "hiring",
            "we're hiring",
            "looking for",
            "join our team",
            "remote",
            "ask hn",
        ],
        "company_stage": [
            "seed",
            "Series A",
            "YC",
            "bootstrapped",
        ],
        "funding_keywords": [
            "raised",
            "funding",
            "investors",
        ],
    },
    "dpiit": {
        "high_intent": [
            "DPIIT recognized",
            "Startup India",
            "registered startup",
            "government certified",
        ],
        "company_stage": [
            "Ideation",
            "Validation",
            "Early Traction",
            "Scaling",
        ],
        "funding_keywords": [
            "seed funded",
            "Series A",
            "bootstrapped",
        ],
    },
    "mca21": {
        "high_intent": [
            "Active",
            "Paid-up Capital",
            "Authorized Capital",
            "Director DIN",
        ],
        "company_stage": [
            "Private Limited",
            "Limited",
            "OPC",
            "LLP",
        ],
        "funding_keywords": [
            "authorized capital",
            "paid up capital",
        ],
    },
}


def _build_prompt(
    text: str,
    source: str,
    author: str = "",
    mode: str = "b2b_sales",
) -> str:
    """
    Construct source-specific prompt following 3-layer architecture.

    Layer 1: Persona + Mission (Andrew Ng: define agent's identity)
    Layer 2: Source Context Block (Karpathy: source vocabulary first)
    Layer 3: Extraction Rules (Dario Amodei: 8 conservative constraints)

    Args:
        text: Raw post/signal text to analyze
        source: Data source identifier (tracxn, hacker_news, etc.)
        author: Author/poster name if available
        mode: Analysis mode (b2b_sales, hiring, job_search, opportunity)

    Returns:
        Fully constructed prompt for Gemini
    """
    # Layer 1: Persona + Mission
    persona_block = """You are a B2B sales intelligence analyst.
Your mission: Extract structured business signals from unstructured text.
You are conservative. You never guess. You prefer null over hallucination."""

    # Layer 2: Source Context Block
    source_prompt = SOURCE_PROMPTS.get(source, get_generic_prompt())

    # Get source-specific signals if available
    signals = INDIA_SIGNALS_LOOKUP.get(source, {})
    signals_block = ""
    if signals:
        high_intent = signals.get("high_intent", [])
        signals_block = f"""
SOURCE-SPECIFIC SIGNALS (use these to identify intent):
High Intent Keywords: {', '.join(high_intent)}
"""

    # Layer 3: Extraction Rules (Constitutional AI - Amodei)
    extraction_rules = """
EXTRACTION RULES (follow these strictly):
1. If a field cannot be extracted, use null (never guess or infer)
2. Confidence reflects data quality, NOT how promising the lead is
3. Source-specific signals above are your PRIMARY evidence
4. Company names must be EXACT - no abbreviations or assumptions
5. Industry should be a standard category (SaaS, Fintech, HealthTech, etc.)
6. Company size must be ONE of: startup, smb, enterprise, unknown
7. Intent taxonomy: buy | evaluate | pain | compare | other
8. Urgency: high (active within 7 days) | medium (within 30 days) | low

RULE 9 (Most Important): Conservative bias. It is better to miss a lead
than to report a false positive. A false positive wastes a salesperson's
time and trains them to distrust the system.

OUTPUT FORMAT (JSON only, no markdown):
{{
  "is_opportunity": <boolean>,
  "confidence": <float 0.0-1.0>,
  "intent": "<buy|evaluate|pain|compare|other>",
  "urgency": "<high|medium|low>",
  "reason": "<one sentence explanation>",
  "company_name": "<string or null>",
  "company_size": "<startup|smb|enterprise|unknown>",
  "industry": "<string or null>",
  "contact_name": "<string or null>",
  "contact_title": "<string or null>",
  "icp_fit_score": <int 0-100>,
  "outreach_draft": "<string or null>"
}}
"""

    # Mode-specific additions
    mode_context = ""
    if mode == "hiring":
        mode_context = """
MODE: HIRING INTELLIGENCE
Focus on: open positions, team growth, funding stage, tech stack mentioned.
is_opportunity = true if: active hiring signal, scaling team, Series A+ funding.
"""
    elif mode == "job_search":
        mode_context = """
MODE: JOB SEARCH
Focus on: job title, remote/onsite, salary range, required skills.
is_opportunity = true if: genuine open role, clear requirements, legitimate company.
"""
    elif mode == "opportunity":
        mode_context = """
MODE: MARKET OPPORTUNITY
Focus on: pain points, gaps in market, underserved segments.
is_opportunity = true if: repeated pain mentions, no good solution exists, growing demand.
"""

    # Combine all layers
    full_prompt = f"""{persona_block}

{source_prompt}
{signals_block}
{mode_context}
{extraction_rules}

INPUT DATA:
Source: {source}
Author: {author or 'Unknown'}
Text: {text[:8000]}

OUTPUT (JSON only, no markdown):"""
    return full_prompt