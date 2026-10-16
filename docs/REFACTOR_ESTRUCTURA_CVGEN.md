# Refactor — Estructura del proyecto en paquete `cvgen/`

**Fecha:** 2026-10-16 · **Rama:** `main`

Reorganización sin cambios de lógica: los módulos sueltos en la raíz pasan a un paquete
`cvgen/`, se elimina el shim `ui_components.py` y se limpia la raíz de archivos sueltos.

Suite: **133 tests en verde** (igual que antes del cambio). `app.py` renderiza los 5 tabs
sin excepciones (verificado con `streamlit.testing.v1.AppTest`).

---

## Estructura nueva

```
app.py               ← entrada (streamlit run app.py), se queda en raíz
cvgen/
  __init__.py
  ai_analyzer.py  banco.py  helpers.py  i18n.py  llm_client.py
  metrics_guard.py  pdf.py  session_keys.py  translate.py  validation.py
  ui/                ← antes ui/ en raíz
  prompts/           ← antes prompts/ en raíz
tests/  docs/
banco_personal.json  config_personal.json  .ai_config.json  logs/   ← datos, siguen en raíz
_archivo/            ← archivos sueltos (ignorado por git)
```

## Cambios

| Área | Antes | Después |
|------|-------|---------|
| Imports | `from helpers import …`, `import session_keys as sk` | `from cvgen.helpers import …`, `from cvgen import session_keys as sk` (app, paquete y tests) |
| Shim | `app.py` → `ui_components.py` → `ui/` | `app.py` → `cvgen.ui`; `ui_components.py` eliminado |
| Rutas de datos | `dirname(__file__)` = raíz | `dirname(dirname(__file__))` = raíz, en `ai_analyzer.py` (`logs/`, `.ai_config.json`), `llm_client.py` (`logs/`), `banco.py` (`banco_personal.json`), `ui/tab_banco.py` (`config_personal.json`, un `..` más) |
| Prompts | `prompts/` en raíz | `cvgen/prompts/`, junto a `ai_analyzer.py` — `_load_prompt` no cambió |

Los datos personales **no se movieron**: siguen en la raíz y en `.gitignore`.

## Limpieza fuera de git

- Eliminados `banco_personal.json.bak2` … `.bak5` (respaldos manuales). Se conserva `.bak`,
  que `banco.py` usa para recuperar un banco corrupto.
- Movidos a `_archivo/` (agregado a `.gitignore`): transcripción `2026-06-18-…txt`,
  `test_cv.pdf`, `banco_habilidades_alexvitesse.html`.

## Notas

- Los planes previos en `docs/` mencionan rutas viejas (`ui_components.py`, `llm_client.py` en
  raíz); se dejan como registro histórico.
- `tests/e2e_filter_test.py` solo se verificó que compile (consume tokens de LLM).
