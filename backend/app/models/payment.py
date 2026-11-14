"""Payment attempt and payment event models for ShopEasy."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import PaymentStatus, sql_enum

if TYPE_CHECKING:
    from app.models.order import Order


class PaymentAttempt(Base):
    """Tracks distinct payment attempts per customer purchase order."""

    __tablename__ = "payment_attempts"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("orders.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        sql_enum(PaymentStatus),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    provider_transaction_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("attempt_reference", name="uq_payment_attempts_reference"),
        Index("idx_payment_attempts_order_id", "order_id"),
        Index("idx_payment_attempts_status_expires", "status", "expires_at"),
    )

    order: Mapped["Order"] = relationship("Order", back_populates="payment_attempts")


class PaymentEvent(Base):
    """Append-only audit and idempotency journal of inbound payment provider events/webhooks."""

    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("orders.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=True,
    )
    payment_attempt_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("payment_attempts.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=True,
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="RECEIVED", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_payment_events_provider_event_id"),
        Index("idx_payment_events_order_id", "order_id"),
    )

    order: Mapped[Optional["Order"]] = relationship("Order")
    payment_attempt: Mapped[Optional["PaymentAttempt"]] = relationship("PaymentAttempt")
