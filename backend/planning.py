"""Автоматическое планирование ППР по периодичности и графику дежурств"""
from datetime import date, timedelta
from calendar import monthrange
from sqlalchemy.orm import Session
from models import Object, PPRTemplate, PPRPlan, User, DutySchedule


PERIOD_DAYS = {
    "daily": 1,
    "monthly": 30,
    "quarterly": 90,
    "semi_annual": 180,
    "twice_year": 180,
    "annual": 365,
}


def get_duty_user(db: Session, on_date: date) -> User | None:
    """Кто дежурит в указанный день (первый по смене day/full)."""
    duty = (
        db.query(DutySchedule)
        .filter(DutySchedule.duty_date == on_date)
        .order_by(DutySchedule.id)
        .first()
    )
    if duty:
        return duty.user
    return None


def get_round_robin_engineer(db: Session, day_index: int) -> User | None:
    """Распределение по кругу среди активных исполнителей ППР."""
    engineers = (
        db.query(User)
        .filter(User.is_active == True, User.can_do_ppr == True, User.role.in_(["engineer", "head", "admin"]))
        .order_by(User.id)
        .all()
    )
    if not engineers:
        return None
    return engineers[day_index % len(engineers)]


def resolve_assignee(db: Session, planned: date, obj_index: int) -> tuple:
    """
    Назначить исполнителя:
    1) дежурный на planned_date
    2) иначе round-robin по инженерам
    Возвращает (User|None, assigned_by_duty: bool, responsible_str)
    """
    duty_user = get_duty_user(db, planned)
    if duty_user:
        return duty_user, True, duty_user.full_name or duty_user.username

    eng = get_round_robin_engineer(db, obj_index)
    if eng:
        return eng, False, eng.full_name or eng.username

    return None, False, "Инженер ОСС"


def generate_plans_for_period(
    db: Session,
    year: int,
    month: int,
    object_types: list = None,
    only_without_plan: bool = True,
    prefer_duty: bool = True,
) -> dict:
    """
    Создаёт задачи ППР на указанный месяц.
    Исполнитель: дежурный на дату плана, иначе round-robin.
    """
    created = 0
    skipped = 0
    by_duty = 0

    templates = db.query(PPRTemplate).filter(PPRTemplate.is_active == True).all()
    templates_by_type = {}
    for t in templates:
        for ot in (t.object_types or []):
            templates_by_type.setdefault(ot, []).append(t)

    q = db.query(Object).filter(Object.status == "active")
    if object_types:
        q = q.filter(Object.object_type.in_(object_types))
    objects = q.order_by(Object.id).all()

    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])

    for idx, obj in enumerate(objects):
        relevant = templates_by_type.get(obj.object_type, [])
        if not relevant:
            if obj.object_type in ("camera_integration", "ovn"):
                relevant = [t for t in templates if t.code in ("7.5", "7.6", "7.7", "7.8") or t.periodicity == "monthly"]
            elif obj.object_type == "voles":
                relevant = [t for t in templates if "11" in (t.code or "") or t.periodicity == "twice_year"]

        if not relevant:
            continue

        template = relevant[0]
        if obj.object_type in ("camera_integration", "ovn"):
            title = f"ППР {obj.code} — {month:02d}.{year}"
        else:
            title = f"{template.name} — {obj.code}"

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

        day = min(5 + (obj.id % 20), month_end.day)
        planned = date(year, month, day)

        if prefer_duty:
            user, by_d, responsible = resolve_assignee(db, planned, idx)
        else:
            user, by_d, responsible = resolve_assignee(db, planned, idx)
            # still uses duty first

        # fallback to object's default responsible if no staff
        if not user and obj.responsible_default:
            responsible = obj.responsible_default

        plan = PPRPlan(
            object_id=obj.id,
            template_id=template.id,
            assignee_id=user.id if user else None,
            title=title,
            planned_date=planned,
            responsible=responsible,
            status="planned",
            work_types_done=[],
            assigned_by_duty=by_d,
        )
        db.add(plan)
        created += 1
        if by_d:
            by_duty += 1

    db.commit()
    return {
        "created": created,
        "skipped": skipped,
        "assigned_by_duty": by_duty,
        "year": year,
        "month": month,
        "message": f"Создано {created} задач (из них по дежурству: {by_duty}), пропущено: {skipped}",
    }


def mark_overdue(db: Session) -> int:
    today = date.today()
    plans = db.query(PPRPlan).filter(
        PPRPlan.status == "planned",
        PPRPlan.planned_date < today,
    ).all()
    for p in plans:
        p.status = "overdue"
    db.commit()
    return len(plans)


def reassign_plans_by_duty(db: Session, year: int, month: int) -> dict:
    """Переназначить уже созданные плановые задачи по актуальному графику дежурств."""
    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    plans = db.query(PPRPlan).filter(
        PPRPlan.planned_date >= month_start,
        PPRPlan.planned_date <= month_end,
        PPRPlan.status.in_(["planned", "overdue"]),
    ).all()
    updated = 0
    for p in plans:
        user = get_duty_user(db, p.planned_date)
        if user:
            p.assignee_id = user.id
            p.responsible = user.full_name or user.username
            p.assigned_by_duty = True
            updated += 1
    db.commit()
    return {"updated": updated, "message": f"Переназначено по графику дежурств: {updated}"}
