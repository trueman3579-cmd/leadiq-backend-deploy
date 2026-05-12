"""
api/routes/nlp.py — NLP analysis endpoints (Phase 7).

POST /api/nlp/sentiment      → Sentiment analysis
POST /api/nlp/topics         → Topic modeling
POST /api/nlp/entities       → Named entity extraction
POST /api/nlp/intent         → Intent classification
POST /api/nlp/semantic-search → Semantic document search
"""
from __future__ import annotations

import logging
from typing import List, Tuple

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.services.nlp_analyzer import get_analyzer, SentimentResult, TopicResult, EntityResult, IntentResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nlp", tags=["nlp"])


# ── Schemas ─────────────────────────────────────────────────────────────────

class SentimentRequest(BaseModel):
    text: str

class SentimentResponse(BaseModel):
    label: str
    score: float
    confidence: float
    breakdown: dict

class TopicsRequest(BaseModel):
    documents: List[Tuple[str, str]] = Field(description="List of (id, text) tuples")
    n_topics: int = Field(5, ge=1, le=20)

class TopicsResponse(BaseModel):
    topics: List[dict]
    total_documents: int

class EntitiesRequest(BaseModel):
    text: str

class EntitiesResponse(BaseModel):
    entities: List[dict]

class IntentRequest(BaseModel):
    text: str

class IntentResponse(BaseModel):
    intent: str
    confidence: float
    scores: dict

class SemanticSearchRequest(BaseModel):
    query: str
    documents: List[Tuple[str, str]] = Field(description="List of (id, text) tuples")
    top_k: int = Field(5, ge=1, le=50)

class SemanticSearchResponse(BaseModel):
    results: List[dict]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/sentiment", response_model=SentimentResponse)
async def analyze_sentiment(body: SentimentRequest):
    """Analyze text sentiment using embedding-space similarity."""
    analyzer = get_analyzer()
    result = analyzer.sentiment(body.text)
    return SentimentResponse(
        label=result.label,
        score=result.score,
        confidence=result.confidence,
        breakdown=result.breakdown,
    )


@router.post("/topics", response_model=TopicsResponse)
async def extract_topics(body: TopicsRequest):
    """Extract topics from documents using k-means clustering on embeddings."""
    analyzer = get_analyzer()
    topics = analyzer.topics(body.documents, n_topics=body.n_topics)
    return TopicsResponse(
        topics=[
            {
                "topic_id": t.topic_id,
                "label": t.label,
                "keywords": t.keywords,
                "document_count": len(t.document_ids),
            }
            for t in topics
        ],
        total_documents=len(body.documents),
    )


@router.post("/entities", response_model=EntitiesResponse)
async def extract_entities(body: EntitiesRequest):
    """Extract named entities using pattern matching + LLM fallback."""
    analyzer = get_analyzer()
    entities = await analyzer.extract_entities(body.text)
    return EntitiesResponse(
        entities=[
            {"text": e.text, "type": e.type, "confidence": e.confidence, "source": e.source}
            for e in entities
        ]
    )


@router.post("/intent", response_model=IntentResponse)
async def classify_intent(body: IntentRequest):
    """Classify user intent using embedding similarity."""
    analyzer = get_analyzer()
    result = analyzer.intent(body.text)
    return IntentResponse(
        intent=result.intent,
        confidence=result.confidence,
        scores=result.scores,
    )


@router.post("/semantic-search", response_model=SemanticSearchResponse)
async def semantic_search(body: SemanticSearchRequest):
    """Search documents by semantic similarity to query."""
    analyzer = get_analyzer()
    results = analyzer.semantic_search(body.query, body.documents, top_k=body.top_k)
    return SemanticSearchResponse(
        results=[
            {"id": doc_id, "score": round(score, 4)}
            for doc_id, score in results
        ]
    )
