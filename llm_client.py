"""Cliente único para Ollama Cloud (V2-07).

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

def _parse_json_response(raw: str) -> dict:
    """Parsea la respuesta del modelo tolerando fences de markdown y texto extra."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        lines = [l for l in raw.split("\n") if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            return json.loads(raw[start:end + 1])
        raise


# ═══════════════════════════════════════════════════════════════
# CLIENTE
# ═══════════════════════════════════════════════════════════════

class LLMError(RuntimeError):
    """Fallo al llamar al LLM: red, HTTP, o respuesta vacía/no parseable."""


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
                timeout=timeout,
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

    raise LLMError(f"Ollama falló tras {retries} intentos: {last_err}")
