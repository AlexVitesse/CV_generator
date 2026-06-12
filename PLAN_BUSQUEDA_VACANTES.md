# Evolución: de Generador de CV a Buscador + Auto-postulación de Vacantes

> Documento de análisis (solo investigación, sin implementación). Recoge qué haría falta para
> que el CV Generator evolucione hacia búsqueda y postulación automática de vacantes, los riesgos
> a considerar, y proyectos open source similares como referencia.

---

## 1. Punto de partida (lo que ya tienes)

La app actual ya resuelve la **mitad difícil** del problema. Lo que en los proyectos de
auto-apply se construye desde cero, aquí ya existe:

| Pieza ya existente | Archivo | Reutilizable para vacantes |
|---|---|---|
| Datos estructurados del CV (Pydantic) | `validation.py` | Sí — base del matching |
| Banco de habilidades | `banco.py` | Sí — selección dinámica por vacante |
| Análisis IA anti-overfitting | `ai_analyzer.py` | Sí — invertible a "adapta CV a vacante" |
| Summary / Cover letter | `ai_analyzer.py` / UI | Sí — cover letter por vacante |
| Traducción ES/EN | `translate.py` | Sí |
| PDF de 1 página | `pdf.py` | Sí — CV adaptado por vacante |
| Persistencia SQLite | `db.py` | Sí — base del tracking |

---

## 2. Las 3 capas nuevas a añadir

### Capa 1 — Búsqueda / scraping de vacantes (entrada de datos)
- Fuentes: LinkedIn, Indeed, InfoJobs, OCC (México), Glassdoor, o portales tipo
  Greenhouse / Workday.
- Dos enfoques:
  - **APIs oficiales**: pocas, caras, limitadas.
  - **Scraping con Selenium / Playwright**: lo que usan casi todos los proyectos open
    source; frágil y contra los Términos de Servicio.
- Salida: lista normalizada `{título, empresa, descripción, skills, url}`.

### Capa 2 — Matching CV ↔ vacante (donde tu IA ya brilla)
- Reutiliza casi todo `ai_analyzer.py`: por cada vacante, **scoring de compatibilidad ATS**
  y **tailoring** del CV (reordenar, enfatizar, inyectar keywords).
- Es literalmente la feature de análisis actual pero invertida: en vez de "evalúa mi CV",
  es "adapta mi CV a esta vacante".
- El banco de habilidades permite seleccionar dinámicamente qué experiencias destacar.

### Capa 3 — Postulación + tracking (la salida, la parte arriesgada)
- Automatizar el "Easy Apply" / rellenar formularios con navegador headless.
- Dashboard de seguimiento (a qué se postuló, estado, respuestas): SQLite (ya disponible),
  Google Sheets o Airtable.

---

## 3. Cambios de arquitectura

- **Streamlit deja de ser ideal** para scraping/auto-apply (procesos largos + navegador).
  Conviene un **worker en background** (cron / GitHub Actions / Celery) separado de la UI.
- Se pasa de una app *stateless de un CV* a un **pipeline con cola de vacantes y estado**.

---

## 4. Riesgos a considerar antes de invertir tiempo

- **Legal / ToS**: LinkedIn, Indeed, etc. **prohíben explícitamente** el scraping y la
  auto-postulación. Cuentas baneadas son comunes. La mayoría de estos repos viven en zona gris.
- **Fragilidad**: los scrapers se rompen cuando el sitio cambia el HTML → mantenimiento constante.
- **Calidad vs. cantidad**: postular a 100 empleos/hora baja la tasa de respuesta y puede quemar
  tu reputación. El valor real está en el **matching + tailoring**, no en el spam.

> **Recomendación**: el camino de mayor valor y menor riesgo es
> **scraping de vacantes + scoring/tailoring con IA + cover letter por vacante**,
> dejando la postulación final como *asistida* (un click humano) en vez de 100% automática.

---

## 5. Proyectos similares en GitHub (referencia)

### Los más parecidos arquitectónicamente (Python + IA + PDF)
- **[anandanair/job-scraper](https://github.com/anandanair/job-scraper)** — El más alineado:
  scraping + parsing de CV + **scoring vacante↔CV** + **PDF ATS-friendly** desde datos
  estructurados, corriendo en **GitHub Actions**. Buen modelo de la capa "worker en background".
- **[imon333/Job-apply-AI-agent](https://github.com/imon333/Job-apply-AI-agent)** — Pipeline
  end-to-end: scrapea LinkedIn/Indeed/StepStone, genera CV + cover letter custom, auto-aplica y
  trackea en Google Sheets/Airtable con alertas por email. Útil para ver el flujo completo.
- **[gopiashokan/AI-Resume-Analyzer-and-LinkedIn-Scraper](https://github.com/gopiashokan/AI-Resume-Analyzer-and-LinkedIn-Scraper-using-Generative-AI)**
  — Básicamente tu app + scraping de LinkedIn con Selenium. El más cercano a la feature de
  análisis actual.

### Auto-apply completos (la capa 3, con más riesgo)
- **[AIHawk / linkedIn_auto_jobs_applier_with_AI](https://github.com/jomacs/linkedIn_auto_jobs_applier_with_AI)**
  — El más famoso del nicho. Auto-postulación personalizada con IA en LinkedIn.
- **[Pickle-Pixel/ApplyPilot](https://github.com/Pickle-Pixel/ApplyPilot)** — Scrapea 5 portales
  (Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs) + Workday; reescribe el CV por vacante.
  Buena referencia de la lógica de tailoring.
- **[GodsScion/Auto_job_applier_linkedIn](https://github.com/GodsScion/Auto_job_applier_linkedIn)**
  — Scraping + relleno de formularios + customización de CV.
- **[wodsuz/EasyApplyJobsBot](https://github.com/wodsuz/EasyApplyJobsBot)** — Multi-portal
  (LinkedIn, Glassdoor, Greenhouse, Monster…) con recomendaciones IA para el CV.

### GitHub Topics para descubrir más
- [`job-application-bot`](https://github.com/topics/job-application-bot)
- [`job-search-automation`](https://github.com/topics/job-search-automation)
- [`ai-job-search`](https://github.com/topics/ai-job-search)

---

## 6. Posible siguiente paso (no ejecutado)

Fase 1 sugerida, de menor riesgo: **scraping de vacantes + scoring** reutilizando
`ai_analyzer.py`, sin auto-postulación. Alternativamente, entrar a `anandanair/job-scraper`
y documentar su arquitectura para copiar el patrón.
