# Plan de Mejoras — CV Generator (Harvard Format)

Este documento detalla la hoja de ruta para la refactorización y optimización del generador de CV. Las tareas etiquetadas con **[GEMINI]** serán implementadas de manera autónoma.

---

## 📋 Estado de Tareas

| ID | Categoría | Descripción | Asignado | Estado |
|---|---|---|---|---|
| MEJ-01 | IA Config | Cambiar modelo predeterminado a `gpt-oss:120b-cloud` | **[GEMINI]** | ✅ Completado |
| MEJ-02 | Visual (PDF) | Renderizar formato Markdown (`**negrita**`, `*cursiva*`) a HTML en el PDF | **[GEMINI]** | ✅ Completado |
| MEJ-03 | Visual (PDF) | Optimización de espaciado dinámico (política estricta de 1 página) | **[GEMINI]** | ✅ Completado |
| MEJ-04 | Funcionalidad | Traducción semántica contextual mediante IA (`gpt-oss`) en vez de Google Translate | **[GEMINI]** | ✅ Completado |
| MEJ-05 | UI / UX | Diff Viewer interactivo para aceptar/rechazar sugerencias de la IA granularmente | **[OPUS]** | ✅ Completado |
| MEJ-06 | Arquitectura | Modularización de `app.py` (componentes UI, helpers, validación Pydantic) | **[OPUS]** | ✅ Completado |

---

## 🛠️ Detalle de Implementación (Tareas GEMINI)

### MEJ-01: Modelo Predeterminado
* **Objetivo:** Cambiar la configuración inicial para que use `gpt-oss:120b-cloud` ya que está verificado que el usuario tiene acceso a este modelo en su cuenta de Ollama Cloud y ofrece un mejor desempeño que Minimax.
* **Archivos:** [ai_analyzer.py](file:///C:/Users/pcdec/OneDrive/Documentos/Python/CVGenerator/ai_analyzer.py)

### MEJ-02: Markdown a HTML en PDF
* **Objetivo:** Limpiar los bullets de texto y procesar la sintaxis Markdown básica convirtiéndola a las etiquetas `<font>`, `<b>`, `<i>` soportadas por ReportLab `Paragraph`.
* **Archivos:** [pdf.py](file:///C:/Users/pcdec/OneDrive/Documentos/Python/CVGenerator/pdf.py)

### MEJ-03: Algoritmo de Página Única
* **Objetivo:** Medir si el documento excede el alto físico de una página Letter y, de ser así, reducir de manera recursiva/proporcional los `fontSize`, `leading` y `Spacer` del `story` hasta que quepa en 1 sola página.
* **Archivos:** [pdf.py](file:///C:/Users/pcdec/OneDrive/Documentos/Python/CVGenerator/pdf.py)

### MEJ-04: Traducción Semántica por IA
* **Objetivo:** Implementar en `translate.py` una función que use el modelo `gpt-oss:120b-cloud` para realizar la traducción, conservando mejor el vocabulario técnico IT. Se mantendrá `deep-translator` como fallback por robustez.
* **Archivos:** [translate.py](file:///C:/Users/pcdec/OneDrive/Documentos/Python/CVGenerator/translate.py), [ai_analyzer.py](file:///C:/Users/pcdec/OneDrive/Documentos/Python/CVGenerator/ai_analyzer.py)

---

## 🛠️ Detalle de Implementación (Tareas OPUS)

### MEJ-05: Diff Viewer Interactivo ✅
* **Objetivo:** Reemplazar el bloque antiguo de "text areas editables + único botón Aplicar todo" por un visor de diferencias granular.
* **Implementado:**
  - Diff inline palabra-por-palabra (`difflib.SequenceMatcher`): 🟩 añadido / 🟥 eliminado, renderizado en HTML.
  - Checkbox **Aceptar este cambio** por cada sugerencia (resumen, título de exp, bullets, descripción de proyecto, skills).
  - Texto sugerido editable antes de aplicar; botones **Aceptar todos / Rechazar todos**.
  - "Aplicar cambios seleccionados" sólo aplica las sugerencias aceptadas (verificado con `AppTest`).
* **Archivos:** [ui_components.py](file:///C:/Users/pcdec/OneDrive/Documentos/Python/CVGenerator/ui_components.py) (`render_suggestions_diff`, `_html_word_diff`, `_collect_suggestion_changes`, `_apply_selected_changes`), claves i18n `diff_*` en [i18n.py](file:///C:/Users/pcdec/OneDrive/Documentos/Python/CVGenerator/i18n.py).

### MEJ-06: Modularización de `app.py` ✅
* **Objetivo:** Romper el monolito de ~1700 líneas en módulos cohesivos.
* **Implementado:**
  - `app.py` (~175 líneas): sólo orquestación — `_init_session_state()` + routing de tabs.
  - `ui_components.py`: render de sidebar, navbar de score y los 5 tabs + Diff Viewer.
  - `helpers.py`: IDs, sync/push de widgets ↔ datos, sanitizado de salida IA, datos por defecto, flujos diferidos, patches del chat.
  - `validation.py`: validadores de formato + modelos **Pydantic** (`CVModel`, etc.) y `parse_cv()` que normaliza el JSON importado y reporta problemas.
* **Nota:** Durante la integración se corrigió un `SyntaxError` heredado en `translate.py` (línea jammeada de MEJ-04) que impedía arrancar la app.
* **Archivos:** [app.py](file:///C:/Users/pcdec/OneDrive/Documentos/Python/CVGenerator/app.py), [ui_components.py](file:///C:/Users/pcdec/OneDrive/Documentos/Python/CVGenerator/ui_components.py), [helpers.py](file:///C:/Users/pcdec/OneDrive/Documentos/Python/CVGenerator/helpers.py), [validation.py](file:///C:/Users/pcdec/OneDrive/Documentos/Python/CVGenerator/validation.py)
