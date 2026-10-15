"""JWT-авторизация с bcrypt-хешированием паролей"""
from datetime import datetime, timedelta
import hashlib
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
from sqlalchemy.orm import Session
from database import get_db
from models import User
from pydantic import BaseModel

SECRET_KEY = "satory-ppr-oss-apk-2026-secret-key-change-in-prod"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


class Token(BaseModel):
    access_token: str
    token_type: str
    full_name: str
    role: str


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    department_id: Optional[int] = None

    class Config:
        from_attributes = True


def _is_password_hash(value: str) -> bool:
    return value.startswith("$2") or value.startswith("$bcrypt-sha256$")


def verify_password(plain: str, hashed: str) -> bool:
    """Поддерживает обычный bcrypt и SHA-256 pre-hash для паролей длиннее 72 байт."""
    if not hashed:
        return False
    if hashed.startswith("$bcrypt-sha256$"):
        try:
            digest = hashlib.sha256(plain.encode("utf-8")).hexdigest().encode("ascii")
            return bcrypt.checkpw(digest, hashed.removeprefix("$bcrypt-sha256$").encode("utf-8"))
        except (ValueError, TypeError):
            return False
    if not hashed.startswith("$2"):
        # Совместимость с legacy-паролями в открытом виде.
        return plain == hashed
    try:
        raw = plain.encode("utf-8")
        if len(raw) > 72:
            return False
        return bcrypt.checkpw(raw, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    """Создаёт bcrypt-хеш; длинные пароли безопасно предварительно хешируются SHA-256."""
    raw = password.encode("utf-8")
    if len(raw) > 72:
        digest = hashlib.sha256(raw).hexdigest().encode("ascii")
        return "$bcrypt-sha256$" + bcrypt.hashpw(digest, bcrypt.gensalt()).decode("utf-8")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password or ""):
        return None
    if user.hashed_password and not _is_password_hash(user.hashed_password):
        user.hashed_password = get_password_hash(password)
        db.commit()
    return user


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None
    return db.query(User).filter(User.username == username).first()


async def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(user: User = Depends(require_user)) -> User:
    if user.role not in ("admin", "head"):
        raise HTTPException(status_code=403, detail="Недостаточно прав (нужна роль admin или head)")
    return user


def is_manager(user: User) -> bool:
    return user.role in ("admin", "head")
