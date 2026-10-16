# Refactor — Datos personales en carpeta `data/`

**Fecha:** 2026-10-16 · **Rama:** `main`

Continuación de [REFACTOR_ESTRUCTURA_CVGEN.md](REFACTOR_ESTRUCTURA_CVGEN.md): los datos personales
que seguían sueltos en la raíz pasan a `data/`, con una sola ruta definida en el paquete.

Suite: **133 tests en verde** (igual que antes del cambio).

---

## Estructura nueva

```
app.py
config_plantilla.json   ← plantilla versionada, se queda en raíz
cvgen/
  __init__.py           ← define ROOT_DIR y DATA_DIR (crea data/ si no existe)
data/                   ← ignorado por git
  banco_personal.json   (+ .bak, lo genera save_banco junto al banco)
  config_personal.json
  .ai_config.json
logs/                   ← sin cambios
```

## Cambios

| Archivo | Antes | Después |
|---------|-------|---------|
| `cvgen/__init__.py` | solo docstring | `ROOT_DIR`, `DATA_DIR` + `os.makedirs(DATA_DIR, exist_ok=True)` |
| `cvgen/banco.py` | `_banco_path()` armaba la ruta a la raíz | `os.path.join(DATA_DIR, BANCO_FILENAME)` |
| `cvgen/ai_analyzer.py` | `_config_path()` a la raíz | `os.path.join(DATA_DIR, _CONFIG_FILE)` |
| `cvgen/helpers.py` | `default_cv_data()` usaba rutas **relativas al CWD** | `DATA_DIR/config_personal.json` y `ROOT_DIR/config_plantilla.json` |
| `app.py` | migración desde `config_personal.json` en raíz | `DATA_DIR/config_personal.json` |
| `cvgen/ui/tab_banco.py` | botón importar con `../../config_personal.json` | `DATA_DIR/config_personal.json` |
| `.gitignore` | ignoraba cada archivo personal por nombre | agrega `data/` (las entradas por nombre se conservan) |
| `README.md` | rutas en raíz | rutas en `data/` |
| `tests/e2e_filter_test.py` | `open("banco_personal.json")` | `open("data/banco_personal.json")` |

## Bug corregido de paso

`default_cv_data()` buscaba `config_personal.json` y `config_plantilla.json` relativo al
directorio de trabajo. Si la app se lanzaba desde otra carpeta (`streamlit run ruta/app.py`), no
los encontraba y arrancaba con datos vacíos. Ahora usa rutas absolutas desde `ROOT_DIR`/`DATA_DIR`.

## Migración

No hay migración automática. Los archivos existentes se movieron a mano a `data/` en esta
máquina. **En otra copia del proyecto** hay que mover `banco_personal.json`,
`config_personal.json` y `.ai_config.json` a `data/`. Si no se mueven, la app arranca con el
banco vacío y sin API keys guardadas.

## Fuera de alcance

- `config_plantilla.json` se queda en la raíz: es parte del repo, no un dato del usuario.
- `logs/` ya tenía su propia carpeta. Sigue igual.
