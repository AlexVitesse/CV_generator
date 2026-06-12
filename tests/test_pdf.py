"""Tests de pdf.py — saneo de texto (V2-17) y conteo de páginas (V2-16)."""

from io import BytesIO

import pytest
from pypdf import PdfReader

from pdf import safe, generate_cv_pdf


def _cv(n_exps=2, bullets_per_exp=3):
    return {
        "name": "Ada Lovelace",
        "location": "São Paulo, Brasil",
        "linkedin": "linkedin.com/in/ada",
        "github": "", "phone": "+55 11 1234-5678", "email": "ada@example.com",
        "summary": "Ingeniera de software con foco en datos.",
        "experiences": [
            {
                "id": f"exp_{i}", "company": f"Empresa {i}", "title": "Engineer",
                "location": "Remote", "dates": "2020-2023",
                "bullets": "\n".join(f"Logró el objetivo {j} con métricas" for j in range(bullets_per_exp)),
            }
            for i in range(n_exps)
        ],
        "projects": [{"id": "p1", "name": "Proj", "url": "", "description": "desc"}],
        "education": [{"id": "e1", "institution": "Uni", "degree": "BSc",
                       "details": "", "location": "", "date": "2019"}],
        "skills": [{"id": "s1", "text": "Python, Rust, SQL"}],
    }


# ── safe() ───────────────────────────────────────────────────────

def test_safe_strips_control_chars():
    out = safe("hola\x00mundo\x07!")
    assert "\x00" not in out and "\x07" not in out
    assert "hola" in out and "mundo" in out


def test_safe_escapes_xml():
    out = safe("a < b & c > d")
    assert "&lt;" in out and "&amp;" in out and "&gt;" in out


def test_safe_preserves_accents():
    # "São Paulo" no debe perder la tilde ni la ã (representables en cp1252).
    out = safe("São Paulo")
    assert "ã" in out


def test_safe_markdown_bold_italic():
    assert "<b>x</b>" in safe("**x**")
    assert "<i>y</i>" in safe("*y*")


def test_safe_handles_none():
    assert safe(None) == ""


# ── generate_cv_pdf ──────────────────────────────────────────────

def test_generate_pdf_returns_valid_buffer():
    buf, fits = generate_cv_pdf(_cv(), lang="es")
    assert isinstance(buf, BytesIO)
    assert isinstance(fits, bool)
    data = buf.getvalue()
    assert data.startswith(b"%PDF")


def test_small_cv_fits_one_page():
    buf, fits = generate_cv_pdf(_cv(n_exps=1, bullets_per_exp=2), lang="es")
    pages = PdfReader(buf).get_num_pages()
    assert pages == 1
    assert fits is True


def test_fits_flag_matches_page_count():
    # El flag 'cabe_en_1_pagina' debe ser consistente con el conteo real de pypdf.
    buf, fits = generate_cv_pdf(_cv(n_exps=8, bullets_per_exp=6), lang="es")
    pages = PdfReader(buf).get_num_pages()
    assert fits == (pages == 1)
