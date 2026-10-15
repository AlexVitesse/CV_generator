"""
Generación de PDF en formato Harvard para el CV Generator.
"""

import re
import unicodedata
from io import BytesIO
from xml.sax.saxutils import escape as xml_escape

from pypdf import PdfReader

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, HRFlowable,
)
from reportlab.lib.colors import black

from i18n import LANG
from metrics_guard import _as_text


# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE FUENTES
# ═══════════════════════════════════════════════════════════════

# Vi\u00F1eta: guion est\u00E1ndar. Es 100% ATS-safe (los ATS lo tratan como vi\u00F1eta est\u00E1ndar,
# no como car\u00E1cter decorativo) y renderiza fiable en Times-Roman sin depender de fuentes
# externas (antes se usaba "\u00b7"/"\u25CF" que algunos parsers ATS leen como ruido decorativo).
BULLET_CHAR = "-"
BULLET_FONT = "Times-Roman"
BULLET_FONT_SIZE = 9.5


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

# Reemplazos Unicode → seguros en WinAnsi. Los guiones especiales son la causa principal:
# reportlab no puede dibujarlos con las fuentes estándar y cae a ZapfDingbats (cuadro negro).
_PDF_CHAR_MAP = {
    "‐": "-", "‑": "-", "‒": "-", "⁃": "-",  # variantes de guion → "-"
    "­": "",                                                # soft hyphen
    "​": "", "‌": "", "‍": "", "﻿": "",      # caracteres de ancho cero
    " ": " ", " ": " ", " ": " ",                 # nbsp / narrow / thin space
    " ": " ", " ": " ",                                # en/em space
    "•": "·", "●": "·",                      # bullet/círculo → middle dot
    "‘": "'", "’": "'", "′": "'",                 # comillas simples / prima
    "“": '"', "”": '"', "″": '"',                 # comillas dobles / doble prima
    "…": "...",                                             # puntos suspensivos
}


def _cp1252_ok(ch: str) -> bool:
    try:
        ch.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def _winansi_safe(text: str) -> str:
    """Convierte caracteres Unicode no soportados por las fuentes estándar (WinAnsi) en
    equivalentes seguros, evitando los cuadros negros del fallback a ZapfDingbats."""
    out = []
    for ch in text:
        if ch in _PDF_CHAR_MAP:
            out.append(_PDF_CHAR_MAP[ch])
            continue
        try:
            # Validamos si el char codifica directo en cp1252 de forma estricta
            ch.encode("cp1252", errors="strict")
            out.append(ch)
            continue
        except UnicodeEncodeError:
            pass
        # carácter exótico → descomponer y conservar solo lo representable, si no se omite
        norm = unicodedata.normalize("NFKD", ch)
        out.append("".join(c for c in norm if _cp1252_ok(c)))
    return "".join(out)


def safe(text: str) -> str:
    """Escapa caracteres especiales XML para uso seguro en PDF y convierte Markdown básico a HTML."""
    val = str(text or "")
    # Remover caracteres de control inválidos para ReportLab (0x00-0x1F excepto \n y \t)
    val = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", val)
    escaped = xml_escape(_winansi_safe(val))
    # Convertir **negrita** a <b>negrita</b>
    escaped = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", escaped)
    # Convertir *cursiva* a <i>cursiva</i>
    escaped = re.sub(r"\*(.*?)\*", r"<i>\1</i>", escaped)
    return escaped


def _norm_url(url: str, kind: str = "url") -> str:
    """Normaliza un valor de contacto a una URL válida para el atributo href."""
    u = str(url or "").strip()
    if not u:
        return ""
    if kind == "email":
        return u if u.lower().startswith("mailto:") else "mailto:" + u
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    return u


def link(url: str, display: str, kind: str = "url") -> str:
    """Devuelve markup de ReportLab para un hipervínculo activo (GitHub, LinkedIn, email,
    URLs de proyecto). El texto visible se escapa con safe(); el href se escapa aparte.
    El resultado ya viene escapado — pásalo a Paragraph SIN volver a envolver en safe()."""
    href = _norm_url(url, kind)
    if not href:
        return safe(display)
    href_attr = xml_escape(href, {'"': "&quot;"})
    return f'<a href="{href_attr}">{safe(display)}</a>'


# ═══════════════════════════════════════════════════════════════
# GENERACIÓN DE PDF
# ═══════════════════════════════════════════════════════════════

# Palabras funcionales exclusivas de cada idioma (sin ambiguas como "a").
_ES_WORDS = {"de", "la", "el", "en", "con", "para", "los", "las", "y", "del", "por", "una", "que"}
_EN_WORDS = {"the", "and", "with", "for", "of", "to", "in", "using", "by", "on", "an", "across"}


def text_lang(text: str) -> str | None:
    """Idioma de un texto suelto ("es"/"en") por palabras funcionales; None si no hay señal."""
    words = re.findall(r"[a-záéíóúñ]+", str(text or "").lower())
    es = sum(w in _ES_WORDS for w in words)
    en = sum(w in _EN_WORDS for w in words)
    return None if es == en else ("en" if en > es else "es")


def detect_content_lang(data: dict) -> str:
    """Idioma dominante del CUERPO del CV (summary, bullets, proyectos): "es" o "en".

    Los títulos de sección del PDF deben coincidir con el contenido, no con el idioma
    de la UI: un CV en inglés con "EXPERIENCIA PROFESIONAL" se ve mal ante un
    reclutador o un filtro de IA. Empate o sin texto → "es".
    """
    parts = [data.get("summary", "")]
    parts += [_as_text(e.get("bullets")) for e in data.get("experiences", []) if isinstance(e, dict)]
    parts += [_as_text(p.get("description")) for p in data.get("projects", []) if isinstance(p, dict)]
    words = re.findall(r"[a-záéíóúñ]+", " ".join(str(x) for x in parts).lower())
    es = sum(w in _ES_WORDS for w in words)
    en = sum(w in _EN_WORDS for w in words)
    return "en" if en > es else "es"


_ES_TO_EN = {
    "Enero": "January", "Febrero": "February", "Marzo": "March", "Abril": "April",
    "Mayo": "May", "Junio": "June", "Julio": "July", "Agosto": "August",
    "Septiembre": "September", "Octubre": "October", "Noviembre": "November",
    "Diciembre": "December", "Actualidad": "Present", "Remoto": "Remote", "EE.UU.": "USA",
}
_EN_TO_ES = {v: k for k, v in _ES_TO_EN.items()}


def localize_meta(text: str, lang: str) -> str:
    """Traduce meses, "Actualidad/Present" y "Remoto/Remote" de fechas y ubicaciones al
    idioma del contenido. Evita "Abril 2026 – Junio 2026" junto a "May 2024 – Present"
    cuando el banco mezcla idiomas (estos campos no pasan por la adaptación de la IA)."""
    table = _ES_TO_EN if lang == "en" else _EN_TO_ES
    pattern = r"(?<![\w.])(" + "|".join(re.escape(k) for k in table) + r")(?!\w)"
    return re.sub(pattern, lambda m: table[m.group(1)], str(text or ""))


def generate_cv_pdf(data: dict, lang: str | None = None) -> tuple[BytesIO, bool, float]:
    """Genera un PDF de CV en formato Harvard, escalando dinámicamente si excede 1 página.

    Retorna (buffer, cabe_en_1_pagina, escala_usada). La escala importa: "cupo" a 0.76
    es un CV al 76% del tamaño de fuente — cabe, pero se lee mal; el caller avisa para
    que recortes contenido en vez de aceptar letra chica.
    """

    lang = lang or detect_content_lang(data)
    labels = LANG.get(lang, LANG["es"])

    # Probamos factores de escala desde 1.0 hasta 0.80 para forzar que quepa en 1 sola página
    for sf in [1.0, 0.94, 0.88, 0.82, 0.76]:
        buf = BytesIO()
        pw, ph = letter
        ml = mr = 0.55 * inch
        mt = mb = 0.4 * inch
        aw = pw - ml - mr

        doc = SimpleDocTemplate(
            buf, pagesize=letter,
            topMargin=mt, bottomMargin=mb,
            leftMargin=ml, rightMargin=mr,
            # Metadatos: algunos ATS muestran el título del PDF; sin esto sale "(anonymous)".
            title=data.get("name", "") or "CV", author=data.get("name", ""),
        )

        # ── Estilos escalados ──────────────────────────────────
        s_name = ParagraphStyle(
            "Name", fontName="Times-Bold", fontSize=14 * sf,
            alignment=TA_CENTER, spaceAfter=2 * sf, leading=17 * sf,
        )
        s_contact = ParagraphStyle(
            "Contact", fontName="Times-Roman", fontSize=9 * sf,
            alignment=TA_CENTER, spaceAfter=4 * sf, leading=12 * sf,
        )
        s_summary = ParagraphStyle(
            "Summary", fontName="Times-Roman", fontSize=9.5 * sf,
            alignment=TA_JUSTIFY, spaceAfter=2 * sf, leading=12 * sf,
        )
        s_section = ParagraphStyle(
            "Section", fontName="Times-Bold", fontSize=10.5 * sf,
            spaceBefore=5 * sf, spaceAfter=0, leading=13 * sf,
        )
        s_bold_l = ParagraphStyle(
            "BoldLeft", fontName="Times-Bold", fontSize=9.5 * sf, leading=12 * sf,
        )
        s_norm_r = ParagraphStyle(
            "NormRight", fontName="Times-Roman", fontSize=9.5 * sf,
            alignment=TA_RIGHT, leading=12 * sf,
        )
        s_ital_l = ParagraphStyle(
            "ItalLeft", fontName="Times-Italic", fontSize=9.5 * sf, leading=12 * sf,
        )
        s_ital_r = ParagraphStyle(
            "ItalRight", fontName="Times-Italic", fontSize=9.5 * sf,
            alignment=TA_RIGHT, leading=12 * sf,
        )
        s_bullet = ParagraphStyle(
            "Bullet", fontName="Times-Roman", fontSize=9.5 * sf,
            leftIndent=20, firstLineIndent=-14,
            leading=11.5 * sf, spaceAfter=1.5 * sf,
        )
        s_detail = ParagraphStyle(
            "Detail", fontName="Times-Roman", fontSize=9.5 * sf, leading=11.5 * sf,
        )

        no_pad = TableStyle([
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ])

        cw = [aw * 0.65, aw * 0.35]

        def row2(lt, ls, rt, rs, lt_raw=False, rt_raw=False):
            left = lt if lt_raw else safe(lt)
            right = rt if rt_raw else safe(rt)
            tbl = Table(
                [[Paragraph(left, ls), Paragraph(right, rs)]],
                colWidths=cw,
            )
            tbl.setStyle(no_pad)
            return tbl

        def bullet_para(text):
            bchar = (
                f'<font name="{BULLET_FONT}" size="{BULLET_FONT_SIZE * sf}">'
                f"{BULLET_CHAR}</font>"
            )
            return Paragraph(f"{bchar}&nbsp;&nbsp;{safe(text)}", s_bullet)

        # ── Construcción de la historia ─────────────────────────
        story = []

        story.append(Paragraph(safe(data.get("name", "")), s_name))

        # Contacto: linkedin/github/email como hiperv\u00ednculos activos; location/phone texto.
        # Cada parte ya viene escapada, as\u00ed que se pasa a Paragraph SIN volver a envolver en safe().
        contact_parts = []
        for field in ("location", "linkedin", "github", "phone", "email"):
            val = str(data.get(field, "") or "").strip()
            if not val:
                continue
            if field in ("linkedin", "github"):
                contact_parts.append(link(val, val))
            elif field == "email":
                contact_parts.append(link(val, val, "email"))
            else:
                contact_parts.append(safe(val))
        if contact_parts:
            story.append(Paragraph(" \u00b7 ".join(contact_parts), s_contact))

        summary = data.get("summary", "").strip()
        if summary:
            # Paragraph colapsa "\n" a espacio: "...Machine Learning Proven track..."
            # quedaba pegado. El salto entre titular y frase se respeta con <br/>.
            story.append(Paragraph(safe(summary).replace("\n", "<br/>"), s_summary))

        story.append(HRFlowable(
            width="100%", thickness=0.75, color=black,
            spaceBefore=4 * sf, spaceAfter=2 * sf,
        ))

        # ── EXPERIENCIA ──────────────────────────────────────────
        experiences = data.get("experiences", [])
        if experiences:
            story.append(Paragraph(labels["pdf_experience"], s_section))
            story.append(HRFlowable(
                width="100%", thickness=0.5, color=black,
                spaceBefore=1 * sf, spaceAfter=4 * sf,
            ))
            for exp in experiences:
                story.append(row2(
                    exp.get("company", ""), s_bold_l,
                    localize_meta(exp.get("location", ""), lang), s_norm_r,
                ))
                story.append(row2(
                    exp.get("title", ""), s_ital_l,
                    localize_meta(exp.get("dates", ""), lang), s_ital_r,
                ))
                story.append(Spacer(1, 3 * sf))
                bullets_raw = exp.get("bullets", "")
                if isinstance(bullets_raw, list):
                    bullets = bullets_raw
                else:
                    bullets = [b.strip() for b in str(bullets_raw).split("\n")
                               if b.strip()]
                for b in bullets:
                    if b.strip():
                        story.append(bullet_para(b))
                story.append(Spacer(1, 6 * sf))

        # ── PROYECTOS ────────────────────────────────────────────
        projects = data.get("projects", [])
        if projects:
            story.append(Paragraph(labels["pdf_projects"], s_section))
            story.append(HRFlowable(
                width="100%", thickness=0.5, color=black,
                spaceBefore=1 * sf, spaceAfter=4 * sf,
            ))
            for proj in projects:
                name = proj.get("name", "")
                url = str(proj.get("url", "") or "").strip()
                if url:
                    title_text = f"{safe(name)} — {link(url, url)}"
                else:
                    title_text = safe(name)
                story.append(row2(title_text, s_bold_l, "", s_norm_r, lt_raw=True))
                desc = proj.get("description", "").strip()
                if desc:
                    story.append(bullet_para(desc))
                story.append(Spacer(1, 4 * sf))

        # ── EDUCACIÓN ────────────────────────────────────────────
        education = data.get("education", [])
        if education:
            story.append(Paragraph(labels["pdf_education"], s_section))
            story.append(HRFlowable(
                width="100%", thickness=0.5, color=black,
                spaceBefore=1 * sf, spaceAfter=4 * sf,
            ))
            for edu in education:
                story.append(row2(
                    edu.get("institution", ""), s_bold_l,
                    localize_meta(edu.get("location", ""), lang), s_norm_r,
                ))
                story.append(row2(
                    edu.get("degree", ""), s_ital_l,
                    localize_meta(edu.get("date", ""), lang), s_ital_r,
                ))
                details = edu.get("details", "").strip()
                if details:
                    story.append(Paragraph(safe(details), s_detail))
                story.append(Spacer(1, 6 * sf))

        # ── CERTIFICACIONES ──────────────────────────────────────
        certifications = data.get("certifications", [])
        if certifications:
            story.append(Paragraph(labels["pdf_certifications"], s_section))
            story.append(HRFlowable(
                width="100%", thickness=0.5, color=black,
                spaceBefore=1 * sf, spaceAfter=4 * sf,
            ))
            for cert in certifications:
                # Sin "text" → "" (NO el dict): str(dict) imprimiría el repr completo,
                # incluyendo credential_id, que se decidió explícitamente no imprimir.
                text = cert.get("text", "") if isinstance(cert, dict) else str(cert)
                if str(text).strip():
                    story.append(bullet_para(text))

        # ── SKILLS ───────────────────────────────────────────────
        skills = data.get("skills", [])
        if skills:
            story.append(Paragraph(labels["pdf_skills"], s_section))
            story.append(HRFlowable(
                width="100%", thickness=0.5, color=black,
                spaceBefore=1 * sf, spaceAfter=4 * sf,
            ))
            for sk in skills:
                text = sk.get("text", "") if isinstance(sk, dict) else str(sk)
                if str(text).strip():
                    story.append(bullet_para(text))

        # Compilar y comprobar número de páginas
        try:
            doc.build(story)
            buf.seek(0)
            pages = PdfReader(buf).get_num_pages()
            if pages <= 1:
                buf.seek(0)
                return buf, True, sf
            if sf <= 0.76:
                buf.seek(0)
                return buf, False, sf
        except Exception:
            if sf <= 0.76:
                buf.seek(0)
                return buf, False, sf

