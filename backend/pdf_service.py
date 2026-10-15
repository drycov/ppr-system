"""Генерация PDF-актов выполненных ППР"""
from io import BytesIO
from datetime import date, datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="TitleRu",
        fontName="Helvetica-Bold",
        fontSize=14,
        alignment=TA_CENTER,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="SubRu",
        fontName="Helvetica",
        fontSize=10,
        alignment=TA_CENTER,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="BodyRu",
        fontName="Helvetica",
        fontSize=10,
        alignment=TA_LEFT,
        spaceAfter=4,
        leading=14,
    ))
    styles.add(ParagraphStyle(
        name="SmallRu",
        fontName="Helvetica",
        fontSize=8,
        alignment=TA_LEFT,
        textColor=colors.grey,
    ))
    styles.add(ParagraphStyle(
        name="SignRu",
        fontName="Helvetica",
        fontSize=10,
        alignment=TA_LEFT,
        spaceBefore=8,
    ))
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
    """Акт выполненных планово-профилактических работ"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = _styles()
    story = []

    # Шапка
    story.append(Paragraph("ТОО «Satory Company ltd»", styles["SubRu"]))
    story.append(Paragraph("филиал в г. Усть-Каменогорск", styles["SubRu"]))
    story.append(Paragraph("Отдел сетей связи (ОСС)", styles["SubRu"]))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f766e")))
    story.append(Spacer(1, 10))

    story.append(Paragraph("АКТ", styles["TitleRu"]))
    story.append(Paragraph("выполненных планово-профилактических работ", styles["TitleRu"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"№ {plan_id} от {fact_date.strftime('%d.%m.%Y')}", styles["SubRu"]))
    story.append(Spacer(1, 12))

    # Основная информация
    data = [
        ["Объект:", f"{object_code}"],
        ["Адрес:", object_address or "—"],
        ["Наименование работ:", title or "ППР"],
        ["Плановая дата:", planned_date.strftime("%d.%m.%Y") if planned_date else "—"],
        ["Фактическая дата:", fact_date.strftime("%d.%m.%Y") if fact_date else "—"],
        ["Ответственный:", responsible or "—"],
    ]
    t = Table(data, colWidths=[45 * mm, 125 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#334155")),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    # Виды работ
    story.append(Paragraph("<b>Выполненные виды работ:</b>", styles["BodyRu"]))
    if work_types:
        for w in work_types:
            story.append(Paragraph(f"• {w}", styles["BodyRu"]))
    else:
        story.append(Paragraph("• Согласно регламенту ППР", styles["BodyRu"]))
    story.append(Spacer(1, 8))

    if comment:
        story.append(Paragraph(f"<b>Примечание:</b> {comment}", styles["BodyRu"]))
        story.append(Spacer(1, 8))

    story.append(Paragraph(
        "Работы выполнены в полном объёме. Оборудование находится в исправном состоянии.",
        styles["BodyRu"],
    ))
    story.append(Spacer(1, 20))

    # Подписи
    sign_data = [
        ["Исполнитель:", "_________________ / " + (engineer or responsible or "___________") + " /"],
        ["", ""],
        ["Проверил:", "_________________ / _________________ /"],
        ["", ""],
        ["Дата:", fact_date.strftime("%d.%m.%Y") if fact_date else "__________"],
    ]
    st = Table(sign_data, colWidths=[40 * mm, 130 * mm])
    st.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(st)
    story.append(Spacer(1, 30))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Paragraph(
        f"Сформировано системой ППР ОСС/АПК · {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        styles["SmallRu"],
    ))

    doc.build(story)
    return buffer.getvalue()
