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

    # Certificaciones
    for cert in data.get("certifications", []):
        key = f"c_tx_{cert['id']}"
        if key in st.session_state:
            cert["text"] = st.session_state[key]
        cid_key = f"c_cid_{cert['id']}"
        if cid_key in st.session_state:
            cert["credential_id"] = st.session_state[cid_key]

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

    for cert in data.get("certifications", []):
        st.session_state[f"c_tx_{cert['id']}"] = cert.get("text", "")
        st.session_state[f"c_cid_{cert['id']}"] = cert.get("credential_id", "")

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


# Un token con mayúscula interna: MuseTalk, LangGraph, ChatPDF, pgVector, ZAPI...
_CAMEL_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9.+#]*[a-z0-9][A-Z][A-Za-z0-9.+#]*\b")


def camel_terms_in(cv_data: dict | None) -> list[str]:
    """Términos CamelCase que YA existen literalmente en el CV del candidato.

    La lista fija `_PROTECTED_TERMS` se queda corta con cada tecnología nueva
    (MuseTalk → 'Muse Talk', LangGraph → 'Lang Graph'). Lo que el candidato ya
    escribió así es intencional por definición, así que se protege solo.
    """
    if not cv_data:
        return []
    parts = [str(cv_data.get("summary", ""))]
    for exp in cv_data.get("experiences", []):
        parts += [str(exp.get(f, "")) for f in ("company", "title", "bullets")]
    for proj in cv_data.get("projects", []):
        parts += [str(proj.get(f, "")) for f in ("name", "description")]
    parts += [str(sk.get("text", "")) for sk in cv_data.get("skills", [])]
    parts += [str(c.get("text", "")) for c in cv_data.get("certifications", [])]
    return sorted(set(_CAMEL_RE.findall(" ".join(parts))), key=len, reverse=True)


def _fix_stuck_words(text: str, extra_protected=()) -> str:
    """Inserta espacio entre palabras pegadas tipo CamelCase: 'EngineerBackend' → 'Engineer Backend'.
    Protege términos técnicos conocidos (FastAPI, APIs, etc.) y los del propio CV."""
    # Reemplazar términos protegidos con placeholders
    placeholders = {}
    for i, term in enumerate([*extra_protected, *_PROTECTED_TERMS]):
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
    """Devuelve cada skill a su tier original si la IA la promovió o degradó de nivel.
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
    lowest = max(ranks_present)  # rank más alto = tier más bajo (familiaridad/exposure)
    buckets = {rank: [] for rank in ranks_present}
    for _label, rank, skills in sugg:
        for sk in skills:
            known = orig_rank.get(sk.lower())
            if known is not None and known != rank and known in ranks_present:
                # El tier es un HECHO en ambos sentidos: ni inflar (Familiaridad→Core) ni
                # degradar (visto: FastAPI de "Dominio avanzado" bajada a Working knowledge).
                # Si es un missing_keyword, _demote_missing_keyword_skills la baja después.
                target = known
            elif known is None and rank < lowest:
                target = lowest  # skill nueva inferida → siempre al tier más bajo
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


def _norm_kw(s: str) -> str:
    """Normaliza una skill/keyword para comparar: 'Next.js (solid experience)' → 'nextjs'.
    Conserva + y # para C++/C#."""
    return re.sub(r"[^a-z0-9+#]", "", str(s or "").split("(")[0].lower())


def _restore_core_skills(suggested: str, original_lines: list) -> str:
    """Re-agrega las skills de DOMINIO AVANZADO del CV original que la IA eliminó.

    El prompt pide conservar todas, pero el modelo las recorta para "enfocar" (visto:
    FastAPI y Oracle Cloud desaparecieron en una vacante de datos). Solo el tier
    superior: re-agregar también los intermedios alargaría la línea sin aportar.
    Van al tier más alto PRESENTE en la sugerencia (nunca a uno superior al original).
    """
    sugg = _parse_skill_tiers(suggested)
    if not sugg:
        return suggested
    present = [_norm_kw(s) for _, _, skills in sugg for s in skills]

    def _has(n):  # "Oracle Cloud" ya cubierto por "Oracle Cloud Infrastructure"
        return any(n in p or p in n for p in present if p)

    lost = []
    for line in original_lines:
        for _label, rank, skills in _parse_skill_tiers(line) or []:
            if rank == 0:
                for s in skills:
                    n = _norm_kw(s)
                    if n and not _has(n):
                        lost.append(s)
                        present.append(n)
    if not lost:
        return suggested
    top = min(rank for _, rank, _ in sugg)
    return " | ".join(
        f"{label}: {', '.join(skills + lost if rank == top else skills)}"
        for label, rank, skills in sugg
    )


def _demote_missing_keyword_skills(suggested: str, missing_keywords: list) -> str:
    """Baja al tier más bajo cualquier skill que la IA listó por encima de 'exposure'
    pese a estar en missing_keywords (contradicción interna detectada en logs: el JD
    marca Next.js como faltante y a la vez aparece en 'working knowledge')."""
    sugg = _parse_skill_tiers(suggested)
    if not sugg or not missing_keywords:
        return suggested
    missing = {_norm_kw(k) for k in missing_keywords if _norm_kw(k)}
    if not missing:
        return suggested

    ranks_present = {rank for _, rank, _ in sugg}
    lowest = max(ranks_present)
    buckets = {rank: [] for rank in ranks_present}
    for _label, rank, skills in sugg:
        for sk in skills:
            target = lowest if (rank < lowest and _norm_kw(sk) in missing) else rank
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


# Umbrales de viabilidad alineados con las bandas de prompts/analyze.md:
# score >= 70 con must-haves cubiertos → viable; 30-49 → no viable.
VIABLE_SCORE_HIGH = 70  # >= esto: el prompt exige viable=true
VIABLE_SCORE_LOW = 50   # < esto: el prompt exige viable=false

# Pisos de score por cobertura de keywords (Bug B — scorer bimodal).
# El LLM colapsa a dos polos (~90/~35): "35" es un valor-imán desconectado del match
# real (visto en logs: 16 keywords cubiertas / 5 faltantes seguía dando 35). Este guard
# SOLO sube el score hasta el piso que la cobertura implica; NUNCA lo baja (no debilita
# la honestidad del prompt, solo corrige la caída artificial). Pares (cobertura, piso):
_COVERAGE_FLOORS = ((0.85, 70), (0.70, 60), (0.55, 50))

# Muestra mínima para creerle a la cobertura. Sin esto, el caso frecuente
# "matched=2, missing=0" da cobertura 1.0 y regala un piso de 70 (+ viable=True,
# que se deriva del score). En los logs, TODAS las corridas recientes traen
# missing=0, así que el piso se estaba aplicando prácticamente siempre.
_MIN_KEYWORDS_FOR_FLOOR = 5


def _reconcile_score_with_coverage(score, matching_kw, missing_kw):
    """Devuelve un score corregido hacia arriba si contradice la cobertura de keywords.

    cobertura = matched / (matched + missing). Si el score quedó por debajo del piso
    que esa cobertura implica, lo sube al piso. Si no hay keywords clasificadas o el
    score ya respeta el piso, lo devuelve igual. Función pura (testeable).
    """
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return score
    n_match = len(matching_kw or [])
    n_miss = len(missing_kw or [])
    total = n_match + n_miss
    if total < _MIN_KEYWORDS_FOR_FLOOR:
        return score
    coverage = n_match / total
    for min_cov, floor in _COVERAGE_FLOORS:
        if coverage >= min_cov:
            return max(score, floor)
    return score


# Fracción de keywords matcheados que la re-eval debe conservar para que el score
# pre-adapt actúe de piso. Tolerante a 1-2 pérdidas por reescritura/traducción.
_REEVAL_PRESERVE_THRESHOLD = 0.85


def _norm_keywords(keywords) -> set:
    """Normaliza una lista de keywords a un set comparable (case-insensitive)."""
    return {str(k).strip().lower() for k in (keywords or []) if str(k).strip()}


def clamp_reeval_score(new_result: dict, prev_result: dict | None) -> dict:
    """Evita que la re-eval tras adaptar baje el score si conservó los matches.

    Adaptar a 1 página re-evalúa un CV más delgado y el scorer (bimodal, sin
    determinismo perfecto en Gemini) lo castiga aunque la evidencia matcheada siga
    presente (visto en logs: mismo CV → 78 luego 48). Si la re-eval preservó >=85%
    de los keywords que el análisis original ya tenía matcheados, el score previo
    actúa de PISO. Solo SUBE el score; nunca lo baja (si la adaptación sí perdió
    evidencia, la caída es legítima y se respeta). Función pura.
    """
    if not isinstance(prev_result, dict):
        return new_result
    prev_score = prev_result.get("match_score")
    new_score = new_result.get("match_score")
    if not all(isinstance(s, (int, float)) and not isinstance(s, bool)
               for s in (prev_score, new_score)):
        return new_result
    if new_score >= prev_score:
        return new_result
    prev_matched = _norm_keywords(prev_result.get("matching_keywords"))
    if not prev_matched:
        return new_result
    preserved = len(prev_matched & _norm_keywords(new_result.get("matching_keywords")))
    if preserved / len(prev_matched) >= _REEVAL_PRESERVE_THRESHOLD:
        new_result["match_score"] = prev_score
    return new_result


def sanitize_ai_result(result: dict, cv_data: dict | None = None) -> dict:
    """Limpia problemas comunes de la respuesta de la IA antes de mostrarla."""
    suggestions = result.get("suggestions", {})

    # ── Reconciliar score con la cobertura de keywords (Bug B — anti imán-35) ──
    # Antes de reconciliar viable, corrige el score si quedó por debajo del piso que
    # implica su propia cobertura de keywords. Así el 88→35 deja de ser posible cuando
    # la cobertura real es alta (el viable de abajo ya usa el score corregido).
    score = _reconcile_score_with_coverage(
        result.get("match_score"),
        result.get("matching_keywords"),
        result.get("missing_keywords"),
    )
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        result["match_score"] = score

    # ── Reconciliar viable con el score (anti-contradicción) ──
    # El modelo a veces se contradice con sus propias bandas (visto en logs: 78→viable
    # False y 60→viable True). Forzamos coherencia en los extremos y respetamos su
    # juicio solo en la banda media 50-69, donde la viabilidad es genuinamente ambigua.
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        if score >= VIABLE_SCORE_HIGH:
            result["viable"] = True
        elif score < VIABLE_SCORE_LOW:
            result["viable"] = False

    # ── Fix summary: palabras pegadas (e.g. "EngineerBackend") ──
    own_terms = camel_terms_in(cv_data)
    if suggestions.get("summary"):
        suggestions["summary"] = _fix_stuck_words(suggestions["summary"], own_terms)

    # ── Fix experience titles y bullets ──
    # El título de un puesto es un HECHO (lo verifica una referencia o LinkedIn): se
    # restaura el real por id aunque el modelo lo "adapte" a la vacante (visto: "Python
    # Backend Engineer" → "Python Data & Systems Engineer").
    real_titles = {e.get("id"): e.get("title") for e in (cv_data or {}).get("experiences", [])
                   if isinstance(e, dict) and e.get("id") and e.get("title")}
    for exp in suggestions.get("experiences", []):
        if exp.get("id") in real_titles:
            exp["title"] = real_titles[exp["id"]]
        elif exp.get("title"):
            exp["title"] = _fix_stuck_words(exp["title"], own_terms)
        if exp.get("bullets"):
            exp["bullets"] = _strip_parenthetical_notes(exp["bullets"])

    # ── Fix project descriptions ──
    for proj in suggestions.get("projects", []):
        if proj.get("description"):
            proj["description"] = _strip_parenthetical_notes(proj["description"])

    # ── Fix skills: quitar paréntesis justificativos ──
    if suggestions.get("skills"):
        if isinstance(suggestions["skills"], list):
            lines = [_strip_parenthetical_notes(s) for s in suggestions["skills"]]
            original_lines = (
                [sk.get("text", "") for sk in cv_data.get("skills", [])] if cv_data else []
            )
            missing_kw = result.get("missing_keywords", [])
            # El prompt nuevo devuelve UNA línea por tier. Los guards operan sobre TODOS
            # los tiers juntos (comparan rangos entre sí): correrlos por línea suelta los
            # anula (un solo tier → nunca hay nivel al que degradar). Combinamos las líneas
            # de tier en un string, aplicamos los guards una vez, y conservamos intactas
            # las líneas no-tier (certs/idiomas) por si el modelo las incluyera.
            tier_lines = [l for l in lines if _parse_skill_tiers(l)]
            other = [l for l in lines if l and not _parse_skill_tiers(l)]
            if tier_lines:
                combined = " | ".join(tier_lines)
                if original_lines:
                    combined = _enforce_skill_tiers(combined, original_lines)
                    combined = _restore_core_skills(combined, original_lines)
                combined = _demote_missing_keyword_skills(combined, missing_kw)
                # Re-separar: una línea por tier (escaneable, como pide el prompt).
                suggestions["skills"] = combined.split(" | ") + other
            else:
                suggestions["skills"] = lines

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
    for cert in data.get("certifications", []):
        if "id" not in cert: cert["id"] = uid()
    for sk in data.get("skills", []):
        if "id" not in sk: sk["id"] = uid()

    return data


import session_keys as sk


# ═══════════════════════════════════════════════════════════════
# DETECCIÓN DE IDIOMA Y FLUJOS DIFERIDOS
# ═══════════════════════════════════════════════════════════════

# Señal decisiva: caracteres que el inglés no usa. Una vacante en español con mucho
# boilerplate en inglés ("about the team", "requirements") empataba o ganaba en el
# conteo de marcadores y disparaba la traducción completa del CV.
_ES_ONLY_CHARS = re.compile(r"[áéíóúñ¿¡]", re.IGNORECASE)


def detect_vacancy_language(text: str) -> str:
    """Detecta si la vacante está en inglés o español con heurística simple."""
    if len(_ES_ONLY_CHARS.findall(text or "")) >= 3:
        return "es"
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


def has_foreign_text(d: dict, lang: str) -> bool:
    """¿Algún summary/bullet/descripción está en otro idioma que `lang`? El banco mezcla
    idiomas y los bullets se usan TAL CUAL (sin reescritura), así que el idioma de la
    sesión no basta para decidir si hay que traducir."""
    from pdf import text_lang
    texts = str(d.get("summary", "")).split("\n")
    for e in d.get("experiences", []):
        texts += str(e.get("bullets", "")).split("\n")
    texts += [p.get("description", "") for p in d.get("projects", [])]
    return any(text_lang(x) not in (None, lang) for x in texts)


def deferred_translate_and_reevaluate(d: dict):
    """Auto-traduce el CV si hay mismatch de idioma con la vacante, luego re-evalúa."""
    vacancy_text = st.session_state.get(sk.VACANCY_TEXT, "").strip()
    if not vacancy_text or not st.session_state.get(sk.AI_API_KEY):
        return

    vacancy_lang = detect_vacancy_language(vacancy_text)
    content_lang = st.session_state.get(sk.CONTENT_LANG, "es")

    # Auto-traducir si hay mismatch de idioma
    if TRANSLATOR_AVAILABLE and (vacancy_lang != content_lang
                                 or has_foreign_text(d, vacancy_lang)):
        try:
            translated = translate_cv_data(
                d,
                source=content_lang,
                target=vacancy_lang,
                api_key=st.session_state.get(sk.AI_API_KEY),
                model=st.session_state.get(sk.AI_MODEL),
                provider=st.session_state.get(sk.AI_PROVIDER),
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
        # Score pre-adapt (análisis contra banco completo): actúa de piso si la
        # re-eval conservó los keywords matcheados (clamp anti-caída artificial).
        prev_result = st.session_state.get(sk.ANALYSIS_RESULT)
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
            provider=st.session_state.get(sk.AI_PROVIDER),
        )
        result = clamp_reeval_score(result, prev_result)
        st.session_state[sk.ANALYSIS_RESULT] = sanitize_ai_result(result, d)
        # Limpiar eval_result anterior porque el CV cambió
        st.session_state[sk.EVAL_RESULT] = None
    except Exception as e:
        st.toast(f"Re-evaluation error: {e}")


# ═══════════════════════════════════════════════════════════════
# APLICACIÓN DE PATCHES DEL CHAT ASESOR
# ═══════════════════════════════════════════════════════════════

def _resolve_patch_index(patch: dict, items: list) -> int:
    """Resuelve el índice objetivo de un patch del chat.

    Ancla por `target_id` (estable) contra `items`; si no hay id o no matchea,
    cae al `target_index` posicional. Mantener el id evita que un patch aterrice
    en la empresa/proyecto equivocado si el modelo reordenó su numeración.
    """
    tid = patch.get("target_id")
    if tid:
        for i, it in enumerate(items):
            if isinstance(it, dict) and it.get("id") == tid:
                return i
    return patch.get("target_index", 0) or 0


def apply_chat_patch(data: dict, patch: dict):
    """Aplica un patch del chat asesor al diccionario del CV."""
    field = patch.get("field")
    action = patch.get("action", "append")
    content = patch.get("content", "")
    idx = patch.get("target_index", 0) or 0  # default para summary/project_new

    if field == "summary":
        if action == "replace":
            data["summary"] = content
        else:
            data["summary"] = data.get("summary", "") + "\n" + content

    elif field == "experience_bullet":
        exps = data.get("experiences", [])
        idx = _resolve_patch_index(patch, exps)
        if 0 <= idx < len(exps):
            if action == "replace":
                exps[idx]["bullets"] = content
            else:
                current = exps[idx].get("bullets", "").rstrip()
                exps[idx]["bullets"] = current + "\n" + content if current else content

    elif field == "experience_title":
        exps = data.get("experiences", [])
        idx = _resolve_patch_index(patch, exps)
        if 0 <= idx < len(exps):
            exps[idx]["title"] = content

    elif field == "skill_line":
        skills = data.get("skills", [])
        idx = _resolve_patch_index(patch, skills)
        if 0 <= idx < len(skills):
            if action == "replace":
                skills[idx]["text"] = content
            else:
                skills[idx]["text"] = skills[idx].get("text", "") + ", " + content

    elif field == "project_description":
        projs = data.get("projects", [])
        idx = _resolve_patch_index(patch, projs)
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
