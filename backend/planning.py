"""Автоматическое планирование ППР по периодичности"""
from datetime import date, timedelta
from calendar import monthrange
from sqlalchemy.orm import Session
from models import Object, PPRTemplate, PPRPlan


PERIOD_DAYS = {
    "daily": 1,
    "monthly": 30,
    "quarterly": 90,
    "semi_annual": 180,
    "twice_year": 180,
    "annual": 365,
}


def next_planned_date(periodicity: str, from_date: date = None) -> date:
    """Ближайшая плановая дата от from_date (по умолчанию сегодня)"""
    base = from_date or date.today()
    days = PERIOD_DAYS.get(periodicity, 30)
    if periodicity == "monthly":
        # 1-е число следующего месяца
        if base.month == 12:
            return date(base.year + 1, 1, 1)
        return date(base.year, base.month + 1, 1)
    if periodicity == "quarterly":
        q = (base.month - 1) // 3
        next_q_month = (q + 1) * 3 + 1
        if next_q_month > 12:
            return date(base.year + 1, 1, 1)
        return date(base.year, next_q_month, 1)
    if periodicity in ("semi_annual", "twice_year"):
        if base.month < 7:
            return date(base.year, 7, 1)
        return date(base.year + 1, 1, 1)
    if periodicity == "annual":
        return date(base.year + 1, 1, 1)
    return base + timedelta(days=days)


def generate_plans_for_period(
    db: Session,
    year: int,
    month: int,
    object_types: list = None,
    only_without_plan: bool = True,
) -> dict:
    """
    Создаёт задачи ППР на указанный месяц для объектов,
    у которых есть подходящий шаблон по типу и периодичности.
    """
    created = 0
    skipped = 0
    errors = []

    templates = db.query(PPRTemplate).filter(PPRTemplate.is_active == True).all()
    # Группируем шаблоны по object_type
    templates_by_type = {}
    for t in templates:
        for ot in (t.object_types or []):
            templates_by_type.setdefault(ot, []).append(t)

    q = db.query(Object).filter(Object.status == "active")
    if object_types:
        q = q.filter(Object.object_type.in_(object_types))
    objects = q.all()

    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])

    for obj in objects:
        relevant = templates_by_type.get(obj.object_type, [])
        if not relevant:
            # Для камер — шаблоны 7.5-7.8 / monthly
            if obj.object_type in ("camera_integration", "ovn"):
                relevant = [t for t in templates if t.code in ("7.5", "7.6", "7.7", "7.8") or t.periodicity == "monthly"]
            elif obj.object_type == "voles":
                relevant = [t for t in templates if "11" in t.code or t.periodicity == "twice_year"]

        if not relevant:
            continue

        # Берём один «главный» шаблон (первый monthly / подходящий)
        template = relevant[0]
        # Для камер — объединённая задача с видами 7.5-7.8
        work_codes = []
        if obj.object_type in ("camera_integration", "ovn"):
            work_codes = ["7.5", "7.6", "7.7", "7.8"]
            title = f"ППР {obj.code} — {month:02d}.{year}"
        else:
            work_codes = template.work_items or [template.code]
            title = f"{template.name} — {obj.code}"

        # Проверяем, нет ли уже плана на этот месяц
        if only_without_plan:
            existing = db.query(PPRPlan).filter(
                PPRPlan.object_id == obj.id,
                PPRPlan.planned_date >= month_start,
                PPRPlan.planned_date <= month_end,
                PPRPlan.status != "cancelled",
            ).first()
            if existing:
                skipped += 1
                continue

        # Распределяем даты внутри месяца (чтобы не все в один день)
        day = min(5 + (obj.id % 20), month_end.day)
        planned = date(year, month, day)

        plan = PPRPlan(
            object_id=obj.id,
            template_id=template.id,
            title=title,
            planned_date=planned,
            responsible=obj.responsible_default or "Инженер ОСС",
            status="planned",
            work_types_done=[],
            comment=None,
        )
        db.add(plan)
        created += 1

    db.commit()
    return {
        "created": created,
        "skipped": skipped,
        "year": year,
        "month": month,
        "message": f"Создано {created} задач, пропущено (уже есть) {skipped}",
    }


def mark_overdue(db: Session) -> int:
    """Помечает просроченные задачи"""
    today = date.today()
    plans = db.query(PPRPlan).filter(
        PPRPlan.status == "planned",
        PPRPlan.planned_date < today,
    ).all()
    for p in plans:
        p.status = "overdue"
    db.commit()
    return len(plans)
