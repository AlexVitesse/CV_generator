"""Tests de validation.py: parse_cv y modelos de respuesta del LLM (V2-08)."""

import pytest

from validation import (
    parse_cv,
    validate_email,
    validate_linkedin,
    VacancyAnalysisResponse,
    DetailedEvalResponse,
    BankSelectionResponse,
)
from pydantic import ValidationError


# ── parse_cv ─────────────────────────────────────────────────────

def test_parse_cv_valid_minimal():
    norm, issues = parse_cv({"name": "Ada", "email": "ada@example.com"})
    assert norm["name"] == "Ada"
    assert "email" not in issues


def test_parse_cv_normalizes_string_skills():
    norm, _ = parse_cv({"name": "Ada", "skills": ["Python", "Rust"]})
    assert all(isinstance(s, dict) and "id" in s for s in norm["skills"])
    assert [s["text"] for s in norm["skills"]] == ["Python", "Rust"]


def test_parse_cv_flags_bad_email():
    _, issues = parse_cv({"name": "Ada", "email": "not-an-email"})
    assert "email" in issues


def test_parse_cv_ensures_list_fields():
    norm, _ = parse_cv({"name": "Ada"})
    for key in ("experiences", "education", "projects", "skills"):
        assert isinstance(norm[key], list)


# ── Validadores de formato ───────────────────────────────────────

def test_validate_email():
    assert validate_email("a@b.com")
    assert not validate_email("a@@b")
    assert validate_email("")  # vacío = no se valida


def test_validate_linkedin_hostname():
    assert validate_linkedin("https://www.linkedin.com/in/ada")
    assert validate_linkedin("linkedin.com/in/ada")
    # No debe aceptar dominios que solo contienen el substring.
    assert not validate_linkedin("https://notalinkedin.com/in/x")


# ── Modelos de respuesta del LLM ─────────────────────────────────

def test_vacancy_analysis_accepts_valid():
    m = VacancyAnalysisResponse.model_validate({
        "match_score": 75, "viable": True,
        "matching_keywords": ["python"], "missing_keywords": [],
        "suggestions": {}, "reasoning": "ok",
    })
    assert m.match_score == 75


def test_vacancy_analysis_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        VacancyAnalysisResponse.model_validate({"match_score": 150})


def test_vacancy_analysis_rejects_missing_score():
    with pytest.raises(ValidationError):
        VacancyAnalysisResponse.model_validate({"viable": True})


def test_vacancy_analysis_coerces_numeric_string():
    m = VacancyAnalysisResponse.model_validate({"match_score": "88"})
    assert m.match_score == 88


def test_detailed_eval_defaults():
    m = DetailedEvalResponse.model_validate({"overall_score": 60})
    assert m.dimensions == [] and m.verdicts == []


def test_bank_selection_defaults_empty():
    m = BankSelectionResponse.model_validate({})
    assert m.selected_ids == []
