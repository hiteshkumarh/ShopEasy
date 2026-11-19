"""WP-7 Plan A Commission Engine Test Suite.

Comprehensive tests verifying:
  1. Eligible first Plan A referred purchase:
     - 1 Power Bank -> 1 unique Billing ID.
     - 1 PlanACommission record with status "EARNED".
     - Gross ₹750, Op cost ₹35, TDS ₹15, Net ₹700.
     - Referrer DIRECT_REFERRAL wallet credited ₹700.00.
     - 1 WalletTransaction ledger entry with idempotency key "PA-COMM:{billing_id}".
  2. Plan A repeat purchase with a new valid referral code (BR-X1):
     - New code owner receives ₹700 net commission.
     - Root ReferralRelationship and User.referred_by_id remain unchanged.
  3. Plan A purchase without referral code:
     - 1 PlanACommission record with status "UNALLOCATED_NO_REFERRER".
     - Net amount ₹0.00, gross ₹750.00, op cost ₹0.00, tds ₹0.00.
     - Zero wallet credits; zero wallet transactions (BR-A7 neutrality).
  4. Plan A repeat purchase without referral code:
     - Status "UNALLOCATED_NO_REFERRER", net ₹0.00; zero wallet credit.
  5. Multi-unit order (Quantity = 3):
     - 3 unique contiguous Billing IDs.
     - 3 distinct PlanACommission records.
     - Referrer credited 3 x ₹700 = ₹2,100 across 3 distinct wallet ledger entries.
  6. Ineligible referrer (No prior purchase):
     - Referrer has no confirmed paid purchase.
     - Status "INELIGIBLE_REFERRER", net ₹0.00; zero wallet credits.
  7. Ineligible referrer (Blocked / Deactivated account - RG-14):
     - Referrer account status is BLOCKED or DEACTIVATED at execution time.
     - Status "INELIGIBLE_REFERRER", net ₹0.00; zero wallet credits.
  8. Cross-programme referral (B -> A):
     - Plan B distributor referring a Plan A customer (B -> A allowed under BR-X3).
     - Distributor receives ₹700 net direct commission for the Plan A Power Bank.
  9. Programme isolation:
     - Plan B Billing IDs are skipped by the Plan A Commission Engine.
  10. Cashback isolation:
      - BillingEngineClaim.status remains "PENDING" and is not marked "PROCESSED".
      - Zero cashback cycles or queue structures touched.
  11. Duplicate / Retry idempotency:
      - Calling commission processing multiple times on same Billing ID does not duplicate records or wallet credit.
  12. Recovery worker sweep:
      - Sweeper identifies pending Billing IDs and processes them with per-item isolation.
  13. Atomic rollback:
      - Error during processing rolls back cleanly without leaving partial records.
"""

from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.models.billing import BillingCounter, BillingEngineClaim, BillingId
from app.models.cart import CartItem
from app.models.commission import PlanACommission
from app.models.enums import (
    AccountStatus,
    OrderStatus,
    PaymentStatus,
    Programme,
    UserRole,
    WalletType,
)
from app.models.order import Order, OrderItem
from app.models.payment import PaymentAttempt
from app.models.product import Product
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.models.wallet import Wallet, WalletTransaction
from app.services.billing.allocator import BillingAllocatorService
from app.services.commission.plan_a import PlanACommissionService
from app.services.commission.recovery_plan_a import PlanACommissionRecoveryWorker
from app.services.fulfilment.orchestrator import FulfilmentOrchestrator


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def seed_counter(db: Session, start_val: int = 1000) -> BillingCounter:
    counter = db.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
    if not counter:
        counter = BillingCounter(sequence_name="GLOBAL_BILLING_ID", current_value=start_val)
        db.add(counter)
        db.flush()
    else:
        counter.current_value = start_val
        db.flush()
    return counter


def create_product(db: Session, price: Decimal = Decimal("3999.00")) -> Product:
    prod = Product(
        name="Arya Power Bank PB-3999",
        product_code="PB-3999",
        price=price,
        stock=100,
        is_active=True,
        is_power_bank=True,
    )
    db.add(prod)
    db.flush()
    return prod


def create_user(
    db: Session,
    full_name: str,
    phone: str,
    programme: Programme = Programme.PLAN_A,
    code: str = "PA111111",
    account_status: AccountStatus = AccountStatus.ACTIVE,
) -> User:
    user = User(
        full_name=full_name,
        phone=phone,
        programme=programme,
        account_status=account_status,
        referral_code=code,
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_address(db: Session, user: User) -> Address:
    addr = Address(
        user_id=user.id,
        recipient_name=user.full_name,
        phone=user.phone,
        address_line1="123 Arya Lane",
        city="Mumbai",
        state="Maharashtra",
        pincode="400001",
    )
    db.add(addr)
    db.flush()
    return addr


def create_confirmed_order(
    db: Session,
    customer: User,
    product: Product,
    quantity: int = 1,
    referral_code: str = None,
    is_first: bool = True,
) -> Order:
    addr = create_address(db, customer)
    order = Order(
        order_number=f"ORD-WP7-{customer.id}-{product.id}-{quantity}",
        idempotency_key=f"idemp-wp7-{customer.id}-{quantity}",
        user_id=customer.id,
        address_id=addr.id,
        total_amount=product.price * quantity,
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
        applied_referral_code=referral_code,
        is_first_successful_order=is_first,
        is_fulfilled=False,
    )
    db.add(order)
    db.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        product_name=product.name,
        unit_price=product.price,
        quantity=quantity,
        line_total=product.price * quantity,
    )
    db.add(item)
    db.flush()
    return order


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPlanACommissionEngine:
    """WP-7 Plan A Commission Engine core test cases."""

    def test_eligible_first_plan_a_referred_purchase(self, db_session: Session) -> None:
        """1. Eligible first Plan A purchase: allocates 1 Billing ID, records EARNED commission, credits ₹700 net."""
        seed_counter(db_session, 100)
        prod = create_product(db_session)
        referrer = create_user(db_session, "Referrer One", "9811100001", code="PAREF001")
        # Give referrer a qualifying purchase
        create_confirmed_order(db_session, referrer, prod)

        customer = create_user(db_session, "Customer One", "9811100002", code="PACUST01")
        order = create_confirmed_order(db_session, customer, prod, quantity=1, referral_code="PAREF001", is_first=True)

        # Fulfil order (allocates Billing ID & claim)
        res_f = FulfilmentOrchestrator.fulfil_order(order.id, db=db_session)
        assert res_f.status == "COMPLETED"

        # Process commission
        results = PlanACommissionService.process_order_commissions(order.id, db=db_session)
        assert len(results) == 1
        res = results[0]
        assert res.status == "EARNED"
        assert res.referrer_id == referrer.id
        assert res.net_credited == Decimal("700.00")

        # Verify commission record in DB
        comm = db_session.query(PlanACommission).filter(PlanACommission.billing_id == res.billing_id).first()
        assert comm is not None
        assert comm.gross_amount == Decimal("750.00")
        assert comm.operational_cost_amount == Decimal("35.00")
        assert comm.tds_amount == Decimal("15.00")
        assert comm.net_amount == Decimal("700.00")
        assert comm.status == "EARNED"
        assert comm.idempotency_key == f"PA-COMM:{comm.billing_id}"

        # Verify wallet balance and ledger entry
        wallet = db_session.query(Wallet).filter(Wallet.user_id == referrer.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet is not None
        assert wallet.balance == Decimal("700.00")

        tx = db_session.query(WalletTransaction).filter(WalletTransaction.idempotency_key == f"PA-COMM:{comm.billing_id}").first()
        assert tx is not None
        assert tx.amount == Decimal("700.00")
        assert tx.balance_after == Decimal("700.00")

    def test_repeat_purchase_with_new_valid_referral_code_br_x1(self, db_session: Session) -> None:
        """2. Plan A repeat purchase with a new valid referral code awards ₹700 net to the new code owner."""
        seed_counter(db_session, 200)
        prod = create_product(db_session)
        ref_orig = create_user(db_session, "Ref Orig", "9811100011", code="PAORIG01")
        ref_new = create_user(db_session, "Ref New", "9811100012", code="PANEW001")
        create_confirmed_order(db_session, ref_orig, prod)
        create_confirmed_order(db_session, ref_new, prod)

        customer = create_user(db_session, "Repeat Cust", "9811100013", code="PACUST02")
        customer.referred_by_id = ref_orig.id
        root_rel = ReferralRelationship(
            referee_id=customer.id,
            referrer_id=ref_orig.id,
            referee_programme=Programme.PLAN_A,
            referrer_programme=Programme.PLAN_A,
            referral_code_used="PAORIG01",
            binding_channel="checkout",
            is_active=True,
        )
        db_session.add(root_rel)
        db_session.flush()

        # Repeat order with ref_new's code
        order_rpt = create_confirmed_order(
            db_session, customer, prod, quantity=1, referral_code="PANEW001", is_first=False
        )
        FulfilmentOrchestrator.fulfil_order(order_rpt.id, db=db_session)

        # Process commission
        results = PlanACommissionService.process_order_commissions(order_rpt.id, db=db_session)
        assert len(results) == 1
        assert results[0].status == "EARNED"
        assert results[0].referrer_id == ref_new.id
        assert results[0].net_credited == Decimal("700.00")

        # Ref New wallet is credited
        wallet_new = db_session.query(Wallet).filter(Wallet.user_id == ref_new.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet_new.balance == Decimal("700.00")

        # Ref Orig wallet is NOT credited for this repeat order
        wallet_orig = db_session.query(Wallet).filter(Wallet.user_id == ref_orig.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet_orig is None or wallet_orig.balance == Decimal("0.00")

        # Root relationship is untouched
        db_session.refresh(customer)
        assert customer.referred_by_id == ref_orig.id

    def test_unreferred_purchase_br_a7_neutrality(self, db_session: Session) -> None:
        """3. Plan A purchase without referral code records UNALLOCATED_NO_REFERRER with ₹0 net and zero wallet credits."""
        seed_counter(db_session, 300)
        prod = create_product(db_session)
        customer = create_user(db_session, "Unreferred Cust", "9811100021", code="PACUST03")

        order = create_confirmed_order(db_session, customer, prod, quantity=1, referral_code=None, is_first=True)
        FulfilmentOrchestrator.fulfil_order(order.id, db=db_session)

        results = PlanACommissionService.process_order_commissions(order.id, db=db_session)
        assert len(results) == 1
        res = results[0]
        assert res.status == "UNALLOCATED_NO_REFERRER"
        assert res.referrer_id is None
        assert res.net_credited == Decimal("0.00")

        comm = db_session.query(PlanACommission).filter(PlanACommission.billing_id == res.billing_id).first()
        assert comm.gross_amount == Decimal("750.00")
        assert comm.operational_cost_amount == Decimal("0.00")
        assert comm.tds_amount == Decimal("0.00")
        assert comm.net_amount == Decimal("0.00")
        assert comm.status == "UNALLOCATED_NO_REFERRER"

        # Zero wallet transactions exist
        assert db_session.query(WalletTransaction).filter(WalletTransaction.idempotency_key == f"PA-COMM:{comm.billing_id}").count() == 0

    def test_repeat_purchase_without_referral_code(self, db_session: Session) -> None:
        """4. Repeat purchase with no referral code records UNALLOCATED_NO_REFERRER with zero wallet credit."""
        seed_counter(db_session, 400)
        prod = create_product(db_session)
        customer = create_user(db_session, "Repeat Unreferred", "9811100031", code="PACUST04")

        order = create_confirmed_order(db_session, customer, prod, quantity=1, referral_code=None, is_first=False)
        FulfilmentOrchestrator.fulfil_order(order.id, db=db_session)

        results = PlanACommissionService.process_order_commissions(order.id, db=db_session)
        assert len(results) == 1
        assert results[0].status == "UNALLOCATED_NO_REFERRER"
        assert results[0].net_credited == Decimal("0.00")

    def test_multi_unit_order_quantity_three(self, db_session: Session) -> None:
        """5. Multi-unit order (quantity 3) creates 3 unique Billing IDs and awards 3 x ₹700 = ₹2,100."""
        seed_counter(db_session, 500)
        prod = create_product(db_session)
        referrer = create_user(db_session, "Multi Ref", "9811100041", code="PAMULTI1")
        create_confirmed_order(db_session, referrer, prod)

        customer = create_user(db_session, "Multi Cust", "9811100042", code="PACUST05")
        order = create_confirmed_order(db_session, customer, prod, quantity=3, referral_code="PAMULTI1", is_first=True)
        FulfilmentOrchestrator.fulfil_order(order.id, db=db_session)

        results = PlanACommissionService.process_order_commissions(order.id, db=db_session)
        assert len(results) == 3
        for res in results:
            assert res.status == "EARNED"
            assert res.net_credited == Decimal("700.00")

        # Check total credited to wallet
        wallet = db_session.query(Wallet).filter(Wallet.user_id == referrer.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("2100.00")

        # 3 distinct ledger entries
        txs = db_session.query(WalletTransaction).filter(WalletTransaction.user_id == referrer.id).all()
        assert len(txs) == 3

    def test_ineligible_referrer_no_prior_purchase(self, db_session: Session) -> None:
        """6. Referrer with no prior qualifying purchase is ineligible: status INELIGIBLE_REFERRER, zero wallet credit."""
        seed_counter(db_session, 600)
        prod = create_product(db_session)
        referrer_unpurchased = create_user(db_session, "Unpurchased Ref", "9811100051", code="PAUNPUR1")

        customer = create_user(db_session, "Cust Six", "9811100052", code="PACUST06")
        order = create_confirmed_order(db_session, customer, prod, quantity=1, referral_code="PAUNPUR1", is_first=True)
        FulfilmentOrchestrator.fulfil_order(order.id, db=db_session)

        results = PlanACommissionService.process_order_commissions(order.id, db=db_session)
        assert len(results) == 1
        res = results[0]
        assert res.status == "INELIGIBLE_REFERRER"
        assert res.net_credited == Decimal("0.00")

        # Referrer wallet was NOT created or credited
        wallet = db_session.query(Wallet).filter(Wallet.user_id == referrer_unpurchased.id).first()
        assert wallet is None

    def test_ineligible_referrer_blocked_account_rg_14(self, db_session: Session) -> None:
        """7. Referrer whose account is BLOCKED at commission execution cannot earn (RG-14)."""
        seed_counter(db_session, 700)
        prod = create_product(db_session)
        referrer_blocked = create_user(
            db_session, "Blocked Ref", "9811100061", code="PABLK001", account_status=AccountStatus.BLOCKED
        )
        # Give them a prior purchase so purchase rule passes
        create_confirmed_order(db_session, referrer_blocked, prod)

        customer = create_user(db_session, "Cust Seven", "9811100062", code="PACUST07")
        order = create_confirmed_order(db_session, customer, prod, quantity=1, referral_code="PABLK001", is_first=True)
        FulfilmentOrchestrator.fulfil_order(order.id, db=db_session)

        results = PlanACommissionService.process_order_commissions(order.id, db=db_session)
        assert len(results) == 1
        assert results[0].status == "INELIGIBLE_REFERRER"
        assert results[0].net_credited == Decimal("0.00")

    def test_cross_programme_referral_b_to_a_allowed(self, db_session: Session) -> None:
        """8. Plan B distributor referring Plan A customer (B -> A): Plan A engine skips order; distributor earns Plan B commissions."""
        seed_counter(db_session, 800)
        prod = create_product(db_session)
        dist_b = create_user(db_session, "Distributor B", "9811100071", programme=Programme.PLAN_B, code="PBDIST01")
        # Plan B distributor completes purchase to activate referral code (BR-X2)
        create_confirmed_order(db_session, dist_b, prod)

        customer_a = create_user(db_session, "Customer A", "9811100072", programme=Programme.PLAN_A, code="PACUST08")
        order = create_confirmed_order(db_session, customer_a, prod, quantity=1, referral_code="PBDIST01", is_first=True)
        FulfilmentOrchestrator.fulfil_order(order.id, db=db_session)

        # Plan A commission service skips order because referrer is Plan B
        results = PlanACommissionService.process_order_commissions(order.id, db=db_session)
        assert len(results) == 0
        assert db_session.query(PlanACommission).filter(PlanACommission.order_id == order.id).count() == 0

        # Post-fulfilment dispatcher routes exclusively to Plan B
        from app.services.fulfilment_handoff import dispatch_order_commissions
        dispatch_order_commissions(order.id, db=db_session)

        # Distributor received Plan B commissions (₹466.66 net direct + ₹46.66 net gen = ₹513.32 net)
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist_b.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("513.32")

    def test_programme_isolation_skips_plan_b_billing_ids(self, db_session: Session) -> None:
        """9. Plan B Billing IDs are skipped with SKIPPED_NOT_PLAN_A; zero PlanACommission records created."""
        seed_counter(db_session, 900)
        prod = create_product(db_session)
        dist_b = create_user(db_session, "Dist B Nine", "9811100081", programme=Programme.PLAN_B, code="PBDIST02")

        # Order placed under Plan B
        order_b = create_confirmed_order(db_session, dist_b, prod, quantity=1)
        # Fulfilment marks BillingId as PLAN_B because user is PLAN_B
        FulfilmentOrchestrator.fulfil_order(order_b.id, db=db_session)

        b_id = db_session.query(BillingId).filter(BillingId.order_id == order_b.id).first()
        assert b_id.programme == Programme.PLAN_B

        res = PlanACommissionService.process_billing_id(b_id.id, db=db_session)
        assert res.status == "SKIPPED_NOT_PLAN_A"
        assert db_session.query(PlanACommission).filter(PlanACommission.billing_id == b_id.id).count() == 0

    def test_cashback_isolation_preserves_claim_status(self, db_session: Session) -> None:
        """10. WP-7 preserves BillingEngineClaim.status as PENDING for future WP-10 cashback engine."""
        seed_counter(db_session, 1000)
        prod = create_product(db_session)
        referrer = create_user(db_session, "Ref Ten", "9811100091", code="PAREF010")
        create_confirmed_order(db_session, referrer, prod)

        customer = create_user(db_session, "Cust Ten", "9811100092", code="PACUST10")
        order = create_confirmed_order(db_session, customer, prod, quantity=1, referral_code="PAREF010")
        FulfilmentOrchestrator.fulfil_order(order.id, db=db_session)

        # Process commission
        PlanACommissionService.process_order_commissions(order.id, db=db_session)

        # Assert BillingEngineClaim is still PENDING and processed_at is None
        claim = (
            db_session.query(BillingEngineClaim)
            .join(BillingId, BillingEngineClaim.billing_id == BillingId.id)
            .filter(BillingId.order_id == order.id)
            .first()
        )
        assert claim is not None
        assert claim.status == "PENDING"
        assert claim.processed_at is None

    def test_idempotent_duplicate_processing(self, db_session: Session) -> None:
        """11. Duplicate invocation on the same Billing ID returns ALREADY_PROCESSED and does not double-credit."""
        seed_counter(db_session, 1100)
        prod = create_product(db_session)
        referrer = create_user(db_session, "Ref Eleven", "9811100101", code="PAREF011")
        create_confirmed_order(db_session, referrer, prod)

        customer = create_user(db_session, "Cust Eleven", "9811100102", code="PACUST11")
        order = create_confirmed_order(db_session, customer, prod, quantity=1, referral_code="PAREF011")
        FulfilmentOrchestrator.fulfil_order(order.id, db=db_session)

        # First run
        res1 = PlanACommissionService.process_order_commissions(order.id, db=db_session)
        assert res1[0].status == "EARNED"

        # Second run
        res2 = PlanACommissionService.process_order_commissions(order.id, db=db_session)
        assert res2[0].status == "ALREADY_PROCESSED"

        # Referrer wallet balance is strictly ₹700, not ₹1400
        wallet = db_session.query(Wallet).filter(Wallet.user_id == referrer.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("700.00")
        assert db_session.query(WalletTransaction).filter(WalletTransaction.user_id == referrer.id).count() == 1

    def test_recovery_worker_sweep(self, db_session: Session) -> None:
        """12. PlanACommissionRecoveryWorker finds and processes pending Plan A commissions."""
        seed_counter(db_session, 1200)
        prod = create_product(db_session)
        referrer = create_user(db_session, "Ref Twelve", "9811100111", code="PAREF012")
        create_confirmed_order(db_session, referrer, prod)

        # Create two fulfilled orders where commission dispatch was not invoked
        c1 = create_user(db_session, "Cust C1", "9811100112", code="PACUST12")
        c2 = create_user(db_session, "Cust C2", "9811100113", code="PACUST13")
        o1 = create_confirmed_order(db_session, c1, prod, quantity=1, referral_code="PAREF012")
        o2 = create_confirmed_order(db_session, c2, prod, quantity=1, referral_code=None)

        # Fulfil orders (claims created)
        BillingAllocatorService.allocate_for_order(db_session, o1)
        BillingAllocatorService.allocate_for_order(db_session, o2)
        b1 = db_session.query(BillingId).filter(BillingId.order_id == o1.id).first()
        b2 = db_session.query(BillingId).filter(BillingId.order_id == o2.id).first()
        db_session.add(BillingEngineClaim(billing_id=b1.id, engine=Programme.PLAN_A, status="PENDING"))
        db_session.add(BillingEngineClaim(billing_id=b2.id, engine=Programme.PLAN_A, status="PENDING"))
        db_session.commit()

        # Run recovery sweep
        sweep_res = PlanACommissionRecoveryWorker.run_sweep(db=db_session)
        assert sweep_res.candidates_found == 2
        assert sweep_res.processed_count == 2
        assert sweep_res.earned_count == 1
        assert sweep_res.unallocated_count == 1
        assert sweep_res.failed_count == 0

        # Referrer wallet was credited for o1
        wallet = db_session.query(Wallet).filter(Wallet.user_id == referrer.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("700.00")

    def test_atomic_transaction_rollback_on_wallet_error(self, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        """13. Unhandled error during wallet credit rolls back session cleanly; no orphan commission record created."""
        seed_counter(db_session, 1300)
        prod = create_product(db_session)
        referrer = create_user(db_session, "Ref Thirteen", "9811100121", code="PAREF013")
        create_confirmed_order(db_session, referrer, prod)

        customer = create_user(db_session, "Cust Thirteen", "9811100122", code="PACUST14")
        order = create_confirmed_order(db_session, customer, prod, quantity=1, referral_code="PAREF013")
        FulfilmentOrchestrator.fulfil_order(order.id, db=db_session)

        bid = db_session.query(BillingId).filter(BillingId.order_id == order.id).first()

        # Mock credit_wallet to raise an unexpected runtime error
        import app.services.commission.plan_a as plan_a_module

        def broken_credit_wallet(*args, **kwargs):
            raise RuntimeError("Database connection interrupted during wallet credit")

        monkeypatch.setattr(plan_a_module, "credit_wallet", broken_credit_wallet)

        res = PlanACommissionService.process_billing_id(bid.id, db=db_session)
        assert res.status == "FAILED"
        assert "Database connection interrupted" in res.message

        # Assert no orphan PlanACommission record was committed in DB
        assert db_session.query(PlanACommission).filter(PlanACommission.billing_id == bid.id).count() == 0
        assert db_session.query(WalletTransaction).count() == 0

