from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime


# --- Auth ---
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


# --- User ---
class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str = ""
    role: str = "viewer"


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    is_active: bool

    class Config:
        from_attributes = True


# --- Organization ---
class OrganizationCreate(BaseModel):
    name: str
    inn: str = ""
    notes: str = ""


class OrganizationOut(OrganizationCreate):
    id: int

    class Config:
        from_attributes = True


# --- Contractor ---
class ContractorCreate(BaseModel):
    name: str
    inn: str = ""
    contact_info: str = ""
    website: str = ""
    logo_url: str = ""
    notes: str = ""


class ContractorOut(ContractorCreate):
    id: int

    class Config:
        from_attributes = True


# --- Employee ---
class EmployeeCreate(BaseModel):
    full_name: str
    position: str = ""
    email: str = ""
    phone: str = ""


class EmployeeOut(EmployeeCreate):
    id: int

    class Config:
        from_attributes = True


# --- Category ---
class CategoryCreate(BaseModel):
    name: str
    color: str = "#5ED0BD"
    icon: str = "📁"


class CategoryOut(CategoryCreate):
    id: int

    class Config:
        from_attributes = True


# --- Payment method ---
class PaymentMethodCreate(BaseModel):
    name: str
    details: str = ""
    icon: str = "💳"


class PaymentMethodOut(PaymentMethodCreate):
    id: int

    class Config:
        from_attributes = True


# --- Subscription ---
class SubscriptionCreate(BaseModel):
    name: str
    sub_type: str = "recurring"  # recurring, balance, onetime
    price: float = 0
    currency: str = "RUB"
    cycle: str = "monthly"
    frequency: int = 1
    next_payment: Optional[date] = None
    start_date: Optional[date] = None
    auto_renew: bool = True

    organization_id: Optional[int] = None
    contractor_id: Optional[int] = None
    employee_id: Optional[int] = None
    category_id: Optional[int] = None
    payment_method_id: Optional[int] = None

    balance: float = 0
    billing_day: int = 1
    min_balance: float = 0
    balance_api_url: str = ""
    balance_api_path: str = "balance"

    url: str = ""
    notes: str = ""
    logo: str = ""
    is_active: bool = True

    notify_enabled: bool = True
    notify_days_before: str = "3"
    notify_duration: str = "1"
    overdue_notify_after: str = "0"
    cancellation_date: Optional[date] = None


class SubscriptionUpdate(SubscriptionCreate):
    pass


class SubscriptionOut(BaseModel):
    id: int
    name: str
    sub_type: str
    price: float
    currency: str
    cycle: str
    frequency: int
    next_payment: Optional[date]
    start_date: Optional[date]
    auto_renew: bool

    organization_id: Optional[int]
    contractor_id: Optional[int]
    employee_id: Optional[int]
    category_id: Optional[int]
    payment_method_id: Optional[int]

    balance: float
    billing_day: int
    min_balance: float
    balance_api_url: str
    balance_api_path: str

    url: str
    notes: str
    logo: str
    is_active: bool

    notify_enabled: bool
    notify_days_before: str
    notify_duration: Optional[str] = "1"
    overdue_notify_after: Optional[str] = "0"
    cancellation_date: Optional[date] = None
    paid_until: Optional[date] = None

    organization: Optional[OrganizationOut] = None
    contractor: Optional[ContractorOut] = None
    employee: Optional[EmployeeOut] = None
    category: Optional[CategoryOut] = None
    payment_method: Optional[PaymentMethodOut] = None

    class Config:
        from_attributes = True


# --- Document ---
class DocumentCreate(BaseModel):
    subscription_id: int
    doc_type: str = "invoice"
    title: str
    filename: str
    doc_date: Optional[date] = None
    amount: float = 0
    notes: str = ""


class DocumentOut(BaseModel):
    id: int
    subscription_id: int
    doc_type: str
    title: str
    filename: str
    doc_date: Optional[date]
    amount: float
    notes: str
    uploaded_at: datetime

    class Config:
        from_attributes = True


# --- Webhook ---
class WebhookCreate(BaseModel):
    name: str = "Default"
    kind: str = "webhook"  # webhook | bitrix24 | email | telegram
    url: str = ""
    method: str = "POST"
    headers: str = "{}"
    payload_template: str = "{}"
    enabled: bool = True
    ignore_ssl: bool = False
    config: str = "{}"


class WebhookOut(WebhookCreate):
    id: int

    class Config:
        from_attributes = True
