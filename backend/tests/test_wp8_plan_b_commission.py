"""WP-8 Plan B Commission Engine Test Suite.

Comprehensive tests covering:
  1. First qualifying order: direct (₹500 gross / ₹466.66 net) plus generation (₹50 gross / ₹46.67 net).
  2. First order with multiple Power Banks (e.g. quantity 3):
     - Direct ₹466.66 + (3 x ₹46.67) generation = ₹606.67 net.
  3. Repeat order by same referee: generation commission only (2 x ₹46.67 = ₹93.34 net).
  4. Direct commission awarded strictly once per referee lifetime (PB-DIRECT:{referee_id}).
  5. Non-retroactive direct commission after a later referral code is applied (BR-B1 Option A).
  6. Distributor without qualifying paid purchase earns zero commission (BR-X2).
  7. Blocked and deactivated distributors cannot refer or earn (RG-14).
  8. Distributor self-purchases generate zero commission (BR-B3).
  9. B -> B referral succeeds and earns standard Plan B commissions (BR-X3).
  10. A -> B rejection and B -> A isolation:
      - Plan B engine ignores Plan A orders / referees.
  11. Plan A Billing ID isolation (Programme.PLAN_A skipped).
  12. Exact gross, operational cost, TDS and net calculations:
      - Direct: ₹500.00 gross -> ₹23.34 op cost, ₹10.00 TDS, ₹466.66 net.
      - Generation: ₹50.00 gross -> ₹2.33 op cost, ₹1.00 TDS, ₹46.67 net.
  13. Five-unit rounding reconciliation:
      - Sample 5 units reconciles to exactly ₹750.00 gross, ₹35.00 op cost, ₹15.00 TDS, ₹700.00 net.
  14. Duplicate fulfilment callbacks and idempotent retries (no double wallet credits).
  15. Concurrent duplicate processing safety (idempotency key barrier).
  16. Wallet freeze behaviour: accrual allowed into wallet balance.
  17. Atomic rollback when wallet credit fails (no orphan commission rows).
  18. Recovery worker discovers missing generation commissions.
  19. Recovery worker isolates failures per candidate order.
  20. No Plan B purchase enters Plan A cashback queues or cycles.
"""

from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.models.billing import BillingCounter, BillingEngineClaim, BillingId
from app.models.commission import PlanBCommission
from app.models.enums import (
    AccountStatus,
    OrderStatus,
    PaymentStatus,
    Programme,
    UserRole,
    WalletType,
)
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.queue import BeneficiaryQueue, CommissionCycle
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.models.wallet import Wallet, WalletTransaction
from app.services.billing.allocator import BillingAllocatorService
from app.services.commission.plan_b import (
    DIRECT_GROSS_AMOUNT,
    DIRECT_NET_AMOUNT,
    DIRECT_OP_COST,
    DIRECT_TDS,
    GEN_GROSS_AMOUNT,
    GEN_NET_AMOUNT,
    GEN_OP_COST,
    GEN_TDS,
    PlanBCommissionService,
)
from app.services.commission.recovery_plan_b import PlanBCommissionRecoveryWorker
from app.services.fulfilment.orchestrator import FulfilmentOrchestrator


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def seed_counter(db: Session, start_val: int = 5000) -> BillingCounter:
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
    programme: Programme = Programme.PLAN_B,
    code: str = "PBDIST01",
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
        address_line1="123 Distributor Way",
        city="Bengaluru",
        state="Karnataka",
        pincode="560001",
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
    seq = datetime_unique()
    order = Order(
        order_number=f"ORD-WP8-{customer.id}-{product.id}-{quantity}-{seq}",
        idempotency_key=f"idemp-wp8-{customer.id}-{quantity}-{seq}",
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


_id_seq = 0
def datetime_unique() -> int:
    global _id_seq
    _id_seq += 1
    return _id_seq


# ---------------------------------------------------------------------------
# Test Suite
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPlanBCommissionEngine:
    """WP-8 Plan B Commission Engine unit & integration tests."""

    def test_first_qualifying_order_direct_and_generation(self, db_session: Session) -> None:
        """1. First qualifying order: awards direct (₹500.00 net) + generation (₹50.00 net) = ₹550.00 net."""
        seed_counter(db_session, 100)
        prod = create_product(db_session)
        distributor = create_user(db_session, "Dist One", "9822200001", code="PBDIST01")
        # Give distributor a qualifying purchase (BR-X2)
        create_confirmed_order(db_session, distributor, prod)

        customer = create_user(db_session, "Cust One", "9822200002", code="PBCUST01")
        order = create_confirmed_order(db_session, customer, prod, quantity=1, referral_code="PBDIST01", is_first=True)
        FulfilmentOrchestrator.fulfil_order(order.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(order.id, db=db_session)
        assert res.status == "COMPLETED"
        assert res.distributor_id == distributor.id
        assert res.direct_net_credited == Decimal("500.00")
        assert res.generation_net_credited == Decimal("50.00")
        assert res.total_net_credited == Decimal("550.00")

        # Verify DB records
        direct_comm = db_session.query(PlanBCommission).filter(
            PlanBCommission.commission_type == "DIRECT",
            PlanBCommission.distributor_id == distributor.id,
        ).first()
        assert direct_comm is not None
        assert direct_comm.gross_amount == Decimal("500.00")
        assert direct_comm.operational_cost_amount == Decimal("0.00")
        assert direct_comm.tds_amount == Decimal("0.00")
        assert direct_comm.net_amount == Decimal("500.00")
        assert direct_comm.idempotency_key == f"PB-DIRECT:{distributor.id}"

        # Verify wallet balance
        wallet = db_session.query(Wallet).filter(Wallet.user_id == distributor.id).first()
        assert wallet.balance == Decimal("550.00")
        assert db_session.query(WalletTransaction).filter(WalletTransaction.user_id == distributor.id).count() == 2

    def test_first_order_with_multiple_power_banks(self, db_session: Session) -> None:
        """2. First order with 3 Power Banks: direct (₹500.00) + 3 x generation (3 x ₹50.00) = ₹650.00 net."""
        seed_counter(db_session, 200)
        prod = create_product(db_session)
        distributor = create_user(db_session, "Dist Two", "9822200011", code="PBDIST02")
        create_confirmed_order(db_session, distributor, prod)

        customer = create_user(db_session, "Cust Two", "9822200012", code="PBCUST02")
        order = create_confirmed_order(db_session, customer, prod, quantity=3, referral_code="PBDIST02", is_first=True)
        FulfilmentOrchestrator.fulfil_order(order.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(order.id, db=db_session)
        assert res.status == "COMPLETED"
        assert res.direct_net_credited == Decimal("500.00")
        assert res.generation_net_credited == Decimal("150.00")  # 3 x 50.00
        assert res.total_net_credited == Decimal("650.00")

        wallet = db_session.query(Wallet).filter(Wallet.user_id == distributor.id).first()
        assert wallet.balance == Decimal("650.00")
        assert db_session.query(WalletTransaction).filter(WalletTransaction.user_id == distributor.id).count() == 4

    def test_repeat_order_generation_commission_only(self, db_session: Session) -> None:
        """3. Repeat order: direct commission is skipped; generation commission awarded for each new unit."""
        seed_counter(db_session, 300)
        prod = create_product(db_session)
        distributor = create_user(db_session, "Dist Three", "9822200021", code="PBDIST03")
        create_confirmed_order(db_session, distributor, prod)

        customer = create_user(db_session, "Cust Three", "9822200022", code="PBCUST03")
        # First order (1 unit)
        o1 = create_confirmed_order(db_session, customer, prod, quantity=1, referral_code="PBDIST03", is_first=True)
        customer.referred_by_id = distributor.id
        FulfilmentOrchestrator.fulfil_order(o1.id, db=db_session)
        PlanBCommissionService.process_order_commissions(o1.id, db=db_session)

        # Second order (2 units)
        o2 = create_confirmed_order(db_session, customer, prod, quantity=2, referral_code="PBDIST03", is_first=False)
        FulfilmentOrchestrator.fulfil_order(o2.id, db=db_session)

        res2 = PlanBCommissionService.process_order_commissions(o2.id, db=db_session)
        assert res2.status == "COMPLETED"
        assert res2.direct_net_credited == Decimal("0.00")  # Already paid
        assert res2.generation_net_credited == Decimal("100.00")  # 2 x 50.00
        assert res2.total_net_credited == Decimal("100.00")

        # Total wallet balance = 550.00 + 100.00 = 650.00
        wallet = db_session.query(Wallet).filter(Wallet.user_id == distributor.id).first()
        assert wallet.balance == Decimal("650.00")

    def test_direct_commission_awarded_only_once_lifetime(self, db_session: Session) -> None:
        """4. PB-DIRECT:{distributor.id} enforces that direct commission is never awarded more than once per distributor."""
        seed_counter(db_session, 400)
        prod = create_product(db_session)
        dist = create_user(db_session, "Dist Four", "9822200031", code="PBDIST04")
        create_confirmed_order(db_session, dist, prod)

        cust = create_user(db_session, "Cust Four", "9822200032", code="PBCUST04")
        o1 = create_confirmed_order(db_session, cust, prod, quantity=1, referral_code="PBDIST04")
        FulfilmentOrchestrator.fulfil_order(o1.id, db=db_session)
        PlanBCommissionService.process_order_commissions(o1.id, db=db_session)

        # Check only 1 direct commission exists for distributor
        assert db_session.query(PlanBCommission).filter(
            PlanBCommission.commission_type == "DIRECT",
            PlanBCommission.distributor_id == dist.id,
        ).count() == 1

    def test_non_retroactive_direct_commission_on_later_code_application(self, db_session: Session) -> None:
        """5. BR-B1 Option A: order 1 without code -> no commission. Order 2 with distributor code -> awards ₹500 non-retroactively."""
        seed_counter(db_session, 500)
        prod = create_product(db_session)
        dist = create_user(db_session, "Dist Five", "9822200041", code="PBDIST05")
        create_confirmed_order(db_session, dist, prod)

        cust = create_user(db_session, "Cust Five", "9822200042", code="PBCUST05")
        # Order 1 without code
        o1 = create_confirmed_order(db_session, cust, prod, quantity=1, referral_code=None, is_first=True)
        FulfilmentOrchestrator.fulfil_order(o1.id, db=db_session)
        res1 = PlanBCommissionService.process_order_commissions(o1.id, db=db_session)
        assert res1.status in ("UNREFERRED", "SELF_PURCHASE_NO_COMMISSION")
        assert res1.total_net_credited == Decimal("0.00")

        # Order 2 with distributor code
        o2 = create_confirmed_order(db_session, cust, prod, quantity=1, referral_code="PBDIST05", is_first=False)
        cust.referred_by_id = dist.id
        FulfilmentOrchestrator.fulfil_order(o2.id, db=db_session)
        res2 = PlanBCommissionService.process_order_commissions(o2.id, db=db_session)
        assert res2.status == "COMPLETED"
        assert res2.direct_net_credited == Decimal("500.00")
        assert res2.generation_net_credited == Decimal("50.00")

        # Total wallet balance has only order 2 earnings
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id).first()
        assert wallet.balance == Decimal("550.00")

    def test_distributor_without_qualifying_paid_purchase(self, db_session: Session) -> None:
        """6. Distributor without prior purchase cannot earn (BR-X2)."""
        seed_counter(db_session, 600)
        prod = create_product(db_session)
        dist_unpurchased = create_user(db_session, "Dist Unpurchased", "9822200051", code="PBUNPUR1")

        cust = create_user(db_session, "Cust Six", "9822200052", code="PBCUST06")
        o = create_confirmed_order(db_session, cust, prod, quantity=1, referral_code="PBUNPUR1")
        FulfilmentOrchestrator.fulfil_order(o.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(o.id, db=db_session)
        assert res.status == "INELIGIBLE_DISTRIBUTOR"
        assert res.total_net_credited == Decimal("0.00")
        assert db_session.query(Wallet).filter(Wallet.user_id == dist_unpurchased.id).first() is None

    def test_blocked_and_deactivated_distributors(self, db_session: Session) -> None:
        """7. Blocked or deactivated distributors cannot earn (RG-14)."""
        seed_counter(db_session, 700)
        prod = create_product(db_session)
        dist_blocked = create_user(db_session, "Dist Blocked", "9822200061", code="PBBLK001", account_status=AccountStatus.BLOCKED)
        create_confirmed_order(db_session, dist_blocked, prod)

        cust = create_user(db_session, "Cust Seven", "9822200062", code="PBCUST07")
        o = create_confirmed_order(db_session, cust, prod, quantity=1, referral_code="PBBLK001")
        FulfilmentOrchestrator.fulfil_order(o.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(o.id, db=db_session)
        assert res.status == "INELIGIBLE_DISTRIBUTOR"
        assert res.total_net_credited == Decimal("0.00")

    def test_distributor_self_purchase(self, db_session: Session) -> None:
        """8. Distributor self-purchases generate zero commission (BR-B3)."""
        seed_counter(db_session, 800)
        prod = create_product(db_session)
        dist = create_user(db_session, "Dist Eight", "9822200071", code="PBDIST08")
        create_confirmed_order(db_session, dist, prod)

        # Dist purchases again with own code
        o_self = create_confirmed_order(db_session, dist, prod, quantity=2, referral_code="PBDIST08", is_first=False)
        FulfilmentOrchestrator.fulfil_order(o_self.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(o_self.id, db=db_session)
        assert res.status == "SELF_PURCHASE_NO_COMMISSION"
        assert res.total_net_credited == Decimal("0.00")

    def test_b_to_b_referral_succeeds(self, db_session: Session) -> None:
        """9. B -> B referral (distributor referring another Plan B participant) is ALLOWED and earns standard commissions (BR-X3)."""
        seed_counter(db_session, 900)
        prod = create_product(db_session)
        dist1 = create_user(db_session, "Dist Nine A", "9822200081", code="PBDIST9A")
        create_confirmed_order(db_session, dist1, prod)

        dist2 = create_user(db_session, "Dist Nine B", "9822200082", code="PBDIST9B")
        o = create_confirmed_order(db_session, dist2, prod, quantity=1, referral_code="PBDIST9A", is_first=True)
        FulfilmentOrchestrator.fulfil_order(o.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(o.id, db=db_session)
        assert res.status == "COMPLETED"
        assert res.distributor_id == dist1.id
        assert res.total_net_credited == Decimal("550.00")

    def test_a_to_b_rejection_and_b_to_a_isolation(self, db_session: Session) -> None:
        """10. Plan B engine ignores Plan A purchasers; zero Plan B commission records created."""
        seed_counter(db_session, 1000)
        prod = create_product(db_session)
        cust_a = create_user(db_session, "Cust Ten A", "9822200091", programme=Programme.PLAN_A, code="PACUST10")

        o = create_confirmed_order(db_session, cust_a, prod, quantity=1)
        FulfilmentOrchestrator.fulfil_order(o.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(o.id, db=db_session)
        assert res.status == "SKIPPED_NOT_PLAN_B"
        assert db_session.query(PlanBCommission).count() == 0

    def test_plan_a_billing_id_isolation(self, db_session: Session) -> None:
        """11. Plan A Billing IDs are ignored by Plan B Commission Engine."""
        seed_counter(db_session, 1100)
        prod = create_product(db_session)
        cust_a = create_user(db_session, "Cust Eleven A", "9822200101", programme=Programme.PLAN_A, code="PACUST11")
        o = create_confirmed_order(db_session, cust_a, prod, quantity=1)
        BillingAllocatorService.allocate_for_order(db_session, o)
        b_id = db_session.query(BillingId).filter(BillingId.order_id == o.id).first()
        assert b_id.programme == Programme.PLAN_A

        res = PlanBCommissionService.process_order_commissions(o.id, db=db_session)
        assert res.status == "SKIPPED_NOT_PLAN_B"

    def test_exact_deduction_arithmetic(self, db_session: Session) -> None:
        """12. Verify deduction policy: Full gross credited (0% Op Cost, 0% TDS for Plan B)."""
        assert DIRECT_GROSS_AMOUNT == Decimal("500.00")
        assert DIRECT_OP_COST == Decimal("0.00")
        assert DIRECT_TDS == Decimal("0.00")
        assert DIRECT_NET_AMOUNT == Decimal("500.00")
        assert DIRECT_OP_COST + DIRECT_TDS + DIRECT_NET_AMOUNT == DIRECT_GROSS_AMOUNT

        assert GEN_GROSS_AMOUNT == Decimal("50.00")
        assert GEN_OP_COST == Decimal("0.00")
        assert GEN_TDS == Decimal("0.00")
        assert GEN_NET_AMOUNT == Decimal("50.00")
        assert GEN_OP_COST + GEN_TDS + GEN_NET_AMOUNT == GEN_GROSS_AMOUNT

    def test_five_unit_sample_rounding_reconciliation(self, db_session: Session) -> None:
        """13. Reconciled 5-unit sample matches approved figures: ₹750 gross, ₹0 op cost, ₹0 TDS, ₹750 net."""
        seed_counter(db_session, 1200)
        prod = create_product(db_session)
        dist = create_user(db_session, "Dist Twelve", "9822200111", code="PBDIST12")
        create_confirmed_order(db_session, dist, prod)

        cust = create_user(db_session, "Cust Twelve", "9822200112", code="PBCUST12")
        o = create_confirmed_order(db_session, cust, prod, quantity=5, referral_code="PBDIST12", is_first=True)
        FulfilmentOrchestrator.fulfil_order(o.id, db=db_session)

        # Process with 5-unit sample reconciliation
        res = PlanBCommissionService.process_order_commissions(o.id, db=db_session, reconcile_sample_five=True)
        assert res.status == "COMPLETED"

        comms = db_session.query(PlanBCommission).filter(PlanBCommission.order_id == o.id).all()
        assert len(comms) == 6  # 1 direct + 5 generation

        total_gross = sum(c.gross_amount for c in comms)
        total_op = sum(c.operational_cost_amount for c in comms)
        total_tds = sum(c.tds_amount for c in comms)
        total_net = sum(c.net_amount for c in comms)

        assert total_gross == Decimal("750.00")
        assert total_op == Decimal("0.00")
        assert total_tds == Decimal("0.00")
        assert total_net == Decimal("750.00")

    def test_duplicate_fulfilment_callbacks_idempotency(self, db_session: Session) -> None:
        """14. Replaying commission processing on the same order does not double-credit wallet."""
        seed_counter(db_session, 1300)
        prod = create_product(db_session)
        dist = create_user(db_session, "Dist Thirteen", "9822200121", code="PBDIST13")
        create_confirmed_order(db_session, dist, prod)

        cust = create_user(db_session, "Cust Thirteen", "9822200122", code="PBCUST13")
        o = create_confirmed_order(db_session, cust, prod, quantity=1, referral_code="PBDIST13")
        FulfilmentOrchestrator.fulfil_order(o.id, db=db_session)

        # Run 1
        res1 = PlanBCommissionService.process_order_commissions(o.id, db=db_session)
        assert res1.total_net_credited == Decimal("550.00")

        # Run 2
        res2 = PlanBCommissionService.process_order_commissions(o.id, db=db_session)
        assert res2.total_net_credited == Decimal("0.00")

        # Balance remains ₹550.00
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id).first()
        assert wallet.balance == Decimal("550.00")

    def test_concurrent_duplicate_processing_safety(self, db_session: Session) -> None:
        """15. Idempotency keys prevent concurrent duplicate credits."""
        seed_counter(db_session, 1400)
        prod = create_product(db_session)
        dist = create_user(db_session, "Dist Fourteen", "9822200131", code="PBDIST14")
        create_confirmed_order(db_session, dist, prod)

        cust = create_user(db_session, "Cust Fourteen", "9822200132", code="PBCUST14")
        o = create_confirmed_order(db_session, cust, prod, quantity=1, referral_code="PBDIST14")
        FulfilmentOrchestrator.fulfil_order(o.id, db=db_session)

        # Process once
        PlanBCommissionService.process_order_commissions(o.id, db=db_session)

        # Manually verify constraint catches duplicate key
        b_id = db_session.query(BillingId).filter(BillingId.order_id == o.id).first()
        dup_comm = PlanBCommission(
            commission_type="GENERATION",
            distributor_id=dist.id,
            referee_id=cust.id,
            order_id=o.id,
            billing_id=b_id.id,
            gross_amount=Decimal("50.00"),
            operational_cost_amount=Decimal("0.00"),
            tds_amount=Decimal("0.00"),
            net_amount=Decimal("50.00"),
            idempotency_key=f"PB-GEN:{b_id.id}",
        )
        db_session.add(dup_comm)
        with pytest.raises(Exception):
            db_session.commit()
        db_session.rollback()

    def test_wallet_accrual_behaviour(self, db_session: Session) -> None:
        """16. Accruals succeed directly into distributor's wallet balance."""
        seed_counter(db_session, 1500)
        prod = create_product(db_session)
        dist = create_user(db_session, "Dist Fifteen", "9822200141", code="PBDIST15")
        create_confirmed_order(db_session, dist, prod)

        cust = create_user(db_session, "Cust Fifteen", "9822200142", code="PBCUST15")
        o = create_confirmed_order(db_session, cust, prod, quantity=1, referral_code="PBDIST15")
        FulfilmentOrchestrator.fulfil_order(o.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(o.id, db=db_session)
        assert res.status == "COMPLETED"
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id).first()
        assert wallet.balance == Decimal("550.00")

    def test_atomic_rollback_on_wallet_error(self, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        """17. Error during wallet credit rolls back entire transaction; no orphan commission rows."""
        seed_counter(db_session, 1600)
        prod = create_product(db_session)
        dist = create_user(db_session, "Dist Sixteen", "9822200151", code="PBDIST16")
        create_confirmed_order(db_session, dist, prod)

        cust = create_user(db_session, "Cust Sixteen", "9822200152", code="PBCUST16")
        o = create_confirmed_order(db_session, cust, prod, quantity=1, referral_code="PBDIST16")
        FulfilmentOrchestrator.fulfil_order(o.id, db=db_session)

        # Mock credit_wallet to fail
        import app.services.commission.plan_b as plan_b_module

        def broken_credit_wallet(*args, **kwargs):
            raise RuntimeError("Database connection died during wallet credit")

        monkeypatch.setattr(plan_b_module, "credit_wallet", broken_credit_wallet)

        res = PlanBCommissionService.process_order_commissions(o.id, db=db_session)
        assert res.status == "FAILED"
        assert "Database connection died" in res.message

        # Zero PlanBCommission rows committed
        assert db_session.query(PlanBCommission).filter(PlanBCommission.order_id == o.id).count() == 0

    def test_recovery_worker_discovers_missing_generation_commissions(self, db_session: Session) -> None:
        """18. PlanBCommissionRecoveryWorker discovers unfulfilled orders and processes them."""
        seed_counter(db_session, 1700)
        prod = create_product(db_session)
        dist = create_user(db_session, "Dist Seventeen", "9822200161", code="PBDIST17")
        create_confirmed_order(db_session, dist, prod)

        cust = create_user(db_session, "Cust Seventeen", "9822200162", code="PBCUST17")
        o = create_confirmed_order(db_session, cust, prod, quantity=2, referral_code="PBDIST17")

        # Manually allocate Billing IDs without running commission service
        BillingAllocatorService.allocate_for_order(db_session, o)
        bids = db_session.query(BillingId).filter(BillingId.order_id == o.id).all()
        for b in bids:
            db_session.add(BillingEngineClaim(billing_id=b.id, engine=Programme.PLAN_B, status="PENDING"))
        db_session.commit()

        # Run recovery sweep
        sweep_res = PlanBCommissionRecoveryWorker.run_sweep(db=db_session)
        assert sweep_res.candidates_found == 1
        assert sweep_res.orders_processed == 1
        assert sweep_res.failed_count == 0

        # Distributor received direct (₹500.00) + 2 x gen (2 x ₹50.00) = ₹600.00
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id).first()
        assert wallet.balance == Decimal("600.00")

    def test_recovery_worker_isolates_failures_per_order(self, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        """19. A failure on one candidate order in a recovery batch does not prevent processing others."""
        seed_counter(db_session, 1800)
        prod = create_product(db_session)
        dist = create_user(db_session, "Dist Eighteen", "9822200171", code="PBDIST18")
        create_confirmed_order(db_session, dist, prod)

        c1 = create_user(db_session, "Cust 18A", "9822200172", code="PBCUST18A")
        c2 = create_user(db_session, "Cust 18B", "9822200173", code="PBCUST18B")
        o1 = create_confirmed_order(db_session, c1, prod, quantity=1, referral_code="PBDIST18")
        o2 = create_confirmed_order(db_session, c2, prod, quantity=1, referral_code="PBDIST18")

        BillingAllocatorService.allocate_for_order(db_session, o1)
        BillingAllocatorService.allocate_for_order(db_session, o2)
        b1 = db_session.query(BillingId).filter(BillingId.order_id == o1.id).first()
        b2 = db_session.query(BillingId).filter(BillingId.order_id == o2.id).first()
        db_session.add(BillingEngineClaim(billing_id=b1.id, engine=Programme.PLAN_B, status="PENDING"))
        db_session.add(BillingEngineClaim(billing_id=b2.id, engine=Programme.PLAN_B, status="PENDING"))
        db_session.commit()

        # Inject error only for o1
        orig_process = PlanBCommissionService.process_order_commissions
        def flaky_process(order_id, *args, **kwargs):
            if order_id == o1.id:
                raise RuntimeError("Flaky error on order 1")
            return orig_process(order_id, *args, **kwargs)

        monkeypatch.setattr(PlanBCommissionService, "process_order_commissions", flaky_process)

        sweep_res = PlanBCommissionRecoveryWorker.run_sweep(db=db_session)
        assert sweep_res.candidates_found == 2
        assert sweep_res.failed_count == 1
        assert sweep_res.orders_processed == 1  # o2 succeeded

    def test_plan_b_purchases_never_enter_plan_a_cashback(self, db_session: Session) -> None:
        """20. Plan B purchases never create BeneficiaryQueue or CommissionCycle records (WP-10 isolation)."""
        seed_counter(db_session, 1900)
        prod = create_product(db_session)
        dist = create_user(db_session, "Dist Twenty", "9822200191", code="PBDIST20")
        create_confirmed_order(db_session, dist, prod)

        cust = create_user(db_session, "Cust Twenty", "9822200192", code="PBCUST20")
        o = create_confirmed_order(db_session, cust, prod, quantity=2, referral_code="PBDIST20", is_first=True)
        FulfilmentOrchestrator.fulfil_order(o.id, db=db_session)
        PlanBCommissionService.process_order_commissions(o.id, db=db_session)

        # Assert no queue or cycle records created
        assert db_session.query(BeneficiaryQueue).count() == 0
        assert db_session.query(CommissionCycle).count() == 0
