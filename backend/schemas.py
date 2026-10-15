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
    title: Optional[str] = None
    planned_date: date
    responsible: Optional[str] = None
    status: str = "planned"
    work_types_done: List[str] = []
    comment: Optional[str] = None


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
