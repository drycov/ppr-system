from pathlib import Path
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# Локальный файл рядом с backend; на Windows это D:\\dev\\ppr-system\\backend\\ppr_system.db
# В sandbox при проблемах с диском можно задать PPR_DB_PATH
_default = Path(__file__).resolve().parent / "ppr_system.db"
DB_PATH = Path(os.environ.get("PPR_DB_PATH", str(_default)))
try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    DB_PATH = Path("/tmp/ppr_system.db")

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_user_fio_columns():
    """
    Добавляет колонки surname / first_name / patronymic / gender в таблицу users,
    если их ещё нет (SQLite не умеет ALTER через create_all).
    """
    try:
        insp = inspect(engine)
        if "users" not in insp.get_table_names():
            return
        existing = {c["name"] for c in insp.get_columns("users")}
        alters = []
        if "surname" not in existing:
            alters.append("ALTER TABLE users ADD COLUMN surname VARCHAR(80)")
        if "first_name" not in existing:
            alters.append("ALTER TABLE users ADD COLUMN first_name VARCHAR(80)")
        if "patronymic" not in existing:
            alters.append("ALTER TABLE users ADD COLUMN patronymic VARCHAR(80)")
        if "gender" not in existing:
            alters.append("ALTER TABLE users ADD COLUMN gender VARCHAR(1)")
        if not alters:
            return
        with engine.begin() as conn:
            for stmt in alters:
                conn.execute(text(stmt))
        print(f"✓ Миграция users: добавлены колонки FIO ({len(alters)})")
    except Exception as e:
        print(f"⚠ migrate_user_fio_columns: {e}")



def migrate_daily_checklist_column():
    """Добавляет колонку checklist в daily_checks, если её нет."""
    try:
        insp = inspect(engine)
        if "daily_checks" not in insp.get_table_names():
            return
        existing = {c["name"] for c in insp.get_columns("daily_checks")}
        if "checklist" in existing:
            return
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE daily_checks ADD COLUMN checklist JSON"))
        print("✓ Миграция daily_checks: добавлена колонка checklist")
    except Exception as e:
        print(f"⚠ migrate_daily_checklist_column: {e}")

def migrate_ppr_direction_columns():
    """work_direction у шаблонов, ppr_specialty у users."""
    try:
        insp = inspect(engine)
        tables = insp.get_table_names()
        with engine.begin() as conn:
            if "ppr_templates" in tables:
                cols = {c["name"] for c in insp.get_columns("ppr_templates")}
                if "work_direction" not in cols:
                    conn.execute(text(
                        "ALTER TABLE ppr_templates ADD COLUMN work_direction VARCHAR(40) DEFAULT 'network_engineer'"
                    ))
                    print("✓ ppr_templates.work_direction")
            if "users" in tables:
                cols = {c["name"] for c in insp.get_columns("users")}
                if "ppr_specialty" not in cols:
                    conn.execute(text(
                        "ALTER TABLE users ADD COLUMN ppr_specialty VARCHAR(40)"
                    ))
                    print("✓ users.ppr_specialty")
    except Exception as e:
        print(f"⚠ migrate_ppr_direction_columns: {e}")


def migrate_object_equipment_columns():
    """Добавляет switches_count / routers_count / children_count в objects для узлов связи."""
    try:
        insp = inspect(engine)
        if "objects" not in insp.get_table_names():
            return
        existing = {c["name"] for c in insp.get_columns("objects")}
        alters = []
        if "switches_count" not in existing:
            alters.append("ALTER TABLE objects ADD COLUMN switches_count INTEGER DEFAULT 0")
        if "routers_count" not in existing:
            alters.append("ALTER TABLE objects ADD COLUMN routers_count INTEGER DEFAULT 0")
        if "children_count" not in existing:
            alters.append("ALTER TABLE objects ADD COLUMN children_count INTEGER DEFAULT 0")
        if not alters:
            return
        with engine.begin() as conn:
            for stmt in alters:
                conn.execute(text(stmt))
        print(f"✓ Миграция objects: добавлены колонки оборудования узла ({len(alters)})")
    except Exception as e:
        print(f"⚠ migrate_object_equipment_columns: {e}")


# Авто-миграция при импорте модуля (после create_all в startup тоже безопасно)
migrate_user_fio_columns()
migrate_daily_checklist_column()
migrate_ppr_direction_columns()
migrate_object_equipment_columns()
