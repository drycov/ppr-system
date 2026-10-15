from sqlalchemy import (
    Column, Integer, String, Text, Date, DateTime, Boolean, Float,
    ForeignKey, Enum as SQLEnum, JSON
)
from sqlalchemy.orm import relationship
from datetime import datetime, date
from database import Base
import enum


class ObjectType(str, enum.Enum):
    # АПК / линии
    CAMERA_INTEGRATION = "camera_integration"  # ИНТ
    OVN = "ovn"                                # ОВН (уличные)
    VOLES = "voles"                            # ВОЛС
    SIP = "sip"                                # СИП
    # Сетевая инфраструктура ОСС
    NETWORK = "network"                        # Сеть ОСС (общее)
    US = "us"                                  # УС — узел связи
    COD = "cod"                                # ЦОД
    CORE_ROUTER = "core_router"                # Роутер ядра
    CORE_SWITCH = "core_switch"                # Коммутатор ядра
    ACCESS_SWITCH = "access_switch"            # Коммутатор доступа
    EDGE_ROUTER = "edge_router"                # Граничный / провайдерский роутер
    WIFI_CONTROLLER = "wifi_controller"        # Контроллер Wi-Fi
    SERVER = "server"                          # Сервер сетевых служб
    UPS = "ups"                                # ИБП
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


class WorkDirection(str, enum.Enum):
    """Направление исполнения ППР (организационное распределение)"""
    SYSADMIN = "sysadmin"              # Системные администраторы
    INSTALLER = "installer"            # Монтажники
    NETWORK_ENGINEER = "network_engineer"  # Сетевые инженеры
    HEAD = "head"                      # Начальник ОСС (инвентаризация и т.п.)
    ANY = "any"                        # любой исполнитель ППР


class PPRTemplate(Base):
    """Шаблоны регламентных работ из Положения ОСС и АПК"""
    __tablename__ = "ppr_templates"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True)  # 1, 2, SA-1, NE-3, 7.5 ...
    name = Column(String(255), nullable=False)
    description = Column(Text)
    object_types = Column(JSON, default=list)  # список типов объектов; [] = общесистемные
    work_items = Column(JSON, default=list)    # список конкретных работ
    periodicity = Column(String(30), default=Periodicity.MONTHLY.value)
    responsible_role = Column(String(50), default="engineer")  # системная роль
    work_direction = Column(String(40), default="network_engineer")  # sysadmin/installer/network_engineer
    is_active = Column(Boolean, default=True)
    # Empty means shared across all departments; otherwise limited to assigned departments.
    department_ids = Column(JSON, default=list, nullable=False)
    # Departments excluded from this regulation even when it is shared.
    excluded_department_ids = Column(JSON, default=list, nullable=False)



class Department(Base):
    """Справочник подразделений"""
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False)
    code = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    notes = Column(Text, nullable=True)
    # PPR templates disabled specifically for this department.
    excluded_template_ids = Column(JSON, default=list, nullable=False)

    positions = relationship("Position", back_populates="department")
    users = relationship("User", back_populates="department")


class Position(Base):
    """Справочник должностей"""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    can_do_ppr_default = Column(Boolean, default=False)  # по умолчанию участвует в ППР
    can_duty_default = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)

    department = relationship("Department", back_populates="positions")
    users = relationship("User", back_populates="position_ref")


class SystemRole(Base):
    """Справочник системных ролей (права в приложении)"""
    __tablename__ = "system_roles"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False)  # admin, head, engineer, viewer
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)


class User(Base):
    """Сотрудник ОСС / исполнитель ППР"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    full_name = Column(String(150))  # нормализованное ФИО целиком (для отображения/отчётов)

    # Разбор ФИО (заполняется автоматически при вводе full_name)
    surname = Column(String(80), nullable=True)       # Фамилия
    first_name = Column(String(80), nullable=True)    # Имя
    patronymic = Column(String(80), nullable=True)    # Отчество
    gender = Column(String(1), nullable=True)         # 'm' | 'f' | None

    role = Column(String(30), default="engineer")  # код из system_roles
    position = Column(String(150), nullable=True)  # отображаемое название должности
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(120), nullable=True)
    is_active = Column(Boolean, default=True)
    can_do_ppr = Column(Boolean, default=True)
    can_duty = Column(Boolean, default=True)
    # Направление ППР: sysadmin | installer | network_engineer | None
    ppr_specialty = Column(String(40), nullable=True)
    hashed_password = Column(String(255))
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    department = relationship("Department", back_populates="users")
    position_ref = relationship("Position", back_populates="users")
    duties = relationship("DutySchedule", back_populates="user")
    plans = relationship("PPRPlan", back_populates="assignee_user")


class DutySchedule(Base):
    """График дежурств: кто дежурит в какой день"""
    __tablename__ = "duty_schedules"

    id = Column(Integer, primary_key=True, index=True)
    duty_date = Column(Date, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    shift = Column(String(30), default="day")  # day / night / full
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="duties")


class PPRPlan(Base):
    """Конкретная задача ППР"""
    __tablename__ = "ppr_plans"

    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("objects.id"), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)
    template_id = Column(Integer, ForeignKey("ppr_templates.id"), nullable=True)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # назначенный сотрудник
    title = Column(String(255))
    planned_date = Column(Date)
    fact_date = Column(Date, nullable=True)
    responsible = Column(String(150))  # ФИО (дубль для отчётов)
    status = Column(String(30), default=PPRStatus.PLANNED.value)
    work_types_done = Column(JSON, default=list)  # ["7.5", "7.6"]
    comment = Column(Text)
    act_file = Column(String(255), nullable=True)
    assigned_by_duty = Column(Boolean, default=False)  # назначен по графику дежурств
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    object = relationship("Object", back_populates="ppr_plans")
    template = relationship("PPRTemplate")
    assignee_user = relationship("User", back_populates="plans")


class DailyCheck(Base):
    """Ежедневный операционный контроль (раздел 2 Положения)"""
    __tablename__ = "daily_checks"

    id = Column(Integer, primary_key=True, index=True)
    check_date = Column(Date, index=True)
    engineer = Column(String(150))
    monitoring_dashboard = Column(String(20), default="ok")  # ok / issues / skip
    critical_services = Column(String(20), default="ok")
    logs_security = Column(String(20), default="ok")
    config_backups = Column(String(20), default="ok")
    channel_utilization = Column(String(20), default="ok")
    ups_status = Column(String(20), default="ok")
    incidents_logged = Column(Boolean, default=True)
    # Чек-лист: [{code, name, done, status, note}, ...]
    checklist = Column(JSON, default=list)
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


class NotificationLog(Base):
    """Журнал уведомлений системы"""
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(50), index=True)  # overdue, duty, auto_plan, manual
    message = Column(Text)
    meta_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
