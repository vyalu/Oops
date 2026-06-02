from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import List
import os
import uuid

from app.models import User
from app.auth import require_manager, get_current_user

router = APIRouter(prefix="/api/icons", tags=["icons"])

ICONS_DIR = "/app/data/icons"
os.makedirs(ICONS_DIR, exist_ok=True)

ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".ico"}
MAX_SIZE = 1 * 1024 * 1024  # 1 МБ — иконки маленькие


@router.get("/")
def list_icons(_: User = Depends(get_current_user)) -> List[dict]:
    """Список всех загруженных пользовательских иконок."""
    if not os.path.exists(ICONS_DIR):
        return []
    items = []
    for fname in sorted(os.listdir(ICONS_DIR)):
        fpath = os.path.join(ICONS_DIR, fname)
        if os.path.isfile(fpath):
            ext = os.path.splitext(fname)[1].lower()
            if ext in ALLOWED_EXTS:
                items.append({
                    "url": f"/data/icons/{fname}",
                    "name": fname,
                })
    return items


@router.post("/upload")
async def upload_icon(
    file: UploadFile = File(...),
    _: User = Depends(require_manager),
):
    """Загружает картинку-иконку в общую библиотеку."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Допустимые форматы: {', '.join(sorted(ALLOWED_EXTS))}")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой (максимум 1 МБ)")

    # Сохраняем под исходным именем (если занято — добавим uuid)
    base = os.path.splitext(file.filename or "icon")[0]
    # очистим имя от опасных символов
    base = "".join(c for c in base if c.isalnum() or c in ("-", "_", ".")).strip() or "icon"
    fname = f"{base}{ext}"
    fpath = os.path.join(ICONS_DIR, fname)
    if os.path.exists(fpath):
        fname = f"{base}_{uuid.uuid4().hex[:6]}{ext}"
        fpath = os.path.join(ICONS_DIR, fname)

    with open(fpath, "wb") as f:
        f.write(content)

    return {"url": f"/data/icons/{fname}", "name": fname}


@router.delete("/{name}")
def delete_icon(name: str, _: User = Depends(require_manager)):
    """Удаляет загруженную иконку."""
    # защита от path traversal
    safe = os.path.basename(name)
    fpath = os.path.join(ICONS_DIR, safe)
    if os.path.exists(fpath):
        try:
            os.remove(fpath)
        except Exception:
            raise HTTPException(status_code=500, detail="Не удалось удалить")
    return {"success": True}
