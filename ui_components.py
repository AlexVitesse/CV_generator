"""
Compatibilidad retro — re-exporta desde el paquete ui/.
app.py sigue importando desde ui_components sin cambios.
"""
from ui import (
    render_score_navbar,
    render_sidebar,
    render_analysis_tab,
    render_manual_tab,
    render_chat_tab,
    render_eval_tab,
    render_banco_tab,
)
