from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String
from datetime import date, datetime
import os
import tarfile
import shutil
import subprocess
import tempfile
import asyncio
import json
import sqlite3
import zipfile

from app.database import get_db, engine
from app.models import (
    Base, User, Organization, Contractor, Employee, Category,
    PaymentMethod, Subscription, WebhookConfig
)


# === Маппинг названия → встроенная SVG-иконка ===
# Используется при импорте Wallos и в эндпоинте apply-builtin-icons
CATEGORY_ICON_MAP = {
    'интернет': '/static/icons/builtin/cat-internet.svg',
    'хостинг': '/static/icons/builtin/cat-hosting.svg',
    'облак': '/static/icons/builtin/cat-cloud.svg',
    'софт': '/static/icons/builtin/cat-software.svg',
    'по ': '/static/icons/builtin/cat-software.svg',
    'программ': '/static/icons/builtin/cat-software.svg',
    'связь': '/static/icons/builtin/cat-phone.svg',
    'телеф': '/static/icons/builtin/cat-phone.svg',
    'смс': '/static/icons/builtin/cat-sms.svg',
    'sms': '/static/icons/builtin/cat-sms.svg',
    'vpn': '/static/icons/builtin/cat-vpn.svg',
    'безопасн': '/static/icons/builtin/cat-security.svg',
    'видео': '/static/icons/builtin/cat-video.svg',
    'музык': '/static/icons/builtin/cat-music.svg',
    'реклам': '/static/icons/builtin/cat-ads.svg',
    'дизайн': '/static/icons/builtin/cat-design.svg',
    'аналит': '/static/icons/builtin/cat-analytics.svg',
    'статист': '/static/icons/builtin/cat-analytics.svg',
    'домен': '/static/icons/builtin/cat-domain.svg',
    'почт': '/static/icons/builtin/cat-email.svg',
    'email': '/static/icons/builtin/cat-email.svg',
    'ai': '/static/icons/builtin/cat-ai.svg',
    'нейро': '/static/icons/builtin/cat-ai.svg',
    'офис': '/static/icons/builtin/cat-office.svg',
}

PAYMENT_ICON_MAP = {
    'visa': '/static/icons/builtin/visa.svg',
    'mastercard': '/static/icons/builtin/mastercard.svg',
    'master card': '/static/icons/builtin/mastercard.svg',
    'мастеркард': '/static/icons/builtin/mastercard.svg',
    'мир': '/static/icons/builtin/mir.svg',
    'сбп': '/static/icons/builtin/sbp.svg',
    'apple pay': '/static/icons/builtin/apple-pay.svg',
    'applepay': '/static/icons/builtin/apple-pay.svg',
    'google pay': '/static/icons/builtin/google-pay.svg',
    'googlepay': '/static/icons/builtin/google-pay.svg',
    'google play': '/static/icons/builtin/google-play.svg',
    'app store': '/static/icons/builtin/app-store.svg',
    'appstore': '/static/icons/builtin/app-store.svg',
    'наличн': '/static/icons/builtin/cash.svg',
    'cash': '/static/icons/builtin/cash.svg',
    'банковск': '/static/icons/builtin/bank-transfer.svg',
    'перевод': '/static/icons/builtin/bank-transfer.svg',
    'расч': '/static/icons/builtin/invoice.svg',
    'счёт': '/static/icons/builtin/invoice.svg',
    'счет': '/static/icons/builtin/invoice.svg',
    'инвойс': '/static/icons/builtin/invoice.svg',
    'invoice': '/static/icons/builtin/invoice.svg',
    'карт': '/static/icons/builtin/card.svg',
    'card': '/static/icons/builtin/card.svg',
    'bitcoin': '/static/icons/builtin/bitcoin.svg',
    'btc': '/static/icons/builtin/bitcoin.svg',
    'крипт': '/static/icons/builtin/bitcoin.svg',
}


def match_icon_by_name(name: str, icon_map: dict) -> str | None:
    """Возвращает путь к иконке если в названии нашлось ключевое слово, иначе None."""
    n = (name or '').lower()
    for key, icon in icon_map.items():
        if key in n:
            return icon
    return None
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/system", tags=["system"])

# Простая таблица настроек
class AppSetting(Base):
    __tablename__ = "app_settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(String(500), default="")

Base.metadata.create_all(bind=engine)

DATA_DIR = os.getenv("OOPS_DATA_DIR", "/app/data")
DB_PATH = os.path.join(DATA_DIR, "oops.db")
LOGOS_DIR = os.path.join(DATA_DIR, "logos")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")


EXPORT_MODELS = {
    "organizations": Organization,
    "contractors": Contractor,
    "employees": Employee,
    "categories": Category,
    "payment_methods": PaymentMethod,
    "subscriptions": Subscription,
    "webhooks": WebhookConfig,
    "settings": AppSetting,
}

IMPORT_ORDER = [
    "organizations",
    "contractors",
    "employees",
    "categories",
    "payment_methods",
    "webhooks",
    "settings",
    "subscriptions",
]

REPLACE_ORDER = [
    "subscriptions",
    "webhooks",
    "settings",
    "payment_methods",
    "categories",
    "employees",
    "contractors",
    "organizations",
]


def _serialize_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _serialize_row(obj):
    return {
        column.name: _serialize_value(getattr(obj, column.name))
        for column in obj.__table__.columns
    }


def _coerce_value(column, value):
    if value in ("", None):
        return value
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return value
    if python_type is date:
        return date.fromisoformat(value)
    if python_type is datetime:
        return datetime.fromisoformat(value)
    return value


def _clean_row(model, row):
    columns = {column.name: column for column in model.__table__.columns}
    clean = {}
    for key, value in row.items():
        if key not in columns:
            continue
        try:
            clean[key] = _coerce_value(columns[key], value)
        except (TypeError, ValueError):
            clean[key] = value
    return clean


def _build_export_payload(db: Session):
    payload = {
        "app": "oops",
        "version": 2,
        "exported_at": datetime.utcnow().isoformat(),
        "data": {},
    }
    for name, model in EXPORT_MODELS.items():
        payload["data"][name] = [
            _serialize_row(row)
            for row in db.query(model).order_by(model.id).all()
        ]
    return payload


def _replace_from_payload(db: Session, payload: dict):
    if payload.get("app") != "oops" or not isinstance(payload.get("data"), dict):
        raise HTTPException(status_code=400, detail="Неверный формат экспорта")

    data = payload["data"]
    summary = {}
    for name in REPLACE_ORDER:
        model = EXPORT_MODELS[name]
        for row in db.query(model).all():
            db.delete(row)
    db.flush()

    for name in IMPORT_ORDER:
        model = EXPORT_MODELS[name]
        rows = data.get(name, [])
        if not isinstance(rows, list):
            raise HTTPException(status_code=400, detail=f"Раздел {name} должен быть списком")
        for row in rows:
            if isinstance(row, dict):
                db.add(model(**_clean_row(model, row)))
        summary[name] = len(rows)
    return summary


def _copy_zip_folder(zf: zipfile.ZipFile, prefix: str, target_dir: str):
    os.makedirs(target_dir, exist_ok=True)
    copied = 0
    prefix = prefix.rstrip("/") + "/"
    for info in zf.infolist():
        if info.is_dir() or not info.filename.startswith(prefix):
            continue
        rel = info.filename[len(prefix):]
        if not rel or rel.startswith("../") or ".." in rel.split("/"):
            continue
        dst = os.path.abspath(os.path.join(target_dir, rel))
        if not dst.startswith(os.path.abspath(target_dir)):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with zf.open(info) as src, open(dst, "wb") as out:
            shutil.copyfileobj(src, out)
        copied += 1
    return copied


def _as_bool(value):
    return bool(int(value or 0)) if str(value).isdigit() else bool(value)


def _wallos_cycle(days):
    try:
        days = int(days or 30)
    except (TypeError, ValueError):
        days = 30
    if days <= 1:
        return "daily"
    if days <= 7:
        return "weekly"
    if days >= 365:
        return "yearly"
    return "monthly"


def _wallos_frequency(value):
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def _import_wallos_backup(db: Session, wallos_db_path: str, zf: zipfile.ZipFile):
    con = sqlite3.connect(wallos_db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    def rows(table):
        try:
            return [dict(row) for row in cur.execute(f"SELECT * FROM {table}")]
        except sqlite3.Error:
            return []

    categories = rows("categories")
    organizations = rows("organizations")
    payment_methods = rows("payment_methods")
    subscriptions = rows("subscriptions")
    webhooks = rows("webhook_notifications")
    currencies = {row["id"]: row.get("code", "RUB") for row in rows("currencies")}
    cycles = {row["id"]: row.get("days", 30) for row in rows("cycles")}
    frequencies = {row["id"]: row.get("name", 1) for row in rows("frequencies")}

    for name in REPLACE_ORDER:
        model = EXPORT_MODELS[name]
        for row in db.query(model).all():
            db.delete(row)
    db.flush()

    for row in organizations:
        db.add(Organization(id=row.get("id"), name=row.get("name") or "", notes=""))
    for row in categories:
        cat_name = row.get("name") or ""
        cat_icon = match_icon_by_name(cat_name, CATEGORY_ICON_MAP) or "/static/icons/builtin/cat-other.svg"
        db.add(Category(id=row.get("id"), name=cat_name, color="#5ED0BD", icon=cat_icon))
    for row in payment_methods:
        pay_name = row.get("name") or ""
        pay_icon = match_icon_by_name(pay_name, PAYMENT_ICON_MAP) or "/static/icons/builtin/card.svg"
        db.add(PaymentMethod(
            id=row.get("id"),
            name=pay_name,
            details="",
            icon=pay_icon,
        ))

    logo_count = _copy_zip_folder(zf, "logos", LOGOS_DIR)

    for row in webhooks:
        if row.get("url"):
            db.add(WebhookConfig(
                name="Wallos webhook",
                url=row.get("url") or "",
                method=row.get("request_method") or "POST",
                headers=row.get("headers") or "{}",
                payload_template=row.get("payload") or "{}",
                enabled=_as_bool(row.get("enabled")),
                ignore_ssl=_as_bool(row.get("ignore_ssl")),
            ))

    for row in subscriptions:
        logo = row.get("logo") or ""
        logo_url = f"/data/logos/{os.path.basename(logo)}" if logo else ""
        db.add(Subscription(
            id=row.get("id"),
            name=row.get("name") or "",
            sub_type=row.get("subscription_type") or "recurring",
            price=float(row.get("price") or 0),
            currency=currencies.get(row.get("currency_id"), "RUB"),
            cycle=_wallos_cycle(cycles.get(row.get("cycle"))),
            frequency=_wallos_frequency(frequencies.get(row.get("frequency"), row.get("frequency"))),
            next_payment=date.fromisoformat(row["next_payment"]) if row.get("next_payment") else None,
            start_date=date.fromisoformat(str(row["start_date"])) if row.get("start_date") and "-" in str(row.get("start_date")) else None,
            auto_renew=_as_bool(row.get("auto_renew")),
            organization_id=row.get("organization_id"),
            category_id=row.get("category_id"),
            payment_method_id=row.get("payment_method_id"),
            balance=float(row.get("balance") or 0),
            last_balance_update=date.fromisoformat(row["last_balance_update"]) if row.get("last_balance_update") else None,
            billing_day=int(row.get("billing_day") or 1),
            min_balance=float(row.get("min_balance") or 0),
            balance_api_url=row.get("balance_api_url") or "",
            balance_api_path=row.get("balance_api_path") or "balance",
            url=row.get("url") or "",
            notes=row.get("notes") or "",
            logo=logo_url,
            is_active=not _as_bool(row.get("inactive")),
            notify_enabled=_as_bool(row.get("notify")) if row.get("notify") is not None else True,
            notify_days_before=str(row.get("notify_days_before") or "3").split(",")[0].strip() or "3",
            cancellation_date=date.fromisoformat(str(row["cancellation_date"])) if row.get("cancellation_date") and "-" in str(row.get("cancellation_date", "")) else None,
        ))

    con.close()
    return {
        "format": "wallos",
        "subscriptions": len(subscriptions),
        "categories": len(categories),
        "organizations": len(organizations),
        "payment_methods": len(payment_methods),
        "webhooks": len([w for w in webhooks if w.get("url")]),
        "logos": logo_count,
    }


@router.get("/notify-policy")
def get_notify_policy(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Глобальная настройка: сколько дней подряд (до платежа) напоминать."""
    s = db.query(AppSetting).filter(AppSetting.key == "notify_days").first()
    try:
        days = int(s.value) if s else 7
    except (ValueError, TypeError):
        days = 7
    return {"notify_days": days}


@router.post("/notify-policy")
def set_notify_policy(data: dict, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    days = data.get("notify_days", 7)
    if days not in (1, 3, 7, 14):
        raise HTTPException(status_code=400, detail="Допустимо: 1, 3, 7 или 14 дней")
    s = db.query(AppSetting).filter(AppSetting.key == "notify_days").first()
    if s:
        s.value = str(days)
    else:
        s = AppSetting(key="notify_days", value=str(days))
        db.add(s)
    db.commit()
    return {"notify_days": days}


@router.get("/theme")
def get_theme(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # Тема на каждого пользователя
    key = f"theme_{user.id}"
    s = db.query(AppSetting).filter(AppSetting.key == key).first()
    return {"theme": s.value if s else "dark"}


@router.post("/theme")
def set_theme(data: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    theme = data.get("theme", "dark")
    if theme not in ("dark", "light"):
        raise HTTPException(status_code=400, detail="Theme must be 'dark' or 'light'")
    key = f"theme_{user.id}"
    s = db.query(AppSetting).filter(AppSetting.key == key).first()
    if s:
        s.value = theme
    else:
        s = AppSetting(key=key, value=theme)
        db.add(s)
    db.commit()
    return {"theme": theme}


@router.get("/export-data")
def export_data(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    payload = _build_export_payload(db)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()

    with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("backup-info.json", json.dumps({
            "app": "oops",
            "version": 2,
            "created_at": payload["exported_at"],
            "contains": ["oops.db", "oops-data.json", "logos", "uploads"],
        }, ensure_ascii=False, indent=2))
        zf.writestr("oops-data.json", json.dumps(payload, ensure_ascii=False, indent=2))
        if os.path.exists(DB_PATH):
            zf.write(DB_PATH, "oops.db")
        for folder_name, folder_path in (("logos", LOGOS_DIR), ("uploads", UPLOADS_DIR)):
            if not os.path.isdir(folder_path):
                continue
            for root, _, files in os.walk(folder_path):
                for filename in files:
                    full_path = os.path.join(root, filename)
                    rel = os.path.relpath(full_path, folder_path).replace(os.sep, "/")
                    zf.write(full_path, f"{folder_name}/{rel}")

    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename=f"Oops-Backup-{stamp}.zip"
    )


@router.post("/import-data")
async def import_data(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Файл слишком большой")

    if file.filename and file.filename.lower().endswith(".zip"):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                with zipfile.ZipFile(tmp_path) as zf:
                    names = set(zf.namelist())
                    if "oops-data.json" in names:
                        payload = json.loads(zf.read("oops-data.json").decode("utf-8"))
                        summary = _replace_from_payload(db, payload)
                        summary["logos"] = _copy_zip_folder(zf, "logos", LOGOS_DIR)
                        summary["uploads"] = _copy_zip_folder(zf, "uploads", UPLOADS_DIR)
                    elif "wallos.db" in names:
                        wallos_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
                        wallos_tmp.write(zf.read("wallos.db"))
                        wallos_tmp.close()
                        try:
                            summary = _import_wallos_backup(db, wallos_tmp.name, zf)
                        finally:
                            os.unlink(wallos_tmp.name)
                    else:
                        raise HTTPException(status_code=400, detail="В ZIP не найден oops-data.json или wallos.db")
            finally:
                os.unlink(tmp_path)
            db.commit()
            return {"success": True, "summary": summary}
        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Ошибка импорта: {e}")

    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Файл должен быть JSON-экспортом Oops")

    if payload.get("app") != "oops" or not isinstance(payload.get("data"), dict):
        raise HTTPException(status_code=400, detail="Неверный формат экспорта")

    data = payload["data"]
    summary = {}
    try:
        for name in REPLACE_ORDER:
            model = EXPORT_MODELS[name]
            for row in db.query(model).all():
                db.delete(row)
        db.flush()

        for name in IMPORT_ORDER:
            model = EXPORT_MODELS[name]
            rows = data.get(name, [])
            if not isinstance(rows, list):
                raise HTTPException(status_code=400, detail=f"Раздел {name} должен быть списком")
            for row in rows:
                if isinstance(row, dict):
                    db.add(model(**_clean_row(model, row)))
            summary[name] = len(rows)

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка импорта: {e}")

    return {"success": True, "summary": summary}


@router.post("/upload-update")
async def upload_update(
    file: UploadFile = File(...),
    _: User = Depends(require_admin)
):
    """Загрузить новый архив с обновлением приложения.

    Архив должен иметь структуру oops/ с папкой app/ внутри.
    Проверка валидности — по содержимому (magic bytes gzip), а не по имени файла.
    После распаковки приложение перезапустится автоматически.
    """
    log = []
    try:
        # Прочитать всё содержимое
        content = await file.read()

        # Проверка magic bytes для gzip (1f 8b)
        if len(content) < 2 or content[0] != 0x1f or content[1] != 0x8b:
            raise HTTPException(status_code=400, detail="Файл не является gzip-архивом (.tar.gz)")

        # Сохранить во временный файл
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar.gz') as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        log.append(f"✓ Архив загружен: {file.filename} ({len(content)} байт)")

        # Извлечь во временную папку
        extract_dir = tempfile.mkdtemp(prefix="oops_update_")
        try:
            with tarfile.open(tmp_path, 'r:gz') as tar:
                tar.extractall(extract_dir)
        except tarfile.TarError as e:
            raise HTTPException(status_code=400, detail=f"Не удалось распаковать tar.gz: {e}")
        log.append(f"✓ Архив распакован")

        # Найти папку app/ внутри
        # Возможные варианты: extract_dir/oops/app, extract_dir/app
        app_source = None
        for root, dirs, files in os.walk(extract_dir):
            if 'app' in dirs and os.path.exists(os.path.join(root, 'app', 'main.py')):
                app_source = os.path.join(root, 'app')
                break

        if not app_source:
            log.append(f"✗ В архиве не найдена папка app/ с main.py")
            raise HTTPException(status_code=400, detail="\n".join(log))

        log.append(f"✓ Найдена папка app/ в архиве")

        # Сделать бэкап текущей app/
        backup_dir = "/app/data/app_backup"
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)
        shutil.copytree("/app/app", backup_dir)
        log.append(f"✓ Создан бэкап текущей версии в /app/data/app_backup")

        # Бэкап базы данных перед обновлением (с отметкой времени)
        try:
            if os.path.exists(DB_PATH):
                pre_update_dir = os.path.join(DATA_DIR, "backups")
                os.makedirs(pre_update_dir, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                db_backup_path = os.path.join(pre_update_dir, f"pre-update-{ts}.db")
                # safe-copy: через резервное соединение SQLite, чтобы не словить частичную запись
                try:
                    src = sqlite3.connect(DB_PATH)
                    dst = sqlite3.connect(db_backup_path)
                    with dst:
                        src.backup(dst)
                    src.close()
                    dst.close()
                except Exception:
                    # фолбэк: обычное копирование файла
                    shutil.copy2(DB_PATH, db_backup_path)
                log.append(f"✓ Бэкап базы данных: backups/pre-update-{ts}.db")
                # оставляем только ПОСЛЕДНИЙ pre-update бэкап (предыдущие удаляем)
                pre_backups = sorted(
                    [f for f in os.listdir(pre_update_dir) if f.startswith("pre-update-") and f.endswith(".db")]
                )
                for old in pre_backups[:-1]:
                    try:
                        os.remove(os.path.join(pre_update_dir, old))
                    except OSError:
                        pass
        except Exception as e:
            log.append(f"⚠ Не удалось сделать бэкап БД: {e}")

        # Заменить app/ файлами из архива (кроме __pycache__)
        target_dir = "/app/app"
        # Удалить старые .py и static файлы, оставив структуру
        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for f in files:
                if f.endswith(('.py', '.html', '.js', '.css')):
                    os.remove(os.path.join(root, f))

        # Скопировать новые
        for root, dirs, files in os.walk(app_source):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            rel = os.path.relpath(root, app_source)
            dst_root = os.path.join(target_dir, rel) if rel != '.' else target_dir
            os.makedirs(dst_root, exist_ok=True)
            for f in files:
                shutil.copy2(os.path.join(root, f), os.path.join(dst_root, f))

        log.append(f"✓ Файлы приложения обновлены")

        # Очистить временные файлы
        shutil.rmtree(extract_dir, ignore_errors=True)
        os.unlink(tmp_path)

        log.append("")
        log.append("⚠️  Перезапуск приложения через 2 секунды...")
        log.append("После перезапуска обновите страницу (Ctrl+F5)")

        # Перезапустить через 2 секунды (в фоне)
        async def restart_later():
            await asyncio.sleep(2)
            os._exit(0)  # Контейнер перезапустится сам (restart: unless-stopped)
        asyncio.create_task(restart_later())

        return {"success": True, "log": "\n".join(log)}

    except HTTPException:
        raise
    except Exception as e:
        log.append(f"✗ Ошибка: {e}")
        raise HTTPException(status_code=500, detail="\n".join(log))


@router.get("/info")
def system_info(_: User = Depends(require_admin)):
    from app.version import VERSION, BUILD
    return {
        "app_version": VERSION,
        "build": BUILD,
        "python_version": os.popen("python --version").read().strip(),
    }


@router.get("/backups")
def list_backups(_: User = Depends(require_admin)):
    """Список снапшотов БД (.db) из data/backups — авто-бэкапы и pre-update."""
    backup_dir = os.path.join(DATA_DIR, "backups")
    items = []
    if os.path.isdir(backup_dir):
        for f in os.listdir(backup_dir):
            if f.endswith(".db"):
                full = os.path.join(backup_dir, f)
                try:
                    st = os.stat(full)
                    items.append({
                        "name": f,
                        "size": st.st_size,
                        "created": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                        "kind": "pre-update" if f.startswith("pre-update-") else "auto",
                    })
                except OSError:
                    pass
    items.sort(key=lambda x: x["created"], reverse=True)
    return {"backups": items}


@router.post("/backups/restore")
async def restore_backup(data: dict, _: User = Depends(require_admin)):
    """Восстановить БД из выбранного снапшота .db. Перед заменой делает
    safety-копию текущей базы, затем перезапускает приложение."""
    name = (data or {}).get("name", "")
    # защита от path traversal — только имя файла, только .db
    if not name or "/" in name or "\\" in name or ".." in name or not name.endswith(".db"):
        raise HTTPException(status_code=400, detail="Некорректное имя бэкапа")

    backup_dir = os.path.join(DATA_DIR, "backups")
    src = os.path.join(backup_dir, name)
    if not os.path.isfile(src):
        raise HTTPException(status_code=404, detail="Бэкап не найден")

    # Проверим, что это валидная база SQLite
    try:
        test = sqlite3.connect(src)
        test.execute("PRAGMA schema_version;")
        test.close()
    except Exception:
        raise HTTPException(status_code=400, detail="Файл не является корректной базой SQLite")

    # Safety-копия текущей БД перед перезаписью
    log = []
    try:
        if os.path.exists(DB_PATH):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safety = os.path.join(backup_dir, f"before-restore-{ts}.db")
            try:
                s = sqlite3.connect(DB_PATH); d = sqlite3.connect(safety)
                with d:
                    s.backup(d)
                s.close(); d.close()
            except Exception:
                shutil.copy2(DB_PATH, safety)
            log.append(f"Текущая база сохранена как backups/before-restore-{ts}.db")

        # Заменить рабочую БД выбранным снапшотом
        shutil.copy2(src, DB_PATH)
        log.append(f"База восстановлена из {name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка восстановления: {e}")

    log.append("Перезапуск приложения...")

    async def restart_later():
        await asyncio.sleep(2)
        os._exit(0)
    asyncio.create_task(restart_later())

    return {"success": True, "log": "\n".join(log)}


