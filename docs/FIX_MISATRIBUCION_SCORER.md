# Fix — Misatribución de experiencias + scorer bimodal + pérdida de evidencia

**Fecha:** 2026-06-18 · rama `main`

Diagnóstico sobre logs reales del caso **88% → 35%** y de **contenido cruzado entre experiencias**
(los bullets de Cóndor bajo ZAPI, los de DCM bajo Cóndor). Evidencia dura en
`logs/response_20260612_152818.json`. Resultado: **72 tests en verde** (+16 nuevos en `tests/test_guards.py`).

---

## Bugs detectados

| # | Problema | Evidencia |
|---|----------|-----------|
| **A** *(crítico)* | Las sugerencias se aplicaban al CV **por índice entero**. El modelo numera `index` según SU ranking de relevancia (no la posición del array) y no devolvía `id`. | `index=0, title="AI Engineer Jr."` con bullet *"FastAPI en Oracle Cloud, 1,200 solicitudes"* (contenido de **Ingeniería Cóndor**), pero `experiences[0]` = **DCM Moguls**. |
| **B** | Scorer **bimodal**: el LLM colapsa a ~90/~35; `35` es un valor-imán desconectado del match real. | 16 keywords cubiertas / 5 faltantes seguía dando 35. |
| **C** | "Adaptar" a 1 página **tira evidencia** de keywords ya matcheados. | 18 keywords → 14 tras la selección de banco. |

---

## Qué se implementó

### Bug A — Anclar sugerencias por `id` (no por índice)
- **`metrics_guard.resolve_target_index(suggestion, items, *, kind, fallback)`** — resolver puro:
  ancla por `id` (que el modelo ve en el CV JSON); fallback `"content"` (proveniencia por
  solapamiento de tokens discriminantes: FastAPI, ESP32, RunPod…, sobreviven reescritura y
  traducción) para **aplicar**, o `"index"` (intención declarada del modelo) para el **guard de
  métricas**. Si nada es confiable → `None` (descartar, NUNCA `items[0]`).
- **`ui/diff_viewer.py`** — resuelve el índice real una sola vez en `_collect_suggestion_changes`
  y lo guarda en `ch["index"]`; descarta + `logger.warning` si no hay match confiable.
- **`prompts/analyze.md`** + **`USER_PROMPT_TEMPLATE`** / **`EXTRACT_PATCH_PROMPT`** — exigen `id`
  (sugerencias) y `target_id` (chat patch).
- **`helpers.apply_chat_patch`** — `_resolve_patch_index` ancla por `target_id`, fallback a `target_index`.
- **`translate._restore_ids_with_fallback`** — re-alinea los items traducidos **por `id`** antes de
  restaurarlos (antes asignaba por posición con `zip` → cruzaba datos si el LLM reordenaba).
- **`metrics_guard.find_fabricated_metrics`** — ahora resuelve el origen por `id`/`index` (no por el
  index crudo), así el guard anti-fabricación no se equivoca de ítem.

### Bug B — Guard de reconciliación score ↔ cobertura
- **`helpers._reconcile_score_with_coverage`** (puro) — `cobertura = matched/(matched+missing)` →
  **piso** por banda (0.85→70, 0.70→60, 0.55→50). Solo SUBE el score (nunca lo baja), matando el
  imán-35 cuando la cobertura es alta. Cableado en `sanitize_ai_result` antes de reconciliar `viable`.

### Bug C — Preservar evidencia en `select_from_bank`
- **`ai_analyzer._reintegrate_lost_evidence`** (puro) — tras la selección, si un `protected_keyword`
  perdió su única evidencia, re-agrega el item del manifest que sí lo evidencia. Red de seguridad
  determinística sobre la regla que el prompt ya pedía.

---

## Archivos tocados

```
metrics_guard.py     resolve_target_index + tokens; find_fabricated_metrics por id/index
ai_analyzer.py       id en plantillas + EXTRACT_PATCH_PROMPT; _reintegrate_lost_evidence en select_from_bank
ui/diff_viewer.py    resolución por id/contenido + descarte/log
ui/tab_chat.py       muestra el destino real (empresa/proyecto) resuelto por id
helpers.py           apply_chat_patch target_id; _reconcile_score_with_coverage en sanitize_ai_result
prompts/analyze.md   regla de ancla por id
translate.py         _restore_ids_with_fallback alinea por id
tests/test_guards.py 16 tests nuevos (A, B, C, translate)
```

## Cómo verificar

```bash
./venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/e2e_filter_test.py   # 72 passed
```

Validado contra el log real: la sugerencia mal-atribuida (`index=0`, sin id) resuelve a
**Ingeniería Cóndor**, no a DCM. El caso 16/5→35 sube a 60 por el piso de cobertura.

## Pendiente
- [ ] Probar end-to-end en la app: misma vacante 88→35, Adaptar, confirmar (1) sin contenido cruzado
  y (2) el re-score ya no cae a 35.
- [ ] `git push` (local va por delante de `origin/main`).
