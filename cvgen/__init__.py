"""Paquete principal de CVGenerator (lógica, IA, PDF y UI)."""
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Datos personales del usuario (banco, config, API keys). Excluido de git.
DATA_DIR = os.path.join(ROOT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
