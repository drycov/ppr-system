"""Генерация PDF-актов с поддержкой кириллицы"""
from io import BytesIO
from datetime import date, datetime
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT

_FONT_REG = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_registered = False


def _register_fonts():
    global _FONT_REG, _FONT_BOLD, _registered
    if _registered:
        return
    candidates = [
        # Linux
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        # Windows
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("C:/Windows/Fonts/DejaVuSans.ttf", "C:/Windows/Fonts/DejaVuSans-Bold.ttf"),
        # Local project fonts
        (str(Path(__file__).parent / "fonts" / "DejaVuSans.ttf"), str(Path(__file__).parent / "fonts" / "DejaVuSans-Bold.ttf")),
    ]
    for reg, bold in candidates:
        if Path(reg).exists():
            try:
                pdfmetrics.registerFont(TTFont("PPRFont", reg))
                if Path(bold).exists():
                    pdfmetrics.registerFont(TTFont("PPRFont-Bold", bold))
                else:
                    pdfmetrics.registerFont(TTFont("PPRFont-Bold", reg))
                _FONT_REG = "PPRFont"
                _FONT_BOLD = "PPRFont-Bold"
                _registered = True
                return
            except Exception:
                continue
    _registered = True  # fallback Helvetica


def _styles():
    _register_fonts()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleRu", fontName=_FONT_BOLD, fontSize=14, alignment=TA_CENTER, spaceAfter=6))
    styles.add(ParagraphStyle(name="SubRu", fontName=_FONT_REG, fontSize=10, alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle(name="BodyRu", fontName=_FONT_REG, fontSize=10, alignment=TA_LEFT, spaceAfter=4, leading=14))
    styles.add(ParagraphStyle(name="SmallRu", fontName=_FONT_REG, fontSize=8, alignment=TA_LEFT, textColor=colors.grey))
    return styles


def generate_ppr_act(
    plan_id: int,
    title: str,
    object_code: str,
    object_address: str,
    responsible: str,
    planned_date: date,
    fact_date: date,
    work_types: list,
    comment: str = "",
    engineer: str = "",
) -> bytes:
    _register_fonts()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm)
    styles = _styles()
    story = []

    story.append(Paragraph("ТОО «Satory Company ltd»", styles["SubRu"]))
    story.append(Paragraph("филиал в г. Усть-Каменогорск", styles["SubRu"]))
    story.append(Paragraph("Отдел сетей связи (ОСС)", styles["SubRu"]))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f766e")))
    story.append(Spacer(1, 10))
    story.append(Paragraph("АКТ", styles["TitleRu"]))
    story.append(Paragraph("выполненных планово-профилактических работ", styles["TitleRu"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"№ {plan_id} от {(fact_date or date.today()).strftime('%d.%m.%Y')}", styles["SubRu"]))
    story.append(Spacer(1, 12))

    data = [
        ["Объект:", object_code or "—"],
        ["Адрес:", object_address or "—"],
        ["Наименование работ:", title or "ППР"],
        ["Плановая дата:", planned_date.strftime("%d.%m.%Y") if planned_date else "—"],
        ["Фактическая дата:", fact_date.strftime("%d.%m.%Y") if fact_date else "—"],
        ["Ответственный:", responsible or "—"],
    ]
    t = Table(data, colWidths=[45*mm, 125*mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), _FONT_BOLD),
        ("FONTNAME", (1, 0), (1, -1), _FONT_REG),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>Выполненные виды работ:</b>", styles["BodyRu"]))
    for w in (work_types or ["Согласно регламенту ППР"]):
        story.append(Paragraph(f"• {w}", styles["BodyRu"]))
    if comment:
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<b>Примечание:</b> {comment}", styles["BodyRu"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Работы выполнены в полном объёме. Оборудование находится в исправном состоянии.", styles["BodyRu"]))
    story.append(Spacer(1, 20))

    sign = (engineer or responsible or "___________")
    sign_data = [
        ["Исполнитель:", f"_________________ / {sign} /"],
        ["", ""],
        ["Проверил:", "_________________ / _________________ /"],
        ["", ""],
        ["Дата:", (fact_date or date.today()).strftime("%d.%m.%Y")],
    ]
    st = Table(sign_data, colWidths=[40*mm, 130*mm])
    st.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_REG),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(st)
    story.append(Spacer(1, 30))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Paragraph(f"Сформировано системой ППР ОСС/АПК · {datetime.now().strftime('%d.%m.%Y %H:%M')}", styles["SmallRu"]))
    doc.build(story)
    return buffer.getvalue()
