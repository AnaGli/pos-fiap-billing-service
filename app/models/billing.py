import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CatalogItemType(str, enum.Enum):
    SERVICE = "SERVICE"
    PART = "PART"


class BudgetStatus(str, enum.Enum):
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REFUNDED = "REFUNDED"


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    item_type: Mapped[CatalogItemType] = mapped_column(Enum(CatalogItemType), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(unique=True, nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[BudgetStatus] = mapped_column(Enum(BudgetStatus), nullable=False, default=BudgetStatus.WAITING_APPROVAL)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    items = relationship("BudgetItem", back_populates="budget", cascade="all, delete-orphan", order_by="BudgetItem.id")
    payments = relationship("Payment", back_populates="budget", cascade="all, delete-orphan", order_by="Payment.id")
    refunds = relationship("Refund", back_populates="budget", cascade="all, delete-orphan", order_by="Refund.id")


class BudgetItem(Base):
    __tablename__ = "budget_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id"), nullable=False)
    item_code: Mapped[str] = mapped_column(String(100), nullable=False)
    item_name: Mapped[str] = mapped_column(String(100), nullable=False)
    item_type: Mapped[CatalogItemType] = mapped_column(Enum(CatalogItemType), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    budget = relationship("Budget", back_populates="items")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="MERCADO_PAGO")
    provider_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_payment_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_method_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_status_detail: Mapped[str | None] = mapped_column(String(100), nullable=True)
    qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_code_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    ticket_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.APPROVED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    budget = relationship("Budget", back_populates="payments")


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    budget = relationship("Budget", back_populates="refunds")
