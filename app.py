"""
╔══════════════════════════════════════════════════════════════╗
║           CV Generator — Formato Harvard                     ║
║   Edita tu CV y genera PDF en Español o Inglés.              ║
║   Traducción automática vía Google Translate (gratis).       ║
║                                                              ║
║   Instalación:                                               ║
║     pip install streamlit reportlab deep-translator          ║
║                                                              ║
║   Uso:                                                       ║
║     streamlit run app.py                                     ║
╚══════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import json
import html as _html
import re
import uuid
import os

from i18n import LANG_NAMES, t
from translate import TRANSLATOR_AVAILABLE, translate_cv_data
from pdf import generate_cv_pdf
from ai_analyzer import AI_AVAILABLE


# ═══════════════════════════════════════════════════════════════
# POST-PROCESAMIENTO DE SUGERENCIAS IA
# ═══════════════════════════════════════════════════════════════

def _sanitize_ai_result(result: dict) -> dict:
    """Limpia problemas comunes de la respuesta de la IA antes de mostrarla."""
    suggestions = result.get("suggestions", {})

    # ── Fix summary: palabras pegadas (e.g. "EngineerBackend") ──
    if suggestions.get("summary"):
        suggestions["summary"] = _fix_stuck_words(suggestions["summary"])

    # ── Fix experience titles y bullets ──
    for exp in suggestions.get("experiences", []):
        if exp.get("title"):
            exp["title"] = _fix_stuck_words(exp["title"])
        if exp.get("bullets"):
            exp["bullets"] = _strip_parenthetical_notes(exp["bullets"])

    # ── Fix project descriptions ──
    for proj in suggestions.get("projects", []):
        if proj.get("description"):
            proj["description"] = _strip_parenthetical_notes(proj["description"])

    # ── Fix skills: quitar paréntesis justificativos ──
    if suggestions.get("skills"):
        if isinstance(suggestions["skills"], list):
            suggestions["skills"] = [
                _strip_parenthetical_notes(s) for s in suggestions["skills"]
            ]

    return result


_PROTECTED_TERMS = [
    "FastAPI", "FastHTML", "JavaScript", "TypeScript", "PostgreSQL",
    "MySQL", "MongoDB", "GraphQL", "NodeJS", "Node.js", "GitHub",
    "GitLab", "BitBucket", "DevOps", "MLOps", "DataOps", "LangChain",
    "LangFuse", "LangSmith", "ChromaDB", "RunPod", "HuggingFace",
    "OpenAI", "SQLAlchemy", "SQLModel", "PyTorch", "TensorFlow",
    "APIs", "SDKs", "LLMs", "ORMs", "IoT", "OAuth", "WebSocket",
    "innerHTML", "CloudRun", "BigQuery", "PubSub",
]


def _fix_stuck_words(text: str) -> str:
    """Inserta espacio entre palabras pegadas tipo CamelCase: 'EngineerBackend' → 'Engineer Backend'.
    Protege términos técnicos conocidos (FastAPI, APIs, etc.)."""
    # Reemplazar términos protegidos con placeholders
    placeholders = {}
    for i, term in enumerate(_PROTECTED_TERMS):
        placeholder = f"\x00TERM{i}\x00"
        if term in text:
            text = text.replace(term, placeholder)
            placeholders[placeholder] = term

    # Aplicar regex de separación
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', text)

    # Restaurar términos protegidos
    for placeholder, term in placeholders.items():
        text = text.replace(placeholder, term)

    return text


def _strip_parenthetical_notes(text: str) -> str:
    """Elimina paréntesis con justificaciones/explicaciones, conserva los técnicos."""
    # Palabras que indican nota justificativa (en/es)
    justification_markers = [
        "implícit", "implicit", "inferred", "inferido",
        "equivalen", "transferi", "implied",
        "uso de", "use of ORMs", "experiencia cloud",
    ]

    def _is_justification(content: str) -> bool:
        lower = content.lower()
        return any(m in lower for m in justification_markers)

    # Reemplaza paréntesis que contienen marcadores justificativos
    def _replace(match):
        inner = match.group(1)
        if _is_justification(inner):
            return ""  # Eliminar completamente
        return match.group(0)  # Conservar paréntesis técnicos

    result = re.sub(r'\s*\(([^)]+)\)', _replace, text)
    # Limpiar espacios dobles resultantes
    result = re.sub(r'  +', ' ', result).strip()
    return result


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def uid():
    return uuid.uuid4().hex[:8]


def clear_keys(*prefixes):
    for key in list(st.session_state.keys()):
        if any(key.startswith(p) for p in prefixes):
            del st.session_state[key]


def sync_widgets_to_data(data: dict):
    """Sincroniza valores de widgets de Streamlit al diccionario de datos del CV.
    Evita la repetición manual de chequear cada key del session_state."""

    # Campos simples: (session_key, data_key)
    simple_fields = [
        ("f_name", "name"),
        ("f_loc", "location"),
        ("f_summary", "summary"),
    ]
    for skey, dkey in simple_fields:
        if skey in st.session_state:
            data[dkey] = st.session_state[skey]

    # Experiencias: (prefijo_widget, campo_en_dict)
    exp_fields = [
        ("x_co_", "company"),
        ("x_ti_", "title"),
        ("x_lo_", "location"),
        ("x_da_", "dates"),
        ("x_bu_", "bullets"),
    ]
    for ex in data.get("experiences", []):
        eid = ex["id"]
        for prefix, field in exp_fields:
            key = f"{prefix}{eid}"
            if key in st.session_state:
                ex[field] = st.session_state[key]

    # Educación
    edu_fields = [
        ("e_in_", "institution"),
        ("e_de_", "degree"),
        ("e_lo_", "location"),
        ("e_dt_", "date"),
        ("e_dz_", "details"),
    ]
    for ed in data.get("education", []):
        eid = ed["id"]
        for prefix, field in edu_fields:
            key = f"{prefix}{eid}"
            if key in st.session_state:
                ed[field] = st.session_state[key]

    # Proyectos
    proj_fields = [
        ("p_nm_", "name"),
        ("p_ur_", "url"),
        ("p_ds_", "description"),
    ]
    for proj in data.get("projects", []):
        pid = proj["id"]
        for prefix, field in proj_fields:
            key = f"{prefix}{pid}"
            if key in st.session_state:
                proj[field] = st.session_state[key]

    # Skills
    for sk in data.get("skills", []):
        key = f"s_tx_{sk['id']}"
        if key in st.session_state:
            sk["text"] = st.session_state[key]


def push_data_to_widgets(data: dict):
    """Actualiza los widgets de Streamlit con los valores del diccionario
    (usado después de traducción para reflejar cambios en pantalla)."""

    st.session_state["f_name"] = data.get("name", "")
    st.session_state["f_loc"] = data.get("location", "")
    st.session_state["f_summary"] = data.get("summary", "")

    for ex in data.get("experiences", []):
        eid = ex["id"]
        st.session_state[f"x_co_{eid}"] = ex.get("company", "")
        st.session_state[f"x_ti_{eid}"] = ex.get("title", "")
        st.session_state[f"x_lo_{eid}"] = ex.get("location", "")
        st.session_state[f"x_da_{eid}"] = ex.get("dates", "")
        st.session_state[f"x_bu_{eid}"] = ex.get("bullets", "")

    for ed in data.get("education", []):
        eid = ed["id"]
        st.session_state[f"e_in_{eid}"] = ed.get("institution", "")
        st.session_state[f"e_de_{eid}"] = ed.get("degree", "")
        st.session_state[f"e_lo_{eid}"] = ed.get("location", "")
        st.session_state[f"e_dt_{eid}"] = ed.get("date", "")
        st.session_state[f"e_dz_{eid}"] = ed.get("details", "")

    for proj in data.get("projects", []):
        pid = proj["id"]
        st.session_state[f"p_nm_{pid}"] = proj.get("name", "")
        st.session_state[f"p_ur_{pid}"] = proj.get("url", "")
        st.session_state[f"p_ds_{pid}"] = proj.get("description", "")

    for sk in data.get("skills", []):
        st.session_state[f"s_tx_{sk['id']}"] = sk.get("text", "")


# ═══════════════════════════════════════════════════════════════
# VALIDACIÓN DE FORMATO
# ═══════════════════════════════════════════════════════════════

def validate_email(email: str) -> bool:
    if not email:
        return True
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def validate_phone(phone: str) -> bool:
    if not phone:
        return True
    # Permite +, dígitos, espacios y guiones
    return bool(re.match(r"^\+?[\d\s\-()]{7,20}$", phone))


def validate_linkedin(url: str) -> bool:
    if not url:
        return True
    return "linkedin.com/in/" in url.lower()


# ═══════════════════════════════════════════════════════════════
# DATOS POR DEFECTO
# ═══════════════════════════════════════════════════════════════

def default_cv_data():
    """Carga datos iniciales desde JSON. Prioriza config_personal.json si existe."""
    personal_config = "config_personal.json"
    template_config = "config_plantilla.json"
    
    data = {}
    if os.path.exists(personal_config):
        try:
            with open(personal_config, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
            
    if not data and os.path.exists(template_config):
        try:
            with open(template_config, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    if not data:
        # Fallback total si fallan los archivos
        data = {
            "name": "Tu Nombre Completo",
            "location": "Ciudad, País",
            "linkedin": "www.linkedin.com/in/tu-perfil",
            "phone": "+52 00 0000 0000",
            "email": "tu@correo.com",
            "summary": "Breve descripción de tu perfil profesional.",
            "experiences": [],
            "education": [],
            "skills": []
        }

    # Asegurar IDs únicos para widgets de Streamlit
    for exp in data.get("experiences", []):
        if "id" not in exp: exp["id"] = uid()
    for proj in data.get("projects", []):
        if "id" not in proj: proj["id"] = uid()
    for edu in data.get("education", []):
        if "id" not in edu: edu["id"] = uid()
    for sk in data.get("skills", []):
        if "id" not in sk: sk["id"] = uid()
        
    return data


# ═══════════════════════════════════════════════════════════════
# INTERFAZ STREAMLIT
# ═══════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title="CV Harvard Generator",
        page_icon="📄",
        layout="wide",
    )

    # ── Inicialización ───────────────────────────────────────
    # ── Banco de habilidades ──
    if "banco" not in st.session_state:
        from banco import load_banco, migrate_from_config, save_banco
        _banco = load_banco()
        if not _banco:
            # Intentar migrar desde config_personal.json
            cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_personal.json")
            if os.path.exists(cfg_path):
                _banco = migrate_from_config(cfg_path)
                save_banco(_banco)
        st.session_state.banco = _banco

    if "cv" not in st.session_state:
        if st.session_state.get("banco"):
            from banco import bank_to_active_cv
            st.session_state.cv = bank_to_active_cv(st.session_state.banco)
        else:
            st.session_state.cv = default_cv_data()
    if "lang" not in st.session_state:
        st.session_state.lang = "es"
    if "content_lang" not in st.session_state:
        st.session_state.content_lang = "es"
    if "ai_api_key" not in st.session_state:
        if AI_AVAILABLE:
            from ai_analyzer import load_ai_config, DEFAULT_MODEL
            _cfg = load_ai_config()
            st.session_state.ai_api_key = _cfg.get("api_key", "")
            st.session_state.ai_model = _cfg.get("model", DEFAULT_MODEL)
        else:
            st.session_state.ai_api_key = ""
            st.session_state.ai_model = ""
    if "analysis_result" not in st.session_state:
        st.session_state.analysis_result = None
    if "eval_result" not in st.session_state:
        st.session_state.eval_result = None
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    if "chat_pending_patch" not in st.session_state:
        st.session_state.chat_pending_patch = None
    if "refine_chat_open" not in st.session_state:
        st.session_state.refine_chat_open = False
    if "refine_messages" not in st.session_state:
        st.session_state.refine_messages = []

    d = st.session_state.cv

    # ── Deferred push: actualizar widget keys ANTES de renderizar widgets ──
    if st.session_state.pop("_needs_widget_push", False):
        push_data_to_widgets(d)

    # ── Deferred: auto-traducir + re-evaluar después de aplicar adaptaciones ──
    if st.session_state.pop("_needs_reevaluation", False):
        _deferred_translate_and_reevaluate(d)

    # ── Título ───────────────────────────────────────────────
    st.title(f"📄 {t('page_title')}")
    st.caption(t("subtitle"))

    # ── Top bar: Score + Vacante + Re-evaluar ────────────────
    _render_score_navbar(d)

    # ── Barra lateral ────────────────────────────────────────
    with st.sidebar:
        # ── Selector de idioma de interfaz ───────────────────
        st.subheader(t("language"))
        lang_options = {"es": "🇲🇽 Español", "en": "🇺🇸 English"}
        current_idx = 0 if st.session_state.lang == "es" else 1
        selected_lang = st.radio(
            t("language"),
            options=list(lang_options.keys()),
            format_func=lambda x: lang_options[x],
            index=current_idx,
            horizontal=True,
            label_visibility="collapsed",
        )
        if selected_lang != st.session_state.lang:
            st.session_state.lang = selected_lang
            st.rerun()

        st.divider()

        # ── Traducción automática del contenido ──────────────
        st.subheader("🔄 Traducción automática")

        current_content = st.session_state.content_lang
        target_lang = "en" if current_content == "es" else "es"
        target_name = LANG_NAMES[target_lang]

        content_label = (
            f"Contenido actual: **{LANG_NAMES[current_content]}**"
            if st.session_state.lang == "es"
            else f"Current content: **{LANG_NAMES[current_content]}**"
        )
        st.markdown(content_label)

        if TRANSLATOR_AVAILABLE:
            if st.button(
                t("translate_btn").format(target_name),
                use_container_width=True,
            ):
                try:
                    sync_widgets_to_data(d)

                    progress_bar = st.progress(0, text=t("translating"))
                    translated = translate_cv_data(
                        d,
                        source=current_content,
                        target=target_lang,
                        progress_callback=lambda p: progress_bar.progress(
                            min(p, 1.0), text=t("translating")
                        ),
                    )
                    progress_bar.progress(1.0, text="✅")

                    st.session_state.cv = translated
                    st.session_state.content_lang = target_lang
                    st.session_state.lang = target_lang

                    st.session_state._needs_widget_push = True
                    st.toast(t("translate_success").format(target_name))
                    st.rerun()
                except Exception as e:
                    print(f"FATAL ERROR: {e}")
                    st.error(t("translate_error").format(str(e)))
        else:
            st.warning(t("translate_missing"))

        st.divider()

        # ── Generar PDF ──────────────────────────────────────
        st.header(t("actions"))

        if st.button(t("generate_pdf"), type="primary",
                     use_container_width=True):
            try:
                pdf_buf = generate_cv_pdf(d, lang=st.session_state.lang)
                st.session_state.pdf_bytes = pdf_buf.getvalue()
                st.success(t("pdf_success"))
            except Exception as e:
                st.error(t("pdf_error").format(e))

        # ── Empresa destino (siempre visible para nombre PDF + cover letter) ──
        import re as _re
        _company_raw = st.text_input(
            t("target_company"),
            key="target_company_input",
            placeholder="Ej: Excelia",
        )
        if _company_raw:
            st.session_state._target_company = _company_raw

        if "pdf_bytes" in st.session_state:
            lang_suffix = st.session_state.lang.upper()
            _name = d.get("name", "")
            _initials = "".join(w[0] for w in _name.split() if w).upper() if _name else "XX"
            _co = st.session_state.get("_target_company", "")
            _company = _re.sub(r'[^\w]', '', _co).strip() if _co else ""
            _pdf_name = f"CV_{_initials}_{_company}.pdf" if _company else f"CV_{_initials}_{lang_suffix}.pdf"
            st.download_button(
                t("download_pdf"),
                data=st.session_state.pdf_bytes,
                file_name=_pdf_name,
                mime="application/pdf",
                use_container_width=True,
            )

        # ── Summary y Cover Letter ────────────────────────
        if AI_AVAILABLE and st.session_state.get("ai_api_key"):
            st.divider()
            sc1, sc2 = st.columns(2)
            with sc1:
                if st.button(t("generate_summary"), use_container_width=True):
                    try:
                        from ai_analyzer import generate_text, SUMMARY_SYSTEM_PROMPT
                        sync_widgets_to_data(d)
                        lang_name = "español" if st.session_state.content_lang == "es" else "English"
                        vacancy_ctx = st.session_state.get("vacancy_text", "").strip()
                        with st.spinner(t("summary_generating")):
                            summary = generate_text(
                                d,
                                st.session_state.ai_api_key,
                                st.session_state.ai_model,
                                SUMMARY_SYSTEM_PROMPT.format(lang=lang_name),
                                f"Genera un summary/elevator pitch en {lang_name}.",
                                vacancy_text=vacancy_ctx,
                            )
                        st.session_state._generated_summary = summary
                    except Exception as e:
                        st.error(str(e))
            with sc2:
                if st.button(t("generate_cover"), use_container_width=True):
                    _co = st.session_state.get("_target_company", "").strip()
                    vacancy_ctx = st.session_state.get("vacancy_text", "").strip()
                    if not _co:
                        st.warning(t("cover_no_company"))
                    elif not vacancy_ctx:
                        st.warning(t("cover_no_vacancy"))
                    else:
                        try:
                            from ai_analyzer import generate_text, COVER_LETTER_SYSTEM_PROMPT
                            sync_widgets_to_data(d)
                            lang_name = "español" if st.session_state.content_lang == "es" else "English"
                            with st.spinner(t("cover_generating")):
                                cover = generate_text(
                                    d,
                                    st.session_state.ai_api_key,
                                    st.session_state.ai_model,
                                    COVER_LETTER_SYSTEM_PROMPT.format(lang=lang_name),
                                    f"Genera una cover letter en {lang_name} para la empresa {_co}.",
                                    vacancy_text=vacancy_ctx,
                                )
                            st.session_state._generated_cover = cover
                        except Exception as e:
                            st.error(str(e))

            # Mostrar summary generado (st.code tiene botón copiar nativo)
            if st.session_state.get("_generated_summary"):
                st.caption("Summary")
                st.code(st.session_state._generated_summary, language=None)

            # Mostrar cover letter generada
            if st.session_state.get("_generated_cover"):
                st.caption(t("cover_result"))
                st.code(st.session_state._generated_cover, language=None)

        st.divider()
        st.subheader(t("data_section"))

        uploaded = st.file_uploader(t("import_json"), type=["json"])
        if uploaded is not None:
            try:
                imported = json.load(uploaded)
                for exp in imported.get("experiences", []):
                    exp.setdefault("id", uid())
                for proj in imported.get("projects", []):
                    proj.setdefault("id", uid())
                for edu in imported.get("education", []):
                    edu.setdefault("id", uid())
                for i, sk in enumerate(imported.get("skills", [])):
                    if isinstance(sk, str):
                        imported["skills"][i] = {"id": uid(), "text": sk}
                    elif isinstance(sk, dict):
                        sk.setdefault("id", uid())
                st.session_state.cv = imported
                st.session_state.content_lang = "es"
                clear_keys("x_", "p_", "e_", "s_", "f_")
                st.success(t("import_success"))
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

        st.divider()

        if st.button(t("restore_example"), use_container_width=True):
            st.session_state.cv = default_cv_data()
            st.session_state.content_lang = "es"
            st.session_state.lang = "es"
            clear_keys("x_", "p_", "e_", "s_", "f_")
            st.rerun()

        # ── Configuración IA ─────────────────────────────────
        st.divider()
        st.subheader(t("ai_config_header"))

        if AI_AVAILABLE:
            from ai_analyzer import save_ai_config, DEFAULT_MODEL
            new_key = st.text_input(
                t("ai_api_key"),
                value=st.session_state.ai_api_key,
                type="password",
            )
            new_model = st.text_input(
                t("ai_model"),
                value=st.session_state.ai_model or DEFAULT_MODEL,
            )
            # Guardar si cambió
            if new_key != st.session_state.ai_api_key or new_model != st.session_state.ai_model:
                st.session_state.ai_api_key = new_key
                st.session_state.ai_model = new_model
                save_ai_config(new_key, new_model)
        else:
            st.warning(t("ai_not_available"))

        # ── Guardar CV al banco ────────────────────────────
        if st.session_state.get("banco"):
            st.divider()
            if st.button(t("banco_save_cv"), use_container_width=True):
                from banco import merge_cv_to_bank, save_banco
                sync_widgets_to_data(d)
                merge_cv_to_bank(d, st.session_state.banco)
                save_banco(st.session_state.banco)
                st.toast(t("banco_saved_to_bank"))

    # ── Tabs principales ────────────────────────────────────
    tab_analysis, tab_manual, tab_chat, tab_eval, tab_banco = st.tabs([
        t("tab_analysis"), t("tab_manual"), t("tab_chat"), t("tab_eval"), t("tab_banco"),
    ])

    # ══════════════════════════════════════════════════════════
    # TAB 1: ANÁLISIS DE VACANTE
    # ══════════════════════════════════════════════════════════
    with tab_analysis:
        if AI_AVAILABLE:
            # Mostrar confirmación si se acaba de aplicar
            if st.session_state.get("cv_adapted"):
                st.success(t("vacancy_applied"))
                del st.session_state.cv_adapted

            vacancy_text = st.text_area(
                t("vacancy_placeholder"),
                height=200,
                key="vacancy_text",
                label_visibility="collapsed",
                placeholder=t("vacancy_placeholder"),
            )

            if st.button(t("vacancy_analyze"), type="primary"):
                if not vacancy_text.strip():
                    st.warning(t("vacancy_empty"))
                else:
                    try:
                        from ai_analyzer import analyze_vacancy
                        sync_widgets_to_data(d)

                        with st.spinner(t("vacancy_analyzing")):
                            result = analyze_vacancy(
                                d, vacancy_text,
                                st.session_state.ai_api_key,
                                st.session_state.ai_model,
                            )
                        st.session_state.analysis_result = _sanitize_ai_result(result)
                        st.session_state._needs_widget_push = True
                        st.rerun()
                    except Exception as e:
                        st.error(t("vacancy_error").format(str(e)))

            # ── Mostrar resultados ────────────────────────────
            result = st.session_state.analysis_result
            if result:
                st.divider()
                c1, c2 = st.columns(2)
                with c1:
                    score = result.get("match_score", 0)
                    st.metric(t("vacancy_match"), f"{score}%")
                with c2:
                    viable = result.get("viable", False)
                    st.metric(
                        t("vacancy_viable"),
                        t("vacancy_yes") if viable else t("vacancy_no"),
                    )

                with st.expander(t("vacancy_matching_kw"), expanded=True):
                    kws = result.get("matching_keywords", [])
                    st.write(", ".join(f"**{k}**" for k in kws) if kws else "—")

                with st.expander(t("vacancy_missing_kw"), expanded=True):
                    kws = result.get("missing_keywords", [])
                    st.write(", ".join(f"**{k}**" for k in kws) if kws else "—")

                with st.expander(t("vacancy_reasoning")):
                    st.write(result.get("reasoning", ""))

                # ── Sugerencias editables ─────────────────────
                suggestions = result.get("suggestions", {})
                if suggestions:
                    st.divider()
                    st.subheader(t("vacancy_suggestions"))

                    edited_summary = None
                    if suggestions.get("summary"):
                        edited_summary = st.text_area(
                            t("vacancy_suggested_summary"),
                            value=suggestions["summary"],
                            height=100,
                            key="sug_summary",
                        )

                    edited_exps = {}
                    edited_titles = {}
                    for exp_sug in suggestions.get("experiences", []):
                        idx = exp_sug.get("index", 0)
                        if exp_sug.get("title"):
                            edited_titles[idx] = st.text_input(
                                f"{t('job_title')} — Exp #{idx}",
                                value=exp_sug["title"],
                                key=f"sug_title_{idx}",
                            )
                        edited_exps[idx] = st.text_area(
                            t("vacancy_suggested_bullets").format(idx),
                            value=exp_sug.get("bullets", ""),
                            height=180,
                            key=f"sug_exp_{idx}",
                        )

                    edited_projs = {}
                    for proj_sug in suggestions.get("projects", []):
                        idx = proj_sug.get("index", 0)
                        edited_projs[idx] = st.text_area(
                            f"Proyecto #{idx} — descripción sugerida",
                            value=proj_sug.get("description", ""),
                            height=100,
                            key=f"sug_proj_{idx}",
                        )

                    edited_skills = None
                    if suggestions.get("skills"):
                        raw_skills = suggestions["skills"]
                        if isinstance(raw_skills, list):
                            skills_value = " | ".join(raw_skills)
                        else:
                            skills_value = str(raw_skills)
                        edited_skills = st.text_area(
                            t("vacancy_suggested_skills"),
                            value=skills_value,
                            height=100,
                            key="sug_skills",
                        )

                    if st.button(t("vacancy_apply"), type="primary"):
                        sync_widgets_to_data(d)

                        if edited_summary is not None:
                            d["summary"] = edited_summary

                        for idx, title in edited_titles.items():
                            if 0 <= idx < len(d.get("experiences", [])):
                                d["experiences"][idx]["title"] = title

                        for idx, bullets in edited_exps.items():
                            if 0 <= idx < len(d.get("experiences", [])):
                                d["experiences"][idx]["bullets"] = bullets

                        for idx, desc in edited_projs.items():
                            projs = d.get("projects", [])
                            if 0 <= idx < len(projs):
                                projs[idx]["description"] = desc

                        if edited_skills is not None:
                            # Preservar líneas de skills existentes que la IA no cubrió (ej: certs)
                            new_skills = [{"id": uid(), "text": edited_skills.strip()}]
                            # Si el CV original tenía más líneas de skills, conservarlas
                            existing_skills = d.get("skills", [])
                            for sk in existing_skills:
                                txt = sk.get("text", "")
                                # Conservar líneas de certs/IA que no están en la sugerencia
                                if ("Cert" in txt or "cert" in txt) and txt.strip() not in edited_skills:
                                    new_skills.append(sk)
                            d["skills"] = new_skills

                        st.session_state._needs_widget_push = True
                        st.session_state._needs_reevaluation = True
                        st.session_state.cv_adapted = True
                        st.rerun()

            # ── Chat de refinamiento inline ──────────────────
            if result:
                st.divider()
                refine_messages = st.session_state.get("refine_messages", [])

                if not st.session_state.get("refine_chat_open"):
                    if st.button("💬 " + t("refine_chat_open"), key="refine_open"):
                        st.session_state.refine_chat_open = True
                        st.session_state.refine_messages = []
                        st.rerun()
                else:
                    st.subheader(t("refine_chat_header"))
                    st.caption(t("refine_chat_caption"))

                    if st.button(t("refine_chat_close"), key="refine_close"):
                        st.session_state.refine_chat_open = False
                        st.session_state.refine_messages = []
                        st.rerun()

                    # Mostrar historial
                    for msg in refine_messages:
                        with st.chat_message(msg["role"]):
                            st.markdown(msg["content"])

                    # Chat input
                    user_input = st.chat_input(
                        t("refine_chat_placeholder"), key="refine_input"
                    )
                    if user_input:
                        st.session_state.refine_messages.append(
                            {"role": "user", "content": user_input}
                        )
                        with st.chat_message("user"):
                            st.markdown(user_input)

                        with st.chat_message("assistant"):
                            with st.spinner(t("chat_thinking")):
                                try:
                                    from ai_analyzer import (
                                        chat_with_advisor,
                                        REFINE_CHAT_SYSTEM_PROMPT,
                                    )
                                    sync_widgets_to_data(d)
                                    # Build analysis context summary
                                    analysis_ctx = (
                                        f"Score: {result.get('match_score', '?')}% | "
                                        f"Viable: {result.get('viable', '?')}\n"
                                        f"Missing keywords: {', '.join(result.get('missing_keywords', []))}\n"
                                        f"Matching keywords: {', '.join(result.get('matching_keywords', []))}"
                                    )
                                    vacancy_ctx = st.session_state.get(
                                        "vacancy_text", ""
                                    ).strip()
                                    reply = chat_with_advisor(
                                        d,
                                        st.session_state.refine_messages,
                                        st.session_state.ai_api_key,
                                        st.session_state.ai_model,
                                        vacancy_text=vacancy_ctx,
                                        system_prompt_override=REFINE_CHAT_SYSTEM_PROMPT,
                                        analysis_context=analysis_ctx,
                                    )
                                    st.markdown(reply)
                                    st.session_state.refine_messages.append(
                                        {"role": "assistant", "content": reply}
                                    )
                                except Exception as e:
                                    st.error(t("chat_error").format(str(e)))

                    # Botón: Re-analizar con lo aprendido
                    if (
                        refine_messages
                        and refine_messages[-1]["role"] == "assistant"
                    ):
                        if st.button(
                            "🔄 " + t("refine_reanalyze"), key="refine_reanalyze"
                        ):
                            try:
                                from ai_analyzer import analyze_vacancy
                                sync_widgets_to_data(d)
                                extra = "\n".join(
                                    m["content"]
                                    for m in refine_messages
                                    if m["role"] == "user"
                                )
                                vacancy_ctx = st.session_state.get(
                                    "vacancy_text", ""
                                ).strip()
                                with st.spinner(t("vacancy_analyzing")):
                                    new_result = analyze_vacancy(
                                        d,
                                        vacancy_ctx,
                                        st.session_state.ai_api_key,
                                        st.session_state.ai_model,
                                        extra_context=extra,
                                    )
                                st.session_state.analysis_result = (
                                    _sanitize_ai_result(new_result)
                                )
                                st.session_state._needs_widget_push = True
                                st.rerun()
                            except Exception as e:
                                st.error(t("vacancy_error").format(str(e)))
        else:
            st.info(t("ai_not_available"))

    # ══════════════════════════════════════════════════════════
    # TAB 2: EDICIÓN MANUAL DEL CV
    # ══════════════════════════════════════════════════════════
    with tab_manual:
        # ── Información Personal ─────────────────────────────
        st.header(t("personal_info"))
        c1, c2 = st.columns(2)
        with c1:
            d["name"] = st.text_input(
                t("full_name"), value=d.get("name", ""), key="f_name"
            )
            d["location"] = st.text_input(
                t("location"), value=d.get("location", ""), key="f_loc"
            )
            d["linkedin"] = st.text_input(
                t("linkedin"), value=d.get("linkedin", ""), key="f_li"
            )
            if not validate_linkedin(d["linkedin"]):
                st.warning(t("validation_linkedin"))
        with c2:
            d["phone"] = st.text_input(
                t("phone"), value=d.get("phone", ""), key="f_phone"
            )
            if not validate_phone(d["phone"]):
                st.warning(t("validation_phone"))
            d["email"] = st.text_input(
                t("email"), value=d.get("email", ""), key="f_email"
            )
            if not validate_email(d["email"]):
                st.warning(t("validation_email"))
            d["github"] = st.text_input(
                "GitHub", value=d.get("github", ""), key="f_gh"
            )

        # ── Resumen ──────────────────────────────────────────
        st.header(t("summary_header"))
        d["summary"] = st.text_area(
            t("summary_label"),
            value=d.get("summary", ""),
            height=100,
            key="f_summary",
        )

        # ── Experiencia Profesional ──────────────────────────
        st.header(t("experience_header"))

        exp_to_remove = None
        for i, exp in enumerate(d["experiences"]):
            eid = exp["id"]
            label = exp.get("company", "") or t("new_experience")
            title_hint = exp.get("title", "")
            with st.expander(
                f"**{label}** — {title_hint}" if title_hint else f"**{label}**",
                expanded=(i == 0),
            ):
                c1, c2 = st.columns(2)
                with c1:
                    exp["company"] = st.text_input(
                        t("company"), value=exp.get("company", ""),
                        key=f"x_co_{eid}",
                    )
                    exp["title"] = st.text_input(
                        t("job_title"), value=exp.get("title", ""),
                        key=f"x_ti_{eid}",
                    )
                with c2:
                    exp["location"] = st.text_input(
                        t("exp_location"), value=exp.get("location", ""),
                        key=f"x_lo_{eid}",
                    )
                    exp["dates"] = st.text_input(
                        t("period"), value=exp.get("dates", ""),
                        key=f"x_da_{eid}",
                    )

                exp["bullets"] = st.text_area(
                    t("bullets_label"),
                    value=exp.get("bullets", ""),
                    height=220,
                    key=f"x_bu_{eid}",
                )

                if st.button(t("delete_experience"), key=f"x_del_{eid}"):
                    exp_to_remove = i

        if exp_to_remove is not None:
            d["experiences"].pop(exp_to_remove)
            st.rerun()

        if st.button(t("add_experience")):
            d["experiences"].append({
                "id": uid(), "company": "", "title": "",
                "location": "", "dates": "", "bullets": "",
            })
            st.rerun()

        # ── Proyectos ─────────────────────────────────────────
        st.header(t("projects_header"))

        proj_to_remove = None
        for i, proj in enumerate(d.get("projects", [])):
            pid = proj["id"]
            label = proj.get("name", "") or f"Proyecto {i + 1}"
            with st.expander(f"**{label}**", expanded=True):
                c1, c2 = st.columns(2)
                with c1:
                    proj["name"] = st.text_input(
                        t("project_name"), value=proj.get("name", ""),
                        key=f"p_nm_{pid}",
                    )
                with c2:
                    proj["url"] = st.text_input(
                        t("project_url"), value=proj.get("url", ""),
                        key=f"p_ur_{pid}",
                    )
                proj["description"] = st.text_area(
                    t("project_description"),
                    value=proj.get("description", ""),
                    height=100,
                    key=f"p_ds_{pid}",
                )
                if st.button(t("delete_project"), key=f"p_del_{pid}"):
                    proj_to_remove = i

        if proj_to_remove is not None:
            d["projects"].pop(proj_to_remove)
            st.rerun()

        if st.button(t("add_project")):
            d.setdefault("projects", []).append({
                "id": uid(), "name": "", "url": "", "description": "",
            })
            st.rerun()

        # ── Educación ────────────────────────────────────────
        st.header(t("education_header"))

        edu_to_remove = None
        for i, edu in enumerate(d["education"]):
            eid = edu["id"]
            label = edu.get("institution", "") or t("new_institution")
            with st.expander(f"**{label}**", expanded=True):
                c1, c2 = st.columns(2)
                with c1:
                    edu["institution"] = st.text_input(
                        t("institution"), value=edu.get("institution", ""),
                        key=f"e_in_{eid}",
                    )
                    edu["degree"] = st.text_input(
                        t("degree"), value=edu.get("degree", ""),
                        key=f"e_de_{eid}",
                    )
                with c2:
                    edu["location"] = st.text_input(
                        t("edu_location"), value=edu.get("location", ""),
                        key=f"e_lo_{eid}",
                    )
                    edu["date"] = st.text_input(
                        t("date"), value=edu.get("date", ""),
                        key=f"e_dt_{eid}",
                    )
                edu["details"] = st.text_input(
                    t("details"),
                    value=edu.get("details", ""),
                    key=f"e_dz_{eid}",
                )

                if st.button(t("delete_education"), key=f"e_del_{eid}"):
                    edu_to_remove = i

        if edu_to_remove is not None:
            d["education"].pop(edu_to_remove)
            st.rerun()

        if st.button(t("add_education")):
            d["education"].append({
                "id": uid(), "institution": "", "degree": "",
                "details": "", "location": "", "date": "",
            })
            st.rerun()

        # ── Skills ───────────────────────────────────────────
        st.header(t("skills_header"))
        st.caption(t("skills_caption"))

        sk_to_remove = None
        for i, sk in enumerate(d["skills"]):
            sid = sk["id"]
            c1, c2 = st.columns([12, 1])
            with c1:
                sk["text"] = st.text_area(
                    f"Skill {i + 1}",
                    value=sk.get("text", ""),
                    height=72,
                    key=f"s_tx_{sid}",
                    label_visibility="collapsed",
                )
            with c2:
                st.write("")
                if st.button("🗑️", key=f"s_del_{sid}"):
                    sk_to_remove = i

        if sk_to_remove is not None:
            d["skills"].pop(sk_to_remove)
            st.rerun()

        if st.button(t("add_skill")):
            d["skills"].append({"id": uid(), "text": ""})
            st.rerun()


    # ══════════════════════════════════════════════════════════
    # TAB 3: CHAT ASESOR DE CV
    # ══════════════════════════════════════════════════════════
    with tab_chat:
        if not AI_AVAILABLE:
            st.info(t("ai_not_available"))
        elif not st.session_state.ai_api_key:
            st.warning(t("chat_need_api"))
        else:
            st.subheader(t("chat_header"))
            st.caption(t("chat_caption"))

            # Indicador de vacante cargada
            vacancy_ctx = st.session_state.get("vacancy_text", "").strip()
            if vacancy_ctx:
                st.info(t("chat_vacancy_loaded"))
            else:
                st.caption(t("chat_vacancy_none"))

            # Botón limpiar chat
            if st.button(t("chat_clear"), key="chat_clear_btn"):
                st.session_state.chat_messages = []
                st.session_state.chat_pending_patch = None
                st.rerun()

            # Mostrar historial
            for msg in st.session_state.chat_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            # Patch pendiente — mostrar preview
            patch = st.session_state.chat_pending_patch
            if patch:
                st.divider()
                st.subheader(t("chat_patch_preview"))
                st.markdown(f"**{t('chat_patch_field')}:** `{patch.get('field')}`")
                if patch.get("target_index") is not None:
                    st.markdown(f"**Index:** `{patch.get('target_index')}`")
                st.markdown(f"**{t('chat_patch_action')}:** `{patch.get('action', 'append')}`")
                st.text_area(
                    t("chat_patch_content"),
                    value=patch.get("content", ""),
                    height=120,
                    key="patch_content_preview",
                    disabled=True,
                )
                cp1, cp2 = st.columns(2)
                with cp1:
                    if st.button(t("chat_confirm_patch"), type="primary", key="patch_confirm"):
                        _apply_chat_patch(d, patch)
                        st.session_state._needs_widget_push = True
                        st.session_state.chat_pending_patch = None
                        st.toast(t("chat_patch_applied"))
                        st.rerun()
                with cp2:
                    if st.button(t("chat_discard_patch"), key="patch_discard"):
                        st.session_state.chat_pending_patch = None
                        st.toast(t("chat_patch_discarded"))
                        st.rerun()

            # Input del chat
            user_input = st.chat_input(t("chat_placeholder"))
            if user_input:
                st.session_state.chat_messages.append(
                    {"role": "user", "content": user_input}
                )
                with st.chat_message("user"):
                    st.markdown(user_input)

                with st.chat_message("assistant"):
                    with st.spinner(t("chat_thinking")):
                        try:
                            from ai_analyzer import chat_with_advisor
                            sync_widgets_to_data(d)
                            reply = chat_with_advisor(
                                d,
                                st.session_state.chat_messages,
                                st.session_state.ai_api_key,
                                st.session_state.ai_model,
                                vacancy_text=vacancy_ctx,
                            )
                            st.markdown(reply)
                            st.session_state.chat_messages.append(
                                {"role": "assistant", "content": reply}
                            )
                        except Exception as e:
                            st.error(t("chat_error").format(str(e)))

            # Botón aplicar última sugerencia
            if (
                st.session_state.chat_messages
                and st.session_state.chat_messages[-1]["role"] == "assistant"
                and not st.session_state.chat_pending_patch
            ):
                if st.button(t("chat_apply"), key="chat_apply_btn"):
                    with st.spinner(t("chat_extracting")):
                        try:
                            from ai_analyzer import extract_chat_patch
                            sync_widgets_to_data(d)
                            last_msg = st.session_state.chat_messages[-1]["content"]
                            patch = extract_chat_patch(
                                last_msg, d,
                                st.session_state.ai_api_key,
                                st.session_state.ai_model,
                            )
                            if patch:
                                st.session_state.chat_pending_patch = patch
                                st.rerun()
                            else:
                                st.warning(t("chat_no_patch"))
                        except Exception as e:
                            st.error(t("chat_error").format(str(e)))


    # ══════════════════════════════════════════════════════════
    # TAB 4: EVALUACIÓN DETALLADA
    # ══════════════════════════════════════════════════════════
    with tab_eval:
        _render_eval_tab(d)

    # ══════════════════════════════════════════════════════════
    # TAB 5: BANCO DE HABILIDADES Y PROYECTOS
    # ══════════════════════════════════════════════════════════
    with tab_banco:
        _render_banco_tab(d)


def _detect_vacancy_language(text: str) -> str:
    """Detecta si la vacante está en inglés o español con heurística simple."""
    en_markers = [" the ", " and ", " with ", " experience ", " years ",
                  " team ", " about ", " requirements ", " skills ",
                  " develop ", " work ", " you ", " our ", " will "]
    es_markers = [" los ", " las ", " con ", " experiencia ", " años ",
                  " equipo ", " acerca ", " requisitos ", " habilidades ",
                  " desarrollar ", " trabajo ", " usted ", " nuestro "]
    text_lower = f" {text.lower()} "
    en_count = sum(1 for w in en_markers if w in text_lower)
    es_count = sum(1 for w in es_markers if w in text_lower)
    return "en" if en_count > es_count else "es"


def _deferred_translate_and_reevaluate(d: dict):
    """Auto-traduce el CV si hay mismatch de idioma con la vacante, luego re-evalúa."""
    vacancy_text = st.session_state.get("vacancy_text", "").strip()
    if not vacancy_text or not st.session_state.get("ai_api_key"):
        return

    vacancy_lang = _detect_vacancy_language(vacancy_text)
    content_lang = st.session_state.get("content_lang", "es")

    # Auto-traducir si hay mismatch de idioma
    if vacancy_lang != content_lang and TRANSLATOR_AVAILABLE:
        try:
            translated = translate_cv_data(d, source=content_lang, target=vacancy_lang)
            st.session_state.cv = translated
            st.session_state.content_lang = vacancy_lang
            st.session_state.lang = vacancy_lang
            # Actualizar d para la re-evaluación
            for k, v in translated.items():
                d[k] = v
            push_data_to_widgets(d)
            st.toast(t("translate_success").format(LANG_NAMES.get(vacancy_lang, vacancy_lang)))
        except Exception as e:
            st.toast(f"Auto-translate error: {e}")

    # Re-evaluar con el CV actualizado (preservar extra_context del chat de refinamiento)
    try:
        from ai_analyzer import analyze_vacancy
        extra_context = ""
        refine_msgs = st.session_state.get("refine_messages", [])
        if refine_msgs:
            extra_context = "\n".join(
                m["content"] for m in refine_msgs if m["role"] == "user"
            )
        result = analyze_vacancy(
            d, vacancy_text,
            st.session_state.ai_api_key,
            st.session_state.ai_model,
            extra_context=extra_context,
        )
        st.session_state.analysis_result = _sanitize_ai_result(result)
        # Limpiar eval_result anterior porque el CV cambió
        st.session_state.eval_result = None
    except Exception as e:
        st.toast(f"Re-evaluation error: {e}")


def _render_score_navbar(d: dict):
    """Renderiza la barra superior con score, label de vacante y botón re-evaluar."""
    result = st.session_state.get("analysis_result")
    vacancy_text = st.session_state.get("vacancy_text", "").strip()

    nb1, nb2, nb3 = st.columns([1, 6, 2])

    with nb1:
        if result:
            score = result.get("match_score", 0)
            if score > 70:
                color = "#28a745"
            elif score >= 40:
                color = "#fd7e14"
            else:
                color = "#dc3545"
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<span style='font-size:2.2rem;font-weight:bold;color:{color};'>{score}%</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<span style='font-size:2.2rem;font-weight:bold;color:#888;'>{t('navbar_no_score')}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    with nb2:
        if vacancy_text:
            label = _html.escape(vacancy_text[:80].replace("\n", " "))
            st.markdown(f"<div style='padding-top:0.6rem;'>📋 {label}...</div>", unsafe_allow_html=True)
        else:
            st.markdown(
                f"<div style='padding-top:0.6rem;color:#888;'>{t('navbar_no_vacancy')}</div>",
                unsafe_allow_html=True,
            )

    with nb3:
        if vacancy_text and st.session_state.get("ai_api_key"):
            if st.button(t("navbar_reevaluate"), use_container_width=True, type="primary"):
                try:
                    from ai_analyzer import analyze_vacancy
                    sync_widgets_to_data(d)
                    extra_context = ""
                    refine_msgs = st.session_state.get("refine_messages", [])
                    if refine_msgs:
                        extra_context = "\n".join(
                            m["content"] for m in refine_msgs if m["role"] == "user"
                        )
                    with st.spinner(t("vacancy_analyzing")):
                        new_result = analyze_vacancy(
                            d, vacancy_text,
                            st.session_state.ai_api_key,
                            st.session_state.ai_model,
                            extra_context=extra_context,
                        )
                    st.session_state.analysis_result = _sanitize_ai_result(new_result)
                    st.rerun()
                except Exception as e:
                    st.error(t("vacancy_error").format(str(e)))

    st.divider()


def _render_eval_tab(d: dict):
    """Renderiza el contenido del tab de evaluación detallada."""
    st.subheader(t("eval_header"))

    vacancy_text = st.session_state.get("vacancy_text", "").strip()
    if not vacancy_text:
        st.info(t("eval_no_vacancy"))
        return

    if not st.session_state.get("ai_api_key"):
        st.warning(t("chat_need_api"))
        return

    if st.button(t("eval_generate"), type="primary"):
        try:
            from ai_analyzer import evaluate_cv_detailed
            sync_widgets_to_data(d)
            with st.spinner(t("eval_generating")):
                eval_result = evaluate_cv_detailed(
                    d, vacancy_text,
                    st.session_state.ai_api_key,
                    st.session_state.ai_model,
                )
            st.session_state.eval_result = eval_result
        except Exception as e:
            st.error(t("vacancy_error").format(str(e)))

    ev = st.session_state.eval_result
    if not ev:
        return

    # ── Score principal ──
    score = ev.get("overall_score", 0)
    label = ev.get("score_label", "")
    if score > 70:
        color = "#28a745"
    elif score >= 40:
        color = "#fd7e14"
    else:
        color = "#dc3545"

    st.markdown(
        f"<div style='text-align:center;margin:1rem 0;'>"
        f"<span style='font-size:3rem;font-weight:bold;color:{color};'>{score}%</span>"
        f"<br><span style='font-size:1.1rem;color:#666;'>{_html.escape(str(label))}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.divider()

    # ── Dimensiones ──
    dims = ev.get("dimensions", [])
    if dims:
        st.subheader(t("eval_dimensions"))
        for dim in dims:
            d_score = dim.get("score", 0)
            status = dim.get("status", "ok")
            emoji = "✅" if status == "ok" else ("⚠️" if status == "warn" else "❌")
            st.markdown(f"{emoji} **{dim.get('name', '')}** — {d_score}%")
            st.progress(min(d_score, 100) / 100)

    st.divider()

    # ── Requisitos ──
    reqs = ev.get("requirements", [])
    if reqs:
        st.subheader(t("eval_requirements"))
        for req in reqs:
            status = req.get("status", "ok")
            emoji = "✅" if status == "ok" else ("⚠️" if status == "warn" else "❌")
            st.markdown(f"{emoji} **{req.get('name', '')}**")
            if req.get("note"):
                st.caption(req["note"])

    st.divider()

    # ── Overfitting ──
    ovf = ev.get("overfitting", [])
    if ovf:
        st.subheader(t("eval_overfitting"))
        for item in ovf:
            severity = item.get("severity", "warn")
            claim = item.get("claim", "")
            reason = item.get("reason", "")
            if severity == "bad":
                st.error(f"**{claim}** — {reason}")
            else:
                st.warning(f"**{claim}** — {reason}")
    else:
        st.subheader(t("eval_overfitting"))
        st.success("No se detectaron problemas de overfitting.")

    st.divider()

    # ── Veredictos ──
    verdicts = ev.get("verdicts", [])
    if verdicts:
        st.subheader(t("eval_verdicts"))
        for v in verdicts:
            vtype = v.get("type", "ok")
            title = v.get("title", "")
            text = v.get("text", "")
            if vtype == "ok":
                st.success(f"**{title}**\n\n{text}")
            elif vtype == "warn":
                st.warning(f"**{title}**\n\n{text}")
            else:
                st.error(f"**{title}**\n\n{text}")


def _render_banco_tab(d: dict):
    """Renderiza el tab del Banco de Habilidades y Proyectos."""
    from banco import (
        load_banco, save_banco, migrate_from_config, bank_to_active_cv,
        count_bank_items, toggle_all, generate_bank_id,
    )

    banco = st.session_state.get("banco", {})

    # ── Si no hay banco, mostrar opción de importar ──
    if not banco or not banco.get("experiences"):
        st.info(t("banco_empty"))
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_personal.json")
        if os.path.exists(cfg_path):
            if st.button(t("banco_import"), type="primary"):
                banco = migrate_from_config(cfg_path)
                save_banco(banco)
                st.session_state.banco = banco
                st.session_state.cv = bank_to_active_cv(banco)
                st.session_state._needs_widget_push = True
                st.toast(t("banco_migrated"))
                st.rerun()
        return

    st.subheader(t("banco_header"))
    st.caption(t("banco_caption"))

    # ── Stats y botones principales ──
    total, active = count_bank_items(banco)

    col_stats, col_all, col_none, col_save = st.columns([4, 2, 2, 2])
    with col_stats:
        st.markdown(f"**{t('banco_item_count').format(active, total)}**")
    with col_all:
        if st.button(t("banco_toggle_all"), use_container_width=True):
            toggle_all(banco, True)
            save_banco(banco)
            st.rerun()
    with col_none:
        if st.button(t("banco_deactivate_all"), use_container_width=True):
            toggle_all(banco, False)
            save_banco(banco)
            st.rerun()
    with col_save:
        if st.button(t("banco_save"), type="primary", use_container_width=True):
            save_banco(banco)
            st.toast(t("banco_saved"))

    # ── Resúmenes ──
    with st.expander(t("banco_summaries"), expanded=False):
        for s in banco.get("summaries", []):
            cols = st.columns([1, 11])
            with cols[0]:
                new_val = st.checkbox("on", value=s.get("active", True), key=f"bk_{s['id']}", label_visibility="collapsed")
                if new_val != s.get("active", True):
                    s["active"] = new_val
            with cols[1]:
                label = _html.escape(s.get("label", "Sin label"))
                preview = _html.escape(s["text"][:120] + ("..." if len(s["text"]) > 120 else ""))
                style = "" if s.get("active", True) else "opacity:0.4;"
                st.markdown(f"<div style='{style}'><b>{label}</b><br><small>{preview}</small></div>",
                            unsafe_allow_html=True)

    # ── Experiencias con bullets ──
    with st.expander(t("banco_experiences"), expanded=True):
        for exp in banco.get("experiences", []):
            exp_active = st.checkbox(
                f"**{exp.get('company', '')}** — {exp.get('title', '')}",
                value=exp.get("active", True),
                key=f"bk_{exp['id']}",
            )
            if exp_active != exp.get("active", True):
                exp["active"] = exp_active

            if exp.get("active", True):
                for bul in exp.get("bullets", []):
                    cols = st.columns([1, 9, 2])
                    with cols[0]:
                        bul_active = st.checkbox("on", value=bul.get("active", True), key=f"bk_{bul['id']}", label_visibility="collapsed")
                        if bul_active != bul.get("active", True):
                            bul["active"] = bul_active
                    with cols[1]:
                        preview = _html.escape(bul["text"][:100] + ("..." if len(bul["text"]) > 100 else ""))
                        style = "" if bul.get("active", True) else "opacity:0.4;text-decoration:line-through;"
                        st.markdown(f"<div style='{style}'>{preview}</div>", unsafe_allow_html=True)
                    with cols[2]:
                        tags = bul.get("tags", [])
                        if tags:
                            st.caption(" ".join(f"`{tg}`" for tg in tags))

    # ── Proyectos ──
    with st.expander(t("banco_projects"), expanded=False):
        for proj in banco.get("projects", []):
            cols = st.columns([1, 9, 2])
            with cols[0]:
                new_val = st.checkbox("on", value=proj.get("active", True), key=f"bk_{proj['id']}", label_visibility="collapsed")
                if new_val != proj.get("active", True):
                    proj["active"] = new_val
            with cols[1]:
                style = "" if proj.get("active", True) else "opacity:0.4;"
                st.markdown(
                    f"<div style='{style}'><b>{_html.escape(proj.get('name', ''))}</b><br>"
                    f"<small>{_html.escape(proj.get('description', '')[:100])}...</small></div>",
                    unsafe_allow_html=True,
                )
            with cols[2]:
                tags = proj.get("tags", [])
                if tags:
                    st.caption(" ".join(f"`{tg}`" for tg in tags))

    # ── Skills ──
    with st.expander(t("banco_skills"), expanded=False):
        for sk in banco.get("skills", []):
            cols = st.columns([1, 11])
            with cols[0]:
                new_val = st.checkbox("on", value=sk.get("active", True), key=f"bk_{sk['id']}", label_visibility="collapsed")
                if new_val != sk.get("active", True):
                    sk["active"] = new_val
            with cols[1]:
                style = "" if sk.get("active", True) else "opacity:0.4;"
                st.markdown(f"<div style='{style}'>{_html.escape(sk['text'][:150])}</div>", unsafe_allow_html=True)

    # ── Educación ──
    with st.expander(t("banco_education"), expanded=False):
        for edu in banco.get("education", []):
            cols = st.columns([1, 11])
            with cols[0]:
                new_val = st.checkbox("on", value=edu.get("active", True), key=f"bk_{edu['id']}", label_visibility="collapsed")
                if new_val != edu.get("active", True):
                    edu["active"] = new_val
            with cols[1]:
                style = "" if edu.get("active", True) else "opacity:0.4;"
                st.markdown(
                    f"<div style='{style}'><b>{_html.escape(edu.get('institution', ''))}</b> — "
                    f"{_html.escape(edu.get('degree', ''))}</div>",
                    unsafe_allow_html=True,
                )

    st.divider()

    # ── Aplicar selección al CV ──
    if st.button(t("banco_apply"), type="primary", use_container_width=True):
        save_banco(banco)
        st.session_state.cv = bank_to_active_cv(banco)
        st.session_state._needs_widget_push = True
        st.toast(t("banco_applied"))
        st.rerun()


def _apply_chat_patch(data: dict, patch: dict):
    """Aplica un patch del chat asesor al diccionario del CV."""
    field = patch.get("field")
    idx = patch.get("target_index", 0) or 0
    action = patch.get("action", "append")
    content = patch.get("content", "")

    if field == "summary":
        if action == "replace":
            data["summary"] = content
        else:
            data["summary"] = data.get("summary", "") + "\n" + content

    elif field == "experience_bullet":
        exps = data.get("experiences", [])
        if 0 <= idx < len(exps):
            if action == "replace":
                exps[idx]["bullets"] = content
            else:
                current = exps[idx].get("bullets", "").rstrip()
                exps[idx]["bullets"] = current + "\n" + content if current else content

    elif field == "experience_title":
        exps = data.get("experiences", [])
        if 0 <= idx < len(exps):
            exps[idx]["title"] = content

    elif field == "skill_line":
        skills = data.get("skills", [])
        if 0 <= idx < len(skills):
            if action == "replace":
                skills[idx]["text"] = content
            else:
                skills[idx]["text"] = skills[idx].get("text", "") + ", " + content

    elif field == "project_description":
        projs = data.get("projects", [])
        if 0 <= idx < len(projs):
            if action == "replace":
                projs[idx]["description"] = content
            else:
                current = projs[idx].get("description", "").rstrip()
                projs[idx]["description"] = current + "\n" + content if current else content

    elif field == "project_new":
        data.setdefault("projects", []).append({
            "id": uid(), "name": content, "url": "", "description": "",
        })


if __name__ == "__main__":
    main()
