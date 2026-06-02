from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
from urllib.parse import urlparse
import os
import uuid

from app.database import get_db
from app.models import Contractor, User
from app.schemas import ContractorCreate, ContractorOut
from app.auth import get_current_user, require_manager

router = APIRouter(prefix="/api/contractors", tags=["contractors"])

LOGOS_DIR = "/app/data/logos"
os.makedirs(LOGOS_DIR, exist_ok=True)

ALLOWED_LOGO_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".ico", ".gif"}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2MB


@router.get("/", response_model=List[ContractorOut])
def list_all(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Contractor).order_by(Contractor.name).all()


@router.post("/", response_model=ContractorOut)
def create(data: ContractorCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = Contractor(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=ContractorOut)
def update(item_id: int, data: ContractorCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = db.query(Contractor).filter(Contractor.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    for k, v in data.model_dump().items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}")
def delete(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = db.query(Contractor).filter(Contractor.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    if item.logo_url and item.logo_url.startswith("/data/logos/"):
        fname = item.logo_url.split("/")[-1]
        fpath = os.path.join(LOGOS_DIR, fname)
        try:
            if os.path.exists(fpath):
                os.remove(fpath)
        except Exception:
            pass
    db.delete(item)
    db.commit()
    return {"success": True}


@router.post("/{item_id}/upload-logo")
async def upload_logo(
    item_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_manager)
):
    item = db.query(Contractor).filter(Contractor.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_LOGO_EXTS:
        raise HTTPException(status_code=400, detail=f"Допустимые форматы: {', '.join(sorted(ALLOWED_LOGO_EXTS))}")

    content = await file.read()
    if len(content) > MAX_LOGO_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой (максимум 2 МБ)")

    if item.logo_url and item.logo_url.startswith("/data/logos/"):
        old_fname = item.logo_url.split("/")[-1]
        old_fpath = os.path.join(LOGOS_DIR, old_fname)
        if os.path.exists(old_fpath):
            try:
                os.remove(old_fpath)
            except Exception:
                pass

    fname = f"{uuid.uuid4().hex}{ext}"
    fpath = os.path.join(LOGOS_DIR, fname)
    with open(fpath, "wb") as f:
        f.write(content)

    item.logo_url = f"/data/logos/{fname}"
    db.commit()
    db.refresh(item)
    return {"logo_url": item.logo_url}


@router.post("/{item_id}/fetch-favicon")
def fetch_favicon(
    item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager)
):
    item = db.query(Contractor).filter(Contractor.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Контрагент не найден")
    if not item.website:
        raise HTTPException(status_code=400, detail="У контрагента не задан сайт")

    site = item.website
    if not site.startswith(("http://", "https://")):
        site = "https://" + site
    parsed = urlparse(site)
    domain = parsed.netloc or parsed.path.split("/")[0]
    domain = domain.replace("www.", "")
    if not domain:
        raise HTTPException(status_code=400, detail="Не удалось извлечь домен из сайта")

    item.logo_url = f"https://icons.duckduckgo.com/ip3/{domain}.ico"
    db.commit()
    db.refresh(item)
    return {"logo_url": item.logo_url}


@router.delete("/{item_id}/logo")
def delete_logo(
    item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager)
):
    item = db.query(Contractor).filter(Contractor.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    if item.logo_url and item.logo_url.startswith("/data/logos/"):
        fname = item.logo_url.split("/")[-1]
        fpath = os.path.join(LOGOS_DIR, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass
    item.logo_url = ""
    db.commit()
    return {"success": True}
