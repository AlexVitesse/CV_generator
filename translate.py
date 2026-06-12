"""
Traducción automática de contenido del CV usando Google Translate (gratis).
"""

import copy
import json

from llm_client import call_ollama, _parse_json_response, get_logger
from pydantic import ValidationError
from validation import TranslationResponse

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False

logger = get_logger("translate")


# Mapeo de etiquetas de skills es↔en
_SKILL_LABELS = {
    "en": {
        # Categorías de skills
        "Dominio avanzado": "Core skills",
        "dominio avanzado": "Core skills",
        "Advanced domain": "Core skills",
        "advanced domain": "Core skills",
        "Dominio intermedio": "Working knowledge",
        "dominio intermedio": "Working knowledge",
        "Intermediate domain": "Working knowledge",
        "intermediate domain": "Working knowledge",
        "Familiaridad": "Exposure to",
        "familiaridad": "Exposure to",
        "Familiarity": "Exposure to",
        "familiarity": "Exposure to",
        # Términos técnicos que Google Translate mangla
        "IA/ML": "AI/ML",
        "Ia/ml": "AI/ML",
        "RAG híbrido": "Hybrid RAG",
        "RAG Híbrido": "Hybrid RAG",
        "rag híbrido": "Hybrid RAG",
        "híbrido": "hybrid",
        "Híbrido": "Hybrid",
        "Certs:": "Certs:",
        "certificaciones": "certifications",
    },
    "es": {
        "Core skills": "Dominio avanzado",
        "core skills": "Dominio avanzado",
        "Working knowledge": "Dominio intermedio",
        "working knowledge": "Dominio intermedio",
        "Exposure to": "Familiaridad",
        "exposure to": "Familiaridad",
        "AI/ML": "IA/ML",
        "Hybrid RAG": "RAG híbrido",
        "hybrid": "híbrido",
    },
}


def _fix_skill_labels(text: str, target_lang: str) -> str:
    """Reemplaza etiquetas de skills con la traducción correcta."""
    replacements = _SKILL_LABELS.get(target_lang, {})
    for wrong, right in replacements.items():
        text = text.replace(wrong, right)
    return text


def translate_text(text: str, source: str, target: str) -> str:
    """Traduce un texto usando Google Translate gratuito.
    Respeta saltos de línea traduciendo línea por línea."""
    if not text or not text.strip():
        return text
    if source == target:
        return text

    translator = GoogleTranslator(source="auto", target=target)

    def _fix_capitalization(original: str, translated: str) -> str:
        """Corrige capitalización de Google Translate.
        Si el original empezaba con minúscula, fuerza minúscula en la traducción."""
        if not original or not translated:
            return translated
        if original[0].islower() and translated[0].isupper():
            return translated[0].lower() + translated[1:]
        return translated

    try:
        if "\n" in text:
            lines = text.split("\n")
            translated_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped:
                    try:
                        res = translator.translate(stripped)
                        res = _fix_capitalization(stripped, res) if res else stripped
                        translated_lines.append(res)
                    except Exception:
                        translated_lines.append(stripped)
                else:
                    translated_lines.append("")
            return "\n".join(translated_lines)
        else:
            res = translator.translate(text)
            return _fix_capitalization(text, res) if res else text
    except Exception as e:
        logger.exception("translate_text error")
        return text


def _restore_ids_with_fallback(data_section: list, trans_section: list, source: str, target: str):
    """Restaura IDs y traduce items faltantes si el LLM devolvió menos."""
    if len(trans_section) < len(data_section):
        logger.warning(
            "LLM devolvió %d items de %d — traduciendo los %d faltantes con fallback",
            len(trans_section), len(data_section),
            len(data_section) - len(trans_section),
        )
        for i in range(len(trans_section), len(data_section)):
            orig = data_section[i]
            missing = copy.deepcopy(orig)
            for key in ("company", "title", "bullets", "name", "description",
                         "institution", "degree", "details", "text", "summary"):
                if key in missing and isinstance(missing[key], str) and missing[key].strip():
                    missing[key] = _translate_fallback(missing[key], source, target)
            trans_section.append(missing)

    for orig, trans in zip(data_section, trans_section):
        if isinstance(trans, dict) and isinstance(orig, dict):
            trans["id"] = orig.get("id", trans.get("id"))


def _translate_fallback(text: str, source: str, target: str) -> str:
    """Traduce un texto con deep-translator."""
    return translate_text(text, source, target)


def translate_cv_via_llm(data: dict, source: str, target: str, api_key: str, model: str) -> dict:
    """Traduce la estructura completa del CV usando LLM (Ollama Cloud) en una sola llamada."""
    cv_clean = copy.deepcopy(data)

    system_prompt = (
        "You are an expert professional translator specializing in IT, Software Engineering, and ATS optimization.\n"
        f"Translate the following CV JSON schema from '{source}' to '{target}'.\n"
        "RULES:\n"
        "1. Translate all text values of fields such as: 'summary', 'company', 'title', 'bullets', 'name', 'description', 'institution', 'degree', 'details', 'location'.\n"
        "2. Keep all JSON keys, IDs (like 'id'), URLs, phone numbers, and structural schema exactly the same.\n"
        "3. Preserve technical jargon appropriately: do not translate standard tech terms literally (e.g., keep 'FastAPI', 'RAG', 'machine learning', 'data pipelines' as standard professional terms in the target language).\n"
        "4. Return ONLY valid raw JSON representing the translated CV. Do not wrap it in markdown code blocks like ```json or add any explanation text."
    )

    user_prompt = json.dumps(cv_clean, ensure_ascii=False)

    raw_reply = call_ollama(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=model, api_key=api_key, json_mode=True, timeout=120.0,
    )

    # Parsing tolerante a fences (antes era json.loads directo → crash si venía texto)
    translated_json = _parse_json_response(raw_reply)

    # Chequeo suave del shape: solo advierte; la reparación item-a-item de abajo
    # cubre los faltantes, así que no bloqueamos la traducción.
    try:
        TranslationResponse.model_validate(translated_json)
    except ValidationError as e:
        logger.warning("translate: shape inesperado del LLM (%d errores)", e.error_count())

    # Restaurar IDs con validación de largos y fallback
    if "experiences" in data and "experiences" in translated_json:
        _restore_ids_with_fallback(
            data["experiences"], translated_json["experiences"], source, target
        )
    if "education" in data and "education" in translated_json:
        _restore_ids_with_fallback(
            data["education"], translated_json["education"], source, target
        )
    if "projects" in data and "projects" in translated_json:
        _restore_ids_with_fallback(
            data["projects"], translated_json["projects"], source, target
        )
    if "skills" in data and "skills" in translated_json:
        _restore_ids_with_fallback(
            data["skills"], translated_json["skills"], source, target
        )

    return translated_json


def translate_cv_data(data: dict, source: str, target: str,
                       progress_callback=None, api_key: str = None, model: str = None) -> dict:
    """Traduce todos los campos de texto del CV. Usa traducción por IA si api_key está disponible,
    si no, o si falla, usa deep-translator."""
    if api_key and model:
        try:
            logger.info("Iniciando traducción semántica por IA (Ollama Cloud)")
            if progress_callback:
                progress_callback(0.3)
            result = translate_cv_via_llm(data, source, target, api_key, model)
            if progress_callback:
                progress_callback(1.0)
            return result
        except Exception as e:
            logger.warning("Fallo traducción por IA, usando fallback de Google: %s", e)

    translated = copy.deepcopy(data)
    logger.info("Traducción Google de %s a %s", source, target)

    total_steps = 2  # summary + location
    total_steps += len(translated.get("experiences", [])) * 3
    total_steps += len(translated.get("projects", [])) * 2
    total_steps += len(translated.get("education", [])) * 3
    total_steps += len(translated.get("skills", []))
    current_step = 0

    def step(field_name, text, src, tgt):
        nonlocal current_step
        current_step += 1
        if progress_callback:
            progress_callback(current_step / max(total_steps, 1))

        result = translate_text(text, src, tgt)
        logger.debug("[%s] (%d chars) -> %s...", field_name, len(text), result[:30])
        return result

    # ── Resumen y Ubicación ──────────────────────────────────
    translated["summary"] = step("summary", translated.get("summary", ""), source, target)
    translated["location"] = step("location", translated.get("location", ""), source, target)

    # ── Experiencias ─────────────────────────────────────────
    for i, exp in enumerate(translated.get("experiences", [])):
        exp["company"] = step(f"exp_{i}_co", exp.get("company", ""), source, target)
        exp["title"] = step(f"exp_{i}_ti", exp.get("title", ""), source, target)
        exp["bullets"] = step(f"exp_{i}_bu", exp.get("bullets", ""), source, target)

        if exp.get("dates"):
            exp["dates"] = translate_text(exp["dates"], source, target)
        if exp.get("location"):
            exp["location"] = translate_text(exp["location"], source, target)

    # ── Proyectos ───────────────────────────────────────────
    for i, proj in enumerate(translated.get("projects", [])):
        proj["name"] = step(f"proj_{i}_nm", proj.get("name", ""), source, target)
        proj["description"] = step(f"proj_{i}_ds", proj.get("description", ""), source, target)

    # ── Educación ────────────────────────────────────────────
    for i, edu in enumerate(translated.get("education", [])):
        edu["institution"] = step(f"edu_{i}_in", edu.get("institution", ""), source, target)
        edu["degree"] = step(f"edu_{i}_de", edu.get("degree", ""), source, target)
        edu["details"] = step(f"edu_{i}_dz", edu.get("details", ""), source, target)

        if edu.get("location"):
            edu["location"] = translate_text(edu["location"], source, target)
        if edu.get("date"):
            edu["date"] = translate_text(edu["date"], source, target)

    # ── Skills ───────────────────────────────────────────────
    for i, sk in enumerate(translated.get("skills", [])):
        sk["text"] = step(f"skill_{i}", sk.get("text", ""), source, target)
        sk["text"] = _fix_skill_labels(sk["text"], target)

    logger.info("Traducción finalizada")
    return translated

