"""
Tab del banco de habilidades y proyectos.
"""

import os

import streamlit as st

from helpers import safe_html
from i18n import t


def render_banco_tab(d: dict):
    """Renderiza el tab del Banco de Habilidades y Proyectos."""
    from banco import (
        load_banco, save_banco, migrate_from_config, bank_to_active_cv,
        count_bank_items, toggle_all, generate_bank_id,
    )

    banco = st.session_state.get("banco", {})

    # ── Si no hay banco, mostrar opción de importar ──
    if not banco or not banco.get("experiences"):
        st.info(t("banco_empty"))
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config_personal.json")
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
                label = safe_html(s.get("label", "Sin label"))
                preview = safe_html(s["text"][:120] + ("..." if len(s["text"]) > 120 else ""))
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
                        preview = safe_html(bul["text"][:100] + ("..." if len(bul["text"]) > 100 else ""))
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
                    f"<div style='{style}'><b>{safe_html(proj.get('name', ''))}</b><br>"
                    f"<small>{safe_html(proj.get('description', '')[:100])}...</small></div>",
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
                st.markdown(f"<div style='{style}'>{safe_html(sk['text'][:150])}</div>", unsafe_allow_html=True)

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
                    f"<div style='{style}'><b>{safe_html(edu.get('institution', ''))}</b> — "
                    f"{safe_html(edu.get('degree', ''))}</div>",
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
