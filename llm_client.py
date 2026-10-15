"""Cliente único de LLM multi-proveedor (Groq por defecto; V2-07).

Centraliza lo que estaba duplicado 7 veces (ai_analyzer.py x6, translate.py x1):
el patrón `httpx.post → raise_for_status → data["message"]["content"]`.

Aporta sobre el patrón copiado:
  - retry con backoff exponencial ante fallos transitorios,
  - acceso seguro con `.get()` (no revienta si Ollama cambia el shape de error),
  - `LLMError` si el contenido viene vacío,
  - parsing JSON tolerante a fences de markdown (`_parse_json_response`),
  - logger compartido con `request_id` en cada línea (sin el bug del formatter
    que exigía el campo como atributo del record).
"""

import json
import logging
import os
import time
import uuid
from logging.handlers import RotatingFileHandler

OLLAMA_CLOUD_URL = "https://ollama.com/api/chat"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Proveedores de LLM soportados. Groq es el default; los demás son opcionales.
# Todos hablan por HTTP (httpx), sin SDKs extra.
DEFAULT_PROVIDER = "groq"
PROVIDERS = ("groq", "ollama", "openai", "anthropic", "gemini")
PROVIDER_LABELS = {
    "groq": "Groq",
    "ollama": "Ollama Cloud",
    "openai": "OpenAI (ChatGPT)",
    "anthropic": "Anthropic (Claude)",
    "gemini": "Google Gemini",
}
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "ollama": "gpt-oss:120b-cloud",
    "anthropic": "claude-opus-5-5",
    "openai": "gpt-6.1-sol",
    "gemini": "gemini-3.8-flash",
}
# Modelos sugeridos por proveedor (id → nota corta para el selector). El sidebar
# permite además escribir cualquier otro id. Revisado 14-oct-2026 contra la doc
# oficial de cada proveedor; ollama: GET https://ollama.com/api/tags.
MODEL_OPTIONS = {
    "groq": {  # todos usables en el plan gratuito, con límites de tokens/min
        "openai/gpt-oss-120b": "recomendado · gratis con límites",
        "openai/gpt-oss-20b": "más rápido · gratis con límites",
        "llama-3.3-70b-versatile": "gratis con límites",
        "llama-3.1-8b-instant": "muy rápido · no recomendado para análisis",
        "qwen/qwen3.8-27b": "preview",
        "minimaxai/minimax-m2.7": "preview",
    },
    "ollama": {  # plan Free: crédito mensual inicial, solo un set de modelos "starter"
        "gpt-oss:120b-cloud": "recomendado (el que ya usabas)",
        "gpt-oss:120b": "nombre API del mismo modelo",
        "gpt-oss:20b": "más rápido",
        "deepseek-v4.1-flash": "rápido",
        "deepseek-v4-pro:0813": "",
        "kimi-k3": "",
        "kimi-k2.6": "",
        "glm-5.3": "",
        "glm-5.3-flash": "rápido",
        "mistral-large-4": "",
        "minimax-m3": "",
        "nemotron-3-super": "",
        "nemotron-3-nano:30b": "rápido",
        "gemma4:31b": "",
    },
    "openai": {
        "gpt-6.1-sol": "recomendado · calidad/precio",
        "gpt-6-astra": "el más capaz · caro",
        "gpt-6-luna": "el más barato",
        "gpt-5.6-sol": "",
        "gpt-5.6-luna": "barato",
        "gpt-5.5": "",
        "gpt-5.4-mini": "barato",
        "gpt-5-mini": "barato",
        "gpt-5-nano": "el más barato · no recomendado para análisis",
    },
    "anthropic": {
        "claude-opus-5-5": "recomendado",
        "claude-sonnet-5-5": "más rápido · más barato",
        "claude-haiku-5-5": "el más rápido y barato",
        "claude-fable-5-1": "el más capaz · caro",
        "claude-opus-4-8": "legacy",
        "claude-sonnet-4-6": "legacy",
        "claude-haiku-4-5": "legacy",
    },
    "gemini": {
        "gemini-3.8-flash": "recomendado",
        "gemini-4-argon": "el más capaz",
        "gemini-3.6-flash": "",
        "gemini-3.5-flash-lite": "barato · no recomendado para análisis (score inflado)",
        "gemini-3.1-flash-lite": "barato · no recomendado para análisis",
        "gemini-3.1-pro-preview": "preview",
        "gemini-3-flash-preview": "preview",
        "gemini-2.5-flash": "legacy · solo cuentas que ya lo usaban",
        "gemini-2.5-pro": "legacy · solo cuentas que ya lo usaban",
    },
}
# Tope de tokens de salida para los proveedores que lo exigen (Anthropic) o que se
# benefician de un límite explícito. 16k cubre con holgura un CV/JSON de análisis.
_MAX_OUTPUT_TOKENS = 16000

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════
# LOGGING COMPARTIDO
# ═══════════════════════════════════════════════════════════════

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

# Flag global de debug: guarda payloads completos y sube el nivel a DEBUG.
CV_DEBUG = os.getenv("CV_DEBUG", "").strip().lower() in ("1", "true", "yes")


def get_logger(name: str) -> logging.Logger:
    """Logger con RotatingFileHandler compartido (logs/ai.log).

    El request_id va embebido en el mensaje (convención `[%s]`), no en el
    formatter, para no romper records que no lo aportan como atributo.
    """
    logger = logging.getLogger(name)
    if getattr(logger, "_cv_configured", False):
        return logger
    logger.setLevel(logging.DEBUG if CV_DEBUG else logging.INFO)
    handler = RotatingFileHandler(
        os.path.join(_LOG_DIR, "ai.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(message)s")
    )
    logger.addHandler(handler)
    logger._cv_configured = True
    return logger


logger = get_logger("llm_client")


def new_request_id() -> str:
    return uuid.uuid4().hex[:8]


# ═══════════════════════════════════════════════════════════════
# PARSING JSON TOLERANTE
# ═══════════════════════════════════════════════════════════════

def _repair_json(text: str) -> str:
    """Repara malformaciones estructurales comunes en JSON emitido por LLMs.

    No es un parser completo: cubre los casos que Gemini/gpt-oss producen con
    más frecuencia y que `json.loads` rechaza —comas finales y comas FALTANTES
    entre un valor y la siguiente clave/elemento (error «Expecting ',' delimiter»)—
    sin tocar el contenido de las cadenas. Rastrea si estamos dentro de un string
    (respetando escapes) para no alterar texto literal.
    """
    out = []
    in_str = False
    esc = False
    n = len(text)
    for i, ch in enumerate(text):
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"' or ch in "{[":
            # ¿Falta una coma antes de abrir esta cadena/clave/valor? El carácter
            # previo no vacío debe cerrar un valor anterior: cualquiera salvo los
            # que ya introducen un valor (`:` `,` `{` `[`). Cubre valores que
            # terminan en `"`, `}`, `]`, número o literal true/false/null.
            j = len(out) - 1
            while j >= 0 and out[j] in " \t\r\n":
                j -= 1
            if j >= 0 and out[j] not in ":,{[":
                out.insert(j + 1, ",")
            if ch == '"':
                in_str = True
            out.append(ch)
            continue

        if ch in "}]":
            # Elimina comas finales: «, }» o «, ]».
            j = len(out) - 1
            while j >= 0 and out[j] in " \t\r\n":
                j -= 1
            if j >= 0 and out[j] == ",":
                del out[j]
            out.append(ch)
            continue

        out.append(ch)

    return "".join(out)


def _parse_json_response(raw: str) -> dict:
    """Parsea la respuesta del modelo tolerando fences de markdown y texto extra.

    Si el JSON está estructuralmente malformado (coma faltante/sobrante), intenta
    una reparación conservadora (`_repair_json`) antes de propagar el error.
    """
    raw = (raw or "").strip()
    if raw.startswith("```"):
        lines = [l for l in raw.split("\n") if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()
    try:
        # strict=False: tolera saltos de línea/tabs crudos dentro de strings
        # ("Invalid control character"), frecuente en Gemini; evita gastar un reintento.
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        candidate = raw[start:end + 1] if (start != -1 and end > start) else raw
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            # Último recurso: reparar comas faltantes/sobrantes fuera de strings.
            return json.loads(_repair_json(candidate), strict=False)


# ═══════════════════════════════════════════════════════════════
# CLIENTE
# ═══════════════════════════════════════════════════════════════

class LLMError(RuntimeError):
    """Fallo al llamar al LLM: red, HTTP, o respuesta vacía/no parseable."""


def _mk_timeout(timeout: float) -> "httpx.Timeout":
    """Construye un timeout granular: la fase de conexión falla rápido (DNS caído,
    host inalcanzable) mientras la lectura tolera generaciones lentas.

    Antes se pasaba un float único: una red intermitente colgaba los `timeout`
    segundos completos en CADA intento solo para resolver el host. Acotamos el
    connect a 10s (o menos si el caller pidió un timeout más corto).
    """
    return httpx.Timeout(timeout, connect=min(10.0, timeout))


def _describe_error(err: Exception) -> str:
    """Traduce errores de red crípticos en un mensaje accionable para el usuario.

    `getaddrinfo failed` / ConnectError = sin DNS o sin conexión; ConnectTimeout =
    el host no respondió. El resto se muestra tal cual.
    """
    if isinstance(err, (httpx.ConnectError, httpx.ConnectTimeout)) or "getaddrinfo" in str(err):
        return ("no se pudo conectar (revisa tu conexión a internet, DNS, VPN o "
                f"proxy/firewall). Detalle: {err}")
    return str(err)


def call_ollama(
    messages: list,
    *,
    model: str,
    api_key: str,
    json_mode: bool = False,
    options: dict | None = None,
    timeout: float = 180.0,
    retries: int = 3,
    request_id: str | None = None,
) -> str:
    """POST único a Ollama Cloud con retry + backoff y acceso seguro.

    Retorna el contenido de texto del mensaje del asistente (str no vacío).
    Lanza `LLMError` si tras `retries` intentos no hay respuesta válida,
    o `ValueError`/`RuntimeError` ante mala configuración.
    """
    if not HTTPX_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Ollama Cloud")

    rid = request_id or new_request_id()
    payload = {"model": model, "messages": messages, "stream": False}
    if json_mode:
        payload["format"] = "json"
    if options:
        payload["options"] = options

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            start = time.monotonic()
            response = httpx.post(
                OLLAMA_CLOUD_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=_mk_timeout(timeout),
            )
            response.raise_for_status()
            elapsed = time.monotonic() - start

            data = response.json()
            content = (data.get("message") or {}).get("content")
            if not content or not content.strip():
                raise LLMError("respuesta del modelo vacía")

            logger.info(
                "call [%s] ok model=%s attempt=%d http=%s dur=%.1fs len=%d",
                rid, model, attempt, response.status_code, elapsed, len(content),
            )
            return content.strip()

        except (httpx.HTTPError, LLMError, json.JSONDecodeError) as e:
            last_err = e
            logger.warning(
                "call [%s] fail model=%s attempt=%d/%d err=%s",
                rid, model, attempt, retries, e,
            )
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))

    raise LLMError(f"Ollama falló tras {retries} intentos: {_describe_error(last_err)}")


# ═══════════════════════════════════════════════════════════════
# DISPATCHER MULTI-PROVEEDOR
# ═══════════════════════════════════════════════════════════════
# Contrato compartido con call_ollama: recibe `messages` en formato chat
# (role/content estilo OpenAI) y devuelve el texto del asistente (str no vacío).
# `options` usa las llaves de Ollama (temperature/top_p/seed) y cada backend las
# mapea a lo suyo (o las ignora cuando el modelo no las admite).


def _split_system(messages: list) -> tuple[str, list]:
    """Separa los mensajes `system` (los junta en un solo string) del resto.

    Anthropic y Gemini llevan el system aparte, no como un mensaje más.
    """
    system_parts, rest = [], []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(m.get("content", ""))
        else:
            rest.append({"role": m.get("role"), "content": m.get("content", "")})
    return "\n\n".join(p for p in system_parts if p), rest


def _retry(do_call, *, rid: str, provider: str, model: str, retries: int) -> str:
    """Ejecuta `do_call` con backoff. No reintenta errores 4xx (salvo 429)."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            start = time.monotonic()
            content = do_call()
            if not content or not content.strip():
                raise LLMError("respuesta del modelo vacía")
            logger.info(
                "call [%s] ok provider=%s model=%s attempt=%d dur=%.1fs len=%d",
                rid, provider, model, attempt, time.monotonic() - start, len(content),
            )
            return content.strip()
        except httpx.HTTPStatusError as e:
            last_err = e
            code = e.response.status_code
            body = ""
            try:
                body = e.response.text[:300]
            except Exception:
                pass
            logger.warning("call [%s] fail provider=%s model=%s attempt=%d/%d http=%s body=%s",
                           rid, provider, model, attempt, retries, code, body)
            if 400 <= code < 500 and code != 429:
                break  # error del cliente (key/model/payload): no tiene sentido reintentar
        except (httpx.HTTPError, LLMError, json.JSONDecodeError) as e:
            last_err = e
            logger.warning("call [%s] fail provider=%s model=%s attempt=%d/%d err=%s",
                           rid, provider, model, attempt, retries, e)
        if attempt < retries:
            time.sleep(min(2 ** (attempt - 1), 8))
    raise LLMError(f"{PROVIDER_LABELS.get(provider, provider)} falló: {_describe_error(last_err)}")


def _call_openai(messages, *, model, api_key, json_mode, options, timeout, rid, retries,
                 url=OPENAI_URL, provider="openai"):
    # Groq expone la misma API (OpenAI-compatible): solo cambian url y provider.
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    opts = options or {}

    def _post(strip_sampling: bool) -> str:
        body = {"model": model, "messages": messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if not strip_sampling:
            for key in ("temperature", "top_p", "seed"):
                if opts.get(key) is not None:
                    body[key] = opts[key]
        r = httpx.post(url, headers=headers, json=body, timeout=_mk_timeout(timeout))
        r.raise_for_status()
        data = r.json()
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")

    def do_call():
        try:
            return _post(strip_sampling=False)
        except httpx.HTTPStatusError as e:
            # Los modelos de razonamiento (gpt-5.x) rechazan temperature/top_p≠default.
            # Reintentar una vez sin parámetros de sampling antes de rendirse.
            if e.response.status_code == 400 and (opts.get("temperature") is not None
                                                  or opts.get("top_p") is not None
                                                  or opts.get("seed") is not None):
                return _post(strip_sampling=True)
            raise

    return _retry(do_call, rid=rid, provider=provider, model=model, retries=retries)


def _call_anthropic(messages, *, model, api_key, json_mode, options, timeout, rid, retries):
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    system, msgs = _split_system(messages)
    if json_mode:
        instruction = "Responde ÚNICAMENTE con JSON válido, sin markdown ni texto adicional."
        system = f"{system}\n\n{instruction}" if system else instruction
    # No se envía temperature/top_p/seed: Opus 4.8 los rechaza (HTTP 400).
    body = {"model": model, "max_tokens": _MAX_OUTPUT_TOKENS, "messages": msgs}
    if system:
        body["system"] = system

    def do_call():
        r = httpx.post(ANTHROPIC_URL, headers=headers, json=body, timeout=_mk_timeout(timeout))
        r.raise_for_status()
        data = r.json()
        if data.get("stop_reason") == "refusal":
            raise LLMError("Anthropic rechazó la solicitud (refusal)")
        return "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )

    return _retry(do_call, rid=rid, provider="anthropic", model=model, retries=retries)


def _call_gemini(messages, *, model, api_key, json_mode, options, timeout, rid, retries):
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    system, msgs = _split_system(messages)
    contents = [
        {"role": "user" if m["role"] == "user" else "model",
         "parts": [{"text": m["content"]}]}
        for m in msgs
    ]
    opts = options or {}
    # `maxOutputTokens` es obligatorio aquí en la práctica: los modelos Flash son
    # "thinking" y, sin tope de salida, gastan el presupuesto en tokens de
    # pensamiento → el candidato vuelve con finishReason=MAX_TOKENS y SIN `parts`
    # (respuesta vacía) o la petición se cuelga (visto en logs: read timeout 3×180s).
    base_gen = {"maxOutputTokens": _MAX_OUTPUT_TOKENS}
    if opts.get("temperature") is not None:
        base_gen["temperature"] = opts["temperature"]
    if opts.get("top_p") is not None:
        base_gen["topP"] = opts["top_p"]
    if opts.get("seed") is not None:
        # `seed` reduce la varianza del scorer (Flash es bimodal: mismo CV → 78/48).
        # Soportado en generationConfig; si un modelo lo rechaza, el fallback de 400
        # lo elimina junto con thinkingConfig.
        base_gen["seed"] = opts["seed"]
    if json_mode:
        base_gen["responseMimeType"] = "application/json"
    url = GEMINI_URL.format(model=model)

    def _post(reduced: bool) -> str:
        gen = dict(base_gen)
        if reduced:
            # Modo defensivo tras un 400: quita los campos que algún modelo/endpoint
            # podría no admitir, dejando solo lo universalmente soportado.
            gen.pop("seed", None)
        else:
            # Apagar el "thinking" vuelve a Flash rápido y estable para extracción
            # JSON (no es una tarea de razonamiento). Elimina la latencia que dispara
            # los read-timeouts y el modo de fallo de respuesta vacía por MAX_TOKENS.
            gen["thinkingConfig"] = {"thinkingBudget": 0}
        body = {"contents": contents, "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        r = httpx.post(url, headers=headers, json=body, timeout=_mk_timeout(timeout))
        r.raise_for_status()
        data = r.json()
        # Bloqueo de seguridad a nivel de prompt: no hay candidates, error claro.
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise LLMError(f"Gemini bloqueó el prompt (blockReason={block})")
        cands = data.get("candidates") or []
        if not cands:
            raise LLMError("Gemini no devolvió candidates")
        cand = cands[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        if not text.strip():
            # finishReason explica el porqué (MAX_TOKENS, SAFETY, RECITATION…) en
            # vez del genérico "respuesta vacía" que no orienta el diagnóstico.
            reason = cand.get("finishReason") or "desconocido"
            raise LLMError(f"Gemini devolvió respuesta vacía (finishReason={reason})")
        return text

    def do_call():
        try:
            return _post(reduced=False)
        except httpx.HTTPStatusError as e:
            # Si el modelo/endpoint no admite thinkingConfig/seed (400), reintentar una
            # vez sin esos campos (mismo patrón que el strip-sampling de OpenAI).
            if e.response.status_code == 400:
                return _post(reduced=True)
            raise

    return _retry(do_call, rid=rid, provider="gemini", model=model, retries=retries)


def call_gemini_vision(
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
    *,
    api_key: str,
    model: str,
    timeout: float = 90.0,
    retries: int = 2,
    request_id: str | None = None,
) -> str:
    """OCR/transcripción de una imagen vía Gemini (`inlineData`), fuera del dispatcher
    de texto porque ningún otro proveedor soportado aquí recibe imágenes.

    Devuelve el texto extraído (str no vacío). Lanza `LLMError` en bloqueo de
    seguridad, respuesta vacía o si el modelo no admite input multimodal.
    """
    if not HTTPX_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Google Gemini")

    import base64
    rid = request_id or new_request_id()
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    url = GEMINI_URL.format(model=model)
    b64 = base64.b64encode(image_bytes).decode("ascii")
    parts = [{"text": prompt}, {"inline_data": {"mime_type": mime_type, "data": b64}}]

    def _post(reduced: bool) -> str:
        gen = {"maxOutputTokens": _MAX_OUTPUT_TOKENS, "temperature": 0}
        if not reduced:
            gen["thinkingConfig"] = {"thinkingBudget": 0}
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen}
        r = httpx.post(url, headers=headers, json=body, timeout=_mk_timeout(timeout))
        r.raise_for_status()
        data = r.json()
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise LLMError(f"Gemini bloqueó la imagen (blockReason={block})")
        cands = data.get("candidates") or []
        if not cands:
            raise LLMError("Gemini no devolvió candidates")
        cand = cands[0]
        cand_parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in cand_parts)
        if not text.strip():
            reason = cand.get("finishReason") or "desconocido"
            raise LLMError(f"Gemini devolvió respuesta vacía (finishReason={reason})")
        return text

    def do_call():
        try:
            return _post(reduced=False)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                return _post(reduced=True)
            raise

    return _retry(do_call, rid=rid, provider="gemini", model=model, retries=retries)


def call_llm(
    messages: list,
    *,
    provider: str | None,
    model: str,
    api_key: str,
    json_mode: bool = False,
    options: dict | None = None,
    timeout: float = 180.0,
    retries: int = 3,
    request_id: str | None = None,
) -> str:
    """Llama al proveedor indicado y devuelve el texto del asistente (str no vacío).

    Enruta a Groq (por defecto), Ollama, OpenAI, Anthropic o Gemini. Mismo contrato que
    `call_ollama` para no tocar el resto del pipeline (los callers siguen parseando
    con `_parse_json_response`).
    """
    if not HTTPX_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    p = (provider or DEFAULT_PROVIDER).lower()
    if not api_key:
        raise ValueError(f"Se requiere API key de {PROVIDER_LABELS.get(p, p)}")
    rid = request_id or new_request_id()

    if p == "ollama":
        return call_ollama(messages, model=model, api_key=api_key, json_mode=json_mode,
                           options=options, timeout=timeout, retries=retries, request_id=rid)
    if p == "groq":
        return _call_openai(messages, model=model, api_key=api_key, json_mode=json_mode,
                            options=options, timeout=timeout, rid=rid, retries=retries,
                            url=GROQ_URL, provider="groq")
    backend = {"openai": _call_openai, "anthropic": _call_anthropic, "gemini": _call_gemini}.get(p)
    if backend is None:
        raise ValueError(f"Proveedor de LLM no soportado: {provider}")
    return backend(messages, model=model, api_key=api_key, json_mode=json_mode,
                   options=options, timeout=timeout, rid=rid, retries=retries)
