"""
Traducción automática de contenido del CV usando Google Translate (gratis).
"""

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False


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
        print(f"Error traducción: {e}")
        return text


def translate_cv_data(data: dict, source: str, target: str,
                      progress_callback=None) -> dict:
    """Traduce todos los campos de texto del CV."""
    import copy
    translated = copy.deepcopy(data)
    print(f"--- Iniciando traducción de {source} a {target} ---")

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
        print(f"[{field_name}] ({len(text)} chars) -> {result[:30]}...")
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
        # Reemplazo determinístico de etiquetas de skills (Google Translate las mangla)
        sk["text"] = _fix_skill_labels(sk["text"], target)

    print("--- Traducción finalizada ---")
    return translated
