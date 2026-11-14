"""Referral Relationship model for Arya Global Digital dual-programme platform."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
    from app.models.user import User


class ReferralRelationship(Base):
    """Authoritative, permanent referral relationship binding a referee to their referrer.

    Design Safeguards:
      1. Single-Referrer Invariant: A referee can be referred by at most one referrer (uq_referral_rel_referee).
      2. Self-Referral Prevention: Referrer and referee cannot be the same user (chk_ref_rel_no_self).
      3. Dual-Programme Scoping: Tracks both referee_programme and referrer_programme.
      4. Binding Metadata: Records binding channel and referral code used.
    """

    __tablename__ = "referral_relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referee_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
    )
    referrer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
    )
    referee_programme: Mapped[Programme] = mapped_column(
        sql_enum(Programme), nullable=False
    )
    referrer_programme: Mapped[Programme] = mapped_column(
        sql_enum(Programme), nullable=False
    )
    referral_code_used: Mapped[str] = mapped_column(String(20), nullable=False)
    binding_channel: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("referee_id", name="uq_referral_rel_referee"),
        CheckConstraint("referee_id != referrer_id", name="chk_ref_rel_no_self"),
        Index("idx_ref_rel_referrer", "referrer_id", "is_active"),
        Index("idx_ref_rel_code", "referral_code_used"),
    )

    referee: Mapped["User"] = relationship(
        "User",
        foreign_keys=[referee_id],
        back_populates="referral_as_referee",
    )
    referrer: Mapped["User"] = relationship(
        "User",
        foreign_keys=[referrer_id],
        back_populates="referral_relationships_as_referrer",
    )

