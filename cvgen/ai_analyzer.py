"""
Módulo de análisis de vacantes y chat asesor con IA.
Usa el proveedor de LLM configurado (Groq por defecto) vía llm_client.
"""

import glob
import json
import os
import re
import uuid
from datetime import datetime

from pydantic import ValidationError

from cvgen.llm_client import (
    CV_DEBUG as _CV_DEBUG,
    HTTPX_AVAILABLE as AI_AVAILABLE,
    LLMError,
    PROVIDERS,
    DEFAULT_PROVIDER,
    DEFAULT_MODELS,
    _parse_json_response,
    call_gemini_vision,
    call_llm,
    get_logger,
)
from cvgen.validation import (
    VacancyAnalysisResponse,
    DetailedEvalResponse,
    BankSelectionResponse,
)
from cvgen.metrics_guard import find_fabricated_metrics

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
logger = get_logger("ai_analyzer")

# Dumps de depuración: se conservan los N más recientes (ai.log ya rota solo; estos
# .json no rotaban y crecían sin techo mientras CV_DEBUG estuviera activo).
_DEBUG_DUMP_KEEP = 40


def _dump_debug(kind: str, ts: str, request_id: str, payload: dict) -> None:
    """Escribe un dump `{kind}_{ts}.json` en logs/ y poda los más viejos de su tipo."""
    if not _CV_DEBUG:
        return
    try:
        path = os.path.join(_LOG_DIR, f"{kind}_{ts}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"request_id": request_id, "timestamp": ts, **payload},
                      f, ensure_ascii=False, indent=2)
        logger.debug("[%s] %s guardado en: %s", request_id, kind, path)
        old = sorted(glob.glob(os.path.join(_LOG_DIR, f"{kind}_*.json")))[:-_DEBUG_DUMP_KEEP]
        for f_old in old:
            os.remove(f_old)
    except OSError as e:  # el debug NUNCA debe tumbar un análisis
        logger.warning("no se pudo escribir/podar el dump %s: %s", kind, e)

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════

DEFAULT_MODEL = DEFAULT_MODELS["ollama"]  # retrocompat (lo usaba la UI/app)
_CONFIG_FILE = ".ai_config.json"


def _config_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), _CONFIG_FILE)


def _default_providers_cfg() -> dict:
    return {p: {"api_key": "", "model": DEFAULT_MODELS[p]} for p in PROVIDERS}


def load_ai_config() -> dict:
    """Carga la config IA multi-proveedor.

    Devuelve {"provider", "providers": {p: {"api_key","model"}}, "api_key","model"}
    (los dos últimos resuelven el proveedor ACTIVO, por retrocompat con app.py).
    Migra el formato antiguo {"api_key","model"} a providers.ollama.
    """
    raw = {}
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    providers = _default_providers_cfg()
    fallback = DEFAULT_PROVIDER
    if isinstance(raw.get("providers"), dict):
        for p, vals in raw["providers"].items():
            if p in providers and isinstance(vals, dict):
                providers[p]["api_key"] = vals.get("api_key", "")
                providers[p]["model"] = vals.get("model") or DEFAULT_MODELS[p]
    elif raw.get("api_key") is not None or raw.get("model") is not None:
        # Formato antiguo (un solo proveedor: Ollama).
        providers["ollama"]["api_key"] = raw.get("api_key", "")
        providers["ollama"]["model"] = raw.get("model") or DEFAULT_MODELS["ollama"]
        fallback = "ollama"  # sus credenciales son de Ollama: no saltar a Groq sin key

    # La variable de entorno OLLAMA_API_KEY sigue teniendo prioridad para Ollama.
    env_key = os.getenv("OLLAMA_API_KEY")
    if env_key:
        providers["ollama"]["api_key"] = env_key

    provider = raw.get("provider") if raw.get("provider") in PROVIDERS else fallback
    active = providers[provider]
    return {
        "provider": provider,
        "providers": providers,
        "api_key": active["api_key"],
        "model": active["model"],
    }


def save_ai_config(provider: str, api_key: str, model: str):
    """Persiste la config del proveedor indicado y lo marca como activo.

    Conserva las credenciales de los demás proveedores (lee el disco y actualiza
    solo el proveedor dado), para no perderlas al cambiar de proveedor.
    """
    provider = provider if provider in PROVIDERS else DEFAULT_PROVIDER
    cfg = load_ai_config()
    providers = cfg["providers"]

    providers[provider] = {"api_key": api_key, "model": model or DEFAULT_MODELS[provider]}

    # Nunca persistir a disco la key de Ollama que viene de la variable de entorno
    # (load_ai_config la re-inyecta en providers['ollama']). Se aplica sin importar qué
    # proveedor se esté guardando: al guardar OpenAI/Gemini también se reescribe el mapa
    # completo, y sin esto la key de entorno quedaría en claro en .ai_config.json.
    env_key = os.getenv("OLLAMA_API_KEY")
    if env_key and providers.get("ollama", {}).get("api_key") == env_key:
        providers["ollama"]["api_key"] = ""

    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump({"provider": provider, "providers": providers}, f, ensure_ascii=False, indent=2)


# Temperatura 0 + seed fijo para tareas de análisis/JSON (score, eval, selección de banco):
# el mismo CV + vacante debe dar el MISMO score entre corridas. La generación de texto libre
# (summary, cover letter) usa CHAT_OPTIONS y mantiene creatividad — no se ve afectada.
ANALYSIS_OPTIONS = {"temperature": 0, "top_p": 0.9, "seed": 42}
# Temperatura media para chat y generación de texto libre.
CHAT_OPTIONS = {"temperature": 0.5}


def _log_json_error_context(raw_str: str, err: json.JSONDecodeError, request_id: str, log_fn):
    pos = err.pos
    start = max(0, pos - 150)
    end = min(len(raw_str), pos + 150)
    snippet = raw_str[start:end]
    # Reemplazar newlines para que quepa en una o pocas líneas legibles en logs
    snippet_clean = snippet.replace("\r", "").replace("\n", " \\n ")
    offset_in_clean = 0
    for idx in range(pos - start):
        ch = snippet[idx]
        if ch == "\n":
            offset_in_clean += 4 # ' \\n ' tiene largo 4
        elif ch != "\r":
            offset_in_clean += 1
    pointer = " " * offset_in_clean + "^"
    log_fn("JSON ERROR CONTEXT [%s] (alrededor de char %d):\nSnippet: %s\nPointer: %s",
           request_id, pos, snippet_clean, pointer)


def _call_validated(
    messages: list,
    *,
    provider: str | None = None,
    model: str,
    api_key: str,
    options: dict,
    response_model,
    request_id: str,
    timeout: float = 180.0,
) -> dict:
    """Llama al LLM en modo JSON, parsea y valida con un modelo Pydantic (V2-08).

    Si la respuesta no es JSON válido O no cumple el esquema, reintenta UNA vez
    pidiendo al modelo que corrija. Si vuelve a fallar, lanza ValueError con un
    mensaje legible. Devuelve el dict ya parseado (sin reformar).

    Nota: algunos modelos (Gemini/gpt-oss) emiten ocasionalmente JSON malformado
    —una coma faltante, una comilla sin escapar— que el parser tolerante tampoco
    puede arreglar. Antes ese caso reventaba sin reintento ni log; ahora se trata
    igual que un error de esquema.
    """
    raw = call_llm(messages, provider=provider, model=model, api_key=api_key, json_mode=True,
                   options=options, request_id=request_id, timeout=timeout)
    try:
        parsed = _parse_json_response(raw)
        response_model.model_validate(parsed)
        return parsed
    except (ValidationError, json.JSONDecodeError) as first_err:
        logger.warning("VALIDATE [%s] respuesta inválida (%s), reintentando: %s",
                       request_id, type(first_err).__name__, first_err)
        if isinstance(first_err, json.JSONDecodeError):
            _log_json_error_context(raw, first_err, request_id, logger.warning)
        else:
            logger.warning("VALIDATE [%s] raw response 1 (ValidationError): %r", request_id, raw)

        retry_messages = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": (
                "Tu respuesta anterior NO fue JSON válido o no cumplió el esquema requerido. "
                "Devuelve SOLO el JSON válido y bien formado (comas y comillas correctas, "
                "sin comas finales), con exactamente los campos y tipos pedidos, sin markdown "
                "ni texto adicional."
            )},
        ]
        # Con temperatura 0 + seed fijo el modelo regenera el MISMO JSON roto (mismo
        # error en el mismo carácter), así que el reintento sería inútil. Variamos el
        # sampling solo para esta corrección para que produzca una salida distinta.
        retry_options = {**options, "temperature": 0.4}
        retry_options.pop("seed", None)
        raw2 = call_llm(retry_messages, provider=provider, model=model, api_key=api_key, json_mode=True,
                        options=retry_options, request_id=request_id, timeout=timeout)
        try:
            parsed2 = _parse_json_response(raw2)
            response_model.model_validate(parsed2)
            return parsed2
        except (ValidationError, json.JSONDecodeError) as second_err:
            logger.error("VALIDATE [%s] respuesta inválida tras reintento (%s): %s",
                         request_id, type(second_err).__name__, second_err)
            if isinstance(second_err, json.JSONDecodeError):
                _log_json_error_context(raw2, second_err, request_id, logger.error)
            else:
                logger.error("VALIDATE [%s] raw response 2 (ValidationError): %r", request_id, raw2)
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
    provider: str | None = None,
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
        raw2 = call_llm(retry_messages, provider=provider, model=model, api_key=api_key, json_mode=True,
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
            logger.exception("No se pudo leer prompts/%s — usando fallback mínimo "
                             "(se pierden las reglas anti-fabricación)", filename)
            return fallback_content
    logger.warning("prompts/%s no existe — usando fallback mínimo "
                   "(se pierden las reglas anti-fabricación)", filename)
    return fallback_content

_SYSTEM_PROMPT_FALLBACK = """Eres un experto en reclutamiento, sistemas ATS y redacción de CVs formato Harvard.
Tu trabajo es adaptar el CV para maximizar el match ATS, siendo HONESTO y estratégico."""

SYSTEM_PROMPT = _load_prompt("analyze.md", _SYSTEM_PROMPT_FALLBACK)

_OCR_VACANCY_PROMPT_FALLBACK = """Eres un OCR especializado en descripciones de vacantes de empleo.
Transcribe TEXTUALMENTE el texto de la vacante en la imagen. Si no hay ninguna, responde: NO_VACANCY_DETECTED"""

OCR_VACANCY_PROMPT = _load_prompt("ocr_vacancy.md", _OCR_VACANCY_PROMPT_FALLBACK)


def extract_vacancy_text_from_image(
    image_bytes: bytes,
    mime_type: str,
    api_key: str,
    model: str = DEFAULT_MODELS["gemini"],
) -> str:
    """Extrae el texto de una vacante desde una imagen (OCR) vía Gemini Vision.

    Solo Gemini soporta este flujo hoy (es el único proveedor multimodal cableado
    en `llm_client`). Lanza `ValueError` si la imagen no contiene una vacante
    reconocible (`NO_VACANCY_DETECTED`).
    """
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Google Gemini")

    request_id = uuid.uuid4().hex[:8]
    logger.info("OCR_VACANCY [%s] modelo=%s mime=%s bytes=%d",
                request_id, model, mime_type, len(image_bytes))

    text = call_gemini_vision(
        image_bytes, mime_type, OCR_VACANCY_PROMPT,
        api_key=api_key, model=model, request_id=request_id,
    ).strip()

    if text == "NO_VACANCY_DETECTED":
        raise ValueError("No se detectó una vacante en la imagen. Intenta con otra captura.")
    return text


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
- Skills agrupadas en líneas separadas por tier (una por línea), escaneables — NO una sola línea larga.

JSON:
{{
  "match_score": <0-100>,
  "viable": <true/false>,
  "matching_keywords": ["keyword1", "keyword2"],
  "missing_keywords": ["keyword1", "keyword2"],
  "suggestions": {{
    "summary": "<resumen adaptado (2 líneas máx, con título de cargo de la vacante) o null si no necesita cambio>",
    "experiences": [
      {{"id": "<el id EXACTO de experiences[].id del CV JSON — identifica la empresa, NO lo inventes ni cambies>", "title": "<título REAL del cargo, idéntico al del CV — NO lo adaptes a la vacante>", "bullets": "<máx 5 bullets en 3ra persona con métricas, uno por línea>"}}
    ],
    "projects": [
      {{"id": "<el id EXACTO de projects[].id del CV JSON — identifica el proyecto, NO lo inventes ni cambies>", "description": "<descripción adaptada con métrica> (MÁXIMO 2 proyectos)"}}
    ],
    "skills": ["<UNA línea POR tier, escaneable. Inglés: 'Core skills: ...', 'Working knowledge: ...', 'Exposure to: ...'; Español: 'Dominio avanzado: ...', 'Dominio intermedio: ...', 'Familiaridad: ...'. ARRAY de strings con un elemento por tier, NUNCA un string suelto ni una sola línea con '|'>"]
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


def _normalize_suggestion_text(parsed: dict) -> None:
    """Algunos modelos (visto: gemini-3.1-pro-preview) devuelven `bullets`/`description`
    como lista en vez del string "uno por línea" que pide el prompt; el resto del
    pipeline (sanitize, diff viewer, PDF) espera string. Une la lista con saltos de línea."""
    sugg = parsed.get("suggestions") or {}
    for section, field in (("experiences", "bullets"), ("projects", "description")):
        for item in sugg.get(section) or []:
            val = item.get(field) if isinstance(item, dict) else None
            if isinstance(val, list):
                item[field] = "\n".join(
                    str(v.get("text", "") if isinstance(v, dict) else v).strip() for v in val
                ).strip()


def analyze_vacancy(cv_data: dict, vacancy_text: str, api_key: str, model: str,
                    extra_context: str = "", provider: str | None = None) -> dict:
    """Envía CV + vacante al proveedor de LLM y retorna el análisis parseado."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key del proveedor de IA")

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

    _dump_debug("request", ts, request_id,
                {"model": model, "system_prompt": SYSTEM_PROMPT, "user_prompt": user_prompt})

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    parsed = _call_validated(
        messages, provider=provider, model=model, api_key=api_key, options=ANALYSIS_OPTIONS,
        response_model=VacancyAnalysisResponse, request_id=request_id,
    )

    # Auto-reparación anti-fabricación de métricas (bug #1)
    parsed, _metric_offenders = _repair_metrics_once(
        messages, parsed, cv_data, provider=provider, model=model, api_key=api_key, request_id=request_id,
    )

    _normalize_suggestion_text(parsed)
    _dump_debug("response", ts, request_id, {"parsed_response": parsed})

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
    provider: str | None = None,
) -> str:
    """Genera texto libre (summary, cover letter, etc.) usando el LLM."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key del proveedor de IA")

    context_msg = build_chat_context_message(cv_data, vacancy_text)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{context_msg}\n\n{user_instruction}"},
    ]

    request_id = uuid.uuid4().hex[:8]
    logger.info("GENERATE_TEXT [%s] provider=%s modelo=%s", request_id, provider, model)

    return call_llm(messages, provider=provider, model=model, api_key=api_key,
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
    provider: str | None = None,
) -> str:
    """Envía historial de chat al proveedor de LLM y retorna respuesta en texto."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key del proveedor de IA")

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
    logger.info("CHAT [%s] provider=%s modelo=%s msgs=%d", request_id, provider, model, len(messages))

    return call_llm(messages, provider=provider, model=model, api_key=api_key,
                    options=CHAT_OPTIONS, request_id=request_id)


# ═══════════════════════════════════════════════════════════════
# EXTRACCIÓN DE PATCH DESDE SUGERENCIA DEL CHAT
# ═══════════════════════════════════════════════════════════════

EXTRACT_PATCH_PROMPT = """\
A partir del mensaje del asesor de CV, extrae UNA acción concreta para aplicar al CV.

Responde SOLO con JSON válido, sin markdown:
{{
  "field": "experience_bullet" | "summary" | "skill_line" | "project_description" | "project_new" | "experience_title",
  "target_id": "<el id EXACTO del elemento del CV (experiences[].id / projects[].id / skills[].id) al que aplica; identifica la empresa/proyecto. null si es summary o project_new>",
  "target_index": <índice 0-based del elemento como respaldo, o null si es summary>,
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
    provider: str | None = None,
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

    raw = call_llm(
        [{"role": "user", "content": prompt}],
        provider=provider, model=model, api_key=api_key, json_mode=True,
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
    cv_data: dict, vacancy_text: str, api_key: str, model: str, provider: str | None = None
) -> dict:
    """Envía CV + vacante al proveedor de LLM y retorna evaluación detallada."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key del proveedor de IA")

    cv_clean = {k: v for k, v in cv_data.items() if k != "id"}
    cv_json = json.dumps(cv_clean, ensure_ascii=False, indent=2)
    current_date = datetime.now().strftime("%B %Y")
    user_prompt = EVAL_USER_PROMPT_TEMPLATE.format(
        vacancy_text=vacancy_text, cv_json=cv_json, current_date=current_date
    )

    request_id = uuid.uuid4().hex[:8]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("EVAL [%s] modelo=%s", request_id, model)

    _dump_debug("eval_request", ts, request_id,
                {"model": model, "system_prompt": EVAL_SYSTEM_PROMPT, "user_prompt": user_prompt})

    messages = [
        {"role": "system", "content": EVAL_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    parsed = _call_validated(
        messages, provider=provider, model=model, api_key=api_key, options=ANALYSIS_OPTIONS,
        response_model=DetailedEvalResponse, request_id=request_id,
    )

    _dump_debug("eval_response", ts, request_id, {"parsed_response": parsed})

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

def _item_evidence_text(item: dict) -> str:
    """Texto evidenciable de un item del manifest (texto + tags), en minúsculas."""
    parts = [item.get("text", "")]
    parts.extend(item.get("tags", []) or [])
    return " ".join(str(p) for p in parts).lower()


def _covers(kw: str, text: str) -> bool:
    """¿`text` evidencia el keyword `kw` como palabra completa? Evita que "Java" quede
    "cubierto" por "JavaScript" o "Go" por "Google" (perdería el bullet real).
    Lookarounds en vez de \\b para que C++, C# y .NET también funcionen."""
    return re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", text) is not None


def _reintegrate_lost_evidence(
    manifest: list[dict], selected_ids: list[str], protected_keywords: list[str] | None,
) -> list[str]:
    """Bug C — re-agrega evidencia de keywords protegidos que la selección descartó.

    Para cada `protected_keyword` que ya NO aparezca en el texto de ningún item
    seleccionado, busca un item del manifest (no seleccionado) que sí lo evidencie y
    lo re-agrega. Función pura: devuelve la lista de ids (orden original + re-agregados).
    """
    if not protected_keywords:
        return selected_ids
    selected = set(selected_ids)
    by_id = {it["id"]: it for it in manifest if it.get("id")}
    covered = " ".join(_item_evidence_text(by_id[i]) for i in selected if i in by_id)
    readded = []
    for kw in protected_keywords:
        k = (kw or "").strip().lower()
        if not k or _covers(k, covered):
            continue
        for it in manifest:
            iid = it.get("id")
            if not iid or iid in selected:
                continue
            # Un summary re-agregado se cuela como PRIMER summary activo y pisa el que
            # el modelo eligió para la vacante (bank_to_active_cv toma active_sums[0]).
            if it.get("type") == "summary":
                continue
            if _covers(k, _item_evidence_text(it)):
                selected.add(iid)
                readded.append(iid)
                covered += " " + _item_evidence_text(it)
                # Un bullet sin su experiencia activa NO se renderiza (bank_to_active_cv
                # salta la experiencia entera): reintegrar el bullet solo era un no-op.
                parent = it.get("parent")
                if parent and parent not in selected:
                    selected.add(parent)
                    readded.append(parent)
                break
    if not readded:
        return selected_ids
    logger.info("BANK_SELECT evidencia reintegrada: %d item(s) %s para no perder keywords protegidos",
                len(readded), readded)
    # Preserva el orden original y añade los reintegrados en orden de manifest.
    orig = set(selected_ids)
    return list(selected_ids) + [it["id"] for it in manifest
                                 if it.get("id") in selected and it["id"] not in orig]


_DEDUP_STOPWORDS = {"own", "project", "proyecto", "propio", "remote", "remoto", "with"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-záéíóúñ0-9]{4,}", text.lower())
            if t not in _DEDUP_STOPWORDS}


def _drop_projects_duplicating_experience(manifest: list[dict], selected_ids: list[str],
                                          keep: frozenset = frozenset()) -> list[str]:
    """Quita proyectos que repiten una experiencia ya seleccionada (mismo producto/empresa).

    Caso real: ZAPI aparece como experiencia Y como proyecto; salían los dos, gastando
    una de las 2 ranuras de proyecto de la página sin aportar un solo keyword nuevo.
    """
    by_id = {it["id"]: it for it in manifest if it.get("id")}
    exp_tokens: set[str] = set()
    for i in selected_ids:
        it = by_id.get(i)
        if it and it.get("type") == "experience":
            exp_tokens |= _tokens(it.get("text", "").split("—")[0])
    if not exp_tokens:
        return selected_ids
    out = []
    for i in selected_ids:
        it = by_id.get(i)
        if i not in keep and it and it.get("type") == "project" and _tokens(it.get("text", "").split(":")[0]) & exp_tokens:
            logger.info("BANK_SELECT proyecto %s descartado: duplica una experiencia seleccionada", i)
            continue
        out.append(i)
    return out


def _pad_thin_experiences(manifest: list[dict], selected_ids: list[str],
                          protected_keywords: list[str] | None) -> list[str]:
    """Una experiencia con <2 bullets se ve débil en la página. Pasa cuando la
    reintegración trae una experiencia no elegida solo por UN bullet de evidencia (visto
    2 veces con ZAPI: quedó con el bullet de webhooks y sin sus agentes ni Gemini Vision).
    Le suma su bullet no seleccionado que cubre más keywords protegidos (si cubre ≥1).
    """
    kws = [(k or "").strip().lower() for k in protected_keywords or [] if (k or "").strip()]
    selected = set(selected_ids)
    added = []
    for exp_id in [i for i in selected_ids if any(
            it.get("id") == i and it.get("type") == "experience" for it in manifest)]:
        bullets = [it for it in manifest if it.get("type") == "bullet" and it.get("parent") == exp_id]
        if sum(b["id"] in selected for b in bullets) >= 2:
            continue
        # El banco tiene bullets gemelos (mismo texto, otro id): sumar uno repetiría la línea.
        have = {b.get("text", "").strip().lower() for b in bullets if b["id"] in selected}
        scored = [(sum(_covers(k, _item_evidence_text(b)) for k in kws), b["id"])
                  for b in bullets if b["id"] not in selected
                  and b.get("text", "").strip().lower() not in have]
        # Hasta 2 bullets: una experiencia exigida por el análisis puede llegar con 0.
        need = 2 - sum(b["id"] in selected for b in bullets)
        for score, bid in sorted(scored, key=lambda s: -s[0])[:need]:
            if score > 0:
                selected.add(bid)
                added.append(bid)
    if added:
        logger.info("BANK_SELECT experiencia con 1 bullet reforzada: %s", added)
    return list(selected_ids) + added


BANK_SELECTION_USER_TEMPLATE = """\
VACANTE:
{vacancy_text}

BANCO DEL CANDIDATO (todos los items disponibles):
{manifest_json}

Selecciona los IDs de items que deben incluirse en el CV para esta vacante.
Responde con JSON: {{"selected_ids": ["id1", "id2", ...], "reasoning": "..."}}"""


def select_from_bank(
    manifest: list[dict], vacancy_text: str, api_key: str, model: str,
    protected_keywords: list[str] | None = None, provider: str | None = None,
    required_ids: list[str] | None = None,
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
        raise ValueError("Se requiere API key del proveedor de IA")

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

    _dump_debug("bank_select_request", ts, request_id,
                {"model": model, "system_prompt": BANK_SELECTION_SYSTEM_PROMPT,
                 "user_prompt": user_prompt})

    messages = [
        {"role": "system", "content": BANK_SELECTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    parsed = _call_validated(
        messages, provider=provider, model=model, api_key=api_key, options=ANALYSIS_OPTIONS,
        response_model=BankSelectionResponse, request_id=request_id,
    )

    _dump_debug("bank_select_response", ts, request_id, {"parsed_response": parsed})

    selected_ids = parsed.get("selected_ids", [])
    reasoning = parsed.get("reasoning", "")

    # Bug C — red de seguridad determinística: si la selección dejó fuera la única
    # evidencia de un keyword ya matcheado, reintégrala (el prompt lo pide, esto lo garantiza).
    # Reintegrar y LUEGO dedup, eximiendo lo reintegrado: así la experiencia ZAPI
    # reintegrada sí elimina el proyecto ZAPI duplicado, pero un proyecto reintegrado
    # como única evidencia de un keyword protegido nunca se descarta.
    # Experiencias para las que el análisis (banco completo) escribió sugerencias: si la
    # selección las tira, la sugerencia se descarta y el summary promete lo que el cuerpo
    # ya no muestra (vacante fintech: sin DCM, "idempotencia" quedó sin un solo bullet).
    known = {it["id"] for it in manifest if it.get("type") == "experience"}
    forced = [i for i in required_ids or [] if i in known and i not in selected_ids]
    if forced:
        logger.info("BANK_SELECT experiencia sugerida por el análisis reintegrada: %s", forced)
        selected_ids = list(selected_ids) + forced
    before = set(selected_ids)
    selected_ids = _reintegrate_lost_evidence(manifest, selected_ids, protected_keywords)
    selected_ids = _drop_projects_duplicating_experience(
        manifest, selected_ids, keep=frozenset(selected_ids) - before)
    selected_ids = _pad_thin_experiences(manifest, selected_ids, protected_keywords)

    logger.info("BANK_SELECT [%s] ids=%d reasoning=%.200s", request_id, len(selected_ids), reasoning or "")

    return selected_ids
