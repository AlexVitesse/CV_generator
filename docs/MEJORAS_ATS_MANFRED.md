# Mejoras ATS — Informe Manfred (ATS Killer)

Optimizaciones al generador de CV a partir de la evaluación externa de **Manfred "ATS Killer"**
sobre un CV generado por la herramienta.

## Contexto

| Iteración | Score | Hallazgos MEDIA | Warning gaps | Estado |
|-----------|-------|-----------------|--------------|--------|
| Informe 1 | **87/100** | 2 (educación, certificaciones) | Sí (2017–24) | Base |
| Informe 2 | **89/100** | **0** | **No** | Tras cambios |

El salto relevante no es el `+2`, sino que **desaparecieron las 2 MEDIA y el aviso de hueco laboral**:
todo lo restante quedó en severidad **BAJA** (pulido opcional).

> ⚠️ Manfred es un ATS basado en LLM, **no determinista y ruidoso**: alucina datos ("715 commits",
> "bug de CI" inexistentes), no detecta las anotaciones de hipervínculo del PDF, reporta una densidad
> de keywords imprecisa/cacheada (18.5% idéntica pese a cambiar el nº de palabras) y su score sube/baja
> entre iteraciones. No conviene perseguir cada hallazgo BAJA.

---

## Cambios implementados

### 1. Hipervínculos activos en el PDF — `pdf.py`
Antes LinkedIn/GitHub/email y las URLs de proyecto eran **texto plano**.
- Nuevo helper `link(url, display, kind)` + `_norm_url()` que envuelven en `<a href="...">` de ReportLab
  (con `mailto:` para email y `https://` implícito).
- Aplicado a la línea de contacto (LinkedIn, GitHub, email) y a las URLs de la sección Proyectos.
- `row2()` ahora acepta `lt_raw`/`rt_raw` para pasar markup ya escapado sin doble-escape.
- **Verificado**: el PDF generado contiene anotaciones `/Link` reales (5 en el CV del banco).

### 2. Viñeta estándar ATS-safe — `pdf.py`
- Viñeta cambiada de `·` / `●` a **guion `-`**.
- Motivo: los ATS tratan el guion como viñeta estándar (no como carácter decorativo) y renderiza
  fiable en Times-Roman sin depender de fuentes externas (DejaVu).
- Eliminado el bloque de registro de `DejaVuSans` e imports muertos (`os`, `pdfmetrics`, `TTFont`).

### 3. Sección dedicada de Certificaciones (feature nueva)
Antes las certs vivían mezcladas dentro de una línea de skills. Ahora son una **sección propia**.

Nuevo campo del modelo: `certifications: [{ id, text, credential_id }]`.

- **`credential_id` se guarda pero NO se imprime en el PDF** (decisión de diseño): los IDs de Oracle
  son hashes de 64 caracteres que ensucian el CV. Quedan disponibles para verificación, editables en la UI.

Archivos tocados:
| Archivo | Cambio |
|---------|--------|
| `validation.py` | `CertificationModel` (+ `credential_id`), `CVModel.certifications`, `_coerce_skills` reutilizado, normalización en `parse_cv`, `TranslationResponse.certifications` |
| `helpers.py` | `default_cv_data` (ids), `collect_widget_data` / `push_data_to_widgets` (keys `c_tx_` y `c_cid_`) |
| `ui/tab_manual.py` | Sección editable (añadir/borrar cert + campo ID que no se imprime) |
| `i18n.py` | Labels es/en: `pdf_certifications`, `certifications_header`, `certifications_caption`, `credential_id`, `credential_id_help`, `add_certification` |
| `translate.py` | Las certs se **preservan sin traducir** (nombres oficiales de credenciales) en la ruta LLM y en la de Google |
| `pdf.py` | Render de la sección `CERTIFICACIONES` entre Educación y Skills |

### 4. Cableado en el Banco Personal — `banco.py`
**Causa raíz del informe 2**: el CV probado se generó desde el **banco**, y el banco no tenía las
certificaciones cableadas → salía sin la sección y con la UNID vieja.

- `bank_to_active_cv()`: ahora ensambla `certifications` (activas por defecto, como educación).
- `merge_cv_to_bank()`: sincroniza las ediciones de certs (texto + `credential_id`) de vuelta al banco.
- `banco_personal.json`: se añadió el array `certifications` (5 certs con IDs), se quitaron las certs
  de la línea de skills, y se corrigió UNID. Backup previo en `banco_personal.json.bak2`.

### 5. Reglas anti-densidad de keywords — `prompts/`
La densidad (18.5%, único dato en rojo) es sobre-optimización.
- `prompts/summary.md`: regla 7 — no repetir tecnologías; mencionar solo el stack core (2-4).
- `prompts/analyze.md`: regla 8 (ANTI-SOBRE-OPTIMIZACIÓN, objetivo <12%) + aclaración de que las
  certs viven en su propia sección y no deben meterse en la línea de skills.

### 6. Datos de Eric — `config_personal.json` + banco
- Certs migradas de la línea de skills a la sección dedicada (con IDs en `credential_id`).
- **UNID**: quitado el poco profesional "(trunca)/(unfinished)" → "Programa no concluido" + materias
  relevantes (POO, Estructuras de Datos, Bases de Datos, Redes, SO, Ingeniería de Software).
- **Métricas**: NO se inventaron números. Solo se quitó el placeholder `[cuantifica: …]` del bullet
  de Dot Com dejándolo cualitativo. Respeta los guards anti-fabricación existentes.
- **Gap 2017–24**: omitido deliberadamente (trabajos no relacionados con desarrollo).

### 7. Skills agrupadas en subcategorías escaneables
Manfred (BAJA #1 y "jerarquización de IA"): la sección de skills era *"una lista excesivamente larga
y difícil de escanear"*. La mega-línea con tiers separados por `|` se dividió en **una línea por tier**.

- **Datos** (`config_personal.json` y `banco_personal.json`): cada segmento `Label: items` de las líneas
  activas quedó como un item de skill independiente → el PDF los renderiza como bullets separados
  (Dominio avanzado / intermedio / Familiaridad / Frontend / Languages / Soft skills).
- **Prompts** (`prompts/analyze.md`, `ai_analyzer.py`): la adaptación ahora devuelve `skills` como
  ARRAY con **una línea por tier**, no una sola línea larga con `|`.
- Se preservan los prefijos de tier → el parser `_parse_skill_tiers` y los guards anti-inflación
  (`helpers.py`) siguen funcionando por línea (verificado).

> ℹ️ Esto mejora la **escaneabilidad** (el hallazgo real de layout); la métrica de "densidad de keywords"
> de Manfred es aparte y poco fiable, por lo que puede no moverse.

---

## Verificación

- **92/92 tests** en verde (`pytest -q`).
- Flujo **banco → CV → PDF** validado: sección CERTIFICATIONS presente, 5 hipervínculos activos,
  0 `credential_id` filtrados al PDF, certs fuera de la línea de skills, "(unfinished)" eliminado,
  cabe en 1 página (94% de escala por el volumen de la sección de 5 certs).

---

## ⚠️ Aviso importante: autoguardado del banco

Durante el trabajo, la app Streamlit (si está abierta) **autoguardó `banco_personal.json` con su estado
en memoria, sobreescribiendo ediciones a nivel de archivo** (se perdieron temporalmente las certs y la
UNID). Los cambios de **código son permanentes**; los cambios de **datos del banco** deben hacerse con la
app cerrada, o volver a aplicarse si la app los clobbering. Se re-aplicaron atómicamente y se verificaron
con read-back. Backups: `banco_personal.json.bak2`.

## Verificación final (flujo banco → CV → PDF)

- 5 certificaciones ensambladas, sección CERTIFICATIONS en el PDF.
- 6 líneas de skills agrupadas y escaneables.
- UNID con coursework, "(unfinished)" eliminado.
- 5 hipervínculos activos, 0 `credential_id` filtrados, 1 página, **92/92 tests**.

## Pendiente / Siguientes pasos

1. **Regenerar desde el banco y re-testear** en Manfred: deberían caer "Estructuración de
   certificaciones", "Detalle en formación técnica (UNID)" y "Optimización de la sección de habilidades".
2. **Validar las materias de UNID**: las propuestas son las típicas de Ing. en Sistemas; Eric debe
   confirmarlas o ajustarlas (no deben inventarse).
