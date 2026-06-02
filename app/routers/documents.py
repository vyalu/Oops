from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date as date_type
import os
import uuid

from app.database import get_db
from app.models import Document, Subscription, User
from app.schemas import DocumentOut
from app.auth import get_current_user, require_manager

router = APIRouter(prefix="/api/documents", tags=["documents"])

UPLOAD_DIR = "/app/data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.get("/by-subscription/{subscription_id}", response_model=List[DocumentOut])
def list_for_subscription(subscription_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Document).filter(Document.subscription_id == subscription_id).all()


@router.post("/", response_model=DocumentOut)
def upload(
    subscription_id: int = Form(...),
    doc_type: str = Form("invoice"),
    title: str = Form(...),
    doc_date: Optional[str] = Form(None),
    amount: float = Form(0),
    notes: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_manager)
):
    sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Подписка не найдена")

    safe_ext = os.path.splitext(file.filename)[1][:10]
    fname = f"{uuid.uuid4().hex}{safe_ext}"
    path = os.path.join(UPLOAD_DIR, fname)
    with open(path, "wb") as f:
        f.write(file.file.read())

    doc = Document(
        subscription_id=subscription_id,
        doc_type=doc_type,
        title=title,
        filename=fname,
        doc_date=date_type.fromisoformat(doc_date) if doc_date else None,
        amount=amount,
        notes=notes,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{doc_id}/download")
def download(doc_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Не найдено")
    path = os.path.join(UPLOAD_DIR, doc.filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(path, filename=doc.title + os.path.splitext(doc.filename)[1])


@router.delete("/{doc_id}")
def delete(doc_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Не найдено")
    path = os.path.join(UPLOAD_DIR, doc.filename)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    db.delete(doc)
    db.commit()
    return {"success": True}
