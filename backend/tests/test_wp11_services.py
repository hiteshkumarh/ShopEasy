"""Tests for WP-11 Step 1A: Core Services Foundation (Audit & Notification Services).

Verifies:
1. Audit record creation with actor, action, target, and metadata.
2. Audit transaction behaviour (flushes without independent commit; rolls back if parent rolls back).
3. Secret-data redaction (passwords, tokens, OTPs, auth headers stripped).
4. Programme-scoped notification emissions.
5. Admin versus distributor recipient targeting.
6. Permitted Plan A events (3 events).
7. Permitted Plan B events (4 events).
8. Duplicate notification suppression.
9. Prohibited notification types are rejected with ValueError.
10. Notification writes do not independently commit caller-owned transactions.
"""

import json
import pytest
from sqlalchemy.orm import Session

from app.models.enums import AccountStatus, Programme, UserRole
from app.models.notification import Notification
from app.models.user import User
from app.services.audit_service import AuditService, sanitize_audit_data
from app.services.notification_service import (
    NotificationEvent,
    NotificationService,
)


@pytest.fixture
def make_user(db_session: Session):
    """Factory fixture for test users."""
    counter = [700]

    def _create(
        programme: Programme = Programme.PLAN_A,
        role: UserRole = UserRole.CUSTOMER,
    ) -> User:
        counter[0] += 1
        num = counter[0]
        # Admin must have referral_code=None per chk_user_role_referral check constraint
        ref_code = f"SERV{num:05d}" if role == UserRole.CUSTOMER else None
        user = User(
            phone=f"95555{num:05d}",
            full_name=f"Service User {num}",
            role=role,
            programme=programme,
            account_status=AccountStatus.ACTIVE,
            referral_code=ref_code,
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _create


@pytest.mark.unit
class TestAuditService:
    """Tests for AuditService functionality, transactions, and secret redaction."""

    def test_01_audit_record_creation(self, db_session: Session, make_user):
        """1: Verify audit record creation with actor, action, entity, and values."""
        admin = make_user(role=UserRole.ADMIN)

        log = AuditService.record_action(
            db=db_session,
            action="APPROVE_WITHDRAWAL",
            entity_type="Withdrawal",
            entity_id=101,
            actor_id=admin.id,
            actor_role=admin.role.value,
            old_values={"status": "requested"},
            new_values={"status": "completed", "amount": 4000.00},
            metadata={"ip": "127.0.0.1"},
            ip_address="127.0.0.1",
            user_agent="TestClient/1.0",
        )
        db_session.commit()

        assert log.id is not None
        assert log.action == "APPROVE_WITHDRAWAL"
        assert log.entity_type == "Withdrawal"
        assert log.entity_id == "101"
        assert log.actor_id == admin.id
        assert log.actor_role == "admin"
        assert log.ip_address == "127.0.0.1"

        old_val = json.loads(log.old_values)
        assert old_val["status"] == "requested"

        new_val = json.loads(log.new_values)
        assert new_val["status"] == "completed"

    def test_02_audit_transaction_caller_ownership(self, db_session: Session, make_user):
        """2: Audit write does not independently commit; rolls back if parent transaction rolls back."""
        admin = make_user(role=UserRole.ADMIN)

        AuditService.record_action(
            db=db_session,
            action="TEST_ACTION",
            entity_type="TestEntity",
            entity_id=999,
            actor_id=admin.id,
        )

        # Rollback parent transaction
        db_session.rollback()

        # Record must not exist
        count = db_session.query(AuditService).filter_by().count() if hasattr(AuditService, "id") else 0
        from app.models.audit import AuditLog
        found = db_session.query(AuditLog).filter_by(entity_id="999").first()
        assert found is None

    def test_03_secret_data_exclusion_and_redaction(self, db_session: Session, make_user):
        """3: Sensitive keys (password, otp, token, secret, api_key, private_key, cookie) are automatically redacted."""
        admin = make_user(role=UserRole.ADMIN)

        payload_with_secrets = {
            "username": "admin1",
            "password": "SuperSecretPassword123!",
            "password_hash": "$2b$12$abcdef...",
            "access_token": "eyJhbGciOi...",
            "otp": "123456",
            "api_key": "live_ak_123456",
            "private_key": "-----BEGIN PRIVATE KEY-----...",
            "cookie": "session_id=abcdef123456",
            "nested": {
                "secret": "top-secret-val",
                "safe_field": "visible_info",
            },
            "nested_list": [
                {"password": "nested_password_123"},
                {"api_key": "nested_api_key_456"},
                {"private_key": "nested_private_key_789"},
                {"cookie": "nested_cookie_abc"},
                {"safe_item_name": "Power Bank 10000mAh", "quantity": 2},
            ],
        }

        log = AuditService.record_action(
            db=db_session,
            action="LOGIN_ATTEMPT",
            entity_type="Auth",
            entity_id="1",
            actor_id=admin.id,
            new_values=payload_with_secrets,
        )
        db_session.commit()

        new_val = json.loads(log.new_values)
        assert new_val["username"] == "admin1"
        assert new_val["password"] == "[REDACTED]"
        assert new_val["password_hash"] == "[REDACTED]"
        assert new_val["access_token"] == "[REDACTED]"
        assert new_val["otp"] == "[REDACTED]"
        assert new_val["api_key"] == "[REDACTED]"
        assert new_val["private_key"] == "[REDACTED]"
        assert new_val["cookie"] == "[REDACTED]"
        assert new_val["nested"]["secret"] == "[REDACTED]"
        assert new_val["nested"]["safe_field"] == "visible_info"

        # Explicit nested list redactions
        list_items = new_val["nested_list"]
        assert list_items[0]["password"] == "[REDACTED]"
        assert list_items[1]["api_key"] == "[REDACTED]"
        assert list_items[2]["private_key"] == "[REDACTED]"
        assert list_items[3]["cookie"] == "[REDACTED]"
        assert list_items[4]["safe_item_name"] == "Power Bank 10000mAh"
        assert list_items[4]["quantity"] == 2


@pytest.mark.unit
class TestNotificationService:
    """Tests for NotificationService, R-10 matrix enforcement, and duplicate prevention."""

    def test_04_05_06_plan_a_permitted_events(self, db_session: Session, make_user):
        """4, 5, 6: Plan A events emit successfully to administrator."""
        admin = make_user(role=UserRole.ADMIN, programme=Programme.PLAN_A)

        # 1. Cashback cycle completed
        n1 = NotificationService.emit_notification(
            db=db_session,
            user_id=admin.id,
            programme=Programme.PLAN_A,
            event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED,
            title="Cashback Cycle Completed",
            message="Cycle #5 completed for customer #123 (₹4,000.00).",
            reference_type="cycle",
            reference_id=5,
        )
        assert n1.id is not None
        assert n1.event_type == "PA_ADMIN_CASHBACK_CYCLE_COMPLETED"
        assert n1.programme == Programme.PLAN_A
        assert n1.is_read is False

        # 2. Cashback withdrawal requested
        n2 = NotificationService.emit_notification(
            db=db_session,
            user_id=admin.id,
            programme=Programme.PLAN_A,
            event_type=NotificationEvent.PA_ADMIN_CASHBACK_WITHDRAWAL_REQUESTED,
            title="Cashback Withdrawal Request",
            message="Customer #123 requested ₹4,000.00 withdrawal.",
            reference_type="withdrawal",
            reference_id=12,
        )
        assert n2.event_type == "PA_ADMIN_CASHBACK_WITHDRAWAL_REQUESTED"

        # 3. Transaction failure
        n3 = NotificationService.emit_notification(
            db=db_session,
            user_id=admin.id,
            programme=Programme.PLAN_A,
            event_type=NotificationEvent.PA_ADMIN_TRANSACTION_FAILURE,
            title="Transaction Failure Alert",
            message="Fulfilment claim error on order #500.",
            reference_type="order",
            reference_id=500,
        )
        assert n3.event_type == "PA_ADMIN_TRANSACTION_FAILURE"

    def test_07_plan_b_permitted_events(self, db_session: Session, make_user):
        """7: Plan B events emit successfully to distributor or admin."""
        dist = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_B)
        admin = make_user(role=UserRole.ADMIN, programme=Programme.PLAN_B)

        # 1. Order delivered -> distributor
        n1 = NotificationService.emit_notification(
            db=db_session,
            user_id=dist.id,
            programme=Programme.PLAN_B,
            event_type=NotificationEvent.PB_DISTRIBUTOR_ORDER_DELIVERED,
            title="Order Delivered",
            message="Referred order #201 was successfully delivered.",
            reference_type="order",
            reference_id=201,
        )
        assert n1.user_id == dist.id
        assert n1.event_type == "PB_DISTRIBUTOR_ORDER_DELIVERED"

        # 2. Blocked withdrawal requested -> admin
        n2 = NotificationService.emit_notification(
            db=db_session,
            user_id=admin.id,
            programme=Programme.PLAN_B,
            event_type=NotificationEvent.PB_ADMIN_BLOCKED_WITHDRAWAL_REQUESTED,
            title="Blocked Distributor Withdrawal",
            message="Blocked distributor #50 requested withdrawal #8.",
            reference_type="withdrawal",
            reference_id=8,
        )
        assert n2.user_id == admin.id
        assert n2.event_type == "PB_ADMIN_BLOCKED_WITHDRAWAL_REQUESTED"

        # 3. Wallet unfrozen -> distributor
        n3 = NotificationService.emit_notification(
            db=db_session,
            user_id=dist.id,
            programme=Programme.PLAN_B,
            event_type=NotificationEvent.PB_DISTRIBUTOR_WALLET_UNFROZEN,
            title="Wallet Unfrozen",
            message="Your wallet #15 has been unfrozen.",
            reference_type="wallet",
            reference_id=15,
        )
        assert n3.event_type == "PB_DISTRIBUTOR_WALLET_UNFROZEN"

        # 4. Successful withdrawal -> distributor
        n4 = NotificationService.emit_notification(
            db=db_session,
            user_id=dist.id,
            programme=Programme.PLAN_B,
            event_type=NotificationEvent.PB_DISTRIBUTOR_WITHDRAWAL_SUCCESS,
            title="Withdrawal Successful",
            message="Withdrawal #9 of ₹750.00 was completed.",
            reference_type="withdrawal",
            reference_id=9,
        )
        assert n4.event_type == "PB_DISTRIBUTOR_WITHDRAWAL_SUCCESS"

    def test_08_duplicate_notification_suppression(self, db_session: Session, make_user):
        """8: Emitting same notification event for same reference returns existing notification."""
        admin = make_user(role=UserRole.ADMIN, programme=Programme.PLAN_A)

        first = NotificationService.emit_notification(
            db=db_session,
            user_id=admin.id,
            programme=Programme.PLAN_A,
            event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED,
            title="Cashback Cycle Completed",
            message="Cycle #10 completed.",
            reference_type="cycle",
            reference_id=10,
        )

        # Second identical emit
        second = NotificationService.emit_notification(
            db=db_session,
            user_id=admin.id,
            programme=Programme.PLAN_A,
            event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED,
            title="Cashback Cycle Completed",
            message="Cycle #10 completed.",
            reference_type="cycle",
            reference_id=10,
        )

        assert first.id == second.id
        total_count = db_session.query(Notification).filter_by(reference_type="cycle", reference_id="10").count()
        assert total_count == 1

    def test_09_prohibited_notification_types_rejected(self, db_session: Session, make_user):
        """9: Unapproved or prohibited events are rejected with ValueError."""
        dist = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_B)

        # Routine commission alert (prohibited per R-10)
        with pytest.raises(ValueError, match="Prohibited or invalid notification event"):
            NotificationService.emit_notification(
                db=db_session,
                user_id=dist.id,
                programme=Programme.PLAN_B,
                event_type="PB_DISTRIBUTOR_COMMISSION_CREDITED",
                title="Commission Credited",
                message="You earned ₹50.00",
            )

        # Cross-programme mismatch (Plan A event under Plan B programme)
        with pytest.raises(ValueError, match="belongs to Plan A, but programme 'PLAN_B' was specified"):
            NotificationService.emit_notification(
                db=db_session,
                user_id=dist.id,
                programme=Programme.PLAN_B,
                event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED,
                title="Invalid event",
                message="Invalid message",
            )

    def test_10_notification_transaction_caller_ownership(self, db_session: Session, make_user):
        """10: Notification write does not independently commit caller-owned transaction."""
        admin = make_user(role=UserRole.ADMIN, programme=Programme.PLAN_A)

        NotificationService.emit_notification(
            db=db_session,
            user_id=admin.id,
            programme=Programme.PLAN_A,
            event_type=NotificationEvent.PA_ADMIN_TRANSACTION_FAILURE,
            title="Failure",
            message="Failure test",
            reference_type="order",
            reference_id=999,
        )

        # Rollback caller transaction
        db_session.rollback()

        found = db_session.query(Notification).filter_by(reference_type="order", reference_id="999").first()
        assert found is None
