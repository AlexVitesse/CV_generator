"""
╔══════════════════════════════════════════════════════════════╗
║           CV Generator — Formato Harvard                     ║
║   Edita tu CV y genera PDF en Español o Inglés.              ║
║   Traducción automática vía IA / Google Translate.           ║
║                                                              ║
║   Instalación:                                               ║
║     pip install streamlit reportlab deep-translator pydantic ║
║                                                              ║
║   Uso:                                                       ║
║     streamlit run app.py                                     ║
║                                                              ║
║   Estructura (MEJ-06):                                       ║
║     app.py          → orquestación (init + routing de tabs)  ║
║     ui_components.py → render de sidebar, navbar y tabs       ║
║     helpers.py       → utilidades y flujos de datos          ║
║     validation.py    → validación Pydantic + formato         ║
╚══════════════════════════════════════════════════════════════╝
"""

import os

import streamlit as st

from i18n import t
from helpers import default_cv_data, deferred_translate_and_reevaluate, push_data_to_widgets
from ai_analyzer import AI_AVAILABLE
from ui_components import (
    render_score_navbar,
    render_sidebar,
    render_analysis_tab,
    render_manual_tab,
    render_chat_tab,
    render_eval_tab,
    render_banco_tab,
)
import session_keys as sk


# ═══════════════════════════════════════════════════════════════
# INICIALIZACIÓN DE SESSION STATE
# ═══════════════════════════════════════════════════════════════

def _init_session_state():
    # ── Banco de habilidades ──
    if sk.BANCO not in st.session_state:
        from banco import get_load_warning, load_banco, migrate_from_config, save_banco
        _banco = load_banco()
        _load_warn = get_load_warning()
        if _load_warn:
            st.warning(_load_warn)
        if not _banco:
            # Intentar migrar desde config_personal.json
            cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_personal.json")
            if os.path.exists(cfg_path):
                _banco = migrate_from_config(cfg_path)
                save_banco(_banco)
        st.session_state[sk.BANCO] = _banco

    if sk.CV not in st.session_state:
        if st.session_state.get(sk.BANCO):
            from banco import bank_to_active_cv
            st.session_state[sk.CV] = bank_to_active_cv(st.session_state[sk.BANCO])
        else:
            st.session_state[sk.CV] = default_cv_data()
    if sk.LANG not in st.session_state:
        st.session_state[sk.LANG] = "es"
    if sk.CONTENT_LANG not in st.session_state:
        st.session_state[sk.CONTENT_LANG] = "es"
    if sk.AI_API_KEY not in st.session_state:
        if AI_AVAILABLE:
            from ai_analyzer import load_ai_config
            from llm_client import DEFAULT_MODELS
            _cfg = load_ai_config()
            _provider = _cfg["provider"]
            _api_key = _cfg.get("api_key", "")
            _model = _cfg.get("model") or DEFAULT_MODELS.get(_provider, "")
            # Reconstruir el mapa por proveedor si la config viene en formato antiguo
            # (sin "providers"), p.ej. tras un hot-reload con el módulo cacheado.
            _providers = _cfg.get("providers")
            if not _providers:
                _providers = {p: {"api_key": "", "model": m} for p, m in DEFAULT_MODELS.items()}
                _providers[_provider] = {"api_key": _api_key, "model": _model}
            st.session_state[sk.AI_PROVIDERS] = _providers
            st.session_state[sk.AI_PROVIDER] = _provider
            st.session_state[sk.AI_API_KEY] = _api_key
            st.session_state[sk.AI_MODEL] = _model
        else:
            st.session_state[sk.AI_PROVIDERS] = {}
            st.session_state[sk.AI_PROVIDER] = None  # call_llm usa DEFAULT_PROVIDER
            st.session_state[sk.AI_API_KEY] = ""
            st.session_state[sk.AI_MODEL] = ""
    if sk.ANALYSIS_RESULT not in st.session_state:
        st.session_state[sk.ANALYSIS_RESULT] = None
    if sk.EVAL_RESULT not in st.session_state:
        st.session_state[sk.EVAL_RESULT] = None
    if sk.CHAT_MESSAGES not in st.session_state:
        st.session_state[sk.CHAT_MESSAGES] = []
    if sk.CHAT_PENDING_PATCH not in st.session_state:
        st.session_state[sk.CHAT_PENDING_PATCH] = None
    if sk.REFINE_CHAT_OPEN not in st.session_state:
        st.session_state[sk.REFINE_CHAT_OPEN] = False
    if sk.REFINE_MESSAGES not in st.session_state:
        st.session_state[sk.REFINE_MESSAGES] = []


# ═══════════════════════════════════════════════════════════════
# INTERFAZ STREAMLIT
# ═══════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title="CV Harvard Generator",
        page_icon="📄",
        layout="wide",
    )

    _init_session_state()
    d = st.session_state[sk.CV]

    # ── Deferred push: actualizar widget keys ANTES de renderizar widgets ──
    if st.session_state.pop(sk.NEEDS_WIDGET_PUSH, False):
        push_data_to_widgets(d)

    # ── Deferred: auto-traducir + re-evaluar después de aplicar adaptaciones ──
    if st.session_state.pop(sk.NEEDS_REEVALUATION, False):
        deferred_translate_and_reevaluate(d)

    # ── Título ───────────────────────────────────────────────
    st.title(f"📄 {t('page_title')}")
    st.caption(t("subtitle"))

    # ── Top bar: Score + Vacante + Re-evaluar ────────────────
    render_score_navbar(d)

    # ── Barra lateral ────────────────────────────────────────
    render_sidebar(d)

    # ── Tabs principales ────────────────────────────────────
    tab_analysis, tab_manual, tab_chat, tab_eval, tab_banco = st.tabs([
        t("tab_analysis"), t("tab_manual"), t("tab_chat"), t("tab_eval"), t("tab_banco"),
    ])

    with tab_analysis:
        render_analysis_tab(d)
    with tab_manual:
        render_manual_tab(d)
    with tab_chat:
        render_chat_tab(d)
    with tab_eval:
        render_eval_tab(d)
    with tab_banco:
        render_banco_tab(d)


if __name__ == "__main__":
    main()
