"""Billing models for ShopEasy: sequence counter, individual Billing IDs, and engine claims."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import Programme, sql_enum

if TYPE_CHECKING:
    from app.models.order import Order, OrderItem
    from app.models.product import Product
    from app.models.user import User


class BillingCounter(Base):
    """Sequence counter for globally unique, contiguous Billing ID generation."""

    __tablename__ = "billing_counters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    current_value: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), default=200, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("sequence_name", name="uq_billing_counters_sequence_name"),
    )


class BillingId(Base):
    """Record of an allocated Billing ID per individual purchased product unit."""

    __tablename__ = "billing_ids"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    billing_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    sequence_number: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), unique=True, nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("orders.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    order_item_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("order_items.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    unit_index: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    programme: Mapped[Programme] = mapped_column(
        sql_enum(Programme),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), default="ALLOCATED", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("billing_number", name="uq_billing_ids_number"),
        UniqueConstraint("sequence_number", name="uq_billing_ids_sequence"),
        UniqueConstraint("order_item_id", "unit_index", name="uq_billing_ids_item_unit"),
        Index("idx_billing_ids_order_id", "order_id"),
        Index("idx_billing_ids_user_id", "user_id"),
        Index("idx_billing_ids_programme", "programme"),
    )

    order: Mapped["Order"] = relationship("Order", back_populates="billing_ids")
    order_item: Mapped["OrderItem"] = relationship("OrderItem", back_populates="billing_ids")
    user: Mapped["User"] = relationship("User")
    product: Mapped["Product"] = relationship("Product")
    engine_claim: Mapped[Optional["BillingEngineClaim"]] = relationship(
        "BillingEngineClaim", back_populates="billing_id_rel", uselist=False
    )


class BillingEngineClaim(Base):
    """Claim record routing a Billing ID to its designated programme commission/cashback engine."""

    __tablename__ = "billing_engine_claims"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    billing_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("billing_ids.id", onupdate="CASCADE", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    engine: Mapped[Programme] = mapped_column(
        sql_enum(Programme),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("billing_id", name="uq_billing_engine_claims_billing_id"),
        Index("idx_billing_engine_claims_engine_status", "engine", "status"),
    )

    billing_id_rel: Mapped["BillingId"] = relationship(
        "BillingId", back_populates="engine_claim"
    )
