from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.billing import BillingId
    from app.models.order import Order
    from app.models.queue import CommissionCycle
    from app.models.user import User


class SequentialCommission(Base):
    """Sequential ₹250 commission credited to the single currently active beneficiary."""

    __tablename__ = "sequential_commissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_id: Mapped[int] = mapped_column(Integer, nullable=False)
    beneficiary_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("orders.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    commission_number: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("250.00"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source_order_id", name="uq_seq_comm_order"),
        UniqueConstraint("cycle_id", "commission_number", name="uq_seq_comm_cycle_num"),
        CheckConstraint("commission_number BETWEEN 1 AND 16", name="chk_seq_comm_number"),
        CheckConstraint("amount = 250.00", name="chk_seq_comm_amount"),
        # Composite FK: guarantees credited user owns the commission cycle
        ForeignKeyConstraint(
            ["cycle_id", "beneficiary_id"],
            ["commission_cycles.id", "commission_cycles.beneficiary_id"],
            name="fk_seq_comm_cycle_beneficiary",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        # Foreign key directly ensuring beneficiary exists in users
        ForeignKeyConstraint(
            ["beneficiary_id"],
            ["users.id"],
            name="fk_seq_comm_beneficiary",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
    )

    cycle: Mapped["CommissionCycle"] = relationship(
        "CommissionCycle",
        back_populates="sequential_commissions",
        foreign_keys="[SequentialCommission.cycle_id, SequentialCommission.beneficiary_id]",
        overlaps="beneficiary,sequential_commissions",
    )
    beneficiary: Mapped["User"] = relationship(
        "User",
        back_populates="sequential_commissions",
        foreign_keys="[SequentialCommission.beneficiary_id]",
        overlaps="cycle,sequential_commissions",
    )
    source_order: Mapped["Order"] = relationship(
        "Order",
        back_populates="sequential_commission",
        foreign_keys="[SequentialCommission.source_order_id]",
    )


class ReferralCommission(Base):
    """One-time ₹750 direct referral reward credited on referee's first successful order."""

    __tablename__ = "referral_commissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
    )
    referee_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
    )
    source_order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("orders.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("750.00"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("referee_id", name="uq_ref_comm_referee"),
        UniqueConstraint("source_order_id", name="uq_ref_comm_order"),
        CheckConstraint("referrer_id != referee_id", name="chk_ref_comm_no_self"),
        CheckConstraint("amount = 750.00", name="chk_ref_comm_amount"),
    )

    referrer: Mapped["User"] = relationship(
        "User",
        back_populates="referrals_as_referrer",
        foreign_keys="[ReferralCommission.referrer_id]",
    )
    referee: Mapped["User"] = relationship(
        "User",
        back_populates="referrals_as_referee",
        foreign_keys="[ReferralCommission.referee_id]",
    )
    source_order: Mapped["Order"] = relationship(
        "Order",
        back_populates="referral_commission",
        foreign_keys="[ReferralCommission.source_order_id]",
    )


class PlanACommission(Base):
    """Direct referral commission record per Plan A Billing ID (WP-7)."""

    __tablename__ = "plan_a_commissions"

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
    order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("orders.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    purchaser_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    referrer_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=True,
    )
    applied_referral_code: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    gross_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("750.00"), nullable=False
    )
    operational_cost_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    tds_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    net_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "EARNED", "UNALLOCATED_NO_REFERRER", "INELIGIBLE_REFERRER"
    idempotency_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("billing_id", name="uq_plan_a_comm_billing_id"),
        UniqueConstraint("idempotency_key", name="uq_plan_a_comm_idempotency"),
        Index("idx_plan_a_comm_referrer_status", "referrer_id", "status"),
        Index("idx_plan_a_comm_order_id", "order_id"),
    )

    billing_id_rel: Mapped["BillingId"] = relationship("BillingId")
    order: Mapped["Order"] = relationship("Order")
    purchaser: Mapped["User"] = relationship("User", foreign_keys="[PlanACommission.purchaser_id]")
    referrer: Mapped[Optional["User"]] = relationship("User", foreign_keys="[PlanACommission.referrer_id]")


class PlanBCommission(Base):
    """Direct referral and generation commissions earned by Plan B distributors (WP-8)."""

    __tablename__ = "plan_b_commissions"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    commission_type: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # "DIRECT" or "GENERATION"
    distributor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    referee_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("orders.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    billing_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("billing_ids.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=True,
    )
    gross_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    operational_cost_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    tds_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    net_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="EARNED", nullable=False
    )  # "EARNED", "INELIGIBLE_DISTRIBUTOR"
    idempotency_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_plan_b_comm_idempotency"),
        Index("idx_plan_b_comm_distributor_status", "distributor_id", "status"),
        Index("idx_plan_b_comm_order_id", "order_id"),
        Index("idx_plan_b_comm_billing_id", "billing_id"),
    )

    distributor: Mapped["User"] = relationship("User", foreign_keys="[PlanBCommission.distributor_id]")
    referee: Mapped["User"] = relationship("User", foreign_keys="[PlanBCommission.referee_id]")
    order: Mapped["Order"] = relationship("Order")
    billing_id_rel: Mapped[Optional["BillingId"]] = relationship("BillingId")
