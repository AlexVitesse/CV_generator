"""
Constantes de session_state para el CV Generator.

Centraliza todas las referencias a claves del session_state para evitar typos.
"""

BANCO = "banco"
CV = "cv"
LANG = "lang"
CONTENT_LANG = "content_lang"
AI_API_KEY = "ai_api_key"
AI_MODEL = "ai_model"
AI_PROVIDER = "ai_provider"
AI_PROVIDERS = "ai_providers_cfg"  # dict provider -> {"api_key", "model"}
ANALYSIS_RESULT = "analysis_result"
EVAL_RESULT = "eval_result"
CHAT_MESSAGES = "chat_messages"
CHAT_PENDING_PATCH = "chat_pending_patch"
REFINE_CHAT_OPEN = "refine_chat_open"
REFINE_MESSAGES = "refine_messages"

# Keys diferidas/señales
NEEDS_WIDGET_PUSH = "_needs_widget_push"
NEEDS_REEVALUATION = "_needs_reevaluation"
CV_ADAPTED = "cv_adapted"
PDF_BYTES = "pdf_bytes"
TARGET_COMPANY = "_target_company"
GENERATED_SUMMARY = "_generated_summary"
GENERATED_COVER = "_generated_cover"
VACANCY_TEXT = "vacancy_text"
VACANCY_IMAGE_UPLOADER = "vacancy_image_uploader"
