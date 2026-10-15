# Fix + Feature — Revisión del diff, Groq como default y catálogo de modelos

**Fecha:** 2026-10-14 · **Rama:** `main` (working tree, sin commitear)

Tres bloques de trabajo sobre el diff pendiente:

1. **Revisión** del diff staged (40 archivos, ~2.7k líneas) → 2 bugs y 3 riesgos, todos corregidos.
2. **Groq pasa a ser el proveedor por defecto**; Ollama, OpenAI, Anthropic y Gemini quedan opcionales.
3. **Catálogo de modelos por proveedor** en el sidebar (lista sugerida + id libre), con modelos
   actualizados a octubre 2026.

Suite: **115 tests en verde** (109 previos + 6 nuevos). Sin dependencias nuevas.

---

## 1. Revisión del diff — bugs y riesgos

Antes de tocar nada: 109 tests OK; `banco_personal.json`, `config_personal.json`, `*.bak`,
`logs/` y `.ai_config.json` siguen en `.gitignore` y nada personal está trackeado.

### Bugs

| # | Archivo | Causa raíz | Fix |
|---|---------|-----------|-----|
| **1** | `translate.py` `_restore_ids_with_fallback` | Si el LLM alteraba un id (`exp_a` → `exp-a`), el original quedaba como hueco (se traducía por fallback) **y** la traducción con id inventado se agregaba al final como "sobrante" → **experiencia duplicada** en el CV. Reproducido. | Los ids que no existen en los originales cuentan como "sin id": se consumen por posición. Se eliminó el `aligned.extend(...)` de sobrantes. El `zip` final restaura el id original. |
| **2** | `ai_analyzer.py` `select_from_bank` | `_reintegrate_lost_evidence` corría **antes** que `_drop_projects_duplicating_experience`: un proyecto reintegrado como única evidencia de un keyword protegido (caso ZAPI) podía descartarse justo después. | Invertir el orden: primero dedup, luego reintegración — la red de keywords protegidos tiene la última palabra. |

### Riesgos

| # | Archivo | Riesgo | Fix |
|---|---------|--------|-----|
| **3** | `ai_analyzer.py` `_call_validated` | El default de `timeout` había bajado de 180s a 90s. Sin streaming, el read-timeout de httpx actúa como timeout total → análisis largos (Opus / gpt-oss-120b, JSON de hasta 16k tokens) podían cortarse. | Vuelve a `180.0`. El connect sigue fallando rápido (10s) vía `_mk_timeout`, así que una red caída no cuelga 180s. |
| **4** | `ai_analyzer.py` `_covers` | `\b…\b` no reconoce keywords con símbolos: `C++`, `C#`, `.NET` nunca quedaban "cubiertos". | Lookarounds `(?<!\w)…(?!\w)`. Sigue rechazando Java ⊂ JavaScript. Se quitó el comentario `ponytail:` que documentaba el límite. |
| **5** | `llm_client.py` | Modelos por defecto desactualizados (`gpt-5.1` está deprecado, `gemini-2.5-*` solo para cuentas que ya lo usaban). | Ver sección 3. |

---

## 2. Groq como proveedor por defecto

| Cambio | Detalle |
|--------|---------|
| Nuevo proveedor `groq` | `GROQ_URL = https://api.groq.com/openai/v1/chat/completions`. Groq es **OpenAI-compatible**: se reutiliza `_call_openai` con parámetros `url=` y `provider=` (sin backend nuevo). Hereda `response_format: json_object` y el reintento sin sampling ante 400. |
| `DEFAULT_PROVIDER = "groq"` | Fuente única del default en `llm_client.py`. `call_llm(provider=None)` resuelve a Groq. |
| Defaults dispersos eliminados | Había ~20 literales `"ollama"` (firmas `provider: str = "ollama"` en `ai_analyzer.py`/`translate.py` y `st.session_state.get(sk.AI_PROVIDER, "ollama")` en `helpers.py` y `ui/*`). Ahora las firmas usan `provider: str \| None = None` y la UI lee `st.session_state.get(sk.AI_PROVIDER)`; el fallback vive solo en `call_llm`. |
| Mensajes de error | `"Se requiere API key de Ollama Cloud"` → `"Se requiere API key del proveedor de IA"` (5 sitios en `ai_analyzer.py`). |
| `app.py` | Lee `_cfg["provider"]` (ya resuelto por `load_ai_config`); sin httpx deja `AI_PROVIDER = None`. |

### Compatibilidad con configs existentes

`load_ai_config` (`ai_analyzer.py`):

| Estado de `.ai_config.json` | Proveedor activo |
|-----------------------------|------------------|
| No existe (instalación nueva) | **groq** |
| Formato nuevo con `"provider"` guardado | El guardado (se respeta la elección del usuario) |
| Formato antiguo `{api_key, model}` (solo Ollama) | **ollama** — sus credenciales son de Ollama; sin esto se saltaría a Groq sin key |

`OLLAMA_API_KEY` (env) mantiene su prioridad para Ollama. No se añadió `GROQ_API_KEY`
(la key se guarda desde el sidebar); agregar si se necesita.

---

## 3. Catálogo de modelos por proveedor

### `llm_client.MODEL_OPTIONS`

Dict `provider → {model_id: nota}`. Es la única lista a mantener; el sidebar la consume.
Ids verificados el 2026-10-14 contra la doc oficial de cada proveedor (Ollama: `GET https://ollama.com/api/tags`).

| Proveedor | Default | Otras opciones | Plan gratis |
|-----------|---------|----------------|-------------|
| **Groq** | `openai/gpt-oss-120b` | `openai/gpt-oss-20b`, `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `qwen/qwen3.8-27b` (preview), `minimaxai/minimax-m2.7` (preview) | Sí, todos, con rate limits |
| **Ollama Cloud** | `gpt-oss:120b-cloud` | `gpt-oss:120b`, `gpt-oss:20b`, `deepseek-v4.1-flash`, `deepseek-v4-pro:0813`, `kimi-k3`, `kimi-k2.6`, `glm-5.3`, `glm-5.3-flash`, `mistral-large-4`, `minimax-m3`, `nemotron-3-super`, `nemotron-3-nano:30b`, `gemma4:31b` | Crédito mensual inicial, solo set "starter" (no detallado) |
| **OpenAI** | `gpt-6.1-sol` | `gpt-6-astra`, `gpt-6-luna`, `gpt-5.6-sol`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.4-mini`, `gpt-5-mini`, `gpt-5-nano` | No |
| **Anthropic** | `claude-opus-5-5` | `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-fable-5-1`; legacy `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5` | No |
| **Gemini** | `gemini-3.8-flash` | `gemini-4-argon`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.1-pro-preview`, `gemini-3-flash-preview`; legacy `gemini-2.5-flash`, `gemini-2.5-pro` | No indicado en la doc |

El OCR de vacante (`extract_vacancy_text_from_image`) usa `DEFAULT_MODELS["gemini"]`, así que pasa a `gemini-3.8-flash` automáticamente.

### Sidebar (`ui/sidebar.py`)

- El `text_input` del modelo se reemplazó por `st.selectbox(..., accept_new_options=True)`:
  lista sugerida con nota (`id — nota`) **y** posibilidad de escribir cualquier otro id.
- El valor actual se inserta en las opciones si no está en la lista (modelo personalizado o
  legacy guardado), para que el widget no falle.
- Nuevo texto i18n `ai_model_help` (es/en).
- `requirements.txt`: `streamlit>=1.45.0` (mínimo para `accept_new_options`; instalado: 1.54).

---

## Tests nuevos

| Test | Archivo | Cubre |
|------|---------|-------|
| `test_covers_symbol_keywords` | `tests/test_guards.py` | #4: C++, C#, .NET cubiertos; Java ⊄ JavaScript |
| `test_reintegrated_project_survives_dedup` | `tests/test_guards.py` | #2: con `_call_validated` mockeado, el proyecto que es única evidencia de un keyword protegido sobrevive |
| `test_translation_mangled_id_does_not_duplicate` | `tests/test_guards.py` | #1: id alterado → 2 items, ids originales, traducción del LLM conservada |
| `test_groq_is_default_and_openai_compatible` | `tests/test_providers.py` | `provider=None` → `GROQ_URL`, payload estilo OpenAI |
| `test_legacy_config_stays_on_ollama` | `tests/test_providers.py` | Config antigua → ollama; sin config → groq |
| `test_default_model_is_in_options` | `tests/test_providers.py` | Cada `DEFAULT_MODELS[p]` está en `MODEL_OPTIONS[p]` |

Además se probó el sidebar con `streamlit.testing.v1.AppTest`: render sin excepciones, cambio
de proveedor carga la lista correcta y preserva el modelo guardado.

> **Nota:** AppTest usa el `.ai_config.json` real; el cambio de proveedor de la prueba lo
> persistió. Se restauró `provider: "ollama"` (keys intactas). Para futuras pruebas de UI,
> monkeypatchear `ai_analyzer._config_path` a un archivo temporal.

---

## Riesgos abiertos

- **Rate limit de Groq free:** ~8K TPM para `gpt-oss-120b` (la doc no aclara si es el límite
  free o Developer). Un análisis completo (CV + vacante + JSON largo) puede dar 429/413.
  Mitigación: `openai/gpt-oss-20b` o el plan Developer de Groq.
- **Tag de Ollama:** la doc de la API indica usar el nombre de `/api/tags` (`gpt-oss:120b`);
  se mantuvo `gpt-oss:120b-cloud` como default porque es el que ya funcionaba. Ambos están en la lista.
- **`gpt-6.1-sol`:** confirmado solo en la doc de modelos de OpenAI; verificar con
  `GET /v1/models` usando tu key.
- **Thinking en Gemini 3.x:** se sigue enviando `thinkingConfig.thinkingBudget = 0`; si un
  modelo lo rechaza con 400, el reintento existente lo quita.

## Archivos tocados

`llm_client.py`, `ai_analyzer.py`, `translate.py`, `app.py`, `helpers.py`, `i18n.py`,
`requirements.txt`, `README.md`, `ui/sidebar.py`, `ui/tab_analysis.py`, `ui/tab_chat.py`,
`ui/tab_eval.py`, `ui/navbar.py`, `tests/test_guards.py`, `tests/test_providers.py`.

## Fuentes

- [Groq models](https://console.groq.com/docs/models) · [Groq rate limits](https://console.groq.com/docs/rate-limits)
- [Ollama pricing](https://ollama.com/pricing) · [Ollama cloud docs](https://docs.ollama.com/cloud)
- [Claude models overview](https://platform.claude.com/docs/en/about-claude/models/overview)
- [OpenAI all models](https://developers.openai.com/api/docs/models/all)
- [Gemini models](https://ai.google.dev/gemini-api/docs/models)

---

## 4. Paridad: que la app genere el CV como uno hecho a mano (2026-10-14, tarde)

Contexto: se adaptaron a mano dos CVs para vacantes reales eligiendo bullets del banco **tal
cual** y solo traduciéndolos/recortándolos. Se comparó contra lo que generaba la app con la
misma vacante (simulación sin Streamlit del flujo analizar → seleccionar banco → aplicar → PDF,
sin guardar el banco) y se cerraron las diferencias. Suite: **127 tests en verde**.

| # | Problema en el CV de la app | Fix | Dónde |
|---|------------------------------|-----|-------|
| 1 | Títulos de puesto inventados ("Python Data & Systems Engineer") | Guard: restaura el título real por id; el prompt pide devolverlo idéntico | `helpers.sanitize_ai_result`, `prompts/analyze.md`, `USER_PROMPT_TEMPLATE` |
| 2 | Bullets "reenfocados" al JD ("ensuring data quality", métrica de Make atribuida a Python/Docker, requests→transactions) | Con banco, la reescritura de bullets/proyectos arranca **desmarcada** en el diff viewer: salen verbatim del banco (opt-in para reescribir). Regla de fidelidad en el prompt. | `ui/diff_viewer.py`, `prompts/analyze.md` |
| 3 | Skills en una sola línea con `\|` | `merge_skill_line` guarda una entrada por tier (reusa ids en orden); el diff une con `\n` | `ui/diff_viewer.py` |
| 4 | El modelo quitaba skills reales (FastAPI, Oracle Cloud) | `_restore_core_skills`: re-agrega las de dominio avanzado eliminadas | `helpers.py` |
| 5 | El modelo degradaba tiers (FastAPI → Working) | `_enforce_skill_tiers` respeta el tier original en **ambos** sentidos | `helpers.py` |
| 6 | Fechas/ubicaciones en otro idioma ("Abril 2026", "Remoto — EE.UU.") | `localize_meta` al renderizar, según el idioma del contenido | `pdf.py` |
| 7 | Bullets del banco en español en un CV inglés (ya no se reescriben) | La autotraducción también se dispara si hay **contenido mezclado** (`has_foreign_text`), no solo si difiere el idioma de sesión | `helpers.deferred_translate_and_reevaluate`, `pdf.text_lang` |
| 8 | Experiencias en orden del banco (contrato terminado arriba del puesto actual) | Orden cronológico inverso: actuales primero, luego por fecha de fin | `banco._date_sort_key`, `bank_to_active_cv` |
| 9 | ZAPI duplicado (experiencia + proyecto) tras reintegrar evidencia | Reintegrar → dedup eximiendo lo reintegrado | `ai_analyzer.select_from_bank` |
| 10 | Score inflado con modelos lite | Marcados "no recomendado para análisis" en el selector | `llm_client.MODEL_OPTIONS` |

### Cambios en el banco (`banco_personal.json`, respaldo en `banco_personal.json.bak3`)

- Eliminadas las líneas de skills basura `2a963b4b` y `d8c53127` (entraron por el bug viejo de
  `merge_skill_line` con uid nuevo); ponían Oracle Cloud en Working y Git/CI/CD en Exposure.
- `Git` y `CI/CD` añadidos a "Dominio intermedio" (los bullets los evidencian).

### Pendiente / límites conocidos

- La selección del banco sigue dependiendo del modelo (varía entre corridas qué bullets elige).
  Usar `gemini-3.8-flash`, `gpt-oss-120b` o superior para analizar.
- El banco aún tiene bullets en español; se traducen al generar, pero traducirlos una vez en el
  banco ahorra una llamada por CV.
- Skills adyacentes del JD (Snowflake, Tableau, a veces dominios como "Financial Regulations")
  entran en "Exposure to" por la regla del usuario; revisar antes de enviar.

## 5. Fixes tras probar con vacantes reales (15-oct-2026)

| # | Problema | Fix | Dónde |
|---|----------|-----|-------|
| 1 | Condor recibió "AI Engineer – Founder" (el título de ZAPI) | El título sugerido solo se aplica si su `id` coincide con el ítem resuelto | `ui/diff_viewer._collect_suggestion_changes` |
| 2 | Skill sin tier pero evidenciada en el CV caía en "Exposure" | `_evidenced`: con evidencia va a Working (nunca a Core); sin ella, al tier más bajo | `helpers._enforce_skill_tiers` |
| 3 | Experiencia reintegrada con 1 solo bullet (ZAPI) | `_pad_thin_experiences`: suma su bullet que cubre más keywords protegidos (si cubre ≥1) | `ai_analyzer.select_from_bank` |
| 4 | ZAPI salió con la misma línea dos veces | El refuerzo salta bullets con texto idéntico a uno ya elegido; se borraron del banco los gemelos `bul_ai_dev_tools`, `bul_d5b606d3`, `bul_72b43b80`, `bul_74785dc0` (respaldo `banco_personal.json.bak5`) | `ai_analyzer._pad_thin_experiences` |
