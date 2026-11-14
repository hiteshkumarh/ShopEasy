"""Audit Log model for Arya Global Digital dual-programme platform."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class AuditLog(Base):
    """Immutable, append-only security and operational audit trail."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    actor_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=True,
    )
    actor_role: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(50), nullable=False)
    old_values: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_values: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_audit_logs_entity", "entity_type", "entity_id"),
        Index("idx_audit_logs_actor", "actor_id", "created_at"),
        Index("idx_audit_logs_action", "action", "created_at"),
        Index("idx_audit_logs_created", "created_at"),
    )

    actor: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[actor_id],
        back_populates="audit_logs_authored",
    )

