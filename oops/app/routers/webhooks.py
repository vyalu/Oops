from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import httpx
import json

from app.database import get_db
from app.models import WebhookConfig, User, Subscription, NotificationLog
from app.schemas import WebhookCreate, WebhookOut
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.get("/", response_model=List[WebhookOut])
def list_all(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(WebhookConfig).all()


@router.get("/logs")
def logs(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Последние записи журнала уведомлений с именем подписки."""
    rows = db.query(NotificationLog).order_by(NotificationLog.sent_at.desc()).limit(limit).all()
    result = []
    for r in rows:
        sub = db.query(Subscription).filter(Subscription.id == r.subscription_id).first()
        result.append({
            "id": r.id,
            "subscription_name": sub.name if sub else f"#{r.subscription_id}",
            "event_type": r.event_type,
            "message": r.message,
            "success": r.success,
            "created_at": r.sent_at.isoformat() if r.sent_at else None,
        })
    return result


@router.post("/", response_model=WebhookOut)
def create(data: WebhookCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    item = WebhookConfig(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}", response_model=WebhookOut)
def update(item_id: int, data: WebhookCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    item = db.query(WebhookConfig).filter(WebhookConfig.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    for k, v in data.model_dump().items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}")
def delete(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    item = db.query(WebhookConfig).filter(WebhookConfig.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(item)
    db.commit()
    return {"success": True}


@router.post("/test-config")
def test_config(data: WebhookCreate, _: User = Depends(require_admin)):
    """Тест канала без сохранения — для проверки настроек на лету."""
    # Создаём временный объект (не сохраняем в БД)
    wh = WebhookConfig(**data.model_dump())
    fake_data = {
        "subscription_name": "Test (без сохранения)",
        "subscription_price": "0",
        "subscription_currency": "RUB",
        "subscription_category": "Test",
        "subscription_date": "2026-01-01",
        "subscription_organization": "Test Org",
        "subscription_url": "https://example.com",
        "subscription_notes": "Проверка канала Oops!",
        "message": "Проверка канала Oops!",
        "event_type": "test",
    }
    return _send_webhook(wh, fake_data)


@router.post("/{item_id}/test")
def test(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    wh = db.query(WebhookConfig).filter(WebhookConfig.id == item_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Не найдено")

    fake_data = {
        "subscription_name": "Test Subscription",
        "subscription_price": "1000",
        "subscription_currency": "RUB",
        "subscription_category": "Test",
        "subscription_date": "2026-01-01",
        "subscription_organization": "Test Org",
        "subscription_url": "https://example.com",
        "subscription_notes": "This is a test notification from Oops!",
    }
    return _send_webhook(wh, fake_data)


@router.post("/{item_id}/send-upcoming")
def send_upcoming(item_id: int, days: int = 7, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Отправляет уведомления только по подпискам с платежами в ближайшие N дней (по умолчанию 7).
    Учитывается: onetime — по next_payment, recurring — по billing_day."""
    from datetime import date as _date

    wh = db.query(WebhookConfig).filter(WebhookConfig.id == item_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Не найдено")

    today = _date.today()
    kind = (wh.kind or "webhook").lower()

    def next_payment_for(s: Subscription):
        if s.sub_type == "onetime":
            return s.next_payment
        if s.sub_type in ("recurring", "balance") and s.billing_day:
            day = min(s.billing_day, 28)
            if today.day <= day:
                try:
                    return today.replace(day=day)
                except ValueError:
                    return None
            if today.month == 12:
                return today.replace(year=today.year + 1, month=1, day=day)
            return today.replace(month=today.month + 1, day=day)
        return None

    subs = db.query(Subscription).filter(Subscription.is_active == True).order_by(Subscription.name).all()
    upcoming = []
    for s in subs:
        np = next_payment_for(s)
        if not np:
            continue
        diff = (np - today).days
        if 0 <= diff <= days:
            upcoming.append((s, np, diff))

    sent, errors = 0, 0
    failed = []
    for s, np, diff in upcoming:
        if diff == 0:
            when = "сегодня"
        elif diff == 1:
            when = "завтра"
        else:
            when = f"через {diff} дн."
        message = (
            f"Ближайший платёж: {s.name}\n"
            f"Стоимость: {s.price} {s.currency}\n"
            f"Дата: {np.isoformat()} ({when})"
        )
        data = {
            "subscription_name": s.name,
            "subscription_price": str(s.price),
            "subscription_currency": s.currency,
            "subscription_category": s.category.name if s.category else "",
            "subscription_date": np.isoformat(),
            "subscription_organization": s.organization.name if s.organization else "",
            "subscription_url": s.url or "",
            "subscription_notes": s.notes or "",
            "message": message,
            "event_type": "send_upcoming",
        }
        try:
            r = _send_webhook(wh, data)
            ok = bool(r.get("success"))
            if ok:
                sent += 1
            else:
                errors += 1
                failed.append({"id": s.id, "name": s.name, "error": r.get("error") or "Не удалось отправить"})
            db.add(NotificationLog(
                subscription_id=s.id,
                event_type="send_upcoming",
                message=f"[{kind}] {message}" + (f" — ОШИБКА: {r.get('error')}" if not ok and r.get('error') else ""),
                success=ok,
            ))
        except Exception as e:
            errors += 1
            failed.append({"id": s.id, "name": s.name, "error": str(e)})
            db.add(NotificationLog(
                subscription_id=s.id,
                event_type="send_upcoming",
                message=f"[{kind}] {message} — ОШИБКА: {e}",
                success=False,
            ))
    db.commit()

    return {
        "success": errors == 0,
        "days": days,
        "total": len(upcoming),
        "sent": sent,
        "errors": errors,
        "failed": failed,
    }


def _send_webhook(wh: WebhookConfig, data: dict):
    """Универсальная отправка через любой тип канала. Возвращает {success, ...}."""
    from app.scheduler import _send_via_webhook, _send_via_bitrix24, _send_via_email, _send_via_telegram
    kind = (wh.kind or "webhook").lower()
    message = data.get("message") or data.get("subscription_notes") or "Тестовое уведомление Oops"
    try:
        if kind == "bitrix24":
            ok = _send_via_bitrix24(wh, data, message)
        elif kind == "email":
            ok = _send_via_email(wh, data, message)
        elif kind == "telegram":
            ok = _send_via_telegram(wh, data, message)
        else:
            ok = _send_via_webhook(wh, data, message)
        return {"success": ok, "kind": kind}
    except Exception as e:
        return {"success": False, "kind": kind, "error": str(e)}
