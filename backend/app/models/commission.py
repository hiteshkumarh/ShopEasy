from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
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
