# Plan: Consistencia del scorer (analyze) y validación con e2e

**Fecha:** 2026-06-12
**Origen:** Resultados de `tests/e2e_filter_test.py` — el scorer rechaza un match legítimo
(`backend_py_en` → 60 / "automated testing" missing pese a estar en el CV), la fase de
sugerencias no aporta (90→90, 62→60) y el Base clavado en ~35 sugiere que el score
reacciona a cantidad de items más que al match real.

---

## Diagnóstico (verificado en código)

| # | Síntoma | Causa probable | Dónde |
|---|---------|----------------|-------|
| 1 | `backend_py_en` puntúa 60 y marca "automated testing" como missing aunque el CV tiene el bullet `bul_dcm_testing` ("pruebas de backend (testing automatizado)…") | El JD está en inglés y la evidencia en español; `prompts/analyze.md` no instruye que un keyword cuente como match en **cualquier idioma**. El placeholder sin cuantificar `[cuantifica: % cobertura…]` debilita el bullet. | `prompts/analyze.md` (bandas de score, líneas 12-26), `banco_personal.json:71` |
| 2 | Fase C (sugerencias) no mueve el score: 90→90 y 62→60 | Toda la ganancia viene de la selección de banco (B). La adaptación de bullets recorta contenido (máx 5+3 bullets, máx 2 proyectos en `USER_PROMPT_TEMPLATE`) y si el scorer premia amplitud, C puede incluso restar. | `ai_analyzer.py:137-169`, `tests/e2e_filter_test.py:79-114` |
| 3 | Base ~35 constante sobre contenido que ya incluye los keywords | El scorer no exige enumerar evidencia por requisito; improvisa una impresión global influida por la cantidad/orden de items. Eso infla artificialmente el "+55" de mejora B−A. | `prompts/analyze.md` (procedimiento de score) |

**Decisión previa:** la selección de banco funciona — NO se toca. El ROI está en el scorer.

---

## Objetivo y criterios de éxito (medibles)

Correr `python3 tests/e2e_filter_test.py` antes (baseline ya existente) y después de cada fase:

1. ✅ `backend_py_en` FINAL ≥ 70 y `viable=true`, sin "automated testing" en `missing_keywords`.
2. ✅ `ai_rag_en` sigue pasando (no romper lo que funciona).
3. ✅ `frontend_react` (control) sigue `viable=false` — endurecer la consistencia NO puede
   aflojar la honestidad. Si el control se vuelve viable, la fase se revierte.
4. ✅ `senior_ai_5y` (stretch) sigue penalizado por años insuficientes.
5. ✅ Criterio del test `final >= base` se cumple en las vacantes `match`.

---

## Fase 1 — Endurecer consistencia del scorer en `prompts/analyze.md`

La fase de mayor ROI. Tres cambios al bloque "SCORE HONESTO":

### 1.1 Match cross-idioma (fix directo del bug #1)
Añadir regla explícita al procedimiento de score:

> Un requisito del JD cuenta como CUMPLIDO si la evidencia aparece en el CV **en cualquier
> idioma**. "automated testing" (JD en inglés) queda cubierto por "testing automatizado" /
> "pruebas automatizadas" (CV en español). Evalúa el CONCEPTO, no la cadena literal.
> Un keyword cubierto en otro idioma va en `matching_keywords`, NUNCA en `missing_keywords`.

### 1.2 Checklist de evidencia por must-have (fix del #3 — score por impresión)
Forzar un procedimiento enumerativo en vez de impresión global:

> Antes de asignar el score, construye internamente una tabla: requisito must-have → cita
> textual del CV que lo evidencia (o "SIN EVIDENCIA"). El score sale SOLO del conteo de esa
> tabla según las bandas. La cantidad de bullets/proyectos/skills NO suma por sí misma:
> 10 items irrelevantes valen menos que 3 que cubren los must-haves.
> En `reasoning`, lista cada must-have con ✓/✗ y su evidencia.

### 1.3 Reglas de coherencia interna (invariantes)
> - Si TODOS los must-haves tienen evidencia → `viable=true` y score ≥ 70. Sin excepciones.
> - Un keyword no puede estar a la vez en `matching_keywords` y `missing_keywords`.
> - `missing_keywords` solo contiene requisitos SIN evidencia en ningún idioma del CV.
> - Un placeholder editorial tipo `[cuantifica: …]` en un bullet NO invalida la evidencia
>   de la skill; la skill cuenta, la métrica pendiente se menciona en `reasoning`.

**Archivos:** solo `prompts/analyze.md`.
**Validación:** e2e completo; foco en criterio 1 y 3 (no aflojar el control).

## Fase 2 — Reducir varianza del scorer (soporta el fix del #2)

Con 90→90 y 62→60, parte del problema puede ser ruido run-to-run.

1. Revisar `ANALYSIS_OPTIONS` en `ai_analyzer.py`: fijar `temperature: 0` (o el mínimo
   soportado por Ollama Cloud) y `seed` si está disponible, SOLO para el análisis/score
   (no para generación de bullets, que sí se beneficia de creatividad).
2. Si analyze hace ambas cosas en una llamada (score + sugerencias), evaluar el trade-off
   y documentar la decisión; no separar la llamada en este plan (cambio mayor, otra iteración).

**Archivos:** `ai_analyzer.py` (solo opciones de la llamada).
**Validación:** correr `--quick` 3 veces seguidas; la dispersión del score de la misma
etapa debería ser ≤ ±3.

## Fase 3 — Diagnosticar por qué la fase C no aporta (no arreglar aún, medir)

Con el scorer ya consistente (Fases 1-2), re-medir B vs C:

1. Si tras el fix C ≥ B en todas las vacantes `match` → el "problema" era el scorer y
   no hay nada que arreglar en la adaptación. Cerrar como resuelto.
2. Si C sigue restando, comparar los CVs B y C de una corrida con `CV_DEBUG` activado
   (los requests/responses quedan en `logs/`): verificar si `apply_all_suggestions` está
   recortando contenido que cubría must-haves (límites de 5+3 bullets / 2 proyectos).
3. Solo entonces decidir: ajustar los límites del `USER_PROMPT_TEMPLATE`, o aceptar que
   C aporta calidad de redacción (vocabulario ATS) aunque no mueva el score numérico —
   y en ese caso cambiar el criterio del test a `final >= base - 2` (tolerancia de ruido).

**Archivos:** ninguno hasta tener datos.

## Fase 4 — Datos: rellenar placeholders del banco

Independiente del scorer pero suma:

1. `banco_personal.json:71` (`bul_dcm_testing`) tiene `[cuantifica: % cobertura…]`.
   Buscar otros placeholders: `grep -n "\[cuantifica" banco_personal.json`.
2. Pedir al usuario las cifras reales (cobertura, nº de servicios, regresiones evitadas)
   — NO inventarlas. Mientras tanto, la regla 1.3 evita que el placeholder penalice.

## Fase 5 — Cierre

1. E2e completo final (`~5 min`) y tabla antes/después en este mismo md.
2. Si todos los criterios pasan: commit con los cambios de prompt + opciones.

---

## Riesgos

- **Aflojar la honestidad:** instruir "si cumple todo → viable" podría hacer al modelo
  más generoso encontrando "evidencia". Mitigación: el control `frontend_react` y el
  stretch `senior_ai_5y` actúan de regresión — si cambian de veredicto, revertir.
- **Costo/tiempo:** cada corrida completa ~5 min y consume tokens. Usar `--quick` para
  iterar en Fase 2 y la corrida completa solo al validar cada fase.
- **No determinismo del LLM:** un solo run no prueba nada. Las comparaciones antes/después
  de Fase 1 deberían hacerse con 2 corridas si el resultado es limítrofe (±3 del umbral).

## Resultados Fase 1 (2026-06-12)

Cambios aplicados a `prompts/analyze.md`: (1.1) match cross-idioma, (1.2) tabla de evidencia
por must-have, (1.3) invariantes de coherencia, y refuerzo de la **regla 1 (años = span de
carrera desde la fecha de inicio más antigua, consistente entre vacantes)**.

E2e completo tras Fase 1:

| vacante | tipo | base | banco | final | resultado |
|---|---|---|---|---|---|
| ai_rag_en | match | 55 | 90 | 88 | ✅ PASA |
| backend_py_en | match | 55 | 40 | 58 | ❌ NO pasa |
| senior_ai_5y | stretch | 35 | 20 | 38 | ✓ honesto-no |
| frontend_react | control | 25 | 35 | 35 | ✓ honesto-no |

**Validado en aislamiento (1 llamada por caso):**
- ✓ El fix cross-idioma funciona: con la evidencia presente, "automated testing" pasa de
  `missing` a `matching` (el reasoning acredita "testing automatizado").
- ✓ Honestidad intacta: control y stretch siguen no-viables.
- ✓ La regla de años funciona: con el rol de Cóndor activo, el scorer reconoce
  "más de 2 años de experiencia backend (desde mayo 2024)" → **backend_py_en = 90, viable=True**.

**HALLAZGO que anula la premisa del plan ("no tocar la selección de banco"):**
El fallo de `backend_py_en` NO está en `analyze.md`. La causa raíz es de **datos/activación**:
`Ingeniería Cóndor` (Consultor TI — Backend & AI Engineer, Mayo 2024 – Actualidad, el ÚNICO
rol de 2 años de backend) tiene `active: false` en `banco_personal.json`. El CV base solo
expone 2 roles de 2026 (~6 meses) → el scorer es honesto al marcar "2+ years" como missing.
La selección IA activa Cóndor para `ai_rag_en` (→88) pero NO para una vacante de backend
(B bajó a 40). El bug real vive en la capa de selección de banco / activación, no en el scorer.

**Decisión tomada:** arreglar el prompt de selección de banco (no activar Cóndor a mano).

### Cierre Fase 1 (todos los criterios OK, e2e exit 0)

El bug resultó vivir en TRES capas, no solo el scorer. Cadena de fixes:

1. **Selección de banco (`get_bank_manifest` + `bank_selection.md`)** — el manifiesto no exponía
   las FECHAS de las experiencias, así que el selector no podía saber que Cóndor da 2 años.
   - `banco.py`: el texto de cada experiencia en el manifiesto ahora incluye `(dates)`.
   - `bank_selection.md`: regla de ANTIGÜEDAD (incluir el rol cuyo span cubre los años pedidos,
     nunca descartarlo por uno más reciente y corto) + regla de COBERTURA DE MUST-HAVES
     (las 2 experiencias conservadas deben cubrir juntas el máximo de obligatorios; si un
     must-have está en una sola experiencia, esa es de inclusión obligatoria).
2. **Generación de sugerencias (`analyze.md`)** — al recortar bullets a 5+3, la IA borraba el
   único bullet de testing, así que el stage C (FINAL) volvía a perder "automated testing".
   - Regla de PRESERVACIÓN DE EVIDENCIA: cada keyword en matching_keywords debe seguir teniendo
     evidencia en los bullets sugeridos; nunca dropear el único bullet de un must-have.
3. **Scorer (`analyze.md`, Fase 1 original)** — match cross-idioma, tabla de evidencia,
   invariantes de coherencia, años = span de carrera consistente entre vacantes.

| vacante | tipo | base | banco | final | resultado |
|---|---|---|---|---|---|
| ai_rag_en | match | 55 | 92 | 90 | ✅ PASA |
| backend_py_en | match | 60 | 92 | **92** | ✅ PASA (antes 58 ❌) |
| senior_ai_5y | stretch | 35 | 15 | 38 | ✓ honesto-no |
| frontend_react | control | 15 | 30 | 38 | ✓ honesto-no |

Criterios: [OK] match pasa filtro · [OK] final ≥ base · [OK] control no-viable.

**Archivos modificados:** `prompts/analyze.md`, `prompts/bank_selection.md`, `banco.py`.
**Nota:** la Fase 2 (temperature/varianza) ya no es bloqueante — el stage C dio resultados
estables (90→90, 92→92) en validaciones repetidas.

### Cierre Fases 2-4 (2026-06-12)

- **Fase 2 (varianza) ✅** — `ANALYSIS_OPTIONS` pasó de `{temperature:0.2, top_p:0.9}` a
  `{temperature:0, top_p:0.9, seed:42}` en `ai_analyzer.py`. Solo afecta score/eval/selección
  (la generación de texto libre usa `CHAT_OPTIONS`, intacta). 3× `--quick`: B=92/92/92 (disp. 0),
  C=92/90/92 (±1), A=38/40/40 (±1). Dispersión ≤±2, dentro del objetivo ≤±3.
- **Fase 3 (diagnóstico C) ✅ sin código** — con el scorer y la selección ya arreglados, C deja de
  restar: final ≥ base en todas las vacantes `match`. El "problema" era el scorer/selección, como
  hipotetizó el plan. El criterio del test `final >= base` se cumple sin necesidad de tolerancia.
- **Fase 4 (placeholders) ✅ N/A** — `grep` no encontró placeholders en `banco_personal.json`;
  el `[cuantifica…]` que citaba el plan ya estaba removido. Nada que rellenar.

### Fixes adicionales detectados durante la validación final

Al correr el e2e completo con temperature 0 aparecieron dos modos de fallo más, ambos del stage C:

4. **Pérdida de la línea de idiomas en skills (`ui/diff_viewer.py` + test)** — `ai_rag_en` caía a
   60 con "English working proficiency" en missing. La sugerencia de skills usa formato tech-tier
   ("Core/Working/Exposure") sin slot para idiomas, y el `apply` reemplazaba TODA la sección de
   skills preservando solo líneas de "Cert" → se perdía "Idiomas: … Inglés …".
   - Fix estructural: `apply` ahora preserva también las líneas de idiomas/soft skills
     (`"idioma"/"language"` además de `"cert"`), en la app real y en el test. Validado 2/2.

5. **Ruido del scorer marcando evidencia presente como missing (`analyze.md`)** — caracterizado con
   3 corridas del pipeline de backend: en las 3 el testing ESTABA en el CV final (incluso literal
   "automated testing suites"), pero el scorer lo marcaba missing ~1 de cada 3 (puro no-determinismo
   del modelo cloud, no drop de contenido).
   - Fix: paso de VERIFICACIÓN FINAL OBLIGATORIA en `analyze.md` — re-escanear cada keyword de
     missing_keywords contra el texto del CV (sinónimos + traducción) antes de emitir el JSON.
     Tras el fix: backend 3/3 pasa (92, 92, 90).

### E2e completo final (todos los criterios OK, exit 0)

| vacante | tipo | base | banco | final | resultado |
|---|---|---|---|---|---|
| ai_rag_en | match | 45 | 90 | 92 | ✅ PASA |
| backend_py_en | match | 32 | 92 | 92 | ✅ PASA |
| senior_ai_5y | stretch | 35 | 35 | 35 | ✓ honesto-no |
| frontend_react | control | 35 | 25 | 20 | ✓ honesto-no |

**Archivos modificados (total):** `prompts/analyze.md`, `prompts/bank_selection.md`, `banco.py`,
`ai_analyzer.py`, `ui/diff_viewer.py`, `tests/e2e_filter_test.py`.

### Observaciones para una próxima iteración (fuera de alcance)

- La IA **inyecta placeholders** `[cuantifica: número]` en los bullets sugeridos cuando le falta
  una métrica (no vienen del banco). La regla 1.3 evita que penalicen el score, pero quedan visibles
  en el CV final; conviene resolverlos en el flujo de revisión.
- El `apply` de experiencias mapea las sugerencias por `index`, pero la IA a veces **reordena las
  experiencias** en su respuesta → los bullets pueden quedar bajo la empresa/fechas equivocadas.
  No afecta el score (el contenido sigue presente) pero sí la integridad del CV mostrado.

## Orden de ejecución

1. Fase 1 (prompt) → e2e completo → comparar.
2. Fase 2 (temperatura) → 3× `--quick` → e2e completo.
3. Fase 3 (diagnóstico C) con los datos de los runs anteriores.
4. Fase 4 (placeholders) cuando el usuario provea cifras.
5. Fase 5 commit.
