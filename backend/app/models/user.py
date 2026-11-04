from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import OTPPurpose, UserRole, sql_enum

if TYPE_CHECKING:
    from app.models.commission import ReferralCommission, SequentialCommission
    from app.models.order import Order
    from app.models.queue import BeneficiaryQueue, CommissionCycle
    from app.models.wallet import Wallet, Withdrawal


class User(Base):
    """Customer and pre-provisioned administrator accounts."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(15), unique=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        sql_enum(UserRole), default=UserRole.CUSTOMER, nullable=False
    )
    referral_code: Mapped[Optional[str]] = mapped_column(
        String(20), unique=True, nullable=True
    )
    referred_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("phone", name="uq_users_phone"),
        UniqueConstraint("referral_code", name="uq_users_referral_code"),
        CheckConstraint(
            "(role = 'customer' AND referral_code IS NOT NULL) OR "
            "(role = 'admin' AND referral_code IS NULL AND referred_by_id IS NULL)",
            name="chk_user_role_referral",
        ),
        CheckConstraint("referred_by_id != id", name="chk_users_no_self_referral"),
    )

    # Self-referential relationship (Referrer <-> Referees)
    referrer: Mapped[Optional["User"]] = relationship(
        "User", remote_side="[User.id]", back_populates="referees"
    )
    referees: Mapped[List["User"]] = relationship("User", back_populates="referrer")

    # Domain relationships
    addresses: Mapped[List["Address"]] = relationship("Address", back_populates="user")
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="user")
    beneficiary_queue_entry: Mapped[Optional["BeneficiaryQueue"]] = relationship(
        "BeneficiaryQueue", back_populates="user", uselist=False
    )
    commission_cycles: Mapped[List["CommissionCycle"]] = relationship(
        "CommissionCycle",
        back_populates="beneficiary",
        foreign_keys="[CommissionCycle.beneficiary_id]",
        overlaps="commission_cycles,queue_entry",
    )
    wallets: Mapped[List["Wallet"]] = relationship("Wallet", back_populates="user")
    withdrawals: Mapped[List["Withdrawal"]] = relationship(
        "Withdrawal",
        back_populates="user",
        foreign_keys="[Withdrawal.user_id]",
        overlaps="wallet,withdrawals",
    )
    referrals_as_referrer: Mapped[List["ReferralCommission"]] = relationship(
        "ReferralCommission",
        back_populates="referrer",
        foreign_keys="[ReferralCommission.referrer_id]",
    )
    referrals_as_referee: Mapped[Optional["ReferralCommission"]] = relationship(
        "ReferralCommission",
        back_populates="referee",
        foreign_keys="[ReferralCommission.referee_id]",
        uselist=False,
    )
    sequential_commissions: Mapped[List["SequentialCommission"]] = relationship(
        "SequentialCommission",
        back_populates="beneficiary",
        foreign_keys="[SequentialCommission.beneficiary_id]",
        overlaps="cycle,sequential_commissions",
    )


class OTP(Base):
    """Transient one-time passwords for authentication."""

    __tablename__ = "otps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    otp_code: Mapped[str] = mapped_column(String(10), nullable=False)
    purpose: Mapped[OTPPurpose] = mapped_column(
        sql_enum(OTPPurpose), nullable=False
    )
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_otps_phone_purpose", "phone", "purpose", "is_used", "expires_at"),
    )


class Address(Base):
    """Customer delivery addresses."""

    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    recipient_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    address_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    pincode: Mapped[str] = mapped_column(String(10), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("idx_addresses_user", "user_id"),)

    user: Mapped["User"] = relationship("User", back_populates="addresses")
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="address")
