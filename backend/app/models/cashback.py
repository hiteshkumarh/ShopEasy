"""Plan A Cashback Engine models for Arya Global Digital dual-plan platform (WP-10).

Models:
- PlanACashbackQueue: Isolated independent FIFO queue for a Plan A referral-root hierarchy (BR-A2).
- PlanACashbackEntry: Monotonic queue entry per eligible purchased Power Bank Billing ID (BR-A1, BR-A3).
- PlanACashbackCycle: 16-contribution (₹4,000) earning cycle for an active recipient Billing ID (PA-09, PA-10).
- PlanACashbackContribution: Audit ledger of individual ₹250 contributions linked to Billing IDs (BR-A1, BR-A3).
- PlanAUnallocatedCashbackReserve: Permanent company-owned reserve for initial new-queue contributions (BR-A4 Option A)
  and active-recipient own-purchase contributions (BR-A5 Option A).
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
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

if TYPE_CHECKING:
    from app.models.billing import BillingId
    from app.models.user import User


class PlanACashbackQueue(Base):
    """Independent FIFO cashback queue rooted at a customer without an active Plan A referrer (BR-A2)."""

    __tablename__ = "plan_a_cashback_queues"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    root_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    active_cycle_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        nullable=True,
    )
    last_allocated_position: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("root_user_id", name="uq_plan_a_cb_queue_root_user"),
        Index("idx_plan_a_cb_queue_active_cycle", "active_cycle_id"),
    )

    root_user: Mapped["User"] = relationship("User", foreign_keys=[root_user_id])
    entries: Mapped[List["PlanACashbackEntry"]] = relationship(
        "PlanACashbackEntry",
        back_populates="queue",
        cascade="all, delete-orphan",
        foreign_keys="[PlanACashbackEntry.queue_id]",
    )
    cycles: Mapped[List["PlanACashbackCycle"]] = relationship(
        "PlanACashbackCycle",
        back_populates="queue",
        cascade="all, delete-orphan",
        foreign_keys="[PlanACashbackCycle.queue_id]",
    )
    contributions: Mapped[List["PlanACashbackContribution"]] = relationship(
        "PlanACashbackContribution",
        back_populates="queue",
        foreign_keys="[PlanACashbackContribution.queue_id]",
    )
    reserves: Mapped[List["PlanAUnallocatedCashbackReserve"]] = relationship(
        "PlanAUnallocatedCashbackReserve",
        back_populates="queue",
        foreign_keys="[PlanAUnallocatedCashbackReserve.queue_id]",
    )


class PlanACashbackEntry(Base):
    """Monotonic queue position assigned to an eligible Plan A Billing ID (BR-A1, BR-A2, BR-A3)."""

    __tablename__ = "plan_a_cashback_entries"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    queue_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("plan_a_cashback_queues.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    billing_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("billing_ids.id", onupdate="CASCADE", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    queue_position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="WAITING", nullable=False)  # WAITING, ACTIVE, COMPLETED
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("billing_id", name="uq_plan_a_cb_entry_billing_id"),
        UniqueConstraint("queue_id", "queue_position", name="uq_plan_a_cb_entry_queue_pos"),
        Index("idx_plan_a_cb_entry_user_status", "user_id", "status"),
        Index("idx_plan_a_cb_entry_queue_status", "queue_id", "status"),
    )

    queue: Mapped["PlanACashbackQueue"] = relationship("PlanACashbackQueue", back_populates="entries")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    billing: Mapped["BillingId"] = relationship("BillingId", foreign_keys=[billing_id])
    cycle: Mapped[Optional["PlanACashbackCycle"]] = relationship(
        "PlanACashbackCycle",
        back_populates="queue_entry",
        uselist=False,
        foreign_keys="[PlanACashbackCycle.queue_entry_id]",
    )


class PlanACashbackCycle(Base):
    """16-contribution (₹4,000) earning cycle tracking for an active recipient Billing ID."""

    __tablename__ = "plan_a_cashback_cycles"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    queue_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("plan_a_cashback_queues.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    queue_entry_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("plan_a_cashback_entries.id", onupdate="CASCADE", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    recipient_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    recipient_billing_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("billing_ids.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    cycle_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    completed_contributions: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    total_earned: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)  # ACTIVE, COMPLETED
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("queue_entry_id", name="uq_plan_a_cb_cycle_queue_entry"),
        CheckConstraint(
            "completed_contributions >= 0 AND completed_contributions <= 16",
            name="chk_plan_a_cb_cycle_contributions",
        ),
        CheckConstraint(
            "total_earned >= 0.00 AND total_earned <= 4000.00",
            name="chk_plan_a_cb_cycle_total_earned",
        ),
        Index("idx_plan_a_cb_cycle_recipient_status", "recipient_user_id", "status"),
        Index("idx_plan_a_cb_cycle_queue_status", "queue_id", "status"),
    )

    queue: Mapped["PlanACashbackQueue"] = relationship("PlanACashbackQueue", back_populates="cycles")
    queue_entry: Mapped["PlanACashbackEntry"] = relationship("PlanACashbackEntry", back_populates="cycle")
    recipient_user: Mapped["User"] = relationship("User", foreign_keys=[recipient_user_id])
    recipient_billing: Mapped["BillingId"] = relationship("BillingId", foreign_keys=[recipient_billing_id])
    contributions: Mapped[List["PlanACashbackContribution"]] = relationship(
        "PlanACashbackContribution",
        back_populates="cycle",
        foreign_keys="[PlanACashbackContribution.cycle_id]",
    )


class PlanACashbackContribution(Base):
    """Audit ledger recording each ₹250 contribution event per eligible Billing ID (BR-A1, BR-A3)."""

    __tablename__ = "plan_a_cashback_contributions"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    queue_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("plan_a_cashback_queues.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    cycle_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("plan_a_cashback_cycles.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=True,
    )
    contributing_billing_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("billing_ids.id", onupdate="CASCADE", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    contributing_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    recipient_user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("250.00"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="ALLOCATED", nullable=False)  # ALLOCATED, UNALLOCATED_COMPANY_RESERVE
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("contributing_billing_id", name="uq_plan_a_cb_contrib_billing_id"),
        UniqueConstraint("idempotency_key", name="uq_plan_a_cb_contrib_idempotency"),
        Index("idx_plan_a_cb_contrib_cycle", "cycle_id"),
        Index("idx_plan_a_cb_contrib_queue_user", "queue_id", "contributing_user_id"),
    )

    queue: Mapped["PlanACashbackQueue"] = relationship("PlanACashbackQueue", back_populates="contributions")
    cycle: Mapped[Optional["PlanACashbackCycle"]] = relationship("PlanACashbackCycle", back_populates="contributions")
    contributing_billing: Mapped["BillingId"] = relationship("BillingId", foreign_keys=[contributing_billing_id])
    contributing_user: Mapped["User"] = relationship("User", foreign_keys=[contributing_user_id])
    recipient_user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[recipient_user_id])


class PlanAUnallocatedCashbackReserve(Base):
    """Permanent company-owned unallocated cashback reserve (BR-A4 Option A & BR-A5 Option A).

    Invariants:
    1. Initial queue contribution without an active recipient ahead is retained permanently (BR-A4 Option A).
    2. Active recipient's own subsequent purchase contribution is retained permanently (BR-A5 Option A).
    3. Never credited to customer wallets or released through queue progression.
    4. Traceable financial record: Billing ID, customer ID, queue ID, amount, timestamp, status.
    """

    __tablename__ = "plan_a_unallocated_cashback_reserves"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    queue_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("plan_a_cashback_queues.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    billing_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("billing_ids.id", onupdate="CASCADE", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("250.00"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(64), default="UNALLOCATED — COMPANY OWNED", nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("billing_id", name="uq_plan_a_cb_res_billing_id"),
        UniqueConstraint("idempotency_key", name="uq_plan_a_cb_res_idempotency"),
        Index("idx_plan_a_cb_res_queue", "queue_id"),
        Index("idx_plan_a_cb_res_customer", "customer_id"),
    )

    queue: Mapped["PlanACashbackQueue"] = relationship("PlanACashbackQueue", back_populates="reserves")
    billing: Mapped["BillingId"] = relationship("BillingId", foreign_keys=[billing_id])
    customer: Mapped["User"] = relationship("User", foreign_keys=[customer_id])

