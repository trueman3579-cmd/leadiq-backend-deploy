import pytest

from backend.llm.schemas import AnalyzedLead
from backend.workers.analyzer import GeminiAnalyzer


@pytest.mark.asyncio
async def test_analyzer_heuristic_fallback():
    analyzer = GeminiAnalyzer()
    # Force fallback path by not configuring credentials in test environment
    result = await analyzer.analyze("We need a better analytics platform ASAP", source="reddit", author="founder123")

    assert isinstance(result, AnalyzedLead)
    assert result.intent in {"buy", "pain", "other", "evaluate", "compare"}
    assert 0.0 <= result.confidence <= 1.0
