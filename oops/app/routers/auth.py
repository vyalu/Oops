from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os

from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserOut
from app.auth import verify_password, create_access_token, get_current_user, hash_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# secure-cookie включается за HTTPS-прокси (COOKIE_SECURE=1). По умолчанию off — чтобы работать по HTTP в локалке.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").strip() in ("1", "true", "yes", "on")


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not user.is_active or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

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
    if len(data.new_password) < 4:
        raise HTTPException(status_code=400, detail="Новый пароль слишком короткий (минимум 4 символа)")
    if data.new_password == "admin":
        raise HTTPException(status_code=400, detail="Нельзя использовать пароль «admin»")
    user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"success": True}
