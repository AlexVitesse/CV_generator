# Fix — Regresiones introducidas por el refactor de UI/prompts

**Fecha:** 2026-07-20 · **Rama:** `main` (working tree, sin commitear)

Revisión completa del diff pendiente (35 candidatos verificados, 10 hallazgos
confirmados + 1 del pase de verificación). Varios cambios del refactor
(`017858c`, prompt como array de tiers, config multi-proveedor, certificaciones)
**rompieron mecanismos de seguridad que este mismo repo había construido** en
`ae46442` y `a17b9c0`. Resultado: **95 tests en verde** (3 nuevos en
`tests/test_guards.py`).

---

## Bugs detectados y fixes

### Críticos

| # | Archivo | Causa raíz | Fix |
|---|---------|-----------|-----|
| **1** | `ai_analyzer.py` `save_ai_config` | `load_ai_config` re-inyecta `OLLAMA_API_KEY` (env) en `providers['ollama']`; al guardar OpenAI/Gemini se reescribe el mapa completo → la key de entorno queda en claro en `.ai_config.json` (dir sincronizado a OneDrive). El guard viejo solo cubría `provider=='ollama'`. | Tras construir `providers`, borrar la key de Ollama si coincide con la de entorno, **sin importar** qué proveedor se guarde. |
| **2** | `helpers.py` `sanitize_ai_result` | El prompt nuevo devuelve `skills` como **array (una línea por tier)**; los guards `_enforce_skill_tiers`/`_demote_missing_keyword_skills` corrían por línea suelta → `ranks_present={rank}` → ninguna democión posible. La inflación de tiers que `ae46442` bloqueaba volvía a pasar. | Combinar las líneas de tier en un solo string (`" | "`), correr los guards **una vez** sobre todos los tiers juntos, preservar líneas no-tier (certs/idiomas). |
| **3** | `translate.py` `_restore_ids_with_fallback` | Si el LLM omitía un item **intermedio**, el realineado compactaba la lista, el fallback re-traducía por la cola y el `zip` posicional corría los ids: bullets de B bajo A, C duplicado, A perdido. | Realineado **posicional con huecos**: una posición por original (ancla por id, o `None` si falta); cada `None` se rellena traduciendo **su propio** original. |
| **4** | `metrics_guard.py` `find_fabricated_metrics` | Usaba `fallback="index"`, pero el prompt nuevo ya no emite `index` → `resolve_target_index` devolvía `None` → `continue`: métrica inventada no se revisaba, mientras el diff viewer sí la ofrecía. | Ver #5 (mismo fix compartido). |

### Altos

| # | Archivo | Causa raíz | Fix |
|---|---------|-----------|-----|
| **5** | `metrics_guard.py` `resolve_target_index` | El fallback por contenido devolvía `None` sin consultar nunca el `index` del modelo → con resultados cacheados o bullets en otro idioma, la adaptación se descartaba con solo un warning (el usuario "aplica" y no ve cambios). | Encadenar **id → contenido → index** (antes cortaba tras el primer fallback). `fallback=` solo fija la **prioridad**: guard de métricas prefiere `index` (detecta trasplantes), diff viewer prefiere `content` (aplica al ítem correcto). Un solo cambio arregla #4 y #5. |
| **6** | `ai_analyzer.py` `_load_prompt` | Si `prompts/analyze.md` faltaba o fallaba la lectura, el `except` tragaba todo y corría con fallback de 2 líneas — sin log — perdiendo todas las reglas anti-fabricación. | `logger.warning`/`logger.exception` al caer al fallback (archivo ausente o ilegible). |

### Medios

| # | Archivo | Causa raíz | Fix |
|---|---------|-----------|-----|
| **7** | `ui/sidebar.py` | Al cambiar de proveedor se llamaba `save_ai_config(cur_provider, …)` (el viejo); el nuevo solo se persistía si luego editabas key/modelo → al reiniciar revertía a Ollama. | Persistir también el proveedor activo nuevo con `save_ai_config(sel_provider, …)`. |
| **8** | `ui/tab_analysis.py` | `_toggle_all(banco, True)` mutaba el banco de **sesión** antes de analizar; si `analyze_vacancy` lanzaba, la selección curada quedaba en todo-activo y se persistía luego. | Construir `d_full` sobre `copy.deepcopy(banco)`; nunca mutar el banco de sesión. |
| **9** | `ai_analyzer.py` `_reintegrate_lost_evidence` | `k in covered` (substring): "Java" quedaba "cubierto" por "JavaScript", "Go" por "Google" → se perdía el bullet real. | Helper `_covers(kw, text)` con `\b` word-boundary. `# ponytail:` C++/C# no cubiertos por `\b`. |
| **10** | `ui/sidebar.py` | `clear_keys("x_","p_","e_","s_","f_")` omitía `c_tx_`/`c_cid_` → al re-importar JSON las certs conservaban el texto viejo editado y eso imprimía el PDF. | Añadir `"c_tx_", "c_cid_"` a ambas llamadas. |
| **11** | `pdf.py` | Cert/skill dict sin `"text"` → `cert.get("text", cert)` devuelve el dict → `str(dict)` imprime el repr completo, incluyendo `credential_id` (que se decidió NO imprimir). | `cert.get("text", "")` en cert (`:323`) y skill (`:336`). |

---

## Tests añadidos (`tests/test_guards.py`)

- `test_translate_omitted_middle_item_no_misattribution` (#3)
- `test_skill_tiers_enforced_on_array_form` (#2)
- `test_java_not_covered_by_javascript` (#9)

**95 passed.** Los tests existentes de realineado por id y reintegración siguen en verde.

---

## Notas de diseño

- **#4+#5 con un solo cambio** en `resolve_target_index`: el guard de métricas
  conserva su prioridad `index` para detectar trasplantes, el diff viewer conserva
  `content` para aplicar bien, y ninguno descarta ya por falta de `index`.
- **#2** colapsa a una línea `" | "` (como ya hacía el `_apply_selected_changes`
  del diff viewer). Limitación conocida: si el modelo devuelve **un solo tier**,
  `_enforce_skill_tiers` sigue sin poder degradar (necesita el tier destino
  presente en la sugerencia). Con los 3 tiers habituales funciona.
