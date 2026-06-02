from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import os
import secrets

from app.database import get_db
from app.models import User

def _load_or_create_secret() -> str:
    """Берём ключ из переменной окружения. Если не задан или дефолтный —
    генерируем случайный и сохраняем в data/secret.key, чтобы он переживал
    перезапуски (иначе сессии слетали бы при каждом рестарте)."""
    env_key = os.getenv("SECRET_KEY", "").strip()
    if env_key and env_key not in ("default-secret-change-me", "change-this-to-random-string-in-production"):
        return env_key
    # Иначе — постоянный ключ в data/
    key_path = "/app/data/secret.key"
    try:
        if os.path.exists(key_path):
            with open(key_path, "r") as f:
                saved = f.read().strip()
                if saved:
                    return saved
        os.makedirs("/app/data", exist_ok=True)
        new_key = secrets.token_urlsafe(48)
        with open(key_path, "w") as f:
            f.write(new_key)
        os.chmod(key_path, 0o600)
        return new_key
    except Exception:
        # Фолбэк: эфемерный ключ (сессии слетят при рестарте, но работа не встанет)
        return secrets.token_urlsafe(48)


SECRET_KEY = _load_or_create_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7  # неделя

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )
    return user


def require_role(*roles):
    def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {roles}"
            )
        return user
    return role_checker


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def require_manager(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Manager or admin required")
    return user
