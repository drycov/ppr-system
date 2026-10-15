"""Формирование Excel-отчётов ППР за произвольный период."""
from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session, joinedload

from models import Department, Object, PPRPlan, PPRTemplate


THIN = Border(*( [Side(style="thin")] * 4 ))
HEADER_FILL = PatternFill("solid", fgColor="0F766E")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
TITLE_FONT = Font(bold=True, size=14)
DONE_FILL = PatternFill("solid", fgColor="D1FAE5")
PLANNED_FILL = PatternFill("solid", fgColor="FEF3C7")
OVERDUE_FILL = PatternFill("solid", fgColor="FEE2E2")
FAKE_FILL = PatternFill("solid", fgColor="FECACA")


def _header(ws, row: int, count: int) -> None:
    for col in range(1, count + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN


def export_ppr_period_report(
    db: Session,
    from_date: date,
    to_date: date,
    object_type: str | None = None,
    work_direction: str | None = None,
    department_id: int | None = None,
) -> bytes:
    query = db.query(PPRPlan).options(
        joinedload(PPRPlan.object), joinedload(PPRPlan.template), joinedload(PPRPlan.assignee_user)
    ).filter(PPRPlan.planned_date >= from_date, PPRPlan.planned_date <= to_date)
    if object_type:
        query = query.join(PPRPlan.object).filter(Object.object_type == object_type)
    if department_id is not None:
        query = query.filter(PPRPlan.department_id == department_id)
    if work_direction:
        query = query.join(PPRPlan.template).filter(PPRTemplate.work_direction == work_direction)
    plans = query.order_by(PPRPlan.planned_date, PPRPlan.id).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Задачи ППР"
    ws.merge_cells("A1:K1")
    department = db.query(Department).filter(Department.id == department_id).first() if department_id is not None else None
    period_title = f"Подразделение: {department.name} | " if department else ""
    ws["A1"] = f"ОТЧЁТ О ВЫПОЛНЕНИИ ППР: {period_title}{from_date:%d.%m.%Y} — {to_date:%d.%m.%Y}"
    ws["A1"].font = TITLE_FONT
    ws["A1"].alignment = Alignment(horizontal="center")
    headers = ["№", "Плановая дата", "Фактическая дата", "Объект", "Адрес", "Направление",
               "Работа", "Ответственный", "Статус", "Виды работ", "Комментарий / аудит"]
    for col, value in enumerate(headers, 1):
        ws.cell(row=3, column=col, value=value)
    _header(ws, 3, len(headers))
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:K{max(3, len(plans) + 3)}"

    counts = {"done": 0, "planned": 0, "in_progress": 0, "overdue": 0, "cancelled": 0, "fictitious": 0}
    labels = {"done": "Выполнено", "planned": "Запланировано", "in_progress": "В работе",
              "overdue": "Просрочено", "cancelled": "Отменено"}
    for idx, plan in enumerate(plans, 1):
        comment = plan.comment or ""
        fictitious = "ФИКТИВНАЯ ОТМЕТКА" in comment.upper() or "НЕ ПОДТВЕРЖДЕНО ФАКТИЧЕСКИ" in comment.upper()
        counts[plan.status] = counts.get(plan.status, 0) + 1
        if fictitious:
            counts["fictitious"] += 1
        obj = plan.object
        template = plan.template
        assignee = plan.assignee_user
        values = [
            idx, plan.planned_date, plan.fact_date,
            (obj.code if obj else "—"),
            ((obj.address or obj.name or "") if obj else ""),
            (template.work_direction if template else ""),
            plan.title or (template.name if template else ""),
            plan.responsible or (assignee.full_name if assignee else ""),
            ("ФИКТИВНО ОТМЕЧЕНО" if fictitious else labels.get(plan.status, plan.status)),
            ", ".join(plan.work_types_done or []),
            comment,
        ]
        row = idx + 3
        for col, value in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = THIN
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if col in (2, 3) and value:
                cell.number_format = "DD.MM.YYYY"
            if fictitious:
                cell.fill = FAKE_FILL
            elif plan.status == "done":
                cell.fill = DONE_FILL
            elif plan.status in ("planned", "in_progress"):
                cell.fill = PLANNED_FILL
            elif plan.status == "overdue":
                cell.fill = OVERDUE_FILL
        ws.row_dimensions[row].height = 36

    for i, width in enumerate([6, 14, 14, 18, 38, 20, 38, 28, 22, 28, 60], 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    summary = wb.create_sheet("Сводка")
    summary["A1"] = "Сводка выполнения ППР"
    summary["A1"].font = TITLE_FONT
    summary["A2"] = "Период"
    summary["B2"] = f"{from_date:%d.%m.%Y} — {to_date:%d.%m.%Y}"
    summary["A3"] = "Подразделение"
    summary["B3"] = department.name if department else "Все подразделения"
    summary["A4"] = "Показатель"
    summary["B4"] = "Количество"
    _header(summary, 4, 2)
    rows = [
        ("Всего задач в периоде", len(plans)),
        ("Выполнено (включая фиктивные)", counts["done"]),
        ("Из них отмечено фиктивно", counts["fictitious"]),
        ("Запланировано", counts["planned"]),
        ("В работе", counts["in_progress"]),
        ("Просрочено", counts["overdue"]),
        ("Отменено", counts["cancelled"]),
        ("Доля выполнения, %", round(counts["done"] / len(plans) * 100, 1) if plans else 0),
    ]
    for row, (label, value) in enumerate(rows, 5):
        summary.cell(row, 1, label).border = THIN
        summary.cell(row, 2, value).border = THIN
        if "фиктивно" in label.lower():
            summary.cell(row, 1).fill = FAKE_FILL
            summary.cell(row, 2).fill = FAKE_FILL
    summary.column_dimensions["A"].width = 34
    summary.column_dimensions["B"].width = 28
    summary["A15"] = "Примечание: фиктивные отметки выделены красным и не подтверждают фактическое выполнение работ."
    summary["A15"].alignment = Alignment(wrap_text=True)
    summary.merge_cells("A15:B16")

    output = BytesIO()
    wb.save(output)
    return output.getvalue()
