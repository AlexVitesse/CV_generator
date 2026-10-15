# Plan de Mejoras V2 — CV Generator (Auditoría de Código)

> Auditoría completa del código (capa IA, capa UI, capa datos/PDF) realizada el 2026-06-12.
> Cada tarea indica el problema actual con referencia `archivo:línea`, **cómo lo haría yo**,
> y el criterio para considerarla terminada. Continúa la numeración de [PLAN_MEJORAS.md](PLAN_MEJORAS.md).

---

## 📋 Estado de Tareas

| ID | Fase | Categoría | Descripción | Prioridad | Asignado | Estado |
|---|---|---|---|---|---|---|
| V2-01 | 0 | Arquitectura | Resolver doble fuente de verdad: JSON vs SQLite (`db.py` está muerto) | 🔴 Bloqueante | 🧠 Claude | ✅ Terminado (JSON único; SQLite eliminado) |
| V2-02 | 1 | Privacidad | Logs guardan CV completo y requests/responses sin anonimizar ni rotar | 🔴 Alta | 🟦 opencode | ✅ Terminado |
| V2-03 | 1 | Seguridad | API key en texto plano en `.ai_config.json` | 🔴 Alta | 🟣 gemini | ✅ Terminado |
| V2-04 | 1 | Datos | Escritura no atómica de `banco_personal.json` (riesgo de pérdida total) | 🔴 Alta | 🟦 opencode | ✅ Terminado |
| V2-05 | 1 | Datos | `merge_cv_to_bank()` sincroniza por índice posicional, no por ID | 🔴 Alta | 🧠 Claude | ✅ Terminado (merge por id + 10 tests) |
| V2-06 | 1 | Seguridad | Escape HTML inconsistente con datos de usuario (XSS) | 🔴 Alta | 🟦 opencode | ✅ Terminado |
| V2-07 | 2 | IA | Extraer helper único `_call_ollama()` (patrón duplicado 7 veces) | 🟠 Media | 🧠 Claude | ✅ Terminado (`llm_client.py`) |
| V2-08 | 2 | IA | Validar respuestas del LLM con modelos Pydantic | 🟠 Media | 🧠 Claude | ✅ Terminado (4 modelos + reintento) |
| V2-09 | 2 | IA | Unificar parsing JSON, constantes y logging entre `ai_analyzer.py` y `translate.py` | 🟠 Media | 🟦 opencode | ✅ Terminado |
| V2-10 | 2 | IA | Externalizar ~500 líneas de prompts hardcodeados a `prompts/` | 🟡 Baja | 🟣 gemini | ✅ Terminado |
| V2-11 | 2 | IA | `zip()` sin validar largos en traducción (pérdida silenciosa de items) | 🟠 Media | 🟦 opencode | ✅ Terminado |
| V2-12 | 3 | UI | Partir `ui_components.py` (1327 líneas) en paquete `ui/` | 🟠 Media | 🟦 opencode | ✅ Terminado |
| V2-13 | 3 | UI | Centralizar 120+ keys mágicas de session_state en constantes | 🟠 Media | 🟣 gemini | ✅ Terminado |
| V2-14 | 3 | Robustez | Eliminar `except Exception` genéricos (34 solo en `ui_components.py`) | 🟠 Media | 🟦 opencode | ✅ Terminado |
| V2-15 | 3 | UI | Borrar items por ID (no índice) + deduplicar helper de color de score | 🟠 Media | 🟣 gemini | ✅ Terminado |
| V2-16 | 4 | PDF | Conteo de páginas exacto con `pypdf` + tope explícito en escalado | 🟠 Media | 🟦 opencode | ✅ Terminado |
| V2-17 | 4 | PDF | Saneo de caracteres de control y revisión de normalización Unicode | 🟡 Baja | 🟣 gemini | ✅ Terminado |
| V2-18 | 4 | Validación | Endurecer validadores: email, LinkedIn URL, campos vacíos | 🟡 Baja | 🟣 gemini | ✅ Terminado |
| V2-19 | 5 | Tests | Crear suite pytest (banco, validación, parsing IA, PDF) | 🔴 Alta | 🧠 Claude | ✅ Terminado (44 tests en verde) |
| V2-20 | 5 | Deps | Pinear versiones en `requirements.txt` | 🟡 Baja | 🟣 gemini | ✅ Terminado |
| V2-21 | 5 | Datos | Hacer idempotente `migrate_json_to_sqlite.py` | 🟡 Baja | 🟣 gemini | ⛔ N/A (script eliminado en V2-01) |
| V2-22 | 5 | Repo | Limpiar artefactos del repo (`cv_generator.db`, `test_cv.pdf`, etc.) | 🟡 Baja | 🟣 gemini | ✅ Terminado |

> **Leyenda de asignación:** 🧠 **Claude** = arquitectura, riesgo de corrupción de datos y piezas que habilitan al resto · 🟦 **opencode** = refactors de complejidad media bien acotados · 🟣 **gemini** = cambios mecánicos, reemplazos globales y bajo riesgo.

---

## Fase 0 — Decisión arquitectónica (bloqueante)

### V2-01: Resolver la doble fuente de verdad JSON vs SQLite — 🧠 Claude

**Problema:** [app.py](app.py) (línea 47) carga el banco vía `from banco import load_banco` →
JSON (`banco_personal.json`). Mientras tanto, [db.py](db.py) (382 líneas, SQLite con
versionado de bullets) expone exactamente la misma API pública pero **ningún módulo de la app
lo importa**: está muerto. Existen dos almacenes (`banco_personal.json` y `cv_generator.db`)
que divergen silenciosamente — el `.db` solo se toca vía `migrate_json_to_sqlite.py` manual.

**Cómo lo haría yo:**
1. Adoptar **SQLite como única fuente de verdad** (ya soporta versionado de bullets por
   enfoque, que JSON no tiene, y habilita el tracking de vacantes del
   [PLAN_BUSQUEDA_VACANTES.md](PLAN_BUSQUEDA_VACANTES.md)).
2. En `app.py:47` cambiar el import a `from db import load_banco, save_banco, ...`.
3. `banco.py` queda solo con la **lógica pura** (ya está así: `bank_to_active_cv`,
   `get_bank_manifest`, `toggle_item`, `merge_cv_to_bank` — `db.py` ya las reimporta).
4. Mantener export/import JSON como función de **backup manual** en el sidebar.
5. Al primer arranque sin `.db` pero con JSON: migrar automáticamente (reusar la lógica de
   `migrate_json_to_sqlite.py`) y renombrar el JSON a `.migrated.bak`.

*Alternativa (si no se quiere SQLite todavía): borrar `db.py` y `migrate_json_to_sqlite.py`
para eliminar la confusión. Lo importante es que no convivan los dos.*

**Hecho cuando:** la app lee y escribe en un solo almacén; el otro formato solo existe como
export/backup explícito.

> **✅ Decisión tomada (2026-06-12):** se eligió la **alternativa Solo JSON**. Se eliminaron
> `db.py`, `migrate_json_to_sqlite.py` y el artefacto `cv_generator.db` (+ `-wal`/`-shm`).
> `banco_personal.json` queda como fuente única, ya con escritura atómica y recuperación
> `.bak` (V2-04). Ningún módulo importa ya `db`; todo compila. Consecuencia: **V2-21 queda N/A**.

---

## Fase 1 — Seguridad y pérdida de datos

### V2-02: Privacidad en logs de IA — 🟦 opencode

**Problema:** [ai_analyzer.py](ai_analyzer.py) escribe en `logs/` el CV completo, la vacante
y archivos `request_*.json` / `response_*.json` con todos los datos personales (nombre,
email, teléfono, historial laboral), sin rotación ni límite (líneas ~306-348, ~739, ~870).

**Cómo lo haría yo:** loguear solo **metadatos** (nº de experiencias, modelo, tamaño del
prompt, duración, status HTTP). Guardar requests/responses completos solo detrás de un flag
`CV_DEBUG=1` y con aviso. Usar `RotatingFileHandler(maxBytes=5MB, backupCount=3)` y un
`request_id` corto (uuid4[:8]) en cada línea para correlacionar.

### V2-03: API key en texto plano — 🟣 gemini

**Problema:** `save_ai_config()` ([ai_analyzer.py](ai_analyzer.py) líneas 54-56) persiste la
API key de Ollama Cloud en claro en `.ai_config.json`.

**Cómo lo haría yo:** prioridad de lectura `os.getenv("OLLAMA_API_KEY")` → `.ai_config.json`
(fallback para no romper el flujo actual). Documentar en README la opción de variable de
entorno. No guardar la key si vino del entorno.

### V2-04: Escritura atómica y carga defensiva del banco — 🟦 opencode

**Problema:** `save_banco()` ([banco.py](banco.py) líneas 38-44) escribe el JSON directo:
un crash a mitad de escritura corrompe el archivo maestro **y se pierden todos los datos**.
`load_banco()` (líneas 29-35) no captura `JSONDecodeError`: con archivo corrupto la app
revienta o retorna `{}` sin avisar.

**Cómo lo haría yo:** escribir a `banco_personal.json.tmp` + `os.replace()` (atómico) y
conservar un `.bak` de la versión anterior. En `load_banco()`, capturar `JSONDecodeError`,
intentar el `.bak`, y propagar un aviso visible en la UI en vez de silencio.
*(Si V2-01 adopta SQLite, esto aplica igual al export JSON y el WAL de SQLite ya cubre la
atomicidad principal.)*

### V2-05: Merge banco↔CV por ID, no por posición — 🧠 Claude

**Problema:** `merge_cv_to_bank()` ([banco.py](banco.py) líneas 362-380) empareja la i-ésima
experiencia del CV con la i-ésima del banco. Si el usuario reordena, agrega o elimina
experiencias en el tab Manual, el merge escribe los bullets en la experiencia equivocada y
**corrompe el banco**.

**Cómo lo haría yo:** todos los items ya tienen `id` (`generate_bank_id`). Emparejar por
`id`; items del CV sin match en el banco se agregan como nuevos; items del banco sin match
se conservan (son el master set). Cubrir con tests (ver V2-19) los casos: reorden,
eliminación intermedia, item nuevo.

### V2-06: Escape HTML consistente (XSS) — 🟦 opencode

**Problema:** datos del usuario se interpolan en HTML/Markdown sin escapar de forma
consistente: navbar de score ([ui_components.py](ui_components.py) líneas 84-89), labels de
checkboxes del banco (línea 1248), y `st.markdown(user_input)` en los chats (líneas 670 y
1015). Un CV importado de un JSON ajeno podría inyectar markup.

**Cómo lo haría yo:** regla única — todo dato de usuario que entre a un f-string HTML pasa
por `html.escape()`; en los chats usar `st.write()` o `st.chat_message` con texto plano.
Crear helper `safe_html(text)` y usarlo en los ~10 puntos de interpolación.

---

## Fase 2 — Robustez de la capa IA

### V2-07: Helper único `_call_ollama()` — 🧠 Claude

**Problema:** el patrón `httpx.post → raise_for_status → data["message"]["content"]` está
copiado **7 veces**: [ai_analyzer.py](ai_analyzer.py) líneas 320-363, 447-466, 530-549,
595-617, 718-755, 850-883 y [translate.py](translate.py) líneas 125-138. Ninguna copia
reintenta ante fallos transitorios ni valida que la respuesta no venga vacía; el acceso
`data["message"]["content"]` lanza `KeyError` si Ollama cambia el shape de error.

**Cómo lo haría yo:**
```python
def call_ollama(messages, *, model, api_key, json_mode=False, temperature=0.3) -> str:
    """POST único con: retry (tenacity, 3 intentos, backoff exponencial),
    timeout, acceso seguro con .get(), ValueError si content vacío,
    y logging de metadatos con request_id."""
```
en un módulo nuevo `llm_client.py`, y las 7 llamadas se reducen a una línea cada una.

> **✅ Hecho (2026-06-12):** creado [llm_client.py](llm_client.py) con `call_ollama(messages, *, model,
> api_key, json_mode, options, timeout, retries, request_id)`: retry con backoff exponencial
> (sin tenacity, `time.sleep`), acceso seguro `.get()` (no más `KeyError`), `LLMError` si el
> contenido viene vacío. También expone `OLLAMA_CLOUD_URL`, `_parse_json_response` y
> `get_logger()` (logger compartido). Las 7 llamadas (6 en `ai_analyzer.py` + 1 en
> `translate.py`) ahora usan el helper. **De paso se arregló la regresión de V2-02**: el
> formatter `[%(request_id)s]` rompía todos los logs (KeyError) — el logger nuevo embebe el
> request_id en el mensaje.
>
> **🟢 V2-09 (opencode) ya está desbloqueada:** `OLLAMA_CLOUD_URL`, `_parse_json_response` y el
> logger común viven en `llm_client.py`; `translate.py` ya importa de ahí y usa el parsing
> tolerante (se eliminó su `json.loads` sin try). Falta solo lo mecánico de V2-09: pasar los
> `print()` de `translate.py` a `logger` y subir los `import` al tope del módulo.

### V2-08: Validar respuestas del LLM con Pydantic — 🧠 Claude

**Problema:** el shape esperado de cada respuesta JSON solo vive como texto dentro del
prompt. `_parse_json_response()` recorta con `rfind("}")` (frágil ante JSON truncado) y
[translate.py](translate.py) línea 148 hace `json.loads(raw_reply)` **sin try/except** —
crash directo si el modelo responde con texto.

**Cómo lo haría yo:** definir en [validation.py](validation.py) un modelo por endpoint
(`VacancyAnalysisResponse` con `match_score: int = Field(ge=0, le=100)`,
`DetailedEvalResponse`, `BankSelectionResponse`, `TranslationResponse`). Tras parsear:
`Model.model_validate(parsed)`; ante `ValidationError`, un único reintento pidiendo al
modelo que corrija, y si falla, error legible en la UI con el raw guardado solo en modo
debug.

> **✅ Hecho (2026-06-12):** en [validation.py](validation.py) se añadieron `VacancyAnalysisResponse`
> (`match_score: int = Field(ge=0, le=100)`), `DetailedEvalResponse`, `BankSelectionResponse` y
> `TranslationResponse`. `ai_analyzer._call_validated()` parsea → valida → **reintenta una vez**
> pidiendo corrección → si vuelve a fallar lanza `ValueError` legible. Aplicado a
> `analyze_vacancy`, `evaluate_cv_detailed` y `select_from_bank`; la traducción usa un chequeo
> suave (warning) porque la reparación item-a-item de V2-11 ya cubre faltantes. **De paso se
> arregló la regresión de V2-18**: faltaba `from typing import List`, lo que dejaba todos los
> modelos Pydantic "not fully defined" y reventaba `parse_cv` en runtime.

### V2-09: Unificar parsing, constantes y logging — 🟦 opencode

**Problema:** [translate.py](translate.py) redefine la URL de Ollama (línea 124), implementa
su propio strip de fences markdown (líneas 143-146) en vez de reutilizar
`_parse_json_response`, usa `print()` en vez de logger (líneas 100, 174, 182, 186, 202, 241)
e importa `httpx/json/copy` dentro de funciones (líneas 106-108, 184).

**Cómo lo haría yo:** mover `OLLAMA_CLOUD_URL`, `_parse_json_response` y el logger común al
nuevo `llm_client.py` (V2-07); `translate.py` y `ai_analyzer.py` los importan de ahí.
Imports al tope del módulo, `print` → `logger`.

### V2-10: Externalizar prompts — 🟣 gemini

**Problema:** 8 system prompts (~500 líneas, el principal de 155 líneas) hardcodeados en
[ai_analyzer.py](ai_analyzer.py) líneas 84-806. Editar una regla anti-overfitting implica
editar código Python; no hay forma de versionar/comparar prompts.

**Cómo lo haría yo:** carpeta `prompts/` con un `.md` por prompt (`analyze.md`, `eval.md`,
`bank_selection.md`, …) cargados una vez al import con un loader de 10 líneas y fallback a
constantes si falta el archivo. De paso, compactar las 7 bandas de score a una tabla
(reduce ~30% los tokens del system prompt en cada análisis).

### V2-11: Traducción sin pérdida silenciosa de items — 🟦 opencode

**Problema:** [translate.py](translate.py) líneas 152-163 hace
`zip(data["experiences"], translated["experiences"])`: si el LLM devuelve menos items de los
enviados, los últimos quedan sin traducir **sin ningún aviso**.

**Cómo lo haría yo:** comparar largos antes del zip; ante desajuste, loguear warning y
traducir los items faltantes individualmente vía el fallback de Google Translate (ya
existe `translate_text`). Nunca dejar contenido a medias sin avisar.

---

## Fase 3 — Mantenibilidad de la UI

### V2-12: Partir `ui_components.py` en paquete `ui/` — 🟦 opencode

**Problema:** [ui_components.py](ui_components.py) tiene 1327 líneas;
`render_manual_tab` ~205 líneas, `render_banco_tab` ~146. El archivo concentra los 5 tabs,
sidebar, navbar y el diff viewer.

**Cómo lo haría yo:** mismo movimiento mecánico que MEJ-06, un nivel más abajo:
```
ui/
  __init__.py      # re-exporta los render_* (app.py no cambia)
  navbar.py        sidebar.py        diff_viewer.py
  tab_analysis.py  tab_manual.py     tab_chat.py
  tab_eval.py      tab_banco.py
```
Solo mover código, cero cambios de lógica, verificando con la app corriendo tras cada
módulo extraído.

### V2-13: Constantes de session_state — 🟣 gemini

**Problema:** 120+ referencias a keys mágicas (`"analysis_result"`, `"cv_adapted"`,
`"_needs_widget_push"`, `"refine_chat_open"`, …) repartidas por `ui_components.py`,
`helpers.py` y `app.py`. Un typo en una key falla en silencio.

**Cómo lo haría yo:** módulo `session_keys.py` con constantes
(`ANALYSIS_RESULT = "analysis_result"`, …) + docstring de qué guarda cada una y quién la
escribe. Reemplazo mecánico con búsqueda global.

### V2-14: Excepciones específicas en lugar de `except Exception` — 🟦 opencode

**Problema:** 34 `except Exception` en [ui_components.py](ui_components.py); además
`load_ai_config()` ([ai_analyzer.py](ai_analyzer.py) línea 50) traga cualquier error
devolviendo `{}`, y `parse_cv()` ([validation.py](validation.py) líneas 132-137) descarta
los errores de Pydantic sin mostrarlos — el usuario nunca sabe por qué su JSON no importó.

**Cómo lo haría yo:** capturar lo esperado (`httpx.HTTPError`, `json.JSONDecodeError`,
`ValidationError`, `KeyError`) y dejar burbujear lo inesperado con `logger.exception`.
`parse_cv()` debe devolver `(data, problemas: list[str])` y la UI mostrar los problemas
en un `st.warning`.

### V2-15: Borrado por ID + helper de color de score — 🟣 gemini

**Problema:** los botones de eliminar experiencia/proyecto/skill guardan el **índice** y
hacen `pop(idx)` tras el loop ([ui_components.py](ui_components.py) líneas 780-821) —
frágil ante reruns y doble click. El coloreo del score (verde/naranja/rojo) está duplicado
en líneas 78-83 y 1100-1105.

**Cómo lo haría yo:** botones que guardan el `id` del item y borrado con list comprehension
(`d["experiences"] = [e for e in ... if e["id"] != target_id]`). Extraer
`get_score_color(score) -> str` a [helpers.py](helpers.py).

---

## Fase 4 — PDF y validación

### V2-16: Conteo de páginas exacto y escalado con tope — 🟦 opencode

**Problema:** [pdf.py](pdf.py) línea 300 cuenta páginas con regex sobre los bytes del PDF
(`/Type /Page`) — heurístico, puede dar falsos positivos. El bucle de escalado (líneas
115-116) baja hasta `sf=0.76` y si aun así no cabe, **entrega el PDF de 2 páginas sin
avisar**.

**Cómo lo haría yo:** `pypdf.PdfReader(buffer).get_num_pages()` (dependencia pura-Python,
ligera). Si tras el factor mínimo sigue >1 página, retornar también un flag para que la UI
muestre "No cupo en 1 página: desactiva items en el Banco" en vez de degradar tipografía a
ilegible o fallar en silencio.

### V2-17: Saneo de texto para ReportLab — 🟣 gemini

**Problema:** `safe()` ([pdf.py](pdf.py) líneas 98-103) escapa XML pero no filtra
caracteres de control (0x00-0x1F), que pueden romper `Paragraph`. `_winansi_safe()`
(líneas 71-93) usa NFKD, que puede descomponer acentos y degradar texto como "São Paulo".

**Cómo lo haría yo:** regex `[\x00-\x08\x0b\x0c\x0e-\x1f]` → `""` antes del escape; probar
cada char contra cp1252 con `char.encode("cp1252", errors="strict")` y solo aplicar
descomposición al que falle, no a toda la cadena.

### V2-18: Endurecer `validation.py` — 🟣 gemini

**Problema:** regex de email demasiado permisivo ([validation.py](validation.py) líneas
25-26); LinkedIn validado por substring `"linkedin.com/in/"` (línea 45) que acepta
`notalinkedin.com/in/x`; los modelos aceptan strings vacíos en campos críticos.

**Cómo lo haría yo:** validar LinkedIn con `urlparse` comprobando hostname ∈
{`linkedin.com`, `www.linkedin.com`}; email con regex más estricto (o `email-validator` si
se acepta la dependencia); `Field(min_length=1)` en `company`, `title`, `name`.

---

## Fase 5 — Calidad de base

### V2-19: Suite de tests con pytest — 🧠 Claude

**Problema:** cero tests. El bug de merge por índice (V2-05) es exactamente la clase de
regresión que una suite habría atrapado. Ya se usó `AppTest` puntualmente en MEJ-05 pero no
quedó nada versionado.

**Cómo lo haría yo:** carpeta `tests/` con:
- `test_banco.py` — merge por ID (reorden/borrado/nuevo), toggle, migración config→banco.
- `test_validation.py` — `parse_cv()` con JSON válido, campos faltantes, tipos erróneos.
- `test_llm_client.py` — `_parse_json_response` (con fences, sin fences, truncado, vacío) y
  `call_ollama` con `httpx` mockeado (éxito, 500+retry, respuesta sin `message`).
- `test_pdf.py` — CV grande genera 1 página (verificado con `pypdf`), caracteres especiales.
- `test_translate.py` — desajuste de largos (V2-11) activa el fallback.

Las funciones puras de `banco.py`, `validation.py` y `pdf.py` no tocan Streamlit, así que
no requieren mocks de UI. Objetivo realista inicial: cubrir la lógica de datos, no la UI.

### V2-20: Pinear dependencias — 🟣 gemini

**Problema:** [requirements.txt](requirements.txt) lista 5 paquetes sin versión — un
`pip install` futuro puede traer un Streamlit o Pydantic incompatible.

**Cómo lo haría yo:** `pip freeze` de las 5 directas con `>=x.y,<x+1` y agregar las nuevas
(`pytest`, `tenacity`, `pypdf`) cuando entren por V2-07/16/19.

### V2-21: Migración idempotente — 🟣 gemini  ⛔ N/A

> **N/A (2026-06-12):** cancelada por la decisión de V2-01 (Solo JSON). El script
> `migrate_json_to_sqlite.py` fue eliminado, así que no hay nada que volver idempotente.
> gemini puede saltarla.


**Problema:** [migrate_json_to_sqlite.py](migrate_json_to_sqlite.py) (líneas 20-22)
re-ejecutado pisa el contenido del `.db` con el JSON sin preguntar; la verificación
(líneas 42-47) solo compara conteos, no IDs.

**Cómo lo haría yo:** si el `.db` ya tiene datos, exigir `--force` y crear backup del `.db`
antes; verificar por conjuntos de IDs, no por conteo. *(Si V2-01 elimina el flujo JSON,
este script se vuelve one-shot y luego se archiva.)*

### V2-22: Limpieza del repo — 🟣 gemini

**Problema:** hay artefactos generados/personales en el working tree: `cv_generator.db`
(datos personales), `test_cv.pdf`, `banco_habilidades_alexvitesse.html`, `__pycache__/`,
`skills-lock.json`, `.continue/`, `.agents/`.

**Cómo lo haría yo:** agregar a [.gitignore](.gitignore): `*.db`, `*.html` de análisis ya
está parcialmente, `.continue/`, `.agents/`. Verificar con `git status` que ningún archivo
con datos personales quede en staging antes del próximo commit.

---

## Reparto de trabajo por agente

### 🧠 Claude — arquitectura y riesgo de corrupción (5 tareas)
Las que deciden la estructura, pueden destruir datos del usuario o habilitan al resto.
- **V2-01** — decisión arquitectónica JSON vs SQLite. *Bloqueante: condiciona V2-04, V2-05 y V2-21. Hacer primero.*
- **V2-05** — merge banco↔CV por ID. *Corrupción silenciosa del banco; depende de tener los tests de V2-19 como red.*
- **V2-07** — helper único `call_ollama()` en `llm_client.py`. *Habilita V2-08 y V2-09; tocar antes que ellas.*
- **V2-08** — validación Pydantic de respuestas del LLM. *Depende de V2-07.*
- **V2-19** — suite pytest. *Escribir los tests de banco ANTES de tocar V2-05.*

### 🟦 opencode — refactors medios bien acotados (8 tareas)
Cambios de tamaño medio, con superficie clara y bajo riesgo de romper datos.
- **V2-02** — privacidad en logs (metadatos + `RotatingFileHandler` + flag `CV_DEBUG`).
- **V2-04** — escritura atómica del banco (`.tmp` + `os.replace` + `.bak`). *Esperar a V2-01.*
- **V2-06** — escape HTML consistente / helper `safe_html()`.
- **V2-09** — unificar parsing/constantes/logging. *Esperar a que Claude cierre V2-07.*
- **V2-11** — traducción sin pérdida silenciosa (validar largos antes del `zip`).
- **V2-12** — partir `ui_components.py` en paquete `ui/` (solo mover código, cero lógica).
- **V2-14** — excepciones específicas en vez de `except Exception`.
- **V2-16** — conteo de páginas con `pypdf` + flag "no cupo en 1 página".

### 🟣 gemini — mecánico, reemplazos globales, bajo riesgo (9 tareas)
Cambios localizados o de búsqueda-reemplazo, sin dependencias entre sí.
- **V2-03** — leer API key de `OLLAMA_API_KEY` antes que del archivo.
- **V2-10** — externalizar prompts a `prompts/*.md` con loader + fallback.
- **V2-13** — `session_keys.py` con constantes (reemplazo mecánico global).
- **V2-15** — borrado por ID + extraer `get_score_color()` a `helpers.py`.
- **V2-17** — saneo de caracteres de control y normalización Unicode en `pdf.py`.
- **V2-18** — endurecer validadores (email, LinkedIn con `urlparse`, `min_length=1`).
- **V2-20** — pinear versiones en `requirements.txt`.
- **V2-21** — `migrate_json_to_sqlite.py` idempotente (`--force` + backup + IDs). *Esperar a V2-01.*
- **V2-22** — limpieza del repo y `.gitignore`.

### Dependencias entre agentes (qué esperar)
- **opencode y gemini esperan a Claude en V2-01** antes de tocar V2-04 / V2-21 (dónde vive el almacén).
- **opencode espera a Claude en V2-07** antes de V2-09 (importa de `llm_client.py`).
- Todo lo demás es **paralelizable** desde ya.

---

## Orden de ejecución recomendado

```
V2-01 (decidir almacén)  ──►  condiciona dónde se implementan V2-04, V2-05, V2-21
        │
Fase 1 (V2-02…06)        ──►  riesgo real: pérdida de datos y privacidad. Hacer ya.
        │
Fase 2 (V2-07…11)        ──►  V2-07 primero: el helper único habilita V2-08 y V2-09.
        │
Fase 5 / V2-19 (tests)   ──►  escribir los tests de banco ANTES de tocar V2-05
        │                     (red de seguridad para el refactor).
Fases 3 y 4              ──►  mantenibilidad; sin dependencias entre sí, paralelizables.
```

## Verificación global

1. `pytest` en verde tras cada fase.
2. `streamlit run app.py`: flujo completo (cargar banco → analizar vacante → aplicar
   adaptaciones → traducir → PDF de 1 página) funciona igual que antes de cada refactor.
3. `git status` sin archivos personales; `logs/` sin datos sensibles tras un análisis.
