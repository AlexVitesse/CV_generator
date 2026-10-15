"""
Tab del chat asesor de CV.
"""

import logging

import streamlit as st

from helpers import sync_widgets_to_data, apply_chat_patch, _resolve_patch_index
from i18n import t
from ai_analyzer import AI_AVAILABLE

logger = logging.getLogger("ui")


import session_keys as sk


def render_chat_tab(d: dict):
    if not AI_AVAILABLE:
        st.info(t("ai_not_available"))
        return
    if not st.session_state[sk.AI_API_KEY]:
        st.warning(t("chat_need_api"))
        return

    st.subheader(t("chat_header"))
    st.caption(t("chat_caption"))

    # Indicador de vacante cargada
    vacancy_ctx = st.session_state.get(sk.VACANCY_TEXT, "").strip()
    if vacancy_ctx:
        st.info(t("chat_vacancy_loaded"))
    else:
        st.caption(t("chat_vacancy_none"))

    # Botón limpiar chat
    if st.button(t("chat_clear"), key="chat_clear_btn"):
        st.session_state[sk.CHAT_MESSAGES] = []
        st.session_state[sk.CHAT_PENDING_PATCH] = None
        st.rerun()

    # Mostrar historial
    for msg in st.session_state[sk.CHAT_MESSAGES]:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.write(msg["content"])
            else:
                st.markdown(msg["content"])

    # Patch pendiente — mostrar preview
    patch = st.session_state[sk.CHAT_PENDING_PATCH]
    if patch:
        st.divider()
        st.subheader(t("chat_patch_preview"))
        st.markdown(f"**{t('chat_patch_field')}:** `{patch.get('field')}`")
        # Mostrar el destino real (empresa/proyecto) resuelto por id, para que el
        # usuario verifique que el patch cae en el ítem correcto (no en otra empresa).
        _field = patch.get("field")
        _list_key = {"experience_bullet": "experiences", "experience_title": "experiences",
                     "project_description": "projects", "skill_line": "skills"}.get(_field)
        if _list_key:
            _items = d.get(_list_key, [])
            _ti = _resolve_patch_index(patch, _items)
            if 0 <= _ti < len(_items):
                _it = _items[_ti]
                _label = _it.get("company") or _it.get("name") or _it.get("text", "")[:40] or f"#{_ti}"
                st.markdown(f"**Destino:** `{_label}`")
        elif patch.get("target_index") is not None:
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
                apply_chat_patch(d, patch)
                st.session_state[sk.NEEDS_WIDGET_PUSH] = True
                st.session_state[sk.CHAT_PENDING_PATCH] = None
                st.toast(t("chat_patch_applied"))
                st.rerun()
        with cp2:
            if st.button(t("chat_discard_patch"), key="patch_discard"):
                st.session_state[sk.CHAT_PENDING_PATCH] = None
                st.toast(t("chat_patch_discarded"))
                st.rerun()

    # Input del chat
    user_input = st.chat_input(t("chat_placeholder"))
    if user_input:
        st.session_state[sk.CHAT_MESSAGES].append(
            {"role": "user", "content": user_input}
        )
        with st.chat_message("user"):
            st.write(user_input)

        with st.chat_message("assistant"):
            with st.spinner(t("chat_thinking")):
                try:
                    from ai_analyzer import chat_with_advisor
                    sync_widgets_to_data(d)
                    reply = chat_with_advisor(
                        d,
                        st.session_state[sk.CHAT_MESSAGES],
                        st.session_state[sk.AI_API_KEY],
                        st.session_state[sk.AI_MODEL],
                        vacancy_text=vacancy_ctx,
                        provider=st.session_state.get(sk.AI_PROVIDER),
                    )
                    st.markdown(reply)
                    st.session_state[sk.CHAT_MESSAGES].append(
                        {"role": "assistant", "content": reply}
                    )
                except Exception as e:
                    logger.exception("Chat error")
                    st.error(t("chat_error").format(str(e)))

    # Botón aplicar última sugerencia
    if (
        st.session_state[sk.CHAT_MESSAGES]
        and st.session_state[sk.CHAT_MESSAGES][-1]["role"] == "assistant"
        and not st.session_state[sk.CHAT_PENDING_PATCH]
    ):
        if st.button(t("chat_apply"), key="chat_apply_btn"):
            with st.spinner(t("chat_extracting")):
                try:
                    from ai_analyzer import extract_chat_patch
                    sync_widgets_to_data(d)
                    last_msg = st.session_state[sk.CHAT_MESSAGES][-1]["content"]
                    patch = extract_chat_patch(
                        last_msg, d,
                        st.session_state[sk.AI_API_KEY],
                        st.session_state[sk.AI_MODEL],
                        provider=st.session_state.get(sk.AI_PROVIDER),
                    )
                    if patch:
                        st.session_state[sk.CHAT_PENDING_PATCH] = patch
                        st.rerun()
                    else:
                        st.warning(t("chat_no_patch"))
                except Exception as e:
                    logger.exception("Extract patch error")
                    st.error(t("chat_error").format(str(e)))
