"""PDF сводки для психиатра (reportlab, шрифт DejaVu с кириллицей)."""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from xml.sax.saxutils import escape

FONTS = Path(__file__).parent / "fonts"
_ready = False

TITLES = {
    "complaints_and_symptoms": "Текущие жалобы и симптомы",
    "functioning": "Влияние на функционирование",
    "scales": "Баллы и даты шкал",
    "previous_episodes_and_treatment": "Предыдущие эпизоды и лечение",
    "current_medications": "Текущие препараты и дозировки",
    "comorbidities_allergies_adverse_events": "Сопутствующие заболевания, аллергии, нежелательные явления",
    "self_report_dynamics": "Динамика самоотчётов",
    "risks": "Данные о рисках",
    "warnings_and_basis": "Предупреждения и их основания",
    "decisions_already_taken": "Уже принятые врачом решения",
}


def _setup() -> None:
    global _ready
    if _ready:
        return
    pdfmetrics.registerFont(TTFont("DV", str(FONTS / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DV-B", str(FONTS / "DejaVuSans-Bold.ttf")))
    _ready = True


def _lines(v: Any, indent: int = 0) -> List[str]:
    pad = "&nbsp;" * (indent * 4)
    out: List[str] = []
    if isinstance(v, dict):
        for k, x in v.items():
            if isinstance(x, (dict, list)) and x:
                out.append("%s<b>%s</b>" % (pad, escape(str(k))))
                out += _lines(x, indent + 1)
            else:
                out.append("%s%s: %s" % (pad, escape(str(k)), escape("—" if x in (None, "", [], {}) else str(x))))
    elif isinstance(v, list):
        for x in v:
            if isinstance(x, (dict, list)):
                out += _lines(x, indent + 1)
                out.append("")
            else:
                out.append("%s• %s" % (pad, escape(str(x))))
    else:
        out.append(pad + escape(str(v)))
    return out


def summary_pdf(summary: Dict[str, Any]) -> bytes:
    """Короткая читаемая сводка: заголовок, блоки обычным текстом, одна строка-оговорка."""
    _setup()
    from .summary import readable
    blocks = summary.get("readable") or readable(summary)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=summary["title"], author="Клинический компас")
    h1 = ParagraphStyle("h1", fontName="DV-B", fontSize=16, leading=20, spaceAfter=2)
    h2 = ParagraphStyle("h2", fontName="DV-B", fontSize=11, leading=14, spaceBefore=9, spaceAfter=2)
    body = ParagraphStyle("b", fontName="DV", fontSize=10, leading=14, spaceAfter=2)
    small = ParagraphStyle("s", fontName="DV", fontSize=8.5, leading=11)
    from datetime import datetime
    when = datetime.fromisoformat(summary["generated_at"]).strftime("%d.%m.%Y %H:%M")
    st: List[Any] = [Paragraph("Сводка для психиатра", h1),
                     Paragraph("Пациент %s · %s" % (escape(summary["patient"]["code"]), when), small)]
    for b in blocks:
        st.append(Paragraph(escape(b["title"]), h2))
        for ln in b["lines"]:
            st.append(Paragraph(escape(ln), body))
    st.append(Spacer(1, 10))
    st.append(Paragraph(escape(summary["disclaimer"]), small))
    doc.build(st)
    return buf.getvalue()
