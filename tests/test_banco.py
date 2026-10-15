"""Tests de banco.py — foco en merge_cv_to_bank por ID (V2-05).

La clase de regresión que estos tests blindan: el merge antiguo emparejaba la
i-ésima experiencia del CV con la i-ésima del banco. Si el usuario reordenaba,
eliminaba o insertaba experiencias en el tab Manual, los bullets editados
aterrizaban en la empresa equivocada y corrompían el banco.
"""

import copy

import pytest

from banco import (
    bank_to_active_cv,
    merge_cv_to_bank,
    toggle_item,
    count_bank_items,
    apply_ai_selection,
)


def _bank():
    """Banco mínimo con 3 experiencias, 2 proyectos y 2 skills, todo activo."""
    return {
        "_meta": {"version": 1},
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "summaries": [
            {"id": "sum_1", "label": "Principal", "text": "Resumen original", "active": True},
        ],
        "experiences": [
            {
                "id": "exp_a", "company": "Alpha", "title": "Dev", "location": "",
                "dates": "2020", "active": True,
                "bullets": [
                    {"id": "bul_a1", "text": "Alpha bullet 1", "tags": [], "active": True},
                    {"id": "bul_a2", "text": "Alpha bullet 2", "tags": [], "active": True},
                ],
            },
            {
                "id": "exp_b", "company": "Bravo", "title": "Eng", "location": "",
                "dates": "2021", "active": True,
                "bullets": [
                    {"id": "bul_b1", "text": "Bravo bullet 1", "tags": [], "active": True},
                ],
            },
            {
                "id": "exp_c", "company": "Charlie", "title": "Lead", "location": "",
                "dates": "2022", "active": True,
                "bullets": [
                    {"id": "bul_c1", "text": "Charlie bullet 1", "tags": [], "active": True},
                ],
            },
        ],
        "projects": [
            {"id": "proj_x", "name": "ProjX", "url": "", "description": "desc x", "tags": [], "active": True},
            {"id": "proj_y", "name": "ProjY", "url": "", "description": "desc y", "tags": [], "active": True},
        ],
        "education": [
            {"id": "edu_1", "institution": "Uni", "degree": "BSc", "details": "",
             "location": "", "date": "2019", "active": True},
        ],
        "skills": [
            {"id": "sk_1", "text": "Python", "tags": [], "active": True},
            {"id": "sk_2", "text": "Rust", "tags": [], "active": True},
        ],
        "certifications": [
            {"id": "cert_1", "text": "AWS Certified", "active": True},
            {"id": "cert_2", "text": "Oracle AI Foundations", "active": True},
        ],
    }


def _exp_by_id(bank, eid):
    return next(e for e in bank["experiences"] if e["id"] == eid)


# ── Merge: experiencias ──────────────────────────────────────────

def test_merge_updates_correct_experience_after_reorder():
    """Reordenar las experiencias en el CV no debe escribir en la equivocada."""
    bank = _bank()
    cv = bank_to_active_cv(bank)

    # El usuario reordena: Bravo pasa al frente y edita su título.
    cv["experiences"].reverse()  # [Charlie, Bravo, Alpha]
    bravo = next(e for e in cv["experiences"] if e["id"] == "exp_b")
    bravo["title"] = "Senior Engineer"
    bravo["bullets"] = "Bravo bullet EDITADO"

    merge_cv_to_bank(cv, bank)

    assert _exp_by_id(bank, "exp_b")["title"] == "Senior Engineer"
    assert _exp_by_id(bank, "exp_b")["bullets"][0]["text"] == "Bravo bullet EDITADO"
    # Alpha y Charlie quedan intactos (no recibieron la edición de Bravo).
    assert _exp_by_id(bank, "exp_a")["title"] == "Dev"
    assert _exp_by_id(bank, "exp_c")["title"] == "Lead"
    assert _exp_by_id(bank, "exp_a")["bullets"][0]["text"] == "Alpha bullet 1"


def test_merge_with_intermediate_deletion():
    """Quitar una experiencia intermedia del CV no desplaza ediciones."""
    bank = _bank()
    cv = bank_to_active_cv(bank)

    # El usuario elimina Bravo (la del medio) del CV y edita Charlie.
    cv["experiences"] = [e for e in cv["experiences"] if e["id"] != "exp_b"]
    charlie = next(e for e in cv["experiences"] if e["id"] == "exp_c")
    charlie["company"] = "Charlie Corp"

    merge_cv_to_bank(cv, bank)

    assert _exp_by_id(bank, "exp_c")["company"] == "Charlie Corp"
    # Bravo se conserva en el banco (es el master set) y queda intacto.
    assert _exp_by_id(bank, "exp_b")["company"] == "Bravo"
    # Alpha intacto.
    assert _exp_by_id(bank, "exp_a")["company"] == "Alpha"


def test_merge_adds_new_experience():
    """Una experiencia del CV sin match en el banco se agrega como nueva."""
    bank = _bank()
    cv = bank_to_active_cv(bank)
    before = len(bank["experiences"])

    cv["experiences"].append({
        "id": "exp_new", "company": "Delta", "title": "Architect",
        "location": "", "dates": "2023", "bullets": "Delta bullet 1\nDelta bullet 2",
    })

    merge_cv_to_bank(cv, bank)

    assert len(bank["experiences"]) == before + 1
    delta = _exp_by_id(bank, "exp_new")
    assert delta["company"] == "Delta"
    assert [b["text"] for b in delta["bullets"]] == ["Delta bullet 1", "Delta bullet 2"]


def test_merge_updates_bullets_within_matched_experience():
    """Los bullets editados se escriben en la experiencia correcta."""
    bank = _bank()
    cv = bank_to_active_cv(bank)

    alpha = next(e for e in cv["experiences"] if e["id"] == "exp_a")
    alpha["bullets"] = "Alpha bullet 1 EDITADO\nAlpha bullet 2 EDITADO"

    merge_cv_to_bank(cv, bank)

    texts = [b["text"] for b in _exp_by_id(bank, "exp_a")["bullets"]]
    assert texts == ["Alpha bullet 1 EDITADO", "Alpha bullet 2 EDITADO"]


def test_merge_appends_new_bullets_to_experience():
    """Bullets extra del CV (p.ej. añadidos por la IA) se agregan a la experiencia."""
    bank = _bank()
    cv = bank_to_active_cv(bank)

    bravo = next(e for e in cv["experiences"] if e["id"] == "exp_b")
    bravo["bullets"] = "Bravo bullet 1\nBravo bullet NUEVO"

    merge_cv_to_bank(cv, bank)

    texts = [b["text"] for b in _exp_by_id(bank, "exp_b")["bullets"]]
    assert texts == ["Bravo bullet 1", "Bravo bullet NUEVO"]


# ── Merge: proyectos y skills ────────────────────────────────────

def test_merge_updates_correct_project_after_reorder():
    bank = _bank()
    cv = bank_to_active_cv(bank)

    cv["projects"].reverse()  # [ProjY, ProjX]
    projx = next(p for p in cv["projects"] if p["id"] == "proj_x")
    projx["description"] = "desc x EDITADO"

    merge_cv_to_bank(cv, bank)

    px = next(p for p in bank["projects"] if p["id"] == "proj_x")
    py = next(p for p in bank["projects"] if p["id"] == "proj_y")
    assert px["description"] == "desc x EDITADO"
    assert py["description"] == "desc y"


def test_merge_updates_correct_skill_after_reorder():
    bank = _bank()
    cv = bank_to_active_cv(bank)

    cv["skills"].reverse()  # [Rust, Python]
    py_skill = next(s for s in cv["skills"] if s["id"] == "sk_1")
    py_skill["text"] = "Python 3.12"

    merge_cv_to_bank(cv, bank)

    s1 = next(s for s in bank["skills"] if s["id"] == "sk_1")
    s2 = next(s for s in bank["skills"] if s["id"] == "sk_2")
    assert s1["text"] == "Python 3.12"
    assert s2["text"] == "Rust"


# ── Funciones puras de apoyo (sanity) ────────────────────────────

def test_toggle_item_nested_bullet():
    bank = _bank()
    toggle_item(bank, "bul_a1", False)
    assert _exp_by_id(bank, "exp_a")["bullets"][0]["active"] is False


def test_count_bank_items():
    bank = _bank()
    total, active = count_bank_items(bank)
    # 1 summary + 3 exps + (2+1+1) bullets + 2 projects + 1 edu + 2 skills
    assert active == total
    assert total == 1 + 3 + 4 + 2 + 1 + 2


# ── Certificaciones: ahora compiten por el espacio de la página ──

def test_certifications_are_in_the_manifest():
    from banco import get_bank_manifest
    ids = {it["id"] for it in get_bank_manifest(_bank()) if it["type"] == "certification"}
    assert ids == {"cert_1", "cert_2"}


def test_selection_filters_certifications():
    bank = _bank()
    apply_ai_selection(bank, ["exp_a", "cert_2"])
    active = [c["id"] for c in bank["certifications"] if c["active"]]
    assert active == ["cert_2"]


def test_selection_without_certs_keeps_them_all():
    # Fail-open: un modelo que ignore las certificaciones no debe borrarlas del CV.
    bank = _bank()
    apply_ai_selection(bank, ["exp_a"])
    assert all(c["active"] for c in bank["certifications"])


def test_education_always_active_even_if_unselected():
    bank = _bank()
    apply_ai_selection(bank, ["exp_a"])
    assert bank["education"][0]["active"] is True


def test_bank_to_active_cv_filters_inactive():
    bank = _bank()
    toggle_item(bank, "exp_b", False)
    cv = bank_to_active_cv(bank)
    ids = [e["id"] for e in cv["experiences"]]
    assert "exp_b" not in ids
    assert ids == ["exp_a", "exp_c"]
