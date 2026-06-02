from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import User
from app.schemas import UserCreate, UserUpdate, UserOut
from app.auth import require_admin, hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(User).all()


@router.post("/", response_model=UserOut)
def create_user(data: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Пользователь уже существует")
    if data.role not in ("admin", "manager", "viewer"):
        raise HTTPException(status_code=400, detail="Неверная роль")
    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=data.role
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.role is not None:
        if data.role not in ("admin", "manager", "viewer"):
            raise HTTPException(status_code=400, detail="Неверная роль")
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.password:
        user.password_hash = hash_password(data.password)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить себя")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    db.delete(user)
    db.commit()
    return {"success": True}
