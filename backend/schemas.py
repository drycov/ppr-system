from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Any
from datetime import date, datetime

from fio_utils import normalize_fio, parse_fio


class ObjectBase(BaseModel):
    code: str
    name: Optional[str] = None
    address: Optional[str] = None
    object_type: str = "camera_integration"
    cameras_count: int = 0
    status: str = "active"
    responsible_default: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("responsible_default", mode="before")
    @classmethod
    def _norm_resp_default(cls, v):
        return normalize_fio(v) if v else v


class ObjectCreate(ObjectBase):
    pass


class ObjectUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    address: Optional[str] = None
    object_type: Optional[str] = None
    cameras_count: Optional[int] = None
    status: Optional[str] = None
    responsible_default: Optional[str] = None
    department_id: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("responsible_default", mode="before")
    @classmethod
    def _norm_resp_default(cls, v):
        return normalize_fio(v) if v is not None else v


class ObjectOut(ObjectBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PPRTemplateBase(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    object_types: List[str] = []
    work_items: List[str] = []
    periodicity: str = "monthly"
    responsible_role: str = "engineer"
    work_direction: str = "network_engineer"
    is_active: bool = True
    department_ids: List[int] = []


class PPRTemplateDepartmentsUpdate(BaseModel):
    department_ids: List[int] = []


class PPRTemplateOut(PPRTemplateBase):
    id: int

    class Config:
        from_attributes = True


class PPRPlanBase(BaseModel):
    object_id: Optional[int] = None
    department_id: Optional[int] = None
    template_id: Optional[int] = None
    assignee_id: Optional[int] = None
    title: Optional[str] = None
    planned_date: date
    responsible: Optional[str] = None
    status: str = "planned"
    work_types_done: List[str] = []
    comment: Optional[str] = None
    assigned_by_duty: bool = False

    @field_validator("responsible", mode="before")
    @classmethod
    def _norm_responsible(cls, v):
        return normalize_fio(v) if v else v


class PPRPlanCreate(PPRPlanBase):
    pass


class PPRPlanUpdate(BaseModel):
    object_id: Optional[int] = None
    department_id: Optional[int] = None
    template_id: Optional[int] = None
    assignee_id: Optional[int] = None
    title: Optional[str] = None
    planned_date: Optional[date] = None
    fact_date: Optional[date] = None
    status: Optional[str] = None
    work_types_done: Optional[List[str]] = None
    comment: Optional[str] = None
    responsible: Optional[str] = None
    assigned_by_duty: Optional[bool] = None

    @field_validator("responsible", mode="before")
    @classmethod
    def _norm_responsible(cls, v):
        return normalize_fio(v) if v is not None else v


class PPRPlanOut(PPRPlanBase):
    id: int
    fact_date: Optional[date] = None
    created_at: Optional[datetime] = None
    object: Optional[ObjectOut] = None

    class Config:
        from_attributes = True


class DailyChecklistItem(BaseModel):
    code: str
    name: str
    done: bool = False
    status: str = "ok"  # ok | issues | skip
    note: Optional[str] = None


# Эталонный чек-лист раздела 2 Положения ОСС
DAILY_CHECKLIST_TEMPLATE = [
    {"code": "D1", "field": "monitoring_dashboard", "name": "Дашборд системы мониторинга"},
    {"code": "D2", "field": "critical_services", "name": "Доступность ключевых сервисов"},
    {"code": "D3", "field": "logs_security", "name": "Логи и события безопасности"},
    {"code": "D4", "field": "config_backups", "name": "Резервные копии конфигураций"},
    {"code": "D5", "field": "channel_utilization", "name": "Загрузка каналов"},
    {"code": "D6", "field": "ups_status", "name": "Состояние ИБП"},
    {"code": "D7", "field": "incidents_logged", "name": "Фиксация инцидентов"},
]


class DailyCheckBase(BaseModel):
    check_date: date
    engineer: Optional[str] = None
    monitoring_dashboard: str = "ok"
    critical_services: str = "ok"
    logs_security: str = "ok"
    config_backups: str = "ok"
    channel_utilization: str = "ok"
    ups_status: str = "ok"
    incidents_logged: bool = True
    checklist: List[DailyChecklistItem] = []
    notes: Optional[str] = None

    @field_validator("engineer", mode="before")
    @classmethod
    def _norm_engineer(cls, v):
        return normalize_fio(v) if v else v


class DailyCheckCreate(DailyCheckBase):
    pass


class DailyCheckUpdate(BaseModel):
    """Обновление выполнения чек-листа"""
    engineer: Optional[str] = None
    monitoring_dashboard: Optional[str] = None
    critical_services: Optional[str] = None
    logs_security: Optional[str] = None
    config_backups: Optional[str] = None
    channel_utilization: Optional[str] = None
    ups_status: Optional[str] = None
    incidents_logged: Optional[bool] = None
    checklist: Optional[List[DailyChecklistItem]] = None
    notes: Optional[str] = None

    @field_validator("engineer", mode="before")
    @classmethod
    def _norm_engineer(cls, v):
        return normalize_fio(v) if v is not None else v


class DailyCheckOut(DailyCheckBase):
    id: int
    created_at: Optional[datetime] = None
    # сколько пунктов отмечено выполненными
    done_count: Optional[int] = None
    total_count: Optional[int] = None

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    total_objects: int
    active_objects: int
    planned_ppr: int
    done_ppr: int
    overdue_ppr: int
    completion_percent: float
    daily_checks_this_month: int
    engineers_count: int


class RegulationItem(BaseModel):
    code: str
    name: str
    content: str
    periodicity: str
    responsible: str


# ---- Staff / Duty ----
class StaffCreate(BaseModel):
    username: str
    full_name: str
    # Можно передать явно, иначе заполняются из full_name
    surname: Optional[str] = None
    first_name: Optional[str] = None
    patronymic: Optional[str] = None
    gender: Optional[str] = None  # 'm' | 'f'

    password: str = "eng"
    role: str = "engineer"
    position: Optional[str] = None
    department_id: Optional[int] = None
    position_id: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    can_do_ppr: bool = True
    can_duty: bool = True
    ppr_specialty: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _fill_fio_parts(self):
        """Нормализация + разбор ФИО → surname / first_name / patronymic / gender."""
        if self.full_name:
            p = parse_fio(self.full_name)
            self.full_name = p.get("full") or normalize_fio(self.full_name) or self.full_name
            if not self.surname:
                self.surname = p.get("surname")
            if not self.first_name:
                self.first_name = p.get("name")
            if not self.patronymic:
                self.patronymic = p.get("patronymic")
            if not self.gender:
                self.gender = p.get("gender")
        return self


class StaffUpdate(BaseModel):
    full_name: Optional[str] = None
    surname: Optional[str] = None
    first_name: Optional[str] = None
    patronymic: Optional[str] = None
    gender: Optional[str] = None

    role: Optional[str] = None
    position: Optional[str] = None
    department_id: Optional[int] = None
    position_id: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    can_do_ppr: Optional[bool] = None
    can_duty: Optional[bool] = None
    ppr_specialty: Optional[str] = None
    notes: Optional[str] = None
    password: Optional[str] = None

    @model_validator(mode="after")
    def _fill_fio_parts(self):
        if self.full_name is not None:
            p = parse_fio(self.full_name)
            self.full_name = p.get("full") or normalize_fio(self.full_name) or self.full_name
            # При обновлении full_name всегда перезаписываем части (если не переданы явно)
            if self.surname is None:
                self.surname = p.get("surname")
            if self.first_name is None:
                self.first_name = p.get("name")
            if self.patronymic is None:
                self.patronymic = p.get("patronymic")
            if self.gender is None:
                self.gender = p.get("gender")
        return self


class StaffOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    surname: Optional[str] = None
    first_name: Optional[str] = None
    patronymic: Optional[str] = None
    gender: Optional[str] = None
    role: str
    position: Optional[str] = None
    department_id: Optional[int] = None
    position_id: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: bool = True
    can_do_ppr: bool = True
    can_duty: bool = True
    ppr_specialty: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class DutyCreate(BaseModel):
    duty_date: date
    user_id: int
    department_id: Optional[int] = None  # null = общее дежурство для всех подразделений
    shift: str = "day"
    notes: Optional[str] = None


class DutyOut(BaseModel):
    id: int
    duty_date: date
    user_id: int
    department_id: Optional[int] = None
    shift: str
    notes: Optional[str] = None
    user: Optional[StaffOut] = None

    class Config:
        from_attributes = True


class DutyBulkCreate(BaseModel):
    """Массовое назначение: список дат одному сотруднику"""
    user_id: int
    dates: List[date]
    department_id: Optional[int] = None  # null = для всех подразделений
    shift: str = "day"
    notes: Optional[str] = None


# ---- Directories ----
class DepartmentCreate(BaseModel):
    name: str
    code: Optional[str] = None
    sort_order: int = 0
    notes: Optional[str] = None
    is_active: bool = True


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    sort_order: Optional[int] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    excluded_template_ids: Optional[List[int]] = None


class DepartmentOut(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    sort_order: int = 0
    notes: Optional[str] = None
    is_active: bool = True
    excluded_template_ids: List[int] = []

    class Config:
        from_attributes = True


class PositionCreate(BaseModel):
    name: str
    department_id: Optional[int] = None
    can_do_ppr_default: bool = False
    can_duty_default: bool = False
    notes: Optional[str] = None
    is_active: bool = True


class PositionUpdate(BaseModel):
    name: Optional[str] = None
    department_id: Optional[int] = None
    can_do_ppr_default: Optional[bool] = None
    can_duty_default: Optional[bool] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class PositionOut(BaseModel):
    id: int
    name: str
    department_id: Optional[int] = None
    can_do_ppr_default: bool = False
    can_duty_default: bool = False
    notes: Optional[str] = None
    is_active: bool = True
    department: Optional[DepartmentOut] = None

    class Config:
        from_attributes = True


class SystemRoleOut(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool = True

    class Config:
        from_attributes = True


class SystemRoleCreate(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool = True
