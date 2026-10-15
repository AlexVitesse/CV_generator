"""
Guard determinista anti-fabricación de métricas (bug #1).

Detecta números/métricas en las sugerencias de la IA que NO existen en la
evidencia original del MISMO ítem del CV — es decir, métricas inventadas o
trasplantadas de otra experiencia/proyecto (visto en logs reales: las
"1,200 solicitudes diarias" de Ingeniería Cóndor apareciendo bajo ZAPI, o
porcentajes 30%/25%/100% que no existen en ningún bullet de origen).

Es un módulo PURO (sin Streamlit) para poder usarse tanto en el pipeline de
análisis (ai_analyzer, para la auto-reparación) como en los tests.
"""

import re

# Capta la parte numérica de una métrica: "1,200", "15.000", "99.5", "0.01", "200".
_NUM_RE = re.compile(r"\d[\d.,]*")


def _digit_key(raw: str) -> str:
    """Reduce un token numérico a solo sus dígitos para comparar de forma
    robusta entre separadores: '1,200' y '1.200' y '1200' → '1200'."""
    return re.sub(r"\D", "", raw)


def extract_metrics(text) -> list[dict]:
    """Extrae métricas de un texto (o lista de bullets).

    Devuelve una lista de dicts: {"raw": "99.5%", "key": "995", "is_pct": True}.
    Solo se consideran métricas "fuertes" (las que importan para un CV):
    cualquier porcentaje, o números de 2+ dígitos. Los dígitos sueltos
    ("3 fases", "4 servicios", "2 años") se ignoran por ser conteos
    estructurales de bajo riesgo.
    """
    if isinstance(text, (list, tuple)):
        text = " ".join(_as_text(x) for x in text)
    text = _as_text(text)

    out = []
    for m in _NUM_RE.finditer(text):
        raw = m.group()
        is_pct = text[m.end():m.end() + 1] == "%"
        key = _digit_key(raw)
        if not key:
            continue
        # Filtro de relevancia: porcentajes (de cualquier magnitud) o 2+ dígitos.
        if not is_pct and len(key) < 2:
            continue
        out.append({"raw": raw + ("%" if is_pct else ""), "key": key, "is_pct": is_pct})
    return out


def _as_text(value) -> str:
    """Convierte un campo del CV (str, lista de bullets-dict, etc.) a texto plano."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("text", "")
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(x) for x in value)
    return str(value)


def _source_keys(*texts) -> set[str]:
    """Conjunto de digit-keys presentes en la evidencia de origen."""
    keys = set()
    for txt in texts:
        for met in extract_metrics(txt):
            keys.add(met["key"])
    return keys


def _exp_source_text(exp: dict) -> str:
    return " ".join(_as_text(exp.get(f)) for f in ("company", "title", "bullets"))


def _proj_source_text(proj: dict) -> str:
    return " ".join(_as_text(proj.get(f)) for f in ("name", "description"))


def _whole_cv_keys(cv_data: dict) -> set[str]:
    parts = [_as_text(cv_data.get("summary"))]
    for exp in cv_data.get("experiences", []):
        parts.append(_exp_source_text(exp))
    for proj in cv_data.get("projects", []):
        parts.append(_proj_source_text(proj))
    for sk in cv_data.get("skills", []):
        parts.append(_as_text(sk))
    return _source_keys(*parts)


# ═══════════════════════════════════════════════════════════════
# RESOLUCIÓN DE SUGERENCIA → ÍTEM DE ORIGEN (anti-misatribución)
# ═══════════════════════════════════════════════════════════════
# El modelo numera "index" según SU ranking de relevancia, no la posición del
# array d["experiences"]/d["projects"]; además a veces no devuelve nada estable.
# Anclar por "id" (que el modelo VE en el CV JSON) evita que un bullet de una
# empresa aterrice bajo otra. Si falta el id, se usa la proveniencia de contenido
# (solapamiento de tokens discriminantes como FastAPI, Oracle, ESP32, RunPod...,
# que sobreviven a la reescritura y a la traducción). Si nada es confiable → None
# (descartar es más seguro que mal-asignar). NUNCA se confía en "index".

_TOKEN_RE = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ0-9+#./]+")
_STOP = frozenset(
    "de la el en y a los las con para por una uno del al que se su sus como mas más "
    "the and of to in for with an at on by from as is are was were be this that".split()
)
_MIN_OVERLAP = 0.12   # solapamiento mínimo para confiar en el match por contenido
_MARGIN = 0.06        # ventaja mínima sobre el segundo mejor (evita ambigüedad)


def _content_tokens(text) -> set[str]:
    """Tokens discriminantes de un texto: alfanuméricos de 3+ chars, sin stopwords."""
    toks = set()
    for m in _TOKEN_RE.finditer(_as_text(text).lower()):
        t = m.group()
        if len(t) >= 3 and t not in _STOP:
            toks.add(t)
    return toks


def resolve_target_index(
    suggestion: dict, items: list, *, kind: str, fallback: str = "content",
) -> int | None:
    """Mapea una sugerencia de la IA al ítem de origen correcto.

    `kind`: "experience" o "project". Siempre intenta primero anclar por `id`.
    `fallback` decide qué hacer cuando no hay id (o no matchea):
    - "content" (default): proveniencia de contenido — ¿a qué ítem pertenece de verdad?
      Es lo correcto para APLICAR la sugerencia (diff_viewer): evita mal-asignar.
    - "index": usa el `index` crudo del modelo (el ítem que el modelo PRETENDÍA).
      Es lo correcto para el guard anti-fabricación de métricas: si el modelo dice
      "esto es de ZAPI" y mete una cifra de Cóndor, hay que detectar el trasplante,
      no re-resolver hacia Cóndor y darlo por bueno.

    Devuelve el índice en `items` o None si no se puede resolver con confianza
    (el caller debe descartar, NO caer a items[0]).
    """
    if not items:
        return None

    # 1) Ancla por id (el modelo ve el id en el CV JSON).
    sid = suggestion.get("id")
    if sid:
        for i, it in enumerate(items):
            if isinstance(it, dict) and it.get("id") == sid:
                return i

    # Fallback por índice crudo del modelo (intención declarada).
    def _by_index():
        idx = suggestion.get("index")
        if isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < len(items):
            return idx
        return None

    # Fallback por proveniencia de contenido. Solo los bullets/description (la señal
    # discriminante real: FastAPI, ESP32, CASA Tier 2...); el título adaptado es genérico
    # ("AI Engineer", "Backend") y solo mete ruido.
    def _by_content():
        if kind == "experience":
            sug_text = _as_text(suggestion.get("bullets"))
            src_fn = _exp_source_text
        else:
            sug_text = _as_text(suggestion.get("description"))
            src_fn = _proj_source_text
        sug_tokens = _content_tokens(sug_text)
        if not sug_tokens:
            return None
        scored = sorted(
            (
                (len(sug_tokens & _content_tokens(src_fn(it))) / len(sug_tokens), i)
                for i, it in enumerate(items)
                if isinstance(it, dict)
            ),
            reverse=True,
        )
        if not scored:
            return None
        best = scored[0]
        second = scored[1] if len(scored) > 1 else (0.0, -1)
        if best[0] >= _MIN_OVERLAP and (best[0] - second[0]) >= _MARGIN:
            return best[1]
        return None

    # Encadena AMBOS fallbacks (no se detiene tras el primero) para que el prompt nuevo,
    # que ya no emite "index", no deje sugerencias sin resolver. `fallback` solo fija la
    # PRIORIDAD: el guard de métricas prefiere el index declarado (detecta trasplantes);
    # el diff viewer prefiere el contenido (aplica al ítem correcto).
    order = (_by_index, _by_content) if fallback == "index" else (_by_content, _by_index)
    for fn in order:
        r = fn()
        if r is not None:
            return r
    return None


def find_fabricated_metrics(suggestions: dict, cv_data: dict) -> list[dict]:
    """Devuelve las métricas sugeridas sin respaldo en su ítem de origen.

    Cada hallazgo: {"kind", "index", "title", "metric", "snippet"}.
    - experiences/projects: la evidencia es el MISMO ítem (resuelto por id/contenido,
      no por el index crudo del modelo) → detecta trasplantes entre ítems aunque el
      número exista en otra parte del CV.
    - summary: se compara contra TODO el CV (es transversal por naturaleza).
    """
    offenders = []
    exps = cv_data.get("experiences", [])
    projs = cv_data.get("projects", [])

    for sug in suggestions.get("experiences", []) or []:
        idx = resolve_target_index(sug, exps, kind="experience", fallback="index")
        if idx is None:
            continue
        src_keys = _source_keys(_exp_source_text(exps[idx]))
        for met in extract_metrics(sug.get("bullets", "")):
            if met["key"] not in src_keys:
                offenders.append({
                    "kind": "experience", "index": idx,
                    "title": sug.get("title") or exps[idx].get("title", ""),
                    "metric": met["raw"], "snippet": _snippet(sug.get("bullets", ""), met["raw"]),
                })

    for sug in suggestions.get("projects", []) or []:
        idx = resolve_target_index(sug, projs, kind="project", fallback="index")
        if idx is None:
            continue
        src_keys = _source_keys(_proj_source_text(projs[idx]))
        for met in extract_metrics(sug.get("description", "")):
            if met["key"] not in src_keys:
                offenders.append({
                    "kind": "project", "index": idx,
                    "title": projs[idx].get("name", ""),
                    "metric": met["raw"], "snippet": _snippet(sug.get("description", ""), met["raw"]),
                })

    summary = suggestions.get("summary")
    if summary:
        cv_keys = _whole_cv_keys(cv_data)
        for met in extract_metrics(summary):
            if met["key"] not in cv_keys:
                offenders.append({
                    "kind": "summary", "index": None, "title": "summary",
                    "metric": met["raw"], "snippet": _snippet(summary, met["raw"]),
                })

    return offenders


def _snippet(text: str, raw_metric: str, width: int = 40) -> str:
    """Extrae un fragmento de contexto alrededor de la métrica para el mensaje de reparación."""
    text = _as_text(text)
    pos = text.find(raw_metric.rstrip("%"))
    if pos < 0:
        return raw_metric
    start = max(0, pos - width)
    end = min(len(text), pos + len(raw_metric) + width)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")
