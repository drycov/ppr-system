"""Генерация PDF-актов на бланке компании с поддержкой кириллицы"""
from io import BytesIO
from datetime import date, datetime
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# Реквизиты бланка (можно переопределить env)
COMPANY = {
    "name": "ТОО «Satory Company ltd»",
    "branch": "Филиал в г. Усть-Каменогорск",
    "dept": "Отдел сетей связи и группа IT (ОСС)",
    "address": "Республика Казахстан, г. Усть-Каменогорск",
    "phone": "",
    "email": "",
}

_FONT_REG = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_registered = False


def _register_fonts():
    global _FONT_REG, _FONT_BOLD, _registered
    if _registered:
        return
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("C:/Windows/Fonts/DejaVuSans.ttf", "C:/Windows/Fonts/DejaVuSans-Bold.ttf"),
        (str(Path(__file__).parent / "fonts" / "DejaVuSans.ttf"), str(Path(__file__).parent / "fonts" / "DejaVuSans-Bold.ttf")),
    ]
    for reg, bold in candidates:
        if Path(reg).exists():
            try:
                pdfmetrics.registerFont(TTFont("PPRFont", reg))
                pdfmetrics.registerFont(TTFont("PPRFont-Bold", bold if Path(bold).exists() else reg))
                _FONT_REG, _FONT_BOLD = "PPRFont", "PPRFont-Bold"
                _registered = True
                return
            except Exception:
                continue
    _registered = True


def _styles():
    _register_fonts()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="OrgName", fontName=_FONT_BOLD, fontSize=12, alignment=TA_CENTER, spaceAfter=2))
    styles.add(ParagraphStyle(name="OrgSub", fontName=_FONT_REG, fontSize=9, alignment=TA_CENTER, spaceAfter=1, textColor=colors.HexColor("#334155")))
    styles.add(ParagraphStyle(name="TitleRu", fontName=_FONT_BOLD, fontSize=14, alignment=TA_CENTER, spaceAfter=4, spaceBefore=6))
    styles.add(ParagraphStyle(name="SubRu", fontName=_FONT_REG, fontSize=10, alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle(name="BodyRu", fontName=_FONT_REG, fontSize=10, alignment=TA_LEFT, spaceAfter=3, leading=14))
    styles.add(ParagraphStyle(name="SmallRu", fontName=_FONT_REG, fontSize=8, alignment=TA_LEFT, textColor=colors.grey))
    styles.add(ParagraphStyle(name="RightRu", fontName=_FONT_REG, fontSize=9, alignment=TA_RIGHT))
    return styles


def _header(styles):
    """Шапка бланка: логотип (если есть) + реквизиты."""
    story = []
    logo = Path(__file__).parent / "static" / "logo.png"
    if logo.exists():
        try:
            img = Image(str(logo), width=28*mm, height=28*mm)
            head = Table([[img, [
                Paragraph(COMPANY["name"], styles["OrgName"]),
                Paragraph(COMPANY["branch"], styles["OrgSub"]),
                Paragraph(COMPANY["dept"], styles["OrgSub"]),
                Paragraph(COMPANY["address"], styles["OrgSub"]),
            ]]], colWidths=[32*mm, 140*mm])
            head.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(head)
        except Exception:
            story.append(Paragraph(COMPANY["name"], styles["OrgName"]))
            story.append(Paragraph(COMPANY["branch"], styles["OrgSub"]))
            story.append(Paragraph(COMPANY["dept"], styles["OrgSub"]))
    else:
        story.append(Paragraph(COMPANY["name"], styles["OrgName"]))
        story.append(Paragraph(COMPANY["branch"], styles["OrgSub"]))
        story.append(Paragraph(COMPANY["dept"], styles["OrgSub"]))
        story.append(Paragraph(COMPANY["address"], styles["OrgSub"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0f766e")))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#0f766e"), spaceBefore=1))
    story.append(Spacer(1, 8))
    return story


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
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm, topMargin=12*mm, bottomMargin=15*mm,
    )
    styles = _styles()
    story = []
    story.extend(_header(styles))

    story.append(Paragraph("АКТ", styles["TitleRu"]))
    story.append(Paragraph("выполненных планово-профилактических работ (ППР)", styles["TitleRu"]))
    story.append(Paragraph(
        f"№ ППР-{plan_id} от {(fact_date or date.today()).strftime('%d.%m.%Y')}",
        styles["SubRu"],
    ))
    story.append(Spacer(1, 8))

    story.append(Paragraph(
        "Настоящий акт составлен о том, что выполнены планово-профилактические работы "
        "в соответствии с Положением о ППР на оборудовании системы сети связи.",
        styles["BodyRu"],
    ))
    story.append(Spacer(1, 6))

    data = [
        ["Объект (код):", object_code or "—"],
        ["Адрес / местоположение:", object_address or "—"],
        ["Наименование работ:", title or "ППР"],
        ["Плановая дата:", planned_date.strftime("%d.%m.%Y") if planned_date else "—"],
        ["Фактическая дата:", (fact_date or date.today()).strftime("%d.%m.%Y")],
        ["Ответственный исполнитель:", responsible or "—"],
    ]
    t = Table(data, colWidths=[50*mm, 120*mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), _FONT_BOLD),
        ("FONTNAME", (1, 0), (1, -1), _FONT_REG),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0fdfa")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#99f6e4")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ccfbf1")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Перечень выполненных работ:</b>", styles["BodyRu"]))
    works = work_types or ["Согласно регламенту ППР ОСС / АПК ИНТЕГРАЦИЯ"]
    for w in works:
        story.append(Paragraph(f"• {w}", styles["BodyRu"]))
    if comment:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Примечание:</b> {comment}", styles["BodyRu"]))

    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Работы выполнены в полном объёме. Замечаний по состоянию оборудования на момент "
        "составления акта не имеется / имеются (нужное подчеркнуть).",
        styles["BodyRu"],
    ))
    story.append(Spacer(1, 16))

    sign = engineer or responsible or "____________________"
    sign_data = [
        [Paragraph("<b>Исполнитель:</b>", styles["BodyRu"]),
         Paragraph(f"_________________ / {sign} /", styles["BodyRu"])],
        [Paragraph("<b>Проверил:</b>", styles["BodyRu"]),
         Paragraph("_________________ / _________________ /", styles["BodyRu"])],
        [Paragraph("<b>Утвердил:</b>", styles["BodyRu"]),
         Paragraph("_________________ / _________________ /", styles["BodyRu"])],
        [Paragraph("<b>Дата:</b>", styles["BodyRu"]),
         Paragraph((fact_date or date.today()).strftime("%d.%m.%Y"), styles["BodyRu"])],
    ]
    st = Table(sign_data, colWidths=[40*mm, 130*mm])
    st.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(st)

    story.append(Spacer(1, 24))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Paragraph(
        f"Документ сформирован системой учёта ППР ОСС/АПК · {datetime.now().strftime('%d.%m.%Y %H:%M')} · "
        f"экземпляр электронный",
        styles["SmallRu"],
    ))
    doc.build(story)
    return buffer.getvalue()
