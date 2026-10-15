"""
Diff Viewer interactivo de sugerencias de la IA.
"""

import difflib
import html as _html
import re

import streamlit as st

from helpers import uid, sync_widgets_to_data
import session_keys as sk
from i18n import t
from llm_client import get_logger
from metrics_guard import resolve_target_index

logger = get_logger("diff_viewer")


def _html_word_diff(before: str, after: str) -> str:
    """Genera un HTML con el diff palabra-por-palabra entre `before` y `after`.
    Verde = añadido, rojo tachado = eliminado."""
    before = before or ""
    after = after or ""
    a = re.split(r'(\s+)', before)
    b = re.split(r'(\s+)', after)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)

    add = "background:#d4f7d4;color:#0a6b0a;border-radius:3px;"
    rem = "background:#f9d4d4;color:#9b1c1c;text-decoration:line-through;border-radius:3px;"
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        a_seg = _html.escape("".join(a[i1:i2]))
        b_seg = _html.escape("".join(b[j1:j2]))
        if tag == "equal":
            out.append(b_seg)
        elif tag == "delete":
            out.append(f"<span style='{rem}'>{a_seg}</span>")
        elif tag == "insert":
            out.append(f"<span style='{add}'>{b_seg}</span>")
        elif tag == "replace":
            out.append(f"<span style='{rem}'>{a_seg}</span>")
            out.append(f"<span style='{add}'>{b_seg}</span>")
    body = "".join(out).replace("\n", "<br>")
    return (
        "<div style='font-size:0.88rem;line-height:1.6;padding:0.6rem 0.8rem;"
        "border:1px solid #e0e0e0;border-radius:8px;background:#fafafa;'>"
        f"{body}</div>"
    )


def _collect_suggestion_changes(d: dict, suggestions: dict) -> tuple[list, list]:
    """Construye la lista de cambios sugeridos no triviales (after != before).

    Devuelve (changes, dropped). Cada cambio: {key, kind, index, label, before, after}.
    `dropped` son las sugerencias que apuntan a ítems que ya NO están en el CV
    (el análisis corre contra el banco completo y la selección de 1 página poda
    después): antes se perdían en silencio, con solo un WARNING en el log.
    """
    changes = []
    dropped = []
    seen_keys = set()

    def _add(key, kind, index, label, before, after):
        before = (before or "").strip()
        after = (after or "").strip()
        if not after or after == before:
            return
        # Dos sugerencias del modelo pueden resolver al MISMO ítem (mismo idx →
        # misma key). Streamlit exige keys únicas, y aplicar ambas escribiría dos
        # veces el mismo campo. Conservamos la primera y descartamos la colisión.
        if key in seen_keys:
            logger.warning("DIFF descarta sugerencia duplicada para el mismo destino "
                           "(key=%s, kind=%s)", key, kind)
            return
        seen_keys.add(key)
        changes.append({
            "key": key, "kind": kind, "index": index,
            "label": label, "before": before, "after": after,
        })

    # Resumen
    if suggestions.get("summary"):
        _add("summary", "summary", None, t("diff_field_summary"),
             d.get("summary", ""), suggestions["summary"])

    # Experiencias (título + bullets). El índice se resuelve por id/contenido
    # (no por el "index" crudo del modelo) para no mal-asignar bullets a otra empresa.
    exps = d.get("experiences", [])
    for exp_sug in suggestions.get("experiences", []):
        idx = resolve_target_index(exp_sug, exps, kind="experience")
        if idx is None:
            logger.warning("DIFF descarta sugerencia de experiencia sin match confiable "
                           "(id=%s, title=%s)", exp_sug.get("id"), exp_sug.get("title"))
            dropped.append(exp_sug.get("title") or exp_sug.get("id") or "?")
            continue
        cur = exps[idx]
        if exp_sug.get("title"):
            _add(f"exptitle_{idx}", "exp_title", idx,
                 t("diff_field_exp_title").format(idx),
                 cur.get("title", ""), exp_sug["title"])
        if exp_sug.get("bullets"):
            _add(f"expbul_{idx}", "exp_bullets", idx,
                 t("diff_field_exp_bullets").format(idx),
                 cur.get("bullets", ""), exp_sug["bullets"])

    # Proyectos
    projs = d.get("projects", [])
    for proj_sug in suggestions.get("projects", []):
        idx = resolve_target_index(proj_sug, projs, kind="project")
        if idx is None:
            logger.warning("DIFF descarta sugerencia de proyecto sin match confiable (id=%s)",
                           proj_sug.get("id"))
            dropped.append(proj_sug.get("name") or proj_sug.get("id") or "?")
            continue
        cur = projs[idx]
        if proj_sug.get("description"):
            _add(f"proj_{idx}", "proj_desc", idx,
                 t("diff_field_proj").format(idx),
                 cur.get("description", ""), proj_sug["description"])

    # Skills
    if suggestions.get("skills"):
        raw_skills = suggestions["skills"]
        after = "\n".join(raw_skills) if isinstance(raw_skills, list) else str(raw_skills)
        before = "\n".join(sk.get("text", "") for sk in d.get("skills", []))
        _add("skills", "skills", None, t("diff_field_skills"), before, after)

    return changes, dropped


def merge_skill_line(old_skills: list, value: str) -> list:
    """Sustituye las líneas de skills técnicas por la línea sugerida `value`.

    Conserva las líneas de certificaciones/idiomas (ahí vive evidencia de must-haves
    como "English proficiency") y REUSA el id de la primera línea técnica: con un
    `uid()` nuevo, `merge_cv_to_bank` no encuentra la skill en el banco y la AGREGA
    como línea suelta en cada "Guardar CV al banco" (así entraron `2a963b4b` y
    `d8c53127`). Función pura para poder testearla sin Streamlit.
    """
    preserved, tech_ids = [], []
    for sk in old_skills:
        txt = sk.get("text", "")
        low = txt.lower()
        if "cert" in low or "idioma" in low or "language" in low:
            if txt.strip() not in value:
                preserved.append(sk)
        else:
            tech_ids.append(sk.get("id"))
    # Una entrada POR tier (escaneable en el PDF). Acepta líneas separadas por "\n" o
    # el formato viejo "A | B | C". Reusa los ids técnicos en orden; uid solo si sobran.
    lines = [l.strip() for l in re.split(r"\n| \| ", value) if l.strip()]
    ids = iter(tech_ids)
    return [{"id": next(ids, None) or uid(), "text": l} for l in lines] + preserved


def _apply_selected_changes(d: dict, changes: list) -> int:
    """Aplica al CV los cambios cuyo checkbox de inclusión está activo.
    Devuelve cuántos se aplicaron."""
    applied = 0
    exps = d.get("experiences", [])
    projs = d.get("projects", [])

    for ch in changes:
        if not st.session_state.get(f"diffinc_{ch['key']}", ch.get("default", True)):
            continue
        value = st.session_state.get(f"diffta_{ch['key']}", ch["after"])
        kind, idx = ch["kind"], ch["index"]

        if kind == "summary":
            d["summary"] = value
            applied += 1
        elif kind == "exp_title" and 0 <= idx < len(exps):
            exps[idx]["title"] = value
            applied += 1
        elif kind == "exp_bullets" and 0 <= idx < len(exps):
            exps[idx]["bullets"] = value
            applied += 1
        elif kind == "proj_desc" and 0 <= idx < len(projs):
            projs[idx]["description"] = value
            applied += 1
        elif kind == "skills":
            # La sugerencia es una sola línea de skills TÉCNICAS (formato tech-tier), que no
            # incluye certificaciones ni la línea de idiomas/soft skills. Preservamos ambas para
            # no perder evidencia de must-haves (ej: "English proficiency" vive en "Idiomas:").
            d["skills"] = merge_skill_line(d.get("skills", []), value)
            applied += 1

    return applied


def render_suggestions_diff(d: dict, result: dict):
    """Diff Viewer: muestra cada sugerencia de la IA con su diff inline y permite
    aceptar/rechazar y editar individualmente antes de aplicar."""
    suggestions = result.get("suggestions", {})
    if not suggestions:
        return

    changes, dropped = _collect_suggestion_changes(d, suggestions)
    if not changes and not dropped:
        return

    st.divider()
    st.subheader(t("vacancy_suggestions"))
    if dropped:
        st.info(t("diff_dropped_orphans").format(len(dropped), ", ".join(dropped[:3])))
    if not changes:
        return
    st.caption(t("diff_intro"))
    st.caption(t("diff_legend"))

    # CV armado desde el banco: sus bullets/proyectos YA son texto real elegido por la
    # selección. La reescritura del modelo tiende a adornarlos hacia el JD ("ensuring
    # data quality", métricas mezcladas), así que arranca DESMARCADA (opt-in).
    from_bank = bool((st.session_state.get(sk.BANCO) or {}).get("experiences"))
    for ch in changes:
        ch["default"] = not (from_bank and ch["kind"] in ("exp_bullets", "proj_desc"))
    if from_bank:
        st.caption(t("diff_bank_bullets_off"))

    # ── Aceptar / rechazar todos ──
    bc1, bc2, _ = st.columns([2, 2, 6])
    with bc1:
        if st.button(t("diff_select_all"), key="diff_all", use_container_width=True):
            for ch in changes:
                st.session_state[f"diffinc_{ch['key']}"] = True
            st.rerun()
    with bc2:
        if st.button(t("diff_select_none"), key="diff_none", use_container_width=True):
            for ch in changes:
                st.session_state[f"diffinc_{ch['key']}"] = False
            st.rerun()

    # ── Render por cambio ──
    for ch in changes:
        inc_key = f"diffinc_{ch['key']}"
        ta_key = f"diffta_{ch['key']}"
        with st.container(border=True):
            st.checkbox(
                f"**{ch['label']}** — {t('diff_include')}",
                value=st.session_state.get(inc_key, ch["default"]),
                key=inc_key,
            )
            edited = st.text_area(
                t("diff_suggested"),
                value=ch["after"],
                height=140 if ch["kind"] in ("exp_bullets", "summary", "skills") else 70,
                key=ta_key,
            )
            with st.expander(t("diff_view"), expanded=False):
                st.markdown(
                    f"**{t('diff_current')}** → **{t('diff_suggested')}**",
                    help=None,
                )
                st.markdown(_html_word_diff(ch["before"], edited), unsafe_allow_html=True)

    # ── Aplicar seleccionados ──
    if st.button(t("diff_apply_selected"), type="primary", key="diff_apply"):
        sync_widgets_to_data(d)
        applied = _apply_selected_changes(d, changes)
        if applied == 0:
            st.warning(t("diff_none_selected"))
        else:
            st.session_state._needs_widget_push = True
            st.session_state._needs_reevaluation = True
            st.session_state.cv_adapted = True
            st.toast(t("diff_applied_count").format(applied))
            st.rerun()
