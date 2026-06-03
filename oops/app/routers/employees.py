from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Employee, User
from app.schemas import EmployeeCreate, EmployeeOut
from app.auth import get_current_user, require_manager

router = APIRouter(prefix="/api/employees", tags=["employees"])


@router.get("/", response_model=List[EmployeeOut])
def list_all(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Employee).order_by(Employee.full_name).all()


@router.post("/", response_model=EmployeeOut)
def create(data: EmployeeCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = Employee(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=EmployeeOut)
def update(item_id: int, data: EmployeeCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = db.query(Employee).filter(Employee.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    for k, v in data.model_dump().items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}")
def delete(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = db.query(Employee).filter(Employee.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(item)
    db.commit()
    return {"success": True}
