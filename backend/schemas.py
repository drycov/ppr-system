from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import date, datetime


class ObjectBase(BaseModel):
    code: str
    name: Optional[str] = None
    address: Optional[str] = None
    object_type: str = "camera_integration"
    cameras_count: int = 0
    status: str = "active"
    responsible_default: Optional[str] = None
    notes: Optional[str] = None


class ObjectCreate(ObjectBase):
    pass


class ObjectUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    cameras_count: Optional[int] = None
    status: Optional[str] = None
    responsible_default: Optional[str] = None
    notes: Optional[str] = None


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
    is_active: bool = True


class PPRTemplateOut(PPRTemplateBase):
    id: int

    class Config:
        from_attributes = True


class PPRPlanBase(BaseModel):
    object_id: Optional[int] = None
    template_id: Optional[int] = None
    assignee_id: Optional[int] = None
    title: Optional[str] = None
    planned_date: date
    responsible: Optional[str] = None
    status: str = "planned"
    work_types_done: List[str] = []
    comment: Optional[str] = None
    assigned_by_duty: bool = False


class PPRPlanCreate(PPRPlanBase):
    pass


class PPRPlanUpdate(BaseModel):
    fact_date: Optional[date] = None
    status: Optional[str] = None
    work_types_done: Optional[List[str]] = None
    comment: Optional[str] = None
    responsible: Optional[str] = None


class PPRPlanOut(PPRPlanBase):
    id: int
    fact_date: Optional[date] = None
    created_at: Optional[datetime] = None
    object: Optional[ObjectOut] = None

    class Config:
        from_attributes = True


class DailyCheckBase(BaseModel):
    check_date: date
    engineer: str
    monitoring_dashboard: str = "ok"
    critical_services: str = "ok"
    logs_security: str = "ok"
    config_backups: str = "ok"
    channel_utilization: str = "ok"
    ups_status: str = "ok"
    incidents_logged: bool = True
    notes: Optional[str] = None


class DailyCheckCreate(DailyCheckBase):
    pass


class DailyCheckOut(DailyCheckBase):
    id: int
    created_at: Optional[datetime] = None

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
    password: str = "eng"
    role: str = "engineer"
    position: Optional[str] = None
    department_id: Optional[int] = None
    position_id: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    can_do_ppr: bool = True
    can_duty: bool = True
    notes: Optional[str] = None


class StaffUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    position: Optional[str] = None
    department_id: Optional[int] = None
    position_id: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    can_do_ppr: Optional[bool] = None
    can_duty: Optional[bool] = None
    notes: Optional[str] = None
    password: Optional[str] = None


class StaffOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    role: str
    position: Optional[str] = None
    department_id: Optional[int] = None
    position_id: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: bool = True
    can_do_ppr: bool = True
    can_duty: bool = True
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class DutyCreate(BaseModel):
    duty_date: date
    user_id: int
    shift: str = "day"
    notes: Optional[str] = None


class DutyOut(BaseModel):
    id: int
    duty_date: date
    user_id: int
    shift: str
    notes: Optional[str] = None
    user: Optional[StaffOut] = None

    class Config:
        from_attributes = True


class DutyBulkCreate(BaseModel):
    """Массовое назначение: список дат одному сотруднику"""
    user_id: int
    dates: List[date]
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


class DepartmentOut(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    sort_order: int = 0
    notes: Optional[str] = None
    is_active: bool = True

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
