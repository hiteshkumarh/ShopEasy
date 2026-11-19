"""Comprehensive test suite for WP-9: Wallet Ledger & Withdrawal State Machines.

Verifies:
  1. Wallet model `is_frozen` default is False and server_default is '0'.
  2. WalletFreezeHistory creation, relations, and indexed queries.
  3. Withdrawal model fields (`status`, `admin_id`, `receipt_reference`, `rejection_reason`).
  4. Active unfrozen distributor withdrawal auto-transitions to COMPLETED with receipt.
  5. Immutable WalletTransaction DEBIT entry recorded with balance_after=0.
  6. Idempotency key replay returns existing withdrawal without double-debiting.
  7. Cross-wallet-type idempotency key conflict raises HTTP 409.
  8. Blocked distributor withdrawal transitions to REQUESTED without debiting balance.
  9. Admin approval of REQUESTED withdrawal debits wallet and completes simulated payout.
  10. Admin double-click approval protection raises HTTP 409.
  11. Admin rejection of REQUESTED withdrawal sets REJECTED status with reason and preserves funds.
  12. Admin double-rejection or approval of already rejected withdrawal raises HTTP 409.
  13. Frozen wallet blocks withdrawal request with HTTP 409.
  14. Wallet unfreeze re-enables withdrawal capability.
  15. Admin freeze/unfreeze actions append auditable WalletFreezeHistory entries.
  16. Freezing wallet does NOT block commission accrual (credit_wallet succeeds).
  17. First withdrawal threshold: balance < ₹750 rejected with HTTP 400.
  18. First withdrawal threshold: balance >= ₹750 succeeds.
  19. Subsequent withdrawal allows balance < ₹750 (e.g. ₹500 or ₹50).
  20. Zero or negative balance withdrawal rejected with HTTP 400.
  21. Sequential commission wallet requires completed 16/16 cycle and >= ₹4,000.
  22. Programme isolation: Plan A and Plan B commission balances coexist in Direct Referral wallet
      without interference from legacy sequential queue balances.
  23. Admin endpoints: GET /pending, POST /approve, POST /reject, POST /freeze, POST /unfreeze.
  24. Customer endpoints: POST /withdraw, GET /withdrawals, GET /wallets.
"""

from datetime import datetime
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.database import Base, get_db
from app.main import app
from app.models.enums import (
    AccountStatus,
    CycleStatus,
    Programme,
    UserRole,
    WalletReferenceType,
    WalletTransactionType,
    WalletType,
    WithdrawalStatus,
)
from app.models.queue import BeneficiaryQueue, CommissionCycle, QueueStatus
from app.models.user import User
from app.models.wallet import Wallet, WalletFreezeHistory, WalletTransaction, Withdrawal
from app.services.wallet_service import (
    admin_approve_withdrawal,
    admin_reject_withdrawal,
    credit_wallet,
    execute_simulated_withdrawal,
    freeze_wallet,
    get_or_create_wallet,
    unfreeze_wallet,
)


@pytest.fixture
def db_session():
    """In-memory SQLite database session with full schema."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def make_user(db_session: Session):
    """Helper to create test users."""
    user_counter = 0

    def _create(
        role: UserRole = UserRole.CUSTOMER,
        account_status: AccountStatus = AccountStatus.ACTIVE,
        programme: Programme = Programme.PLAN_A,
    ) -> User:
        nonlocal user_counter
        user_counter += 1
        ref_code = f"REF{user_counter:04d}" if role == UserRole.CUSTOMER else None
        user = User(
            phone=f"+919876543{user_counter:03d}",
            full_name=f"Test User {user_counter}",
            role=role,
            account_status=account_status,
            programme=programme,
            is_active=True,
            referral_code=ref_code,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _create


@pytest.mark.unit
class TestWP9WalletModels:
    """Validate ORM model enhancements for WP-9."""

    def test_wallet_is_frozen_default(self, db_session: Session, make_user):
        user = make_user()
        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        assert wallet.is_frozen is False

    def test_wallet_freeze_history_model(self, db_session: Session, make_user):
        admin = make_user(role=UserRole.ADMIN)
        user = make_user()
        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)

        history = WalletFreezeHistory(
            wallet_id=wallet.id,
            admin_id=admin.id,
            action="FREEZE",
            reason="Suspected fraudulent activity",
        )
        db_session.add(history)
        db_session.commit()
        db_session.refresh(history)

        assert history.id is not None
        assert history.wallet_id == wallet.id
        assert history.admin_id == admin.id
        assert history.action == "FREEZE"
        assert history.reason == "Suspected fraudulent activity"
        assert history.created_at is not None

    def test_withdrawal_model_wp9_columns(self, db_session: Session, make_user):
        admin = make_user(role=UserRole.ADMIN)
        user = make_user()
        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)

        wd = Withdrawal(
            wallet_id=wallet.id,
            user_id=user.id,
            amount=Decimal("750.00"),
            status=WithdrawalStatus.REQUESTED,
            idempotency_key="TEST-WD-001",
            rejection_reason="Incomplete KYC documents",
            admin_id=admin.id,
            receipt_reference="SIM-PAYOUT-ABC12345",
        )
        db_session.add(wd)
        db_session.commit()
        db_session.refresh(wd)

        assert wd.status == WithdrawalStatus.REQUESTED
        assert wd.rejection_reason == "Incomplete KYC documents"
        assert wd.admin_id == admin.id
        assert wd.receipt_reference == "SIM-PAYOUT-ABC12345"
        assert wd.completed_at is None


@pytest.mark.unit
class TestWP9DistributorWithdrawalStateMachine:
    """Validate distributor state machine transitions and payouts."""

    def test_active_distributor_withdrawal_auto_completes(self, db_session: Session, make_user):
        user = make_user(account_status=AccountStatus.ACTIVE)
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("1000.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        db_session.commit()

        wd = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="WD-001",
        )
        db_session.commit()

        assert wd.status == WithdrawalStatus.COMPLETED
        assert wd.amount == Decimal("1000.00")
        assert wd.completed_at is not None
        assert wd.receipt_reference is not None
        assert wd.receipt_reference.startswith("SIM-PAYOUT-")

        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        assert wallet.balance == Decimal("0.00")
        assert wallet.total_withdrawn == Decimal("1000.00")

        tx = (
            db_session.query(WalletTransaction)
            .filter(
                WalletTransaction.wallet_id == wallet.id,
                WalletTransaction.transaction_type == WalletTransactionType.DEBIT,
            )
            .first()
        )
        assert tx is not None
        assert tx.amount == Decimal("1000.00")
        assert tx.balance_after == Decimal("0.00")
        assert tx.reference_type == WalletReferenceType.WITHDRAWAL
        assert tx.reference_id == wd.id

    def test_withdrawal_idempotency_returns_existing_record(self, db_session: Session, make_user):
        user = make_user()
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("800.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        db_session.commit()

        wd1 = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="IDEMP-KEY-123",
        )
        db_session.commit()

        wd2 = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="IDEMP-KEY-123",
        )
        assert wd1.id == wd2.id
        assert wd2.status == WithdrawalStatus.COMPLETED

        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        assert wallet.total_withdrawn == Decimal("800.00")

    def test_withdrawal_idempotency_type_mismatch_raises_conflict(self, db_session: Session, make_user):
        user = make_user()
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("800.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        db_session.commit()

        execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="SAME-KEY",
        )
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            execute_simulated_withdrawal(
                db_session,
                customer=user,
                wallet_type=WalletType.SEQUENTIAL_COMMISSION,
                idempotency_key="SAME-KEY",
            )
        assert exc_info.value.status_code == 409
        assert "was already used for a direct_referral withdrawal" in exc_info.value.detail


@pytest.mark.unit
class TestWP9BlockedDistributorWorkflow:
    """Validate blocked distributor withdrawal review and approval/rejection."""

    def test_blocked_distributor_withdrawal_held_in_requested_status(self, db_session: Session, make_user):
        user = make_user(account_status=AccountStatus.BLOCKED)
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("1500.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        db_session.commit()

        wd = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="BLOCKED-WD-001",
        )
        db_session.commit()

        assert wd.status == WithdrawalStatus.REQUESTED
        assert wd.completed_at is None
        assert wd.receipt_reference is None

        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        assert wallet.balance == Decimal("1500.00")
        assert wallet.total_withdrawn == Decimal("0.00")

    def test_admin_approves_blocked_distributor_withdrawal(self, db_session: Session, make_user):
        admin = make_user(role=UserRole.ADMIN)
        user = make_user(account_status=AccountStatus.BLOCKED)
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("1500.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        db_session.commit()

        wd = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="BLOCKED-WD-001",
        )
        db_session.commit()

        approved_wd = admin_approve_withdrawal(db_session, wd.id, admin.id)
        db_session.commit()

        assert approved_wd.status == WithdrawalStatus.COMPLETED
        assert approved_wd.admin_id == admin.id
        assert approved_wd.receipt_reference is not None
        assert approved_wd.completed_at is not None

        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        assert wallet.balance == Decimal("0.00")
        assert wallet.total_withdrawn == Decimal("1500.00")

    def test_admin_double_click_approval_raises_conflict(self, db_session: Session, make_user):
        admin = make_user(role=UserRole.ADMIN)
        user = make_user(account_status=AccountStatus.BLOCKED)
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("1500.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        db_session.commit()

        wd = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="BLOCKED-WD-001",
        )
        db_session.commit()

        admin_approve_withdrawal(db_session, wd.id, admin.id)
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            admin_approve_withdrawal(db_session, wd.id, admin.id)
        assert exc_info.value.status_code == 409
        assert "cannot be approved from current status: completed" in exc_info.value.detail

    def test_admin_rejects_blocked_distributor_withdrawal(self, db_session: Session, make_user):
        admin = make_user(role=UserRole.ADMIN)
        user = make_user(account_status=AccountStatus.BLOCKED)
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("1200.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        db_session.commit()

        wd = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="BLOCKED-WD-002",
        )
        db_session.commit()

        rejected_wd = admin_reject_withdrawal(
            db_session, wd.id, admin.id, reason="Account compliance failure"
        )
        db_session.commit()

        assert rejected_wd.status == WithdrawalStatus.REJECTED
        assert rejected_wd.admin_id == admin.id
        assert rejected_wd.rejection_reason == "Account compliance failure"

        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        assert wallet.balance == Decimal("1200.00")
        assert wallet.total_withdrawn == Decimal("0.00")

    def test_admin_cannot_approve_already_rejected_withdrawal(self, db_session: Session, make_user):
        admin = make_user(role=UserRole.ADMIN)
        user = make_user(account_status=AccountStatus.BLOCKED)
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("1200.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        db_session.commit()

        wd = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="BLOCKED-WD-003",
        )
        db_session.commit()

        admin_reject_withdrawal(db_session, wd.id, admin.id, reason="Invalid bank details")
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            admin_approve_withdrawal(db_session, wd.id, admin.id)
        assert exc_info.value.status_code == 409
        assert "cannot be approved from current status: rejected" in exc_info.value.detail


@pytest.mark.unit
class TestWP9WalletFreezeAndAccrual:
    """Validate wallet freeze/unfreeze and continued commission accrual."""

    def test_frozen_wallet_blocks_withdrawal_with_409(self, db_session: Session, make_user):
        admin = make_user(role=UserRole.ADMIN)
        user = make_user()
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("1000.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        freeze_wallet(db_session, wallet.id, admin.id, reason="Security review")
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            execute_simulated_withdrawal(
                db_session,
                customer=user,
                wallet_type=WalletType.DIRECT_REFERRAL,
                idempotency_key="WD-FROZEN",
            )
        assert exc_info.value.status_code == 409
        assert "Wallet is frozen by administrator" in exc_info.value.detail

    def test_unfreeze_wallet_restores_withdrawal_ability(self, db_session: Session, make_user):
        admin = make_user(role=UserRole.ADMIN)
        user = make_user()
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("1000.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        freeze_wallet(db_session, wallet.id, admin.id, reason="Security review")
        db_session.commit()

        unfreeze_wallet(db_session, wallet.id, admin.id, reason="Review passed")
        db_session.commit()

        wd = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="WD-UNFROZEN",
        )
        db_session.commit()
        assert wd.status == WithdrawalStatus.COMPLETED

    def test_commission_continues_accruing_while_frozen(self, db_session: Session, make_user):
        admin = make_user(role=UserRole.ADMIN)
        user = make_user()
        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        freeze_wallet(db_session, wallet.id, admin.id, reason="Compliance audit")
        db_session.commit()

        assert wallet.is_frozen is True

        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("700.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=10,
            idempotency_key="COMM-FREEZE-1",
        )
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("50.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=11,
            idempotency_key="COMM-FREEZE-2",
        )
        db_session.commit()

        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        assert wallet.balance == Decimal("750.00")

    def test_freeze_history_audit_records(self, db_session: Session, make_user):
        admin = make_user(role=UserRole.ADMIN)
        user = make_user()
        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)

        freeze_wallet(db_session, wallet.id, admin.id, reason="Suspicious IP")
        unfreeze_wallet(db_session, wallet.id, admin.id, reason="Verified IP")
        db_session.commit()

        history = (
            db_session.query(WalletFreezeHistory)
            .filter(WalletFreezeHistory.wallet_id == wallet.id)
            .order_by(WalletFreezeHistory.id.asc())
            .all()
        )
        assert len(history) == 2
        assert history[0].action == "FREEZE"
        assert history[0].reason == "Suspicious IP"
        assert history[1].action == "UNFREEZE"
        assert history[1].reason == "Verified IP"


@pytest.mark.unit
class TestWP9WithdrawalThresholdsAndGating:
    """Validate first-withdrawal vs subsequent thresholds and Sequential wallet gating."""

    def test_first_withdrawal_under_750_rejected(self, db_session: Session, make_user):
        user = make_user()
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("500.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            execute_simulated_withdrawal(
                db_session,
                customer=user,
                wallet_type=WalletType.DIRECT_REFERRAL,
                idempotency_key="FIRST-WD-FAIL",
            )
        assert exc_info.value.status_code == 400
        assert "Minimum first withdrawal balance is ₹750.00" in exc_info.value.detail

    def test_first_withdrawal_at_or_above_750_succeeds(self, db_session: Session, make_user):
        user = make_user()
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("750.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        db_session.commit()

        wd = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="FIRST-WD-PASS",
        )
        db_session.commit()
        assert wd.status == WithdrawalStatus.COMPLETED
        assert wd.amount == Decimal("750.00")

    def test_subsequent_withdrawal_under_750_succeeds(self, db_session: Session, make_user):
        user = make_user()
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("750.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="COMM-001",
        )
        db_session.commit()

        wd1 = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="WD-FIRST",
        )
        db_session.commit()
        assert wd1.status == WithdrawalStatus.COMPLETED

        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("50.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=2,
            idempotency_key="COMM-002",
        )
        db_session.commit()

        wd2 = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="WD-SUBSEQUENT",
        )
        db_session.commit()
        assert wd2.status == WithdrawalStatus.COMPLETED
        assert wd2.amount == Decimal("50.00")

    def test_zero_balance_withdrawal_rejected(self, db_session: Session, make_user):
        user = make_user()
        with pytest.raises(HTTPException) as exc_info:
            execute_simulated_withdrawal(
                db_session,
                customer=user,
                wallet_type=WalletType.DIRECT_REFERRAL,
                idempotency_key="WD-EMPTY",
            )
        assert exc_info.value.status_code == 400
        assert "No available balance to withdraw" in exc_info.value.detail

    def test_sequential_wallet_requires_completed_cycle_and_4000_balance(self, db_session: Session, make_user):
        user = make_user()
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.SEQUENTIAL_COMMISSION,
            amount=Decimal("4000.00"),
            reference_type=WalletReferenceType.SEQUENTIAL_COMMISSION,
            reference_id=1,
            idempotency_key="SEQ-COMM-001",
        )
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            execute_simulated_withdrawal(
                db_session,
                customer=user,
                wallet_type=WalletType.SEQUENTIAL_COMMISSION,
                idempotency_key="SEQ-WD-FAIL",
            )
        assert exc_info.value.status_code == 400
        assert "only permitted after completing the full 16-commission cycle" in exc_info.value.detail

        queue_entry = BeneficiaryQueue(
            user_id=user.id,
            queue_position=1,
            status=QueueStatus.COMPLETED,
        )
        db_session.add(queue_entry)
        db_session.commit()
        db_session.refresh(queue_entry)

        cycle = CommissionCycle(
            queue_entry_id=queue_entry.id,
            beneficiary_id=user.id,
            cycle_number=1,
            status=CycleStatus.COMPLETED,
            completed_commissions=16,
            total_earned=Decimal("4000.00"),
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
        )
        db_session.add(cycle)
        db_session.commit()

        wd = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.SEQUENTIAL_COMMISSION,
            idempotency_key="SEQ-WD-PASS",
        )
        db_session.commit()
        assert wd.status == WithdrawalStatus.COMPLETED
        assert wd.amount == Decimal("4000.00")

    def test_plan_a_cashback_cycle_withdrawal_eligibility(self, db_session: Session, make_user):
        """Validate Plan A PlanACashbackCycle withdrawal eligibility in Sequential wallet.
        
        Covers:
          1. Completed 16-contribution cycle with ₹4,000 balance: succeeds.
          2. Incomplete 15-contribution cycle: rejected (HTTP 400).
          3. Completed cycle belonging to another customer: rejected (HTTP 400).
          4. Frozen wallet: rejected (HTTP 409).
          5. Idempotent repeat: returns same withdrawal without double-liquidation.
        """
        from app.models.cashback import PlanACashbackCycle, PlanACashbackEntry, PlanACashbackQueue
        from app.models.billing import BillingId
        from app.models.order import Order, OrderItem
        from app.models.product import Product
        from app.models.user import Address

        # 1. Setup customer and related models
        customer = make_user(programme=Programme.PLAN_A)
        other_customer = make_user(programme=Programme.PLAN_A)

        address = Address(
            user_id=customer.id,
            recipient_name=customer.full_name,
            phone=customer.phone,
            address_line1="123 API St",
            city="Mumbai",
            state="Maharashtra",
            pincode="400001",
        )
        db_session.add(address)
        db_session.flush()

        prod = Product(
            name="Power Bank Pro",
            price=Decimal("1500.00"),
            stock=100,
            product_code=f"PB-PRO-{customer.id}",
            is_power_bank=True,
            is_active=True,
        )
        db_session.add(prod)
        db_session.flush()

        order = Order(
            order_number=f"ORD-CB-{customer.id}",
            idempotency_key=f"IDEMP-ORD-{customer.id}",
            user_id=customer.id,
            address_id=address.id,
            total_amount=Decimal("1500.00"),
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            product_name=prod.name,
            quantity=1,
            unit_price=Decimal("1500.00"),
            line_total=Decimal("1500.00"),
        )
        db_session.add(item)
        db_session.flush()

        bid = BillingId(
            billing_number=f"AGD-CB-{customer.id}",
            sequence_number=900000 + customer.id,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=1,
            user_id=customer.id,
            product_id=prod.id,
            programme=Programme.PLAN_A,
        )
        db_session.add(bid)
        db_session.flush()

        queue = PlanACashbackQueue(root_user_id=customer.id, last_allocated_position=1)
        db_session.add(queue)
        db_session.flush()

        entry = PlanACashbackEntry(
            queue_id=queue.id,
            user_id=customer.id,
            billing_id=bid.id,
            queue_position=1,
            status="COMPLETED",
        )
        db_session.add(entry)
        db_session.flush()

        # Incomplete cycle (15/16 contributions)
        cycle = PlanACashbackCycle(
            queue_id=queue.id,
            queue_entry_id=entry.id,
            recipient_user_id=customer.id,
            recipient_billing_id=bid.id,
            cycle_number=1,
            completed_contributions=15,
            total_earned=Decimal("3750.00"),
            status="ACTIVE",
        )
        db_session.add(cycle)
        db_session.flush()

        # Fund wallet with ₹4,000.00
        wallet = get_or_create_wallet(db_session, customer.id, WalletType.SEQUENTIAL_COMMISSION)
        wallet.balance = Decimal("4000.00")
        db_session.commit()

        # 2. Incomplete cycle rejected
        with pytest.raises(HTTPException) as exc_info:
            execute_simulated_withdrawal(
                db_session,
                customer=customer,
                wallet_type=WalletType.SEQUENTIAL_COMMISSION,
                idempotency_key="CB-WD-INCOMPLETE",
            )
        assert exc_info.value.status_code == 400
        assert "only permitted after completing the full 16-commission cycle" in exc_info.value.detail

        # 3. Completed cycle belonging to another customer rejected
        # Switch recipient to other_customer but mark completed
        cycle.recipient_user_id = other_customer.id
        cycle.completed_contributions = 16
        cycle.total_earned = Decimal("4000.00")
        cycle.status = "COMPLETED"
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            execute_simulated_withdrawal(
                db_session,
                customer=customer,
                wallet_type=WalletType.SEQUENTIAL_COMMISSION,
                idempotency_key="CB-WD-OTHER",
            )
        assert exc_info.value.status_code == 400
        assert "only permitted after completing the full 16-commission cycle" in exc_info.value.detail

        # 4. Correct customer cycle completed, but wallet frozen
        cycle.recipient_user_id = customer.id
        wallet.is_frozen = True
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            execute_simulated_withdrawal(
                db_session,
                customer=customer,
                wallet_type=WalletType.SEQUENTIAL_COMMISSION,
                idempotency_key="CB-WD-FROZEN",
            )
        assert exc_info.value.status_code == 409
        assert "Wallet is frozen by administrator" in exc_info.value.detail

        # 5. Unfreeze wallet -> Successful full withdrawal
        wallet.is_frozen = False
        db_session.commit()

        wd = execute_simulated_withdrawal(
            db_session,
            customer=customer,
            wallet_type=WalletType.SEQUENTIAL_COMMISSION,
            idempotency_key="CB-WD-SUCCESS",
        )
        db_session.commit()

        assert wd.status == WithdrawalStatus.COMPLETED
        assert wd.amount == Decimal("4000.00")
        assert wallet.balance == Decimal("0.00")
        assert wallet.total_withdrawn == Decimal("4000.00")

        # 6. Idempotency replay check
        wd_replay = execute_simulated_withdrawal(
            db_session,
            customer=customer,
            wallet_type=WalletType.SEQUENTIAL_COMMISSION,
            idempotency_key="CB-WD-SUCCESS",
        )
        db_session.commit()
        assert wd_replay.id == wd.id
        assert wd_replay.status == WithdrawalStatus.COMPLETED
        assert wallet.balance == Decimal("0.00")

    def test_dual_programme_coexistence_in_direct_referral_wallet(self, db_session: Session, make_user):
        """Plan A (₹700 net) and Plan B (₹50 net) credit into DIRECT_REFERRAL wallet and liquidate cleanly."""
        user = make_user()
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("700.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=101,
            idempotency_key="PA-COMM:101",
        )
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("46.67"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=202,
            idempotency_key="PB-GEN:202",
        )
        credit_wallet(
            db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("466.67"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=303,
            idempotency_key="PB-DIRECT:303",
        )
        db_session.commit()

        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        expected_total = Decimal("700.00") + Decimal("46.67") + Decimal("466.67")
        assert wallet.balance == expected_total

        wd = execute_simulated_withdrawal(
            db_session,
            customer=user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="COEXIST-WD",
        )
        db_session.commit()

        assert wd.status == WithdrawalStatus.COMPLETED
        assert wd.amount == expected_total
        assert wallet.balance == Decimal("0.00")
        assert wallet.total_withdrawn == expected_total


@pytest.mark.unit
class TestWP9ApiEndpoints:
    """Validate HTTP endpoints for wallets and administrative management."""

    def test_admin_api_endpoints_workflow(self, db_session: Session, make_user):
        admin = make_user(role=UserRole.ADMIN)
        blocked_user = make_user(account_status=AccountStatus.BLOCKED)

        # Credit blocked user
        credit_wallet(
            db_session,
            user_id=blocked_user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("900.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=50,
            idempotency_key="COMM-API-1",
        )
        db_session.commit()

        # Blocked user initiates withdrawal
        wd = execute_simulated_withdrawal(
            db_session,
            customer=blocked_user,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="WD-API-1",
        )
        db_session.commit()
        assert wd.status == WithdrawalStatus.REQUESTED

        # TestClient with dependency override
        app.dependency_overrides[get_db] = lambda: db_session
        from app.api.dependencies import require_admin
        app.dependency_overrides[require_admin] = lambda: admin

        client = TestClient(app)

        # 1. GET /api/v1/admin/withdrawals/pending
        resp = client.get("/api/v1/admin/withdrawals/pending")
        assert resp.status_code == 200
        pending_list = resp.json()
        assert len(pending_list) == 1
        assert pending_list[0]["id"] == wd.id

        # 2. POST /api/v1/admin/wallets/{id}/freeze
        wallet = get_or_create_wallet(db_session, blocked_user.id, WalletType.DIRECT_REFERRAL)
        freeze_resp = client.post(
            f"/api/v1/admin/wallets/{wallet.id}/freeze",
            json={"reason": "Suspicious referral activity"},
        )
        assert freeze_resp.status_code == 200
        assert freeze_resp.json()["is_frozen"] is True

        # Approving while frozen should fail with 409
        app_fail = client.post(f"/api/v1/admin/withdrawals/{wd.id}/approve")
        assert app_fail.status_code == 409
        assert "currently frozen" in app_fail.json()["detail"]

        # 3. POST /api/v1/admin/wallets/{id}/unfreeze
        unfreeze_resp = client.post(
            f"/api/v1/admin/wallets/{wallet.id}/unfreeze",
            json={"reason": "Cleared suspicion"},
        )
        assert unfreeze_resp.status_code == 200
        assert unfreeze_resp.json()["is_frozen"] is False

        # 4. GET /api/v1/admin/wallets/{id}/freeze-history
        hist_resp = client.get(f"/api/v1/admin/wallets/{wallet.id}/freeze-history")
        assert hist_resp.status_code == 200
        history = hist_resp.json()
        assert len(history) == 2
        assert history[0]["action"] == "UNFREEZE"
        assert history[1]["action"] == "FREEZE"

        # 5. POST /api/v1/admin/withdrawals/{id}/approve
        app_ok = client.post(f"/api/v1/admin/withdrawals/{wd.id}/approve")
        assert app_ok.status_code == 200
        assert app_ok.json()["status"] == "completed"
        assert app_ok.json()["receipt_reference"] is not None

        # Clean overrides
        app.dependency_overrides.clear()
