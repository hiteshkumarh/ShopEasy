from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
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
from app.models.enums import (
    WalletReferenceType,
    WalletTransactionType,
    WalletType,
    WithdrawalStatus,
    sql_enum,
)

if TYPE_CHECKING:
    from app.models.user import User


class Wallet(Base):
    """Isolated customer earning balances (Direct Referral or Sequential Commission)."""

    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    wallet_type: Mapped[WalletType] = mapped_column(
        sql_enum(WalletType), nullable=False
    )
    balance: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    total_withdrawn: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "wallet_type", name="uq_wallets_user_type"),
        UniqueConstraint("id", "user_id", "wallet_type", name="uq_wallets_id_user_type"),
        # Composite unique key required for withdrawal composite FK (enforcing wallet ownership)
        UniqueConstraint("id", "user_id", name="uq_wallets_id_user"),
        CheckConstraint("balance >= 0.00", name="chk_wallets_balance_non_negative"),
        CheckConstraint(
            "total_withdrawn >= 0.00", name="chk_wallets_withdrawn_non_negative"
        ),
    )

    user: Mapped["User"] = relationship("User", back_populates="wallets")
    transactions: Mapped[List["WalletTransaction"]] = relationship(
        "WalletTransaction",
        back_populates="wallet",
        foreign_keys="[WalletTransaction.wallet_id, WalletTransaction.user_id, WalletTransaction.wallet_type]",
    )
    withdrawals: Mapped[List["Withdrawal"]] = relationship(
        "Withdrawal",
        back_populates="wallet",
        foreign_keys="[Withdrawal.wallet_id, Withdrawal.user_id]",
        overlaps="user,withdrawals",
    )


class WalletTransaction(Base):
    """Immutable auditable ledger entries for wallet credit and debit events."""

    __tablename__ = "wallet_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    wallet_type: Mapped[WalletType] = mapped_column(
        sql_enum(WalletType), nullable=False
    )
    transaction_type: Mapped[WalletTransactionType] = mapped_column(
        sql_enum(WalletTransactionType), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    reference_type: Mapped[WalletReferenceType] = mapped_column(
        sql_enum(WalletReferenceType), nullable=False
    )
    reference_id: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_wallet_tx_idempotency"),
        CheckConstraint("amount > 0.00", name="chk_wallet_tx_amount_positive"),
        CheckConstraint(
            "balance_after >= 0.00", name="chk_wallet_tx_balance_non_negative"
        ),
        # Composite FK: guarantees wallet ownership and type consistency
        ForeignKeyConstraint(
            ["wallet_id", "user_id", "wallet_type"],
            ["wallets.id", "wallets.user_id", "wallets.wallet_type"],
            name="fk_wallet_tx_wallet_composite",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        # Foreign key ensuring user exists in users
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_wallet_tx_user",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        Index("idx_wallet_tx_reference", "reference_type", "reference_id"),
    )

    wallet: Mapped["Wallet"] = relationship(
        "Wallet",
        back_populates="transactions",
        foreign_keys="[WalletTransaction.wallet_id, WalletTransaction.user_id, WalletTransaction.wallet_type]",
    )


class Withdrawal(Base):
    """Simulated full-balance payouts."""

    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[WithdrawalStatus] = mapped_column(
        sql_enum(WithdrawalStatus),
        default=WithdrawalStatus.COMPLETED,
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Customer-scoped idempotency
        UniqueConstraint("user_id", "idempotency_key", name="uq_withdrawals_user_idempotency"),
        CheckConstraint("amount > 0.00", name="chk_withdrawals_amount_positive"),
        # Composite FK: ensures wallet belongs to user
        ForeignKeyConstraint(
            ["wallet_id", "user_id"],
            ["wallets.id", "wallets.user_id"],
            name="fk_withdrawals_wallet_user",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_withdrawals_user",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
    )

    wallet: Mapped["Wallet"] = relationship(
        "Wallet",
        back_populates="withdrawals",
        foreign_keys="[Withdrawal.wallet_id, Withdrawal.user_id]",
        overlaps="user,withdrawals",
    )
    user: Mapped["User"] = relationship(
        "User",
        back_populates="withdrawals",
        foreign_keys="[Withdrawal.user_id]",
        overlaps="wallet,withdrawals",
    )

    @property
    def wallet_type(self) -> Optional[WalletType]:
        return self.wallet.wallet_type if self.wallet else None
