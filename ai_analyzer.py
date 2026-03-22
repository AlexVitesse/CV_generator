"""
Módulo de análisis de vacantes con IA.
Usa Ollama Cloud API nativa (https://ollama.com/api/chat).
"""

import json
import logging
import os
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

logger = logging.getLogger("ai_analyzer")
logger.setLevel(logging.DEBUG)

_fh = logging.FileHandler(
    os.path.join(_LOG_DIR, "ai_analyzer.log"), encoding="utf-8"
)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_fh)

try:
    import httpx
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════

OLLAMA_CLOUD_URL = "https://ollama.com/api/chat"
DEFAULT_MODEL = "minimax-m2.7:cloud"
_CONFIG_FILE = ".ai_config.json"


def _config_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), _CONFIG_FILE)


def load_ai_config() -> dict:
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_ai_config(api_key: str, model: str):
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump({"api_key": api_key, "model": model}, f)


# ═══════════════════════════════════════════════════════════════
# PROMPT Y ANÁLISIS
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """\
Eres un experto en reclutamiento, sistemas ATS y redacción de CVs formato Harvard.
Tu trabajo es adaptar el CV para maximizar el match ATS, siendo HONESTO y estratégico.

═══ REGLAS ANTI-OVERFITTING (PRIORIDAD MÁXIMA) ═══

1. AÑOS DE EXPERIENCIA — Calcula los años REALES a partir del campo "dates" de las experiencias.
   - Si la experiencia empieza en "Mayo 2024", son ~1-2 años, NO "4+ años".
   - NUNCA inventes años de experiencia. Usa frases como "con experiencia en" en vez de "X años de experiencia".
   - Si la vacante pide 4+ años y el candidato tiene 1, eso va a missing_keywords como gap real.

2. SCORE HONESTO — El match_score debe reflejar la REALIDAD, no lo que el candidato quiere oír.
   - Si faltan requisitos hard (años, tecnologías core), el score NO puede superar 60.
   - Si hay gaps estructurales (SDK authoring sin experiencia, años insuficientes), viable = false.
   - Un candidato con 3 de 10 requisitos cubiertos NO es 68/100. Es 30-40/100.

3. NO KEYWORD STUFFING — Solo agrega a "Familiaridad" tecnologías que el candidato \
razonablemente conoce por proximidad con su stack:
   - OK: FastAPI → Flask, PostgreSQL → MongoDB, Oracle Cloud → AWS (mismo ecosistema)
   - MAL: No tiene nada de observability → agregar Datadog. No usó Griptape → agregar Griptape.
   - REGLA: Si el candidato nunca mencionó ni usó una tecnología ni algo similar, NO la agregues.

4. NO COPIAR FRASES DEL JD — No pegues frases textuales del JD en bullets si no hay evidencia:
   - MAL: "optimizing token usage patterns in AI workloads" (si nunca optimizó tokens)
   - MAL: "fault-tolerant components for continuous operation" (si nunca diseñó fault tolerance)
   - BIEN: Reformular lo que SÍ hizo usando vocabulario relevante al JD sin inventar.

═══ ESTRATEGIA DE ADAPTACIÓN ═══

1. KEYWORDS — Reformula bullets existentes usando vocabulario del JD:
   - Si el JD dice "scalable backend systems" y el candidato tiene "APIs REST en FastAPI", \
reescribe: "Construyó backend systems escalables con FastAPI, procesando 1,200+ solicitudes diarias..."
   - Solo reformula lo que REALMENTE hizo. No agregues capacidades que no tiene.

2. REORDENAMIENTO — Los bullets más relevantes al JD van PRIMERO.

═══ REGLAS DE FORMATO ═══

Bullets de experiencia:
- Tercera persona pasada SIEMPRE: "Diseñó", "Desarrolló", "Implementó", "Construyó", "Lideró".
- NUNCA primera persona.
- Cada bullet DEBE empezar con verbo. NO pongas mayúsculas en medio de un bullet.
- Cada bullet DEBE tener métrica cuantitativa.
- CONSERVA TODOS los bullets — devuelve el MISMO NÚMERO que recibiste.

Summary:
- EXACTAMENTE 2 líneas, no más.
- Línea 1: Título de cargo + stack principal. SIN inventar años de experiencia.
- Línea 2: Fortaleza diferenciadora real del candidato.

Skills — REGLA CRÍTICA:
- CONSERVA TODAS las skills y certificaciones existentes. NUNCA elimines ninguna.
- Certificaciones (AWS, OCI, etc.) SIEMPRE deben aparecer.
- Formato: "Dominio avanzado: ... | Dominio intermedio: ... | Familiaridad: ..."
- REORDENA poniendo primero las skills relevantes al JD, sin eliminar las demás.
- Solo agrega a Familiaridad tecnologías razonablemente cercanas al stack del candidato.

missing_keywords:
- Lista TODOS los requisitos del JD que el candidato genuinamente no cumple.
- Incluye años de experiencia si no los tiene.
- Sé brutalmente honesto — el candidato necesita saber si vale la pena aplicar.

Responde SOLO con JSON válido, sin markdown ni texto adicional."""

USER_PROMPT_TEMPLATE = """\
VACANTE:
{vacancy_text}

CV DEL CANDIDATO (JSON):
{cv_json}

Analiza la vacante contra el CV y responde con este JSON exacto:
{{
  "match_score": <0-100>,
  "viable": <true/false>,
  "matching_keywords": ["keyword1", "keyword2"],
  "missing_keywords": ["keyword1", "keyword2"],
  "suggestions": {{
    "summary": "<resumen adaptado (2 líneas máx, con título de cargo de la vacante) o null si no necesita cambio>",
    "experiences": [
      {{"index": 0, "title": "<título del cargo adaptado al idioma y vacante>", "bullets": "<bullets en 3ra persona con métricas, uno por línea>"}}
    ],
    "projects": [
      {{"index": 0, "description": "<descripción adaptada con métrica>"}}
    ],
    "skills": ["Dominio avanzado: skill1, skill2 | Dominio intermedio: skill3 | Familiaridad: skill4 (DEBE ser un ARRAY de strings, NUNCA un string suelto)"]
  }},
  "reasoning": "<explicación breve de tu análisis>"
}}"""


def build_analysis_prompt(cv_data: dict, vacancy_text: str) -> str:
    cv_clean = {k: v for k, v in cv_data.items() if k != "id"}
    cv_json = json.dumps(cv_clean, ensure_ascii=False, indent=2)
    return USER_PROMPT_TEMPLATE.format(vacancy_text=vacancy_text, cv_json=cv_json)


def analyze_vacancy(cv_data: dict, vacancy_text: str, api_key: str, model: str) -> dict:
    """Envía CV + vacante a Ollama Cloud y retorna el análisis parseado."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Ollama Cloud")

    user_prompt = build_analysis_prompt(cv_data, vacancy_text)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Log request
    logger.info("=" * 60)
    logger.info("NUEVA SOLICITUD DE ANÁLISIS — %s", ts)
    logger.info("Modelo: %s", model)
    logger.info("Vacante (primeros 500 chars): %s", vacancy_text[:500])
    logger.info("CV keys enviadas: %s", list(cv_data.keys()))

    # Guardar request completo
    req_file = os.path.join(_LOG_DIR, f"request_{ts}.json")
    with open(req_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "model": model,
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": user_prompt,
        }, f, ensure_ascii=False, indent=2)
    logger.info("Request guardado en: %s", req_file)

    response = httpx.post(
        OLLAMA_CLOUD_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        },
        timeout=120.0,
    )
    response.raise_for_status()

    data = response.json()
    raw = data["message"]["content"].strip()

    # Log raw response
    logger.info("Response HTTP status: %s", response.status_code)
    logger.info("Response raw (primeros 500 chars): %s", raw[:500])

    # Guardar response completo
    resp_file = os.path.join(_LOG_DIR, f"response_{ts}.json")
    with open(resp_file, "w", encoding="utf-8") as f:
        json.dump({"timestamp": ts, "raw_response": raw}, f, ensure_ascii=False, indent=2)
    logger.info("Response guardado en: %s", resp_file)

    # Limpiar posible markdown wrapping
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)

    parsed = json.loads(raw)

    # Log resultado parseado
    logger.info("Match score: %s | Viable: %s", parsed.get("match_score"), parsed.get("viable"))
    logger.info("Matching KWs: %s", parsed.get("matching_keywords"))
    logger.info("Missing KWs: %s", parsed.get("missing_keywords"))
    logger.info("Tiene sugerencias: summary=%s, experiences=%s, projects=%s, skills=%s",
                bool(parsed.get("suggestions", {}).get("summary")),
                len(parsed.get("suggestions", {}).get("experiences", [])),
                len(parsed.get("suggestions", {}).get("projects", [])),
                len(parsed.get("suggestions", {}).get("skills", [])))
    logger.info("=" * 60)

    return parsed
