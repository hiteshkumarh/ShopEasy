from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import CycleStatus, QueueStatus, sql_enum

if TYPE_CHECKING:
    from app.models.commission import SequentialCommission
    from app.models.user import User


class BeneficiaryQueue(Base):
    """Global sequential FIFO beneficiary queue."""

    __tablename__ = "beneficiary_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    queue_position: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    status: Mapped[QueueStatus] = mapped_column(
        sql_enum(QueueStatus), default=QueueStatus.WAITING, nullable=False
    )

    # Generated column: evaluates to 1 when active, NULL otherwise
    active_flag: Mapped[Optional[int]] = mapped_column(
        Integer,
        Computed("CASE WHEN status = 'active' THEN 1 ELSE NULL END", persisted=True),
        nullable=True,
    )

    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_queue_user"),
        UniqueConstraint("queue_position", name="uq_queue_position"),
        UniqueConstraint("active_flag", name="uq_queue_active_singleton"),
        UniqueConstraint("id", "user_id", name="uq_queue_id_user"),
    )

    user: Mapped["User"] = relationship("User", back_populates="beneficiary_queue_entry")
    commission_cycles: Mapped[List["CommissionCycle"]] = relationship(
        "CommissionCycle",
        back_populates="queue_entry",
        foreign_keys="[CommissionCycle.queue_entry_id, CommissionCycle.beneficiary_id]",
        overlaps="beneficiary",
    )


class CommissionCycle(Base):
    """Lifetime 16-commission cycle tracking for an enrolled customer."""

    __tablename__ = "commission_cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_entry_id: Mapped[int] = mapped_column(Integer, nullable=False)
    beneficiary_id: Mapped[int] = mapped_column(Integer, nullable=False)
    cycle_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[CycleStatus] = mapped_column(
        sql_enum(CycleStatus), default=CycleStatus.ACTIVE, nullable=False
    )

    # Generated column: evaluates to 1 when active, NULL otherwise
    active_flag: Mapped[Optional[int]] = mapped_column(
        Integer,
        Computed("CASE WHEN status = 'active' THEN 1 ELSE NULL END", persisted=True),
        nullable=True,
    )

    completed_commissions: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    total_earned: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        # Mandatory: Exactly one lifetime cycle per customer
        UniqueConstraint("beneficiary_id", name="uq_cycles_beneficiary_lifetime"),
        CheckConstraint("cycle_number = 1", name="chk_cycles_cycle_number_is_one"),
        UniqueConstraint("active_flag", name="uq_cycles_active_singleton"),
        UniqueConstraint("id", "beneficiary_id", "status", name="uq_cycle_composite"),
        UniqueConstraint("id", "beneficiary_id", name="uq_cycles_id_beneficiary"),
        CheckConstraint(
            "completed_commissions BETWEEN 0 AND 16", name="chk_cycles_max_commissions"
        ),
        CheckConstraint(
            "total_earned = (completed_commissions * 250.00)",
            name="chk_cycles_total_earned",
        ),
        ForeignKeyConstraint(
            ["queue_entry_id", "beneficiary_id"],
            ["beneficiary_queue.id", "beneficiary_queue.user_id"],
            name="fk_cycles_queue_entry_user",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["beneficiary_id"],
            ["users.id"],
            name="fk_cycles_beneficiary",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
    )

    queue_entry: Mapped["BeneficiaryQueue"] = relationship(
        "BeneficiaryQueue",
        back_populates="commission_cycles",
        foreign_keys="[CommissionCycle.queue_entry_id, CommissionCycle.beneficiary_id]",
    )
    beneficiary: Mapped["User"] = relationship(
        "User",
        back_populates="commission_cycles",
        foreign_keys="[CommissionCycle.beneficiary_id]",
        overlaps="commission_cycles,queue_entry",
    )
    sequential_commissions: Mapped[List["SequentialCommission"]] = relationship(
        "SequentialCommission",
        back_populates="cycle",
        foreign_keys="[SequentialCommission.cycle_id, SequentialCommission.beneficiary_id]",
        overlaps="beneficiary",
    )
    queue_control: Mapped[Optional["QueueControl"]] = relationship(
        "QueueControl",
        back_populates="active_cycle",
        foreign_keys="[QueueControl.active_cycle_id, QueueControl.active_beneficiary_id, QueueControl.active_cycle_status]",
        uselist=False,
    )


class QueueControl(Base):
    """Singleton queue controller (id=1) tracking active beneficiary and sequence pointer."""

    __tablename__ = "queue_control"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    active_cycle_id: Mapped[Optional[int]] = mapped_column(
        Integer, unique=True, nullable=True
    )
    active_beneficiary_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    active_cycle_status: Mapped[Optional[CycleStatus]] = mapped_column(
        sql_enum(CycleStatus), nullable=True
    )
    last_allocated_position: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("active_cycle_id", name="uq_queue_control_active_cycle"),
        CheckConstraint("id = 1", name="chk_queue_control_singleton"),
        CheckConstraint(
            "(active_cycle_id IS NULL AND active_beneficiary_id IS NULL AND active_cycle_status IS NULL) OR "
            "(active_cycle_id IS NOT NULL AND active_beneficiary_id IS NOT NULL AND active_cycle_status = 'active')",
            name="chk_qc_active_triple",
        ),
        ForeignKeyConstraint(
            ["active_cycle_id", "active_beneficiary_id", "active_cycle_status"],
            [
                "commission_cycles.id",
                "commission_cycles.beneficiary_id",
                "commission_cycles.status",
            ],
            name="fk_qc_active_cycle",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
    )

    active_cycle: Mapped[Optional["CommissionCycle"]] = relationship(
        "CommissionCycle",
        back_populates="queue_control",
        foreign_keys="[QueueControl.active_cycle_id, QueueControl.active_beneficiary_id, QueueControl.active_cycle_status]",
    )
