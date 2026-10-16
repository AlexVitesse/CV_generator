"""
Tab de edición manual del CV.
"""

import streamlit as st

from cvgen.helpers import uid
from cvgen.i18n import t
from cvgen.validation import validate_email, validate_phone, validate_linkedin


def render_manual_tab(d: dict):
    # ── Información Personal ─────────────────────────────
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
        d["github"] = st.text_input(
            "GitHub", value=d.get("github", ""), key="f_gh"
        )

    # ── Resumen ──────────────────────────────────────────
    st.header(t("summary_header"))
    d["summary"] = st.text_area(
        t("summary_label"),
        value=d.get("summary", ""),
        height=100,
        key="f_summary",
    )

    # ── Experiencia Profesional ──────────────────────────
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
                exp_to_remove = eid

    if exp_to_remove is not None:
        d["experiences"] = [e for e in d["experiences"] if e["id"] != exp_to_remove]
        st.rerun()

    if st.button(t("add_experience")):
        d["experiences"].append({
            "id": uid(), "company": "", "title": "",
            "location": "", "dates": "", "bullets": "",
        })
        st.rerun()

    # ── Proyectos ─────────────────────────────────────────
    st.header(t("projects_header"))

    proj_to_remove = None
    for i, proj in enumerate(d.get("projects", [])):
        pid = proj["id"]
        label = proj.get("name", "") or f"Proyecto {i + 1}"
        with st.expander(f"**{label}**", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                proj["name"] = st.text_input(
                    t("project_name"), value=proj.get("name", ""),
                    key=f"p_nm_{pid}",
                )
            with c2:
                proj["url"] = st.text_input(
                    t("project_url"), value=proj.get("url", ""),
                    key=f"p_ur_{pid}",
                )
            proj["description"] = st.text_area(
                t("project_description"),
                value=proj.get("description", ""),
                height=100,
                key=f"p_ds_{pid}",
            )
            if st.button(t("delete_project"), key=f"p_del_{pid}"):
                proj_to_remove = pid

    if proj_to_remove is not None:
        d["projects"] = [p for p in d["projects"] if p["id"] != proj_to_remove]
        st.rerun()

    if st.button(t("add_project")):
        d.setdefault("projects", []).append({
            "id": uid(), "name": "", "url": "", "description": "",
        })
        st.rerun()

    # ── Educación ────────────────────────────────────────
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
                edu_to_remove = eid

    if edu_to_remove is not None:
        d["education"] = [e for e in d["education"] if e["id"] != edu_to_remove]
        st.rerun()

    if st.button(t("add_education")):
        d["education"].append({
            "id": uid(), "institution": "", "degree": "",
            "details": "", "location": "", "date": "",
        })
        st.rerun()

    # ── Certificaciones ──────────────────────────────────
    st.header(t("certifications_header"))
    st.caption(t("certifications_caption"))

    d.setdefault("certifications", [])
    cert_to_remove = None
    for i, cert in enumerate(d["certifications"]):
        cid = cert["id"]
        c1, c2 = st.columns([12, 1])
        with c1:
            cert["text"] = st.text_input(
                f"Certificación {i + 1}",
                value=cert.get("text", ""),
                key=f"c_tx_{cid}",
                label_visibility="collapsed",
            )
            cert["credential_id"] = st.text_input(
                t("credential_id"),
                value=cert.get("credential_id", ""),
                key=f"c_cid_{cid}",
                help=t("credential_id_help"),
            )
        with c2:
            st.write("")
            if st.button("🗑️", key=f"c_del_{cid}"):
                cert_to_remove = cid

    if cert_to_remove is not None:
        d["certifications"] = [c for c in d["certifications"] if c["id"] != cert_to_remove]
        st.rerun()

    if st.button(t("add_certification")):
        d["certifications"].append({"id": uid(), "text": ""})
        st.rerun()

    # ── Skills ───────────────────────────────────────────
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
                sk_to_remove = sid

    if sk_to_remove is not None:
        d["skills"] = [s for s in d["skills"] if s["id"] != sk_to_remove]
        st.rerun()

    if st.button(t("add_skill")):
        d["skills"].append({"id": uid(), "text": ""})
        st.rerun()
