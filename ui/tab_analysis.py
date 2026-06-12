"""
Tab de análisis de vacante y chat de refinamiento inline.
"""

import json
import logging

import httpx
import streamlit as st

from helpers import sync_widgets_to_data, push_data_to_widgets, sanitize_ai_result
from i18n import t
from ai_analyzer import AI_AVAILABLE

logger = logging.getLogger("ui")


import session_keys as sk


def render_analysis_tab(d: dict):
    if not AI_AVAILABLE:
        st.info(t("ai_not_available"))
        return

    # Mostrar confirmación si se acaba de aplicar
    if st.session_state.get(sk.CV_ADAPTED):
        st.success(t("vacancy_applied"))
        del st.session_state[sk.CV_ADAPTED]

    vacancy_text = st.text_area(
        t("vacancy_placeholder"),
        height=200,
        key=sk.VACANCY_TEXT,
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

                # Fase 1: Analizar con TODO el banco/CV completo
                banco = st.session_state.get(sk.BANCO)
                d_full = d
                if banco and banco.get("experiences"):
                    from banco import bank_to_active_cv as _b2cv
                    from banco import toggle_all as _toggle_all, save_banco
                    _toggle_all(banco, True)
                    d_full = _b2cv(banco)

                with st.spinner(t("vacancy_analyzing")):
                    result = analyze_vacancy(
                        d_full, vacancy_text,
                        st.session_state[sk.AI_API_KEY],
                        st.session_state[sk.AI_MODEL],
                    )
                st.session_state[sk.ANALYSIS_RESULT] = sanitize_ai_result(result, d_full)

                # Fase 2: Seleccionar items óptimos del banco para CV de 1 página
                if banco and banco.get("experiences"):
                    from ai_analyzer import select_from_bank
                    from banco import get_bank_manifest, apply_ai_selection, bank_to_active_cv
                    with st.spinner(t("banco_selecting")):
                        manifest = get_bank_manifest(banco)
                        selected_ids = select_from_bank(
                            manifest, vacancy_text,
                            st.session_state[sk.AI_API_KEY],
                            st.session_state[sk.AI_MODEL],
                        )
                        apply_ai_selection(banco, selected_ids)
                        save_banco(banco)
                        d = bank_to_active_cv(banco)
                        st.session_state[sk.CV] = d

                st.session_state[sk.NEEDS_WIDGET_PUSH] = True
                st.rerun()
            except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError) as e:
                logger.exception("Analysis error")
                st.error(t("vacancy_error").format(str(e)))

    # ── Mostrar resultados ────────────────────────────
    result = st.session_state[sk.ANALYSIS_RESULT]
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

        # ── Diff Viewer de sugerencias (MEJ-05) ──────────
        from ui.diff_viewer import render_suggestions_diff
        render_suggestions_diff(d, result)

        # ── Chat de refinamiento inline ──────────────────
        render_refine_chat(d, result)


# ═══════════════════════════════════════════════════════════════
# CHAT DE REFINAMIENTO INLINE (dentro del tab de análisis)
# ═══════════════════════════════════════════════════════════════

def render_refine_chat(d: dict, result: dict):
    st.divider()
    refine_messages = st.session_state.get(sk.REFINE_MESSAGES, [])

    if not st.session_state.get(sk.REFINE_CHAT_OPEN):
        if st.button("💬 " + t("refine_chat_open"), key="refine_open"):
            st.session_state[sk.REFINE_CHAT_OPEN] = True
            st.session_state[sk.REFINE_MESSAGES] = []
            st.rerun()
        return

    st.subheader(t("refine_chat_header"))
    st.caption(t("refine_chat_caption"))

    if st.button(t("refine_chat_close"), key="refine_close"):
        st.session_state[sk.REFINE_CHAT_OPEN] = False
        st.session_state[sk.REFINE_MESSAGES] = []
        st.rerun()

    # Mostrar historial
    for msg in refine_messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.write(msg["content"])
            else:
                st.markdown(msg["content"])

    # Chat input
    user_input = st.chat_input(
        t("refine_chat_placeholder"), key="refine_input"
    )
    if user_input:
        st.session_state[sk.REFINE_MESSAGES].append(
            {"role": "user", "content": user_input}
        )
        with st.chat_message("user"):
            st.write(user_input)

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
                        sk.VACANCY_TEXT, ""
                    ).strip()
                    reply = chat_with_advisor(
                        d,
                        st.session_state[sk.REFINE_MESSAGES],
                        st.session_state[sk.AI_API_KEY],
                        st.session_state[sk.AI_MODEL],
                        vacancy_text=vacancy_ctx,
                        system_prompt_override=REFINE_CHAT_SYSTEM_PROMPT,
                        analysis_context=analysis_ctx,
                    )
                    st.markdown(reply)
                    st.session_state[sk.REFINE_MESSAGES].append(
                        {"role": "assistant", "content": reply}
                    )
                except Exception as e:
                    logger.exception("Refine chat error")
                    st.error(t("chat_error").format(str(e)))

    # Botón: Re-analizar con lo aprendido
    if refine_messages and refine_messages[-1]["role"] == "assistant":
        if st.button("🔄 " + t("refine_reanalyze"), key="refine_reanalyze"):
            try:
                from ai_analyzer import analyze_vacancy
                sync_widgets_to_data(d)
                extra = "\n".join(
                    m["content"]
                    for m in refine_messages
                    if m["role"] == "user"
                )
                vacancy_ctx = st.session_state.get(sk.VACANCY_TEXT, "").strip()
                with st.spinner(t("vacancy_analyzing")):
                    new_result = analyze_vacancy(
                        d,
                        vacancy_ctx,
                        st.session_state[sk.AI_API_KEY],
                        st.session_state[sk.AI_MODEL],
                        extra_context=extra,
                    )
                st.session_state[sk.ANALYSIS_RESULT] = sanitize_ai_result(new_result, d)
                st.session_state[sk.NEEDS_WIDGET_PUSH] = True
                st.rerun()
            except Exception as e:
                logger.exception("Re-analysis error")
                st.error(t("vacancy_error").format(str(e)))
