from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import os

# Логирование на уровне INFO с временем и уровнем
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("oops")

from app.database import engine, SessionLocal
from app.models import Base, User, Category, PaymentMethod
from app.auth import hash_password
from app.scheduler import start_scheduler

from app.routers import (
    auth, users, organizations, contractors, employees,
    categories, payment_methods, subscriptions, documents, webhooks, system
)


from sqlalchemy import text


def migrate_db():
    """Простые миграции для добавления новых колонок к существующим таблицам."""
    with engine.connect() as conn:
        # Список колонок Contractor — если logo_url отсутствует, добавим
        try:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(contractors)"))]
            if "logo_url" not in cols:
                conn.execute(text("ALTER TABLE contractors ADD COLUMN logo_url VARCHAR(500) DEFAULT ''"))
                conn.commit()
        except Exception as e:
            log.warning(f"Migration: {e}")

        # Добавить колонку icon в payment_methods
        try:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(payment_methods)"))]
            if "icon" not in cols:
                conn.execute(text("ALTER TABLE payment_methods ADD COLUMN icon VARCHAR(50) DEFAULT '💳'"))
                conn.commit()
        except Exception as e:
            log.warning(f"Migration (payment icon): {e}")

        # Добавить поля уведомлений в subscriptions
        try:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(subscriptions)"))]
            if "notify_enabled" not in cols:
                conn.execute(text("ALTER TABLE subscriptions ADD COLUMN notify_enabled BOOLEAN DEFAULT 1"))
            if "notify_days_before" not in cols:
                conn.execute(text("ALTER TABLE subscriptions ADD COLUMN notify_days_before VARCHAR(100) DEFAULT '3'"))
            if "cancellation_date" not in cols:
                conn.execute(text("ALTER TABLE subscriptions ADD COLUMN cancellation_date DATE"))
            conn.commit()
        except Exception as e:
            log.warning(f"Migration (subscription notify): {e}")

        # Добавить поля типа/конфига в webhook_configs (универсальный канал уведомлений)
        try:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(webhook_configs)"))]
            if "kind" not in cols:
                conn.execute(text("ALTER TABLE webhook_configs ADD COLUMN kind VARCHAR(20) DEFAULT 'webhook'"))
            if "config" not in cols:
                conn.execute(text("ALTER TABLE webhook_configs ADD COLUMN config TEXT DEFAULT '{}'"))
            conn.commit()
        except Exception as e:
            log.warning(f"Migration (webhook kind/config): {e}")
        # Убрать категорию-заглушку "No category" / "Без категории":
        # у подписок с ней сбросить category_id в NULL, саму категорию удалить.
        try:
            placeholder_names = ("No category", "Без категории", "Uncategorized", "Без категорії")
            placeholders = ",".join(f"'{n}'" for n in placeholder_names)
            rows = list(conn.execute(text(
                f"SELECT id FROM categories WHERE name IN ({placeholders})"
            )))
            for row in rows:
                cat_id = row[0]
                conn.execute(text("UPDATE subscriptions SET category_id = NULL WHERE category_id = :cid"), {"cid": cat_id})
                conn.execute(text("DELETE FROM categories WHERE id = :cid"), {"cid": cat_id})
            if rows:
                conn.commit()
        except Exception as e:
            log.warning(f"Migration (placeholder category): {e}")

        # Унификация типов подписок: fixed → recurring, special → balance
        try:
            res1 = conn.execute(text("UPDATE subscriptions SET sub_type = 'recurring' WHERE sub_type = 'fixed'"))
            res2 = conn.execute(text("UPDATE subscriptions SET sub_type = 'balance' WHERE sub_type = 'special'"))
            if (res1.rowcount or 0) + (res2.rowcount or 0) > 0:
                conn.commit()
                log.info(f"Migration sub_type: fixed→recurring={res1.rowcount}, special→balance={res2.rowcount}")
        except Exception as e:
            log.warning(f"Migration (sub_type unify): {e}")

        # Поле даты последнего уведомления о низком балансе
        try:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(subscriptions)"))]
            if "last_low_balance_notify" not in cols:
                conn.execute(text("ALTER TABLE subscriptions ADD COLUMN last_low_balance_notify DATE"))
                conn.commit()
        except Exception as e:
            log.warning(f"Migration (last_low_balance_notify): {e}")

        # Поля отслеживания напоминаний и ручного продления
        try:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(subscriptions)"))]
            if "last_payment_notify_for" not in cols:
                conn.execute(text("ALTER TABLE subscriptions ADD COLUMN last_payment_notify_for DATE"))
            if "paid_until" not in cols:
                conn.execute(text("ALTER TABLE subscriptions ADD COLUMN paid_until DATE"))
            if "overdue_notify_after" not in cols:
                conn.execute(text("ALTER TABLE subscriptions ADD COLUMN overdue_notify_after VARCHAR(50) DEFAULT '0'"))
            if "notify_duration" not in cols:
                conn.execute(text("ALTER TABLE subscriptions ADD COLUMN notify_duration VARCHAR(50) DEFAULT '1'"))
            if "daily_charge" not in cols:
                conn.execute(text("ALTER TABLE subscriptions ADD COLUMN daily_charge BOOLEAN DEFAULT 0"))
            if "notify_days_left" not in cols:
                conn.execute(text("ALTER TABLE subscriptions ADD COLUMN notify_days_left INTEGER DEFAULT 10"))
            conn.commit()
            # Перевод старого флага daily_charge в новый тип balance_daily (разовая миграция)
            try:
                conn.execute(text(
                    "UPDATE subscriptions SET sub_type='balance_daily' "
                    "WHERE daily_charge=1 AND sub_type='balance'"
                ))
                conn.commit()
            except Exception as e:
                log.warning(f"Migration (daily_charge -> balance_daily): {e}")
        except Exception as e:
            log.warning(f"Migration (notify/paid fields): {e}")


def init_db():
    Base.metadata.create_all(bind=engine)
    migrate_db()
    db = SessionLocal()
    try:
        # Создать админа если нет ни одного пользователя
        if not db.query(User).first():
            admin = User(
                username="admin",
                password_hash=hash_password("admin"),
                full_name="Администратор",
                role="admin",
            )
            db.add(admin)

        # Базовые категории
        if not db.query(Category).first():
            for name, icon, color in [
                ("Интернет", "/static/icons/builtin/cat-internet.svg", "#0EA5E9"),
                ("Хостинг", "/static/icons/builtin/cat-hosting.svg", "#8B5CF6"),
                ("Облако", "/static/icons/builtin/cat-cloud.svg", "#06B6D4"),
                ("ПО / Софт", "/static/icons/builtin/cat-software.svg", "#10B981"),
                ("Связь", "/static/icons/builtin/cat-phone.svg", "#F43F5E"),
                ("СМС", "/static/icons/builtin/cat-sms.svg", "#A855F7"),
                ("VPN", "/static/icons/builtin/cat-vpn.svg", "#0F766E"),
                ("Безопасность", "/static/icons/builtin/cat-security.svg", "#DC2626"),
                ("Видео", "/static/icons/builtin/cat-video.svg", "#EF4444"),
                ("Музыка", "/static/icons/builtin/cat-music.svg", "#EC4899"),
                ("Реклама", "/static/icons/builtin/cat-ads.svg", "#F59E0B"),
                ("Дизайн", "/static/icons/builtin/cat-design.svg", "#9333EA"),
                ("Аналитика", "/static/icons/builtin/cat-analytics.svg", "#3B82F6"),
                ("Домен", "/static/icons/builtin/cat-domain.svg", "#14B8A6"),
                ("Почта", "/static/icons/builtin/cat-email.svg", "#6366F1"),
                ("AI / Нейросети", "/static/icons/builtin/cat-ai.svg", "#1F2937"),
                ("Офис", "/static/icons/builtin/cat-office.svg", "#475569"),
                ("Прочее", "/static/icons/builtin/cat-other.svg", "#94A3B8"),
            ]:
                db.add(Category(name=name, icon=icon, color=color))

        # Базовые способы оплаты
        if not db.query(PaymentMethod).first():
            for name, icon in [
                ("Банковская карта", "/static/icons/builtin/card.svg"),
                ("Visa", "/static/icons/builtin/visa.svg"),
                ("MasterCard", "/static/icons/builtin/mastercard.svg"),
                ("МИР", "/static/icons/builtin/mir.svg"),
                ("Банковский перевод", "/static/icons/builtin/bank-transfer.svg"),
                ("Расчётный счёт", "/static/icons/builtin/invoice.svg"),
                ("СБП", "/static/icons/builtin/sbp.svg"),
                ("Google Pay", "/static/icons/builtin/google-pay.svg"),
                ("Apple Pay", "/static/icons/builtin/apple-pay.svg"),
                ("Google Play", "/static/icons/builtin/google-play.svg"),
                ("App Store", "/static/icons/builtin/app-store.svg"),
                ("Наличные", "/static/icons/builtin/cash.svg"),
            ]:
                db.add(PaymentMethod(name=name, icon=icon))

        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    sched = start_scheduler()
    yield
    sched.shutdown()


app = FastAPI(title="Oops! — учёт подписок и оплат", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(organizations.router)
app.include_router(contractors.router)
app.include_router(employees.router)
app.include_router(categories.router)
app.include_router(payment_methods.router)
app.include_router(subscriptions.router)
app.include_router(documents.router)
app.include_router(webhooks.router)
app.include_router(system.router)

# Статика
static_path = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Логотипы контрагентов (раздаются как /data/logos/*)
logos_path = "/app/data/logos"
os.makedirs(logos_path, exist_ok=True)
app.mount("/data/logos", StaticFiles(directory=logos_path), name="logos")

# Пользовательские иконки (категории/способы оплаты)
icons_path = "/app/data/icons"
os.makedirs(icons_path, exist_ok=True)
app.mount("/data/icons", StaticFiles(directory=icons_path), name="icons")


_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}


@app.get("/")
def index():
    from app.version import BUILD
    from fastapi.responses import HTMLResponse
    try:
        with open(os.path.join(static_path, "index.html"), "r", encoding="utf-8") as f:
            html = f.read()
        # Подставляем номер сборки в cache-bust параметры (?v=__BUILD__)
        html = html.replace("__BUILD__", str(BUILD))
        return HTMLResponse(content=html, headers=_NO_CACHE)
    except Exception:
        return FileResponse(os.path.join(static_path, "index.html"), headers=_NO_CACHE)


@app.get("/login")
def login_page():
    return FileResponse(os.path.join(static_path, "login.html"), headers=_NO_CACHE)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    svg_path = os.path.join(static_path, "favicon.svg")
    if os.path.exists(svg_path):
        return FileResponse(svg_path, media_type="image/svg+xml")
    return Response(status_code=204)
