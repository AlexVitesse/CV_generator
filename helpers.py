"""
Helpers del CV Generator: utilidades de IDs, sincronización de widgets ↔ datos,
post-procesamiento de sugerencias de la IA, carga de datos por defecto y flujos
diferidos (auto-traducción + re-evaluación, aplicación de patches del chat).
"""

import html as _html
import json
import os
import re
import uuid

import streamlit as st

from i18n import LANG_NAMES, t
from translate import TRANSLATOR_AVAILABLE, translate_cv_data

# ═══════════════════════════════════════════════════════════════
# SAFE HTML HELPER (XSS prevention)
# ═══════════════════════════════════════════════════════════════


def safe_html(text: str) -> str:
    """Escapa HTML para usar en st.markdown(unsafe_allow_html=True)."""
    return _html.escape(str(text or ""))


# ═══════════════════════════════════════════════════════════════
# IDs Y SESSION STATE
# ═══════════════════════════════════════════════════════════════

def uid():
    return uuid.uuid4().hex[:8]


def get_score_color(score: int) -> str:
    """Retorna el color hexadecimal asociado al score dado."""
    score = score or 0
    if score > 70:
        return "#28a745"
    elif score >= 40:
        return "#fd7e14"
    else:
        return "#dc3545"


def clear_keys(*prefixes):
    for key in list(st.session_state.keys()):
        if any(key.startswith(p) for p in prefixes):
            del st.session_state[key]


# ═══════════════════════════════════════════════════════════════
# SINCRONIZACIÓN WIDGETS ↔ DATOS
# ═══════════════════════════════════════════════════════════════

def sync_widgets_to_data(data: dict):
    """Sincroniza valores de widgets de Streamlit al diccionario de datos del CV.
    Evita la repetición manual de chequear cada key del session_state."""

    # Campos simples: (session_key, data_key)
    simple_fields = [
        ("f_name", "name"),
        ("f_loc", "location"),
        ("f_summary", "summary"),
    ]
    for skey, dkey in simple_fields:
        if skey in st.session_state:
            data[dkey] = st.session_state[skey]

    # Experiencias: (prefijo_widget, campo_en_dict)
    exp_fields = [
        ("x_co_", "company"),
        ("x_ti_", "title"),
        ("x_lo_", "location"),
        ("x_da_", "dates"),
        ("x_bu_", "bullets"),
    ]
    for ex in data.get("experiences", []):
        eid = ex["id"]
        for prefix, field in exp_fields:
            key = f"{prefix}{eid}"
            if key in st.session_state:
                ex[field] = st.session_state[key]

    # Educación
    edu_fields = [
        ("e_in_", "institution"),
        ("e_de_", "degree"),
        ("e_lo_", "location"),
        ("e_dt_", "date"),
        ("e_dz_", "details"),
    ]
    for ed in data.get("education", []):
        eid = ed["id"]
        for prefix, field in edu_fields:
            key = f"{prefix}{eid}"
            if key in st.session_state:
                ed[field] = st.session_state[key]

    # Proyectos
    proj_fields = [
        ("p_nm_", "name"),
        ("p_ur_", "url"),
        ("p_ds_", "description"),
    ]
    for proj in data.get("projects", []):
        pid = proj["id"]
        for prefix, field in proj_fields:
            key = f"{prefix}{pid}"
            if key in st.session_state:
                proj[field] = st.session_state[key]

    # Skills
    for sk in data.get("skills", []):
        key = f"s_tx_{sk['id']}"
        if key in st.session_state:
            sk["text"] = st.session_state[key]


def push_data_to_widgets(data: dict):
    """Actualiza los widgets de Streamlit con los valores del diccionario
    (usado después de traducción para reflejar cambios en pantalla)."""

    st.session_state["f_name"] = data.get("name", "")
    st.session_state["f_loc"] = data.get("location", "")
    st.session_state["f_summary"] = data.get("summary", "")

    for ex in data.get("experiences", []):
        eid = ex["id"]
        st.session_state[f"x_co_{eid}"] = ex.get("company", "")
        st.session_state[f"x_ti_{eid}"] = ex.get("title", "")
        st.session_state[f"x_lo_{eid}"] = ex.get("location", "")
        st.session_state[f"x_da_{eid}"] = ex.get("dates", "")
        st.session_state[f"x_bu_{eid}"] = ex.get("bullets", "")

    for ed in data.get("education", []):
        eid = ed["id"]
        st.session_state[f"e_in_{eid}"] = ed.get("institution", "")
        st.session_state[f"e_de_{eid}"] = ed.get("degree", "")
        st.session_state[f"e_lo_{eid}"] = ed.get("location", "")
        st.session_state[f"e_dt_{eid}"] = ed.get("date", "")
        st.session_state[f"e_dz_{eid}"] = ed.get("details", "")

    for proj in data.get("projects", []):
        pid = proj["id"]
        st.session_state[f"p_nm_{pid}"] = proj.get("name", "")
        st.session_state[f"p_ur_{pid}"] = proj.get("url", "")
        st.session_state[f"p_ds_{pid}"] = proj.get("description", "")

    for sk in data.get("skills", []):
        st.session_state[f"s_tx_{sk['id']}"] = sk.get("text", "")


# ═══════════════════════════════════════════════════════════════
# POST-PROCESAMIENTO DE SUGERENCIAS IA
# ═══════════════════════════════════════════════════════════════

_PROTECTED_TERMS = [
    "FastAPI", "FastHTML", "JavaScript", "TypeScript", "PostgreSQL",
    "MySQL", "MongoDB", "GraphQL", "NodeJS", "Node.js", "GitHub",
    "GitLab", "BitBucket", "DevOps", "MLOps", "DataOps", "LangChain",
    "LangFuse", "LangSmith", "ChromaDB", "RunPod", "HuggingFace",
    "OpenAI", "SQLAlchemy", "SQLModel", "PyTorch", "TensorFlow",
    "APIs", "SDKs", "LLMs", "ORMs", "IoT", "OAuth", "WebSocket",
    "innerHTML", "CloudRun", "BigQuery", "PubSub",
]


def _fix_stuck_words(text: str) -> str:
    """Inserta espacio entre palabras pegadas tipo CamelCase: 'EngineerBackend' → 'Engineer Backend'.
    Protege términos técnicos conocidos (FastAPI, APIs, etc.)."""
    # Reemplazar términos protegidos con placeholders
    placeholders = {}
    for i, term in enumerate(_PROTECTED_TERMS):
        placeholder = f"\x00TERM{i}\x00"
        if term in text:
            text = text.replace(term, placeholder)
            placeholders[placeholder] = term

    # Aplicar regex de separación
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', text)

    # Restaurar términos protegidos
    for placeholder, term in placeholders.items():
        text = text.replace(placeholder, term)

    return text


def _strip_parenthetical_notes(text: str) -> str:
    """Elimina paréntesis con justificaciones/explicaciones, conserva los técnicos."""
    # Palabras que indican nota justificativa (en/es)
    justification_markers = [
        "implícit", "implicit", "inferred", "inferido",
        "equivalen", "transferi", "implied",
        "uso de", "use of ORMs", "experiencia cloud",
    ]

    def _is_justification(content: str) -> bool:
        lower = content.lower()
        return any(m in lower for m in justification_markers)

    # Reemplaza paréntesis que contienen marcadores justificativos
    def _replace(match):
        inner = match.group(1)
        if _is_justification(inner):
            return ""  # Eliminar completamente
        return match.group(0)  # Conservar paréntesis técnicos

    result = re.sub(r'\s*\(([^)]+)\)', _replace, text)
    # Limpiar espacios dobles resultantes
    result = re.sub(r'  +', ' ', result).strip()
    return result


# Labels de tier reconocidos, por rango: 0 = avanzado, 1 = intermedio, 2 = familiaridad.
_TIER_LABELS = [
    ("dominio avanzado", "core skills", "advanced proficiency"),
    ("dominio intermedio", "working knowledge", "intermediate proficiency"),
    ("familiaridad", "exposure to", "familiarity"),
]


def _parse_skill_tiers(line: str):
    """Parsea 'Label: a, b | Label2: c' → [(label, rank, [skills])].
    Retorna None si algún segmento no tiene un label de tier reconocido
    (p.ej. líneas de certificaciones o idiomas), para dejarlas intactas."""
    parsed = []
    for seg in line.split("|"):
        seg = seg.strip()
        if ":" not in seg:
            return None
        label, items = seg.split(":", 1)
        rank = next(
            (r for r, names in enumerate(_TIER_LABELS) if label.strip().lower() in names),
            None,
        )
        if rank is None:
            return None
        skills = [s.strip() for s in items.split(",") if s.strip()]
        parsed.append((label.strip(), rank, skills))
    return parsed


def _enforce_skill_tiers(suggested: str, original_lines: list) -> str:
    """Devuelve cada skill a su tier original si la IA la promovió de nivel.
    Las skills nuevas (inferidas) nunca pueden quedar en el tier avanzado."""
    orig_rank = {}
    for line in original_lines:
        for _label, rank, skills in _parse_skill_tiers(line) or []:
            for sk in skills:
                key = sk.lower()
                if key not in orig_rank or rank < orig_rank[key]:
                    orig_rank[key] = rank

    sugg = _parse_skill_tiers(suggested)
    if not sugg or not orig_rank:
        return suggested

    ranks_present = {rank for _, rank, _ in sugg}
    buckets = {rank: [] for rank in ranks_present}
    for _label, rank, skills in sugg:
        for sk in skills:
            known = orig_rank.get(sk.lower())
            if known is not None and known > rank and known in ranks_present:
                target = known  # estaba en un tier inferior: regresarla ahí
            elif known is None and rank == 0 and 1 in ranks_present:
                target = 1  # skill nueva inferida: nunca en avanzado
            else:
                target = rank
            buckets[target].append(sk)

    parts = []
    for label, rank, _ in sugg:
        seen, items = set(), []
        for sk in buckets[rank]:
            if sk.lower() not in seen:
                seen.add(sk.lower())
                items.append(sk)
        if items:
            parts.append(f"{label}: {', '.join(items)}")
    return " | ".join(parts)


def sanitize_ai_result(result: dict, cv_data: dict | None = None) -> dict:
    """Limpia problemas comunes de la respuesta de la IA antes de mostrarla."""
    suggestions = result.get("suggestions", {})

    # ── Fix summary: palabras pegadas (e.g. "EngineerBackend") ──
    if suggestions.get("summary"):
        suggestions["summary"] = _fix_stuck_words(suggestions["summary"])

    # ── Fix experience titles y bullets ──
    for exp in suggestions.get("experiences", []):
        if exp.get("title"):
            exp["title"] = _fix_stuck_words(exp["title"])
        if exp.get("bullets"):
            exp["bullets"] = _strip_parenthetical_notes(exp["bullets"])

    # ── Fix project descriptions ──
    for proj in suggestions.get("projects", []):
        if proj.get("description"):
            proj["description"] = _strip_parenthetical_notes(proj["description"])

    # ── Fix skills: quitar paréntesis justificativos ──
    if suggestions.get("skills"):
        if isinstance(suggestions["skills"], list):
            suggestions["skills"] = [
                _strip_parenthetical_notes(s) for s in suggestions["skills"]
            ]
            # Anti-inflación: regresar skills promovidas a su tier original
            if cv_data:
                original_lines = [
                    sk.get("text", "") for sk in cv_data.get("skills", [])
                ]
                suggestions["skills"] = [
                    _enforce_skill_tiers(s, original_lines)
                    for s in suggestions["skills"]
                ]

    return result


# Alias retro-compatible (algunos módulos importaban el nombre con guion bajo)
_sanitize_ai_result = sanitize_ai_result


# ═══════════════════════════════════════════════════════════════
# DATOS POR DEFECTO
# ═══════════════════════════════════════════════════════════════

def default_cv_data():
    """Carga datos iniciales desde JSON. Prioriza config_personal.json si existe."""
    personal_config = "config_personal.json"
    template_config = "config_plantilla.json"

    data = {}
    if os.path.exists(personal_config):
        try:
            with open(personal_config, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    if not data and os.path.exists(template_config):
        try:
            with open(template_config, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    if not data:
        # Fallback total si fallan los archivos
        data = {
            "name": "Tu Nombre Completo",
            "location": "Ciudad, País",
            "linkedin": "www.linkedin.com/in/tu-perfil",
            "phone": "+52 00 0000 0000",
            "email": "tu@correo.com",
            "summary": "Breve descripción de tu perfil profesional.",
            "experiences": [],
            "education": [],
            "skills": []
        }

    # Asegurar IDs únicos para widgets de Streamlit
    for exp in data.get("experiences", []):
        if "id" not in exp: exp["id"] = uid()
    for proj in data.get("projects", []):
        if "id" not in proj: proj["id"] = uid()
    for edu in data.get("education", []):
        if "id" not in edu: edu["id"] = uid()
    for sk in data.get("skills", []):
        if "id" not in sk: sk["id"] = uid()

    return data


import session_keys as sk


# ═══════════════════════════════════════════════════════════════
# DETECCIÓN DE IDIOMA Y FLUJOS DIFERIDOS
# ═══════════════════════════════════════════════════════════════

def detect_vacancy_language(text: str) -> str:
    """Detecta si la vacante está en inglés o español con heurística simple."""
    en_markers = [" the ", " and ", " with ", " experience ", " years ",
                  " team ", " about ", " requirements ", " skills ",
                  " develop ", " work ", " you ", " our ", " will "]
    es_markers = [" los ", " las ", " con ", " experiencia ", " años ",
                  " equipo ", " acerca ", " requisitos ", " habilidades ",
                  " desarrollar ", " trabajo ", " usted ", " nuestro "]
    text_lower = f" {text.lower()} "
    en_count = sum(1 for w in en_markers if w in text_lower)
    es_count = sum(1 for w in es_markers if w in text_lower)
    return "en" if en_count > es_count else "es"


def deferred_translate_and_reevaluate(d: dict):
    """Auto-traduce el CV si hay mismatch de idioma con la vacante, luego re-evalúa."""
    vacancy_text = st.session_state.get(sk.VACANCY_TEXT, "").strip()
    if not vacancy_text or not st.session_state.get(sk.AI_API_KEY):
        return

    vacancy_lang = detect_vacancy_language(vacancy_text)
    content_lang = st.session_state.get(sk.CONTENT_LANG, "es")

    # Auto-traducir si hay mismatch de idioma
    if vacancy_lang != content_lang and TRANSLATOR_AVAILABLE:
        try:
            translated = translate_cv_data(
                d,
                source=content_lang,
                target=vacancy_lang,
                api_key=st.session_state.get(sk.AI_API_KEY),
                model=st.session_state.get(sk.AI_MODEL),
            )
            st.session_state[sk.CV] = translated
            st.session_state[sk.CONTENT_LANG] = vacancy_lang
            st.session_state[sk.LANG] = vacancy_lang
            # Actualizar d para la re-evaluación
            for k, v in translated.items():
                d[k] = v
            push_data_to_widgets(d)
            st.toast(t("translate_success").format(LANG_NAMES.get(vacancy_lang, vacancy_lang)))
        except Exception as e:
            st.toast(f"Auto-translate error: {e}")

    # Re-evaluar con el CV actualizado (preservar extra_context del chat de refinamiento)
    try:
        from ai_analyzer import analyze_vacancy
        extra_context = ""
        refine_msgs = st.session_state.get(sk.REFINE_MESSAGES, [])
        if refine_msgs:
            extra_context = "\n".join(
                m["content"] for m in refine_msgs if m["role"] == "user"
            )
        result = analyze_vacancy(
            d, vacancy_text,
            st.session_state[sk.AI_API_KEY],
            st.session_state[sk.AI_MODEL],
            extra_context=extra_context,
        )
        st.session_state[sk.ANALYSIS_RESULT] = sanitize_ai_result(result, d)
        # Limpiar eval_result anterior porque el CV cambió
        st.session_state[sk.EVAL_RESULT] = None
    except Exception as e:
        st.toast(f"Re-evaluation error: {e}")


# ═══════════════════════════════════════════════════════════════
# APLICACIÓN DE PATCHES DEL CHAT ASESOR
# ═══════════════════════════════════════════════════════════════

def apply_chat_patch(data: dict, patch: dict):
    """Aplica un patch del chat asesor al diccionario del CV."""
    field = patch.get("field")
    idx = patch.get("target_index", 0) or 0
    action = patch.get("action", "append")
    content = patch.get("content", "")

    if field == "summary":
        if action == "replace":
            data["summary"] = content
        else:
            data["summary"] = data.get("summary", "") + "\n" + content

    elif field == "experience_bullet":
        exps = data.get("experiences", [])
        if 0 <= idx < len(exps):
            if action == "replace":
                exps[idx]["bullets"] = content
            else:
                current = exps[idx].get("bullets", "").rstrip()
                exps[idx]["bullets"] = current + "\n" + content if current else content

    elif field == "experience_title":
        exps = data.get("experiences", [])
        if 0 <= idx < len(exps):
            exps[idx]["title"] = content

    elif field == "skill_line":
        skills = data.get("skills", [])
        if 0 <= idx < len(skills):
            if action == "replace":
                skills[idx]["text"] = content
            else:
                skills[idx]["text"] = skills[idx].get("text", "") + ", " + content

    elif field == "project_description":
        projs = data.get("projects", [])
        if 0 <= idx < len(projs):
            if action == "replace":
                projs[idx]["description"] = content
            else:
                current = projs[idx].get("description", "").rstrip()
                projs[idx]["description"] = current + "\n" + content if current else content

    elif field == "project_new":
        data.setdefault("projects", []).append({
            "id": uid(), "name": content, "url": "", "description": "",
        })
