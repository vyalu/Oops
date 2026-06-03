from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import PaymentMethod, User
from app.schemas import PaymentMethodCreate, PaymentMethodOut
from app.auth import get_current_user, require_manager

router = APIRouter(prefix="/api/payment-methods", tags=["payment-methods"])


@router.get("/", response_model=List[PaymentMethodOut])
def list_all(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(PaymentMethod).order_by(PaymentMethod.name).all()


@router.post("/", response_model=PaymentMethodOut)
def create(data: PaymentMethodCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = PaymentMethod(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=PaymentMethodOut)
def update(item_id: int, data: PaymentMethodCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = db.query(PaymentMethod).filter(PaymentMethod.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    for k, v in data.model_dump().items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}")
def delete(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = db.query(PaymentMethod).filter(PaymentMethod.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(item)
    db.commit()
    return {"success": True}
