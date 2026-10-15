from sqlalchemy import (
    Column, Integer, String, Text, Date, DateTime, Boolean, Float,
    ForeignKey, Enum as SQLEnum, JSON
)
from sqlalchemy.orm import relationship
from datetime import datetime, date
from database import Base
import enum


class ObjectType(str, enum.Enum):
    CAMERA_INTEGRATION = "camera_integration"  # ИНТ
    OVN = "ovn"                                # ОВН (уличные)
    VOLES = "voles"                            # ВОЛС
    SIP = "sip"                                # СИП
    NETWORK = "network"                        # Сетевое оборудование ОСС
    OTHER = "other"


class Periodicity(str, enum.Enum):
    DAILY = "daily"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    TWICE_YEAR = "twice_year"


class PPRStatus(str, enum.Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class Object(Base):
    __tablename__ = "objects"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=False)  # ИНТ-01, ОВН-043
    name = Column(String(255))
    address = Column(Text)
    object_type = Column(String(50), default=ObjectType.CAMERA_INTEGRATION.value)
    cameras_count = Column(Integer, default=0)
    status = Column(String(30), default="active")  # active, relocated, decommissioned
    responsible_default = Column(String(150))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    ppr_plans = relationship("PPRPlan", back_populates="object")


class PPRTemplate(Base):
    """Шаблоны регламентных работ из Положения ОСС и АПК"""
    __tablename__ = "ppr_templates"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True)  # 1, 2, 7.5, 9.2 ...
    name = Column(String(255), nullable=False)
    description = Column(Text)
    object_types = Column(JSON, default=list)  # список типов объектов
    work_items = Column(JSON, default=list)    # список конкретных работ
    periodicity = Column(String(30), default=Periodicity.MONTHLY.value)
    responsible_role = Column(String(50), default="engineer")
    is_active = Column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    full_name = Column(String(150))
    role = Column(String(30), default="engineer")  # engineer, head, admin
    is_active = Column(Boolean, default=True)
    hashed_password = Column(String(255))


class PPRPlan(Base):
    """Конкретная задача ППР"""
    __tablename__ = "ppr_plans"

    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("objects.id"), nullable=True)
    template_id = Column(Integer, ForeignKey("ppr_templates.id"), nullable=True)
    title = Column(String(255))
    planned_date = Column(Date)
    fact_date = Column(Date, nullable=True)
    responsible = Column(String(150))
    status = Column(String(30), default=PPRStatus.PLANNED.value)
    work_types_done = Column(JSON, default=list)  # ["7.5", "7.6"]
    comment = Column(Text)
    act_file = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    object = relationship("Object", back_populates="ppr_plans")
    template = relationship("PPRTemplate")


class DailyCheck(Base):
    """Ежедневный операционный контроль (раздел 2 Положения)"""
    __tablename__ = "daily_checks"

    id = Column(Integer, primary_key=True, index=True)
    check_date = Column(Date, index=True)
    engineer = Column(String(150))
    monitoring_dashboard = Column(String(20), default="ok")  # ok / issues
    critical_services = Column(String(20), default="ok")
    logs_security = Column(String(20), default="ok")
    config_backups = Column(String(20), default="ok")
    channel_utilization = Column(String(20), default="ok")
    ups_status = Column(String(20), default="ok")
    incidents_logged = Column(Boolean, default=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class RelocationLog(Base):
    """История переносов объектов (ОВН и др.)"""
    __tablename__ = "relocation_logs"

    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("objects.id"))
    old_address = Column(Text)
    new_address = Column(Text)
    reason = Column(Text)
    date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)
