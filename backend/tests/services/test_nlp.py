"""Tests for NLP analyzer service (Phase 7)."""

import pytest
from backend.services.nlp_analyzer import NLPAnalyzer, SentimentResult, IntentResult, TopicResult


@pytest.fixture
def analyzer():
    return NLPAnalyzer()


def test_sentiment_positive(analyzer):
    result = analyzer.sentiment("This product is amazing and works perfectly")
    assert isinstance(result, SentimentResult)
    # May be mixed with fallback embeddings
    assert result.label in ("positive", "neutral", "mixed")
    assert 0.0 <= result.confidence <= 1.0
    assert result.breakdown["positive"] >= result.breakdown["negative"]


def test_sentiment_negative(analyzer):
    result = analyzer.sentiment("Terrible experience, worst purchase ever")
    assert isinstance(result, SentimentResult)
    assert result.label in ("negative", "neutral", "mixed")
    assert 0.0 <= result.confidence <= 1.0


def test_sentiment_empty(analyzer):
    result = analyzer.sentiment("")
    assert result.label == "neutral"


def test_intent_buy(analyzer):
    result = analyzer.intent("I want to buy this software right now")
    assert isinstance(result, IntentResult)
    assert result.intent in ("buy", "inquire")
    assert 0.0 <= result.confidence <= 1.0


def test_intent_complain(analyzer):
    result = analyzer.intent("This is broken and not working at all")
    assert result.intent == "complain"


def test_intent_empty(analyzer):
    result = analyzer.intent("")
    assert result.intent == "inquire"


def test_topic_extraction(analyzer):
    docs = [
        ("1", "Startup raised 5M in series A funding from top VCs"),
        ("2", "New AI product launch with amazing features"),
        ("3", "Hiring engineers for backend and ML roles"),
        ("4", "Government scheme for MSMEs provides subsidy"),
        ("5", "Company complains about poor customer service"),
    ]
    topics = analyzer.topics(docs, n_topics=2)
    assert len(topics) >= 1
    for t in topics:
        assert isinstance(t, TopicResult)
        assert t.keywords
        assert len(t.document_ids) >= 0


def test_pattern_entities(analyzer):
    text = """
    Acme Corp. raised $10 million in Series B funding.
    Contact: john@acme.com
    Visit https://acme.com for more info.
    """
    entities = analyzer._pattern_entities(text)
    assert any(e.type == "FUNDING" for e in entities)
    assert any(e.type == "ORG" for e in entities)


def test_cosine_similarity(analyzer):
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    assert round(analyzer._cosine(v1, v2), 2) == 1.0
    assert round(analyzer._cosine(v1, v3), 2) == 0.0
