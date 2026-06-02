from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Organization, User
from app.schemas import OrganizationCreate, OrganizationOut
from app.auth import get_current_user, require_manager

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


@router.get("/", response_model=List[OrganizationOut])
def list_all(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Organization).order_by(Organization.name).all()


@router.post("/", response_model=OrganizationOut)
def create(data: OrganizationCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = Organization(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=OrganizationOut)
def update(item_id: int, data: OrganizationCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = db.query(Organization).filter(Organization.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    for k, v in data.model_dump().items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}")
def delete(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = db.query(Organization).filter(Organization.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(item)
    db.commit()
    return {"success": True}
