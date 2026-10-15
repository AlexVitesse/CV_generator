# Feature — OCR de vacante desde imagen (Gemini Vision)

**Fecha:** 2026-07-13 · rama `main`

Se añadió la posibilidad de subir una **imagen** de la vacante (captura de pantalla o
foto) y extraer su texto automáticamente vía **Google Gemini Vision**, en vez de
tener que pegarlo a mano. Sin dependencias nuevas — reusa `httpx` y el `GEMINI_URL`
ya cableado en [[llm_client]] para el resto del pipeline multi-proveedor (ver
`FEATURE_MULTI_PROVEEDOR.md`).

---

## Por qué solo Gemini

Es el único proveedor de los cuatro soportados (`ollama`, `openai`, `anthropic`,
`gemini`) con input multimodal ya integrado al proyecto. El botón de OCR se
habilita **solo si hay una API key de Gemini guardada**, sin importar cuál sea el
proveedor activo en el sidebar — se lee de `AI_PROVIDERS["gemini"]`, el mapa en
sesión que conserva las credenciales de todos los proveedores simultáneamente.

---

## Arquitectura

### `llm_client.py` — `call_gemini_vision()`
Función standalone (no pasa por el dispatcher `call_llm`, cuyo contrato de texto no
admite imágenes). Construye el request a `GEMINI_URL` con:
- `parts: [{"text": prompt}, {"inline_data": {"mime_type", "data": <base64>}}]`
- `generationConfig`: `temperature=0` (transcripción determinista) +
  `maxOutputTokens` + `thinkingConfig: {thinkingBudget: 0}` en el primer intento
  (mismo patrón que `_call_gemini`: apagar "thinking" evita los timeouts/respuestas
  vacías vistos en Flash). Ante HTTP 400 reintenta sin `thinkingConfig`.
- Reusa `_retry`, `_mk_timeout`, `LLMError` y el logger compartido — mismo
  tratamiento de errores (bloqueo de seguridad, `candidates` vacío, `finishReason`)
  que el resto de los backends.

### `ai_analyzer.py` — `extract_vacancy_text_from_image()`
Wrapper delgado que:
- Carga el prompt desde `prompts/ocr_vacancy.md` (con fallback inline, mismo patrón
  que `SYSTEM_PROMPT`/`SUMMARY_SYSTEM_PROMPT` vía `_load_prompt`).
- El prompt instruye transcripción **textual** (sin traducir, sin resumir, sin
  opinar) y responder `NO_VACANCY_DETECTED` si la imagen no contiene una vacante
  reconocible.
- Si el modelo devuelve `NO_VACANCY_DETECTED`, se traduce a `ValueError` con mensaje
  accionable para el usuario.

### `ui/tab_analysis.py` — UI
Justo **antes** del `text_area` de la vacante (`key=sk.VACANCY_TEXT`):
- `st.file_uploader` (`png`/`jpg`/`jpeg`/`webp`) con key
  `sk.VACANCY_IMAGE_UPLOADER`.
- Botón **"🖼️ Extraer texto de la imagen (OCR con Gemini)"**, `disabled=True`
  salvo que haya API key de Gemini guardada **y** una imagen subida. Si falta la
  key, se muestra un aviso apuntando al sidebar.
- Al extraer con éxito: `st.session_state[sk.VACANCY_TEXT] = extracted` + `st.rerun()`.

  > El bloque de OCR se ubica **antes** del `text_area` en el código a propósito:
  > Streamlit no permite mutar el `session_state` de un widget que ya fue
  > instanciado en el mismo run. Al procesar el OCR primero, el `text_area` lee el
  > valor nuevo en el siguiente render sin conflicto.

### `session_keys.py`
- `VACANCY_IMAGE_UPLOADER = "vacancy_image_uploader"` (nueva).

### `i18n.py`
- Nuevas claves (ES/EN): `vacancy_ocr_uploader`, `vacancy_ocr_button`,
  `vacancy_ocr_no_key`, `vacancy_ocr_running`, `vacancy_ocr_success`,
  `vacancy_ocr_error`.

---

## Archivos tocados

```
llm_client.py            call_gemini_vision() — OCR standalone vía inline_data
ai_analyzer.py            extract_vacancy_text_from_image() + OCR_VACANCY_PROMPT
prompts/ocr_vacancy.md    (nuevo) prompt de transcripción textual
session_keys.py           VACANCY_IMAGE_UPLOADER
i18n.py                   claves vacancy_ocr_* (ES/EN)
ui/tab_analysis.py        file_uploader + botón OCR (gated por key de Gemini)
```

## Cómo verificar

```bash
./venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/e2e_filter_test.py   # 92 passed
```

En la app: guarda una API key de Gemini en el sidebar (proveedor "Google Gemini") →
ve al tab de Análisis → sube una captura de una vacante → botón OCR habilitado →
extrae y revisa que el texto caiga en el campo de vacante.

## Pendiente / no incluido

- Solo Gemini soporta OCR hoy; si en el futuro se quiere usar otro proveedor con
  visión (p. ej. OpenAI con `gpt-4o`), habría que replicar el patrón de
  `call_gemini_vision` para ese backend.
- No hay límite explícito de tamaño de imagen del lado de la app — Gemini rechaza
  con HTTP 400 si el payload excede su límite de `inline_data`; el error se
  propaga tal cual al usuario.
