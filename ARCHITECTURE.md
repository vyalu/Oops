# Архитектура Oops!

## Обзор

Oops! — самохостящееся веб-приложение для учёта подписок и регулярных платежей организаций. Однофайловая БД SQLite, без сборщиков и npm — всё работает «в коробке» через один Docker-контейнер.

```
┌──────────────────────────────────────┐
│           Browser (Alpine.js)         │
└──────────────┬───────────────────────┘
               │ HTTPS/REST + Cookies
┌──────────────▼───────────────────────┐
│      FastAPI app (uvicorn)            │
│  ┌────────────────────────────────┐  │
│  │  Routers (api/*)                │  │
│  │  - auth, users                  │  │
│  │  - organizations, contractors   │  │
│  │  - employees, categories        │  │
│  │  - subscriptions, documents     │  │
│  │  - webhooks, system             │  │
│  └────────────────────────────────┘  │
│  ┌────────────────────────────────┐  │
│  │  APScheduler (background jobs)  │  │
│  └────────────────────────────────┘  │
│  ┌────────────────────────────────┐  │
│  │  SQLAlchemy ORM                 │  │
│  └────────┬───────────────────────┘  │
└───────────┼──────────────────────────┘
            │
       ┌────▼────┐    ┌─────────────┐
       │ SQLite  │    │  Uploads/   │
       │ oops.db │    │ documents   │
       └─────────┘    └─────────────┘
       (/app/data, mount как volume)
```

## Структура проекта

```
oops/
├── docker-compose.yml          # Один сервис, порт 8383→8000
├── Dockerfile                  # python:3.12-slim
├── requirements.txt            # Python зависимости
├── README.md                   # Инструкция по запуску
├── CHANGELOG.md                # История изменений
├── ARCHITECTURE.md             # Этот файл
│
├── app/
│   ├── __init__.py
│   ├── main.py                # Точка входа FastAPI + init БД
│   ├── database.py            # SQLAlchemy engine + sessionmaker
│   ├── models.py              # ORM модели всех сущностей
│   ├── schemas.py             # Pydantic схемы для валидации запросов/ответов
│   ├── auth.py                # JWT, хеширование паролей, RBAC dependencies
│   ├── scheduler.py           # APScheduler — фоновые задачи
│   │
│   ├── routers/               # API endpoints (по сущностям)
│   │   ├── auth.py            # POST /api/auth/login, logout, me
│   │   ├── users.py           # CRUD пользователей (admin only)
│   │   ├── organizations.py
│   │   ├── contractors.py
│   │   ├── employees.py
│   │   ├── categories.py
│   │   ├── payment_methods.py
│   │   ├── subscriptions.py   # CRUD + статистика + fetch-balance
│   │   ├── documents.py       # Загрузка файлов
│   │   ├── webhooks.py        # CRUD + тест + send-all
│   │   └── system.py          # Темы, дизайн, обновление приложения
│   │
│   └── static/                # Frontend (раздаётся как /static/*)
│       ├── index.html         # Главное SPA на Alpine.js
│       ├── login.html         # Страница входа
│       ├── styles.css         # Все стили + CSS-переменные тем
│       └── app.js             # Состояние и методы Alpine компонента
│
└── data/                      # Volume (создаётся при первом запуске)
    ├── oops.db                # SQLite БД
    ├── uploads/               # Загруженные документы
    └── app_backup/            # Бэкап старой версии app/ перед обновлением
```

## База данных

### Основные таблицы

| Таблица | Назначение |
|---|---|
| `users` | Учётки + роли (admin/manager/viewer), bcrypt-хеши паролей |
| `organizations` | Юр.лица клиента (ИНН, заметки) |
| `contractors` | Поставщики услуг (тоже ИНН, контакты, сайт) |
| `employees` | Сотрудники-ответственные |
| `categories` | Категории расходов с иконкой и цветом |
| `payment_methods` | Способы оплаты |
| `subscriptions` | **Главная таблица**: подписки 3 типов |
| `documents` | Прикреплённые файлы к подпискам |
| `webhook_configs` | Настройки webhook-уведомлений |
| `notification_log` | Лог отправленных уведомлений |
| `app_settings` | key-value хранилище (темы, дизайн, прочее) |

### Типы подписок (`subscriptions.sub_type`)

- **`fixed`** — стандартная регулярная (нужны `cycle`, `frequency`, `next_payment`)
- **`balance`** — пополняемый счёт (нужны `balance`, `billing_day`, опц. `balance_api_url`/`min_balance`)
- **`onetime`** — разовая (нужна только `next_payment`)

### Миграции

Сейчас используется `Base.metadata.create_all()` — таблицы создаются если их нет. При изменении схемы в проде нужен Alembic, но пока обходимся без него (приложение всё ещё в активной разработке).

## Авторизация

**JWT + httpOnly cookie**. При логине:
1. Проверка пароля через `passlib + bcrypt`
2. Генерация JWT с `sub` (username) и `role`
3. Запись токена в `access_token` cookie (`httponly`, `samesite=lax`, 7 дней)

При каждом запросе FastAPI dependency `get_current_user` достаёт токен из cookie или из заголовка `Authorization: Bearer`.

### Роли

- **`admin`** — всё: пользователи, webhooks, дизайн, обновление системы
- **`manager`** — CRUD подписок и справочников
- **`viewer`** — только просмотр

Реализация в `app/auth.py`:
- `require_admin` — dependency для admin-only endpoints
- `require_manager` — для admin или manager
- `get_current_user` — для любого авторизованного

## Frontend

**Без сборки**: один HTML + Alpine.js через CDN + Tailwind не используется, всё в кастомном CSS.

### Принципы

1. **Один HTML файл** (`index.html`) — все вкладки как `<div x-show="tab === '...'">`
2. **Один JS-компонент** (`app.js`) — функция `app()` возвращает Alpine state
3. **CSS-переменные** для тем — всё через `:root[data-theme="dark|light"]`
4. **Без bundle** — Alpine.js и шрифты подгружаются с CDN, остальное локально

### Темы

- Атрибут `data-theme` на `<html>` (читается из localStorage до загрузки JS чтобы не мигало)
- При логине загружается серверная настройка (`/api/system/theme`)
- Изменения сохраняются в БД per-user + дублируются в localStorage

### Кастомный дизайн (вкладка «Дизайн»)

- Все CSS-переменные сохраняются в `app_settings` под ключом `design_vars` (JSON)
- При загрузке приложения они применяются через `<style id="custom-design-vars">` инжектируемый в `<head>`
- Формат хранения: `{"--accent": "#5ED0BD", "light:--bg": "#fff"}` — префикс `light:` означает что переменная применяется только к светлой теме
- Live-preview: при изменении в UI сразу обновляется `<style>` элемент

## Автоматические задачи (APScheduler)

Запускается в `lifespan` FastAPI приложения, использует тот же процесс.

| Время | Задача | Что делает |
|---|---|---|
| 00:05 ежедневно | `update_balance_subscriptions` | Списывает баланс у подписок с `sub_type=balance` если сегодня `billing_day`. Обновляет `next_payment`. Шлёт webhook если баланс ниже порога. |
| Каждые 6 часов | `fetch_balances_from_api` | Получает балансы из внешних API (`balance_api_url`). Шлёт webhook если упал ниже порога. |
| 09:00 ежедневно | `send_payment_reminders` | Шлёт webhook за 3 дня до даты платежа (для `fixed` подписок). |

## Обновление приложения через UI

Endpoint `POST /api/system/upload-update` (только admin):

1. Принимает `.tar.gz` архив
2. Распаковывает во временную папку
3. Ищет внутри папку `app/` с `main.py`
4. Создаёт бэкап текущей `/app/app/` в `/app/data/app_backup/`
5. Удаляет старые `.py/.html/.js/.css` в `/app/app/`
6. Копирует новые файлы
7. Через 2 секунды делает `os._exit(0)`
8. Docker (`restart: unless-stopped`) поднимает контейнер заново с новым кодом
9. Frontend через 12 секунд делает `window.location.reload()`

Данные не теряются — БД и uploads в volume `/app/data/`.

## Webhook'и

Универсальный механизм уведомлений. В шаблоне `payload_template` можно использовать переменные:

| Переменная | Значение |
|---|---|
| `{{subscription_name}}` | Название подписки |
| `{{subscription_price}}` | Цена (число строкой) |
| `{{subscription_currency}}` | Валюта (RUB/USD/EUR) |
| `{{subscription_category}}` | Название категории |
| `{{subscription_date}}` | Дата следующего платежа |
| `{{subscription_organization}}` | Название организации |
| `{{subscription_url}}` | URL сервиса |
| `{{subscription_notes}}` | Примечания (или системное сообщение при low balance) |

Поддерживаются методы POST, PUT, GET, кастомные заголовки в JSON, отключение проверки SSL.

## Расширение

### Добавить новую сущность

1. Модель в `app/models.py`
2. Pydantic схемы в `app/schemas.py`
3. Router в `app/routers/имя.py` (по образцу `organizations.py`)
4. Подключить в `app/main.py` (`app.include_router(...)`)
5. Опционально — фронтенд: вкладка в `index.html` + загрузка в `app.js`

### Добавить новое поле в подписку

1. Колонка в `Subscription` (`models.py`)
2. Поле в `SubscriptionCreate/Out` (`schemas.py`)
3. Поле в форме (`index.html`)
4. Поле в `openSubForm` инициализации (`app.js`)
5. **Внимание**: для новых колонок в проде нужна миграция (или удалить БД и пересоздать в dev).

### Изменить дизайн без редактирования CSS

1. Залогиниться как admin
2. Открыть вкладку «Дизайн»
3. Настроить цвета через color picker
4. Нажать «Сохранить»

Для разработки удобнее редактировать `app/static/styles.css` напрямую и пересобирать через UI или `docker compose up -d --build`.

## Безопасность

- Пароли хешируются `bcrypt` (passlib)
- JWT подписывается секретом из `SECRET_KEY` env (обязательно менять в продакшене!)
- Cookie с токеном — `httponly` + `samesite=lax`
- CORS открыт (`*`) — допустимо т.к. через cookie, но в продакшене лучше ограничить
- Файловые загрузки сохраняются с UUID именами в `/app/data/uploads/`
- Endpoint обновления приложения требует admin-роль

## Известные ограничения

- Нет полноценных миграций БД (нужен Alembic при больших изменениях схемы)
- Нет восстановления из бэкапа `app_backup` через UI (только ручное)
- Один Docker-контейнер — без горизонтального масштабирования
- SQLite не подходит для большой нагрузки (>десятков RPS)
- Webhook'и шлются синхронно в cron — при большом числе подписок может тормозить
