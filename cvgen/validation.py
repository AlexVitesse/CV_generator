"""
Validación de datos del CV.

Combina dos niveles:
  1. Validadores de formato sueltos (email, teléfono, LinkedIn) usados por la UI
     para mostrar advertencias en vivo bajo cada campo.
  2. Modelos Pydantic que normalizan la estructura completa del CV (asegurando
     listas, IDs y tipos correctos) al importar JSON, devolviendo además una
     lista de problemas legibles para el usuario.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import List
from urllib.parse import urlparse
from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger("validation")


# ═══════════════════════════════════════════════════════════════
# VALIDADORES DE FORMATO (advertencias en vivo en la UI)
# ═══════════════════════════════════════════════════════════════

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
_PHONE_RE = re.compile(r"^\+?[\d\s\-()]{7,20}$")


def validate_email(email: str) -> bool:
    if not email:
        return True
    return bool(_EMAIL_RE.match(email))


def validate_phone(phone: str) -> bool:
    if not phone:
        return True
    # Permite +, dígitos, espacios y guiones
    return bool(_PHONE_RE.match(phone))


def validate_linkedin(url: str) -> bool:
    if not url:
        return True
    url_lower = url.lower().strip()
    if not url_lower.startswith(("http://", "https://")):
        url_lower = "https://" + url_lower
    try:
        parsed = urlparse(url_lower)
        # Validar que sea linkedin.com o www.linkedin.com y contenga /in/
        return parsed.netloc in ("linkedin.com", "www.linkedin.com") and "/in/" in parsed.path
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# MODELOS PYDANTIC (normalización estructural al importar)
# ═══════════════════════════════════════════════════════════════

def _uid() -> str:
    return uuid.uuid4().hex[:8]


class _Base(BaseModel):
    """Base permisiva: ignora campos extra y coacciona tipos comunes."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=False)


class ExperienceModel(_Base):
    id: str = Field(default_factory=_uid)
    company: str = Field("", min_length=1)
    title: str = Field("", min_length=1)
    location: str = ""
    dates: str = ""
    bullets: str = ""


class EducationModel(_Base):
    id: str = Field(default_factory=_uid)
    institution: str = Field("", min_length=1)
    degree: str = Field("", min_length=1)
    location: str = ""
    date: str = ""
    details: str = ""


class ProjectModel(_Base):
    id: str = Field(default_factory=_uid)
    name: str = Field("", min_length=1)
    url: str = ""
    description: str = ""


class SkillModel(_Base):
    id: str = Field(default_factory=_uid)
    text: str = Field("", min_length=1)


class CertificationModel(_Base):
    id: str = Field(default_factory=_uid)
    text: str = Field("", min_length=1)
    credential_id: str = ""  # ID/URL de verificación — se guarda pero NO se imprime en el PDF


class CVModel(_Base):
    name: str = Field("", min_length=1)
    location: str = ""
    linkedin: str = ""
    phone: str = ""
    email: str = ""
    github: str = ""
    summary: str = ""
    experiences: List[ExperienceModel] = Field(default_factory=list)
    education: List[EducationModel] = Field(default_factory=list)
    projects: List[ProjectModel] = Field(default_factory=list)
    certifications: List[CertificationModel] = Field(default_factory=list)
    skills: List[SkillModel] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# MODELOS DE RESPUESTA DEL LLM (V2-08)
# ═══════════════════════════════════════════════════════════════
# Validan el shape de cada endpoint de IA. Permisivos (extra="allow") salvo en
# los campos críticos: el score debe ser entero 0-100 y las listas/ids deben
# tener el tipo correcto. ai_analyzer reintenta una vez ante ValidationError
# antes de fallar con un mensaje legible.

class VacancyAnalysisResponse(_Base):
    match_score: int = Field(ge=0, le=100)
    viable: bool = True
    matching_keywords: List[str] = Field(default_factory=list)
    missing_keywords: List[str] = Field(default_factory=list)
    suggestions: dict = Field(default_factory=dict)
    reasoning: str = ""


class DetailedEvalResponse(_Base):
    overall_score: int = Field(ge=0, le=100)
    score_label: str = ""
    dimensions: List[dict] = Field(default_factory=list)
    requirements: List[dict] = Field(default_factory=list)
    overfitting: List[dict] = Field(default_factory=list)
    verdicts: List[dict] = Field(default_factory=list)


class BankSelectionResponse(_Base):
    selected_ids: List[str] = Field(default_factory=list)
    reasoning: str = ""


class TranslationResponse(_Base):
    """Shape esperado de translate_cv_via_llm (mismo esquema que el CV activo).

    Permisivo: la reparación item-a-item (V2-11) cubre faltantes, así que se
    usa como chequeo suave (warning), no como bloqueo.
    """
    experiences: List[dict] = Field(default_factory=list)
    education: List[dict] = Field(default_factory=list)
    projects: List[dict] = Field(default_factory=list)
    certifications: List[dict] = Field(default_factory=list)
    skills: List[dict] = Field(default_factory=list)


def _coerce_skills(raw) -> list:
    """Skills y certificaciones pueden venir como strings sueltos o dicts; normaliza a dicts."""
    out = []
    for sk in raw or []:
        if isinstance(sk, str):
            out.append({"id": _uid(), "text": sk})
        elif isinstance(sk, dict):
            sk.setdefault("id", _uid())
            out.append(sk)
    return out


def parse_cv(data: dict) -> tuple[dict, List[str]]:
    """Valida y normaliza un dict de CV importado.

    Devuelve `(cv_normalizado, problemas)`:
      - `cv_normalizado`: dict con la estructura garantizada (listas, IDs, tipos).
        Si Pydantic falla, devuelve el dict original sin tocar.
      - `problemas`: lista de mensajes legibles (formato de email/teléfono, etc.).
    """
    issues: List[str] = []

    # Normalizar skills/certificaciones antes de Pydantic (acepta strings sueltos)
    if isinstance(data, dict) and "skills" in data:
        data = {**data, "skills": _coerce_skills(data.get("skills"))}
    if isinstance(data, dict) and "certifications" in data:
        data = {**data, "certifications": _coerce_skills(data.get("certifications"))}

    try:
        model = CVModel.model_validate(data)
        normalized = model.model_dump()
    except Exception as e:
        # Si la validación estructural falla, no bloqueamos la importación.
        issues.append(f"Error de validación: {e}")
        logger.exception("parse_cv validation error")
        normalized = data

    # Validaciones de formato (no bloqueantes, solo advertencias)
    if not validate_email(normalized.get("email", "")):
        issues.append("email")
    if not validate_phone(normalized.get("phone", "")):
        issues.append("phone")
    if not validate_linkedin(normalized.get("linkedin", "")):
        issues.append("linkedin")

    return normalized, issues
