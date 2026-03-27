"""
Módulo de análisis de vacantes y chat asesor con IA.
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

1. AÑOS DE EXPERIENCIA — Calcula los años REALES usando la FECHA ACTUAL proporcionada y el campo "dates".
   - Resta la fecha de inicio de cada experiencia a la FECHA ACTUAL para obtener los años reales.
   - Ejemplo: Si "dates" dice "Mayo 2024" y la fecha actual es "March 2026", son ~1 año 10 meses (~2 años).
   - NUNCA inventes años de experiencia. Usa frases como "con experiencia en" en vez de "X años de experiencia".
   - Si la vacante pide 4+ años y el candidato tiene 2, eso va a missing_keywords como gap real.

2. SCORE HONESTO — El match_score debe reflejar la REALIDAD, no lo que el candidato quiere oír.
   - Si faltan requisitos hard (años, tecnologías core), el score NO puede superar 60.
   - Si falta CUALQUIER requisito marcado como "must", "required" o "obligatorio" → viable = false.
   - Si hay gaps estructurales (SDK authoring sin experiencia, años insuficientes), viable = false.
   - Un candidato con 3 de 10 requisitos cubiertos NO es 68/100. Es 30-40/100.

3. INFERENCIA TÉCNICA INTELIGENTE — Infiere dependencias IMPLÍCITAS pero NUNCA inventes:
   A) DEPENDENCIAS OBLIGATORIAS — Si usa X, SEGURO usa Y. Agregar LIMPIO a Working knowledge:
      - FastAPI → Pydantic, SQLAlchemy (si usa PostgreSQL)
      - RunPod / despliegue de contenedores → Docker
      - CI/CD + GitHub → Git
   B) EQUIVALENCIAS CLOUD — Si tiene experiencia en un cloud, agregar otros a Exposure to:
      - Oracle Cloud + AWS → GCP
   C) PROHIBIDO — Tecnologías sin conexión con el stack del candidato:
      - MAL: Agregar Node.js, Java, React si nunca los menciona ni usa algo similar.
      - BIEN: Reordenar las skills existentes poniendo primero las relevantes al JD.

   ██ REGLA CRÍTICA DE FORMATO PARA INFERENCIAS ██
   Las tecnologías inferidas se agregan LIMPIAS, sin paréntesis ni explicaciones.
   - MAL: "SQLAlchemy (implícito por uso de ORMs con PostgreSQL)"
   - MAL: "Docker (implícito en RunPod)"
   - MAL: "GCP (experiencia cloud equivalente en OCI/AWS, transferible a GCP)"
   - BIEN: "SQLAlchemy"
   - BIEN: "Docker"
   - BIEN: "GCP"
   Las justificaciones van SOLO en el campo "reasoning", NUNCA en skills ni bullets.

4. NO FABRICAR HECHOS — NUNCA cambies datos reales del CV por otros:
   - MAL: Cambiar "RunPod" → "AWS" en un bullet (el candidato desplegó en RunPod, no en AWS).
   - MAL: Cambiar "Ionic" → "React" porque la vacante pide React.
   - BIEN: Mantener los hechos reales y reformular el CONTEXTO usando vocabulario del JD.
   - BIEN: Si el candidato desplegó contenedores en RunPod, PUEDES mencionar Docker en ese bullet \
porque es un hecho implícito (RunPod usa Docker).

5. NO COPIAR FRASES DEL JD — No pegues frases textuales del JD en bullets si no hay evidencia:
   - MAL: "optimizing token usage patterns in AI workloads" (si nunca optimizó tokens)
   - MAL: "fault-tolerant components for continuous operation" (si nunca diseñó fault tolerance)
   - BIEN: Reformular lo que SÍ hizo usando vocabulario relevante al JD sin inventar.

═══ ESTRATEGIA DE ADAPTACIÓN ═══

1. ESPEJO DE VOCABULARIO (MÁXIMO IMPACTO ATS) — Usa EXACTAMENTE la terminología del JD:
   - Si el JD dice "agentes conversacionales" y el CV dice "asistentes virtuales" → reescribe como "agentes conversacionales". \
Es el MISMO concepto, solo cambia la etiqueta. Esto NO es mentir, es hablar el idioma del reclutador.
   - Si el JD dice "microservices" y el candidato tiene "servicios desplegados por separado" → usa "microservices".
   - Si el JD dice "scalable backend systems" y el candidato tiene "APIs REST en FastAPI" → \
reescribe: "Construyó backend systems escalables con FastAPI, procesando 1,200+ solicitudes diarias..."
   - APLICA ESTO EN TODOS LOS CAMPOS: summary, bullets, proyectos. Cada keyword del JD que tenga \
equivalente real en el CV DEBE aparecer con la MISMA PALABRA que usa el JD.
   - Solo reformula lo que REALMENTE hizo. No agregues capacidades que no tiene.

2. DETECCIÓN DE KEYWORDS CRÍTICAS POR FRECUENCIA — Analiza cuántas veces aparece cada tecnología en el JD:
   - Si una tecnología aparece 3+ veces en el JD → es CRÍTICA para el ATS. El reclutador la marcó como prioritaria.
   - Si esa tecnología crítica NO está en el CV → ponla PRIMERO en missing_keywords y en el reasoning \
explica: "⚠️ [Tecnología] aparece N veces en la vacante y no está en el CV — alto riesgo de filtro ATS."
   - Si el candidato tiene experiencia EQUIVALENTE (ej: Oracle Cloud cuando piden Azure), sugiere en reasoning \
una acción concreta: "El candidato podría crear una demo con [tecnología] free tier para poder mencionarla con honestidad."
   - NUNCA agregues la tecnología al CV si el candidato no la tiene. Solo señala el gap y sugiere cómo cerrarlo.

3. REORDENAMIENTO — Los bullets más relevantes al JD van PRIMERO.

═══ REGLAS DE FORMATO ═══

IDIOMA — REGLA FUNDAMENTAL:
- Detecta el idioma de la VACANTE (no del CV).
- TODAS las sugerencias (summary, bullets, skills, titles) DEBEN estar en el idioma de la VACANTE.
- Si la vacante está en inglés: TODO en inglés, incluso si el CV original está en español.
- Si la vacante está en español: TODO en español.
- CERO mezcla de idiomas. Revisa cada campo — UNA palabra en el idioma incorrecto es un error.
- Skills en inglés: "Core skills: ... | Working knowledge: ... | Exposure to: ..."
- Skills en español: "Dominio avanzado: ... | Dominio intermedio: ... | Familiaridad: ..."

██ REGLA ANTI-PARÉNTESIS (PRIORIDAD MÁXIMA) ██
- NUNCA pongas paréntesis explicativos/justificativos en NINGÚN campo del CV (summary, bullets, skills).
- MAL en bullet: "implementing CI/CD and automated monitoring (Docker implicit in RunPod)"
- BIEN en bullet: "implementing CI/CD, Docker containers and automated monitoring"
- MAL en skills: "Docker (implícito en RunPod)"
- BIEN en skills: "Docker"
- Los paréntesis con CONTENIDO TÉCNICO sí están permitidos: "ChromaDB + BM25 (EnsembleRetriever)"
- Las explicaciones y justificaciones van SOLO en el campo "reasoning".

Bullets de experiencia:
- Tercera persona pasada SIEMPRE: "Diseñó"/"Designed", "Desarrolló"/"Developed", etc.
- NUNCA primera persona.
- Cada bullet DEBE empezar con verbo. NO pongas mayúsculas en medio de un bullet.
- Cada bullet DEBE tener métrica cuantitativa.
- CONSERVA TODOS los bullets — devuelve el MISMO NÚMERO que recibiste.
- Si agregas una tecnología inferida a un bullet, intégrala naturalmente en la frase.

Summary:
- EXACTAMENTE 2 líneas separadas por un salto de línea (\n).
- Línea 1: Título de cargo + stack principal. SIN inventar años de experiencia.
- Línea 2: Fortaleza diferenciadora real del candidato.
- VERIFICA que haya un espacio entre cada palabra. NUNCA pegues palabras: \
"Software EngineerBackend" es INCORRECTO → "Software Engineer — Backend" es CORRECTO.

Skills — REGLA CRÍTICA:
- CONSERVA TODAS las skills y certificaciones existentes. NUNCA elimines ninguna.
- Certificaciones (AWS, OCI, etc.) SIEMPRE deben aparecer.
- Labels según idioma del CV:
  - Español: "Dominio avanzado: ... | Dominio intermedio: ... | Familiaridad: ..."
  - English: "Core skills: ... | Working knowledge: ... | Exposure to: ..."
- Usa SIEMPRE "AI/ML" (nunca "IA/ML" en CV en inglés).
- REORDENA poniendo primero las skills relevantes al JD, sin eliminar las demás.
- PUEDES agregar dependencias implícitas (ver regla 3A): Pydantic, SQLAlchemy, Docker, etc. si se infieren del stack.
- PUEDES agregar equivalencias cloud (ver regla 3B) a Familiaridad/Exposure to.
- NUNCA agregues tecnologías sin conexión alguna con el stack del candidato (ver regla 3C).

missing_keywords:
- Lista TODOS los requisitos del JD que el candidato genuinamente no cumple.
- Incluye años de experiencia si no los tiene.
- Sé brutalmente honesto — el candidato necesita saber si vale la pena aplicar.

═══ FORMATO DE RESPUESTA ═══
- Responde SOLO con JSON válido, sin markdown ni texto adicional.
- El campo "reasoning" DEBE estar 100% en español. NUNCA mezcles otros idiomas.
- NO uses caracteres de otros alfabetos (chino, japonés, etc.) en ningún campo."""

USER_PROMPT_TEMPLATE = """\
FECHA ACTUAL: {current_date}

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
    current_date = datetime.now().strftime("%B %Y")
    return USER_PROMPT_TEMPLATE.format(
        vacancy_text=vacancy_text, cv_json=cv_json, current_date=current_date
    )


def analyze_vacancy(cv_data: dict, vacancy_text: str, api_key: str, model: str, extra_context: str = "") -> dict:
    """Envía CV + vacante a Ollama Cloud y retorna el análisis parseado."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Ollama Cloud")

    user_prompt = build_analysis_prompt(cv_data, vacancy_text)
    if extra_context:
        user_prompt += (
            "\n\nCONTEXTO ADICIONAL DEL CANDIDATO:\n"
            f"{extra_context}\n"
            "IMPORTANTE: El candidato confirma tener estas habilidades/experiencias adicionales. "
            "Incorpóralas en tus sugerencias manteniendo las reglas anti-overfitting."
        )
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


# ═══════════════════════════════════════════════════════════════
# CHAT ASESOR DE CV
# ═══════════════════════════════════════════════════════════════

CHAT_SYSTEM_PROMPT = """\
Eres un asesor de CV experto en formato Harvard, ATS y reclutamiento tech.
Tu rol es ser un mentor honesto que ayuda al candidato a mejorar su CV.

CONTEXTO: El candidato te compartirá su CV (en JSON) y opcionalmente una vacante.
Puedes recibir preguntas, experiencias no documentadas, o pedidos de mejora.

REGLAS:
1. Responde en el MISMO IDIOMA que el usuario usa en su mensaje.
2. Sé honesto — no infles experiencia ni inventes años.
3. Cuando sugieras texto para el CV, sé MUY ESPECÍFICO:
   - Indica EXACTAMENTE dónde va: "Agregar este bullet a Experiencia #0", "Mover X de Familiaridad a Dominio intermedio en Skills".
   - Escribe el texto exacto entre comillas o en un bloque.
   - Bullets SIEMPRE en tercera persona pasada con métrica: "Configuró...", "Implementó...".
4. Si el usuario dice que tiene experiencia con algo, ayúdalo a redactar un bullet con métrica.
   Pregunta detalles si faltan: "¿En qué contexto usaste Docker? ¿Proyecto personal o laboral? ¿Qué resultado obtuviste?"
5. Si hay vacante cargada, evalúa si la experiencia mencionada ayuda al match.
6. NO generes JSON — responde en lenguaje natural conversacional.
7. Mantén respuestas concisas (máx 200 palabras) a menos que el usuario pida detalle."""


SUMMARY_SYSTEM_PROMPT = """\
Eres un experto en reclutamiento y redacción de CVs.
Tu trabajo es generar un resumen profesional (Summary/Elevator Pitch) de 2-3 oraciones \
que el candidato pueda copiar y pegar directamente en LinkedIn, portales de empleo o emails.

REGLAS:
1. IDIOMA — Escribe en el idioma indicado por el usuario ({lang}).
2. Usa tercera persona implícita o primera persona profesional según el estándar del idioma.
3. Menciona: rol objetivo, stack/especialidad principal, logro destacado.
4. Si hay vacante, adapta el tono y keywords a esa vacante.
5. NO inventes experiencia ni años que no existan en el CV.
6. Máximo 60 palabras. Directo, sin fluff."""

COVER_LETTER_SYSTEM_PROMPT = """\
Eres un experto en reclutamiento y redacción de cartas de presentación.
Tu trabajo es generar una Cover Letter profesional, concisa y personalizada.

REGLAS:
1. IDIOMA — Escribe en el idioma indicado por el usuario ({lang}).
2. ESTRUCTURA:
   - Saludo dirigido a la empresa (usa el nombre proporcionado).
   - Párrafo 1: Por qué te interesa el rol y la empresa (2-3 oraciones).
   - Párrafo 2: Tus fortalezas relevantes con evidencia concreta del CV (3-4 oraciones).
   - Párrafo 3: Cierre con call-to-action (1-2 oraciones).
3. NO inventes experiencia. Usa SOLO datos reales del CV.
4. Tono: profesional pero cercano, sin ser genérico.
5. Máximo 250 palabras.
6. NO incluyas encabezados de carta formal (fecha, dirección). Solo el cuerpo."""


def generate_text(
    cv_data: dict,
    api_key: str,
    model: str,
    system_prompt: str,
    user_instruction: str,
    vacancy_text: str = "",
) -> str:
    """Genera texto libre (summary, cover letter, etc.) usando el LLM."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Ollama Cloud")

    context_msg = build_chat_context_message(cv_data, vacancy_text)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{context_msg}\n\n{user_instruction}"},
    ]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("=" * 60)
    logger.info("GENERATE TEXT — %s", ts)
    logger.info("Modelo: %s", model)

    response = httpx.post(
        OLLAMA_CLOUD_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "stream": False,
        },
        timeout=90.0,
    )
    response.raise_for_status()

    data = response.json()
    reply = data["message"]["content"].strip()

    logger.info("Generate text response (primeros 300 chars): %s", reply[:300])
    logger.info("=" * 60)

    return reply


REFINE_CHAT_SYSTEM_PROMPT = """\
Eres un asesor experto en CVs y ATS que ayuda a refinar el análisis de una vacante.

CONTEXTO: El candidato ya analizó su CV contra una vacante y obtuvo un resultado inicial.
Ahora quiere contarte experiencias, habilidades o proyectos que NO están en su CV para mejorar las sugerencias.

REGLAS:
1. Responde en el MISMO IDIOMA que el usuario usa en su mensaje.
2. Cuando el usuario mencione experiencia con una tecnología, pregunta detalles:
   - ¿Fue en contexto laboral o personal? ¿Cuánto tiempo? ¿Qué resultado obtuvo?
3. Evalúa si lo mencionado realmente ayuda al match con la vacante.
4. Sé honesto — si la experiencia es superficial, dilo. No infles.
5. Al final de cada respuesta, resume brevemente qué se podría agregar al CV.
6. Mantén respuestas concisas (máx 200 palabras).
7. NO generes JSON — responde en lenguaje natural conversacional."""


def build_chat_context_message(cv_data: dict, vacancy_text: str = "") -> str:
    """Construye el mensaje de contexto con CV y vacante opcional."""
    cv_clean = {k: v for k, v in cv_data.items() if k != "id"}
    cv_json = json.dumps(cv_clean, ensure_ascii=False, indent=2)
    current_date = datetime.now().strftime("%B %Y")
    parts = [f"FECHA ACTUAL: {current_date}\n\nCV DEL CANDIDATO:\n{cv_json}"]
    if vacancy_text and vacancy_text.strip():
        parts.append(f"\nVACANTE CARGADA:\n{vacancy_text.strip()}")
    return "\n".join(parts)


def chat_with_advisor(
    cv_data: dict,
    chat_history: list,
    api_key: str,
    model: str,
    vacancy_text: str = "",
    system_prompt_override: str = "",
    analysis_context: str = "",
) -> str:
    """Envía historial de chat a Ollama Cloud y retorna respuesta en texto."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Ollama Cloud")

    context_msg = build_chat_context_message(cv_data, vacancy_text)
    if analysis_context:
        context_msg += f"\n\nRESULTADO DEL ANÁLISIS PREVIO:\n{analysis_context}"

    sys_prompt = system_prompt_override or CHAT_SYSTEM_PROMPT

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": context_msg},
        {"role": "assistant", "content": "Entendido. Tengo tu CV cargado. ¿En qué puedo ayudarte?"},
    ]
    messages.extend(chat_history)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("=" * 60)
    logger.info("CHAT ASESOR — %s", ts)
    logger.info("Modelo: %s | Mensajes: %d", model, len(messages))

    response = httpx.post(
        OLLAMA_CLOUD_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "stream": False,
        },
        timeout=120.0,
    )
    response.raise_for_status()

    data = response.json()
    reply = data["message"]["content"].strip()

    logger.info("Chat response (primeros 300 chars): %s", reply[:300])
    logger.info("=" * 60)

    return reply


# ═══════════════════════════════════════════════════════════════
# EXTRACCIÓN DE PATCH DESDE SUGERENCIA DEL CHAT
# ═══════════════════════════════════════════════════════════════

EXTRACT_PATCH_PROMPT = """\
A partir del mensaje del asesor de CV, extrae UNA acción concreta para aplicar al CV.

Responde SOLO con JSON válido, sin markdown:
{{
  "field": "experience_bullet" | "summary" | "skill_line" | "project_description" | "project_new" | "experience_title",
  "target_index": <índice del elemento (0-based), o null si es summary>,
  "action": "replace" | "append",
  "content": "<texto exacto a insertar o reemplazar>"
}}

Si el mensaje no contiene una sugerencia aplicable, responde: {{"field": null}}

MENSAJE DEL ASESOR:
{advisor_message}

CV ACTUAL (para referencia de índices):
{cv_json}"""


def extract_chat_patch(
    advisor_message: str,
    cv_data: dict,
    api_key: str,
    model: str,
) -> dict | None:
    """Extrae un patch JSON de una sugerencia del chat."""
    if not AI_AVAILABLE:
        return None

    cv_clean = {k: v for k, v in cv_data.items() if k != "id"}
    cv_json = json.dumps(cv_clean, ensure_ascii=False, indent=2)
    prompt = EXTRACT_PATCH_PROMPT.format(
        advisor_message=advisor_message, cv_json=cv_json
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("EXTRACT PATCH — %s", ts)

    response = httpx.post(
        OLLAMA_CLOUD_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        },
        timeout=60.0,
    )
    response.raise_for_status()

    data = response.json()
    raw = data["message"]["content"].strip()

    logger.info("Patch raw: %s", raw[:500])

    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)

    parsed = json.loads(raw)
    if parsed.get("field") is None:
        return None
    return parsed


# ═══════════════════════════════════════════════════════════════
# EVALUACIÓN DETALLADA DEL CV
# ═══════════════════════════════════════════════════════════════

EVAL_SYSTEM_PROMPT = """\
Eres un evaluador experto de CVs contra vacantes. Tu trabajo es producir una evaluación \
DETALLADA, HONESTA y ESTRUCTURADA del match entre un CV y una vacante.

═══ REGLAS ═══

1. HONESTIDAD ANTE TODO — El score debe reflejar la realidad.
   - Si faltan requisitos hard (años, tecnologías core), el score NO puede superar 60.
   - Si hay gaps estructurales graves, el score debe ser <40.
   - Un candidato con 3 de 10 requisitos cubiertos NO es 68/100.

2. AÑOS DE EXPERIENCIA — Calcula años REALES usando la FECHA ACTUAL proporcionada y el campo "dates".
   - Resta la fecha de inicio a la FECHA ACTUAL. Ej: "Mayo 2024" hasta "March 2026" = ~2 años.

3. DETECCIÓN DE OVERFITTING — Si el CV contiene claims inflados o keywords stuffing:
   - Marca cada claim sospechoso con evidencia.
   - Esto BAJA el score, no lo sube.

4. DIMENSIONES — Evalúa cada skill/requisito clave de la vacante por separado (0-100).

5. REQUISITOS — Lista CADA requisito mencionado en la vacante y marca si se cumple o no.

6. VEREDICTOS — Da conclusiones accionables: fortalezas, problemas, recomendaciones.

Responde SOLO con JSON válido, sin markdown ni texto adicional."""

EVAL_USER_PROMPT_TEMPLATE = """\
FECHA ACTUAL: {current_date}

VACANTE:
{vacancy_text}

CV DEL CANDIDATO (JSON):
{cv_json}

Evalúa el CV contra la vacante y responde con este JSON exacto:
{{
  "overall_score": <0-100>,
  "score_label": "<frase corta describiendo el nivel de match>",
  "dimensions": [
    {{"name": "<skill/requisito clave>", "score": <0-100>, "status": "ok|warn|bad"}}
  ],
  "requirements": [
    {{"name": "<requisito del JD>", "status": "ok|warn|bad", "note": "<explicación breve>"}}
  ],
  "overfitting": [
    {{"severity": "warn|bad", "claim": "<claim sospechoso en el CV>", "reason": "<por qué es sospechoso>"}}
  ],
  "verdicts": [
    {{"type": "ok|warn|bad", "title": "<título>", "text": "<explicación>"}}
  ]
}}"""


def evaluate_cv_detailed(
    cv_data: dict, vacancy_text: str, api_key: str, model: str
) -> dict:
    """Envía CV + vacante a Ollama Cloud y retorna evaluación detallada."""
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Ollama Cloud")

    cv_clean = {k: v for k, v in cv_data.items() if k != "id"}
    cv_json = json.dumps(cv_clean, ensure_ascii=False, indent=2)
    current_date = datetime.now().strftime("%B %Y")
    user_prompt = EVAL_USER_PROMPT_TEMPLATE.format(
        vacancy_text=vacancy_text, cv_json=cv_json, current_date=current_date
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("=" * 60)
    logger.info("EVALUACIÓN DETALLADA — %s", ts)
    logger.info("Modelo: %s", model)

    req_file = os.path.join(_LOG_DIR, f"eval_request_{ts}.json")
    with open(req_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "model": model,
            "system_prompt": EVAL_SYSTEM_PROMPT,
            "user_prompt": user_prompt,
        }, f, ensure_ascii=False, indent=2)
    logger.info("Eval request guardado en: %s", req_file)

    response = httpx.post(
        OLLAMA_CLOUD_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": EVAL_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        },
        timeout=120.0,
    )
    response.raise_for_status()

    data = response.json()
    raw = data["message"]["content"].strip()

    logger.info("Eval response HTTP: %s", response.status_code)
    logger.info("Eval raw (primeros 500 chars): %s", raw[:500])

    resp_file = os.path.join(_LOG_DIR, f"eval_response_{ts}.json")
    with open(resp_file, "w", encoding="utf-8") as f:
        json.dump({"timestamp": ts, "raw_response": raw}, f, ensure_ascii=False, indent=2)

    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)

    parsed = json.loads(raw)

    logger.info("Eval score: %s | Label: %s", parsed.get("overall_score"), parsed.get("score_label"))
    logger.info("Dimensions: %d | Requirements: %d | Overfitting: %d | Verdicts: %d",
                len(parsed.get("dimensions", [])),
                len(parsed.get("requirements", [])),
                len(parsed.get("overfitting", [])),
                len(parsed.get("verdicts", [])))
    logger.info("=" * 60)

    return parsed


# ═══════════════════════════════════════════════════════════════
# SELECCIÓN DE ITEMS DEL BANCO
# ═══════════════════════════════════════════════════════════════

BANK_SELECTION_SYSTEM_PROMPT = """\
Eres un experto en reclutamiento, ATS y optimización de CVs formato Harvard.
Tu trabajo es seleccionar los items del banco del candidato que son MÁS RELEVANTES \
para la vacante dada.

═══ REGLAS ═══

1. RELEVANCIA — Selecciona SOLO items que aporten al match con la vacante.
   - Si la vacante es Backend puro: omite items de AI/ML, trading, IoT a menos que la vacante los mencione.
   - Si la vacante es AI/ML: incluye items de AI/ML + backend relevante.
   - Si la vacante es Full Stack: incluye backend, frontend y proyectos web.

2. EXPERIENCIAS — Siempre incluye el ID de la experiencia Y los IDs de los bullets relevantes.
   - Máximo 7 bullets por experiencia (límite formato Harvard).
   - Prioriza bullets con métricas cuantitativas y tecnologías mencionadas en el JD.

3. EDUCACIÓN — Incluye SIEMPRE toda la educación (todos los IDs de education).

4. SKILLS — Incluye skills que contengan tecnologías relevantes a la vacante.

5. SUMMARIES — Selecciona EL summary más relevante a la vacante.

6. PROYECTOS — Selecciona proyectos que demuestren habilidades pedidas en el JD.

═══ FORMATO DE RESPUESTA ═══
Responde SOLO con JSON válido, sin markdown:
{"selected_ids": ["id1", "id2", ...], "reasoning": "<explicación breve en español>"}"""

BANK_SELECTION_USER_TEMPLATE = """\
VACANTE:
{vacancy_text}

BANCO DEL CANDIDATO (todos los items disponibles):
{manifest_json}

Selecciona los IDs de items que deben incluirse en el CV para esta vacante.
Responde con JSON: {{"selected_ids": ["id1", "id2", ...], "reasoning": "..."}}"""


def select_from_bank(
    manifest: list[dict], vacancy_text: str, api_key: str, model: str
) -> list[str]:
    """Pide a la IA que seleccione qué items del banco activar para una vacante.

    Retorna lista de IDs seleccionados.
    """
    if not AI_AVAILABLE:
        raise RuntimeError("httpx no instalado. Ejecuta: pip install httpx")
    if not api_key:
        raise ValueError("Se requiere API key de Ollama Cloud")

    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
    user_prompt = BANK_SELECTION_USER_TEMPLATE.format(
        vacancy_text=vacancy_text, manifest_json=manifest_json
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("=" * 60)
    logger.info("SELECCIÓN DE BANCO — %s", ts)
    logger.info("Modelo: %s | Items en manifest: %d", model, len(manifest))

    req_file = os.path.join(_LOG_DIR, f"bank_select_request_{ts}.json")
    with open(req_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "model": model,
            "system_prompt": BANK_SELECTION_SYSTEM_PROMPT,
            "user_prompt": user_prompt,
        }, f, ensure_ascii=False, indent=2)

    response = httpx.post(
        OLLAMA_CLOUD_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": BANK_SELECTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        },
        timeout=90.0,
    )
    response.raise_for_status()

    data = response.json()
    raw = data["message"]["content"].strip()

    logger.info("Bank selection response (primeros 500 chars): %s", raw[:500])

    resp_file = os.path.join(_LOG_DIR, f"bank_select_response_{ts}.json")
    with open(resp_file, "w", encoding="utf-8") as f:
        json.dump({"timestamp": ts, "raw_response": raw}, f, ensure_ascii=False, indent=2)

    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)

    parsed = json.loads(raw)
    selected_ids = parsed.get("selected_ids", [])
    reasoning = parsed.get("reasoning", "")

    logger.info("IDs seleccionados: %d | Reasoning: %s", len(selected_ids), reasoning[:200])
    logger.info("=" * 60)

    return selected_ids
