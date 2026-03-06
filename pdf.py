"""
Generación de PDF en formato Harvard para el CV Generator.
"""

import os
from io import BytesIO
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, HRFlowable,
)
from reportlab.lib.colors import black
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from i18n import LANG


# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE FUENTES
# ═══════════════════════════════════════════════════════════════

BULLET_CHAR = "\u2022"
BULLET_FONT = "Times-Roman"
BULLET_FONT_SIZE = 10

_DEJAVU_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/DejaVuSans.ttf",
    os.path.expanduser("~/.fonts/DejaVuSans.ttf"),
    "C:/Windows/Fonts/DejaVuSans.ttf",
]
for _p in _DEJAVU_PATHS:
    if os.path.exists(_p):
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSans", _p))
            BULLET_CHAR = "\u25CF"
            BULLET_FONT = "DejaVuSans"
            BULLET_FONT_SIZE = 7
            break
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def safe(text: str) -> str:
    """Escapa caracteres especiales XML para uso seguro en PDF."""
    return xml_escape(str(text or ""))


# ═══════════════════════════════════════════════════════════════
# GENERACIÓN DE PDF
# ═══════════════════════════════════════════════════════════════

def generate_cv_pdf(data: dict, lang: str = "es") -> BytesIO:
    """Genera un PDF de CV en formato Harvard."""

    labels = LANG.get(lang, LANG["es"])

    buf = BytesIO()
    pw, ph = letter
    ml = mr = 0.7 * inch
    mt = mb = 0.5 * inch
    aw = pw - ml - mr

    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=mt, bottomMargin=mb,
        leftMargin=ml, rightMargin=mr,
    )

    # ── Estilos ──────────────────────────────────────────────
    s_name = ParagraphStyle(
        "Name", fontName="Times-Bold", fontSize=16,
        alignment=TA_CENTER, spaceAfter=4, leading=20,
    )
    s_contact = ParagraphStyle(
        "Contact", fontName="Times-Roman", fontSize=9,
        alignment=TA_CENTER, spaceAfter=4, leading=12,
    )
    s_summary = ParagraphStyle(
        "Summary", fontName="Times-Roman", fontSize=9.5,
        alignment=TA_JUSTIFY, spaceAfter=2, leading=12,
    )
    s_section = ParagraphStyle(
        "Section", fontName="Times-Bold", fontSize=11,
        spaceBefore=6, spaceAfter=0, leading=14,
    )
    s_bold_l = ParagraphStyle(
        "BoldLeft", fontName="Times-Bold", fontSize=10, leading=13,
    )
    s_norm_r = ParagraphStyle(
        "NormRight", fontName="Times-Roman", fontSize=10,
        alignment=TA_RIGHT, leading=13,
    )
    s_ital_l = ParagraphStyle(
        "ItalLeft", fontName="Times-Italic", fontSize=10, leading=13,
    )
    s_ital_r = ParagraphStyle(
        "ItalRight", fontName="Times-Italic", fontSize=10,
        alignment=TA_RIGHT, leading=13,
    )
    s_bullet = ParagraphStyle(
        "Bullet", fontName="Times-Roman", fontSize=10,
        leftIndent=20, firstLineIndent=-14,
        leading=12, spaceAfter=2,
    )
    s_detail = ParagraphStyle(
        "Detail", fontName="Times-Roman", fontSize=10, leading=12,
    )

    no_pad = TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ])

    cw = [aw * 0.65, aw * 0.35]

    def row2(lt, ls, rt, rs):
        tbl = Table(
            [[Paragraph(safe(lt), ls), Paragraph(safe(rt), rs)]],
            colWidths=cw,
        )
        tbl.setStyle(no_pad)
        return tbl

    def bullet_para(text):
        bchar = (
            f'<font name="{BULLET_FONT}" size="{BULLET_FONT_SIZE}">'
            f"{BULLET_CHAR}</font>"
        )
        return Paragraph(f"{bchar}&nbsp;&nbsp;{safe(text)}", s_bullet)

    # ── Construcción ─────────────────────────────────────────
    story = []

    story.append(Paragraph(safe(data.get("name", "")), s_name))

    contact_fields = ["location", "linkedin", "phone", "email"]
    parts = [data.get(k, "") for k in contact_fields]
    contact_str = " \u2022 ".join(p.strip() for p in parts if p.strip())
    story.append(Paragraph(safe(contact_str), s_contact))

    summary = data.get("summary", "").strip()
    if summary:
        story.append(Paragraph(safe(summary), s_summary))

    story.append(HRFlowable(
        width="100%", thickness=0.75, color=black,
        spaceBefore=4, spaceAfter=2,
    ))

    # ── EXPERIENCIA ──────────────────────────────────────────
    experiences = data.get("experiences", [])
    if experiences:
        story.append(Paragraph(labels["pdf_experience"], s_section))
        story.append(HRFlowable(
            width="100%", thickness=0.5, color=black,
            spaceBefore=1, spaceAfter=4,
        ))
        for exp in experiences:
            story.append(row2(
                exp.get("company", ""), s_bold_l,
                exp.get("location", ""), s_norm_r,
            ))
            story.append(row2(
                exp.get("title", ""), s_ital_l,
                exp.get("dates", ""), s_ital_r,
            ))
            story.append(Spacer(1, 3))
            bullets_raw = exp.get("bullets", "")
            if isinstance(bullets_raw, list):
                bullets = bullets_raw
            else:
                bullets = [b.strip() for b in str(bullets_raw).split("\n")
                           if b.strip()]
            for b in bullets:
                if b.strip():
                    story.append(bullet_para(b))
            story.append(Spacer(1, 6))

    # ── EDUCACIÓN ────────────────────────────────────────────
    education = data.get("education", [])
    if education:
        story.append(Paragraph(labels["pdf_education"], s_section))
        story.append(HRFlowable(
            width="100%", thickness=0.5, color=black,
            spaceBefore=1, spaceAfter=4,
        ))
        for edu in education:
            story.append(row2(
                edu.get("institution", ""), s_bold_l,
                edu.get("location", ""), s_norm_r,
            ))
            story.append(row2(
                edu.get("degree", ""), s_ital_l,
                edu.get("date", ""), s_ital_r,
            ))
            details = edu.get("details", "").strip()
            if details:
                story.append(Paragraph(safe(details), s_detail))
            story.append(Spacer(1, 6))

    # ── SKILLS ───────────────────────────────────────────────
    skills = data.get("skills", [])
    if skills:
        story.append(Paragraph(labels["pdf_skills"], s_section))
        story.append(HRFlowable(
            width="100%", thickness=0.5, color=black,
            spaceBefore=1, spaceAfter=4,
        ))
        for sk in skills:
            text = sk.get("text", sk) if isinstance(sk, dict) else str(sk)
            if text.strip():
                story.append(bullet_para(text))

    doc.build(story)
    buf.seek(0)
    return buf
