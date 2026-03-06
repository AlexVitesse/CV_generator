"""
Traducción automática de contenido del CV usando Google Translate (gratis).
"""

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False


def translate_text(text: str, source: str, target: str) -> str:
    """Traduce un texto usando Google Translate gratuito.
    Respeta saltos de línea traduciendo línea por línea."""
    if not text or not text.strip():
        return text
    if source == target:
        return text

    translator = GoogleTranslator(source="auto", target=target)

    try:
        if "\n" in text:
            lines = text.split("\n")
            translated_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped:
                    try:
                        res = translator.translate(stripped)
                        translated_lines.append(res if res else stripped)
                    except Exception:
                        translated_lines.append(stripped)
                else:
                    translated_lines.append("")
            return "\n".join(translated_lines)
        else:
            res = translator.translate(text)
            return res if res else text
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

    print("--- Traducción finalizada ---")
    return translated
