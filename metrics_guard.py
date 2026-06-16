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


def find_fabricated_metrics(suggestions: dict, cv_data: dict) -> list[dict]:
    """Devuelve las métricas sugeridas sin respaldo en su ítem de origen.

    Cada hallazgo: {"kind", "index", "title", "metric", "snippet"}.
    - experiences/projects: la evidencia es el MISMO ítem (por index) → detecta
      trasplantes entre ítems aunque el número exista en otra parte del CV.
    - summary: se compara contra TODO el CV (es transversal por naturaleza).
    """
    offenders = []
    exps = cv_data.get("experiences", [])
    projs = cv_data.get("projects", [])

    for sug in suggestions.get("experiences", []) or []:
        idx = sug.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(exps)):
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
        idx = sug.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(projs)):
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
