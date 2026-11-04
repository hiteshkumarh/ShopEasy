from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import (
    AllocationScenario,
    OrderStatus,
    PaymentStatus,
    sql_enum,
)

if TYPE_CHECKING:
    from app.models.commission import ReferralCommission, SequentialCommission
    from app.models.product import Product
    from app.models.user import Address, User


class Order(Base):
    """Customer purchase order records."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    address_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("addresses.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    order_status: Mapped[OrderStatus] = mapped_column(
        sql_enum(OrderStatus),
        default=OrderStatus.PENDING_PAYMENT,
        nullable=False,
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        sql_enum(PaymentStatus),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    payment_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    applied_referral_code: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    is_first_successful_order: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("order_number", name="uq_orders_order_number"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_orders_user_idempotency"),
        Index("idx_orders_user_status", "user_id", "order_status"),
    )

    user: Mapped["User"] = relationship("User", back_populates="orders")
    address: Mapped["Address"] = relationship("Address", back_populates="orders")
    order_items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    order_allocation: Mapped[Optional["OrderAllocation"]] = relationship(
        "OrderAllocation", back_populates="order", uselist=False
    )
    sequential_commission: Mapped[Optional["SequentialCommission"]] = relationship(
        "SequentialCommission",
        back_populates="source_order",
        foreign_keys="[SequentialCommission.source_order_id]",
        uselist=False,
    )
    referral_commission: Mapped[Optional["ReferralCommission"]] = relationship(
        "ReferralCommission",
        back_populates="source_order",
        foreign_keys="[ReferralCommission.source_order_id]",
        uselist=False,
    )


class OrderItem(Base):
    """Line items within a customer order."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("orders.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="chk_order_items_qty_positive"),
    )

    order: Mapped["Order"] = relationship("Order", back_populates="order_items")
    product: Mapped["Product"] = relationship("Product", back_populates="order_items")


class OrderAllocation(Base):
    """Immutable financial snapshot recorded for each placed order."""

    __tablename__ = "order_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("orders.id", onupdate="CASCADE", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    scenario: Mapped[AllocationScenario] = mapped_column(
        sql_enum(AllocationScenario), nullable=False
    )
    power_bank_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    order_total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Power Bank regular cost reserve allocations
    product_import_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    output_gst: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    packing_courier: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    gift_achievement: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    office_staff: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )

    # Conditional rewards
    direct_referral_reward: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    sequential_commission: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )

    # Summary totals
    total_allocated: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    remaining_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("order_id", name="uq_order_allocations_order"),
        CheckConstraint("power_bank_quantity >= 0", name="chk_allocations_pb_qty"),
        CheckConstraint(
            "product_import_cost = (power_bank_quantity * 1500.00) AND "
            "output_gst = (power_bank_quantity * 400.00) AND "
            "packing_courier = (power_bank_quantity * 150.00) AND "
            "gift_achievement = (power_bank_quantity * 150.00) AND "
            "office_staff = (power_bank_quantity * 100.00)",
            name="chk_allocations_pb_scaling",
        ),
        CheckConstraint(
            "direct_referral_reward IN (0.00, 750.00) AND "
            "sequential_commission IN (0.00, 250.00)",
            name="chk_allocations_rewards",
        ),
        CheckConstraint(
            "total_allocated = (product_import_cost + output_gst + packing_courier + "
            "gift_achievement + office_staff + direct_referral_reward + sequential_commission)",
            name="chk_allocations_sum",
        ),
        CheckConstraint(
            "remaining_amount = (order_total_amount - total_allocated)",
            name="chk_allocations_remaining",
        ),
        CheckConstraint(
            "total_allocated <= order_total_amount AND remaining_amount >= 0.00",
            name="chk_allocations_solvency",
        ),
    )

    order: Mapped["Order"] = relationship("Order", back_populates="order_allocation")
