from backend.workers.scorer import ScoringInput, score_opportunity


def test_score_opportunity_hot():
    inp = ScoringInput(
        is_opportunity=True,
        confidence=0.92,
        intent="buy",
        urgency="high",
        icp_fit_score=88,
        engagement=0.75,
    )
    result = score_opportunity(inp)
    assert result.final_score >= 80
    assert result.score_band == "hot"


def test_score_opportunity_cold_when_not_opportunity():
    inp = ScoringInput(
        is_opportunity=False,
        confidence=0.9,
        intent="buy",
        urgency="high",
        icp_fit_score=95,
        engagement=1.0,
    )
    result = score_opportunity(inp)
    assert result.final_score == 0.0
    assert result.score_band == "cold"
