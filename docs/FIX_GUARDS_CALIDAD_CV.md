# Fix — Guards de calidad en la adaptación de CV

**Fecha:** 2026-06-16 · **Commit:** `ae46442` (rama `main`)

Diagnóstico hecho sobre CVs reales generados (revisión de `logs/response_*.json`,
sesión del 12-jun). Se detectaron 3 problemas y se aplicaron defensas deterministas
+ ajustes de prompt. Resultado: **56 tests en verde** (12 nuevos en `tests/test_guards.py`).

---

## Bugs detectados

| # | Problema | Evidencia en logs |
|---|----------|-------------------|
| **#1** | La IA **inventa métricas** y **trasplanta** números de un ítem a otro. | "1,200 solicitudes/día" (real de Ingeniería Cóndor) apareciendo bajo ZAPI; `30%`/`25%`/`100%` inventados en bullets de DCM; "15,000 líneas de código" → "15,000 interacciones". |
| **#2** | **Tier de skills**: skills inferidas subían demasiado y una skill marcada como faltante aparecía como conocimiento sólido. | "Next.js" en `missing_keywords` y a la vez en *working knowledge* (contradicción). |
| **#3** | **Umbral de viabilidad inconsistente**. | `score 78 → viable False` junto a `score 60 → viable True`. |

> **Nota #2 — criterio del usuario:** inferir tecnología adyacente que sí se ha
> tocado (Supabase, Vercel, Render) es **válido**; el defecto era el *tier* y la
> contradicción, no agregar la skill. Ver memoria `skills-adyacentes-tier-bajo`.

---

## Qué se implementó

### Bug #1 — Anti-fabricación de métricas
- **`metrics_guard.py`** (módulo puro, sin Streamlit):
  - `extract_metrics(text)` — extrae métricas "fuertes" (todo `%`, o números de 2+
    dígitos; ignora dígitos sueltos tipo "3 fases").
  - `find_fabricated_metrics(suggestions, cv_data)` — por cada experiencia/proyecto
    sugerido, verifica que cada número exista en el **mismo ítem de origen** (por
    `index`). El summary se compara contra todo el CV. Detecta inventados **y**
    trasplantes entre ítems.
- **`ai_analyzer._repair_metrics_once`** — si hay métricas sin respaldo, hace **un
  retry dirigido** pidiendo corregir solo esos casos (mismo patrón de reintento que
  `_call_validated`). Si la corrección no valida o no mejora, conserva el original.
  Cableado dentro de `analyze_vacancy` tras la validación.
- **`prompts/analyze.md`**:
  - Se eliminó *"Cada bullet DEBE tener métrica cuantitativa"* (era la causa raíz:
    forzaba a inventar números cuando el origen no tenía).
  - Se añadió la regla **"MÉTRICAS — PROVENIENCIA OBLIGATORIA"**: cada número debe
    existir textualmente en el mismo ítem; prohibido inventar, mover o cambiar el
    significado de una cifra.

### Bug #2 — Tier de skills
- **`helpers._enforce_skill_tiers`**: las skills inferidas nuevas van al **tier más
  bajo** (Familiaridad/Exposure to), ya no a intermedio.
- **`helpers._demote_missing_keyword_skills`** (nuevo): cualquier skill listada en
  `missing_keywords` se baja al tier más bajo si la IA la puso por encima de "exposure".
- Cableado en `sanitize_ai_result`. Prompt (reglas 3A y 6) alineado.

### Bug #3 — Viabilidad
- Ya estaba resuelto en `sanitize_ai_result` (reconcilia `score ↔ viable`: ≥70→viable,
  <50→no viable, 50-69→criterio del modelo). Se añadieron **tests de regresión**.

---

## Archivos tocados

```
metrics_guard.py        (nuevo)   guard puro de métricas
tests/test_guards.py    (nuevo)   regresión de los 3 guards
ai_analyzer.py          mod       _repair_metrics_once + wiring en analyze_vacancy
helpers.py              mod       tier más bajo + _demote_missing_keyword_skills
prompts/analyze.md      mod       regla de proveniencia + tiers
ui/tab_analysis.py      mod       pasa protected_keywords a select_from_bank
```

No commiteado: `banco_personal.json.bak` (respaldo). `banco_personal.json` está en
`.gitignore` (data local).

---

## Cómo verificar

```bash
# Suite completa (excluye e2e que requiere API key)
./venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/e2e_filter_test.py

# Guard contra un CV real del log
./venv/Scripts/python.exe -c "import json; from metrics_guard import find_fabricated_metrics; \
cv=json.load(open('config_personal.json',encoding='utf-8')); \
r=json.loads(json.load(open('logs/response_20260612_151636.json',encoding='utf-8'))['raw_response']); \
print(find_fabricated_metrics(r['suggestions'], cv))"
```

Confirmado: captura los `30%`/`25%` inventados (DCM) y el `1,200` trasplantado (ZAPI).

---

## Pendiente / próximos pasos
- [ ] `git push` (local va 3 commits por delante de `origin/main`).
- [ ] Probar en la app contra una vacante real (validar el retry de reparación end-to-end).
- [ ] Opcional: el caso de **cambio de significado** de un número con mismo dígito
  (15,000 líneas → 15,000 usuarios) lo cubre solo el prompt, no el guard numérico.
```
