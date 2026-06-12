"""
Paquete ui — componentes de Streamlit del CV Generator.

Re-exporta los render_* para que app.py los importe desde ui_components
sin cambiar el código existente.
"""

from ui.navbar import render_score_navbar
from ui.sidebar import render_sidebar
from ui.tab_analysis import render_analysis_tab, render_refine_chat
from ui.tab_manual import render_manual_tab
from ui.tab_chat import render_chat_tab
from ui.tab_eval import render_eval_tab
from ui.tab_banco import render_banco_tab
from ui.diff_viewer import render_suggestions_diff
