from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text, Date
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(200), default="")
    role = Column(String(20), default="viewer")  # admin, manager, viewer
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class Organization(Base):
    __tablename__ = "organizations"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    inn = Column(String(20), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    subscriptions = relationship("Subscription", back_populates="organization")


class Contractor(Base):
    __tablename__ = "contractors"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    inn = Column(String(20), default="")
    contact_info = Column(Text, default="")
    website = Column(String(500), default="")
    logo_url = Column(String(500), default="")
    notes = Column(Text, default="")

    subscriptions = relationship("Subscription", back_populates="contractor")


class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    full_name = Column(String(200), nullable=False)
    position = Column(String(200), default="")
    email = Column(String(200), default="")
    phone = Column(String(50), default="")

    subscriptions = relationship("Subscription", back_populates="employee")


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    color = Column(String(20), default="#5ED0BD")
    icon = Column(String(50), default="📁")

    subscriptions = relationship("Subscription", back_populates="category")


class PaymentMethod(Base):
    __tablename__ = "payment_methods"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    details = Column(Text, default="")
    icon = Column(String(50), default="💳")

    subscriptions = relationship("Subscription", back_populates="payment_method")


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    sub_type = Column(String(20), default="recurring")  # recurring, balance, onetime
    price = Column(Float, default=0)
    currency = Column(String(10), default="RUB")

    cycle = Column(String(20), default="monthly")
    frequency = Column(Integer, default=1)
    next_payment = Column(Date)
    start_date = Column(Date)
    auto_renew = Column(Boolean, default=True)

    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    contractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    payment_method_id = Column(Integer, ForeignKey("payment_methods.id"), nullable=True)

    balance = Column(Float, default=0)
    last_balance_update = Column(Date, nullable=True)
    last_low_balance_notify = Column(Date, nullable=True)
    billing_day = Column(Integer, default=1)
    min_balance = Column(Float, default=0)
    balance_api_url = Column(String(500), default="")
    balance_api_path = Column(String(100), default="balance")

    url = Column(String(500), default="")
    notes = Column(Text, default="")
    logo = Column(String(500), default="")
    is_active = Column(Boolean, default=True)

    # Уведомления (на каждую подписку)
    notify_enabled = Column(Boolean, default=True)
    # Список дней «до события» через запятую: "0,1,3,7" — за столько дней до next_payment слать напоминание
    notify_days_before = Column(String(100), default="3")
    # Сколько дней подряд напоминать, начиная со старта (за notify_days_before дней до платежа)
    notify_duration = Column(String(50), default="1")
    # Через сколько дней ПОСЛЕ платежа напомнить о просрочке, если не отмечено «Продлено». 0 = не напоминать.
    overdue_notify_after = Column(String(50), default="0")
    # Дата платежа, для которого уже отправлено напоминание (чтобы не слать дважды и догонять пропущенные)
    last_payment_notify_for = Column(Date, nullable=True)
    # Дата платежа, который пользователь отметил как «оплачено вручную» (Продлено)
    paid_until = Column(Date, nullable=True)
    # Дата отмены подписки (опционально)
    cancellation_date = Column(Date, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization", back_populates="subscriptions")
    contractor = relationship("Contractor", back_populates="subscriptions")
    employee = relationship("Employee", back_populates="subscriptions")
    category = relationship("Category", back_populates="subscriptions")
    payment_method = relationship("PaymentMethod", back_populates="subscriptions")
    documents = relationship("Document", back_populates="subscription", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False)
    doc_type = Column(String(50), default="invoice")
    title = Column(String(255), nullable=False)
    filename = Column(String(500), nullable=False)
    doc_date = Column(Date, nullable=True)
    amount = Column(Float, default=0)
    notes = Column(Text, default="")
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    subscription = relationship("Subscription", back_populates="documents")


class WebhookConfig(Base):
    __tablename__ = "webhook_configs"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), default="Default")
    # Тип канала: webhook | bitrix24 | email | telegram
    kind = Column(String(20), default="webhook")
    url = Column(String(500), default="")
    method = Column(String(10), default="POST")
    headers = Column(Text, default="{}")
    payload_template = Column(Text, default="{}")
    enabled = Column(Boolean, default=True)
    ignore_ssl = Column(Boolean, default=False)
    # JSON c доп. настройками канала: SMTP-параметры, telegram-токен и т.п.
    config = Column(Text, default="{}")


class NotificationLog(Base):
    __tablename__ = "notification_log"
    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"))
    event_type = Column(String(50))
    message = Column(Text)
    sent_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)
