"""
Módulo de análisis de vacantes y chat asesor con IA.
Usa Ollama Cloud API nativa (https://ollama.com/api/chat).
"""

import json
import os
import uuid
from datetime import datetime

from pydantic import ValidationError

from llm_client import (
    CV_DEBUG as _CV_DEBUG,
    HTTPX_AVAILABLE as AI_AVAILABLE,
    LLMError,
    _parse_json_response,
    call_ollama,
    get_logger,
)
from validation import (
    VacancyAnalysisResponse,
    DetailedEvalResponse,
    BankSelectionResponse,
)
from metrics_guard import find_fabricated_metrics

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
logger = get_logger("ai_analyzer")

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════

DEFAULT_MODEL = "gpt-oss:120b-cloud"
_CONFIG_FILE = ".ai_config.json"


def _config_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), _CONFIG_FILE)


def load_ai_config() -> dict:
    config = {}
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    env_key = os.getenv("OLLAMA_API_KEY")
    if env_key:
        config["api_key"] = env_key
    return config


def save_ai_config(api_key: str, model: str):
    env_key = os.getenv("OLLAMA_API_KEY")
    # Si la key ingresada es la misma que la variable de entorno, no guardarla en disco
    saved_key = "" if (env_key and api_key == env_key) else api_key
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump({"api_key": saved_key, "model": model}, f)


# Temperatura 0 + seed fijo para tareas de análisis/JSON (score, eval, selección de banco):
# el mismo CV + vacante debe dar el MISMO score entre corridas. La generación de texto libre
# (summary, cover letter) usa CHAT_OPTIONS y mantiene creatividad — no se ve afectada.
ANALYSIS_OPTIONS = {"temperature": 0, "top_p": 0.9, "seed": 42}
# Temperatura media para chat y generación de texto libre.
CHAT_OPTIONS = {"temperature": 0.5}


def _call_validated(
    messages: list,
    *,
    model: str,
    api_key: str,
    options: dict,
    response_model,
    request_id: str,
    timeout: float = 180.0,
) -> dict:
    """Llama al LLM en modo JSON, parsea y valida con un modelo Pydantic (V2-08).

    Si la respuesta no cumple el esquema, reintenta UNA vez pidiendo al modelo
    que corrija. Si vuelve a fallar, lanza ValueError con un mensaje legible.
    Devuelve el dict ya parseado (sin reformar, para no romper el pipeline).
    """
    raw = call_ollama(messages, model=model, api_key=api_key, json_mode=True,
                       options=options, request_id=request_id, timeout=timeout)
    parsed = _parse_json_response(raw)
    try:
        response_model.model_validate(parsed)
        return parsed
    except ValidationError as first_err:
        logger.warning("VALIDATE [%s] esquema inválido, reintentando: %s",
                       request_id, first_err)
        retry_messages = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": (
                "Tu respuesta anterior no cumplió el esquema JSON requerido "
                f"({first_err.error_count()} errores). Devuelve SOLO el JSON válido, "
                "con exactamente los campos y tipos pedidos, sin texto adicional."
            )},
        ]
        raw2 = call_ollama(retry_messages, model=model, api_key=api_key, json_mode=True,
                           options=options, request_id=request_id, timeout=timeout)
        parsed2 = _parse_json_response(raw2)
        try:
            response_model.model_validate(parsed2)
            return parsed2
        except ValidationError as second_err:
            logger.error("VALIDATE [%s] esquema inválido tras reintento: %s",
                         request_id, second_err)
            raise ValueError(
                "La IA devolvió una respuesta con formato inesperado. "
                "Intenta de nuevo o revisa el modelo seleccionado."
            ) from second_err


_KIND_LABEL = {
    "experience": "experiencia",
    "project": "proyecto",
    "summary": "summary",
}


def _repair_metrics_once(
    base_messages: list,
    parsed: dict,
    cv_data: dict,
    *,
    model: str,
    api_key: str,
    request_id: str,
) -> tuple[dict, list]:
    """Auto-repara métricas inventadas/trasplantadas (bug #1).

    Detecta números en las sugerencias sin respaldo en su ítem de origen y, si
    los hay, pide al modelo UNA corrección dirigida (mismo patrón de reintento
    que `_call_validated`). Si la corrección no valida o no mejora, conserva el
    resultado original. Devuelve (parsed_final, offenders_detectados_iniciales).
    """
    offenders = find_fabricated_metrics(parsed.get("suggestions", {}), cv_data)
    if not offenders:
        return parsed, []

    lines = []
    for o in offenders:
        loc = _KIND_LABEL.get(o["kind"], o["kind"])
        title = o.get("title") or ""
        where = f"{loc} «{title}»" if title and o["kind"] != "summary" else loc
        lines.append(f"- En {where}: el número «{o['metric']}» NO existe en la "
                     f"evidencia original de ESE ítem. Fragmento: \"{o['snippet']}\"")

    repair_msg = (
        "REVISIÓN ANTI-FABRICACIÓN DE MÉTRICAS. Las siguientes cifras que incluiste "
        "no tienen respaldo en el ítem de origen del CV (están inventadas o "
        "trasplantadas desde otra experiencia/proyecto):\n"
        + "\n".join(lines)
        + "\n\nCorrige SOLO esos casos: elimina el número o sustitúyelo por uno que "
        "aparezca TEXTUALMENTE en la evidencia original de ESE MISMO ítem. Si el ítem "
        "no tiene una métrica real, deja el bullet/descripción en forma cualitativa, sin "
        "número. No inventes ni muevas cifras entre ítems. No modifiques nada más. "
        "Devuelve el JSON COMPLETO corregido, con el mismo esquema."
    )

    retry_messages = base_messages + [
        {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)},
        {"role": "user", "content": repair_msg},
    ]
    logger.info("METRIC_REPAIR [%s] %d métrica(s) sin respaldo, reparando", request_id, len(offenders))
    try:
        raw2 = call_ollama(retry_messages, model=model, api_key=api_key, json_mode=True,
                           options=ANALYSIS_OPTIONS, request_id=request_id, timeout=180.0)
        parsed2 = _parse_json_response(raw2)
        VacancyAnalysisResponse.model_validate(parsed2)
    except (LLMError, ValidationError, ValueError) as err:
        logger.warning("METRIC_REPAIR [%s] reparación falló (%s), se conserva original", request_id, err)
        return parsed, offenders

    remaining = find_fabricated_metrics(parsed2.get("suggestions", {}), cv_data)
    logger.info("METRIC_REPAIR [%s] offenders %d → %d tras reparar", request_id, len(offenders), len(remaining))
    return parsed2, offenders


def _load_prompt(filename: str, fallback_content: str) -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return fallback_content

_SYSTEM_PROMPT_FALLBACK = """Eres un experto en reclutamiento, sistemas ATS y redacción de CVs formato Harvard.
Tu trabajo es adaptar el CV para maximizar el match ATS, siendo HONESTO y estratégico."""

SYSTEM_PROMPT = _load_prompt("analyze.md", _SYSTEM_PROMPT_FALLBACK)

USER_PROMPT_TEMPLATE = """\
FECHA ACTUAL: {current_date}

VACANTE:
{vacancy_text}

CV DEL CANDIDATO (JSON):
{cv_json}

Analiza la vacante contra el CV y responde con este JSON exacto.
IMPORTANTE — RESTRICCIONES DE 1 PÁGINA para las sugerencias:
- Sugiere máximo 5 bullets para la experiencia más relevante y 3 para la segunda.
- Sugiere máximo 2 proyectos (los más relevantes al JD). NO incluyas proyectos que no aporten al match.
- 1 línea de skills técnicas.

JSON:
{{
  "match_score": <0-100>,
  "viable": <true/false>,
  "matching_keywords": ["keyword1", "keyword2"],
  "missing_keywords": ["keyword1", "keyword2"],
  "suggestions": {{
    "summary": "<resumen adaptado (2 líneas máx, con título de cargo de la vacante) o null si no necesita cambio>",
    "experiences": [
      {{"index": 0, "title": "<título del cargo adaptado al idioma y vacante>", "bullets": "<máx 5 bullets en 3ra persona con métricas, uno por línea>"}}
    ],
    "projects": [
      {{"index": 0, "description": "<descripción adaptada con métrica> (MÁXIMO 2 proyectos)"}}
    ],
    "skills": ["<línea de skills con labels EN EL IDIOMA DE LA VACANTE: vacante en inglés → 'Core skills: ... | Working knowledge: ... | Exposure to: ...'; vacante en español → 'Dominio avanzado: ... | Dominio intermedio: ... | Familiaridad: ...'. DEBE ser un ARRAY de strings, NUNCA un string suelto>"]
  }},
  "reasoning": "<explicación breve de tu análisis>"
}}"""


def build_analysis_prompt(cv_data: dict, vacancy_text: str) -> str:
    cv_clean = {k: v for k, v in cv_data.items() if k != "id"}
    cv_json = json.dumps(cv_clean, ensure_ascii=False, indent=2)
    current_date = datetime.now().strftime("%B %Y")
    return USER_PROMPT_TEMPLATE.format(
        vacancy_text=vacancy_text, cv_json=cv_json, current_date=current_date
    )


def analyze_vacancy(cv_data: dict, vacancy_text: str, api_key: str, model: str, extra_context: str = "") -> dict:
    """Envía CV + vacante a Ollama Cloud y retorna el análisis parseado."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Ollama Cloud")

    user_prompt = build_analysis_prompt(cv_data, vacancy_text)
    if extra_context:
        user_prompt += (
            "\n\nCONTEXTO ADICIONAL DEL CANDIDATO:\n"
            f"{extra_context}\n"
            "IMPORTANTE: El candidato confirma tener estas habilidades/experiencias adicionales. "
            "Incorpóralas en tus sugerencias manteniendo las reglas anti-overfitting."
        )
    request_id = uuid.uuid4().hex[:8]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("ANALYZE [%s] modelo=%s cv_keys=%s prompt_len=%d",
                request_id, model, list(cv_data.keys()), len(user_prompt))

    if _CV_DEBUG:
        req_file = os.path.join(_LOG_DIR, f"request_{ts}.json")
        with open(req_file, "w", encoding="utf-8") as f:
            json.dump({
                "request_id": request_id,
                "timestamp": ts,
                "model": model,
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt": user_prompt,
            }, f, ensure_ascii=False, indent=2)
        logger.debug("[%s] Request completo guardado en: %s", request_id, req_file)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    parsed = _call_validated(
        messages, model=model, api_key=api_key, options=ANALYSIS_OPTIONS,
        response_model=VacancyAnalysisResponse, request_id=request_id,
    )

    # Auto-reparación anti-fabricación de métricas (bug #1)
    parsed, _metric_offenders = _repair_metrics_once(
        messages, parsed, cv_data, model=model, api_key=api_key, request_id=request_id,
    )

    if _CV_DEBUG:
        resp_file = os.path.join(_LOG_DIR, f"response_{ts}.json")
        with open(resp_file, "w", encoding="utf-8") as f:
            json.dump({"request_id": request_id, "timestamp": ts, "parsed_response": parsed},
                      f, ensure_ascii=False, indent=2)
        logger.debug("[%s] Response guardado en: %s", request_id, resp_file)

    logger.info("ANALYZE [%s] score=%s viable=%s match_kw=%d miss_kw=%d",
                request_id,
                parsed.get("match_score"), parsed.get("viable"),
                len(parsed.get("matching_keywords", [])),
                len(parsed.get("missing_keywords", [])))

    return parsed


# ═══════════════════════════════════════════════════════════════
# CHAT ASESOR DE CV
# ═══════════════════════════════════════════════════════════════

_CHAT_SYSTEM_PROMPT_FALLBACK = """Eres un asesor de CV experto en formato Harvard, ATS y reclutamiento tech.
Tu rol es ser un mentor honesto que ayuda al candidato a mejorar su CV."""

CHAT_SYSTEM_PROMPT = _load_prompt("chat.md", _CHAT_SYSTEM_PROMPT_FALLBACK)

_SUMMARY_SYSTEM_PROMPT_FALLBACK = """Eres un experto en reclutamiento y redacción de CVs.
Tu trabajo es generar un resumen profesional de 2-3 oraciones."""

SUMMARY_SYSTEM_PROMPT = _load_prompt("summary.md", _SUMMARY_SYSTEM_PROMPT_FALLBACK)

_COVER_LETTER_SYSTEM_PROMPT_FALLBACK = """Eres un experto en reclutamiento y redacción de cartas de presentación.
Tu trabajo es generar una Cover Letter profesional, concisa y personalizada."""

COVER_LETTER_SYSTEM_PROMPT = _load_prompt("cover_letter.md", _COVER_LETTER_SYSTEM_PROMPT_FALLBACK)


def generate_text(
    cv_data: dict,
    api_key: str,
    model: str,
    system_prompt: str,
    user_instruction: str,
    vacancy_text: str = "",
) -> str:
    """Genera texto libre (summary, cover letter, etc.) usando el LLM."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Ollama Cloud")

    context_msg = build_chat_context_message(cv_data, vacancy_text)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{context_msg}\n\n{user_instruction}"},
    ]

    request_id = uuid.uuid4().hex[:8]
    logger.info("GENERATE_TEXT [%s] modelo=%s", request_id, model)

    return call_ollama(messages, model=model, api_key=api_key,
                       options=CHAT_OPTIONS, request_id=request_id)


_REFINE_CHAT_SYSTEM_PROMPT_FALLBACK = """Eres un asesor experto en CVs y ATS que ayuda a refinar el análisis de una vacante.
CONTEXTO: El candidato ya analizó su CV contra una vacante y obtuvo un resultado inicial."""

REFINE_CHAT_SYSTEM_PROMPT = _load_prompt("refine_chat.md", _REFINE_CHAT_SYSTEM_PROMPT_FALLBACK)


def build_chat_context_message(cv_data: dict, vacancy_text: str = "") -> str:
    """Construye el mensaje de contexto con CV y vacante opcional."""
    cv_clean = {k: v for k, v in cv_data.items() if k != "id"}
    cv_json = json.dumps(cv_clean, ensure_ascii=False, indent=2)
    current_date = datetime.now().strftime("%B %Y")
    parts = [f"FECHA ACTUAL: {current_date}\n\nCV DEL CANDIDATO:\n{cv_json}"]
    if vacancy_text and vacancy_text.strip():
        parts.append(f"\nVACANTE CARGADA:\n{vacancy_text.strip()}")
    return "\n".join(parts)


def chat_with_advisor(
    cv_data: dict,
    chat_history: list,
    api_key: str,
    model: str,
    vacancy_text: str = "",
    system_prompt_override: str = "",
    analysis_context: str = "",
) -> str:
    """Envía historial de chat a Ollama Cloud y retorna respuesta en texto."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Ollama Cloud")

    context_msg = build_chat_context_message(cv_data, vacancy_text)
    if analysis_context:
        context_msg += f"\n\nRESULTADO DEL ANÁLISIS PREVIO:\n{analysis_context}"

    sys_prompt = system_prompt_override or CHAT_SYSTEM_PROMPT

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": context_msg},
        {"role": "assistant", "content": "Entendido. Tengo tu CV cargado. ¿En qué puedo ayudarte?"},
    ]
    messages.extend(chat_history)

    request_id = uuid.uuid4().hex[:8]
    logger.info("CHAT [%s] modelo=%s msgs=%d", request_id, model, len(messages))

    return call_ollama(messages, model=model, api_key=api_key,
                       options=CHAT_OPTIONS, request_id=request_id)


# ═══════════════════════════════════════════════════════════════
# EXTRACCIÓN DE PATCH DESDE SUGERENCIA DEL CHAT
# ═══════════════════════════════════════════════════════════════

EXTRACT_PATCH_PROMPT = """\
A partir del mensaje del asesor de CV, extrae UNA acción concreta para aplicar al CV.

Responde SOLO con JSON válido, sin markdown:
{{
  "field": "experience_bullet" | "summary" | "skill_line" | "project_description" | "project_new" | "experience_title",
  "target_index": <índice del elemento (0-based), o null si es summary>,
  "action": "replace" | "append",
  "content": "<texto exacto a insertar o reemplazar>"
}}

Si el mensaje no contiene una sugerencia aplicable, responde: {{"field": null}}

MENSAJE DEL ASESOR:
{advisor_message}

CV ACTUAL (para referencia de índices):
{cv_json}"""


def extract_chat_patch(
    advisor_message: str,
    cv_data: dict,
    api_key: str,
    model: str,
) -> dict | None:
    """Extrae un patch JSON de una sugerencia del chat."""
    if not AI_AVAILABLE:
        return None

    cv_clean = {k: v for k, v in cv_data.items() if k != "id"}
    cv_json = json.dumps(cv_clean, ensure_ascii=False, indent=2)
    prompt = EXTRACT_PATCH_PROMPT.format(
        advisor_message=advisor_message, cv_json=cv_json
    )

    request_id = uuid.uuid4().hex[:8]
    logger.info("EXTRACT_PATCH [%s]", request_id)

    raw = call_ollama(
        [{"role": "user", "content": prompt}],
        model=model, api_key=api_key, json_mode=True,
        options=ANALYSIS_OPTIONS, request_id=request_id, timeout=60.0,
    )

    parsed = _parse_json_response(raw)
    if parsed.get("field") is None:
        return None
    return parsed


# ═══════════════════════════════════════════════════════════════
# EVALUACIÓN DETALLADA DEL CV
# ═══════════════════════════════════════════════════════════════

_EVAL_SYSTEM_PROMPT_FALLBACK = """Eres un evaluador experto de CVs contra vacantes. Tu trabajo es producir una evaluación DETALLADA, HONESTA y ESTRUCTURADA del match entre un CV y una vacante."""

EVAL_SYSTEM_PROMPT = _load_prompt("eval.md", _EVAL_SYSTEM_PROMPT_FALLBACK)

EVAL_USER_PROMPT_TEMPLATE = """\
FECHA ACTUAL: {current_date}

VACANTE:
{vacancy_text}

CV DEL CANDIDATO (JSON):
{cv_json}

Evalúa el CV contra la vacante y responde con este JSON exacto:
{{
  "overall_score": <0-100>,
  "score_label": "<frase corta describiendo el nivel de match>",
  "dimensions": [
    {{"name": "<skill/requisito clave>", "score": <0-100>, "status": "ok|warn|bad"}}
  ],
  "requirements": [
    {{"name": "<requisito del JD>", "status": "ok|warn|bad", "note": "<explicación breve>"}}
  ],
  "overfitting": [
    {{"severity": "warn|bad", "claim": "<claim sospechoso en el CV>", "reason": "<por qué es sospechoso>"}}
  ],
  "verdicts": [
    {{"type": "ok|warn|bad", "title": "<título>", "text": "<explicación>"}}
  ]
}}"""


def evaluate_cv_detailed(
    cv_data: dict, vacancy_text: str, api_key: str, model: str
) -> dict:
    """Envía CV + vacante a Ollama Cloud y retorna evaluación detallada."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Ollama Cloud")

    cv_clean = {k: v for k, v in cv_data.items() if k != "id"}
    cv_json = json.dumps(cv_clean, ensure_ascii=False, indent=2)
    current_date = datetime.now().strftime("%B %Y")
    user_prompt = EVAL_USER_PROMPT_TEMPLATE.format(
        vacancy_text=vacancy_text, cv_json=cv_json, current_date=current_date
    )

    request_id = uuid.uuid4().hex[:8]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("EVAL [%s] modelo=%s", request_id, model)

    if _CV_DEBUG:
        req_file = os.path.join(_LOG_DIR, f"eval_request_{ts}.json")
        with open(req_file, "w", encoding="utf-8") as f:
            json.dump({
                "request_id": request_id,
                "timestamp": ts,
                "model": model,
                "system_prompt": EVAL_SYSTEM_PROMPT,
                "user_prompt": user_prompt,
            }, f, ensure_ascii=False, indent=2)
        logger.debug("[%s] Eval request guardado en: %s", request_id, req_file)

    messages = [
        {"role": "system", "content": EVAL_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    parsed = _call_validated(
        messages, model=model, api_key=api_key, options=ANALYSIS_OPTIONS,
        response_model=DetailedEvalResponse, request_id=request_id,
    )

    if _CV_DEBUG:
        resp_file = os.path.join(_LOG_DIR, f"eval_response_{ts}.json")
        with open(resp_file, "w", encoding="utf-8") as f:
            json.dump({"request_id": request_id, "timestamp": ts, "parsed_response": parsed},
                      f, ensure_ascii=False, indent=2)

    logger.info("EVAL [%s] score=%s label=%s dims=%d reqs=%d ovf=%d vered=%d",
                request_id,
                parsed.get("overall_score"), parsed.get("score_label"),
                len(parsed.get("dimensions", [])),
                len(parsed.get("requirements", [])),
                len(parsed.get("overfitting", [])),
                len(parsed.get("verdicts", [])))

    return parsed


# ═══════════════════════════════════════════════════════════════
# SELECCIÓN DE ITEMS DEL BANCO
# ═══════════════════════════════════════════════════════════════

_BANK_SELECTION_SYSTEM_PROMPT_FALLBACK = """Eres un experto en reclutamiento, ATS y optimización de CVs formato Harvard de 1 PÁGINA.
Tu trabajo es seleccionar los items del banco del candidato que MAXIMIZAN el match ATS con la vacante, respetando el límite estricto de 1 página."""

BANK_SELECTION_SYSTEM_PROMPT = _load_prompt("bank_selection.md", _BANK_SELECTION_SYSTEM_PROMPT_FALLBACK)

BANK_SELECTION_USER_TEMPLATE = """\
VACANTE:
{vacancy_text}

BANCO DEL CANDIDATO (todos los items disponibles):
{manifest_json}

Selecciona los IDs de items que deben incluirse en el CV para esta vacante.
Responde con JSON: {{"selected_ids": ["id1", "id2", ...], "reasoning": "..."}}"""


def select_from_bank(
    manifest: list[dict], vacancy_text: str, api_key: str, model: str,
    protected_keywords: list[str] | None = None,
) -> list[str]:
    """Pide a la IA que seleccione qué items del banco activar para una vacante.

    Retorna lista de IDs seleccionados.

    `protected_keywords`: keywords que el análisis con el banco COMPLETO ya detectó
    como match. Se le exige al modelo no descartar la única evidencia de ninguno, para
    que la selección de 1 página no tire abajo el score (ver helpers.deferred_translate_and_reevaluate).
    """
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Ollama Cloud")

    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
    user_prompt = BANK_SELECTION_USER_TEMPLATE.format(
        vacancy_text=vacancy_text, manifest_json=manifest_json
    )
    if protected_keywords:
        kw_list = ", ".join(k for k in protected_keywords if k)
        if kw_list:
            user_prompt += (
                "\n\nKEYWORDS YA DEMOSTRADOS EN EL CV COMPLETO "
                "(el análisis previo los detectó como match con la vacante):\n"
                f"{kw_list}\n"
                "REGLA CRÍTICA: para CADA keyword de esta lista, incluye al menos un item del banco "
                "que lo evidencie. NO descartes la única evidencia de un keyword ya matcheado solo por "
                "ahorrar espacio — perder esa evidencia baja el match score tras adaptar. Prioriza "
                "cubrir todos estos keywords sobre incluir items redundantes. Solo si hay conflicto real "
                "de espacio (1 página estricta), conserva primero los keywords que sean must-have de la vacante."
            )

    request_id = uuid.uuid4().hex[:8]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("BANK_SELECT [%s] modelo=%s items=%d", request_id, model, len(manifest))

    if _CV_DEBUG:
        req_file = os.path.join(_LOG_DIR, f"bank_select_request_{ts}.json")
        with open(req_file, "w", encoding="utf-8") as f:
            json.dump({
                "request_id": request_id,
                "timestamp": ts,
                "model": model,
                "system_prompt": BANK_SELECTION_SYSTEM_PROMPT,
                "user_prompt": user_prompt,
            }, f, ensure_ascii=False, indent=2)
        logger.debug("[%s] Bank select request guardado en: %s", request_id, req_file)

    messages = [
        {"role": "system", "content": BANK_SELECTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    parsed = _call_validated(
        messages, model=model, api_key=api_key, options=ANALYSIS_OPTIONS,
        response_model=BankSelectionResponse, request_id=request_id,
    )

    if _CV_DEBUG:
        resp_file = os.path.join(_LOG_DIR, f"bank_select_response_{ts}.json")
        with open(resp_file, "w", encoding="utf-8") as f:
            json.dump({"request_id": request_id, "timestamp": ts, "parsed_response": parsed},
                      f, ensure_ascii=False, indent=2)

    selected_ids = parsed.get("selected_ids", [])
    reasoning = parsed.get("reasoning", "")

    logger.info("BANK_SELECT [%s] ids=%d reasoning=%.200s", request_id, len(selected_ids), reasoning or "")

    return selected_ids
