"""Focused unit tests for WP-3 Step 3.1: Models and Enums.

Validates:
  1. AccountStatus enum definition and values (ACTIVE, BLOCKED, DEACTIVATED).
  2. User model extensions (programme, account_status) and backward compatibility with existing defaults.
  3. AccountStatusHistory model, fields, and relationships.
  4. ReferralRelationship model, fields, and relationships.
  5. ReferralRelationship single-referee uniqueness constraint.
  6. ReferralRelationship self-referral check constraint.
  7. AuditLog model, fields, indexes, and nullable actor relationship.
  8. Notification model, fields, scoping, read-status tracking, and database CASCADE delete.
  9. Package export verification in app.models.
"""

from datetime import datetime, timezone
import pytest
from sqlalchemy import (
    CheckConstraint,
    Index,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.enums import AccountStatus, Programme, UserRole
from app.models.notification import Notification
from app.models.referral import ReferralRelationship
from app.models.user import AccountStatusHistory, User
import app.models


@pytest.mark.unit
class TestWP3Enums:
    """Tests verifying enum definitions and allowed values."""

    def test_account_status_enum_values(self) -> None:
        """Verify AccountStatus enum has exactly ACTIVE, BLOCKED, DEACTIVATED with string values."""
        assert AccountStatus.ACTIVE == "ACTIVE"
        assert AccountStatus.BLOCKED == "BLOCKED"
        assert AccountStatus.DEACTIVATED == "DEACTIVATED"

        expected_values = {"ACTIVE", "BLOCKED", "DEACTIVATED"}
        actual_values = {status.value for status in AccountStatus}
        assert actual_values == expected_values
        assert len(AccountStatus) == 3

    def test_programme_enum_values(self) -> None:
        """Verify Programme enum has PLAN_A, PLAN_B, LEGACY."""
        assert Programme.PLAN_A == "PLAN_A"
        assert Programme.PLAN_B == "PLAN_B"
        assert Programme.LEGACY == "LEGACY"
        assert len(Programme) == 3


@pytest.mark.unit
class TestWP3UserModelExtensions:
    """Tests verifying User model extensions and backwards compatibility."""

    def test_user_model_defaults_and_backward_compatibility(self, db_session: Session) -> None:
        """Verify new users receive programme=LEGACY and account_status=ACTIVE by default."""
        user = User(
            full_name="Default Legacy Customer",
            phone="9876500001",
            role=UserRole.CUSTOMER,
            referral_code="REF-LEGACY-01",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        # Defaults must be applied
        assert user.programme == Programme.LEGACY
        assert user.account_status == AccountStatus.ACTIVE
        assert user.is_active is True
        assert user.referral_code == "REF-LEGACY-01"
        assert user.referred_by_id is None

    def test_user_explicit_programme_and_status(self, db_session: Session) -> None:
        """Verify explicit programme and account_status values are persisted accurately."""
        user_a = User(
            full_name="Plan A Active Customer",
            phone="9876500002",
            role=UserRole.CUSTOMER,
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="REF-PLANA-01",
            is_active=True,
        )
        user_b = User(
            full_name="Plan B Blocked Distributor",
            phone="9876500003",
            role=UserRole.CUSTOMER,
            programme=Programme.PLAN_B,
            account_status=AccountStatus.BLOCKED,
            referral_code="REF-PLANB-01",
            is_active=True,  # Blocked users retain is_active=True to log in and view dashboard
        )
        user_deact = User(
            full_name="Deactivated User",
            phone="9876500004",
            role=UserRole.CUSTOMER,
            programme=Programme.PLAN_A,
            account_status=AccountStatus.DEACTIVATED,
            referral_code="REF-DEACT-01",
            is_active=False,
        )
        db_session.add_all([user_a, user_b, user_deact])
        db_session.flush()

        assert user_a.programme == Programme.PLAN_A
        assert user_a.account_status == AccountStatus.ACTIVE

        assert user_b.programme == Programme.PLAN_B
        assert user_b.account_status == AccountStatus.BLOCKED

        assert user_deact.programme == Programme.PLAN_A
        assert user_deact.account_status == AccountStatus.DEACTIVATED
        assert user_deact.is_active is False

    def test_admin_user_compatibility_with_programme_and_status(self, db_session: Session) -> None:
        """Verify admin users satisfy chk_user_role_referral and hold valid programme/status."""
        admin = User(
            full_name="System Admin",
            phone="9876500099",
            role=UserRole.ADMIN,
            referral_code=None,
            referred_by_id=None,
            is_active=True,
        )
        db_session.add(admin)
        db_session.flush()

        assert admin.role == UserRole.ADMIN
        assert admin.programme == Programme.LEGACY
        assert admin.account_status == AccountStatus.ACTIVE
        assert admin.referral_code is None
        assert admin.referred_by_id is None

    def test_user_model_wp3_indexes(self) -> None:
        """Verify planned WP-3 indexes on User: idx_users_programme, idx_users_account_status, idx_users_prog_role."""
        indexes = {idx.name: [col.name for col in idx.columns] for idx in User.__table__.indexes}
        assert "idx_users_programme" in indexes
        assert indexes["idx_users_programme"] == ["programme"]
        assert "idx_users_account_status" in indexes
        assert indexes["idx_users_account_status"] == ["account_status"]
        assert "idx_users_prog_role" in indexes
        assert indexes["idx_users_prog_role"] == ["programme", "role"]


@pytest.mark.unit
class TestAccountStatusHistoryModel:
    """Tests verifying AccountStatusHistory model and transitions."""

    def test_account_status_history_creation_and_relationships(self, db_session: Session) -> None:
        """Verify status history records link to the user and the changing administrator."""
        admin = User(
            full_name="Admin Moderator",
            phone="9876500100",
            role=UserRole.ADMIN,
            referral_code=None,
            referred_by_id=None,
            is_active=True,
        )
        customer = User(
            full_name="Subject Customer",
            phone="9876500101",
            role=UserRole.CUSTOMER,
            referral_code="REF-SUBJ-01",
            is_active=True,
        )
        db_session.add_all([admin, customer])
        db_session.flush()

        history_entry = AccountStatusHistory(
            user_id=customer.id,
            old_status=AccountStatus.ACTIVE,
            new_status=AccountStatus.BLOCKED,
            reason="Suspected non-genuine referral activity under administrative review",
            changed_by_id=admin.id,
        )
        db_session.add(history_entry)
        db_session.flush()

        # Query back and verify attributes
        saved_entry = db_session.get(AccountStatusHistory, history_entry.id)
        assert saved_entry is not None
        assert saved_entry.user_id == customer.id
        assert saved_entry.old_status == AccountStatus.ACTIVE
        assert saved_entry.new_status == AccountStatus.BLOCKED
        assert saved_entry.changed_by_id == admin.id
        assert saved_entry.reason == "Suspected non-genuine referral activity under administrative review"
        assert saved_entry.created_at is not None

        # Verify relationship navigation
        assert saved_entry.user == customer
        assert saved_entry.changed_by == admin
        assert len(customer.status_history) == 1
        assert customer.status_history[0] == saved_entry

    def test_account_status_history_retention_and_cascade_prevention(self) -> None:
        """Verify relationship cascade does NOT include delete or delete-orphan, preserving audit trail."""
        cascade_opts = User.status_history.property.cascade
        assert "delete" not in cascade_opts, "status_history relationship must not cascade delete!"
        assert "delete-orphan" not in cascade_opts, "status_history relationship must not cascade delete-orphan!"
        assert User.status_history.property.passive_deletes is True

        # Verify foreign key constraint specifies RESTRICT on delete
        fk = next(iter(AccountStatusHistory.__table__.c.user_id.foreign_keys))
        assert fk.ondelete.upper() == "RESTRICT"

    def test_user_deletion_blocked_by_database_foreign_key_restrict(self, db_session: Session) -> None:
        """Verify that attempting to delete a User with status history is rejected by RESTRICT constraint."""
        # Explicitly ensure foreign keys are enabled on connection
        db_session.execute(text("PRAGMA foreign_keys = ON"))

        user = User(
            full_name="Subject For Restrict Test",
            phone="9876500103",
            role=UserRole.CUSTOMER,
            referral_code="REF-REST-01",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        history = AccountStatusHistory(
            user_id=user.id,
            old_status=AccountStatus.ACTIVE,
            new_status=AccountStatus.DEACTIVATED,
            reason="Voluntary closure",
        )
        db_session.add(history)
        db_session.commit()

        user_id = user.id
        history_id = history.id

        # Reload user in session and attempt delete
        user_to_delete = db_session.get(User, user_id)
        assert user_to_delete is not None
        db_session.delete(user_to_delete)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

        # Both the user and their account status history must remain completely intact
        retained_user = db_session.get(User, user_id)
        retained_history = db_session.get(AccountStatusHistory, history_id)
        assert retained_user is not None
        assert retained_history is not None
        assert retained_history.user_id == user_id


@pytest.mark.unit
class TestReferralRelationshipModel:
    """Tests verifying ReferralRelationship model, fields, and constraints."""

    def test_referral_relationship_creation_and_relationships(self, db_session: Session) -> None:
        """Verify creating a valid referral relationship linking referee and referrer."""
        distributor = User(
            full_name="Plan B Distributor Referrer",
            phone="9876500201",
            role=UserRole.CUSTOMER,
            programme=Programme.PLAN_B,
            referral_code="DIST-7777",
            is_active=True,
        )
        referee = User(
            full_name="Plan A Referred Customer",
            phone="9876500202",
            role=UserRole.CUSTOMER,
            programme=Programme.PLAN_A,
            referral_code="CUST-8888",
            is_active=True,
        )
        db_session.add_all([distributor, referee])
        db_session.flush()

        rel = ReferralRelationship(
            referee_id=referee.id,
            referrer_id=distributor.id,
            referee_programme=Programme.PLAN_A,
            referrer_programme=Programme.PLAN_B,
            referral_code_used="DIST-7777",
            binding_channel="REGISTRATION",
            is_active=True,
        )
        db_session.add(rel)
        db_session.flush()

        # Verify persisted fields
        saved_rel = db_session.get(ReferralRelationship, rel.id)
        assert saved_rel is not None
        assert saved_rel.referee_id == referee.id
        assert saved_rel.referrer_id == distributor.id
        assert saved_rel.referee_programme == Programme.PLAN_A
        assert saved_rel.referrer_programme == Programme.PLAN_B
        assert saved_rel.referral_code_used == "DIST-7777"
        assert saved_rel.binding_channel == "REGISTRATION"
        assert saved_rel.is_active is True
        assert saved_rel.created_at is not None

        # Verify bidirectional relationships
        assert saved_rel.referee == referee
        assert saved_rel.referrer == distributor
        assert referee.referral_as_referee == saved_rel
        assert len(distributor.referral_relationships_as_referrer) == 1
        assert distributor.referral_relationships_as_referrer[0] == saved_rel

    def test_referral_relationship_unique_referee_constraint(self, db_session: Session) -> None:
        """Verify unique referee constraint: a referee cannot have more than one referrer."""
        referrer_1 = User(
            full_name="Referrer One",
            phone="9876500301",
            role=UserRole.CUSTOMER,
            referral_code="REF-ONE-01",
            is_active=True,
        )
        referrer_2 = User(
            full_name="Referrer Two",
            phone="9876500302",
            role=UserRole.CUSTOMER,
            referral_code="REF-TWO-02",
            is_active=True,
        )
        referee = User(
            full_name="Single Referee",
            phone="9876500303",
            role=UserRole.CUSTOMER,
            referral_code="REF-THREE-03",
            is_active=True,
        )
        db_session.add_all([referrer_1, referrer_2, referee])
        db_session.flush()

        rel_1 = ReferralRelationship(
            referee_id=referee.id,
            referrer_id=referrer_1.id,
            referee_programme=Programme.PLAN_A,
            referrer_programme=Programme.PLAN_A,
            referral_code_used="REF-ONE-01",
            binding_channel="REGISTRATION",
            is_active=True,
        )
        db_session.add(rel_1)
        db_session.flush()

        # Attempting to bind a second referrer to the same referee must violate uq_referral_rel_referee
        rel_2 = ReferralRelationship(
            referee_id=referee.id,
            referrer_id=referrer_2.id,
            referee_programme=Programme.PLAN_A,
            referrer_programme=Programme.PLAN_A,
            referral_code_used="REF-TWO-02",
            binding_channel="CHECKOUT",
            is_active=True,
        )
        db_session.add(rel_2)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    def test_referral_relationship_self_referral_constraint(self, db_session: Session) -> None:
        """Verify self-referral check constraint rejects referee_id == referrer_id."""
        user = User(
            full_name="Self Referrer Attempt",
            phone="9876500401",
            role=UserRole.CUSTOMER,
            referral_code="SELF-REF-01",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        # Check table constraints definition
        constraints = [
            c for c in ReferralRelationship.__table__.constraints if isinstance(c, CheckConstraint)
        ]
        self_check = next((c for c in constraints if c.name == "chk_ref_rel_no_self"), None)
        assert self_check is not None

        # Attempt to insert self-referral
        self_rel = ReferralRelationship(
            referee_id=user.id,
            referrer_id=user.id,
            referee_programme=Programme.PLAN_A,
            referrer_programme=Programme.PLAN_A,
            referral_code_used="SELF-REF-01",
            binding_channel="REGISTRATION",
            is_active=True,
        )
        db_session.add(self_rel)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()


@pytest.mark.unit
class TestAuditLogModel:
    """Tests verifying AuditLog model, fields, and actor relationship."""

    def test_audit_log_fields_and_actor_relationship(self, db_session: Session) -> None:
        """Verify inserting an administrative audit log with JSON values and actor navigation."""
        admin = User(
            full_name="Audit Logging Admin",
            phone="9876500501",
            role=UserRole.ADMIN,
            referral_code=None,
            referred_by_id=None,
            is_active=True,
        )
        target_user = User(
            full_name="Audit Target User",
            phone="9876500502",
            role=UserRole.CUSTOMER,
            referral_code="AUDIT-TGT-01",
            is_active=True,
        )
        db_session.add_all([admin, target_user])
        db_session.flush()

        log = AuditLog(
            actor_id=admin.id,
            actor_role="admin",
            action="USER_STATUS_CHANGE",
            entity_type="user",
            entity_id=str(target_user.id),
            old_values='{"account_status": "ACTIVE"}',
            new_values='{"account_status": "BLOCKED"}',
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            metadata_json='{"reason": "suspicious velocity"}',
        )
        db_session.add(log)
        db_session.flush()

        saved_log = db_session.get(AuditLog, log.id)
        assert saved_log is not None
        assert saved_log.actor_id == admin.id
        assert saved_log.actor_role == "admin"
        assert saved_log.action == "USER_STATUS_CHANGE"
        assert saved_log.entity_type == "user"
        assert saved_log.entity_id == str(target_user.id)
        assert saved_log.old_values == '{"account_status": "ACTIVE"}'
        assert saved_log.new_values == '{"account_status": "BLOCKED"}'
        assert saved_log.ip_address == "192.168.1.100"
        assert saved_log.metadata_json == '{"reason": "suspicious velocity"}'
        assert saved_log.created_at is not None

        # Relationship
        assert saved_log.actor == admin
        assert len(admin.audit_logs_authored) == 1
        assert admin.audit_logs_authored[0] == saved_log

    def test_audit_log_system_actor_nullable(self, db_session: Session) -> None:
        """Verify audit logs support system/unauthenticated events where actor_id is None."""
        system_log = AuditLog(
            actor_id=None,
            actor_role="system",
            action="FINANCIAL_RECONCILIATION_RUN",
            entity_type="reconciliation",
            entity_id="RUN-2026-11-14",
            metadata_json='{"status": "PASSED"}',
        )
        db_session.add(system_log)
        db_session.flush()

        assert system_log.id is not None
        assert system_log.actor_id is None
        assert system_log.actor is None


@pytest.mark.unit
class TestNotificationModel:
    """Tests verifying Notification model, scoping, and read tracking (R-10)."""

    def test_notification_creation_scoping_and_read_status(self, db_session: Session) -> None:
        """Verify notifications link to recipient user with programme scoping and read timestamp."""
        user = User(
            full_name="Notification Recipient",
            phone="9876500601",
            role=UserRole.CUSTOMER,
            programme=Programme.PLAN_A,
            referral_code="NOTIF-01",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        notif = Notification(
            user_id=user.id,
            programme=Programme.PLAN_A,
            event_type="COMMISSION_EARNED",
            title="Referral Commission Credited",
            message="You earned Rs. 700.00 net commission on Order #105.",
            reference_type="order",
            reference_id="105",
            is_read=False,
        )
        db_session.add(notif)
        db_session.flush()

        saved_notif = db_session.get(Notification, notif.id)
        assert saved_notif is not None
        assert saved_notif.user_id == user.id
        assert saved_notif.programme == Programme.PLAN_A
        assert saved_notif.event_type == "COMMISSION_EARNED"
        assert saved_notif.title == "Referral Commission Credited"
        assert saved_notif.message == "You earned Rs. 700.00 net commission on Order #105."
        assert saved_notif.reference_type == "order"
        assert saved_notif.reference_id == "105"
        assert saved_notif.is_read is False
        assert saved_notif.read_at is None
        assert saved_notif.created_at is not None

        # User relationship
        assert saved_notif.user == user
        assert len(user.notifications) == 1
        assert user.notifications[0] == saved_notif

        # Mark as read
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        saved_notif.is_read = True
        saved_notif.read_at = now
        db_session.flush()

        reloaded = db_session.get(Notification, notif.id)
        assert reloaded.is_read is True
        assert reloaded.read_at == now

    def test_notification_foreign_key_database_on_delete_cascade(self, db_session: Session) -> None:
        """Verify that deleting a User cascades to delete all their Notification records at the DB level."""
        # 1. Verify foreign key metadata specifies CASCADE on delete and update
        fk = next(iter(Notification.__table__.c.user_id.foreign_keys))
        assert fk.ondelete.upper() == "CASCADE"
        assert fk.onupdate.upper() == "CASCADE"

        # 2. Explicitly enable SQLite foreign key enforcement for this connection
        db_session.execute(text("PRAGMA foreign_keys = ON"))

        try:
            # 3. Create target user and control user
            target_user = User(
                full_name="Target Cascade Recipient",
                phone="9876500701",
                role=UserRole.CUSTOMER,
                programme=Programme.PLAN_A,
                referral_code="NOTIF-CAS-01",
                is_active=True,
            )
            control_user = User(
                full_name="Control Cascade Recipient",
                phone="9876500702",
                role=UserRole.CUSTOMER,
                programme=Programme.PLAN_B,
                referral_code="NOTIF-CAS-02",
                is_active=True,
            )
            db_session.add_all([target_user, control_user])
            db_session.flush()

            target_id = target_user.id
            control_id = control_user.id

            # 4. Create notifications for target user and control user
            notif_t1 = Notification(
                user_id=target_id,
                programme=Programme.PLAN_A,
                event_type="COMMISSION_EARNED",
                title="Target Notif 1",
                message="Target message 1",
            )
            notif_t2 = Notification(
                user_id=target_id,
                programme=Programme.PLAN_A,
                event_type="ORDER_PLACED",
                title="Target Notif 2",
                message="Target message 2",
            )
            notif_ctrl = Notification(
                user_id=control_id,
                programme=Programme.PLAN_B,
                event_type="SYSTEM_ALERT",
                title="Control Notif",
                message="Control message",
            )
            db_session.add_all([notif_t1, notif_t2, notif_ctrl])
            db_session.commit()

            t1_id = notif_t1.id
            t2_id = notif_t2.id
            ctrl_id = notif_ctrl.id

            # 5. Confirm notifications exist in database before deletion
            target_count = db_session.execute(
                text("SELECT COUNT(*) FROM notifications WHERE user_id = :uid"),
                {"uid": target_id},
            ).scalar()
            assert target_count == 2

            control_count = db_session.execute(
                text("SELECT COUNT(*) FROM notifications WHERE user_id = :uid"),
                {"uid": control_id},
            ).scalar()
            assert control_count == 1

            # 6. Execute direct database DELETE against users table.
            # Expiring session cache ensures no ORM cascades interfere;
            # this proves SQLite's database-level ON DELETE CASCADE removes the child records.
            db_session.expire_all()
            db_session.execute(
                text("DELETE FROM users WHERE id = :uid"),
                {"uid": target_id},
            )
            db_session.commit()

            # 7. Query notification table and confirm target notifications were cascaded and removed
            remaining_target_notifs = db_session.execute(
                text("SELECT COUNT(*) FROM notifications WHERE user_id = :uid"),
                {"uid": target_id},
            ).scalar()
            assert remaining_target_notifs == 0

            assert db_session.execute(
                text("SELECT id FROM notifications WHERE id = :nid"), {"nid": t1_id}
            ).first() is None
            assert db_session.execute(
                text("SELECT id FROM notifications WHERE id = :nid"), {"nid": t2_id}
            ).first() is None

            # Confirm target user row itself is gone
            assert db_session.execute(
                text("SELECT id FROM users WHERE id = :uid"), {"uid": target_id}
            ).first() is None

            # 8. Verify unrelated control user and notification records remain completely intact
            assert db_session.execute(
                text("SELECT id FROM users WHERE id = :uid"), {"uid": control_id}
            ).first() is not None

            control_remaining = db_session.execute(
                text("SELECT COUNT(*) FROM notifications WHERE user_id = :uid"),
                {"uid": control_id},
            ).scalar()
            assert control_remaining == 1

            assert db_session.execute(
                text("SELECT id FROM notifications WHERE id = :nid"), {"nid": ctrl_id}
            ).first() is not None
        finally:
            db_session.rollback()
            db_session.execute(text("PRAGMA foreign_keys = OFF"))


@pytest.mark.unit
class TestModelExports:
    """Verify package exports in app.models."""

    def test_app_models_exports_new_wp3_classes(self) -> None:
        """Verify all new classes are exported in app.models.__all__ and importable."""
        expected_exports = [
            "AccountStatus",
            "AccountStatusHistory",
            "ReferralRelationship",
            "AuditLog",
            "Notification",
        ]
        for name in expected_exports:
            assert hasattr(app.models, name), f"{name} is missing from app.models"
            assert name in app.models.__all__, f"{name} is missing from app.models.__all__"


@pytest.mark.unit
class TestWP3MigrationA:
    """Verify WP-3 Migration A script properties and linear migration chain statically."""

    def test_migration_chain_is_linear_with_single_head(self) -> None:
        """Verify Alembic script directory has exactly one head and WP-3 migration is at the tip."""
        from pathlib import Path
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        backend_dir = Path(__file__).resolve().parent.parent
        ini_path = backend_dir / "alembic.ini"
        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))

        script_dir = ScriptDirectory.from_config(cfg)
        heads = script_dir.get_heads()
        assert len(heads) == 1, f"Expected exactly 1 Alembic head, got {heads}"
        assert heads[0] == "79b742f969d6", f"Expected head '79b742f969d6', got '{heads[0]}'"

        # Walk revisions and verify linear link from 79b742f969d6 to 2270de96fe73
        rev_head = script_dir.get_revision("79b742f969d6")
        assert rev_head is not None
        assert rev_head.down_revision == "2270de96fe73"
        assert rev_head.revision == "79b742f969d6"

    def test_migration_dry_run_ddl_generation_mysql(self) -> None:
        """Verify dry-run SQL generation for MySQL dialect executes cleanly without DB connection."""
        from pathlib import Path
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy.dialects import mysql

        backend_dir = Path(__file__).resolve().parent.parent
        ini_path = backend_dir / "alembic.ini"
        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))

        script_dir = ScriptDirectory.from_config(cfg)
        rev = script_dir.get_revision("79b742f969d6")
        assert rev is not None

        # Verify upgrade and downgrade DDL generation in memory (no network or DB socket)
        ctx = MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True})
        with Operations.context(ctx):
            rev.module.upgrade()
            rev.module.downgrade()

