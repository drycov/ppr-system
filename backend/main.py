import logging
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, inspect
from typing import List, Optional
from datetime import date, datetime, timedelta
from pathlib import Path
from io import BytesIO

from database import get_db, engine, Base
from models import Object, PPRTemplate, PPRPlan, DailyCheck, User, DutySchedule, Department, Position, SystemRole, RelocationLog, NotificationLog, SystemSetting, SettingsAudit
import schemas
import seed
from auth import (
    get_password_hash, is_manager,
    authenticate_user, create_access_token, require_user, require_admin,
    get_current_user, Token, UserOut, ACCESS_TOKEN_EXPIRE_HOURS
)
from planning import generate_plans_for_period, mark_overdue, reassign_plans_by_duty, generate_quick_plans
from pdf_service import generate_ppr_act
from excel_export import export_ppr_report
from import_excel import import_from_excel
from scheduler import start_scheduler
from notifications import notify_message

logger = logging.getLogger("ppr.main")
from settings_service import SETTINGS_CATALOG, CATALOG_BY_KEY, get_settings_snapshot, save_settings, get_setting

app = FastAPI(
    title="Система управления ППР — ОСС / АПК",
    description="Планово-профилактические работы филиала ТОО «Satory Company ltd» г. Усть-Каменогорск",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== Инициализация ==========
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    department_columns = {column["name"] for column in inspect(engine).get_columns("departments")}
    if "duty_enabled" not in department_columns:
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE departments ADD COLUMN duty_enabled BOOLEAN NOT NULL DEFAULT 1")
    duty_columns = {column["name"] for column in inspect(engine).get_columns("duty_schedules")}
    if "department_id" not in duty_columns:
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE duty_schedules ADD COLUMN department_id INTEGER REFERENCES departments(id)")
    user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    with engine.begin() as conn:
        if "telegram_chat_id" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN telegram_chat_id VARCHAR(64)")
        if "telegram_status" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN telegram_status VARCHAR(20) NOT NULL DEFAULT 'unlinked'")
        if "telegram_pending_phone" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN telegram_pending_phone VARCHAR(50)")
    # Подразделение относится к задаче ППР, объект не закрепляется за подразделением.
    plan_columns = {column["name"] for column in inspect(engine).get_columns("ppr_plans")}
    if "department_id" not in plan_columns:
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE ppr_plans ADD COLUMN department_id INTEGER REFERENCES departments(id)")
            conn.exec_driver_sql("UPDATE ppr_plans SET department_id = (SELECT department_id FROM users WHERE users.id = ppr_plans.assignee_id) WHERE department_id IS NULL AND assignee_id IS NOT NULL")
    template_columns = {column["name"] for column in inspect(engine).get_columns("ppr_templates")}
    with engine.begin() as conn:
        if "department_ids" not in template_columns:
            conn.exec_driver_sql("ALTER TABLE ppr_templates ADD COLUMN department_ids JSON NOT NULL DEFAULT '[]'")
        if "excluded_department_ids" not in template_columns:
            conn.exec_driver_sql("ALTER TABLE ppr_templates ADD COLUMN excluded_department_ids JSON NOT NULL DEFAULT '[]'")
    # Автосид при первом запуске
    db = next(get_db())
    try:
        if db.query(Object).count() == 0:
            print("Первый запуск — заполняем БД...")
            seed.seed_templates(db)
            seed.seed_directories(db)
            seed.seed_users(db)
            seed.import_integration_objects(db)
            seed.import_voles_objects(db)
            seed.seed_sample_plans(db)
        # Новые регламенты ЦОД добавляются идемпотентно и на уже заполненной БД.
        seed.seed_data_center_templates(db)
    finally:
        db.close()
    # Start the configured background scheduler after schema and seed initialization.
    start_scheduler()
    from telegram_bot import start_telegram_bot
    start_telegram_bot(db=None)


@app.on_event("shutdown")
def on_shutdown():
    from telegram_bot import stop_telegram_bot
    stop_telegram_bot()


# ========== System settings ==========
@app.get("/api/settings")
def list_system_settings(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"settings": get_settings_snapshot(db), "categories": list(dict.fromkeys(x["category"] for x in SETTINGS_CATALOG))}


@app.put("/api/settings")
def update_system_settings(payload: dict, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    values = payload.get("settings", payload)
    try:
        changed = save_settings(db, values, user.username or user.full_name or str(user.id))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    if any(key in changed for key in ("integrations.telegram.bot_token", "integrations.telegram.enabled", "integrations.telegram.miniapp_url")):
        from telegram_bot import restart_telegram_bot
        restart_telegram_bot(db)
    return {"ok": True, "changed": changed, "settings": get_settings_snapshot(db)}


@app.post("/api/settings/reset")
def reset_system_settings(payload: dict, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    keys = payload.get("keys", [])
    if not isinstance(keys, list) or any(not isinstance(k, str) for k in keys):
        raise HTTPException(422, "keys должен быть массивом строк")
    unknown = sorted(set(keys) - set(CATALOG_BY_KEY))
    if unknown:
        raise HTTPException(422, "Неизвестные настройки: " + ", ".join(unknown))
    query = db.query(SystemSetting)
    if keys:
        query = query.filter(SystemSetting.key.in_(keys))
    rows = query.all()
    changed = {}
    for row in rows:
        spec = CATALOG_BY_KEY[row.key]
        changed[row.key] = {"old": "***" if spec["type"] == "secret" else row.value, "new": "default"}
        db.delete(row)
    if changed:
        db.add(SettingsAudit(actor=user.username or user.full_name or str(user.id), action="reset", changes=changed, created_at=datetime.utcnow()))
        db.commit()
    return {"ok": True, "reset": list(changed), "settings": get_settings_snapshot(db)}


@app.get("/api/settings/export")
def export_system_settings(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    values = {item["key"]: item["value"] for item in get_settings_snapshot(db, include_secrets=True) if item["type"] != "secret"}
    return {"version": 1, "exported_at": datetime.utcnow().isoformat() + "Z", "settings": values}


@app.post("/api/settings/import")
def import_system_settings(payload: dict, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    values = payload.get("settings")
    if not isinstance(values, dict):
        raise HTTPException(422, "Ожидается объект settings из экспорта")
    try:
        changed = save_settings(db, values, user.username or user.full_name or str(user.id))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "changed": changed, "settings": get_settings_snapshot(db)}


@app.get("/api/settings/audit")
def list_settings_audit(limit: int = Query(100, ge=1, le=500), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(SettingsAudit).order_by(SettingsAudit.created_at.desc()).limit(limit).all()
    return [{"id": r.id, "actor": r.actor, "action": r.action, "changes": r.changes, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


# ========== Telegram Mini App authentication ==========
@app.post("/api/telegram-miniapp/auth")
def telegram_miniapp_auth(payload: dict, db: Session = Depends(get_db)):
    """Validate Telegram WebApp initData and issue a short-lived application JWT."""
    import hashlib
    import hmac
    import json
    import os
    import time
    from urllib.parse import parse_qsl

    init_data = payload.get("init_data")
    if not isinstance(init_data, str) or not init_data or len(init_data) > 8192:
        raise HTTPException(status_code=400, detail="Некорректные данные Telegram Mini App")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError("duplicate fields")
        received_hash = fields.pop("hash", "")
        auth_date = int(fields.get("auth_date", "0"))
        telegram_user = json.loads(fields.get("user", "{}"))
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Не удалось проверить авторизацию Telegram")
    if not received_hash or not isinstance(telegram_user, dict) or not telegram_user.get("id"):
        raise HTTPException(status_code=401, detail="Telegram не передал данные пользователя")
    now = int(time.time())
    if auth_date > now + 60 or now - auth_date > 86400:
        raise HTTPException(status_code=401, detail="Сессия Telegram устарела. Откройте Mini App заново.")
    try:
        from settings_service import get_setting
        bot_token = get_setting(db, "integrations.telegram.bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    except Exception:
        logger.exception("Cannot load Telegram bot token for Mini App auth")
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        raise HTTPException(status_code=503, detail="Telegram-бот не настроен в системе")
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=401, detail="Подпись Telegram недействительна")
    telegram_id = str(telegram_user["id"])
    user = db.query(User).filter(
        User.telegram_chat_id == telegram_id,
        User.telegram_status == "approved",
        User.is_active.is_(True),
    ).first()
    if not user:
        raise HTTPException(status_code=403, detail="Учётная запись не привязана или ожидает одобрения администратора")
    access_token = create_access_token({"sub": user.username, "auth_method": "telegram_miniapp"})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name or user.username,
            "role": user.role,
            "department_id": user.department_id,
        },
    }


@app.get("/api/telegram-miniapp/duties")
def telegram_miniapp_duties(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Return only the authenticated employee's duty entries for the Mini App."""
    from sqlalchemy import or_
    start = from_date or date.today()
    end = to_date or (start + timedelta(days=30))
    if end < start or (end - start).days > 93:
        raise HTTPException(status_code=422, detail="Период должен быть не более 94 дней")
    rows = (
        db.query(DutySchedule)
        .outerjoin(Department, DutySchedule.department_id == Department.id)
        .filter(
            DutySchedule.user_id == user.id,
            DutySchedule.duty_date >= start,
            DutySchedule.duty_date <= end,
            or_(DutySchedule.department_id.is_(None), Department.duty_enabled.is_(True)),
        )
        .order_by(DutySchedule.duty_date, DutySchedule.shift)
        .all()
    )
    return [{
        "id": row.id,
        "duty_date": row.duty_date.isoformat(),
        "shift": row.shift,
        "notes": row.notes,
        "department": row.department.name if row.department else "Все подразделения",
    } for row in rows]


# ========== Dashboard ==========
@app.get("/api/dashboard", response_model=schemas.DashboardStats)
def get_dashboard(db: Session = Depends(get_db)):
    total = db.query(Object).count()
    active = db.query(Object).filter(Object.status == "active").count()
    planned = db.query(PPRPlan).filter(PPRPlan.status == "planned").count()
    done = db.query(PPRPlan).filter(PPRPlan.status == "done").count()
    overdue = db.query(PPRPlan).filter(
        PPRPlan.status == "planned",
        PPRPlan.planned_date < date.today()
    ).count()
    total_plans = planned + done + overdue
    percent = round(done / total_plans * 100, 1) if total_plans else 0.0

    month_start = date.today().replace(day=1)
    daily = db.query(DailyCheck).filter(DailyCheck.check_date >= month_start).count()
    engineers = db.query(User).filter(User.role == "engineer").count()

    return schemas.DashboardStats(
        total_objects=total,
        active_objects=active,
        planned_ppr=planned,
        done_ppr=done,
        overdue_ppr=overdue,
        completion_percent=percent,
        daily_checks_this_month=daily,
        engineers_count=engineers,
    )


# ========== Objects ==========

@app.get("/api/object-types")
def list_object_types():
    """Справочник типов объектов для UI."""
    return [
        {"code": "camera_integration", "name": "ИНТ (камеры)", "group": "apk"},
        {"code": "ovn", "name": "ОВН", "group": "apk"},
        {"code": "voles", "name": "ВОЛС", "group": "apk"},
        {"code": "sip", "name": "СИП", "group": "apk"},
        {"code": "us", "name": "УС (узел связи)", "group": "network"},
        {"code": "cod", "name": "ЦОД", "group": "network"},
        {"code": "core_router", "name": "Роутер ядра", "group": "network"},
        {"code": "core_switch", "name": "Коммутатор ядра", "group": "network"},
        {"code": "access_switch", "name": "Коммутатор доступа", "group": "network"},
        {"code": "edge_router", "name": "Граничный роутер", "group": "network"},
        {"code": "wifi_controller", "name": "Контроллер Wi-Fi", "group": "network"},
        {"code": "server", "name": "Сервер", "group": "network"},
        {"code": "ups", "name": "ИБП", "group": "network"},
        {"code": "network", "name": "Сеть ОСС (общее)", "group": "network"},
        {"code": "other", "name": "Прочее", "group": "other"},
    ]


@app.get("/api/objects", response_model=List[schemas.ObjectOut])
def list_objects(
    object_type: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(Object)
    if object_type:
        q = q.filter(Object.object_type == object_type)
    if status:
        q = q.filter(Object.status == status)
    if search:
        like = f"%{search}%"
        q = q.filter(
            (Object.code.ilike(like)) |
            (Object.address.ilike(like)) |
            (Object.name.ilike(like))
        )
    return q.order_by(Object.code).offset(skip).limit(limit).all()


@app.get("/api/objects/{object_id}", response_model=schemas.ObjectOut)
def get_object(object_id: int, db: Session = Depends(get_db)):
    obj = db.query(Object).filter(Object.id == object_id).first()
    if not obj:
        raise HTTPException(404, "Объект не найден")
    return obj


@app.post("/api/objects", response_model=schemas.ObjectOut)
def create_object(data: schemas.ObjectCreate, db: Session = Depends(get_db)):
    if db.query(Object).filter(Object.code == data.code).first():
        raise HTTPException(400, "Объект с таким кодом уже существует")
    obj = Object(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.patch("/api/objects/{object_id}", response_model=schemas.ObjectOut)
def update_object(object_id: int, data: schemas.ObjectUpdate, db: Session = Depends(get_db)):
    obj = db.query(Object).filter(Object.id == object_id).first()
    if not obj:
        raise HTTPException(404, "Объект не найден")
    payload = data.model_dump(exclude_unset=True)
    if "code" in payload and payload["code"] != obj.code:
        exists = db.query(Object).filter(Object.code == payload["code"], Object.id != object_id).first()
        if exists:
            raise HTTPException(400, "Объект с таким кодом уже существует")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


# ========== Templates (Регламент) ==========
@app.get("/api/templates", response_model=List[schemas.PPRTemplateOut])
def list_templates(db: Session = Depends(get_db)):
    return db.query(PPRTemplate).filter(PPRTemplate.is_active == True).order_by(PPRTemplate.code).all()

@app.patch("/api/templates/{template_id}/departments")
def assign_template_departments(
    template_id: int,
    payload: schemas.PPRTemplateDepartmentsUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    template = db.query(PPRTemplate).filter(PPRTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Регламент не найден")
    ids = sorted(set(payload.department_ids))
    excluded_ids = sorted(set(payload.excluded_department_ids))
    all_ids = set(ids) | set(excluded_ids)
    if all_ids:
        found = {row[0] for row in db.query(Department.id).filter(Department.id.in_(all_ids)).all()}
        missing = all_ids - found
        if missing:
            raise HTTPException(422, f"Не найдены подразделения: {sorted(missing)}")
    template.department_ids = ids
    template.excluded_department_ids = excluded_ids
    db.commit()
    return {
        "ok": True,
        "template_id": template.id,
        "department_ids": ids,
        "excluded_department_ids": excluded_ids,
    }


@app.get("/api/regulations")
def get_regulations():
    """Текстовое представление Положения для UI"""
    return {
        "title": "Перечень планово-профилактических работ на оборудовании системы сети на 2026 год",
        "sections": [
            {
                "name": "1. Планово-профилактические работы (периодические)",
                "items": [
                    {"code": "1", "name": "Маршрутизаторы и коммутаторы", "periodicity": "Ежеквартально", "responsible": "Инженер ОСС"},
                    {"code": "2", "name": "Аудит конфигураций активного оборудования", "periodicity": "Ежемесячно", "responsible": "Инженер ОСС"},
                    {"code": "3", "name": "Серверы сетевых служб", "periodicity": "Ежеквартально", "responsible": "Инженер ОСС"},
                    {"code": "4", "name": "ИБП", "periodicity": "Раз в полугодие", "responsible": "Инженер ОСС"},
                    {"code": "5", "name": "VPN, туннели, HotSpot", "periodicity": "Ежемесячно", "responsible": "Инженер ОСС"},
                    {"code": "6", "name": "Firewall и безопасность", "periodicity": "Ежемесячно", "responsible": "Инженер ОСС"},
                    {"code": "7", "name": "СКС, патч-панели, кроссы", "periodicity": "Ежегодно", "responsible": "Инженер ОСС"},
                    {"code": "8", "name": "Точки доступа Wi-Fi", "periodicity": "Ежеквартально", "responsible": "Инженер ОСС"},
                    {"code": "9", "name": "Системы мониторинга (Zabbix)", "periodicity": "Ежемесячно", "responsible": "Инженер ОСС"},
                    {"code": "10", "name": "ПО и прошивки", "periodicity": "Ежеквартально", "responsible": "Инженер ОСС"},
                    {"code": "11", "name": "Резервные каналы", "periodicity": "Ежеквартально", "responsible": "Инженер ОСС"},
                    {"code": "12", "name": "Инвентаризация", "periodicity": "Ежегодно", "responsible": "Начальник ОСС"},
                ],
            },
            {
                "name": "2. Ежедневные работы (операционный контроль)",
                "items": [
                    {"code": "D1", "name": "Дашборд системы мониторинга", "periodicity": "Ежедневно", "responsible": "Инженер ОСС"},
                    {"code": "D2", "name": "Доступность ключевых сервисов", "periodicity": "Ежедневно", "responsible": "Инженер ОСС"},
                    {"code": "D3", "name": "Логи и события безопасности", "periodicity": "Ежедневно", "responsible": "Инженер ОСС"},
                    {"code": "D4", "name": "Резервные копии конфигураций", "periodicity": "Ежедневно", "responsible": "Инженер ОСС"},
                    {"code": "D5", "name": "Загрузка каналов", "periodicity": "Ежедневно", "responsible": "Инженер ОСС"},
                    {"code": "D6", "name": "Состояние ИБП", "periodicity": "Ежедневно", "responsible": "Инженер ОСС"},
                    {"code": "D7", "name": "Фиксация инцидентов", "periodicity": "Ежедневно", "responsible": "Инженер ОСС"},
                ],
            },
            {
                "name": "Виды работ АПК (камеры)",
                "items": [
                    {"code": "7.5", "name": "Юстировка камер", "periodicity": "Ежемесячно", "responsible": "Инженер"},
                    {"code": "7.6", "name": "Проверка крепления камер", "periodicity": "Ежемесячно", "responsible": "Инженер"},
                    {"code": "7.7", "name": "Проверка крепления шкафа", "periodicity": "Ежемесячно", "responsible": "Инженер"},
                    {"code": "7.8", "name": "Обслуживание UTP", "periodicity": "Ежемесячно", "responsible": "Инженер"},
                ],
            },
        ],
        "notes": [
            "ППР выполняются силами специалистов ОСС.",
            "Ежедневный контроль проводится в начале рабочего дня.",
            "Результаты фиксируются в системе / журнале ППР.",
            "При критических неисправностях — внеплановые работы с уведомлением руководства.",
        ],
    }


# ========== PPR Plans ==========
@app.get("/api/plans", response_model=List[schemas.PPRPlanOut])
def list_plans(
    status: Optional[str] = None,
    object_id: Optional[int] = None,
    department_id: Optional[int] = None,
    responsible: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(PPRPlan).options(joinedload(PPRPlan.object))
    if status:
        q = q.filter(PPRPlan.status == status)
    if object_id:
        q = q.filter(PPRPlan.object_id == object_id)
    if department_id is not None:
        q = q.filter(PPRPlan.department_id == department_id)
    if responsible:
        q = q.filter(PPRPlan.responsible.ilike(f"%{responsible}%"))
    if from_date:
        q = q.filter(PPRPlan.planned_date >= from_date)
    if to_date:
        q = q.filter(PPRPlan.planned_date <= to_date)
    return q.order_by(PPRPlan.planned_date.desc()).offset(skip).limit(limit).all()


@app.post("/api/plans", response_model=schemas.PPRPlanOut)
def create_plan(data: schemas.PPRPlanCreate, db: Session = Depends(get_db)):
    if data.department_id is not None and not db.query(Department.id).filter(Department.id == data.department_id).first():
        raise HTTPException(422, "Подразделение не найдено")
    if data.object_id is not None and not db.query(Object.id).filter(Object.id == data.object_id).first():
        raise HTTPException(422, "Объект не найден")
    plan = PPRPlan(**data.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@app.get("/api/plans/my")
def my_plans(
    status: Optional[str] = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Задачи текущего пользователя (по assignee или ФИО)"""
    from sqlalchemy import or_
    conds = [PPRPlan.assignee_id == user.id]
    if user.full_name:
        conds.append(PPRPlan.responsible.ilike(f"%{user.full_name}%"))
    q = db.query(PPRPlan).options(joinedload(PPRPlan.object)).filter(or_(*conds))
    if status:
        q = q.filter(PPRPlan.status == status)
    return q.order_by(PPRPlan.planned_date).limit(100).all()


@app.get("/api/plans/{plan_id}", response_model=schemas.PPRPlanOut)
def get_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(PPRPlan).options(joinedload(PPRPlan.object)).filter(PPRPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Задача не найдена")
    return plan


@app.patch("/api/plans/{plan_id}", response_model=schemas.PPRPlanOut)
def update_plan(plan_id: int, data: schemas.PPRPlanUpdate, db: Session = Depends(get_db)):
    plan = db.query(PPRPlan).filter(PPRPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Задача не найдена")
    payload = data.model_dump(exclude_unset=True)
    if payload.get("department_id") is not None and not db.query(Department.id).filter(Department.id == payload["department_id"]).first():
        raise HTTPException(422, "Подразделение не найдено")
    if payload.get("object_id") is not None and not db.query(Object.id).filter(Object.id == payload["object_id"]).first():
        raise HTTPException(422, "Объект не найден")
    # если сменили исполнителя — подтянуть ФИО
    if "assignee_id" in payload and payload["assignee_id"]:
        u = db.query(User).filter(User.id == payload["assignee_id"]).first()
        if u and "responsible" not in payload:
            payload["responsible"] = u.full_name or u.username
    for k, v in payload.items():
        setattr(plan, k, v)
    if payload.get("status") == "done" and not plan.fact_date:
        plan.fact_date = date.today()
    if payload.get("status") == "planned":
        # вернули в план — сбросить факт при необходимости не трогаем
        pass
    db.commit()
    db.refresh(plan)
    return plan


@app.delete("/api/plans/{plan_id}")
def delete_plan(plan_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    plan = db.query(PPRPlan).filter(PPRPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Задача не найдена")
    if plan.status == "done" and user.role not in ("admin", "head"):
        raise HTTPException(403, "Выполненную задачу может удалить только руководитель")
    db.delete(plan)
    db.commit()
    return {"ok": True, "message": "Задача удалена"}


@app.post("/api/plans/{plan_id}/complete")
def complete_plan(
    plan_id: int,
    work_types: List[str] = Query(default=[]),
    comment: Optional[str] = None,
    db: Session = Depends(get_db),
):
    plan = db.query(PPRPlan).filter(PPRPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Задача не найдена")
    plan.status = "done"
    plan.fact_date = date.today()
    if work_types:
        plan.work_types_done = work_types
    if comment:
        plan.comment = comment
    db.commit()
    return {"ok": True, "message": "ППР отмечен как выполненный"}



@app.post("/api/plans/complete-bulk")
def complete_plans_bulk(
    payload: dict,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Массовое закрытие задач объектов разрешено только для подразделения ОСС."""
    ids = payload.get("plan_ids")
    if not isinstance(ids, list) or not ids or len(ids) > 500:
        raise HTTPException(422, "plan_ids должен содержать от 1 до 500 идентификаторов задач")
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in ids):
        raise HTTPException(422, "Некорректный список идентификаторов задач")
    ids = list(dict.fromkeys(ids))

    from sqlalchemy import or_
    oss_department = db.query(Department).filter(
        or_(
            func.lower(func.trim(Department.name)) == "осс",
            func.lower(func.trim(Department.code)) == "oss",
        ),
        Department.is_active.is_(True),
    ).first()
    if not oss_department:
        raise HTTPException(403, "Массовое выполнение доступно только для активного подразделения ОСС")
    if user.role not in ("admin", "head") and user.department_id != oss_department.id:
        raise HTTPException(403, "Массовое выполнение ППР доступно только сотрудникам ОСС")

    plans = db.query(PPRPlan).filter(PPRPlan.id.in_(ids)).all()
    if len(plans) != len(ids):
        raise HTTPException(404, "Одна или несколько задач не найдены")
    if any(p.department_id != oss_department.id or p.object_id is None for p in plans):
        raise HTTPException(403, "Массово можно выполнять только задачи, назначенные на объекты подразделения ОСС")
    if any(p.status in ("done", "cancelled") for p in plans):
        raise HTTPException(409, "В выборке есть уже выполненные или отменённые задачи; обновите список")

    work_types = payload.get("work_types_done", [])
    if not isinstance(work_types, list) or any(not isinstance(v, str) for v in work_types):
        raise HTTPException(422, "work_types_done должен быть списком строк")
    comment = payload.get("comment")
    if comment is not None and not isinstance(comment, str):
        raise HTTPException(422, "comment должен быть строкой")

    today = date.today()
    for plan in plans:
        plan.status = "done"
        plan.fact_date = today
        if work_types:
            plan.work_types_done = work_types
        if comment:
            plan.comment = comment
    db.commit()
    return {"ok": True, "completed": len(plans), "plan_ids": ids, "message": f"Массово выполнено задач: {len(plans)}"}


# ========== Daily Checks ==========
def _enrich_daily_out(check: DailyCheck) -> dict:
    """Добавляет done_count / total_count и нормализует checklist."""
    items = check.checklist or []
    if not items:
        # собираем из старых полей
        tpl = schemas.DAILY_CHECKLIST_TEMPLATE
        items = []
        for t in tpl:
            field = t["field"]
            if field == "incidents_logged":
                done = bool(getattr(check, "incidents_logged", False))
                status = "ok" if done else "skip"
            else:
                status = getattr(check, field, "ok") or "ok"
                done = status in ("ok", "issues")
            items.append({
                "code": t["code"],
                "name": t["name"],
                "done": done,
                "status": status if field != "incidents_logged" else ("ok" if done else "skip"),
                "note": None,
            })
    done_count = sum(1 for i in items if (i.get("done") if isinstance(i, dict) else getattr(i, "done", False)))
    total = len(items) or len(schemas.DAILY_CHECKLIST_TEMPLATE)
    return {
        "id": check.id,
        "check_date": check.check_date,
        "engineer": check.engineer,
        "monitoring_dashboard": check.monitoring_dashboard,
        "critical_services": check.critical_services,
        "logs_security": check.logs_security,
        "config_backups": check.config_backups,
        "channel_utilization": check.channel_utilization,
        "ups_status": check.ups_status,
        "incidents_logged": check.incidents_logged,
        "checklist": items,
        "notes": check.notes,
        "created_at": check.created_at,
        "done_count": done_count,
        "total_count": total,
    }


def _apply_checklist_to_fields(payload: dict) -> dict:
    """Синхронизирует checklist → плоские поля модели."""
    cl = payload.get("checklist") or []
    if not cl:
        return payload
    field_by_code = {t["code"]: t["field"] for t in schemas.DAILY_CHECKLIST_TEMPLATE}
    for item in cl:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        code = item.get("code")
        field = field_by_code.get(code)
        if not field:
            continue
        done = bool(item.get("done"))
        status = item.get("status") or "ok"
        if field == "incidents_logged":
            payload["incidents_logged"] = done
        else:
            if not done:
                payload[field] = "skip"
            else:
                payload[field] = status if status in ("ok", "issues") else "ok"
    # сериализуем checklist в list[dict]
    payload["checklist"] = [
        (i.model_dump() if hasattr(i, "model_dump") else i) for i in cl
    ]
    return payload


@app.get("/api/daily-checks", response_model=List[schemas.DailyCheckOut])
def list_daily_checks(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 30,
    db: Session = Depends(get_db),
):
    q = db.query(DailyCheck)
    if from_date:
        q = q.filter(DailyCheck.check_date >= from_date)
    if to_date:
        q = q.filter(DailyCheck.check_date <= to_date)
    rows = q.order_by(DailyCheck.check_date.desc()).limit(limit).all()
    return [_enrich_daily_out(r) for r in rows]


@app.get("/api/daily-checks/template")
def daily_checklist_template():
    """Эталонный чек-лист ежедневного контроля (раздел 2)."""
    return {
        "title": "Ежедневный операционный контроль",
        "items": schemas.DAILY_CHECKLIST_TEMPLATE,
    }


@app.post("/api/daily-checks", response_model=schemas.DailyCheckOut)
def create_daily_check(
    data: schemas.DailyCheckCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    eng = (data.engineer or "").strip() or (user.full_name or user.username)
    existing = db.query(DailyCheck).filter(
        DailyCheck.check_date == data.check_date,
        DailyCheck.engineer == eng,
    ).first()
    if existing:
        raise HTTPException(400, "Проверка на эту дату для вас уже есть")
    payload = _apply_checklist_to_fields(data.model_dump())
    payload["engineer"] = eng
    check = DailyCheck(**payload)
    db.add(check)
    db.commit()
    db.refresh(check)
    return _enrich_daily_out(check)


@app.patch("/api/daily-checks/{check_id}", response_model=schemas.DailyCheckOut)
def update_daily_check(check_id: int, data: schemas.DailyCheckUpdate, db: Session = Depends(get_db)):
    check = db.query(DailyCheck).filter(DailyCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Проверка не найдена")
    payload = data.model_dump(exclude_unset=True)
    if "checklist" in payload:
        payload = _apply_checklist_to_fields(payload)
    for k, v in payload.items():
        setattr(check, k, v)
    db.commit()
    db.refresh(check)
    return _enrich_daily_out(check)


# ========== Stats by type ==========
@app.get("/api/stats/by-type")
def stats_by_type(db: Session = Depends(get_db)):
    rows = db.query(Object.object_type, func.count(Object.id)).group_by(Object.object_type).all()
    return {t: c for t, c in rows}


@app.get("/api/stats/completion")
def completion_stats(db: Session = Depends(get_db)):
    total = db.query(PPRPlan).count()
    done = db.query(PPRPlan).filter(PPRPlan.status == "done").count()
    planned = db.query(PPRPlan).filter(PPRPlan.status == "planned").count()
    overdue = db.query(PPRPlan).filter(
        PPRPlan.status == "planned", PPRPlan.planned_date < date.today()
    ).count()
    return {
        "total": total,
        "done": done,
        "planned": planned,
        "overdue": overdue,
        "percent": round(done / total * 100, 1) if total else 0,
    }


# ========== Health ==========
@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}



# ========== Auth ==========
@app.post("/api/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
    )
    return Token(
        access_token=token,
        token_type="bearer",
        full_name=user.full_name or user.username,
        role=user.role,
    )


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(require_user)):
    return user


# ========== Auto-planning ==========
@app.post("/api/planning/generate")
def api_generate_plans(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    object_type: Optional[str] = None,
    work_direction: Optional[str] = Query(
        None, description="sysadmin | installer | network_engineer | head"
    ),
    department_id: Optional[int] = Query(None, ge=1),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if department_id is not None and not db.query(Department).filter(Department.id == department_id, Department.is_active == True).first():
        raise HTTPException(404, "Подразделение не найдено или неактивно")
    types = [object_type] if object_type else None
    result = generate_plans_for_period(
        db, year, month, object_types=types, work_direction=work_direction, department_id=department_id
    )
    return result


@app.post("/api/planning/generate-quick")
def api_generate_quick(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    work_direction: Optional[str] = Query(None),
    department_id: Optional[int] = Query(None, ge=1),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Быстрое создание задач ППР на месяц по объектам выбранного подразделения."""
    if department_id is not None and not db.query(Department).filter(Department.id == department_id, Department.is_active == True).first():
        raise HTTPException(404, "Подразделение не найдено или неактивно")
    from planning import generate_quick_plans
    return generate_quick_plans(db, year, month, work_direction=work_direction, department_id=department_id)


@app.get("/api/planning/distribution")
def api_ppr_distribution(db: Session = Depends(get_db)):
    """Сводка шаблонов ППР по направлениям и периодичности."""
    templates = db.query(PPRTemplate).filter(PPRTemplate.is_active == True).order_by(PPRTemplate.code).all()
    directions = {
        "sysadmin": {"title": "Системные администраторы", "items": []},
        "installer": {"title": "Монтажники", "items": []},
        "network_engineer": {"title": "Сетевые инженеры", "items": []},
        "head": {"title": "Начальник ОСС", "items": []},
    }
    for t in templates:
        d = t.work_direction or "network_engineer"
        if d not in directions:
            directions[d] = {"title": d, "items": []}
        directions[d]["items"].append({
            "code": t.code,
            "name": t.name,
            "periodicity": t.periodicity,
            "work_items": t.work_items or [],
        })
    return {"directions": directions, "total": len(templates)}


@app.post("/api/planning/reseed-templates")
def api_reseed_templates(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Обновить шаблоны ППР из seed (распределение по направлениям)."""
    seed.seed_templates(db)
    count = db.query(PPRTemplate).count()
    return {"ok": True, "templates": count, "message": f"Шаблоны обновлены, всего {count}"}


@app.post("/api/planning/mark-overdue")
def api_mark_overdue(user: User = Depends(require_user), db: Session = Depends(get_db)):
    count = mark_overdue(db)
    return {"marked": count, "message": f"Помечено просроченными: {count}"}


# ========== PDF Act ==========
@app.get("/api/plans/{plan_id}/act.pdf")
def download_act(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(PPRPlan).filter(PPRPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Задача не найдена")
    obj = plan.object
    pdf_bytes = generate_ppr_act(
        plan_id=plan.id,
        title=plan.title or "ППР",
        object_code=obj.code if obj else "—",
        object_address=obj.address if obj else "",
        responsible=plan.responsible or "",
        planned_date=plan.planned_date,
        fact_date=plan.fact_date or date.today(),
        work_types=plan.work_types_done or [],
        comment=plan.comment or "",
        engineer=plan.responsible or "",
    )
    filename = f"act_ppr_{plan_id}_{date.today().isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ========== Excel export ==========
@app.get("/api/export/ppr.xlsx")
def export_excel(
    year: Optional[int] = Query(None, ge=2000, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    object_type: Optional[str] = Query(None),
    work_direction: Optional[str] = Query(None),
    department_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Excel-отчёт за месяц (year/month) либо произвольный период (from_date/to_date)."""
    if from_date is None and to_date is None:
        if year is None or month is None:
            raise HTTPException(400, "Укажите year и month либо from_date и to_date")
        from calendar import monthrange
        from_date = date(year, month, 1)
        to_date = date(year, month, monthrange(year, month)[1])
    elif from_date is None or to_date is None:
        raise HTTPException(400, "Для отчёта за период укажите обе даты: from_date и to_date")
    if from_date > to_date:
        raise HTTPException(400, "from_date не может быть позже to_date")
    if (to_date - from_date).days > 3660:
        raise HTTPException(400, "Максимальный период отчёта — 10 лет")
    if department_id is not None and not db.query(Department).filter(Department.id == department_id).first():
        raise HTTPException(404, "Подразделение не найдено")
    from report_service import export_ppr_period_report
    data = export_ppr_period_report(
        db, from_date, to_date, object_type=object_type, work_direction=work_direction, department_id=department_id
    )
    dept_suffix = f"_dept{department_id}" if department_id is not None else "_all_departments"
    filename = f"Otchet_PPR_{from_date.isoformat()}_{to_date.isoformat()}{dept_suffix}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/plans/{plan_id}/admin-fictitious-completion")
def admin_fictitious_completion(
    plan_id: int,
    reason: str = Query(..., min_length=5, max_length=500),
    fact_date: Optional[date] = Query(None),
    work_types: List[str] = Query(default=[]),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Административная фиктивная отметка; явно маркируется и попадает в аудит/отчёт."""
    if user.role != "admin":
        raise HTTPException(403, "Фиктивные отметки доступны только администратору системы")
    plan = db.query(PPRPlan).filter(PPRPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Задача ППР не найдена")
    reason = reason.strip()
    if len(reason) < 5:
        raise HTTPException(422, "Укажите причину фиктивной отметки (не менее 5 символов)")
    fact_date = fact_date or date.today()
    marker = (
        f"[ФИКТИВНАЯ ОТМЕТКА — НЕ ПОДТВЕРЖДЕНО ФАКТИЧЕСКИ] "
        f"Администратор: {user.username}; дата внесения: {datetime.utcnow().isoformat(timespec='seconds')}; "
        f"дата выполнения: {fact_date.isoformat()}; причина: {reason}"
    )
    plan.status = "done"
    plan.fact_date = fact_date
    if work_types:
        plan.work_types_done = work_types
    plan.comment = f"{plan.comment or ''}\n{marker}".strip()
    db.commit()
    db.refresh(plan)
    return {
        "ok": True,
        "plan_id": plan.id,
        "status": plan.status,
        "fact_date": plan.fact_date,
        "fictitious": True,
        "audit_marker": marker,
        "message": "Отметка внесена как фиктивная; она явно обозначается в отчётах",
    }



# ========== Staff (сотрудники) ==========
@app.get("/api/staff", response_model=List[schemas.StaffOut])
def list_staff(
    active_only: bool = True,
    can_duty: Optional[bool] = None,
    can_do_ppr: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if active_only:
        q = q.filter(User.is_active == True)
    if can_duty is not None:
        q = q.filter(User.can_duty == can_duty)
    if can_do_ppr is not None:
        q = q.filter(User.can_do_ppr == can_do_ppr)
    return q.order_by(User.full_name).all()


@app.get("/api/telegram/registrations")
def list_telegram_registrations(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = (
        db.query(User)
        .options(joinedload(User.department))
        .filter(User.telegram_status == "pending")
        .order_by(User.full_name)
        .all()
    )
    return [{
        "id": row.id,
        "full_name": row.full_name,
        "username": row.username,
        "phone": row.phone,
        "pending_phone": row.telegram_pending_phone,
        "telegram_chat_id": row.telegram_chat_id,
        "position": row.position,
        "department_id": row.department_id,
        "department_name": row.department.name if row.department else None,
    } for row in rows]


@app.post("/api/telegram/registrations/{staff_id}/approve")
def approve_telegram_registration(staff_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.query(User).filter(User.id == staff_id, User.telegram_status == "pending").first()
    if not row:
        raise HTTPException(404, "Заявка не найдена")
    if not row.telegram_chat_id:
        raise HTTPException(422, "В заявке отсутствует Telegram Chat ID")
    if not row.is_active:
        raise HTTPException(409, "Нельзя одобрить привязку неактивного сотрудника")
    conflict = db.query(User).filter(
        User.id != row.id,
        User.telegram_chat_id == row.telegram_chat_id,
        User.telegram_status == "approved",
    ).first()
    if conflict:
        raise HTTPException(409, "Этот Telegram уже привязан к другому сотруднику")
    row.phone = row.telegram_pending_phone or row.phone
    row.telegram_pending_phone = None
    row.telegram_status = "approved"
    db.commit()
    try:
        from telegram_bot import send_telegram_to_chat
        send_telegram_to_chat(row.telegram_chat_id, "✅ Ваша привязка Telegram одобрена. Теперь доступны команды /who, /week, /schedule, /status и /whoami.")
    except Exception:
        logger.exception("Could not notify Telegram registration approval")
    return {"ok": True, "staff_id": row.id, "telegram_status": row.telegram_status}


@app.post("/api/telegram/registrations/{staff_id}/reject")
def reject_telegram_registration(staff_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.query(User).filter(User.id == staff_id, User.telegram_status == "pending").first()
    if not row:
        raise HTTPException(404, "Заявка не найдена")
    chat_id = row.telegram_chat_id
    row.telegram_chat_id = None
    row.telegram_pending_phone = None
    row.telegram_status = "unlinked"
    db.commit()
    try:
        from telegram_bot import send_telegram_to_chat
        if chat_id:
            send_telegram_to_chat(chat_id, "Заявка на привязку Telegram отклонена. Проверьте данные или обратитесь к администратору.")
    except Exception:
        logger.exception("Could not notify Telegram registration rejection")
    return {"ok": True, "staff_id": row.id, "telegram_status": row.telegram_status}


@app.post("/api/staff", response_model=schemas.StaffOut)
def create_staff(data: schemas.StaffCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Логин уже занят")
    pos_name = data.position
    if data.position_id:
        pos = db.query(Position).filter(Position.id == data.position_id).first()
        if pos:
            pos_name = pos.name
            if data.can_do_ppr is True and pos.can_do_ppr_default:
                pass  # keep explicit
    u = User(
        username=data.username,
        full_name=data.full_name,
        surname=data.surname,
        first_name=data.first_name,
        patronymic=data.patronymic,
        gender=data.gender,
        hashed_password=get_password_hash(data.password),
        role=data.role,
        department_id=data.department_id,
        position=pos_name,
        position_id=data.position_id,
        phone=data.phone,
        email=data.email,
        can_do_ppr=data.can_do_ppr,
        can_duty=data.can_duty,
        ppr_specialty=getattr(data, "ppr_specialty", None),
        notes=data.notes,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@app.patch("/api/staff/{staff_id}", response_model=schemas.StaffOut)
def update_staff(staff_id: int, data: schemas.StaffUpdate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == staff_id).first()
    if not u:
        raise HTTPException(404, "Сотрудник не найден")
    payload = data.model_dump(exclude_unset=True)
    if "password" in payload and payload["password"]:
        u.hashed_password = get_password_hash(payload.pop("password"))
    else:
        payload.pop("password", None)
    for k, v in payload.items():
        setattr(u, k, v)
    db.commit()
    db.refresh(u)
    return u


@app.delete("/api/staff/{staff_id}")
def deactivate_staff(staff_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == staff_id).first()
    if not u:
        raise HTTPException(404, "Сотрудник не найден")
    u.is_active = False
    db.commit()
    return {"ok": True}


# ========== Duty schedule (дежурства) ==========
def _check_duty_scope(user: User, department_id: Optional[int]) -> None:
    """Администратор видит все графики; руководитель — общий и своего подразделения."""
    if user.role == "admin":
        return
    if user.role == "head" and (department_id is None or department_id == user.department_id):
        return
    raise HTTPException(403, "Доступ разрешён только администратору или руководителю своего подразделения")


@app.get("/api/duties", response_model=List[schemas.DutyOut])
def list_duties(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    user_id: Optional[int] = None,
    department_id: Optional[int] = None,
    scope: Optional[str] = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if user.role not in ("admin", "head"):
        raise HTTPException(403, "Графики дежурств доступны администратору и руководителям подразделений")
    q = db.query(DutySchedule).join(Department, DutySchedule.department_id == Department.id).options(joinedload(DutySchedule.user)).filter(Department.duty_enabled == True, Department.is_active == True)
    if user.role == "head":
        q = q.filter((DutySchedule.department_id == user.department_id) | (DutySchedule.department_id.is_(None)))
    if from_date:
        q = q.filter(DutySchedule.duty_date >= from_date)
    if to_date:
        q = q.filter(DutySchedule.duty_date <= to_date)
    if user_id:
        q = q.filter(DutySchedule.user_id == user_id)
    if scope == "global":
        q = q.filter(DutySchedule.department_id.is_(None))
    elif department_id is not None:
        q = q.filter(DutySchedule.department_id == department_id)
    return q.order_by(DutySchedule.duty_date, DutySchedule.department_id, DutySchedule.shift, DutySchedule.id).all()


@app.get("/api/duties/today")
def duty_today(user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.role not in ("admin", "head"):
        raise HTTPException(403, "Графики дежурств доступны администратору и руководителям подразделений")
    today = date.today()
    duties = (
        db.query(DutySchedule)
        .join(Department, DutySchedule.department_id == Department.id)
        .options(joinedload(DutySchedule.user))
        .filter(Department.duty_enabled == True, Department.is_active == True)
        .filter(DutySchedule.duty_date == today)
        .filter(
            ((DutySchedule.department_id == user.department_id) | (DutySchedule.department_id.is_(None)))
            if user.role == "head" else True
        )
        .order_by(DutySchedule.department_id, DutySchedule.id)
        .all()
    )
    return [
        {
            "id": d.id,
            "duty_date": d.duty_date.isoformat(),
            "shift": d.shift,
            "user_id": d.user_id,
            "department_id": d.department_id,
            "full_name": d.user.full_name if d.user else None,
            "username": d.user.username if d.user else None,
        }
        for d in duties
    ]


@app.post("/api/duties", response_model=schemas.DutyOut)
def create_duty(data: schemas.DutyCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if data.department_id is None:
        raise HTTPException(422, "Назначение создаётся только в графике конкретного подразделения; общий график доступен только для просмотра")
    _check_duty_scope(user, data.department_id)
    shift = (data.shift or "day").strip().lower()
    if shift not in {"day", "night", "full"}:
        raise HTTPException(422, "Смена должна быть day, night или full")
    staff = db.query(User).filter(User.id == data.user_id).first()
    if not staff:
        raise HTTPException(404, "Сотрудник не найден")
    if not staff.is_active or not staff.can_duty:
        raise HTTPException(422, "Назначить можно только активного сотрудника с правом дежурства")
    if data.department_id is not None:
        department = db.query(Department).filter(Department.id == data.department_id).first()
        if not department or not department.is_active:
            raise HTTPException(422, "Подразделение не найдено или неактивно")
        if not department.duty_enabled:
            raise HTTPException(422, "Это подразделение исключено из дежурств")
        if staff.department_id != data.department_id:
            raise HTTPException(422, "Для графика подразделения выберите сотрудника этого подразделения")
    existing = db.query(DutySchedule).filter(
        DutySchedule.duty_date == data.duty_date,
        DutySchedule.shift == shift,
        DutySchedule.department_id == data.department_id if data.department_id is not None else DutySchedule.department_id.is_(None),
    ).first()
    if existing:
        existing.user_id = data.user_id
        existing.notes = data.notes
        db.commit()
        db.refresh(existing)
        return existing
    d = DutySchedule(
        duty_date=data.duty_date,
        user_id=data.user_id,
        department_id=data.department_id,
        shift=shift,
        notes=data.notes,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


@app.post("/api/duties/bulk")
def create_duties_bulk(data: schemas.DutyBulkCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if data.department_id is None:
        raise HTTPException(422, "Массовое назначение возможно только для конкретного подразделения")
    _check_duty_scope(user, data.department_id)
    shift = (data.shift or "day").strip().lower()
    if shift not in {"day", "night", "full"}:
        raise HTTPException(422, "Смена должна быть day, night или full")
    staff = db.query(User).filter(User.id == data.user_id).first()
    if not staff:
        raise HTTPException(404, "Сотрудник не найден")
    if not staff.is_active or not staff.can_duty:
        raise HTTPException(422, "Назначить можно только активного сотрудника с правом дежурства")
    if data.department_id is not None:
        department = db.query(Department).filter(Department.id == data.department_id).first()
        if not department or not department.is_active:
            raise HTTPException(422, "Подразделение не найдено или неактивно")
        if not department.duty_enabled:
            raise HTTPException(422, "Это подразделение исключено из дежурств")
        if staff.department_id != data.department_id:
            raise HTTPException(422, "Для графика подразделения выберите сотрудника этого подразделения")
    dates = sorted(set(data.dates))
    created = 0
    updated = 0
    for duty_date in dates:
        q = db.query(DutySchedule).filter(
            DutySchedule.duty_date == duty_date,
            DutySchedule.shift == shift,
        )
        q = q.filter(
            DutySchedule.department_id == data.department_id
            if data.department_id is not None else DutySchedule.department_id.is_(None)
        )
        existing = q.first()
        if existing:
            existing.user_id = data.user_id
            existing.notes = data.notes
            updated += 1
        else:
            db.add(DutySchedule(
                duty_date=duty_date,
                user_id=data.user_id,
                department_id=data.department_id,
                shift=shift,
                notes=data.notes,
            ))
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "message": f"Создано {created}, обновлено {updated}"}


@app.delete("/api/duties/{duty_id}")
def delete_duty(duty_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    d = db.query(DutySchedule).filter(DutySchedule.id == duty_id).first()
    if not d:
        raise HTTPException(404, "Запись не найдена")
    _check_duty_scope(user, d.department_id)
    db.delete(d)
    db.commit()
    return {"ok": True}


@app.post("/api/planning/reassign-by-duty")
def api_reassign_by_duty(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(403, "Массовое переназначение задач по всем подразделениям доступно только администратору")
    return reassign_plans_by_duty(db, year, month)



# ========== Directories ==========
@app.get("/api/departments", response_model=List[schemas.DepartmentOut])
def list_departments(active_only: bool = True, db: Session = Depends(get_db)):
    q = db.query(Department)
    if active_only:
        q = q.filter(Department.is_active == True)
    return q.order_by(Department.sort_order, Department.name).all()


@app.post("/api/departments", response_model=schemas.DepartmentOut)
def create_department(data: schemas.DepartmentCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if db.query(Department).filter(Department.name == data.name).first():
        raise HTTPException(400, "Подразделение уже существует")
    d = Department(**data.model_dump())
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


@app.patch("/api/departments/{dept_id}", response_model=schemas.DepartmentOut)
def update_department(dept_id: int, data: schemas.DepartmentUpdate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    d = db.query(Department).filter(Department.id == dept_id).first()
    if not d:
        raise HTTPException(404, "Не найдено")
    updates = data.model_dump(exclude_unset=True)
    if "excluded_template_ids" in updates and updates["excluded_template_ids"] is not None:
        ids = sorted(set(updates["excluded_template_ids"]))
        if ids:
            found = {row[0] for row in db.query(PPRTemplate.id).filter(PPRTemplate.id.in_(ids)).all()}
            missing = set(ids) - found
            if missing:
                raise HTTPException(422, f"Не найдены регламенты: {sorted(missing)}")
        updates["excluded_template_ids"] = ids
    for k, v in updates.items():
        setattr(d, k, v)
    db.commit()
    db.refresh(d)
    return d


@app.get("/api/positions", response_model=List[schemas.PositionOut])
def list_positions(department_id: Optional[int] = None, active_only: bool = True, db: Session = Depends(get_db)):
    q = db.query(Position).options(joinedload(Position.department))
    if active_only:
        q = q.filter(Position.is_active == True)
    if department_id:
        q = q.filter(Position.department_id == department_id)
    return q.order_by(Position.name).all()


@app.post("/api/positions", response_model=schemas.PositionOut)
def create_position(data: schemas.PositionCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    pos = Position(**data.model_dump())
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return pos


@app.patch("/api/positions/{pos_id}", response_model=schemas.PositionOut)
def update_position(pos_id: int, data: schemas.PositionUpdate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    pos = db.query(Position).filter(Position.id == pos_id).first()
    if not pos:
        raise HTTPException(404, "Не найдено")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(pos, k, v)
    db.commit()
    db.refresh(pos)
    return pos


@app.get("/api/roles", response_model=List[schemas.SystemRoleOut])
def list_roles(db: Session = Depends(get_db)):
    return db.query(SystemRole).filter(SystemRole.is_active == True).order_by(SystemRole.id).all()


@app.post("/api/roles", response_model=schemas.SystemRoleOut)
def create_role(data: schemas.SystemRoleCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if db.query(SystemRole).filter(SystemRole.code == data.code).first():
        raise HTTPException(400, "Код роли уже есть")
    r = SystemRole(**data.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r



# ========== Import Excel ==========
@app.post("/api/import/excel")
def api_import_excel(
    path: Optional[str] = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return import_from_excel(db, path)


# ========== Object relocate / delete ==========
@app.post("/api/objects/{object_id}/relocate")
def relocate_object(
    object_id: int,
    new_address: str = Query(...),
    reason: Optional[str] = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    obj = db.query(Object).filter(Object.id == object_id).first()
    if not obj:
        raise HTTPException(404, "Объект не найден")
    old = obj.address
    obj.address = new_address
    obj.status = "active"
    db.add(RelocationLog, NotificationLog(
        object_id=obj.id,
        old_address=old,
        new_address=new_address,
        reason=reason or "Перенос",
        date=date.today(),
    ))
    db.commit()
    return {"ok": True, "old": old, "new": new_address}


@app.get("/api/objects/{object_id}/relocations")
def object_relocations(object_id: int, db: Session = Depends(get_db)):
    rows = db.query(RelocationLog, NotificationLog).filter(RelocationLog, NotificationLog.object_id == object_id).order_by(RelocationLog, NotificationLog.date.desc()).all()
    return [
        {"id": r.id, "old_address": r.old_address, "new_address": r.new_address, "reason": r.reason, "date": r.date.isoformat() if r.date else None}
        for r in rows
    ]


@app.delete("/api/objects/{object_id}")
def deactivate_object(object_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    obj = db.query(Object).filter(Object.id == object_id).first()
    if not obj:
        raise HTTPException(404, "Объект не найден")
    obj.status = "decommissioned"
    db.commit()
    return {"ok": True}



# ========== Relocations journal ==========
@app.get("/api/relocations")
def list_relocations(limit: int = 50, db: Session = Depends(get_db)):
    rows = (
        db.query(RelocationLog)
        .order_by(RelocationLog.date.desc(), RelocationLog.id.desc())
        .limit(limit)
        .all()
    )
    result = []
    for r in rows:
        obj = db.query(Object).filter(Object.id == r.object_id).first()
        result.append({
            "id": r.id,
            "object_id": r.object_id,
            "object_code": obj.code if obj else None,
            "old_address": r.old_address,
            "new_address": r.new_address,
            "reason": r.reason,
            "date": r.date.isoformat() if r.date else None,
        })
    return result


# ========== Notifications ==========
@app.get("/api/notifications")
def list_notifications(limit: int = 50, user: User = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.query(NotificationLog).order_by(NotificationLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "message": r.message,
            "meta": r.meta_json,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@app.post("/api/notifications/test")
def test_notification(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    sent = notify_message(db, "manual", f"Тестовое уведомление от {user.full_name or user.username}")
    if sent:
        return {"ok": True, "telegram_sent": True, "message": "Тестовое уведомление отправлено в Telegram и записано в журнал."}
    return {"ok": True, "telegram_sent": False, "message": "Запись добавлена в журнал, но Telegram не отправлен. Проверьте, что интеграция включена, токен и Chat ID заданы, а бот имеет доступ к чату."}


@app.post("/api/planning/run-daily")
def run_daily_jobs_now(user: User = Depends(require_admin)):
    """Ручной запуск ежедневных jobs (просрочки, дежурные, 1-е число)."""
    from scheduler import _run_daily_jobs
    _run_daily_jobs()
    return {"ok": True, "message": "Ежедневные задачи выполнены"}


# ========== Static frontend ==========
STATIC_DIR = Path(__file__).parent / "static"

@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api"):
        raise HTTPException(404, "Not found")
    file = STATIC_DIR / full_path
    if file.exists() and file.is_file():
        return FileResponse(file)
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
