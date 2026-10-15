"""Автоматическое планирование ППР по периодичности, направлению и графику дежурств"""
from datetime import date, timedelta
from calendar import monthrange
from sqlalchemy.orm import Session
from models import Object, PPRTemplate, PPRPlan, User, DutySchedule


NETWORK_OBJECT_TYPES = {
    "network", "us", "cod", "core_router", "core_switch",
    "access_switch", "edge_router", "wifi_controller", "server", "ups",
}


PERIOD_DAYS = {
    "daily": 1,
    "monthly": 30,
    "quarterly": 90,
    "semi_annual": 180,
    "twice_year": 180,
    "annual": 365,
}

# Соответствие должности → направление ППР
POSITION_TO_SPECIALTY = {
    "системный администратор": "sysadmin",
    "сисадмин": "sysadmin",
    "монтажник": "installer",
    "бригадир": "installer",
    "сварщик волс": "installer",
    "сетевой инженер": "network_engineer",
    "ведущий сетевой инженер": "network_engineer",
    "начальник отдела сетей связи": "head",
    "начальник осс": "head",
}


def infer_specialty(user: User) -> str | None:
    if user.ppr_specialty:
        return user.ppr_specialty
    pos = (user.position or "").strip().lower()
    for key, spec in POSITION_TO_SPECIALTY.items():
        if key in pos:
            return spec
    return None


def get_duty_user(db: Session, on_date: date) -> User | None:
    duty = (
        db.query(DutySchedule)
        .filter(DutySchedule.duty_date == on_date)
        .order_by(DutySchedule.id)
        .first()
    )
    return duty.user if duty else None


def get_users_by_specialty(db: Session, specialty: str | None, department_id: int | None = None) -> list:
    q = db.query(User).filter(
        User.is_active == True,
        User.can_do_ppr == True,
    )
    if department_id is not None:
        q = q.filter(User.department_id == department_id)
    users = q.order_by(User.id).all()
    if not specialty or specialty in ("any",):
        return users
    matched = [u for u in users if infer_specialty(u) == specialty]
    if matched:
        return matched
    # fallback: все исполнители ППР
    return users


def resolve_assignee_for_template(
    db: Session,
    template: PPRTemplate,
    planned: date,
    index: int,
    prefer_duty: bool = True,
    department_id: int | None = None,
) -> tuple:
    """
    1) head → пользователь с role head/admin или specialty head
    2) по work_direction шаблона
    3) дежурный (для daily)
    4) round-robin среди подходящих
    """
    direction = (template.work_direction or "network_engineer").strip()

    if direction == "head" or template.responsible_role == "head":
        heads = (
            db.query(User)
            .filter(User.is_active == True, User.role.in_(["head", "admin"]))
            .filter(User.department_id == department_id if department_id is not None else True)
            .order_by(User.id)
            .all()
        )
        if heads:
            u = heads[index % len(heads)]
            return u, False, u.full_name or u.username

    # daily — предпочитаем дежурного
    if prefer_duty and template.periodicity == "daily":
        duty = get_duty_user(db, planned)
        if duty and (department_id is None or duty.department_id == department_id):
            return duty, True, duty.full_name or duty.username

    pool = get_users_by_specialty(db, direction, department_id=department_id)
    if not pool:
        return None, False, "Инженер ОСС"

    # дежурный из пула, если есть
    if prefer_duty:
        duty = get_duty_user(db, planned)
        if duty and duty in pool and (department_id is None or duty.department_id == department_id):
            return duty, True, duty.full_name or duty.username

    u = pool[index % len(pool)]
    return u, False, u.full_name or u.username


def _planned_dates_for_period(year: int, month: int, periodicity: str) -> list:
    """Даты планов внутри месяца по периодичности."""
    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    mid = date(year, month, min(15, month_end.day))

    if periodicity == "daily":
        # не создаём daily-задачи на каждый день пачкой — только «якорную» на 1-е
        # (ежедневный контроль ведётся отдельно модулем DailyCheck)
        return [month_start]

    if periodicity == "monthly":
        return [mid]

    if periodicity == "quarterly":
        # только в месяцах 1,4,7,10 (начало квартала) — mid
        if month in (1, 4, 7, 10):
            return [mid]
        return []

    if periodicity in ("semi_annual", "twice_year"):
        # II и IV кварталы → апрель, октябрь
        if month in (4, 10):
            return [mid]
        return []

    if periodicity == "annual":
        # инвентаризация / СКС — III или IV квартал (сент/окт)
        if month in (9, 10):
            return [mid]
        return []

    return [mid]


def generate_plans_for_period(
    db: Session,
    year: int,
    month: int,
    object_types: list = None,
    only_without_plan: bool = True,
    prefer_duty: bool = True,
    work_direction: str = None,
    include_daily_templates: bool = False,
    department_id: int | None = None,
) -> dict:
    """
    Создаёт задачи ППР на месяц:
    - по шаблонам (общесистемные network + привязка к объектам camera/voles)
    - исполнитель по work_direction / specialty
    """
    if department_id is None:
        from models import Department
        departments = db.query(Department).filter(Department.is_active == True).order_by(Department.id).all()
        if departments:
            totals = {"created": 0, "skipped": 0, "by_duty": 0, "by_direction": {}, "objects_considered": 0}
            for department in departments:
                result = generate_plans_for_period(db, year, month, object_types=object_types, only_without_plan=only_without_plan, prefer_duty=prefer_duty, work_direction=work_direction, include_daily_templates=include_daily_templates, department_id=department.id)
                for key in ("created", "skipped", "by_duty", "objects_considered"):
                    totals[key] += result.get(key, 0)
                for key, value in result.get("by_direction", {}).items():
                    totals["by_direction"][key] = totals["by_direction"].get(key, 0) + value
            return {**totals, "period": f"{year}-{month:02d}", "department_id": None, "message": "Создано задач: " + str(totals["created"]) + ", пропущено: " + str(totals["skipped"])}

    created = 0
    skipped = 0
    by_duty = 0
    by_direction = {}

    templates = (
        db.query(PPRTemplate)
        .filter(PPRTemplate.is_active == True)
        .order_by(PPRTemplate.code)
        .all()
    )
    if work_direction:
        templates = [t for t in templates if (t.work_direction or "") == work_direction]
    if department_id is not None:
        templates = [t for t in templates if not (t.department_ids or []) or department_id in (t.department_ids or [])]
    if not include_daily_templates:
        templates = [t for t in templates if t.periodicity != "daily"]

    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])

    # --- 1) Общесистемные / network шаблоны (без привязки к каждому объекту) ---
    system_templates = [
        t for t in templates
        if not t.object_types
        or t.object_types == ["network"]
        or (len(t.object_types) == 1 and t.object_types[0] == "network")
    ]
    # В режиме подразделения все задачи привязываются к объектам этого подразделения.
    if department_id is not None:
        system_templates = []
    # исключим камерные коды
    system_templates = [
        t for t in system_templates
        if not (t.code or "").startswith("7.") and "11." not in (t.code or "")
    ]

    for idx, tpl in enumerate(system_templates):
        dates = _planned_dates_for_period(year, month, tpl.periodicity)
        for planned in dates:
            if only_without_plan:
                existing = (
                    db.query(PPRPlan)
                    .filter(
                        PPRPlan.template_id == tpl.id,
                        PPRPlan.object_id.is_(None),
                        PPRPlan.department_id == department_id,
                        PPRPlan.planned_date >= month_start,
                        PPRPlan.planned_date <= month_end,
                        PPRPlan.status != "cancelled",
                    )
                    .first()
                )
                if existing:
                    skipped += 1
                    continue

            user, by_d, responsible = resolve_assignee_for_template(
                db, tpl, planned, idx, prefer_duty=prefer_duty, department_id=department_id
            )
            if by_d:
                by_duty += 1

            plan = PPRPlan(
                object_id=None,
                department_id=department_id,
                template_id=tpl.id,
                assignee_id=user.id if user else None,
                title=f"{tpl.name} — {month:02d}.{year}",
                planned_date=planned,
                responsible=responsible,
                status="planned",
                work_types_done=[],
                assigned_by_duty=by_d,
            )
            db.add(plan)
            created += 1
            d = tpl.work_direction or "any"
            by_direction[d] = by_direction.get(d, 0) + 1

    # --- 2) Объектные шаблоны (камеры, ОВН, ВОЛС) ---
    object_templates = [t for t in templates if t not in system_templates]
    q = db.query(Object).filter(Object.status == "active")
    if object_types:
        q = q.filter(Object.object_type.in_(object_types))
    objects = q.order_by(Object.id).all()

    for oidx, obj in enumerate(objects):
        relevant = [
            t for t in object_templates
            if not (t.object_types or [])
            or obj.object_type in (t.object_types or [])
            or (
                obj.object_type in NETWORK_OBJECT_TYPES
                and "network" in (t.object_types or [])
            )
        ]
        if not relevant:
            continue

        for tidx, tpl in enumerate(relevant):
            dates = _planned_dates_for_period(year, month, tpl.periodicity)
            for planned in dates:
                if only_without_plan:
                    existing = (
                        db.query(PPRPlan)
                        .filter(
                            PPRPlan.object_id == obj.id,
                            PPRPlan.department_id == department_id,
                            PPRPlan.template_id == tpl.id,
                            PPRPlan.planned_date >= month_start,
                            PPRPlan.planned_date <= month_end,
                            PPRPlan.status != "cancelled",
                        )
                        .first()
                    )
                    if existing:
                        skipped += 1
                        continue

                user, by_d, responsible = resolve_assignee_for_template(
                    db, tpl, planned, oidx + tidx, prefer_duty=prefer_duty, department_id=department_id
                )
                if by_d:
                    by_duty += 1
                if not user and obj.responsible_default:
                    responsible = obj.responsible_default

                title = f"ППР {obj.code}: {tpl.name}"
                plan = PPRPlan(
                    object_id=obj.id,
                    department_id=department_id,
                    template_id=tpl.id,
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
                d = tpl.work_direction or "any"
                by_direction[d] = by_direction.get(d, 0) + 1

    db.commit()
    return {
        "created": created,
        "skipped": skipped,
        "by_duty": by_duty,
        "by_direction": by_direction,
        "period": f"{year}-{month:02d}",
        "department_id": department_id,
        "objects_considered": len(objects),
        "message": f"Создано задач: {created}, пропущено: {skipped}",
    }


def mark_overdue(db: Session) -> int:
    today = date.today()
    plans = (
        db.query(PPRPlan)
        .filter(PPRPlan.status == "planned", PPRPlan.planned_date < today)
        .all()
    )
    for p in plans:
        p.status = "overdue"
    db.commit()
    return len(plans)


def reassign_plans_by_duty(db: Session, year: int, month: int) -> dict:
    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    plans = (
        db.query(PPRPlan)
        .filter(
            PPRPlan.planned_date >= month_start,
            PPRPlan.planned_date <= month_end,
            PPRPlan.status.in_(["planned", "overdue"]),
        )
        .all()
    )
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


def generate_quick_plans(
    db: Session,
    year: int,
    month: int,
    work_direction: str = None,
    department_id: int | None = None,
) -> dict:
    """Быстрое создание задач на месяц по направлению (или всем)."""
    return generate_plans_for_period(
        db,
        year,
        month,
        work_direction=work_direction,
        only_without_plan=True,
        prefer_duty=True,
        include_daily_templates=False,
        department_id=department_id,
    )
