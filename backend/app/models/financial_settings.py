"""SQLAlchemy models for versioned, effective-dated financial settings.

Supports:
  - Programme isolation (PLAN_A vs PLAN_B).
  - Explicit currency and high-precision Decimal rates and monetary amounts.
  - Immutable version tracking per (programme, setting_key).
  - Effective-from and effective-to timestamps for historical auditability.
  - Administrative is_active toggle.
  - Complete change audit trail in financial_settings_history.
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
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
from app.core.money import Money
from app.models.enums import Programme, SettingAction, sql_enum

if TYPE_CHECKING:
    from app.models.user import User


class FinancialSetting(Base):
    """Versioned, effective-dated financial settings model for dual-programme platform.

    Note on Resolution:
      Historical transactions resolve settings based on the transaction timestamp falling
      within [effective_from, effective_to), regardless of whether is_active is currently True
      for new transactions today.
    """

    __tablename__ = "financial_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    programme: Mapped[Programme] = mapped_column(sql_enum(Programme), nullable=False)
    setting_key: Mapped[str] = mapped_column(String(64), nullable=False)
    setting_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    effective_to: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "programme",
            "setting_key",
            "version",
            name="uq_fin_settings_prog_key_version",
        ),
        Index(
            "ix_fin_settings_lookup",
            "programme",
            "setting_key",
            "effective_from",
            "effective_to",
        ),
        Index("ix_fin_settings_active", "programme", "setting_key", "is_active"),
        CheckConstraint("version >= 1", name="chk_fin_settings_version_positive"),
        CheckConstraint(
            "setting_value >= 0.000000",
            name="chk_fin_settings_value_non_negative",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="chk_fin_settings_effective_window",
        ),
    )

    created_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[created_by_id],
    )
    history: Mapped[List["FinancialSettingHistory"]] = relationship(
        "FinancialSettingHistory",
        back_populates="setting",
        cascade="all, delete-orphan",
        order_by="FinancialSettingHistory.changed_at.desc()",
    )

    def as_money(self) -> Money:
        """Convert setting_value to Money without silent rounding."""
        return Money(self.setting_value, currency=self.currency)

    def as_rate(self) -> Decimal:
        """Return setting_value as Decimal rate."""
        return self.setting_value

    @property
    def money(self) -> Money:
        """Property getter for setting_value as Money."""
        return Money(self.setting_value, currency=self.currency)

    @money.setter
    def money(self, val: Money) -> None:
        """Property setter for setting_value from a Money instance."""
        if not isinstance(val, Money):
            raise TypeError(f"Expected a Money instance, got {type(val).__name__}.")
        self.setting_value = val.amount
        self.currency = val.currency


class FinancialSettingHistory(Base):
    """Immutable audit trail for changes to financial settings."""

    __tablename__ = "financial_settings_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    setting_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("financial_settings.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    programme: Mapped[Programme] = mapped_column(sql_enum(Programme), nullable=False)
    setting_key: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    new_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[SettingAction] = mapped_column(sql_enum(SettingAction), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    changed_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=True,
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_fin_settings_hist_setting", "setting_id"),
        Index("ix_fin_settings_hist_lookup", "programme", "setting_key"),
        Index("ix_fin_settings_hist_changed_at", "changed_at"),
    )

    setting: Mapped["FinancialSetting"] = relationship(
        "FinancialSetting",
        back_populates="history",
        foreign_keys=[setting_id],
    )
    changed_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[changed_by_id],
    )

