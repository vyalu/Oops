from fastapi import APIRouter, Depends, HTTPException, Response, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os

from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserOut
from app.auth import verify_password, create_access_token, get_current_user, hash_password, check_new_password
import threading
import time

router = APIRouter(prefix="/api/auth", tags=["auth"])

# secure-cookie включается за HTTPS-прокси (COOKIE_SECURE=1). По умолчанию off — чтобы работать по HTTP в локалке.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").strip() in ("1", "true", "yes", "on")


# Защита от подбора пароля: не больше MAX_FAILS неудачных входов с одного IP за WINDOW секунд.
MAX_FAILS = 10
WINDOW = 15 * 60
_fails = {}
_fails_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _recent_fails(ip: str, now: float):
    lst = [t for t in _fails.get(ip, []) if now - t < WINDOW]
    if lst:
        _fails[ip] = lst
    else:
        _fails.pop(ip, None)
    return lst


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    now = time.time()
    with _fails_lock:
        fails = _recent_fails(ip, now)
        if len(fails) >= MAX_FAILS:
            wait = int(WINDOW - (now - fails[0])) // 60 + 1
            raise HTTPException(status_code=429, detail=f"Слишком много неудачных попыток входа. Попробуйте через {wait} мин.")

    user = db.query(User).filter(User.username == data.username).first()
    if not user or not user.is_active or not verify_password(data.password, user.password_hash):
        with _fails_lock:
            _fails.setdefault(ip, []).append(now)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    with _fails_lock:
        _fails.pop(ip, None)

    token = create_access_token({"sub": user.username, "role": user.role})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=60 * 60 * 24 * 7
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role
        }
    }


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"success": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    # Признак, что пользователь всё ещё с дефолтным паролем admin/admin
    must_change = user.username == "admin" and verify_password("admin", user.password_hash)
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "must_change_password": must_change,
    }


class ChangeOwnPassword(BaseModel):
    old_password: str
    new_password: str


@router.post("/change-password")
def change_own_password(data: ChangeOwnPassword, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Текущий пароль неверен")
    check_new_password(data.new_password)
    user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"success": True}
