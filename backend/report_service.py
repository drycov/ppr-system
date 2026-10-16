"""Формирование Excel-отчётов ППР за произвольный период."""
from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session, joinedload

from models import DailyCheck, Department, Object, PPRPlan, PPRTemplate


NETWORK_OBJECT_TYPES = {
    "network", "us", "cod", "core_router", "core_switch",
    "access_switch", "edge_router", "wifi_controller", "server", "ups",
}


def _is_network_department(department: Department | None) -> bool:
    if not department:
        return False
    identity = f"{department.name or ''} {department.code or ''}".casefold()
    return "сет" in identity or "network" in identity


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

    # Полный реестр не зависит от наличия задач ППР за выбранный период.
    objects_query = db.query(Object)
    if object_type:
        objects_query = objects_query.filter(Object.object_type == object_type)
    objects = objects_query.order_by(Object.object_type, Object.code).all()
    daily_checks = (
        db.query(DailyCheck)
        .filter(DailyCheck.check_date >= from_date, DailyCheck.check_date <= to_date)
        .order_by(DailyCheck.check_date, DailyCheck.engineer, DailyCheck.id)
        .all()
    )

    departments = db.query(Department).all()
    departments_by_id = {item.id: item.name for item in departments}
    network_department_ids = {item.id for item in departments if _is_network_department(item)}
    active_objects = db.query(Object).filter(Object.status == "active").order_by(Object.object_type, Object.code).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "Задачи ППР"
    ws.merge_cells("A1:M1")
    department = db.query(Department).filter(Department.id == department_id).first() if department_id is not None else None
    period_title = f"Подразделение: {department.name} | " if department else ""
    ws["A1"] = f"ОТЧЁТ О ВЫПОЛНЕНИИ ППР: {period_title}{from_date:%d.%m.%Y} — {to_date:%d.%m.%Y}"
    ws["A1"].font = TITLE_FONT
    ws["A1"].alignment = Alignment(horizontal="center")
    headers = ["№", "Плановая дата", "Фактическая дата", "Объект", "Адрес", "Подразделение", "Направление",
               "Работа", "Ответственный", "Статус", "Виды работ", "Комментарий / аудит", "Перечень объектов"]
    for col, value in enumerate(headers, 1):
        ws.cell(row=3, column=col, value=value)
    _header(ws, 3, len(headers))
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:M{max(3, len(report_rows) + 3)}"

    counts = {"done": 0, "planned": 0, "in_progress": 0, "overdue": 0, "cancelled": 0, "fictitious": 0}
    labels = {"done": "Выполнено", "planned": "Запланировано", "in_progress": "В работе",
              "overdue": "Просрочено", "cancelled": "Отменено"}

    # Общая задача сетевого отдела в UI разворачивается в Excel в отдельную строку
    # на каждый охваченный объект. Запись в БД остаётся единой.
    report_rows = []
    for plan in plans:
        obj = plan.object
        if obj is None and plan.department_id in network_department_ids:
            template = plan.template
            object_types = (template.object_types or []) if template else []
            if not object_types or object_types == ["network"]:
                covered_objects = [item for item in active_objects if item.object_type in NETWORK_OBJECT_TYPES]
            else:
                covered_types = set(object_types)
                if "network" in covered_types:
                    covered_types.update(NETWORK_OBJECT_TYPES)
                covered_objects = [item for item in active_objects if item.object_type in covered_types]
            if covered_objects:
                report_rows.extend((plan, item) for item in covered_objects)
            else:
                report_rows.append((plan, None))
        else:
            report_rows.append((plan, obj))

    for idx, (plan, obj) in enumerate(report_rows, 1):
        comment = plan.comment or ""
        fictitious = "ФИКТИВНАЯ ОТМЕТКА" in comment.upper() or "НЕ ПОДТВЕРЖДЕНО ФАКТИЧЕСКИ" in comment.upper()
        counts[plan.status] = counts.get(plan.status, 0) + 1
        if fictitious:
            counts["fictitious"] += 1
        template = plan.template
        assignee = plan.assignee_user
        covered_objects = [obj] if obj else []
        object_list = (
            f"{obj.code} — {obj.name or obj.address or ''}".rstrip(" —")
            if obj else ""
        )
        values = [
            idx, plan.planned_date, plan.fact_date,
            (obj.code if obj else ("Общая задача" if covered_objects else "—")),
            ((obj.address or obj.name or "") if obj else ""),
            departments_by_id.get(plan.department_id, "—"),
            (template.work_direction if template else ""),
            plan.title or (template.name if template else ""),
            plan.responsible or (assignee.full_name if assignee else ""),
            ("ФИКТИВНО ОТМЕЧЕНО" if fictitious else labels.get(plan.status, plan.status)),
            ", ".join(plan.work_types_done or []),
            comment,
            object_list,
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

    for i, width in enumerate([6, 14, 14, 18, 38, 24, 20, 38, 28, 22, 28, 60, 72], 1):
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
        ("Всего объектов в реестре", len(objects)),
        ("Активных объектов", sum(1 for obj in objects if obj.status == "active")),
        ("Объектов типа ЦОД", sum(1 for obj in objects if obj.object_type == "cod")),
        ("Записей ежедневного контроля", len(daily_checks)),
        ("Всего задач в периоде", len(report_rows)),
        ("Выполнено (включая фиктивные)", counts["done"]),
        ("Из них отмечено фиктивно", counts["fictitious"]),
        ("Запланировано", counts["planned"]),
        ("В работе", counts["in_progress"]),
        ("Просрочено", counts["overdue"]),
        ("Отменено", counts["cancelled"]),
        ("Доля выполнения, %", round(counts["done"] / len(report_rows) * 100, 1) if report_rows else 0),
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

    # Отдельный лист со всеми объектами: объекты без задач тоже должны присутствовать в отчёте.
    registry = wb.create_sheet("Все объекты")
    registry_headers = ["№", "Код", "Наименование", "Тип объекта", "Адрес", "Статус",
                        "Камер", "Ответственный по умолчанию", "Задач за период",
                        "Выполнено", "Запланировано / в работе", "Просрочено", "Работы по ЦОД"]
    registry.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(registry_headers))
    registry["A1"] = f"ПОЛНЫЙ РЕЕСТР ОБЪЕКТОВ СИСТЕМЫ: {from_date:%d.%m.%Y} — {to_date:%d.%m.%Y}"
    registry["A1"].font = TITLE_FONT
    registry["A1"].alignment = Alignment(horizontal="center")
    for col, value in enumerate(registry_headers, 1):
        registry.cell(row=3, column=col, value=value)
    _header(registry, 3, len(registry_headers))
    registry.freeze_panes = "A4"
    registry.auto_filter.ref = f"A3:M{max(3, len(objects) + 3)}"
    type_names = {
        "camera_integration": "ИНТ (камеры)", "ovn": "ОВН", "voles": "ВОЛС", "sip": "СИП",
        "us": "УС (узел связи)", "cod": "ЦОД", "core_router": "Роутер ядра",
        "core_switch": "Коммутатор ядра", "access_switch": "Коммутатор доступа",
        "edge_router": "Граничный роутер", "wifi_controller": "Контроллер Wi-Fi",
        "server": "Сервер", "ups": "ИБП", "network": "Сеть ОСС (общее)", "other": "Прочее",
    }
    plans_by_object = {}
    for plan in plans:
        if plan.object_id is not None:
            plans_by_object.setdefault(plan.object_id, []).append(plan)
    for idx, obj in enumerate(objects, 1):
        object_plans = plans_by_object.get(obj.id, [])
        cod_work = [
            plan for plan in object_plans
            if obj.object_type == "cod"
            and ((plan.template and (plan.template.code or "").startswith("DC-"))
                 or "ЦОД" in (plan.title or "").upper())
        ]
        row_values = [
            idx, obj.code, obj.name or "", type_names.get(obj.object_type, obj.object_type or "—"),
            obj.address or "", obj.status or "", obj.cameras_count or 0, obj.responsible_default or "",
            len(object_plans),
            sum(1 for plan in object_plans if plan.status == "done"),
            sum(1 for plan in object_plans if plan.status in ("planned", "in_progress")),
            sum(1 for plan in object_plans if plan.status == "overdue"),
            "; ".join(sorted({plan.title or (plan.template.name if plan.template else "") for plan in cod_work})),
        ]
        for col, value in enumerate(row_values, 1):
            cell = registry.cell(row=idx + 3, column=col, value=value)
            cell.border = THIN
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for col, width in enumerate([6, 16, 28, 24, 42, 16, 10, 28, 14, 12, 22, 12, 52], 1):
        registry.column_dimensions[get_column_letter(col)].width = width

    # История ежедневного контроля включается в тот же Excel-файл.
    daily_ws = wb.create_sheet("Ежедневный контроль")
    daily_headers = ["№", "Дата", "Сотрудник", "Мониторинг", "Критичные сервисы",
                     "Журналы / безопасность", "Резервные копии", "Загрузка каналов",
                     "ИБП", "Инциденты зарегистрированы", "Чек-лист", "Примечания"]
    daily_ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(daily_headers))
    daily_ws["A1"] = f"ЖУРНАЛ ЕЖЕДНЕВНОГО КОНТРОЛЯ: {from_date:%d.%m.%Y} — {to_date:%d.%m.%Y}"
    daily_ws["A1"].font = TITLE_FONT
    daily_ws["A1"].alignment = Alignment(horizontal="center")
    for col, value in enumerate(daily_headers, 1):
        daily_ws.cell(row=3, column=col, value=value)
    _header(daily_ws, 3, len(daily_headers))
    daily_ws.freeze_panes = "A4"
    daily_ws.auto_filter.ref = f"A3:L{max(3, len(daily_checks) + 3)}"
    for idx, check in enumerate(daily_checks, 1):
        checklist = check.checklist or []
        checklist_text = "; ".join(
            f"{item.get('name') or item.get('code') or 'Пункт'}: "
            f"{'да' if item.get('done') else item.get('status') or 'нет'}"
            + (f" ({item.get('note')})" if item.get('note') else "")
            for item in checklist if isinstance(item, dict)
        )
        values = [
            idx, check.check_date, check.engineer or "", check.monitoring_dashboard or "",
            check.critical_services or "", check.logs_security or "", check.config_backups or "",
            check.channel_utilization or "", check.ups_status or "",
            "Да" if check.incidents_logged else "Нет", checklist_text, check.notes or "",
        ]
        for col, value in enumerate(values, 1):
            cell = daily_ws.cell(row=idx + 3, column=col, value=value)
            cell.border = THIN
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if col == 2 and value:
                cell.number_format = "DD.MM.YYYY"
    for col, width in enumerate([6, 14, 28, 18, 20, 24, 18, 18, 12, 22, 60, 50], 1):
        daily_ws.column_dimensions[get_column_letter(col)].width = width

    output = BytesIO()
    wb.save(output)
    return output.getvalue()
