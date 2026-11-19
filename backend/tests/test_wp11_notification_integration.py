"""Integration tests for WP-11 Step 1B: Notification Workflow Integration.

Covers:
1. Each of the seven permitted notification events:
   - PA_ADMIN_CASHBACK_CYCLE_COMPLETED
   - PA_ADMIN_CASHBACK_WITHDRAWAL_REQUESTED
   - PA_ADMIN_TRANSACTION_FAILURE
   - PB_DISTRIBUTOR_ORDER_DELIVERED
   - PB_ADMIN_BLOCKED_WITHDRAWAL_REQUESTED
   - PB_DISTRIBUTOR_WALLET_UNFROZEN
   - PB_DISTRIBUTOR_WITHDRAWAL_SUCCESS
2. Correct administrator / distributor targeting and isolation.
3. Correct programme association (Plan A vs Plan B).
4. Notification creation and business-event transaction rollback atomicity.
5. Duplicate suppression on retries and duplicate events.
6. Recovery / reprocessing without duplicate notifications.
7. No notification for incomplete or unsuccessful events.
8. No prohibited notification types or cross-programme leakage.
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
import uuid
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.billing import BillingEngineClaim, BillingId
from app.models.cashback import (
    PlanACashbackContribution,
    PlanACashbackCycle,
    PlanACashbackEntry,
    PlanACashbackQueue,
    PlanAUnallocatedCashbackReserve,
)
from app.models.enums import (
    AccountStatus,
    CycleStatus,
    OrderStatus,
    PaymentStatus,
    Programme,
    UserRole,
    WalletReferenceType,
    WalletTransactionType,
    WalletType,
    WithdrawalStatus,
)
from app.models.notification import Notification
from app.models.order import Order, OrderItem
from app.models.payment import PaymentAttempt, PaymentEvent
from app.models.product import Product
from app.models.queue import CommissionCycle
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.models.wallet import Wallet, WalletFreezeHistory, WalletTransaction, Withdrawal
from app.services.cashback.plan_a import (
    CASHBACK_CONTRIBUTION_AMOUNT,
    CASHBACK_CYCLE_COMPLETION_AMOUNT,
    MAX_CYCLE_CONTRIBUTIONS,
    PlanACashbackService,
)
from app.services.notification_service import (
    NotificationEvent,
    NotificationService,
)
from app.services.payment.base import VerifiedPaymentEvent
from app.services.payment.service import PaymentService
from app.services.wallet_service import (
    admin_approve_withdrawal,
    credit_wallet,
    execute_simulated_withdrawal,
    get_or_create_wallet,
    unfreeze_wallet,
)


@pytest.fixture
def make_user(db_session: Session):
    """Factory fixture for test users with unique phones and referral codes."""
    counter = [900]

    def _create(
        programme: Programme = Programme.PLAN_A,
        role: UserRole = UserRole.CUSTOMER,
        account_status: AccountStatus = AccountStatus.ACTIVE,
        referred_by_id: int = None,
    ) -> User:
        counter[0] += 1
        num = counter[0]
        ref_code = f"NOTIF{num:05d}" if role == UserRole.CUSTOMER else None
        user = User(
            phone=f"96666{num:05d}",
            full_name=f"Notify User {num}",
            role=role,
            programme=programme,
            account_status=account_status,
            referral_code=ref_code,
            referred_by_id=referred_by_id,
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _create


@pytest.fixture
def make_product(db_session: Session):
    """Factory for test product."""
    def _create(programme: Programme = Programme.PLAN_A) -> Product:
        prod = Product(
            name=f"Product {uuid.uuid4().hex[:6]}",
            product_code=f"CODE-{uuid.uuid4().hex[:8].upper()}",
            description="Test product description",
            price=Decimal("2999.00"),
            stock=100,
            is_active=True,
            is_power_bank=True,
        )
        db_session.add(prod)
        db_session.flush()
        return prod
    return _create


@pytest.fixture
def make_address(db_session: Session):
    """Factory for test delivery address."""
    def _create(user_id: int) -> Address:
        addr = Address(
            user_id=user_id,
            recipient_name="Recipient",
            address_line1="123 Road",
            city="City",
            state="State",
            pincode="560001",
            phone="9876543210",
        )
        db_session.add(addr)
        db_session.flush()
        return addr
    return _create


@pytest.fixture
def make_order(db_session: Session, make_product, make_address):
    """Factory for test order."""
    def _create(
        user: User,
        order_status: OrderStatus = OrderStatus.CONFIRMED,
        payment_status: PaymentStatus = PaymentStatus.COMPLETED,
        applied_referral_code: str = None,
    ) -> Order:
        addr = make_address(user.id)
        prod = make_product(user.programme)
        order = Order(
            order_number=f"ORD-{uuid.uuid4().hex[:8].upper()}",
            idempotency_key=f"IK-{uuid.uuid4().hex[:12]}",
            user_id=user.id,
            address_id=addr.id,
            total_amount=Decimal("2999.00"),
            order_status=order_status,
            payment_status=payment_status,
            applied_referral_code=applied_referral_code,
            is_fulfilled=True,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            product_name=prod.name,
            quantity=1,
            unit_price=Decimal("2999.00"),
            line_total=Decimal("2999.00"),
        )
        db_session.add(item)
        db_session.flush()
        return order
    return _create


@pytest.fixture
def make_billing_id(db_session: Session, make_order):
    """Factory for test Billing IDs."""
    seq = [1000]

    def _create(user: User, applied_referral_code: str = None) -> BillingId:
        seq[0] += 1
        order = make_order(user, applied_referral_code=applied_referral_code)
        bid = BillingId(
            billing_number=f"AGD-PA-20261115-{seq[0]:06d}",
            order_id=order.id,
            order_item_id=order.order_items[0].id,
            unit_index=1,
            user_id=user.id,
            product_id=order.order_items[0].product_id,
            programme=Programme.PLAN_A,
            sequence_number=seq[0],
            status="ALLOCATED",
        )
        db_session.add(bid)
        db_session.flush()

        claim = BillingEngineClaim(
            billing_id=bid.id,
            engine=Programme.PLAN_A,
            status="PENDING",
        )
        db_session.add(claim)
        db_session.flush()
        return bid

    return _create


# ==============================================================================
# 1. PLAN A NOTIFICATION INTEGRATION TESTS
# ==============================================================================

class TestPlanANotificationIntegration:
    """Tests covering Plan A notification workflow events."""

    def test_01_cashback_cycle_completed_notifies_admin(
        self, db_session: Session, make_user, make_billing_id
    ):
        """1: PA_ADMIN_CASHBACK_CYCLE_COMPLETED emits on 16th contribution to all active admins."""
        admin = make_user(role=UserRole.ADMIN, programme=Programme.PLAN_A)
        recipient = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_A)

        # 1. Initial purchase by root recipient initializes queue under BR-A4
        bid_root = make_billing_id(recipient)
        init_res = PlanACashbackService.process_billing_id(bid_root.id, db=db_session)
        assert init_res.status == "RESERVED_INITIAL_QUEUE"

        # Advance cycle directly to 15/16 contributions
        cycle = (
            db_session.query(PlanACashbackCycle)
            .filter(PlanACashbackCycle.recipient_user_id == recipient.id)
            .one()
        )
        cycle.completed_contributions = 15
        cycle.total_earned = Decimal("3750.00")
        db_session.flush()

        # 2. 16th contribution arrives from a referred purchaser
        purchaser = make_user(
            role=UserRole.CUSTOMER,
            programme=Programme.PLAN_A,
            referred_by_id=recipient.id,
        )
        rel = ReferralRelationship(
            referee_id=purchaser.id,
            referrer_id=recipient.id,
            referee_programme=Programme.PLAN_A,
            referrer_programme=Programme.PLAN_A,
            referral_code_used=recipient.referral_code,
            binding_channel="CHECKOUT",
            is_active=True,
        )
        db_session.add(rel)
        db_session.flush()

        bid16 = make_billing_id(purchaser, applied_referral_code=recipient.referral_code)

        res = PlanACashbackService.process_billing_id(bid16.id, db=db_session)
        assert res.status == "CONTRIBUTED"
        assert res.cycle_completed is True

        # Verify notification was emitted to admin
        notif = (
            db_session.query(Notification)
            .filter(
                Notification.user_id == admin.id,
                Notification.event_type == NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED.value,
                Notification.reference_type == "cycle",
                Notification.reference_id == str(cycle.id),
            )
            .first()
        )
        assert notif is not None
        assert notif.programme == Programme.PLAN_A
        assert f"cycle #{cycle.id}" in notif.message
        assert notif.is_read is False

        # Verify recipient customer received NO admin notification
        cust_notif = (
            db_session.query(Notification)
            .filter(Notification.user_id == recipient.id)
            .count()
        )
        assert cust_notif == 0

        # Duplicate suppression: calling emit again with same ref returns existing notification
        dup = NotificationService.emit_admin_notification(
            db=db_session,
            programme=Programme.PLAN_A,
            event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED,
            title="Cashback Cycle Completed",
            message="Duplicate attempt",
            reference_type="cycle",
            reference_id=cycle.id,
        )
        assert len(dup) == 1
        assert dup[0].id == notif.id
        assert db_session.query(Notification).filter(Notification.user_id == admin.id).count() == 1

    def test_02_cashback_withdrawal_requested_notifies_admin(
        self, db_session: Session, make_user
    ):
        """2: PA_ADMIN_CASHBACK_WITHDRAWAL_REQUESTED emits when Plan A cashback withdrawal is recorded."""
        admin = make_user(role=UserRole.ADMIN, programme=Programme.PLAN_A)
        customer = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_A)

        # Set up completed cycle and ₹4,000 balance in SEQUENTIAL_COMMISSION wallet
        wallet = get_or_create_wallet(
            db_session, user_id=customer.id, wallet_type=WalletType.SEQUENTIAL_COMMISSION
        )
        wallet.balance = Decimal("4000.00")

        # CommissionCycle required by wallet_service gating
        cycle = CommissionCycle(
            queue_entry_id=1,
            beneficiary_id=customer.id,
            cycle_number=1,
            status=CycleStatus.COMPLETED,
            completed_commissions=16,
            total_earned=Decimal("4000.00"),
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
        )
        db_session.add(cycle)
        db_session.flush()

        wd = execute_simulated_withdrawal(
            db=db_session,
            customer=customer,
            wallet_type=WalletType.SEQUENTIAL_COMMISSION,
            idempotency_key="WD-PA-NOTIF-001",
        )
        assert wd.id is not None

        # Verify admin received notification
        notif = (
            db_session.query(Notification)
            .filter(
                Notification.user_id == admin.id,
                Notification.event_type == NotificationEvent.PA_ADMIN_CASHBACK_WITHDRAWAL_REQUESTED.value,
                Notification.reference_type == "withdrawal",
                Notification.reference_id == str(wd.id),
            )
            .first()
        )
        assert notif is not None
        assert notif.programme == Programme.PLAN_A
        assert f"withdrawal #{wd.id}" in notif.message

        # Idempotency / retry does not duplicate notification
        wd_retry = execute_simulated_withdrawal(
            db=db_session,
            customer=customer,
            wallet_type=WalletType.SEQUENTIAL_COMMISSION,
            idempotency_key="WD-PA-NOTIF-001",
        )
        assert wd_retry.id == wd.id
        assert (
            db_session.query(Notification)
            .filter(
                Notification.user_id == admin.id,
                Notification.event_type == NotificationEvent.PA_ADMIN_CASHBACK_WITHDRAWAL_REQUESTED.value,
            )
            .count()
            == 1
        )

    def test_03_transaction_failure_notifies_admin(
        self, db_session: Session, make_user, make_order
    ):
        """3: PA_ADMIN_TRANSACTION_FAILURE emits for Plan A payment transaction failure."""
        admin = make_user(role=UserRole.ADMIN, programme=Programme.PLAN_A)
        customer = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_A)

        order = make_order(
            user=customer,
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )

        # Create pending payment attempt
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference=f"ATT-{uuid.uuid4().hex[:12]}",
            provider="simulated",
            amount=order.total_amount,
            status=PaymentStatus.PENDING,
            expires_at=datetime.now(timezone.utc),
        )
        db_session.add(attempt)
        db_session.flush()

        payload = {
            "event_id": f"EVT-FAIL-{uuid.uuid4().hex[:8]}",
            "event_type": "payment.failed",
            "attempt_reference": attempt.attempt_reference,
            "amount": float(order.total_amount),
            "currency": "INR",
            "failure_reason": "Card expired or issuer declined.",
        }
        outcome, data = PaymentService.process_verified_event(
            db=db_session,
            raw_payload=json.dumps(payload).encode("utf-8"),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert outcome == "FAILED"

        # Verify admin received transaction failure notification
        notif = (
            db_session.query(Notification)
            .filter(
                Notification.user_id == admin.id,
                Notification.event_type == NotificationEvent.PA_ADMIN_TRANSACTION_FAILURE.value,
                Notification.reference_type == "order",
                Notification.reference_id == str(order.id),
            )
            .first()
        )
        assert notif is not None
        assert notif.programme == Programme.PLAN_A
        assert f"order #{order.id}" in notif.message


# ==============================================================================
# 2. PLAN B NOTIFICATION INTEGRATION TESTS
# ==============================================================================

class TestPlanBNotificationIntegration:
    """Tests covering Plan B notification workflow events."""

    def test_04_order_delivered_notifies_distributor(
        self, db_session: Session, make_user, make_order
    ):
        """4: PB_DISTRIBUTOR_ORDER_DELIVERED fails safely without verified delivery; emits only with verified evidence."""
        distributor = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_B)
        purchaser = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_B)

        order = make_order(
            user=purchaser,
            applied_referral_code=distributor.referral_code,
        )

        # 1. Calling without verified delivery evidence fails safely (no false notification)
        unverified_notif = NotificationService.notify_order_delivered(db_session, order.id)
        assert unverified_notif is None
        assert (
            db_session.query(Notification)
            .filter(Notification.user_id == distributor.id)
            .count()
            == 0
        )

        # 2. Emits correctly when verified courier delivery evidence is provided
        notif = NotificationService.notify_order_delivered(
            db_session, order.id, verified_delivery=True
        )
        assert notif is not None
        assert notif.user_id == distributor.id
        assert notif.programme == Programme.PLAN_B
        assert notif.event_type == NotificationEvent.PB_DISTRIBUTOR_ORDER_DELIVERED.value
        assert notif.reference_type == "order"
        assert notif.reference_id == str(order.id)

        # 3. Duplicate delivery hook call suppresses duplicate notification
        dup = NotificationService.notify_order_delivered(
            db_session, order.id, verified_delivery=True
        )
        assert dup.id == notif.id
        assert (
            db_session.query(Notification)
            .filter(Notification.user_id == distributor.id)
            .count()
            == 1
        )

    def test_05_blocked_distributor_withdrawal_requested_notifies_admin(
        self, db_session: Session, make_user
    ):
        """5: PB_ADMIN_BLOCKED_WITHDRAWAL_REQUESTED notifies admin when blocked distributor requests withdrawal."""
        admin = make_user(role=UserRole.ADMIN, programme=Programme.PLAN_B)
        blocked_dist = make_user(
            role=UserRole.CUSTOMER,
            programme=Programme.PLAN_B,
            account_status=AccountStatus.BLOCKED,
        )

        wallet = get_or_create_wallet(
            db_session, user_id=blocked_dist.id, wallet_type=WalletType.DIRECT_REFERRAL
        )
        wallet.balance = Decimal("1500.00")
        db_session.flush()

        wd = execute_simulated_withdrawal(
            db=db_session,
            customer=blocked_dist,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="WD-BLK-001",
        )
        assert wd.status == WithdrawalStatus.REQUESTED

        # Verify admin was notified
        notif = (
            db_session.query(Notification)
            .filter(
                Notification.user_id == admin.id,
                Notification.event_type == NotificationEvent.PB_ADMIN_BLOCKED_WITHDRAWAL_REQUESTED.value,
                Notification.reference_type == "withdrawal",
                Notification.reference_id == str(wd.id),
            )
            .first()
        )
        assert notif is not None
        assert notif.programme == Programme.PLAN_B
        assert f"distributor #{blocked_dist.id}" in notif.message

        # Blocked distributor themselves did not receive the admin notification
        assert (
            db_session.query(Notification)
            .filter(Notification.user_id == blocked_dist.id)
            .count()
            == 0
        )

    def test_06_wallet_unfrozen_notifies_distributor(
        self, db_session: Session, make_user
    ):
        """6: PB_DISTRIBUTOR_WALLET_UNFROZEN notifies distributor when wallet is unfrozen."""
        admin = make_user(role=UserRole.ADMIN, programme=Programme.PLAN_B)
        distributor = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_B)

        wallet = get_or_create_wallet(
            db_session, user_id=distributor.id, wallet_type=WalletType.DIRECT_REFERRAL
        )
        wallet.is_frozen = True
        db_session.flush()

        unfrozen = unfreeze_wallet(
            db=db_session,
            wallet_id=wallet.id,
            admin_id=admin.id,
            reason="KYC documents verified successfully",
        )
        assert unfrozen.is_frozen is False

        # Verify distributor received notification
        notif = (
            db_session.query(Notification)
            .filter(
                Notification.user_id == distributor.id,
                Notification.event_type == NotificationEvent.PB_DISTRIBUTOR_WALLET_UNFROZEN.value,
                Notification.reference_type == "wallet",
                Notification.reference_id == str(wallet.id),
            )
            .first()
        )
        assert notif is not None
        assert notif.programme == Programme.PLAN_B
        assert f"wallet #{wallet.id}" in notif.message

        # Calling unfreeze on already unfrozen wallet does not emit new notification
        unfreeze_wallet(db_session, wallet.id, admin.id)
        assert (
            db_session.query(Notification)
            .filter(Notification.user_id == distributor.id)
            .count()
            == 1
        )

    def test_07_distributor_withdrawal_success_notifies_distributor(
        self, db_session: Session, make_user
    ):
        """7: PB_DISTRIBUTOR_WITHDRAWAL_SUCCESS notifies distributor upon completed payout."""
        distributor = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_B)

        wallet = get_or_create_wallet(
            db_session, user_id=distributor.id, wallet_type=WalletType.DIRECT_REFERRAL
        )
        wallet.balance = Decimal("1000.00")
        db_session.flush()

        wd = execute_simulated_withdrawal(
            db=db_session,
            customer=distributor,
            wallet_type=WalletType.DIRECT_REFERRAL,
            idempotency_key="WD-DIST-SUCC-001",
        )
        assert wd.status == WithdrawalStatus.COMPLETED

        notif = (
            db_session.query(Notification)
            .filter(
                Notification.user_id == distributor.id,
                Notification.event_type == NotificationEvent.PB_DISTRIBUTOR_WITHDRAWAL_SUCCESS.value,
                Notification.reference_type == "withdrawal",
                Notification.reference_id == str(wd.id),
            )
            .first()
        )
        assert notif is not None
        assert notif.programme == Programme.PLAN_B
        assert f"Withdrawal #{wd.id}" in notif.message


# ==============================================================================
# 3. TRANSACTION ATOMICITY, ROLLBACK & NEGATIVE RESTRICTIONS
# ==============================================================================

class TestNotificationAtomicityAndNegativeRestrictions:
    """Tests covering atomicity, rollbacks, and strictly prohibited notifications."""

    def test_08_transaction_rollback_reverts_notifications(
        self, db_session: Session, make_user
    ):
        """8: Notifications roll back cleanly if caller's business transaction is aborted."""
        admin = make_user(role=UserRole.ADMIN, programme=Programme.PLAN_A)
        customer = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_A)

        # Emitting within transaction without commit
        NotificationService.emit_admin_notification(
            db=db_session,
            programme=Programme.PLAN_A,
            event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED,
            title="Uncommitted Cycle",
            message="This should be rolled back.",
            reference_type="cycle",
            reference_id=9999,
        )

        assert (
            db_session.query(Notification)
            .filter(Notification.user_id == admin.id)
            .count()
            == 1
        )

        # Simulate transaction rollback
        db_session.rollback()

        # Notification must be completely reverted
        assert (
            db_session.query(Notification)
            .filter(Notification.user_id == admin.id)
            .count()
            == 0
        )

    def test_09_plan_b_payment_failure_does_not_emit_notification(
        self, db_session: Session, make_user, make_order
    ):
        """9: Plan B payment failure strictly does NOT emit notification (R-10 negative rule)."""
        admin = make_user(role=UserRole.ADMIN, programme=Programme.PLAN_B)
        distributor = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_B)

        order = make_order(
            user=distributor,
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )

        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference=f"ATT-PB-{uuid.uuid4().hex[:12]}",
            provider="simulated",
            amount=order.total_amount,
            status=PaymentStatus.PENDING,
            expires_at=datetime.now(timezone.utc),
        )
        db_session.add(attempt)
        db_session.flush()

        payload = {
            "event_id": f"EVT-PB-FAIL-{uuid.uuid4().hex[:8]}",
            "event_type": "payment.failed",
            "attempt_reference": attempt.attempt_reference,
            "amount": float(order.total_amount),
            "currency": "INR",
            "failure_reason": "Plan B routine payment failure.",
        }
        outcome, data = PaymentService.process_verified_event(
            db=db_session,
            raw_payload=json.dumps(payload).encode("utf-8"),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert outcome == "FAILED"

        # Assert ZERO notifications emitted for Plan B payment failure
        total_notifs = db_session.query(Notification).count()
        assert total_notifs == 0

    def test_10_self_purchased_order_does_not_emit_delivery_notification(
        self, db_session: Session, make_user, make_order
    ):
        """10: Self-purchased Plan B order does not emit order delivered notification."""
        distributor = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_B)

        # Self purchase: order applied_referral_code is distributor's own code
        order = make_order(
            user=distributor,
            applied_referral_code=distributor.referral_code,
        )

        # Neither unverified nor verified delivery creates notification for self-purchases
        notif_unverified = NotificationService.notify_order_delivered(db_session, order.id)
        assert notif_unverified is None

        notif_verified = NotificationService.notify_order_delivered(
            db_session, order.id, verified_delivery=True
        )
        assert notif_verified is None
        assert db_session.query(Notification).count() == 0

    def test_11_prohibited_event_types_strictly_rejected(
        self, db_session: Session, make_user
    ):
        """11: Prohibited event types (registration, commission, etc.) raise ValueError."""
        user = make_user(role=UserRole.CUSTOMER, programme=Programme.PLAN_B)

        with pytest.raises(ValueError, match="Only the 7 explicitly confirmed R-10"):
            NotificationService.emit_notification(
                db=db_session,
                user_id=user.id,
                programme=Programme.PLAN_B,
                event_type="PB_REGISTRATION_SUCCESS",
                title="Registration Successful",
                message="Welcome!",
            )

        with pytest.raises(ValueError, match="Only the 7 explicitly confirmed R-10"):
            NotificationService.emit_notification(
                db=db_session,
                user_id=user.id,
                programme=Programme.PLAN_B,
                event_type="COMMISSION_CREDITED",
                title="Commission Earned",
                message="Earned ₹500.00",
            )
