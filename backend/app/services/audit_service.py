"""Audit logging service for tracking administrative and operational actions (WP-11).

Invariants:
- Uses existing AuditLog model (app.models.audit.AuditLog).
- Appends immutable audit records.
- Operates within caller's database transaction without issuing independent commits.
- Strips or masks passwords, tokens, OTPs, and sensitive secret data before storage.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional, Union

from sqlalchemy.orm import Session

from app.models.audit import AuditLog

logger = logging.getLogger("shopeasy.audit")

# Keys that must never be recorded in audit logs
FORBIDDEN_SECRET_KEYS = {
    "password",
    "password_hash",
    "new_password",
    "old_password",
    "confirm_password",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "otp",
    "otp_code",
    "jwt",
    "authorization",
    "api_key",
    "private_key",
    "cookie",
}


def sanitize_audit_data(data: Any) -> Any:
    """Recursively redact secrets and sensitive fields from audit payload."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if str(k).lower() in FORBIDDEN_SECRET_KEYS:
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_audit_data(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_audit_data(item) for item in data]
    return data


class AuditService:
    """Service for creating and querying immutable administrative audit logs."""

    @classmethod
    def record_action(
        cls,
        db: Session,
        action: str,
        entity_type: str,
        entity_id: Union[int, str],
        actor_id: Optional[int] = None,
        actor_role: Optional[str] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        """Record an administrative or security audit event.

        Args:
            db: Active SQLAlchemy database session.
            action: Action verb (e.g. "APPROVE_WITHDRAWAL", "FREEZE_WALLET", "UPDATE_SETTING").
            entity_type: Entity category (e.g. "Withdrawal", "Wallet", "Customer", "Setting").
            entity_id: Identifier of the target entity.
            actor_id: Optional User ID of the administrator or system actor.
            actor_role: Role of the actor (e.g. "admin", "system").
            old_values: Optional dictionary of prior attribute values.
            new_values: Optional dictionary of updated attribute values.
            metadata: Optional additional contextual metadata.
            ip_address: Client IP address if available.
            user_agent: Client user-agent string if available.

        Returns:
            Created and flushed AuditLog record (uncommitted).
        """
        sanitized_old = sanitize_audit_data(old_values) if old_values else None
        sanitized_new = sanitize_audit_data(new_values) if new_values else None
        sanitized_meta = sanitize_audit_data(metadata) if metadata else None

        old_json = json.dumps(sanitized_old, default=str) if sanitized_old else None
        new_json = json.dumps(sanitized_new, default=str) if sanitized_new else None
        meta_json = json.dumps(sanitized_meta, default=str) if sanitized_meta else None

        audit_entry = AuditLog(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action.strip(),
            entity_type=entity_type.strip(),
            entity_id=str(entity_id).strip(),
            old_values=old_json,
            new_values=new_json,
            metadata_json=meta_json,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=datetime.now(timezone.utc),
        )

        db.add(audit_entry)
        db.flush()

        logger.info(
            f"Audit log recorded: action={action}, entity={entity_type}#{entity_id}, actor={actor_role}#{actor_id}"
        )
        return audit_entry

