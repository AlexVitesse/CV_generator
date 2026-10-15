"""
Tab de evaluación detallada del CV.
"""

import logging

import streamlit as st

from helpers import sync_widgets_to_data, safe_html, get_score_color
from i18n import t

logger = logging.getLogger("ui")


def render_eval_tab(d: dict):
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
                    provider=st.session_state.get("ai_provider"),
                )
            st.session_state.eval_result = eval_result
        except Exception as e:
            logger.exception("Eval error")
            st.error(t("vacancy_error").format(str(e)))

    ev = st.session_state.eval_result
    if not ev:
        return

    # ── Score principal ──
    score = ev.get("overall_score", 0)
    label = ev.get("score_label", "")
    color = get_score_color(score)

    st.markdown(
        f"<div style='text-align:center;margin:1rem 0;'>"
        f"<span style='font-size:3rem;font-weight:bold;color:{color};'>{score}%</span>"
        f"<br><span style='font-size:1.1rem;color:#666;'>{safe_html(str(label))}</span>"
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
