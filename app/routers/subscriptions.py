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

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


@router.get("/", response_model=List[SubscriptionOut])
def list_all(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
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

    return q.order_by(Subscription.next_payment.asc().nullslast()).all()


@router.get("/{item_id}", response_model=SubscriptionOut)
def get_one(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    item = db.query(Subscription).options(
        joinedload(Subscription.organization),
        joinedload(Subscription.contractor),
        joinedload(Subscription.employee),
        joinedload(Subscription.category),
        joinedload(Subscription.payment_method),
    ).filter(Subscription.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    return item


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

    if item.sub_type == "onetime":
        item.paid_until = item.next_payment or today
    else:
        # recurring/balance — отмечаем оплаченным до даты ближайшего платежа,
        # рассчитанной с учётом периодичности (cycle/frequency)
        from calendar import monthrange

        def _add_period(d, cycle, freq):
            freq = max(1, int(freq or 1))
            if cycle == "daily":
                return d + timedelta(days=freq)
            if cycle == "weekly":
                return d + timedelta(weeks=freq)
            if cycle == "yearly":
                try:
                    return d.replace(year=d.year + freq)
                except ValueError:
                    return d.replace(year=d.year + freq, day=28)
            m = d.month - 1 + freq
            y = d.year + m // 12
            m = m % 12 + 1
            dd = min(d.day, monthrange(y, m)[1])
            return date(y, m, dd)

        cycle = item.cycle or "monthly"
        freq = item.frequency or 1
        anchor = item.next_payment or item.start_date
        if not anchor and item.billing_day:
            day = min(item.billing_day, 28)
            try:
                anchor = today.replace(day=day)
            except ValueError:
                anchor = today
        if anchor:
            d = anchor
            guard = 0
            while d < today and guard < 1000:
                d = _add_period(d, cycle, freq)
                guard += 1
            item.paid_until = d
        else:
            item.paid_until = today

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
        with httpx.Client(timeout=15, verify=False, follow_redirects=True) as client:
            r = client.get(item.balance_api_url)
            r.raise_for_status()
            raw_text = r.text
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
            s = val.strip()
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
    m = re.search(r'(?:balance|money|amount|sum)\s*[=:]\s*([0-9]+(?:[.,][0-9]+)?)', text_stripped, re.IGNORECASE)
    if m:
        return m.group(1).replace(",", ".")
    for line in text_stripped.splitlines():
        line = line.strip().replace(",", ".")
        if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', line):
            return line
    m = re.search(r'([0-9]+(?:[.,][0-9]+)?)', text_stripped)
    if m:
        return m.group(1).replace(",", ".")
    return None


@router.get("/stats/dashboard")
def stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    today = date.today()
    in_30_days = today + timedelta(days=30)

    subs = db.query(Subscription).filter(Subscription.is_active == True).all()

    total_monthly = 0.0
    total_yearly = 0.0
    for s in subs:
        if s.sub_type == "onetime":
            continue
        # Приведение к месячной стоимости
        if s.cycle == "monthly":
            month_cost = s.price / max(s.frequency, 1)
        elif s.cycle == "yearly":
            month_cost = s.price / (12 * max(s.frequency, 1))
        elif s.cycle == "weekly":
            month_cost = s.price * (4.345 / max(s.frequency, 1))
        elif s.cycle == "daily":
            month_cost = s.price * (30 / max(s.frequency, 1))
        else:
            month_cost = 0
        total_monthly += month_cost
    total_yearly = total_monthly * 12

    from calendar import monthrange

    def _add_period(d, cycle, freq):
        freq = max(1, int(freq or 1))
        if cycle == "daily":
            return d + timedelta(days=freq)
        if cycle == "weekly":
            return d + timedelta(weeks=freq)
        if cycle == "yearly":
            try:
                return d.replace(year=d.year + freq)
            except ValueError:
                return d.replace(year=d.year + freq, day=28)
        m = d.month - 1 + freq
        y = d.year + m // 12
        m = m % 12 + 1
        day = min(d.day, monthrange(y, m)[1])
        return date(y, m, day)

    def get_next_payment_date(s):
        """Дата следующего платежа с учётом периодичности."""
        if s.sub_type == "onetime":
            return s.next_payment
        if s.sub_type != "recurring":
            return s.next_payment
        cycle = s.cycle or "monthly"
        freq = s.frequency or 1
        # опорная дата
        anchor = s.next_payment or s.start_date
        if not anchor and s.billing_day:
            day = min(s.billing_day, 28)
            try:
                anchor = today.replace(day=day)
            except ValueError:
                anchor = None
        if not anchor:
            return None
        d = anchor
        guard = 0
        while d < today and guard < 1000:
            d = _add_period(d, cycle, freq)
            guard += 1
        return d

    upcoming = []
    overdue = []
    for s in subs:
        if s.sub_type in ("balance", "balance_daily"):
            continue
        next_pay = get_next_payment_date(s)
        if not next_pay:
            continue
        # уже оплачено до этой даты — не показываем
        if s.paid_until and s.paid_until >= next_pay:
            continue
        item = {
            "id": s.id,
            "name": s.name,
            "price": s.price,
            "currency": s.currency,
            "next_payment": next_pay.isoformat(),
            "organization": s.organization.name if s.organization else None,
            "logo_url": s.contractor.logo_url if s.contractor and s.contractor.logo_url else None,
        }
        if today <= next_pay <= in_30_days:
            upcoming.append(item)
        elif next_pay < today and not s.auto_renew and s.sub_type == "onetime":
            overdue.append(item)
    upcoming.sort(key=lambda x: x["next_payment"] or "")

    low_balance = []
    for s in subs:
        if s.sub_type != "balance":
            continue
        threshold = s.min_balance if s.min_balance > 0 else s.price
        if threshold > 0 and s.balance < threshold:
            low_balance.append({
                "id": s.id,
                "name": s.name,
                "balance": s.balance,
                "threshold": threshold,
                "organization": s.organization.name if s.organization else None,
                "logo_url": s.contractor.logo_url if s.contractor and s.contractor.logo_url else None,
            })

    # По организациям
    by_org = {}
    for s in subs:
        if s.sub_type == "onetime":
            continue
        org_name = s.organization.name if s.organization else "Без организации"
        if s.cycle == "monthly":
            month_cost = s.price / max(s.frequency, 1)
        elif s.cycle == "yearly":
            month_cost = s.price / (12 * max(s.frequency, 1))
        elif s.cycle == "weekly":
            month_cost = s.price * (4.345 / max(s.frequency, 1))
        elif s.cycle == "daily":
            month_cost = s.price * (30 / max(s.frequency, 1))
        else:
            month_cost = 0
        by_org[org_name] = by_org.get(org_name, 0) + month_cost

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
