from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date, datetime, timedelta
from calendar import monthrange
from html import escape as html_escape
from urllib.parse import urlsplit
from sqlalchemy.orm import Session
import httpx
import json
import logging
import os
import smtplib
import sqlite3
from email.mime.text import MIMEText
from email.utils import formataddr

from app.database import SessionLocal
from app.models import Subscription, WebhookConfig, NotificationLog
from app import billing

log = logging.getLogger("oops.scheduler")


def _safe_url(url: str) -> str:
    """URL для логов без секретов: только схема и хост (токены Bitrix/Telegram в пути не пишем)."""
    try:
        u = urlsplit(url or "")
        return f"{u.scheme}://{u.hostname}{':' + str(u.port) if u.port else ''}/…" if u.hostname else "(url)"
    except Exception:
        return "(url)"


def _format_payload(template: str, data: dict) -> str:
    """Подставляет {{переменные}} в шаблон.

    Если шаблон — JSON (начинается с { или [), значения экранируются для JSON,
    чтобы кавычки/переносы в названиях (ООО "Ромашка") не ломали тело запроса.
    """
    out = template or ""
    is_json = out.lstrip()[:1] in ("{", "[")
    for k, v in data.items():
        val = "" if v is None else str(v)
        if is_json:
            val = json.dumps(val, ensure_ascii=False)[1:-1]
        out = out.replace("{{" + k + "}}", val)
    return out


def _send_via_webhook(wh: WebhookConfig, data: dict, message: str):
    payload = _format_payload(wh.payload_template or "{}", data)
    headers = {}
    try:
        headers = json.loads(wh.headers) if wh.headers else {}
    except Exception:
        pass
    log.info(f"Webhook → {wh.method or 'POST'} {_safe_url(wh.url)}")
    try:
        with httpx.Client(timeout=10, verify=not wh.ignore_ssl) as client:
            r = client.request(wh.method or "POST", wh.url, content=payload, headers=headers)
            text = r.text[:500]
            log.info(f"Webhook ← {r.status_code} {text[:200]}")
            ok = r.status_code < 400
            return {
                "success": ok,
                "status": r.status_code,
                "response": text,
                "error": None if ok else f"HTTP {r.status_code}: {text[:200]}",
            }
    except Exception as e:
        log.warning(f"Webhook exception: {e}")
        return {"success": False, "error": str(e)}


def _send_via_bitrix24(wh: WebhookConfig, data: dict, message: str):
    """Bitrix24 incoming webhook.

    URL вида: https://your.bitrix24.ru/rest/<user_id>/<token>/
    Если задан CHAT_ID (DIALOG_ID) — отправляем сообщение в чат через im.message.add.
    Иначе — личное уведомление через im.notify (USER_ID — кому, иначе владельцу вебхука).
    """
    if not wh.url:
        return {"success": False, "error": "URL не задан"}
    try:
        cfg = json.loads(wh.config or "{}")
    except Exception as e:
        return {"success": False, "error": f"Не удалось распарсить config: {e}"}
    user_id = str(cfg.get("user_id") or "").strip()
    dialog_id = str(cfg.get("dialog_id") or cfg.get("chat_id") or "").strip()
    # Флаг «системное сообщение в чате» — серый курсив по центру, без аватарки
    system_msg = bool(cfg.get("system_message", False))
    text = f"💳 [B]{data.get('subscription_name','')}[/B]\n{message}"
    base = wh.url.rstrip("/")
    if dialog_id:
        endpoint = f"{base}/im.message.add.json"
        body = {
            "DIALOG_ID": dialog_id,
            "MESSAGE": text,
            "SYSTEM": "Y" if system_msg else "N",
        }
    else:
        endpoint = f"{base}/im.notify.json"
        body = {"TYPE": "SYSTEM", "MESSAGE": text}
        if user_id:
            body["USER_ID"] = user_id

    log.info(f"Bitrix24 → POST {_safe_url(endpoint)} method={endpoint.rsplit('/', 1)[-1]}")
    try:
        with httpx.Client(timeout=10, verify=not wh.ignore_ssl) as client:
            r = client.post(endpoint, data=body)
            response_text = r.text[:500]
            log.info(f"Bitrix24 ← {r.status_code} {response_text}")
            if r.status_code >= 400:
                return {
                    "success": False,
                    "status": r.status_code,
                    "response": response_text,
                    "error": f"HTTP {r.status_code}: {response_text[:300]}",
                }
            # API Битрикса может вернуть 200 с {"error": ...} или result=false
            try:
                j = r.json()
                if isinstance(j, dict) and j.get("error"):
                    err = j.get("error_description") or j.get("error")
                    return {
                        "success": False,
                        "status": r.status_code,
                        "response": response_text,
                        "error": f"Bitrix24: {err}",
                    }
                if isinstance(j, dict) and j.get("result") is False:
                    return {
                        "success": False,
                        "status": r.status_code,
                        "response": response_text,
                        "error": f"Bitrix24 вернул result=false: {response_text[:200]}",
                    }
            except Exception:
                pass
            return {"success": True, "status": r.status_code, "response": response_text}
    except Exception as e:
        log.warning(f"Bitrix24 exception: {e}")
        return {"success": False, "error": str(e)}


def _send_via_email(wh: WebhookConfig, data: dict, message: str):
    try:
        cfg = json.loads(wh.config or "{}")
    except Exception as e:
        return {"success": False, "error": f"Не удалось распарсить config: {e}"}
    host = cfg.get("smtp_host")
    port = int(cfg.get("smtp_port") or 587)
    user = cfg.get("smtp_user", "")
    password = cfg.get("smtp_password", "")
    from_addr = cfg.get("from_addr") or user
    to_addr = cfg.get("to_addr")
    use_tls = cfg.get("use_tls", True)
    if not (host and to_addr):
        return {"success": False, "error": "Не задан SMTP-хост или адрес получателя"}
    subj = f"Oops! — {data.get('subscription_name', 'Уведомление')}"
    body_text = f"{message}\n\nПодписка: {data.get('subscription_name','')}\nЦена: {data.get('subscription_price','')} {data.get('subscription_currency','')}\nДата: {data.get('subscription_date','')}"
    msg = MIMEText(body_text, "plain", "utf-8")
    msg["Subject"] = subj
    msg["From"] = formataddr(("Oops!", from_addr))
    msg["To"] = to_addr
    log.info(f"Email → {host}:{port} {from_addr} → {to_addr}")
    try:
        if port == 465:
            # порт 465 — сразу SSL-соединение (SMTPS), STARTTLS там не работает
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            if use_tls:
                server.starttls()
        if user:
            server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())
        server.quit()
        return {"success": True}
    except Exception as e:
        log.warning(f"Email send failed: {e}")
        return {"success": False, "error": str(e)}


def _send_via_telegram(wh: WebhookConfig, data: dict, message: str):
    try:
        cfg = json.loads(wh.config or "{}")
    except Exception as e:
        return {"success": False, "error": f"Не удалось распарсить config: {e}"}
    token = cfg.get("bot_token")
    chat_id = cfg.get("chat_id")
    if not (token and chat_id):
        return {"success": False, "error": "Не задан bot_token или chat_id"}
    # HTML-разметка: в отличие от Markdown не ломается на «_» и «*» в названиях
    e = lambda v: html_escape(str(v or ""), quote=False)
    text = (f"💳 <b>{e(data.get('subscription_name'))}</b>\n{e(message)}\n\n"
            f"<i>Цена:</i> {e(data.get('subscription_price'))} {e(data.get('subscription_currency'))}")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    log.info(f"Telegram → chat_id={chat_id}")
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
            text_resp = r.text[:500]
            log.info(f"Telegram ← {r.status_code} {text_resp[:200]}")
            ok = r.status_code < 400
            return {
                "success": ok,
                "status": r.status_code,
                "response": text_resp,
                "error": None if ok else f"HTTP {r.status_code}: {text_resp[:200]}",
            }
    except Exception as e:
        log.warning(f"Telegram exception: {e}")
        return {"success": False, "error": str(e)}


def _send_webhook_notification(db: Session, sub: Subscription, message: str, event_type: str, due_date=None):
    """Шлёт уведомление через все включённые каналы любого типа.
    due_date — дата платежа, о котором уведомление (иначе — next_payment из карточки)."""
    channels = db.query(WebhookConfig).filter(WebhookConfig.enabled == True).all()
    pay_date = due_date or sub.next_payment
    data = {
        "subscription_name": sub.name,
        "subscription_price": str(sub.price),
        "subscription_currency": sub.currency,
        "subscription_category": sub.category.name if sub.category else "",
        "subscription_date": pay_date.isoformat() if pay_date else "",
        "subscription_organization": sub.organization.name if sub.organization else "",
        "subscription_url": sub.url or "",
        "subscription_notes": message,
        "message": message,
        "event_type": event_type,
    }
    for ch in channels:
        kind = (ch.kind or "webhook").lower()
        if kind == "bitrix24":
            result = _send_via_bitrix24(ch, data, message)
        elif kind == "email":
            result = _send_via_email(ch, data, message)
        elif kind == "telegram":
            result = _send_via_telegram(ch, data, message)
        else:
            result = _send_via_webhook(ch, data, message)
        ok = bool(result.get("success"))
        # В лог пишем не только сам message, но и ошибку если была — чтобы было видно в журнале UI
        log_msg = f"[{kind}] {message}"
        if not ok and result.get("error"):
            log_msg += f" — ОШИБКА: {result['error']}"
        db.add(NotificationLog(
            subscription_id=sub.id,
            event_type=event_type,
            message=log_msg,
            success=ok,
        ))
    db.commit()


def _check_low_balance(db, s):
    """Уведомление о низком балансе не чаще раза в сутки.
    Правила — в app/billing.py (low_balance_check), те же, что на дашборде."""
    today = date.today()
    reasons, _threshold = billing.low_balance_check(s, today)

    if reasons:
        if s.last_low_balance_notify == today:
            return  # уже слали сегодня
        msg = f"⚠️ «{s.name}»: " + "; ".join(reasons)
        _send_webhook_notification(db, s, msg, "balance_low")
        s.last_low_balance_notify = today
        db.commit()
    else:
        if s.last_low_balance_notify is not None:
            s.last_low_balance_notify = None
            db.commit()


def update_balance_subscriptions():
    """Ежемесячное автосписание для РУЧНЫХ балансовых подписок (без API).
    Подписки с API не трогаем — их реальный баланс приходит из внешнего сервиса
    и уже учитывает все списания/пополнения на его стороне.

    Списание происходит в день списания (для 29–31 в коротком месяце — в последний
    день месяца). Если в этот день приложение было выключено — списание догоняется
    позже в том же месяце, но только если прошлое списание было в прошлом месяце
    (то есть счёт регулярно обслуживается и пропуск действительно случайный)."""
    db = SessionLocal()
    try:
        today = date.today()
        prev_month_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        subs = db.query(Subscription).filter(
            Subscription.sub_type.in_(["balance", "balance_daily"]),
            Subscription.is_active == True
        ).all()
        for s in subs:
            # Пропускаем подписки с включённым API — их баланс ведёт внешний сервис
            if s.balance_api_url:
                continue
            # Без дня списания автосписания нет (ручной контроль)
            if not s.billing_day:
                continue
            charge_day = min(int(s.billing_day), monthrange(today.year, today.month)[1])
            last = s.last_balance_update
            if last and last.year == today.year and last.month == today.month:
                continue  # в этом месяце уже списали
            if today.day == charge_day:
                pass  # штатное списание
            elif today.day > charge_day and last and last >= prev_month_start:
                log.info(f"Balance charge catch-up for {s.name} (day {charge_day} was missed)")
            else:
                continue

            s.balance = max(0, (s.balance or 0) - (s.price or 0))
            s.last_balance_update = today
            nm_y, nm_m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            s.next_payment = date(nm_y, nm_m, min(int(s.billing_day), monthrange(nm_y, nm_m)[1]))
            db.commit()

            _check_low_balance(db, s)
    except Exception as e:
        log.warning(f"update_balance_subscriptions: {e}")
    finally:
        db.close()


def fetch_balances_from_api():
    """Каждые 30 минут обновляет баланс из API если указан URL (для balance)"""
    from app.routers.subscriptions import _extract_balance, _ApiError, http_get_balance
    db = SessionLocal()
    try:
        subs = db.query(Subscription).filter(
            Subscription.sub_type.in_(["balance", "balance_daily"]),
            Subscription.is_active == True,
            Subscription.balance_api_url != ""
        ).all()
        for s in subs:
            try:
                raw_text = http_get_balance(s.balance_api_url)
                value = _extract_balance(raw_text, s.balance_api_path or "balance")
                if value is None:
                    log.warning(f"Balance not found for {s.name}: response={raw_text.strip()[:120]!r}")
                    continue
                old_balance = s.balance
                s.balance = float(value)
                s.last_balance_update = date.today()
                db.commit()
                log.info(f"Balance updated for {s.name}: {old_balance} → {s.balance}")

                _check_low_balance(db, s)
            except Exception as e:
                log.warning(f"Failed to fetch balance for {s.name}: {e}")
    finally:
        db.close()


def fmt_amount(s):
    """Сумма платежа для текста уведомления."""
    try:
        return f"{s.price:.0f} {s.currency}" if s.price == int(s.price) else f"{s.price} {s.currency}"
    except Exception:
        return f"{s.price} {s.currency}"


def send_payment_reminders():
    """Каждый час (и при старте) — напоминания о платежах согласно notify_days_before.
    Не чаще одного напоминания о платеже и одного об отмене в сутки на подписку.
    Также шлёт уведомление об отмене подписки за указанные дни до cancellation_date."""
    db = SessionLocal()
    try:
        today = date.today()

        subs = db.query(Subscription).filter(
            Subscription.is_active == True,
            Subscription.notify_enabled == True,
        ).all()

        for s in subs:
            try:
                _remind_one(db, s, today)
            except Exception as e:
                db.rollback()
                log.warning(f"Reminder for {s.name} failed: {e}")
    finally:
        db.close()


def _remind_one(db, s, today):
    # За сколько дней до платежа начинать напоминать (своё у каждой подписки)
    try:
        start_before = int(str(s.notify_days_before or "3").split(",")[0].strip())
    except (ValueError, AttributeError):
        start_before = 3

    def send(msg, due):
        _send_webhook_notification(db, s, msg, "payment_due", due_date=due)
        s.last_payment_notify_for = today
        db.commit()

    # Раз в день максимум
    if s.last_payment_notify_for != today:
        manual = not s.auto_renew and s.sub_type in ("recurring", "onetime")
        od = billing.overdue_date(s, today) if manual else None
        next_pay = billing.next_payment_for(s, today)

        if od:
            # Ручная оплата: наступивший платёж не отмечен — напоминаем каждый день
            days = (today - od).days
            send(f"Просрочено {days} дн.: не оплачена подписка «{s.name}» — платёж был "
                 f"{od.isoformat()} ({fmt_amount(s)})", od)
        elif next_pay and next_pay >= today:
            diff = (next_pay - today).days
            already_paid = billing.is_paid(s, next_pay)
            if 0 <= diff <= start_before:
                if s.sub_type == "balance":
                    bal = f"Баланс: {s.balance:.0f} {s.currency}"
                    if diff > 1:
                        send(f"Через {diff} дн. списание со счёта «{s.name}» — {next_pay.isoformat()} ({fmt_amount(s)}). {bal}", next_pay)
                    elif diff == 1:
                        send(f"Завтра списание со счёта «{s.name}» ({fmt_amount(s)}). {bal}", next_pay)
                    else:
                        send(f"Сегодня списание со счёта «{s.name}» ({fmt_amount(s)}). {bal}", next_pay)
                elif not already_paid:
                    word = "автосписание по" if s.auto_renew else "оплата подписки"
                    if diff > 1:
                        send(f"Через {diff} дн. {word} «{s.name}» — {next_pay.isoformat()} ({fmt_amount(s)})", next_pay)
                    elif diff == 1:
                        send(f"Завтра {word} «{s.name}» ({fmt_amount(s)})", next_pay)
                    else:
                        send(f"Сегодня {word} «{s.name}» ({fmt_amount(s)})", next_pay)

    # Напоминание об отмене — тоже не чаще раза в сутки
    if s.cancellation_date and s.last_cancel_notify != today:
        cdiff = (s.cancellation_date - today).days
        if 0 <= cdiff <= start_before:
            msg = f"Подписка «{s.name}» будет отменена {s.cancellation_date.isoformat()}"
            _send_webhook_notification(db, s, msg, "cancellation", due_date=s.cancellation_date)
            s.last_cancel_notify = today
            db.commit()


def record_monthly_snapshot():
    """1-го числа месяца: записывает суммарный месячный расход в историю (для графика)."""
    from .models import Subscription, MonthlySnapshot
    db = SessionLocal()
    try:
        subs = db.query(Subscription).filter(Subscription.is_active == True).all()
        total = 0.0
        for s in subs:
            if s.sub_type == "onetime":
                continue
            total += billing.monthly_cost(s)
        period = date.today().strftime("%Y-%m")
        snap = db.query(MonthlySnapshot).filter(MonthlySnapshot.period == period).first()
        if snap:
            snap.total_monthly = round(total, 2)
        else:
            db.add(MonthlySnapshot(period=period, total_monthly=round(total, 2)))
        db.commit()
        log.info(f"Monthly snapshot {period}: {total:.0f}")
    except Exception as e:
        log.warning(f"record_monthly_snapshot: {e}")
    finally:
        db.close()


def sqlite_backup(src_path: str, dest_path: str):
    """Консистентная копия SQLite (online backup API) — безопасна во время записи."""
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dest_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def auto_backup():
    """Раз в неделю: создаёт snapshot БД в /app/data/backups/, хранит последние 4."""
    backup_dir = "/app/data/backups"
    db_path = "/app/data/oops.db"
    if not os.path.exists(db_path):
        return
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(backup_dir, f"oops_{ts}.db")
    try:
        sqlite_backup(db_path, dest)
    except Exception as e:
        log.warning(f"Auto-backup failed: {e}")
        return
    # Ротация: оставляем последние 4
    files = sorted(
        [f for f in os.listdir(backup_dir) if f.startswith("oops_") and f.endswith(".db")],
        reverse=True
    )
    for old in files[4:]:
        try:
            os.remove(os.path.join(backup_dir, old))
        except Exception:
            pass


def start_scheduler():
    tz = os.getenv("TZ") or "Europe/Moscow"
    try:
        sched = BackgroundScheduler(timezone=tz)
    except Exception:
        log.warning(f"Unknown TZ {tz!r}, using Europe/Moscow")
        sched = BackgroundScheduler(timezone="Europe/Moscow")
    sched.add_job(update_balance_subscriptions, "cron", hour=0, minute=5, id="balance_update")
    sched.add_job(fetch_balances_from_api, "cron", minute="*/30", id="fetch_balances")
    # Каждый час: догоняем пропущенные напоминания (дедуп защищает от повторов).
    # Так уведомление уйдёт даже если в 9:00 контейнер был выключен/перезапускался.
    sched.add_job(send_payment_reminders, "cron", minute=0, id="payment_reminders")
    sched.add_job(auto_backup, "cron", day_of_week="sun", hour=3, minute=0, id="auto_backup")
    sched.add_job(record_monthly_snapshot, "cron", day=1, hour=1, minute=0, id="monthly_snapshot")
    # записать снимок текущего месяца при старте (чтобы история начала копиться сразу)
    sched.add_job(record_monthly_snapshot, "date",
                  run_date=datetime.now() + timedelta(seconds=45), id="snapshot_startup")
    # Догнать списание балансов, если контейнер был выключен в день списания
    sched.add_job(update_balance_subscriptions, "date",
                  run_date=datetime.now() + timedelta(seconds=20), id="balance_startup")
    # Разовый прогон вскоре после старта — догнать пропущенное за время простоя
    sched.add_job(send_payment_reminders, "date",
                  run_date=datetime.now() + timedelta(seconds=30), id="reminders_startup")
    sched.start()
    return sched
