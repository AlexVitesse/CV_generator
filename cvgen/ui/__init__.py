"""
Paquete ui — componentes de Streamlit del CV Generator.

Re-exporta los render_* que usa app.py.
"""

from cvgen.ui.navbar import render_score_navbar
from cvgen.ui.sidebar import render_sidebar
from cvgen.ui.tab_analysis import render_analysis_tab, render_refine_chat
from cvgen.ui.tab_manual import render_manual_tab
from cvgen.ui.tab_chat import render_chat_tab
from cvgen.ui.tab_eval import render_eval_tab
from cvgen.ui.tab_banco import render_banco_tab
from cvgen.ui.diff_viewer import render_suggestions_diff
