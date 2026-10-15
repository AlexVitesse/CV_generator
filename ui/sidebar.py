"""
Sidebar del CV Generator.
"""

import json
import logging
import os
import re

import streamlit as st

logger = logging.getLogger("ui")

from helpers import (
    uid, clear_keys, sync_widgets_to_data, push_data_to_widgets,
    default_cv_data,
)
from i18n import LANG_NAMES, t
from translate import TRANSLATOR_AVAILABLE, translate_cv_data
from pdf import generate_cv_pdf
from ai_analyzer import AI_AVAILABLE
from validation import parse_cv
import session_keys as sk


def render_sidebar(d: dict):
    with st.sidebar:
        # ── Selector de idioma de interfaz ───────────────────
        st.subheader(t("language"))
        lang_options = {"es": "🇲🇽 Español", "en": "🇺🇸 English"}
        current_idx = 0 if st.session_state[sk.LANG] == "es" else 1
        selected_lang = st.radio(
            t("language"),
            options=list(lang_options.keys()),
            format_func=lambda x: lang_options[x],
            index=current_idx,
            horizontal=True,
            label_visibility="collapsed",
        )
        if selected_lang != st.session_state[sk.LANG]:
            st.session_state[sk.LANG] = selected_lang
            st.rerun()

        st.divider()

        # ── Traducción automática del contenido ──────────────
        st.subheader("🔄 Traducción automática")

        current_content = st.session_state[sk.CONTENT_LANG]
        target_lang = "en" if current_content == "es" else "es"
        target_name = LANG_NAMES[target_lang]

        content_label = (
            f"Contenido actual: **{LANG_NAMES[current_content]}**"
            if st.session_state[sk.LANG] == "es"
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
                        api_key=st.session_state.get(sk.AI_API_KEY),
                        model=st.session_state.get(sk.AI_MODEL),
                        provider=st.session_state.get(sk.AI_PROVIDER),
                    )

                    progress_bar.progress(1.0, text="✅")

                    st.session_state[sk.CV] = translated
                    st.session_state[sk.CONTENT_LANG] = target_lang
                    st.session_state[sk.LANG] = target_lang

                    st.session_state[sk.NEEDS_WIDGET_PUSH] = True
                    st.toast(t("translate_success").format(target_name))
                    st.rerun()
                except Exception as e:
                    logger.exception("Translate error")
                    st.error(t("translate_error").format(str(e)))
        else:
            st.warning(t("translate_missing"))

        st.divider()

        # ── Generar PDF ──────────────────────────────────────
        st.header(t("actions"))

        if st.button(t("generate_pdf"), type="primary",
                     use_container_width=True):
            try:
                pdf_buf, cabe, escala = generate_cv_pdf(d)  # títulos en el idioma del contenido
                st.session_state[sk.PDF_BYTES] = pdf_buf.getvalue()
                if not cabe:
                    st.warning(t("pdf_no_fit"))
                elif escala < 1.0:
                    st.warning(t("pdf_shrunk").format(int(escala * 100)))
                else:
                    st.success(t("pdf_success"))
            except Exception as e:
                logger.exception("PDF generation error")
                st.error(t("pdf_error").format(e))

        # ── Empresa destino (siempre visible para nombre PDF + cover letter) ──
        _company_raw = st.text_input(
            t("target_company"),
            key="target_company_input",
            placeholder="Ej: Excelia",
        )
        if _company_raw:
            st.session_state[sk.TARGET_COMPANY] = _company_raw

        if sk.PDF_BYTES in st.session_state:
            lang_suffix = st.session_state[sk.LANG].upper()
            _name = d.get("name", "")
            _initials = "".join(w[0] for w in _name.split() if w).upper() if _name else "XX"
            _co = st.session_state.get(sk.TARGET_COMPANY, "")
            _company = re.sub(r'[^\w]', '', _co).strip() if _co else ""
            _pdf_name = f"CV_{_initials}_{_company}.pdf" if _company else f"CV_{_initials}_{lang_suffix}.pdf"
            st.download_button(
                t("download_pdf"),
                data=st.session_state[sk.PDF_BYTES],
                file_name=_pdf_name,
                mime="application/pdf",
                use_container_width=True,
            )

        # ── Summary y Cover Letter ────────────────────────
        if AI_AVAILABLE and st.session_state.get(sk.AI_API_KEY):
            st.divider()
            sc1, sc2 = st.columns(2)
            with sc1:
                if st.button(t("generate_summary"), use_container_width=True):
                    try:
                        from ai_analyzer import generate_text, SUMMARY_SYSTEM_PROMPT
                        sync_widgets_to_data(d)
                        lang_name = "español" if st.session_state[sk.CONTENT_LANG] == "es" else "English"
                        vacancy_ctx = st.session_state.get(sk.VACANCY_TEXT, "").strip()
                        with st.spinner(t("summary_generating")):
                            summary = generate_text(
                                d,
                                st.session_state[sk.AI_API_KEY],
                                st.session_state[sk.AI_MODEL],
                                SUMMARY_SYSTEM_PROMPT.format(lang=lang_name),
                                f"Genera un summary/elevator pitch en {lang_name}.",
                                vacancy_text=vacancy_ctx,
                                provider=st.session_state.get(sk.AI_PROVIDER),
                            )
                        st.session_state[sk.GENERATED_SUMMARY] = summary
                    except Exception as e:
                        logger.exception("Summary generation error")
                        st.error(str(e))
            with sc2:
                if st.button(t("generate_cover"), use_container_width=True):
                    _co = st.session_state.get(sk.TARGET_COMPANY, "").strip()
                    vacancy_ctx = st.session_state.get(sk.VACANCY_TEXT, "").strip()
                    if not _co:
                        st.warning(t("cover_no_company"))
                    elif not vacancy_ctx:
                        st.warning(t("cover_no_vacancy"))
                    else:
                        try:
                            from ai_analyzer import generate_text, COVER_LETTER_SYSTEM_PROMPT
                            sync_widgets_to_data(d)
                            lang_name = "español" if st.session_state[sk.CONTENT_LANG] == "es" else "English"
                            with st.spinner(t("cover_generating")):
                                cover = generate_text(
                                    d,
                                    st.session_state[sk.AI_API_KEY],
                                    st.session_state[sk.AI_MODEL],
                                    COVER_LETTER_SYSTEM_PROMPT.format(lang=lang_name),
                                    f"Genera una cover letter en {lang_name} para la empresa {_co}.",
                                    vacancy_text=vacancy_ctx,
                                    provider=st.session_state.get(sk.AI_PROVIDER),
                                )
                            st.session_state[sk.GENERATED_COVER] = cover
                        except Exception as e:
                            logger.exception("Cover letter generation error")
                            st.error(str(e))

            # Mostrar summary generado (st.code tiene botón copiar nativo)
            if st.session_state.get(sk.GENERATED_SUMMARY):
                st.caption("Summary")
                st.code(st.session_state[sk.GENERATED_SUMMARY], language=None)

            # Mostrar cover letter generada
            if st.session_state.get(sk.GENERATED_COVER):
                st.caption(t("cover_result"))
                st.code(st.session_state[sk.GENERATED_COVER], language=None)

        st.divider()
        st.subheader(t("data_section"))

        uploaded = st.file_uploader(t("import_json"), type=["json"])
        if uploaded is not None:
            try:
                imported = json.load(uploaded)
                # Validación/normalización Pydantic
                imported, issues = parse_cv(imported)
                st.session_state[sk.CV] = imported
                st.session_state[sk.CONTENT_LANG] = "es"
                clear_keys("x_", "p_", "e_", "s_", "f_", "c_tx_", "c_cid_")
                st.success(t("import_success"))
                for field in issues:
                    st.warning(t(f"validation_{field}"))
                st.rerun()
            except Exception as e:
                logger.exception("Import JSON error")
                st.error(f"Error: {e}")

        st.divider()

        if st.button(t("clean_vacancy"), use_container_width=True):
            if sk.VACANCY_TEXT in st.session_state:
                st.session_state[sk.VACANCY_TEXT] = ""
            st.session_state[sk.ANALYSIS_RESULT] = None
            st.session_state[sk.EVAL_RESULT] = None
            st.session_state[sk.CHAT_MESSAGES] = []
            st.session_state[sk.CHAT_PENDING_PATCH] = None
            st.session_state[sk.REFINE_MESSAGES] = []
            if sk.GENERATED_SUMMARY in st.session_state:
                st.session_state[sk.GENERATED_SUMMARY] = ""
            if sk.GENERATED_COVER in st.session_state:
                st.session_state[sk.GENERATED_COVER] = ""
            st.toast("✨ Datos de vacante y análisis limpiados.")
            st.rerun()

        if st.button(t("restore_example"), use_container_width=True):
            st.session_state[sk.CV] = default_cv_data()
            st.session_state[sk.CONTENT_LANG] = "es"
            st.session_state[sk.LANG] = "es"
            clear_keys("x_", "p_", "e_", "s_", "f_")
            st.rerun()

        # ── Configuración IA ─────────────────────────────────
        st.divider()
        st.subheader(t("ai_config_header"))

        if AI_AVAILABLE:
            from ai_analyzer import save_ai_config
            from llm_client import PROVIDERS, PROVIDER_LABELS, DEFAULT_MODELS, DEFAULT_PROVIDER, MODEL_OPTIONS

            providers_cfg = st.session_state.setdefault(sk.AI_PROVIDERS, {})
            cur_provider = st.session_state.get(sk.AI_PROVIDER) or DEFAULT_PROVIDER

            # ── Selector de proveedor (Ollama / OpenAI / Anthropic / Gemini) ──
            sel_provider = st.selectbox(
                t("ai_provider"),
                options=list(PROVIDERS),
                index=list(PROVIDERS).index(cur_provider) if cur_provider in PROVIDERS else 0,
                format_func=lambda p: PROVIDER_LABELS.get(p, p),
            )
            # Los inputs usan key explícita para poder leer lo que el usuario tenga
            # escrito (incluso a medio editar) en el momento de cambiar de proveedor.
            if "ai_key_input" not in st.session_state:
                st.session_state["ai_key_input"] = st.session_state[sk.AI_API_KEY]
                st.session_state["ai_model_input"] = (
                    st.session_state[sk.AI_MODEL] or DEFAULT_MODELS[cur_provider]
                )

            if sel_provider != cur_provider:
                # Guardado defensivo: persistir lo que esté escrito para el proveedor ACTUAL
                # ANTES de cambiar, así nunca se pierde una key recién tecleada.
                pend_key = st.session_state.get("ai_key_input", st.session_state[sk.AI_API_KEY])
                pend_model = st.session_state.get("ai_model_input", st.session_state[sk.AI_MODEL])
                providers_cfg[cur_provider] = {"api_key": pend_key, "model": pend_model}
                save_ai_config(cur_provider, pend_key, pend_model)

                # Cargar las credenciales guardadas del proveedor elegido (sin perder las otras).
                saved = providers_cfg.get(sel_provider, {})
                new_active_key = saved.get("api_key", "")
                new_active_model = saved.get("model") or DEFAULT_MODELS[sel_provider]
                st.session_state[sk.AI_PROVIDER] = sel_provider
                st.session_state[sk.AI_API_KEY] = new_active_key
                st.session_state[sk.AI_MODEL] = new_active_model
                # Persistir también el proveedor ACTIVO nuevo: si no, .ai_config.json
                # sigue apuntando al anterior hasta que el usuario edite key/modelo, y al
                # reiniciar la app revierte silenciosamente al proveedor viejo (Ollama).
                save_ai_config(sel_provider, new_active_key, new_active_model)
                # Re-sembrar los widgets para que muestren los valores del nuevo proveedor.
                st.session_state["ai_key_input"] = new_active_key
                st.session_state["ai_model_input"] = new_active_model
                st.rerun()

            new_key = st.text_input(t("ai_api_key"), type="password", key="ai_key_input")
            # Lista sugerida + cualquier id escrito a mano (accept_new_options). El valor
            # actual se incluye siempre: si fuera personalizado y no estuviera, el widget fallaría.
            notes = MODEL_OPTIONS.get(sel_provider, {})
            model_opts = list(notes)
            if st.session_state["ai_model_input"] not in model_opts:
                model_opts.insert(0, st.session_state["ai_model_input"])
            new_model = st.selectbox(
                t("ai_model"), options=model_opts, key="ai_model_input",
                accept_new_options=True, help=t("ai_model_help"),
                format_func=lambda m: f"{m} — {notes[m]}" if notes.get(m) else m,
            )
            # Guardar si cambió (por proveedor)
            if new_key != st.session_state[sk.AI_API_KEY] or new_model != st.session_state[sk.AI_MODEL]:
                st.session_state[sk.AI_API_KEY] = new_key
                st.session_state[sk.AI_MODEL] = new_model
                providers_cfg[sel_provider] = {"api_key": new_key, "model": new_model}
                save_ai_config(sel_provider, new_key, new_model)
        else:
            st.warning(t("ai_not_available"))

        # ── Guardar CV al banco ────────────────────────────
        if st.session_state.get(sk.BANCO):
            st.divider()
            if st.button(t("banco_save_cv"), use_container_width=True):
                from banco import merge_cv_to_bank, save_banco
                sync_widgets_to_data(d)
                merge_cv_to_bank(d, st.session_state[sk.BANCO])
                save_banco(st.session_state[sk.BANCO])
                st.toast(t("banco_saved_to_bank"))
