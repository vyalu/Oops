"""Единая логика дат платежей и проверки баланса.

Раньше расчёт был скопирован в пять мест (дашборд, отметка оплаты, напоминания,
«отправить ближайшие», календарь) и копии расходились. Теперь сервер везде
использует этот модуль.

Даты считаются от опорной даты (anchor) по номеру периода k, а не шагами
от предыдущей даты — поэтому платёж 31-го не «съезжает» на 28-е после февраля.
"""
from calendar import monthrange
from datetime import date, timedelta
import math


def _clamp_day(y: int, m: int, day: int) -> date:
    return date(y, m, min(day, monthrange(y, m)[1]))


def nth_due(anchor: date, cycle: str, freq: int, k: int) -> date:
    """Дата k-го платежа от опорной (k=0 — сама опорная дата)."""
    freq = max(1, int(freq or 1))
    cycle = cycle or "monthly"
    if cycle == "daily":
        return anchor + timedelta(days=freq * k)
    if cycle == "weekly":
        return anchor + timedelta(weeks=freq * k)
    if cycle == "yearly":
        return _clamp_day(anchor.year + freq * k, anchor.month, anchor.day)
    total = anchor.month - 1 + freq * k
    return _clamp_day(anchor.year + total // 12, total % 12 + 1, anchor.day)


def _approx_k(anchor: date, cycle: str, freq: int, target: date) -> int:
    """Грубая оценка номера периода, ближайшего к target (дальше уточняется)."""
    freq = max(1, int(freq or 1))
    if cycle == "daily":
        return (target - anchor).days // freq
    if cycle == "weekly":
        return (target - anchor).days // (7 * freq)
    if cycle == "yearly":
        return (target.year - anchor.year) // freq
    months = (target.year - anchor.year) * 12 + (target.month - anchor.month)
    return months // freq


def next_due(anchor: date, cycle: str, freq: int, today: date) -> date:
    """Первая дата платежа >= today."""
    if anchor >= today:
        return anchor
    k = max(0, _approx_k(anchor, cycle, freq, today) - 1)
    while nth_due(anchor, cycle, freq, k) < today:
        k += 1
    return nth_due(anchor, cycle, freq, k)


def last_due(anchor: date, cycle: str, freq: int, today: date):
    """Последняя дата платежа <= today, или None, если первый платёж ещё впереди."""
    if anchor > today:
        return None
    k = max(0, _approx_k(anchor, cycle, freq, today) + 1)
    while k > 0 and nth_due(anchor, cycle, freq, k) > today:
        k -= 1
    return nth_due(anchor, cycle, freq, k)


def cycle_anchor(s, today: date):
    """Опорная дата графика платежей.

    База — next_payment, иначе start_date, иначе сегодня. Для помесячных и
    годовых графиков число берётся из «Дня списания» (billing_day) — именно его
    пользователь задаёт в форме подписки и видит в карточке и календаре.
    (До 1.2.1 сервер брал число из next_payment, которое форма молча заполняла
    датой создания, — и напоминания приходили не в день списания.)
    Первый платёж — не раньше базы.
    """
    base = s.next_payment or s.start_date
    bd = int(s.billing_day or 0)
    cycle = s.cycle or "monthly"
    if bd and cycle in ("monthly", "yearly"):
        b = base or today
        a = _clamp_day(b.year, b.month, bd)
        if base and a < base:
            a = nth_due(a, cycle, s.frequency, 1)
        return a
    return base


def has_schedule(s) -> bool:
    """Есть ли у подписки регулярные платежи по графику."""
    if s.sub_type == "recurring":
        return True
    if s.sub_type == "balance":
        return bool(s.billing_day)  # счёт без дня списания — ручной контроль
    return False


def next_payment_for(s, today: date):
    """Дата ближайшего платежа (>= today) с учётом периодичности."""
    if s.sub_type == "onetime":
        return s.next_payment
    if not has_schedule(s):
        return None
    anchor = cycle_anchor(s, today)
    if not anchor:
        return None
    return next_due(anchor, s.cycle, s.frequency, today)


def last_due_for(s, today: date):
    """Последняя наступившая дата платежа (<= today)."""
    if s.sub_type == "onetime":
        return s.next_payment if (s.next_payment and s.next_payment <= today) else None
    if not has_schedule(s):
        return None
    anchor = cycle_anchor(s, today)
    if not anchor:
        return None
    return last_due(anchor, s.cycle, s.frequency, today)


def is_paid(s, due: date) -> bool:
    return bool(s.paid_until and due and s.paid_until >= due)


def overdue_date(s, today: date):
    """Дата неоплаченного просроченного платежа для подписки с ручной оплатой, иначе None.

    Учитывается только последний наступивший платёж: если пропущено несколько
    периодов подряд, напоминаем о самом свежем.
    """
    if s.auto_renew or s.sub_type not in ("recurring", "onetime"):
        return None
    due = last_due_for(s, today)
    if due and due < today and not is_paid(s, due):
        return due
    return None


def mark_paid_until(s, today: date) -> date:
    """До какой даты считать оплаченным при нажатии «Отметить оплату».

    Если есть неоплаченный просроченный платёж — закрываем именно его
    (раньше закрывался уже следующий период). Иначе — ближайший платёж.
    """
    if s.sub_type == "onetime":
        return s.next_payment or today
    od = overdue_date(s, today)
    if od:
        return od
    nxt = next_payment_for(s, today)
    return nxt or today


def monthly_cost(s) -> float:
    """Стоимость подписки, приведённая к месяцу."""
    price = s.price or 0
    freq = max(int(s.frequency or 1), 1)
    cycle = s.cycle or "monthly"
    if cycle == "monthly":
        return price / freq
    if cycle == "yearly":
        return price / (12 * freq)
    if cycle == "weekly":
        return price * (4.345 / freq)
    if cycle == "daily":
        return price * (30 / freq)
    return 0.0


def _n(x) -> str:
    try:
        return f"{x:.0f}" if x == int(x) else f"{x:.2f}"
    except Exception:
        return str(x)


def low_balance_check(s, today: date):
    """Проверка низкого баланса. Возвращает (причины, порог).

    Общее для всех счетов: баланс <= «минимум для уведомления» (если задан).
    Ежедневное списание: если задана стоимость за месяц — предупреждаем,
      когда баланса хватает на notify_days_left дней или меньше.
    Периодическое списание: баланс меньше суммы следующего списания.
    """
    reasons = []
    threshold = 0.0
    balance = s.balance or 0
    has_min = bool(s.min_balance and s.min_balance > 0)
    has_price = bool(s.price and s.price > 0)

    if has_min:
        threshold = s.min_balance
        if balance <= s.min_balance:
            reasons.append(f"баланс {_n(balance)} ниже минимума {_n(s.min_balance)} {s.currency}")

    if s.sub_type == "balance_daily":
        if has_price:
            per_day = s.price / monthrange(today.year, today.month)[1]
            warn_days = s.notify_days_left or 10
            threshold = max(threshold, per_day * warn_days)
            days_left = math.floor(balance / per_day) if per_day > 0 else None
            if days_left is not None and days_left <= warn_days:
                until = today + timedelta(days=max(days_left, 0))
                reasons.append(
                    f"баланса {_n(balance)} {s.currency} хватит на ~{max(days_left, 0)} дн. "
                    f"(до {until.strftime('%d.%m.%Y')})"
                )
    elif has_price:
        threshold = max(threshold, s.price)
        if balance < s.price:
            reasons.append(f"баланса {_n(balance)} не хватит на следующее списание {_n(s.price)} {s.currency}")

    return reasons, threshold
