"""Tests de los guards anti-fabricación: métricas (#1), tier de skills (#2),
reconciliación de viabilidad (#3). Cubren los casos reales vistos en logs/."""

from metrics_guard import extract_metrics, find_fabricated_metrics
from helpers import (
    sanitize_ai_result,
    _enforce_skill_tiers,
    _demote_missing_keyword_skills,
)


# ── #1 — extract_metrics ─────────────────────────────────────────

def test_extract_metrics_captures_pct_and_thousands():
    mets = {m["key"] for m in extract_metrics("logró 99.5% sobre 1,200 solicitudes diarias")}
    assert "995" in mets and "1200" in mets


def test_extract_metrics_ignores_lone_small_digits():
    # "3 fases" / "4 servicios" son conteos estructurales, no métricas de impacto.
    keys = {m["key"] for m in extract_metrics("entregó 4 servicios en 3 fases")}
    assert keys == set()


def test_extract_metrics_keeps_single_digit_percent():
    mets = extract_metrics("precisión de ±1%")
    assert any(m["key"] == "1" and m["is_pct"] for m in mets)


# ── #1 — find_fabricated_metrics ─────────────────────────────────

_CV = {
    "summary": "AI Engineer",
    "experiences": [
        {"company": "ZAPI", "title": "Founder",
         "bullets": "Construyó agente con 89% en benchmark y 99% de uptime."},
        {"company": "Cóndor", "title": "Backend",
         "bullets": "APIs en FastAPI procesando 1,200+ solicitudes diarias."},
    ],
    "projects": [
        {"name": "ZAPI", "description": "SaaS con ~15,000 líneas de código."},
    ],
    "skills": [],
}


def test_detects_transplanted_metric_across_items():
    # La métrica 1,200/día es de Cóndor (index 1); aquí aparece bajo ZAPI (index 0).
    suggestions = {"experiences": [
        {"index": 0, "title": "Founder",
         "bullets": "Construyó plataforma procesando 1,200 solicitudes diarias."},
    ]}
    offenders = find_fabricated_metrics(suggestions, _CV)
    assert any(o["metric"].startswith("1,200") and o["index"] == 0 for o in offenders)


def test_detects_invented_percentage():
    suggestions = {"experiences": [
        {"index": 1, "title": "Backend",
         "bullets": "Implementó pruebas reduciendo regresiones en 30%."},
    ]}
    offenders = find_fabricated_metrics(suggestions, _CV)
    assert any(o["metric"] == "30%" for o in offenders)


def test_real_metric_in_same_item_is_clean():
    suggestions = {"experiences": [
        {"index": 0, "title": "Founder",
         "bullets": "Construyó agente con 89% en benchmark."},
    ]}
    assert find_fabricated_metrics(suggestions, _CV) == []


def test_summary_metric_checked_against_whole_cv():
    suggestions = {"summary": "AI Engineer con 5,000 despliegues."}  # 5000 no está en el CV
    offenders = find_fabricated_metrics(suggestions, _CV)
    assert any(o["kind"] == "summary" for o in offenders)


# ── #2 — tier de skills ──────────────────────────────────────────

def test_inferred_skill_goes_to_lowest_tier():
    original = ["Dominio avanzado: Python | Dominio intermedio: SQL | Familiaridad: Make"]
    # La IA mete "Docker" (nueva, inferida) en avanzado → debe bajar a familiaridad.
    suggested = "Dominio avanzado: Python, Docker | Dominio intermedio: SQL | Familiaridad: Make"
    out = _enforce_skill_tiers(suggested, original)
    assert "Docker" in out.split("Familiaridad:")[1]
    assert "Docker" not in out.split("|")[0]  # ya no en avanzado


def test_missing_keyword_skill_demoted():
    suggested = "Core skills: Python | Working knowledge: Next.js | Exposure to: Make"
    out = _demote_missing_keyword_skills(suggested, ["Next.js (solid experience)"])
    assert "Next.js" in out.split("Exposure to:")[1]
    assert "Working knowledge: Next.js" not in out  # ya no en working knowledge


# ── #3 — reconciliación de viabilidad ────────────────────────────

def test_high_score_forces_viable_true():
    res = sanitize_ai_result({"match_score": 78, "viable": False, "suggestions": {}})
    assert res["viable"] is True


def test_low_score_forces_viable_false():
    res = sanitize_ai_result({"match_score": 35, "viable": True, "suggestions": {}})
    assert res["viable"] is False


def test_mid_score_respects_model_judgment():
    res = sanitize_ai_result({"match_score": 60, "viable": True, "suggestions": {}})
    assert res["viable"] is True
    res2 = sanitize_ai_result({"match_score": 58, "viable": False, "suggestions": {}})
    assert res2["viable"] is False
