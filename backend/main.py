from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import List, Optional
from datetime import date, datetime, timedelta
from pathlib import Path
from io import BytesIO

from database import get_db, engine, Base
from models import Object, PPRTemplate, PPRPlan, DailyCheck, User
import schemas
import seed
from auth import (
    authenticate_user, create_access_token, require_user, require_admin,
    get_current_user, Token, UserOut, ACCESS_TOKEN_EXPIRE_HOURS
)
from planning import generate_plans_for_period, mark_overdue
from pdf_service import generate_ppr_act
from excel_export import export_ppr_report

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
    # Автосид при первом запуске
    db = next(get_db())
    try:
        if db.query(Object).count() == 0:
            print("Первый запуск — заполняем БД...")
            seed.seed_templates(db)
            seed.seed_users(db)
            seed.import_integration_objects(db)
            seed.import_voles_objects(db)
            seed.seed_sample_plans(db)
    finally:
        db.close()


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
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


# ========== Templates (Регламент) ==========
@app.get("/api/templates", response_model=List[schemas.PPRTemplateOut])
def list_templates(db: Session = Depends(get_db)):
    return db.query(PPRTemplate).filter(PPRTemplate.is_active == True).order_by(PPRTemplate.code).all()


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
    if responsible:
        q = q.filter(PPRPlan.responsible.ilike(f"%{responsible}%"))
    if from_date:
        q = q.filter(PPRPlan.planned_date >= from_date)
    if to_date:
        q = q.filter(PPRPlan.planned_date <= to_date)
    return q.order_by(PPRPlan.planned_date.desc()).offset(skip).limit(limit).all()


@app.post("/api/plans", response_model=schemas.PPRPlanOut)
def create_plan(data: schemas.PPRPlanCreate, db: Session = Depends(get_db)):
    plan = PPRPlan(**data.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@app.patch("/api/plans/{plan_id}", response_model=schemas.PPRPlanOut)
def update_plan(plan_id: int, data: schemas.PPRPlanUpdate, db: Session = Depends(get_db)):
    plan = db.query(PPRPlan).filter(PPRPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Задача не найдена")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(plan, k, v)
    if data.status == "done" and not plan.fact_date:
        plan.fact_date = date.today()
    db.commit()
    db.refresh(plan)
    return plan


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


# ========== Daily Checks ==========
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
    return q.order_by(DailyCheck.check_date.desc()).limit(limit).all()


@app.post("/api/daily-checks", response_model=schemas.DailyCheckOut)
def create_daily_check(data: schemas.DailyCheckCreate, db: Session = Depends(get_db)):
    existing = db.query(DailyCheck).filter(
        DailyCheck.check_date == data.check_date,
        DailyCheck.engineer == data.engineer,
    ).first()
    if existing:
        raise HTTPException(400, "Проверка на эту дату уже существует")
    check = DailyCheck(**data.model_dump())
    db.add(check)
    db.commit()
    db.refresh(check)
    return check


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
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    types = [object_type] if object_type else None
    result = generate_plans_for_period(db, year, month, object_types=types)
    return result


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
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    data = export_ppr_report(db, year, month)
    filename = f"Otchet_PPR_APK_{year}_{month:02d}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
