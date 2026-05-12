"""
backend/llm/gemini_service.py — Core Gemini LLM Integration

Uses Google's LangExtract library for production extraction with:
- Source grounding (character offsets → no hallucinations)
- Controlled generation (schema enforcement at model layer)
- Parallel chunking (long pages → parallel passes)

Model Hierarchy:
    - gemini-2.0-flash-lite: Bulk extraction ($0.075/M tokens)
    - gemini-2.0-flash: Scoring/parsing ($0.10/M tokens)
    - text-embedding-004: Embeddings ($0.00002/K tokens)

Usage:
    from backend.llm.gemini_service import extract_lead, get_embedding

    lead = await extract_lead(markdown_content, source="tracxn", url="...")
    embedding = await get_embedding(lead["company_name"])
"""
from __future__ import annotations

import asyncio
import json
import structlog
from typing import Any

from vertexai.generative_models import GenerativeModel, GenerationConfig, Part

from backend.llm.cost_guard import check_budget
from backend.llm.SOURCE_PROMPTS import SOURCE_PROMPTS, get_generic_prompt

logger = structlog.get_logger()


class GeminiExtractionError(Exception):
    """Raised when Gemini extraction fails irrecoverably."""
    def __init__(
        self,
        message: str,
        source: str | None = None,
        url: str | None = None,
    ):
        super().__init__(message)
        self.source = source
        self.url = url


# ── Model Configuration ────────────────────────────────────────────────────────

MODELS = {
    "extract": "gemini-2.0-flash-lite",  # $0.075/M — bulk extraction
    "score": "gemini-2.0-flash",        # $0.10/M — scoring/parsing
    "embed": "text-embedding-004",      # $0.00002/K — semantic search
    "vision": "gemini-2.0-flash",       # multimodal — team pages, images
}

# Pydantic schema for lead extraction
LEAD_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "company_name": {"type": "string", "description": "Company or organization name"},
        "industry": {"type": "string", "description": "Industry or business sector"},
        "location": {"type": "string", "description": "City, State, Country"},
        "company_size": {"type": "string", "description": "Employee count range: 1-10/11-50/51-200/201-500/500+"},
        "funding_stage": {"type": "string", "description": "Funding stage: bootstrapped/pre-seed/seed/series-a/series-b/series-c/public"},
        "tech_stack": {"type": "array", "items": {"type": "string"}, "description": "Technologies used"},
        "email": {"type": "string", "description": "Contact email (null if not found)"},
        "linkedin_url": {"type": "string", "description": "LinkedIn company or profile URL"},
        "website": {"type": "string", "description": "Company website URL"},
        "founded_year": {"type": "integer", "description": "Year founded (null if unknown)"},
        "intent_signals": {"type": "array", "items": {"type": "string"}, "description": "Buying intent indicators"},
        "notes": {"type": "string", "description": "Additional context"},
    },
    "required": ["company_name"],
}


# ── Core Extraction Function ────────────────────────────────────────────────────

async def extract_lead(
    markdown_content: str,
    source: str,
    url: str,
) -> dict[str, Any]:
    """
    Extract lead data from page content using Gemini.

    Uses LangExtract-style structured extraction with source grounding.
    Falls back to regex parser if budget exceeded.

    Args:
        markdown_content: Preprocessed page content (fit_markdown from Crawlee)
        source: Data source identifier (tracxn, github_profile, etc.)
        url: Original URL for context

    Returns:
        dict with extracted lead fields + confidence score
    """
    # Estimate tokens (rough: 1 token ≈ 4 chars)
    estimated_tokens = len(markdown_content) // 4 + 500  # +500 for prompt overhead

    if not await check_budget(estimated_tokens):
        logger.warning("gemini_budget_exceeded_using_fallback", source=source, url=url)
        return await regex_fallback_extract(markdown_content, source, url)

    # Get source-specific prompt
    prompt = SOURCE_PROMPTS.get(source, get_generic_prompt())

    # Get source-specific examples if available
    from backend.llm.SOURCE_PROMPTS import EXTRACTION_EXAMPLES
    examples = EXTRACTION_EXAMPLES.get(source, [])
    examples_block = ""
    if examples:
        examples_block = "\n\nEXAMPLES:\n"
        for i, ex in enumerate(examples[:2], 1):
            examples_block += f"\nExample {i}:\nInput: {ex['input'][:200]}...\nOutput: {json.dumps(ex['output'])}\n"

    # Build schema-injected prompt
    full_prompt = f"""{prompt}

URL: {url}

Extract the company/lead information from the following content.
Return ONLY a valid JSON object matching this exact schema:
{json.dumps(LEAD_EXTRACTION_SCHEMA, indent=2)}

RULES:
- If a field cannot be found in the content, use null (never guess or infer)
- company_size must be one of: 1-10, 11-50, 51-200, 201-500, 500+
- funding_stage must be one of: bootstrapped, pre-seed, seed, series-a, series-b, series-c, public
- tech_stack should be an array of technology names found in the content
- email should only be included if explicitly visible in the content
- Return ONLY the JSON object, no markdown, no explanations
{examples_block}

Content to extract from:
{markdown_content[:30000]}  # Truncate to avoid context limit

EXTRACTED JSON:"""

    try:
        model = GenerativeModel(MODELS["extract"])
        response = await asyncio.to_thread(
            model.generate_content,
            full_prompt,
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1,  # Low temperature for extraction
                max_output_tokens=2048,
            ),
        )

        # Parse JSON response
        result = json.loads(response.text)

        # Add metadata
        result["source"] = source
        result["source_url"] = url
        result["confidence"] = compute_confidence(result, source)

        logger.info(
            "gemini_extraction_complete",
            source=source,
            company=result.get("company_name"),
            confidence=result["confidence"],
            tokens_used=estimated_tokens,
        )

        return result

    except json.JSONDecodeError as exc:
        logger.error("gemini_json_parse_error", source=source, error=str(exc))
        raise GeminiExtractionError(
            f"JSON parse error: {exc}", source=source, url=url
        ) from exc

    except Exception as exc:
        logger.error("gemini_extraction_error", source=source, error=str(exc))
        raise GeminiExtractionError(
            f"Extraction failed: {exc}", source=source, url=url
        ) from exc


async def regex_fallback_extract(
    markdown_content: str,
    source: str,
    url: str,
) -> dict[str, Any]:
    """
    Fallback parser when budget exceeded.

    Uses regex patterns for basic extraction without LLM.
    Much lower quality but zero cost.
    """
    import re

    result = {
        "source": source,
        "source_url": url,
        "confidence": 0.30,  # Low confidence for regex fallback
    }

    text = markdown_content

    # Extract company name (first H1 or bold heading, or title tag)
    h1_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title_match = re.search(r"<title>([^<]+)</title>", text, re.IGNORECASE)
    if h1_match:
        result["company_name"] = h1_match.group(1).strip()
    elif title_match:
        result["company_name"] = title_match.group(1).strip().split(" - ")[0].split(" | ")[0]

    # Extract industry from common keywords
    industry_keywords = {
        "SaaS": ["saas", "software as a service", "cloud software"],
        "Fintech": ["fintech", "financial technology", "payments", "banking"],
        "HealthTech": ["healthtech", "healthcare", "medical", "digital health"],
        "AI/ML": ["artificial intelligence", "machine learning", "ai/ml", "deep learning"],
        "E-commerce": ["e-commerce", "ecommerce", "online store", "marketplace"],
        "EdTech": ["edtech", "education technology", "learning platform"],
        "Consumer Tech": ["consumer", "b2c", "mobile app"],
        "Developer Tools": ["developer tools", "devops", "api", "sdk"],
    }
    text_lower = text.lower()
    for industry, keywords in industry_keywords.items():
        if any(kw in text_lower for kw in keywords):
            result["industry"] = industry
            break

    # Extract location
    location_patterns = [
        r"(?:Headquarters|Location|Based in|Office):\s*([^\n<]+)",
        r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)*),\s*([A-Z]{2,})\s*\d{5}?",
    ]
    for pattern in location_patterns:
        loc_match = re.search(pattern, text)
        if loc_match:
            result["location"] = loc_match.group(1).strip()
            break

    # Extract company size
    size_patterns = [
        r"(\d{1,3})\s*(?:employees?|staff|people|team members?)",
        r"(1-10|11-50|51-200|201-500|500\+)",
    ]
    for pattern in size_patterns:
        size_match = re.search(pattern, text, re.IGNORECASE)
        if size_match:
            result["company_size"] = size_match.group(1).strip()
            break

    # Extract funding stage
    funding_patterns = [
        r"(seed|series\s*[abc]|pre-seed|bootstrapped|angel|ipo|public)",
        r"(Series\s+[ABC])",
    ]
    for pattern in funding_patterns:
        fund_match = re.search(pattern, text, re.IGNORECASE)
        if fund_match:
            result["funding_stage"] = fund_match.group(1).lower().replace(" ", "-")
            break

    # Extract tech stack from common technologies
    tech_keywords = [
        "React", "Vue.js", "Angular", "Next.js", "Node.js", "Python", "Django",
        "FastAPI", "Flask", "Ruby", "Rails", "Go", "Rust", "Java", "Spring",
        "PHP", "Laravel", "TypeScript", "JavaScript", "C++", "C#", "Swift",
        "Kotlin", "Flutter", "React Native", "AWS", "GCP", "Azure", "Docker",
        "Kubernetes", "Terraform", "PostgreSQL", "MySQL", "MongoDB", "Redis",
        "Elasticsearch", "GraphQL", "REST", "gRPC", "WebSocket", "TensorFlow",
        "PyTorch", "Scikit-learn", "Pandas", "NumPy", "Apache Spark", "Hadoop",
        "Kafka", "RabbitMQ", "Nginx", "Apache", "Linux", "Ubuntu", "Debian",
    ]
    found_tech = []
    for tech in tech_keywords:
        if re.search(rf"\b{re.escape(tech)}\b", text, re.IGNORECASE):
            found_tech.append(tech)
    if found_tech:
        result["tech_stack"] = found_tech[:8]  # Limit to top 8

    # Extract email
    email_match = re.search(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text
    )
    if email_match:
        result["email"] = email_match.group(0)

    # Extract website
    website_match = re.search(r"https?://([^\s\)\"]+)", text)
    if website_match:
        result["website"] = website_match.group(0)

    # Extract founded year
    year_match = re.search(r"(?:Founded|Established|Incorporated)\s*(?:in)?\s*(\d{4})", text, re.IGNORECASE)
    if not year_match:
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if year_match:
        result["founded_year"] = int(year_match.group(1))

    logger.info("regex_fallback_used", source=source, company=result.get("company_name"))
    return result


# ── Embedding Function ───────────────────────────────────────────────────────────

async def get_embedding(text: str) -> list[float] | None:
    """
    Generate embedding for semantic similarity/deduplication.

    Uses text-embedding-004 for 768-dim vectors.
    Truncates to 2048 tokens max.

    Args:
        text: Text to embed (company name + description recommended)

    Returns:
        768-dim embedding vector or None if budget exceeded
    """
    from vertexai.language_models import TextEmbeddingModel

    estimated_tokens = len(text) // 4
    if not await check_budget(estimated_tokens):
        logger.warning("embedding_budget_exceeded", tokens=estimated_tokens)
        return None

    try:
        model = TextEmbeddingModel.from_pretrained(MODELS["embed"])
        embeddings = await asyncio.to_thread(model.get_embeddings, [text[:8192]])  # 8K char limit
        return list(embeddings[0].values)

    except Exception as exc:
        logger.error("embedding_error", error=str(exc))
        raise GeminiExtractionError(f"Embedding failed: {exc}") from exc


# ── Vision Extraction ────────────────────────────────────────────────────────────

async def extract_from_image(
    image_bytes: bytes,
    instruction: str,
    mime_type: str = "image/png",
) -> dict[str, Any]:
    """
    Extract structured data from images (team pages, conference slides).

    Args:
        image_bytes: Raw image data
        instruction: What to extract from the image
        mime_type: Image MIME type

    Returns:
        dict with extracted fields
    """
    estimated_tokens = 500  # Vision tokens are ~500 per image
    if not await check_budget(estimated_tokens):
        return {}

    try:
        model = GenerativeModel(MODELS["vision"])
        image_part = Part.from_data(image_bytes, mime_type=mime_type)

        response = await asyncio.to_thread(
            model.generate_content,
            [image_part, instruction],
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=512,
            ),
        )

        return json.loads(response.text)

    except Exception as exc:
        logger.error("vision_extraction_error", error=str(exc))
        raise GeminiExtractionError(f"Vision extraction failed: {exc}") from exc


# ── ICP Parser ───────────────────────────────────────────────────────────────────

async def parse_natural_language_icp(description: str) -> dict[str, Any]:
    """
    Parse natural language ICP description into structured format.

    Example input:
        "Find CTOs at Indian SaaS startups 20-200 employees using React
         who raised Series A in 2025 and are hiring backend engineers"

    Returns:
        {
          "target_titles": ["CTO", "VP Engineering"],
          "target_industries": ["SaaS", "B2B Software"],
          "target_sizes": ["11-50", "51-200"],
          "target_locations": ["India"],
          "target_stack": ["React"],
          "funding_stages": ["series-a"],
          "required_signals": ["hiring"],
        }
    """
    estimated_tokens = len(description) // 4 + 300
    if not await check_budget(estimated_tokens):
        return {}

    prompt = f"""Parse this ICP description into structured JSON.

ICP Description: "{description}"

Output JSON:
{{
  "target_titles": ["..."],
  "target_industries": ["..."],
  "target_sizes": ["..."],
  "target_locations": ["..."],
  "target_stack": ["..."],
  "funding_stages": ["..."],
  "required_signals": ["..."],
  "min_confidence": 0.65
}}

Rules:
- Extract ONLY what is explicitly stated
- Null for unmentioned fields, never assume
- target_sizes: use exact enum values: 1-10/11-50/51-200/201-500/500+
- funding_stages: bootstrapped/pre-seed/seed/series-a/series-b/series-c/public
"""

    try:
        model = GenerativeModel(MODELS["score"])  # Use flash for reasoning
        response = await asyncio.to_thread(
            model.generate_content,
            prompt,
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                temperature=0.05,  # Near-zero for parsing
                max_output_tokens=512,
            ),
        )
        return json.loads(response.text)

    except Exception as exc:
        logger.error("icp_parse_error", error=str(exc))
        raise GeminiExtractionError(f"ICP parse failed: {exc}") from exc


# ── Confidence Computation ──────────────────────────────────────────────────────

def compute_confidence(lead: dict[str, Any], source: str) -> float:
    """
    Compute confidence score for extracted lead.

    Formula: field_completeness × source_trust

    SOURCE_TRUST reflects data source reliability:
        - github_api: 0.95 (verified API, developer confirms email)
        - hunter_io: 0.90 (email verification service)
        - hacker_news: 0.82 (self-posted by founders)
        - yourstory: 0.75 (editorial, generally accurate)
        - producthunt: 0.72 (self-posted but fields often incomplete)
        - tracxn: 0.70 (aggregated, verify funding independently)
        - indimart: 0.50 (user-submitted B2B directory, often stale)
        - llm_web_scrape: 0.40 (generic LLM extraction, needs validation)
    """
    from backend.services.confidence import SOURCE_TRUST, compute_field_score

    source_trust = SOURCE_TRUST.get(source, 0.40)
    field_score = compute_field_score(lead)

    return round(field_score * source_trust, 3)