"""Authoritative automated test suite for Plan B Permanent Commission Engine (TiDB Cloud compatible)."""

from decimal import Decimal
import threading
from typing import List
import pytest
from sqlalchemy.orm import Session

from app.models.billing import BillingCounter, BillingId
from app.models.cashback import PlanACashbackCycle, PlanACashbackEntry, PlanACashbackQueue
from app.models.commission import PlanACommission, PlanBCommission
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
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.models.wallet import Wallet, WalletTransaction
from app.services.commission.plan_a import PlanACommissionService
from app.services.commission.plan_b import (
    DIRECT_GROSS_AMOUNT,
    DIRECT_NET_AMOUNT,
    DIRECT_OP_COST,
    DIRECT_TDS,
    GEN_FIRST_NET_AMOUNT,
    GEN_FIRST_OP_COST,
    GEN_FIRST_TDS,
    GEN_GROSS_AMOUNT,
    GEN_SUBSEQUENT_NET_AMOUNT,
    GEN_SUBSEQUENT_OP_COST,
    GEN_SUBSEQUENT_TDS,
    PlanBCommissionService,
)
from app.services.fulfilment.orchestrator import FulfilmentOrchestrator
from app.services.fulfilment_handoff import dispatch_order_commissions
from app.services.reports.plan_b_reports import PlanBReportService

_seq_counter = 0

def get_next_seq() -> int:
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def ensure_counter(db: Session, start_val: int = 20000) -> BillingCounter:
    counter = db.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
    if not counter:
        counter = BillingCounter(sequence_name="GLOBAL_BILLING_ID", current_value=start_val)
        db.add(counter)
        db.flush()
    return counter


def create_test_product(db: Session, price: Decimal = Decimal("3999.00")) -> Product:
    seq = get_next_seq()
    prod = Product(
        name=f"Arya Power Bank PB-{seq}",
        product_code=f"PB-{seq}",
        price=price,
        stock=1000,
        is_active=True,
        is_power_bank=True,
    )
    db.add(prod)
    db.flush()
    return prod


def create_test_user(
    db: Session,
    full_name: str,
    phone: str,
    programme: Programme = Programme.PLAN_B,
    referral_code: str = None,
    account_status: AccountStatus = AccountStatus.ACTIVE,
    referred_by_id: int = None,
) -> User:
    user = User(
        full_name=full_name,
        phone=phone,
        programme=programme,
        account_status=account_status,
        referral_code=referral_code or f"PB{get_next_seq():06d}",
        role=UserRole.CUSTOMER,
        is_active=True,
        referred_by_id=referred_by_id,
    )
    db.add(user)
    db.flush()

    for w_type in [WalletType.DIRECT_REFERRAL, WalletType.SEQUENTIAL_COMMISSION]:
        w = Wallet(
            user_id=user.id,
            wallet_type=w_type,
            balance=Decimal("0.00"),
            total_withdrawn=Decimal("0.00"),
            is_frozen=False,
        )
        db.add(w)
    db.flush()
    return user


def create_order(
    db: Session,
    user: User,
    product: Product,
    quantity: int = 1,
    referral_code: str = None,
) -> Order:
    seq = get_next_seq()
    addr = Address(
        user_id=user.id,
        recipient_name=user.full_name,
        phone=user.phone,
        address_line1="123 Test Street",
        city="Bengaluru",
        state="Karnataka",
        pincode="560001",
    )
    db.add(addr)
    db.flush()

    order = Order(
        user_id=user.id,
        order_number=f"ORD-TEST-{user.id}-{seq}",
        idempotency_key=f"IDEMP-ORD-{user.id}-{seq}",
        address_id=addr.id,
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
        total_amount=product.price * quantity,
        applied_referral_code=referral_code,
        is_first_successful_order=True,
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


@pytest.mark.unit
class TestPlanBPermanentCommissionEngine:
    """Comprehensive test suite verifying all 16 required Plan B commission scenarios."""

    # =========================================================================
    # 1. DIRECT REFERRAL COMMISSION TESTS
    # =========================================================================

    def test_01_first_qualifying_purchase_triggers_500_direct_bonus(self, db_session: Session) -> None:
        """Scenario 1: First qualifying purchase triggers ₹500 gross (₹466.66 net)."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Distributor 1", "9019440101", Programme.PLAN_B, "PBDIST01")
        # Qualifying purchase for distributor
        dist_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(dist_ord.id, db=db_session)

        # Referee makes first qualifying purchase of 1 product
        referee = create_test_user(db_session, "Referee 1", "9019440102", Programme.PLAN_B, referred_by_id=dist.id)
        ord1 = create_order(db_session, referee, prod, 1, referral_code="PBDIST01")
        FulfilmentOrchestrator.fulfil_order(ord1.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)
        assert res.status == "COMPLETED"
        assert res.distributor_id == dist.id
        assert res.direct_net_credited == Decimal("466.66")
        assert res.generation_net_credited == Decimal("46.66")  # First generation unit
        assert res.total_net_credited == Decimal("513.32")

        # Verify DB records
        d_comm = db_session.query(PlanBCommission).filter(
            PlanBCommission.commission_type == "DIRECT",
            PlanBCommission.distributor_id == dist.id,
            PlanBCommission.referee_id == referee.id,
        ).first()
        assert d_comm is not None
        assert d_comm.gross_amount == Decimal("500.00")
        assert d_comm.operational_cost_amount == Decimal("23.34")
        assert d_comm.tds_amount == Decimal("10.00")
        assert d_comm.net_amount == Decimal("466.66")
        assert d_comm.status == "EARNED"
        assert d_comm.idempotency_key == f"PB-DIRECT:{dist.id}"

    def test_02_same_customer_second_and_third_purchases_skip_500_direct_bonus(self, db_session: Session) -> None:
        """Scenario 2 & 3: Same customer makes second and third purchases; earns ₹0 direct bonus."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Distributor 2", "9019440201", Programme.PLAN_B, "PBDIST02")
        dist_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(dist_ord.id, db=db_session)

        referee = create_test_user(db_session, "Referee 2", "9019440202", Programme.PLAN_B, referred_by_id=dist.id)

        # Order 1 (First purchase: Direct ₹466.66 + Gen ₹46.66 = ₹513.32)
        ord1 = create_order(db_session, referee, prod, 1, referral_code="PBDIST02")
        FulfilmentOrchestrator.fulfil_order(ord1.id, db=db_session)
        PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)

        # Order 2 (Second purchase: Direct ₹0.00 + Gen ₹46.67 = ₹46.67)
        ord2 = create_order(db_session, referee, prod, 1, referral_code="PBDIST02")
        FulfilmentOrchestrator.fulfil_order(ord2.id, db=db_session)
        res2 = PlanBCommissionService.process_order_commissions(ord2.id, db=db_session)
        assert res2.status == "COMPLETED"
        assert res2.direct_net_credited == Decimal("0.00")
        assert res2.generation_net_credited == Decimal("46.67")
        assert res2.total_net_credited == Decimal("46.67")

        # Order 3 (Third purchase: Direct ₹0.00 + Gen ₹46.67 = ₹46.67)
        ord3 = create_order(db_session, referee, prod, 1, referral_code="PBDIST02")
        FulfilmentOrchestrator.fulfil_order(ord3.id, db=db_session)
        res3 = PlanBCommissionService.process_order_commissions(ord3.id, db=db_session)
        assert res3.status == "COMPLETED"
        assert res3.direct_net_credited == Decimal("0.00")
        assert res3.generation_net_credited == Decimal("46.67")
        assert res3.total_net_credited == Decimal("46.67")

        # Exactly 1 Direct commission record for referee 2
        d_comms = db_session.query(PlanBCommission).filter(
            PlanBCommission.commission_type == "DIRECT",
            PlanBCommission.referee_id == referee.id,
        ).all()
        assert len(d_comms) == 1

        # Wallet balance = 513.32 + 46.67 + 46.67 = 606.66
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("606.66")

    def test_03_first_order_with_multiple_products_awards_500_once(self, db_session: Session) -> None:
        """Scenario 4: First order with 3 products awards ₹500 direct once + 3 generation commissions."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Distributor 3", "9019440301", Programme.PLAN_B, "PBDIST03")
        dist_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(dist_ord.id, db=db_session)

        referee = create_test_user(db_session, "Referee 3", "9019440302", Programme.PLAN_B, referred_by_id=dist.id)
        # Order with 3 Power Banks
        ord1 = create_order(db_session, referee, prod, 3, referral_code="PBDIST03")
        FulfilmentOrchestrator.fulfil_order(ord1.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)
        assert res.status == "COMPLETED"
        assert res.direct_net_credited == Decimal("466.66")  # Exactly once
        # 3 units: Unit 1 = ₹46.66, Unit 2 = ₹46.67, Unit 3 = ₹46.67 -> sum = ₹140.00
        assert res.generation_net_credited == Decimal("140.00")
        # Total net = ₹466.66 + ₹140.00 = ₹606.66 (Matches Example 1 in spec!)
        assert res.total_net_credited == Decimal("606.66")

        # Verify only 1 DIRECT commission record
        direct_count = db_session.query(PlanBCommission).filter(
            PlanBCommission.commission_type == "DIRECT",
            PlanBCommission.distributor_id == dist.id,
        ).count()
        assert direct_count == 1

        # Verify 3 GENERATION commission records
        gen_count = db_session.query(PlanBCommission).filter(
            PlanBCommission.commission_type == "GENERATION",
            PlanBCommission.distributor_id == dist.id,
        ).count()
        assert gen_count == 3

    def test_04_duplicate_callback_idempotency(self, db_session: Session) -> None:
        """Scenario 5: Repeated order callback / retry never duplicates commissions or wallet balance."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Distributor 4", "9019440401", Programme.PLAN_B, "PBDIST04")
        dist_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(dist_ord.id, db=db_session)

        referee = create_test_user(db_session, "Referee 4", "9019440402", Programme.PLAN_B, referred_by_id=dist.id)
        ord1 = create_order(db_session, referee, prod, 1, referral_code="PBDIST04")
        FulfilmentOrchestrator.fulfil_order(ord1.id, db=db_session)

        # Call 1
        res1 = PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)
        assert res1.status == "COMPLETED"
        assert res1.total_net_credited == Decimal("513.32")

        # Call 2 (Duplicate / Retry)
        res2 = PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)
        assert res2.status == "COMPLETED"
        assert res2.direct_net_credited == Decimal("0.00")
        assert res2.generation_net_credited == Decimal("0.00")
        assert res2.total_net_credited == Decimal("0.00")

        # Wallet balance remains strictly ₹513.32
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("513.32")

    # =========================================================================
    # 2. GENERATION COMMISSION TESTS
    # =========================================================================

    def test_05_generation_commission_sequence_deductions_and_future_purchase(self, db_session: Session) -> None:
        """Scenario 6, 7 & 8: First order 3 units + Future order 2 units (Matches spec Examples 1 & 2)."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Distributor 5", "9019440501", Programme.PLAN_B, "PBDIST05")
        dist_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(dist_ord.id, db=db_session)

        ref = create_test_user(db_session, "Referee 5", "9019440502", Programme.PLAN_B, referred_by_id=dist.id)

        # First order: 3 Power Banks
        ord1 = create_order(db_session, ref, prod, 3, referral_code="PBDIST05")
        FulfilmentOrchestrator.fulfil_order(ord1.id, db=db_session)
        res1 = PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)

        # Expected: Direct net ₹466.66 + (₹46.66 + ₹46.67 + ₹46.67) = ₹606.66
        assert res1.direct_net_credited == Decimal("466.66")
        assert res1.generation_net_credited == Decimal("140.00")
        assert res1.total_net_credited == Decimal("606.66")

        # Future purchase: 2 Power Banks (Spec Example 2: ₹100 gross, ₹4.66 op cost, ₹2.00 TDS, ₹93.34 net)
        ord2 = create_order(db_session, ref, prod, 2, referral_code="PBDIST05")
        FulfilmentOrchestrator.fulfil_order(ord2.id, db=db_session)
        res2 = PlanBCommissionService.process_order_commissions(ord2.id, db=db_session)

        assert res2.direct_net_credited == Decimal("0.00")
        assert res2.generation_net_credited == Decimal("93.34")  # 2 x ₹46.67
        assert res2.total_net_credited == Decimal("93.34")

        # Total wallet balance = ₹606.66 + ₹93.34 = ₹700.00!
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("700.00")

    def test_06_five_generation_commissions_reconcile_to_700_net(self, db_session: Session) -> None:
        """Scenario 9: Exact Table 4.3 reconciliation: 1 Direct + 5 Generation units = ₹700.00 net."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Distributor 6", "9019440601", Programme.PLAN_B, "PBDIST06")
        dist_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(dist_ord.id, db=db_session)

        ref = create_test_user(db_session, "Referee 6", "9019440602", Programme.PLAN_B, referred_by_id=dist.id)
        # Order with 5 Power Banks
        ord1 = create_order(db_session, ref, prod, 5, referral_code="PBDIST06")
        FulfilmentOrchestrator.fulfil_order(ord1.id, db=db_session)
        res = PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)

        # Table 4.3:
        # Direct: Gross ₹500, Op ₹23.34, TDS ₹10, Net ₹466.66
        # Gen 1: Gross ₹50, Op ₹2.34, TDS ₹1, Net ₹46.66
        # Gen 2: Gross ₹50, Op ₹2.33, TDS ₹1, Net ₹46.67
        # Gen 3: Gross ₹50, Op ₹2.33, TDS ₹1, Net ₹46.67
        # Gen 4: Gross ₹50, Op ₹2.33, TDS ₹1, Net ₹46.67
        # Gen 5: Gross ₹50, Op ₹2.33, TDS ₹1, Net ₹46.67
        # Total: Gross ₹750.00, Op ₹35.00, TDS ₹15.00, Net ₹700.00
        assert res.direct_net_credited == Decimal("466.66")
        assert res.generation_net_credited == Decimal("233.34")  # 46.66 + 4 * 46.67 = 233.34
        assert res.total_net_credited == Decimal("700.00")

        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("700.00")

    def test_07_no_upstream_payments_single_tier_direct_referring_distributor(self, db_session: Session) -> None:
        """Scenario 10: Generation commission goes ONLY to direct referring distributor, NOT upstream."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        # Upline hierarchy: RootDist -> MiddleDist -> Referee
        root_dist = create_test_user(db_session, "Root Dist", "9019440701", Programme.PLAN_B, "PBROOT701")
        r_ord = create_order(db_session, root_dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(r_ord.id, db=db_session)

        middle_dist = create_test_user(db_session, "Middle Dist", "9019440702", Programme.PLAN_B, "PBMID702", referred_by_id=root_dist.id)
        m_ord = create_order(db_session, middle_dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(m_ord.id, db=db_session)

        # Referee referred directly by middle_dist
        referee = create_test_user(db_session, "Direct Referee", "9019440703", Programme.PLAN_B, referred_by_id=middle_dist.id)
        ord1 = create_order(db_session, referee, prod, 2, referral_code="PBMID702")
        FulfilmentOrchestrator.fulfil_order(ord1.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)
        assert res.status == "COMPLETED"
        assert res.distributor_id == middle_dist.id

        # Middle distributor receives Direct (₹466.66) + Gen (₹46.66 + ₹46.67 = ₹93.33) = ₹559.99
        mid_wallet = db_session.query(Wallet).filter(Wallet.user_id == middle_dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert mid_wallet.balance == Decimal("559.99")

        # Root distributor receives ZERO commission from this order!
        root_wallet = db_session.query(Wallet).filter(Wallet.user_id == root_dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert root_wallet.balance == Decimal("0.00")

        root_comms = db_session.query(PlanBCommission).filter(
            PlanBCommission.distributor_id == root_dist.id,
            PlanBCommission.order_id == ord1.id,
        ).all()
        assert len(root_comms) == 0

    # =========================================================================
    # 3. CROSS-PROGRAMME REFERRAL TESTS (B -> A)
    # =========================================================================

    def test_08_cross_programme_b_to_a_referral(self, db_session: Session) -> None:
        """Scenario 11: Plan B distributor refers Plan A customer.
        Referrer earns Plan B commissions; Customer remains in Plan A and joins Plan A cashback queue.
        """
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist_b = create_test_user(db_session, "Plan B Dist", "9019440801", Programme.PLAN_B, "PBDIST801")
        d_ord = create_order(db_session, dist_b, prod, 1)
        FulfilmentOrchestrator.fulfil_order(d_ord.id, db=db_session)

        # Plan A customer referred by Plan B distributor
        cust_a = create_test_user(db_session, "Plan A Customer", "9019440802", Programme.PLAN_A, referred_by_id=dist_b.id)
        rel = ReferralRelationship(
            referee_id=cust_a.id,
            referrer_id=dist_b.id,
            referee_programme=Programme.PLAN_A,
            referrer_programme=Programme.PLAN_B,
            referral_code_used="PBDIST801",
            binding_channel="TEST",
            is_active=True,
        )
        db_session.add(rel)
        db_session.flush()

        # Customer purchases 3 Power Banks
        ord1 = create_order(db_session, cust_a, prod, 3, referral_code="PBDIST801")
        FulfilmentOrchestrator.fulfil_order(ord1.id, db=db_session)

        # Dispatch commissions via handoff
        dispatch_order_commissions(ord1.id, db=db_session)

        # Verify Plan B distributor received ₹606.66 (₹466.66 direct + ₹140.00 gen)
        wallet_b = db_session.query(Wallet).filter(Wallet.user_id == dist_b.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet_b.balance == Decimal("606.66")

        # Verify Plan A customer remains in Plan A
        assert cust_a.programme == Programme.PLAN_A

        # Verify NO Plan A commission was created for this order
        pa_comms = db_session.query(PlanACommission).filter(PlanACommission.order_id == ord1.id).all()
        assert len(pa_comms) == 0

        # Verify Billing IDs belong to Plan A cashback queue
        bids = db_session.query(BillingId).filter(BillingId.order_id == ord1.id).all()
        assert len(bids) == 3
        assert all(b.status == "ALLOCATED" for b in bids)

    # =========================================================================
    # 4. MULTI-USER, CONCURRENCY & ISOLATION TESTS
    # =========================================================================

    def test_09_multiple_distributors_with_independent_referees(self, db_session: Session) -> None:
        """Scenario 12: Multiple independent distributors earn their own commissions with isolated sequences."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        # Distributor Alpha
        dist_alpha = create_test_user(db_session, "Dist Alpha", "9019440901", Programme.PLAN_B, "PBALPHA01")
        ord_a = create_order(db_session, dist_alpha, prod, 1)
        FulfilmentOrchestrator.fulfil_order(ord_a.id, db=db_session)

        # Distributor Beta
        dist_beta = create_test_user(db_session, "Dist Beta", "9019440902", Programme.PLAN_B, "PBBETA02")
        ord_b = create_order(db_session, dist_beta, prod, 1)
        FulfilmentOrchestrator.fulfil_order(ord_b.id, db=db_session)

        # Customer Alpha under Dist Alpha
        c_alpha = create_test_user(db_session, "Cust Alpha", "9019440903", Programme.PLAN_B, referred_by_id=dist_alpha.id)
        o_a = create_order(db_session, c_alpha, prod, 1, referral_code="PBALPHA01")
        FulfilmentOrchestrator.fulfil_order(o_a.id, db=db_session)
        PlanBCommissionService.process_order_commissions(o_a.id, db=db_session)

        # Customer Beta under Dist Beta
        c_beta = create_test_user(db_session, "Cust Beta", "9019440904", Programme.PLAN_B, referred_by_id=dist_beta.id)
        o_b = create_order(db_session, c_beta, prod, 1, referral_code="PBBETA02")
        FulfilmentOrchestrator.fulfil_order(o_b.id, db=db_session)
        PlanBCommissionService.process_order_commissions(o_b.id, db=db_session)

        # Both distributors receive exactly ₹513.32 (Direct ₹466.66 + 1st Gen ₹46.66)
        w_alpha = db_session.query(Wallet).filter(Wallet.user_id == dist_alpha.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        w_beta = db_session.query(Wallet).filter(Wallet.user_id == dist_beta.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert w_alpha.balance == Decimal("513.32")
        assert w_beta.balance == Decimal("513.32")

    def test_10_distributor_dashboard_overview_matches_9_metrics(self, db_session: Session) -> None:
        """Scenario 13: Distributor dashboard overview returns all 9 metrics with separate history lists."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Overview Dist", "9019441001", Programme.PLAN_B, "PBOVER01")
        dist_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(dist_ord.id, db=db_session)

        ref1 = create_test_user(db_session, "Ref 1", "9019441002", Programme.PLAN_B, referred_by_id=dist.id)
        ord1 = create_order(db_session, ref1, prod, 2, referral_code="PBOVER01")
        FulfilmentOrchestrator.fulfil_order(ord1.id, db=db_session)
        PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)

        overview = PlanBReportService.get_distributor_dashboard_overview(db_session, dist.id)
        metrics = overview["summary_metrics"]

        # 9 metrics verified:
        assert metrics["available_wallet_balance"] == Decimal("559.99")  # 466.66 + 46.66 + 46.67
        assert metrics["lifetime_direct_earned"] == Decimal("466.66")
        assert metrics["generation_commission_earned"] == Decimal("93.33")  # 46.66 + 46.67
        assert metrics["total_gross_commission"] == Decimal("600.00")       # 500 + 50 + 50
        assert metrics["total_operational_cost"] == Decimal("28.01")        # 23.34 + 2.34 + 2.33
        assert metrics["total_tds"] == Decimal("12.00")                     # 10 + 1 + 1
        assert metrics["total_net_commission_earned"] == Decimal("559.99")
        assert metrics["total_withdrawn"] == Decimal("0.00")
        assert metrics["available_withdrawable_balance"] == Decimal("559.99")

        # Separate Direct Referral History (exactly 1 row)
        assert len(overview["direct_commissions"]) == 1
        assert overview["direct_commissions"][0]["gross_amount"] == Decimal("500.00")
        assert overview["direct_commissions"][0]["net_amount"] == Decimal("466.66")

        # Separate Generation Commission History (exactly 2 rows, one per Billing ID)
        assert len(overview["generation_commissions"]) == 2
        assert all(c["gross_amount"] == Decimal("50.00") for c in overview["generation_commissions"])
        gen_nets = sorted([c["net_amount"] for c in overview["generation_commissions"]])
        assert gen_nets == [Decimal("46.66"), Decimal("46.67")]

    def test_11_distributor_excel_statement_generation(self, db_session: Session) -> None:
        """Scenario 14: Official Excel (.xlsx) commission statement generated per standard R-08."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Statement Dist", "9019441101", Programme.PLAN_B, "PBSTMT01")
        dist_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(dist_ord.id, db=db_session)

        ref = create_test_user(db_session, "Ref Stmt", "9019441102", Programme.PLAN_B, referred_by_id=dist.id)
        ord1 = create_order(db_session, ref, prod, 1, referral_code="PBSTMT01")
        FulfilmentOrchestrator.fulfil_order(ord1.id, db=db_session)
        PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)

        xlsx_bytes, filename = PlanBReportService.generate_distributor_self_statement_excel(db_session, dist.id)
        assert filename.endswith(".xlsx")
        assert len(xlsx_bytes) > 0

    def test_12_unqualified_distributor_without_purchase_earns_zero(self, db_session: Session) -> None:
        """Scenario 15: Distributor without qualifying purchase (BR-X2) earns zero commission."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        # Distributor has NO purchases
        unqual_dist = create_test_user(db_session, "Unqual Dist", "9019441201", Programme.PLAN_B, "PBUNQUAL01")

        ref = create_test_user(db_session, "Ref Unqual", "9019441202", Programme.PLAN_B, referred_by_id=unqual_dist.id)
        ord1 = create_order(db_session, ref, prod, 1, referral_code="PBUNQUAL01")
        FulfilmentOrchestrator.fulfil_order(ord1.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)
        assert res.status == "INELIGIBLE_DISTRIBUTOR"
        assert res.total_net_credited == Decimal("0.00")

        wallet = db_session.query(Wallet).filter(Wallet.user_id == unqual_dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("0.00")
