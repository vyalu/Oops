from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
import httpx
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

from app.database import SessionLocal
from app.models import Subscription, WebhookConfig, NotificationLog

log = logging.getLogger("oops.scheduler")


def _format_payload(template: str, data: dict) -> str:
    out = template or ""
    for k, v in data.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def _send_via_webhook(wh: WebhookConfig, data: dict, message: str):
    payload = _format_payload(wh.payload_template or "{}", data)
    headers = {}
    try:
        headers = json.loads(wh.headers) if wh.headers else {}
    except Exception:
        pass
    log.info(f"Webhook → {wh.method or 'POST'} {wh.url}")
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

    log.info(f"Bitrix24 → POST {endpoint} body={body}")
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
        if use_tls:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=15) if port == 465 else smtplib.SMTP(host, port, timeout=15)
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
    text = f"💳 *{data.get('subscription_name','')}*\n{message}\n\n_Цена:_ {data.get('subscription_price','')} {data.get('subscription_currency','')}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    log.info(f"Telegram → chat_id={chat_id}")
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
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


def _send_webhook_notification(db: Session, sub: Subscription, message: str, event_type: str):
    """Шлёт уведомление через все включённые каналы любого типа."""
    channels = db.query(WebhookConfig).filter(WebhookConfig.enabled == True).all()
    data = {
        "subscription_name": sub.name,
        "subscription_price": str(sub.price),
        "subscription_currency": sub.currency,
        "subscription_category": sub.category.name if sub.category else "",
        "subscription_date": sub.next_payment.isoformat() if sub.next_payment else "",
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
    """Уведомление о низком балансе не чаще раза в сутки. Условие (любое из):
    - задан min_balance и баланс ≤ min_balance (твой порог тревоги)
    - задана стоимость и баланс < price (не хватит на следующее списание)
    """
    today = date.today()
    reasons = []

    has_min = s.min_balance and s.min_balance > 0
    has_price = s.price and s.price > 0

    if has_min and s.balance <= s.min_balance:
        reasons.append(f"баланс {s.balance} ниже минимума {s.min_balance}")
    if has_price and s.balance < s.price:
        reasons.append(f"баланса {s.balance} не хватит на следующее списание {s.price}")

    if reasons:
        if s.last_low_balance_notify == today:
            return  # уже слали сегодня
        msg = f"⚠️ «{s.name}»: " + "; ".join(reasons) + f" {s.currency}"
        _send_webhook_notification(db, s, msg, "balance_low")
        s.last_low_balance_notify = today
        db.commit()
    else:
        # баланс в норме — сбрасываем, чтобы при следующем падении уведомить сразу
        if s.last_low_balance_notify is not None:
            s.last_low_balance_notify = None
            db.commit()


def update_balance_subscriptions():
    """Ежедневное автосписание для РУЧНЫХ балансовых подписок (без API).
    Подписки с API не трогаем — их реальный баланс приходит из внешнего сервиса
    и уже учитывает все списания/пополнения на его стороне."""
    db = SessionLocal()
    try:
        today = date.today()
        subs = db.query(Subscription).filter(
            Subscription.sub_type == "balance",
            Subscription.is_active == True
        ).all()
        for s in subs:
            # Пропускаем подписки с включённым API — их баланс ведёт внешний сервис
            if s.balance_api_url:
                continue
            # Без дня списания автосписания нет (ручной контроль)
            if not s.billing_day:
                continue
            if today.day != s.billing_day:
                continue
            if s.last_balance_update and s.last_balance_update.year == today.year and s.last_balance_update.month == today.month:
                continue

            new_balance = max(0, s.balance - s.price)
            next_month = today + timedelta(days=32)
            try:
                next_pay = next_month.replace(day=min(s.billing_day, 28))
            except ValueError:
                next_pay = next_month.replace(day=28)

            s.balance = new_balance
            s.last_balance_update = today
            s.next_payment = next_pay
            db.commit()

            _check_low_balance(db, s)
    finally:
        db.close()


def fetch_balances_from_api():
    """Каждые 30 минут обновляет баланс из API если указан URL (для balance)"""
    from app.routers.subscriptions import _extract_balance, _ApiError
    db = SessionLocal()
    try:
        subs = db.query(Subscription).filter(
            Subscription.sub_type == "balance",
            Subscription.is_active == True,
            Subscription.balance_api_url != ""
        ).all()
        for s in subs:
            try:
                with httpx.Client(timeout=15, verify=False, follow_redirects=True) as client:
                    r = client.get(s.balance_api_url)
                    r.raise_for_status()
                    raw_text = r.text
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
    """Каждый день в 9:00 — напоминания о платежах согласно notify_days_before подписки.
    Также шлёт уведомление об отмене подписки за указанные дни до cancellation_date."""
    db = SessionLocal()
    try:
        today = date.today()

        def parse_days(s):
            try:
                return sorted({max(0, int(x.strip())) for x in (s or "").split(",") if x.strip()})
            except Exception:
                return [3]

        def next_payment_for(s):
            """Возвращает дату следующего платежа подписки."""
            if s.sub_type == "onetime":
                return s.next_payment
            # recurring всегда по billing_day; balance — только если задан billing_day (есть автосписание)
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

        def last_due_for(s):
            """Дата последнего НАСТУПИВШЕГО платежа (сегодня или в прошлом), или None."""
            if s.sub_type == "onetime":
                return s.next_payment if (s.next_payment and s.next_payment <= today) else None
            if s.sub_type in ("recurring", "balance") and s.billing_day:
                day = min(s.billing_day, 28)
                # платёж этого месяца
                try:
                    this_month = today.replace(day=day)
                except ValueError:
                    return None
                if this_month <= today:
                    return this_month
                # иначе — платёж прошлого месяца
                if today.month == 1:
                    return today.replace(year=today.year - 1, month=12, day=day)
                return today.replace(month=today.month - 1, day=day)
            return None

        # Все активные подписки с включёнными уведомлениями
        subs = db.query(Subscription).filter(
            Subscription.is_active == True,
            Subscription.notify_enabled == True,
        ).all()

        for s in subs:
            # За сколько дней до платежа начинать напоминать (своё у каждой подписки)
            try:
                start_before = int(str(s.notify_days_before or "3").split(",")[0].strip())
            except (ValueError, AttributeError):
                start_before = 3

            # Раз в день максимум
            sent_today = s.last_payment_notify_for == today

            next_pay = next_payment_for(s)
            if next_pay and not sent_today:
                already_paid = s.paid_until and s.paid_until >= next_pay
                diff = (next_pay - today).days  # >0 до платежа, 0 в день, <0 просрочено

                if s.auto_renew:
                    # Автопродление: только предупреждаем заранее (в окне до платежа),
                    # без напоминаний о просрочке — платёж спишется сам.
                    if not already_paid and 0 <= diff <= start_before:
                        if diff > 1:
                            msg = f"Через {diff} дн. автосписание по «{s.name}» — {next_pay.isoformat()} ({fmt_amount(s)})"
                        elif diff == 1:
                            msg = f"Завтра автосписание по «{s.name}» ({fmt_amount(s)})"
                        else:
                            msg = f"Сегодня автосписание по «{s.name}» ({fmt_amount(s)})"
                        _send_webhook_notification(db, s, msg, "payment_due")
                        s.last_payment_notify_for = today
                        db.commit()
                else:
                    # Ручная оплата: напоминаем каждый день, начиная за start_before дней
                    # и далее, включая просрочку, пока не нажато «Продлено».
                    if not already_paid and diff <= start_before:
                        if diff > 1:
                            msg = f"Через {diff} дн. оплата подписки «{s.name}» — {next_pay.isoformat()} ({fmt_amount(s)})"
                        elif diff == 1:
                            msg = f"Завтра оплата подписки «{s.name}» ({fmt_amount(s)})"
                        elif diff == 0:
                            msg = f"Сегодня оплата подписки «{s.name}» ({fmt_amount(s)})"
                        else:
                            msg = f"Просрочено {(-diff)} дн.: не оплачена подписка «{s.name}» — платёж был {next_pay.isoformat()} ({fmt_amount(s)})"
                        _send_webhook_notification(db, s, msg, "payment_due")
                        s.last_payment_notify_for = today
                        db.commit()

            # Напоминание об отмене
            if s.cancellation_date:
                cdiff = (s.cancellation_date - today).days
                if 0 <= cdiff <= start_before:
                    msg = f"Подписка «{s.name}» будет отменена {s.cancellation_date.isoformat()}"
                    _send_webhook_notification(db, s, msg, "cancellation")
    finally:
        db.close()


def auto_backup():
    """Раз в неделю: создаёт snapshot БД в /app/data/backups/, хранит последние 4."""
    import shutil
    import os
    from datetime import datetime
    backup_dir = "/app/data/backups"
    db_path = "/app/data/oops.db"
    if not os.path.exists(db_path):
        return
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(backup_dir, f"oops_{ts}.db")
    try:
        shutil.copy2(db_path, dest)
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
    sched = BackgroundScheduler(timezone="Europe/Moscow")
    sched.add_job(update_balance_subscriptions, "cron", hour=0, minute=5, id="balance_update")
    sched.add_job(fetch_balances_from_api, "cron", minute="*/30", id="fetch_balances")
    # Каждый час: догоняем пропущенные напоминания (дедуп защищает от повторов).
    # Так уведомление уйдёт даже если в 9:00 контейнер был выключен/перезапускался.
    sched.add_job(send_payment_reminders, "cron", minute=0, id="payment_reminders")
    sched.add_job(auto_backup, "cron", day_of_week="sun", hour=3, minute=0, id="auto_backup")
    # Разовый прогон вскоре после старта — догнать пропущенное за время простоя
    sched.add_job(send_payment_reminders, "date",
                  run_date=datetime.now() + timedelta(seconds=30), id="reminders_startup")
    sched.start()
    return sched
