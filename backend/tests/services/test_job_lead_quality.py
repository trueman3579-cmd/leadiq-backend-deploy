"""
Tests for job lead quality classifier — deterministic scoring, cosine sim, sections.
"""
from __future__ import annotations

import pytest

from backend.services.job_lead_quality import (
    cosine_similarity,
    extract_sections,
    score_lead_deterministic,
    score_lead_multivector,
    normalize_llm_json,
    clean_llm_output,
)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_partial_match(self):
        a = [1.0, 1.0]
        b = [1.0, 0.0]
        sim = cosine_similarity(a, b)
        assert 0 < sim < 1


class TestExtractSections:
    def test_extracts_headings_and_paragraphs(self):
        html = "<body><h1>Title</h1><p>First paragraph.</p><h2>Section</h2><p>Second paragraph.</p></body>"
        sections = extract_sections(html)
        assert len(sections) == 4
        assert sections[0]["tag"] == "h1"
        assert sections[1]["tag"] == "p"
        assert sections[2]["tag"] == "h2"
        assert sections[3]["tag"] == "p"

    def test_section_ids(self):
        html = "<body><h1>A</h1><p>B</p><p>C</p><h2>D</h2><p>E</p></body>"
        sections = extract_sections(html)
        assert sections[0]["id"] == "1-0"
        assert sections[1]["id"] == "1-1"
        assert sections[2]["id"] == "1-2"
        assert sections[3]["id"] == "2-0"
        assert sections[4]["id"] == "2-1"

    def test_sentence_splitting(self):
        html = "<body><p>First sentence. Second sentence! Third?</p></body>"
        sections = extract_sections(html)
        assert len(sections[0]["sentences"]) == 3

    def test_empty_body(self):
        sections = extract_sections("")
        assert sections == []


class TestScoreLeadDeterministic:
    def test_web_dev_role_scores_high(self):
        score = score_lead_deterministic(
            title="Frontend React Developer",
            body="We are looking for a React developer with JavaScript experience.",
            company="Tech Corp",
        )
        assert score.role_match_score > 0.3
        assert "role_match" in score.reason_codes

    def test_apply_signals_detected(self):
        score = score_lead_deterministic(
            title="Developer",
            body="Click Apply Now to submit your application. Immediate urgent joining available.",
        )
        assert score.application_live_score > 0.3
        assert "application_live" in score.reason_codes

    def test_relevant_skills_boost(self):
        score = score_lead_deterministic(
            title="Developer",
            body="Some description",
            skills=["react", "javascript", "python"],
        )
        assert "relevant_skills" in score.reason_codes
        assert score.role_match_score > 0

    def test_non_relevant_scores_low(self):
        score = score_lead_deterministic(
            title="Accountant",
            body="We need an accountant with CA experience.",
            company="Finance Co",
        )
        assert score.role_match_score < 0.3
        assert score.company_signal_score < 0.3


class TestScoreLeadMultivector:
    def test_max_aggregation(self):
        query_vec = [1.0, 0.0, 0.0]
        lead_vecs = {
            "title": [1.0, 0.0, 0.0],
            "company": [0.0, 0.0, 0.0],
            "description": [0.5, 0.86, 0.0],
        }
        result = score_lead_multivector(query_vec, lead_vecs)
        assert result["max_score"] == pytest.approx(1.0)
        assert result["per_field"]["title"] == pytest.approx(1.0)
        assert result["per_field"]["company"] == pytest.approx(0.0)

    def test_weighted_aggregation(self):
        query_vec = [1.0, 0.0]
        lead_vecs = {
            "title": [1.0, 0.0],
            "company": [0.0, 0.0],
        }
        result = score_lead_multivector(query_vec, lead_vecs, weights={"title": 0.7, "company": 0.3})
        assert result["weighted_score"] == pytest.approx(0.7)

    def test_empty_vectors(self):
        result = score_lead_multivector([1.0], {})
        assert result["max_score"] == 0.0


class TestNormalizeLLMJson:
    def test_normalizes_unquoted_keys(self):
        raw = '{name: "John", age: 30}'
        result = normalize_llm_json(raw)
        assert result == {"name": "John", "age": 30}

    def test_removes_special_tokens(self):
        raw = '<|end_of_text|>{"score": 0.9}'
        result = normalize_llm_json(raw)
        assert result == {"score": 0.9}

    def test_returns_empty_on_invalid(self):
        result = normalize_llm_json("not json at all")
        assert result == {}


class TestCleanLLMOutput:
    def test_removes_tool_call_tags(self):
        text = 'Hello<tool_call>{"fn": "test"}<tool_call|>World'
        result = clean_llm_output(text)
        assert "tool_call" not in result

    def test_removes_end_token(self):
        text = "Hello<|end_of_text|> World"
        result = clean_llm_output(text)
        assert result == "Hello World"
