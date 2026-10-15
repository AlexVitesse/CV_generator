# Feature — Selección de proveedor de LLM (Ollama / OpenAI / Anthropic / Gemini)

**Fecha:** 2026-06-18 · rama `main`

> **Actualizado 2026-10-14:** Groq es ahora el proveedor por defecto y los modelos de la tabla
> cambiaron. Ver [FIX_REVISION_GROQ_MODELOS.md](FIX_REVISION_GROQ_MODELOS.md).

Se añadió la posibilidad de elegir el proveedor de LLM **sin quitar Ollama** (sigue siendo el
default). Todo por HTTP con `httpx` — **cero dependencias nuevas**. Decisión del usuario:
HTTP crudo + set de modelos recomendado. Suite: **81 tests en verde** (+9 nuevos en
`tests/test_providers.py`).

---

## Proveedores y modelos por defecto

| Proveedor | Etiqueta UI | Modelo default (editable) | Endpoint |
|-----------|-------------|---------------------------|----------|
| `ollama` | Ollama Cloud | `gpt-oss:120b-cloud` | `https://ollama.com/api/chat` |
| `openai` | OpenAI (ChatGPT) | `gpt-5.1` | `https://api.openai.com/v1/chat/completions` |
| `anthropic` | Anthropic (Claude) | `claude-opus-4-8` | `https://api.anthropic.com/v1/messages` |
| `gemini` | Google Gemini | `gemini-2.5-flash` | `…/v1beta/models/{model}:generateContent` |

---

## Arquitectura

### `llm_client.py` — capa de proveedor
- **`call_llm(messages, *, provider, model, api_key, json_mode, options, …) → str`** — dispatcher
  con el **mismo contrato** que `call_ollama` (recibe chat estilo OpenAI, devuelve texto). Nada
  más del pipeline cambió: los callers siguen parseando con `_parse_json_response`.
- Backends REST por proveedor, cada uno devolviendo `str`:
  - **OpenAI:** `response_format: json_object` para JSON; mapea `temperature/top_p/seed`. Si un
    modelo de razonamiento (gpt-5.x) rechaza el sampling con HTTP 400, **reintenta una vez sin esos
    parámetros**.
  - **Anthropic:** extrae el `system` de los mensajes, fija `max_tokens=16000`, **NO envía
    `temperature`** (Opus 4.8 da 400), añade instrucción JSON y traduce `stop_reason: refusal` a error.
  - **Gemini:** mapea a `contents`/`systemInstruction` + `generationConfig` (`responseMimeType`,
    `temperature`, `topP`).
  - `_retry`: backoff exponencial que **no reintenta 4xx** (salvo 429); `_split_system` separa el system.
- Constantes: `PROVIDERS`, `PROVIDER_LABELS`, `DEFAULT_MODELS`.

### Configuración por proveedor — `.ai_config.json`
```json
{
  "provider": "ollama",
  "providers": {
    "ollama":    {"api_key": "...", "model": "gpt-oss:120b-cloud"},
    "openai":    {"api_key": "...", "model": "gpt-5.1"},
    "anthropic": {"api_key": "...", "model": "claude-opus-4-8"},
    "gemini":    {"api_key": "",    "model": "gemini-2.5-flash"}
  }
}
```
- `load_ai_config()` (`ai_analyzer.py`): devuelve el mapa completo + el proveedor activo resuelto;
  **migra** el formato antiguo `{api_key, model}` a `providers.ollama`. `OLLAMA_API_KEY` (env)
  sigue teniendo prioridad para Ollama.
- `save_ai_config(provider, api_key, model)`: lee el disco y **actualiza solo ese proveedor**,
  conservando las credenciales de los demás.

### UI — `ui/sidebar.py`
- Selectbox de proveedor; al cambiar carga las credenciales guardadas del elegido.
- **Guardado defensivo:** los inputs usan key explícita (`ai_key_input`/`ai_model_input`) y, antes
  de cambiar de proveedor, persiste lo que el usuario tenga escrito para el proveedor **actual**
  (aunque sea a medio teclear) → nunca se pierde una API key recién puesta.
- `session_keys.py`: `AI_PROVIDER` y `AI_PROVIDERS` (mapa en sesión). `app.py` inicializa desde la
  config (con reconstrucción defensiva si llega en formato antiguo por un hot-reload cacheado).

### Propagación de `provider`
Parámetro `provider="ollama"` (default, retrocompatible) en: `analyze_vacancy`,
`evaluate_cv_detailed`, `select_from_bank`, `generate_text`, `chat_with_advisor`,
`extract_chat_patch`, `translate_cv_data` (+ internos `_call_validated`, `_repair_metrics_once`).
Los call-sites de UI lo pasan desde `st.session_state[AI_PROVIDER]`.

---

## Hardening — reintento ante JSON malformado

`_call_validated` (`ai_analyzer.py`) **antes solo reintentaba ante error de esquema**
(`ValidationError`); si el modelo devolvía JSON inválido (coma faltante, comilla sin escapar), el
primer `_parse_json_response` reventaba **sin reintento ni log** → en la UI:
`Error al analizar: Expecting ',' delimiter`.

**Ahora** reintenta una vez también ante `json.JSONDecodeError` (pidiendo al modelo corregir el
JSON) y lo registra: `VALIDATE [id] respuesta inválida (JSONDecodeError)…`. Cubre análisis,
evaluación y selección de banco, para todos los proveedores. Modelos como Gemini/gpt-oss emiten
JSON imperfecto de forma ocasional; esto lo absorbe.

> Pendiente opcional: aplicar el mismo reintento a `extract_chat_patch` y `translate_cv_via_llm`
> (hoy solo blindado el camino principal vía `_call_validated`).

---

## Comparativa observada (Gemini vs gpt-oss:120b)

De los logs reales de prueba (muestra pequeña, no benchmark formal):

| | gpt-oss:120b (Ollama) | Gemini Flash |
|---|---|---|
| JSON válido | siempre | sí (candidato más probable del JSON imperfecto) |
| Reproducibilidad del score | **alta** (`temperature=0 + seed=42`) | media (temp 0 ≈ determinista; **sin seed**) |
| Ajuste a los prompts | los prompts se tunearon contra él | bien; un caso sobre-generó keywords (109) |
| Velocidad | 25–45 s | 9–60 s |

**Recomendación:** `gpt-oss:120b` como default (scores reproducibles y prompts calibrados a él);
Gemini Flash como alternativa rápida/barata. OpenAI requiere una API key válida (la probada daba
`Incorrect API key provided`).

---

## Archivos tocados

```
llm_client.py        call_llm + backends OpenAI/Anthropic/Gemini, _retry, _split_system, constantes
ai_analyzer.py       provider en funciones públicas + _call_validated/_repair; load/save_ai_config
                     por proveedor; reintento ante JSON malformado
translate.py         provider en translate_cv_via_llm / translate_cv_data; re-alineación por id
session_keys.py      AI_PROVIDER, AI_PROVIDERS
app.py               init multi-proveedor (defensivo)
i18n.py              "ai_provider"; "ai_api_key" generalizada
ui/sidebar.py        selectbox de proveedor + guardado defensivo
ui/tab_analysis.py, ui/tab_eval.py, ui/tab_chat.py, ui/navbar.py, helpers.py
                     call-sites pasan provider desde session_state
tests/test_providers.py  (nuevo) 9 tests del dispatcher (payloads, strip-on-400, refusal, etc.)
```

## Cómo verificar
```bash
./venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/e2e_filter_test.py   # 81 passed
```
En la app: sidebar → elige proveedor → pega API key → corre un análisis. Reinicia Streamlit por
completo tras cambios de código (el hot-reload puede dejar módulos cacheados).
