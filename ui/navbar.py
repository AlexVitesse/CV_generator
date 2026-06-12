"""
Navbar de score y vacante.
"""

import html as _html
import logging

import streamlit as st

from helpers import safe_html, get_score_color
from i18n import t

logger = logging.getLogger("ui")


def render_score_navbar(d: dict):
    """Renderiza la barra superior con score, label de vacante y botón re-evaluar."""
    result = st.session_state.get("analysis_result")
    vacancy_text = st.session_state.get("vacancy_text", "").strip()

    nb1, nb2, nb3 = st.columns([1, 6, 2])

    with nb1:
        if result:
            score = result.get("match_score", 0)
            color = get_score_color(score)
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
            label = safe_html(vacancy_text[:80].replace("\n", " "))
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
                    from helpers import sync_widgets_to_data, sanitize_ai_result
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
                    st.session_state.analysis_result = sanitize_ai_result(new_result, d)
                    st.rerun()
                except Exception as e:
                    logger.exception("Re-evaluate error")
                    st.error(t("vacancy_error").format(str(e)))

    st.divider()
