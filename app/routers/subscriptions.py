from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from typing import List, Optional
from datetime import date, timedelta
import httpx
import json

from app.database import get_db
from app.models import Subscription, User, WebhookConfig
from app.schemas import SubscriptionCreate, SubscriptionUpdate, SubscriptionOut
from app.auth import get_current_user, require_manager
from app import billing

MASK = "•••"


def _out(item, user):
    """Наблюдателю (viewer) не показываем URL API баланса — в нём логины/ключи."""
    out = SubscriptionOut.model_validate(item)
    if user.role not in ("admin", "manager") and out.balance_api_url:
        out.balance_api_url = MASK
    return out

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


@router.get("/", response_model=List[SubscriptionOut])
def list_all(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    organization_id: Optional[int] = None,
    contractor_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    category_id: Optional[int] = None,
    sub_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
):
    q = db.query(Subscription).options(
        joinedload(Subscription.organization),
        joinedload(Subscription.contractor),
        joinedload(Subscription.employee),
        joinedload(Subscription.category),
        joinedload(Subscription.payment_method),
    )
    if organization_id is not None:
        q = q.filter(Subscription.organization_id == organization_id)
    if contractor_id is not None:
        q = q.filter(Subscription.contractor_id == contractor_id)
    if employee_id is not None:
        q = q.filter(Subscription.employee_id == employee_id)
    if category_id is not None:
        q = q.filter(Subscription.category_id == category_id)
    if sub_type is not None:
        q = q.filter(Subscription.sub_type == sub_type)
    if is_active is not None:
        q = q.filter(Subscription.is_active == is_active)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Subscription.name.ilike(like), Subscription.notes.ilike(like)))

    return [_out(i, user) for i in q.order_by(Subscription.next_payment.asc().nullslast()).all()]


@router.get("/{item_id}", response_model=SubscriptionOut)
def get_one(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(Subscription).options(
        joinedload(Subscription.organization),
        joinedload(Subscription.contractor),
        joinedload(Subscription.employee),
        joinedload(Subscription.category),
        joinedload(Subscription.payment_method),
    ).filter(Subscription.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    return _out(item, user)


@router.post("/", response_model=SubscriptionOut)
def create(data: SubscriptionCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = Subscription(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}", response_model=SubscriptionOut)
def update(item_id: int, data: SubscriptionUpdate, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = db.query(Subscription).filter(Subscription.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    for k, v in data.model_dump().items():
        if k == "balance_api_url" and v == MASK:
            continue  # маска пришла обратно из формы — оставляем прежний URL
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}")
def delete(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = db.query(Subscription).filter(Subscription.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(item)
    db.commit()
    return {"success": True}


@router.post("/{item_id}/mark-paid")
def mark_paid(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    """Отметить текущий платёж как оплаченный («Продлено»).
    Для recurring сдвигает next_payment на следующий период и помечает,
    чтобы напоминание за уже оплаченный платёж не приходило."""
    item = db.query(Subscription).filter(Subscription.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")

    today = date.today()
    # Если есть неоплаченный просроченный платёж — закрываем его,
    # иначе — ближайший предстоящий (см. app/billing.py).
    item.paid_until = billing.mark_paid_until(item, today)

    # сбрасываем отметку об отправленном напоминании (платёж закрыт)
    item.last_payment_notify_for = None
    db.commit()
    db.refresh(item)
    return {"success": True, "paid_until": item.paid_until.isoformat() if item.paid_until else None}


@router.post("/{item_id}/fetch-balance")
def fetch_balance(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    item = db.query(Subscription).filter(Subscription.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    if not item.balance_api_url:
        raise HTTPException(status_code=400, detail="URL для проверки баланса не указан")

    try:
        raw_text = http_get_balance(item.balance_api_url)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Ошибка запроса: {e}")

    try:
        balance_value = _extract_balance(raw_text, item.balance_api_path or "balance")
    except _ApiError as e:
        raise HTTPException(status_code=400, detail=f"Сервис вернул ошибку: {e}")
    if balance_value is None:
        # дадим понять что именно вернул сервис (первые 200 символов)
        preview = (raw_text or "").strip()[:200]
        raise HTTPException(
            status_code=500,
            detail=f"Не удалось извлечь баланс. Ответ сервиса: {preview!r}"
        )

    try:
        item.balance = float(balance_value)
        item.last_balance_update = date.today()
        db.commit()
        db.refresh(item)
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail=f"Значение '{balance_value}' не является числом")

    return {"success": True, "balance": item.balance}


def http_get_balance(url: str) -> str:
    """GET к API баланса. Сначала с проверкой сертификата; если сервер с
    самоподписанным сертификатом — повторяем без проверки (как было раньше),
    чтобы не сломать уже настроенные счета."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            r = client.get(url)
    except httpx.ConnectError as e:
        if "CERTIFICATE" not in str(e).upper() and "SSL" not in str(e).upper():
            raise
        import logging
        logging.getLogger("oops").warning("Balance API: SSL certificate not trusted, retrying without verification")
        with httpx.Client(timeout=15, verify=False, follow_redirects=True) as client:
            r = client.get(url)
    r.raise_for_status()
    return r.text


class _ApiError(Exception):
    """Ответ API содержал ошибку (например, недостаточно прав)."""
    pass


def _extract_balance(raw_text: str, path: str):
    """Извлекает числовой баланс из ответа API.
    Поддерживает:
      - JSON по пути (точечная нотация, индексы массивов)
      - BILLmanager: значение во вложенном ключе "$" ({"balance": {"$": "109.30 EUR"}})
      - значение с валютой в строке ("109.30 EUR", "1 234,56 руб")
      - plain-число, формат SMS.ru ("OK\\n100.50"), "balance=100.50"
    """
    if not raw_text:
        return None
    text_stripped = raw_text.strip()

    def _num_from(val):
        """Достаёт число из значения, которое может быть числом, строкой с валютой,
        или dict с ключом '$' (формат BILLmanager)."""
        import re
        if val is None:
            return None
        # BILLmanager оборачивает значение в {"$": "..."}
        if isinstance(val, dict):
            if "$" in val:
                return _num_from(val["$"])
            return None
        if isinstance(val, (int, float)):
            return val
        if isinstance(val, str):
            s = val.strip().replace("\u2212", "-")
            # "109.30 EUR", "1 234,56 руб", "−50.00" → вытащим число
            # убираем пробелы-разделители тысяч
            s2 = s.replace("\u00a0", "").replace(" ", "")
            m = re.search(r'-?[0-9]+(?:[.,][0-9]+)?', s2)
            if m:
                return m.group(0).replace(",", ".")
        return None

    # 1) Пробуем JSON
    try:
        data = json.loads(text_stripped)

        # Если ответ — это ошибка API, не выдёргиваем случайные числа.
        # BILLmanager: {"doc":{"error":{...}}}; другие: {"error":...}
        err = None
        if isinstance(data, dict):
            if isinstance(data.get("error"), (str, dict)):
                err = data["error"]
            elif isinstance(data.get("doc"), dict) and data["doc"].get("error"):
                err = data["doc"]["error"]
        if err is not None:
            # вытащим текст ошибки для информативности
            err_msg = None
            if isinstance(err, dict):
                m = err.get("msg")
                if isinstance(m, dict):
                    err_msg = m.get("$")
                elif isinstance(m, str):
                    err_msg = m
                if not err_msg and isinstance(err.get("detail"), dict):
                    err_msg = err["detail"].get("$")
            elif isinstance(err, str):
                err_msg = err
            raise _ApiError(err_msg or "API вернул ошибку")

        value = data
        ok = True
        for key in path.split("."):
            if isinstance(value, dict) and key in value:
                value = value[key]
            elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
                value = value[int(key)]
            else:
                ok = False
                break
        if ok:
            num = _num_from(value)
            if num is not None:
                return num
        # путь не сработал — попробуем популярные ключи на верхнем уровне
        if isinstance(data, dict):
            for k in ("balance", "Balance", "money", "amount", "sum", "real_balance", "result"):
                if k in data:
                    num = _num_from(data[k])
                    if num is not None:
                        return num
    except (json.JSONDecodeError, ValueError):
        pass

    # 2) Текстовые форматы
    import re
    # Отрицательный баланс должен остаться отрицательным: учитываем «-» и «−» (U+2212)
    norm = text_stripped.replace("\u2212", "-")
    m = re.search(r'(?:balance|money|amount|sum)\s*[=:]\s*(-?[0-9]+(?:[.,][0-9]+)?)', norm, re.IGNORECASE)
    if m:
        return m.group(1).replace(",", ".")
    for line in norm.splitlines():
        line = line.strip().replace(",", ".")
        if re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?', line):
            return line
    # Последний шанс: короткий ответ ровно с одним числом («100.50 RUB»).
    # В длинных ответах (HTML-страница ошибки и т.п.) случайное число не берём.
    if len(norm) <= 50:
        nums = re.findall(r'-?[0-9]+(?:[.,][0-9]+)?', norm)
        if len(nums) == 1:
            return nums[0].replace(",", ".")
    return None


@router.get("/stats/dashboard")
def stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    today = date.today()
    in_30_days = today + timedelta(days=30)

    subs = db.query(Subscription).filter(Subscription.is_active == True).all()

    total_monthly = sum(billing.monthly_cost(s) for s in subs if s.sub_type != "onetime")
    total_yearly = total_monthly * 12

    def _card(s, pay_date):
        return {
            "id": s.id,
            "name": s.name,
            "price": s.price,
            "currency": s.currency,
            "next_payment": pay_date.isoformat(),
            "organization": s.organization.name if s.organization else None,
            "logo_url": s.contractor.logo_url if s.contractor and s.contractor.logo_url else None,
        }

    upcoming = []
    overdue = []
    for s in subs:
        if s.sub_type in ("balance", "balance_daily"):
            continue
        # Просрочка: ручная оплата, наступивший платёж не отмечен оплаченным
        od = billing.overdue_date(s, today)
        if od:
            item = _card(s, od)
            item["days_overdue"] = (today - od).days
            overdue.append(item)
        next_pay = billing.next_payment_for(s, today)
        if not next_pay or next_pay < today:
            continue
        if billing.is_paid(s, next_pay):
            continue
        if next_pay <= in_30_days:
            upcoming.append(_card(s, next_pay))
    upcoming.sort(key=lambda x: x["next_payment"] or "")
    overdue.sort(key=lambda x: x["next_payment"] or "")

    low_balance = []
    for s in subs:
        if s.sub_type not in ("balance", "balance_daily"):
            continue
        reasons, threshold = billing.low_balance_check(s, today)
        if reasons:
            low_balance.append({
                "id": s.id,
                "name": s.name,
                "balance": s.balance,
                "currency": s.currency,
                "threshold": round(threshold, 2),
                "reason": "; ".join(reasons),
                "organization": s.organization.name if s.organization else None,
                "logo_url": s.contractor.logo_url if s.contractor and s.contractor.logo_url else None,
            })

    # По организациям
    by_org = {}
    for s in subs:
        if s.sub_type == "onetime":
            continue
        org_name = s.organization.name if s.organization else "Без организации"
        by_org[org_name] = by_org.get(org_name, 0) + billing.monthly_cost(s)

    # Сумма к оплате в ближайшие 30 дней
    upcoming_30d_total = sum(x["price"] or 0 for x in upcoming)

    # История расходов по месяцам (для графика динамики)
    from ..models import MonthlySnapshot
    snapshots = db.query(MonthlySnapshot).order_by(MonthlySnapshot.period).all()
    history = [{"period": s.period, "total": round(s.total_monthly, 2)} for s in snapshots[-8:]]

    return {
        "total_active": len([s for s in subs if s.sub_type != "onetime"]),
        "total_monthly": round(total_monthly, 2),
        "total_yearly": round(total_yearly, 2),
        "upcoming_30d_total": round(upcoming_30d_total, 2),
        "upcoming_count": len(upcoming),
        "upcoming": upcoming[:10],
        "overdue": overdue,
        "low_balance": low_balance,
        "by_organization": [{"name": k, "monthly": round(v, 2)} for k, v in sorted(by_org.items(), key=lambda x: -x[1])],
        "history": history,
    }
