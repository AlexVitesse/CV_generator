"""
╔══════════════════════════════════════════════════════════════╗
║           CV Generator — Formato Harvard                     ║
║   Edita tu CV y genera PDF en Español o Inglés.              ║
║   Traducción automática vía Google Translate (gratis).       ║
║                                                              ║
║   Instalación:                                               ║
║     pip install streamlit reportlab deep-translator          ║
║                                                              ║
║   Uso:                                                       ║
║     streamlit run app.py                                     ║
╚══════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import json
import re
import uuid
import os

from i18n import LANG_NAMES, t
from translate import TRANSLATOR_AVAILABLE, translate_cv_data
from pdf import generate_cv_pdf


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def uid():
    return uuid.uuid4().hex[:8]


def clear_keys(*prefixes):
    for key in list(st.session_state.keys()):
        if any(key.startswith(p) for p in prefixes):
            del st.session_state[key]


def sync_widgets_to_data(data: dict):
    """Sincroniza valores de widgets de Streamlit al diccionario de datos del CV.
    Evita la repetición manual de chequear cada key del session_state."""

    # Campos simples: (session_key, data_key)
    simple_fields = [
        ("f_name", "name"),
        ("f_loc", "location"),
        ("f_summary", "summary"),
    ]
    for skey, dkey in simple_fields:
        if skey in st.session_state:
            data[dkey] = st.session_state[skey]

    # Experiencias: (prefijo_widget, campo_en_dict)
    exp_fields = [
        ("x_co_", "company"),
        ("x_ti_", "title"),
        ("x_lo_", "location"),
        ("x_da_", "dates"),
        ("x_bu_", "bullets"),
    ]
    for ex in data.get("experiences", []):
        eid = ex["id"]
        for prefix, field in exp_fields:
            key = f"{prefix}{eid}"
            if key in st.session_state:
                ex[field] = st.session_state[key]

    # Educación
    edu_fields = [
        ("e_in_", "institution"),
        ("e_de_", "degree"),
        ("e_lo_", "location"),
        ("e_dt_", "date"),
        ("e_dz_", "details"),
    ]
    for ed in data.get("education", []):
        eid = ed["id"]
        for prefix, field in edu_fields:
            key = f"{prefix}{eid}"
            if key in st.session_state:
                ed[field] = st.session_state[key]

    # Skills
    for sk in data.get("skills", []):
        key = f"s_tx_{sk['id']}"
        if key in st.session_state:
            sk["text"] = st.session_state[key]


def push_data_to_widgets(data: dict):
    """Actualiza los widgets de Streamlit con los valores del diccionario
    (usado después de traducción para reflejar cambios en pantalla)."""

    st.session_state["f_name"] = data.get("name", "")
    st.session_state["f_loc"] = data.get("location", "")
    st.session_state["f_summary"] = data.get("summary", "")

    for ex in data.get("experiences", []):
        eid = ex["id"]
        st.session_state[f"x_co_{eid}"] = ex.get("company", "")
        st.session_state[f"x_ti_{eid}"] = ex.get("title", "")
        st.session_state[f"x_lo_{eid}"] = ex.get("location", "")
        st.session_state[f"x_da_{eid}"] = ex.get("dates", "")
        st.session_state[f"x_bu_{eid}"] = ex.get("bullets", "")

    for ed in data.get("education", []):
        eid = ed["id"]
        st.session_state[f"e_in_{eid}"] = ed.get("institution", "")
        st.session_state[f"e_de_{eid}"] = ed.get("degree", "")
        st.session_state[f"e_lo_{eid}"] = ed.get("location", "")
        st.session_state[f"e_dt_{eid}"] = ed.get("date", "")
        st.session_state[f"e_dz_{eid}"] = ed.get("details", "")

    for sk in data.get("skills", []):
        st.session_state[f"s_tx_{sk['id']}"] = sk.get("text", "")


# ═══════════════════════════════════════════════════════════════
# VALIDACIÓN DE FORMATO
# ═══════════════════════════════════════════════════════════════

def validate_email(email: str) -> bool:
    if not email:
        return True
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def validate_phone(phone: str) -> bool:
    if not phone:
        return True
    # Permite +, dígitos, espacios y guiones
    return bool(re.match(r"^\+?[\d\s\-()]{7,20}$", phone))


def validate_linkedin(url: str) -> bool:
    if not url:
        return True
    return "linkedin.com/in/" in url.lower()


# ═══════════════════════════════════════════════════════════════
# DATOS POR DEFECTO
# ═══════════════════════════════════════════════════════════════

def default_cv_data():
    """Carga datos iniciales desde JSON. Prioriza config_personal.json si existe."""
    personal_config = "config_personal.json"
    template_config = "config_plantilla.json"
    
    data = {}
    if os.path.exists(personal_config):
        try:
            with open(personal_config, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
            
    if not data and os.path.exists(template_config):
        try:
            with open(template_config, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    if not data:
        # Fallback total si fallan los archivos
        data = {
            "name": "Tu Nombre Completo",
            "location": "Ciudad, País",
            "linkedin": "www.linkedin.com/in/tu-perfil",
            "phone": "+52 00 0000 0000",
            "email": "tu@correo.com",
            "summary": "Breve descripción de tu perfil profesional.",
            "experiences": [],
            "education": [],
            "skills": []
        }

    # Asegurar IDs únicos para widgets de Streamlit
    for exp in data.get("experiences", []):
        if "id" not in exp: exp["id"] = uid()
    for edu in data.get("education", []):
        if "id" not in edu: edu["id"] = uid()
    for sk in data.get("skills", []):
        if "id" not in sk: sk["id"] = uid()
        
    return data


# ═══════════════════════════════════════════════════════════════
# INTERFAZ STREAMLIT
# ═══════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title="CV Harvard Generator",
        page_icon="📄",
        layout="wide",
    )

    # ── Inicialización ───────────────────────────────────────
    if "cv" not in st.session_state:
        st.session_state.cv = default_cv_data()
    if "lang" not in st.session_state:
        st.session_state.lang = "es"
    if "content_lang" not in st.session_state:
        st.session_state.content_lang = "es"

    d = st.session_state.cv

    # ── Título ───────────────────────────────────────────────
    st.title(f"📄 {t('page_title')}")
    st.caption(t("subtitle"))

    # ── Barra lateral ────────────────────────────────────────
    with st.sidebar:
        # ── Selector de idioma de interfaz ───────────────────
        st.subheader(t("language"))
        lang_options = {"es": "🇲🇽 Español", "en": "🇺🇸 English"}
        current_idx = 0 if st.session_state.lang == "es" else 1
        selected_lang = st.radio(
            t("language"),
            options=list(lang_options.keys()),
            format_func=lambda x: lang_options[x],
            index=current_idx,
            horizontal=True,
            label_visibility="collapsed",
        )
        if selected_lang != st.session_state.lang:
            st.session_state.lang = selected_lang
            st.rerun()

        st.divider()

        # ── Traducción automática del contenido ──────────────
        st.subheader("🔄 Traducción automática")

        current_content = st.session_state.content_lang
        target_lang = "en" if current_content == "es" else "es"
        target_name = LANG_NAMES[target_lang]

        content_label = (
            f"Contenido actual: **{LANG_NAMES[current_content]}**"
            if st.session_state.lang == "es"
            else f"Current content: **{LANG_NAMES[current_content]}**"
        )
        st.markdown(content_label)

        if TRANSLATOR_AVAILABLE:
            if st.button(
                t("translate_btn").format(target_name),
                use_container_width=True,
            ):
                try:
                    sync_widgets_to_data(d)

                    progress_bar = st.progress(0, text=t("translating"))
                    translated = translate_cv_data(
                        d,
                        source=current_content,
                        target=target_lang,
                        progress_callback=lambda p: progress_bar.progress(
                            min(p, 1.0), text=t("translating")
                        ),
                    )
                    progress_bar.progress(1.0, text="✅")

                    st.session_state.cv = translated
                    st.session_state.content_lang = target_lang
                    st.session_state.lang = target_lang

                    push_data_to_widgets(translated)

                    st.toast(t("translate_success").format(target_name))
                    st.rerun()
                except Exception as e:
                    print(f"FATAL ERROR: {e}")
                    st.error(t("translate_error").format(str(e)))
        else:
            st.warning(t("translate_missing"))

        st.divider()

        # ── Generar PDF ──────────────────────────────────────
        st.header(t("actions"))

        if st.button(t("generate_pdf"), type="primary",
                     use_container_width=True):
            try:
                pdf_buf = generate_cv_pdf(d, lang=st.session_state.lang)
                st.session_state.pdf_bytes = pdf_buf.getvalue()
                st.success(t("pdf_success"))
            except Exception as e:
                st.error(t("pdf_error").format(e))

        if "pdf_bytes" in st.session_state:
            lang_suffix = st.session_state.lang.upper()
            st.download_button(
                t("download_pdf"),
                data=st.session_state.pdf_bytes,
                file_name=f"cv_harvard_{lang_suffix}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

        st.divider()
        st.subheader(t("data_section"))

        st.download_button(
            t("export_json"),
            data=json.dumps(d, ensure_ascii=False, indent=2),
            file_name="cv_data.json",
            mime="application/json",
            use_container_width=True,
        )

        uploaded = st.file_uploader(t("import_json"), type=["json"])
        if uploaded is not None:
            try:
                imported = json.load(uploaded)
                for exp in imported.get("experiences", []):
                    exp.setdefault("id", uid())
                for edu in imported.get("education", []):
                    edu.setdefault("id", uid())
                for i, sk in enumerate(imported.get("skills", [])):
                    if isinstance(sk, str):
                        imported["skills"][i] = {"id": uid(), "text": sk}
                    elif isinstance(sk, dict):
                        sk.setdefault("id", uid())
                st.session_state.cv = imported
                st.session_state.content_lang = "es"
                clear_keys("x_", "e_", "s_", "f_")
                st.success(t("import_success"))
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

        st.divider()

        if st.button(t("restore_example"), use_container_width=True):
            st.session_state.cv = default_cv_data()
            st.session_state.content_lang = "es"
            st.session_state.lang = "es"
            clear_keys("x_", "e_", "s_", "f_")
            st.rerun()

    # ── Información Personal ─────────────────────────────────
    st.header(t("personal_info"))
    c1, c2 = st.columns(2)
    with c1:
        d["name"] = st.text_input(
            t("full_name"), value=d.get("name", ""), key="f_name"
        )
        d["location"] = st.text_input(
            t("location"), value=d.get("location", ""), key="f_loc"
        )
        d["linkedin"] = st.text_input(
            t("linkedin"), value=d.get("linkedin", ""), key="f_li"
        )
        if not validate_linkedin(d["linkedin"]):
            st.warning(t("validation_linkedin"))
    with c2:
        d["phone"] = st.text_input(
            t("phone"), value=d.get("phone", ""), key="f_phone"
        )
        if not validate_phone(d["phone"]):
            st.warning(t("validation_phone"))
        d["email"] = st.text_input(
            t("email"), value=d.get("email", ""), key="f_email"
        )
        if not validate_email(d["email"]):
            st.warning(t("validation_email"))

    # ── Resumen ──────────────────────────────────────────────
    st.header(t("summary_header"))
    d["summary"] = st.text_area(
        t("summary_label"),
        value=d.get("summary", ""),
        height=100,
        key="f_summary",
    )

    # ── Experiencia Profesional ──────────────────────────────
    st.header(t("experience_header"))

    exp_to_remove = None
    for i, exp in enumerate(d["experiences"]):
        eid = exp["id"]
        label = exp.get("company", "") or t("new_experience")
        title_hint = exp.get("title", "")
        with st.expander(
            f"**{label}** — {title_hint}" if title_hint else f"**{label}**",
            expanded=(i == 0),
        ):
            c1, c2 = st.columns(2)
            with c1:
                exp["company"] = st.text_input(
                    t("company"), value=exp.get("company", ""),
                    key=f"x_co_{eid}",
                )
                exp["title"] = st.text_input(
                    t("job_title"), value=exp.get("title", ""),
                    key=f"x_ti_{eid}",
                )
            with c2:
                exp["location"] = st.text_input(
                    t("exp_location"), value=exp.get("location", ""),
                    key=f"x_lo_{eid}",
                )
                exp["dates"] = st.text_input(
                    t("period"), value=exp.get("dates", ""),
                    key=f"x_da_{eid}",
                )

            exp["bullets"] = st.text_area(
                t("bullets_label"),
                value=exp.get("bullets", ""),
                height=220,
                key=f"x_bu_{eid}",
            )

            if st.button(t("delete_experience"), key=f"x_del_{eid}"):
                exp_to_remove = i

    if exp_to_remove is not None:
        d["experiences"].pop(exp_to_remove)
        st.rerun()

    if st.button(t("add_experience")):
        d["experiences"].append({
            "id": uid(), "company": "", "title": "",
            "location": "", "dates": "", "bullets": "",
        })
        st.rerun()

    # ── Educación ────────────────────────────────────────────
    st.header(t("education_header"))

    edu_to_remove = None
    for i, edu in enumerate(d["education"]):
        eid = edu["id"]
        label = edu.get("institution", "") or t("new_institution")
        with st.expander(f"**{label}**", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                edu["institution"] = st.text_input(
                    t("institution"), value=edu.get("institution", ""),
                    key=f"e_in_{eid}",
                )
                edu["degree"] = st.text_input(
                    t("degree"), value=edu.get("degree", ""),
                    key=f"e_de_{eid}",
                )
            with c2:
                edu["location"] = st.text_input(
                    t("edu_location"), value=edu.get("location", ""),
                    key=f"e_lo_{eid}",
                )
                edu["date"] = st.text_input(
                    t("date"), value=edu.get("date", ""),
                    key=f"e_dt_{eid}",
                )
            edu["details"] = st.text_input(
                t("details"),
                value=edu.get("details", ""),
                key=f"e_dz_{eid}",
            )

            if st.button(t("delete_education"), key=f"e_del_{eid}"):
                edu_to_remove = i

    if edu_to_remove is not None:
        d["education"].pop(edu_to_remove)
        st.rerun()

    if st.button(t("add_education")):
        d["education"].append({
            "id": uid(), "institution": "", "degree": "",
            "details": "", "location": "", "date": "",
        })
        st.rerun()

    # ── Skills ───────────────────────────────────────────────
    st.header(t("skills_header"))
    st.caption(t("skills_caption"))

    sk_to_remove = None
    for i, sk in enumerate(d["skills"]):
        sid = sk["id"]
        c1, c2 = st.columns([12, 1])
        with c1:
            sk["text"] = st.text_area(
                f"Skill {i + 1}",
                value=sk.get("text", ""),
                height=72,
                key=f"s_tx_{sid}",
                label_visibility="collapsed",
            )
        with c2:
            st.write("")
            if st.button("🗑️", key=f"s_del_{sid}"):
                sk_to_remove = i

    if sk_to_remove is not None:
        d["skills"].pop(sk_to_remove)
        st.rerun()

    if st.button(t("add_skill")):
        d["skills"].append({"id": uid(), "text": ""})
        st.rerun()


if __name__ == "__main__":
    main()
