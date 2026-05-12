"""
job_lead_quality.py — Deterministic pre-LLM lead quality scoring.

Merged from gemma4-browser-extension algorithms:
- cosine_similarity (askWebsite.ts:113-129)
- max-pooled sentence scoring (askWebsite.ts:131-166)
- multi-vector aggregation (VectorHistory.ts:113-170)
- section extraction (extractWebsiteParts.ts:4-42)
- LLM output normalizer (extractToolCalls.ts:3-13)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from bs4 import BeautifulSoup


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    a, b = np.array(vec_a, dtype=np.float64), np.array(vec_b, dtype=np.float64)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def extract_sections(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("main") or soup.find("body") or soup
    elements = root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p"])
    sections = []
    current_section_id = 0
    current_part_id = 0
    for el in elements:
        current_part_id += 1
        tag = el.name
        if re.match(r"^h[1-6]$", tag):
            current_section_id += 1
            current_part_id = 0
        content = el.get_text(strip=True)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", content) if s.strip()]
        sections.append({
            "tag": tag,
            "section_id": current_section_id,
            "paragraph_id": current_part_id,
            "id": f"{current_section_id}-{current_part_id}",
            "content": content,
            "sentences": sentences,
        })
    return sections


def embed_sections(sections: list[dict], embed_fn) -> list[dict]:
    for section in sections:
        if section["sentences"]:
            section["embeddings"] = embed_fn(section["sentences"])
        else:
            section["embeddings"] = []
    return sections


def score_sections(
    query_embedding: list[float],
    sections: list[dict[str, Any]],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    scored = []
    for section in sections:
        if not section.get("embeddings"):
            continue
        max_sim = max(
            cosine_similarity(query_embedding, sent_emb)
            for sent_emb in section["embeddings"]
        )
        scored.append({**section, "score": max_sim})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def score_lead_multivector(
    query_embedding: list[float],
    lead_vectors: dict[str, list[float]],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    scores = {}
    for field, vector in lead_vectors.items():
        if vector and any(v != 0.0 for v in vector):
            scores[field] = cosine_similarity(query_embedding, vector)
        else:
            scores[field] = 0.0
    max_score = max(scores.values()) if scores else 0.0
    if weights:
        total = sum(weights.get(f, 0) for f in scores)
        weighted = sum(scores.get(f, 0) * weights.get(f, 0) for f in scores) / total if total > 0 else 0.0
    else:
        weighted = max_score
    return {"per_field": scores, "max_score": max_score, "weighted_score": weighted}


@dataclass
class LeadQualityScore:
    role_match_score: float = 0.0
    company_signal_score: float = 0.0
    application_live_score: float = 0.0
    conversion_score: float = 0.0
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_match_score": self.role_match_score,
            "company_signal_score": self.company_signal_score,
            "application_live_score": self.application_live_score,
            "conversion_score": self.conversion_score,
            "reason_codes": self.reason_codes,
        }


QUALITY_QUERIES = [
    ("role_match", ["web developer", "frontend developer", "react developer", "full stack"]),
    ("company_signal", ["agency hiring", "company actively hiring", "growing team"]),
    ("application_live", ["apply now", "submit application", "easy apply", "start application"]),
    ("conversion", ["immediate joining", "urgent hiring", "quick apply", "direct hire"]),
]


def score_lead_deterministic(
    title: str,
    body: str,
    company: str = "",
    skills: list[str] | None = None,
) -> LeadQualityScore:
    text = f"{title} {body} {company}".lower()
    skills_text = " ".join(skills or []).lower()

    score = LeadQualityScore()

    role_keywords = ["web developer", "frontend", "react", "angular", "vue", "full stack", "javascript", "typescript"]
    score.role_match_score = min(1.0, sum(1 for kw in role_keywords if kw in text) / len(role_keywords))

    company_signals = ["agency", "it services", "consulting", "product company", "startup", "service based"]
    score.company_signal_score = min(1.0, sum(1 for s in company_signals if s in text) / len(company_signals))

    apply_signals = ["apply now", "submit application", "easy apply", "start application", "apply"]
    score.application_live_score = min(1.0, sum(1 for a in apply_signals if a in text) / len(apply_signals))

    conversion_signals = ["immediate", "urgent", "quick", "direct hire", "fast hire", "join now"]
    score.conversion_score = min(1.0, sum(1 for c in conversion_signals if c in text) / len(conversion_signals))

    reasons = []
    if score.role_match_score >= 0.3:
        reasons.append("role_match")
    if score.company_signal_score >= 0.3:
        reasons.append("company_signal")
    if score.application_live_score >= 0.3:
        reasons.append("application_live")
    if score.conversion_score >= 0.3:
        reasons.append("conversion_ready")
    if any(s in skills_text for s in ["react", "javascript", "typescript", "python", "node"]):
        reasons.append("relevant_skills")
        score.role_match_score = min(1.0, score.role_match_score + 0.2)
    score.reason_codes = reasons

    return score


def normalize_llm_json(raw: str) -> dict:
    cleaned = re.sub(r"<\|end_of_text\|>", "", raw)
    cleaned = re.sub(r"<\|.*?\|>", "", cleaned)
    cleaned = re.sub(r"([{,\s])([a-zA-Z_]\w*)\s*:", r'\1"\2":', cleaned)
    cleaned = cleaned.replace("'", '"')
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {}


def clean_llm_output(text: str) -> str:
    patterns = [
        r"<\|end_of_text\|>",
        r"<\|tool_response\>.*?<tool_response\|>",
        r"<tool_response>.*?</tool_response>",
        r"<\|tool_call\>.*?(?:<tool_call\|>|$)",
        r"<tool_call>.*?(?:</tool_call>|$)",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.DOTALL)
    return text.strip()
