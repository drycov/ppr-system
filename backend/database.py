from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# Локальный файл рядом с backend; на Windows это D:\dev\ppr-system\backend\ppr_system.db
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
