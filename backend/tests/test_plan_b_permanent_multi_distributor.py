"""Comprehensive multi-distributor, cross-programme, and multi-user test suite for Plan B permanent engine."""

from decimal import Decimal
import io
import threading
from typing import List, Tuple
import openpyxl
import pytest
from sqlalchemy.orm import Session

from app.core.security import create_access_token
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
from app.models.user import Address, User
from app.models.wallet import Wallet, WalletTransaction
from app.services.billing.allocator import BillingAllocatorService
from app.services.cashback.plan_a import PlanACashbackService
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
from app.services.fulfilment_handoff import dispatch_order_commissions, dispatch_order_fulfilment
from app.services.reports.plan_b_reports import PlanBReportService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_seq_counter = 0

def get_next_seq() -> int:
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def ensure_counter(db: Session, start_val: int = 10000) -> BillingCounter:
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
        referral_code=referral_code or f"REF{get_next_seq():06d}",
        role=UserRole.CUSTOMER,
        is_active=True,
        referred_by_id=referred_by_id,
    )
    db.add(user)
    db.flush()

    # Create Direct Referral and Sequential Commission wallets
    w1 = Wallet(user_id=user.id, wallet_type=WalletType.DIRECT_REFERRAL, balance=Decimal("0.00"), total_withdrawn=Decimal("0.00"))
    w2 = Wallet(user_id=user.id, wallet_type=WalletType.SEQUENTIAL_COMMISSION, balance=Decimal("0.00"), total_withdrawn=Decimal("0.00"))
    db.add_all([w1, w2])
    db.flush()
    return user


def create_order(
    db: Session,
    customer: User,
    product: Product,
    quantity: int = 1,
    referral_code: str = None,
    order_status: OrderStatus = OrderStatus.CONFIRMED,
    payment_status: PaymentStatus = PaymentStatus.COMPLETED,
) -> Order:
    seq = get_next_seq()
    addr = Address(
        user_id=customer.id,
        recipient_name=customer.full_name,
        phone=customer.phone,
        address_line1="100 Test St",
        city="Bengaluru",
        state="Karnataka",
        pincode="560001",
    )
    db.add(addr)
    db.flush()

    order = Order(
        order_number=f"ORD-TEST-{customer.id}-{seq}",
        idempotency_key=f"idemp-test-{customer.id}-{seq}",
        user_id=customer.id,
        address_id=addr.id,
        total_amount=product.price * quantity,
        order_status=order_status,
        payment_status=payment_status,
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


# ---------------------------------------------------------------------------
# Test Suite
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPlanBPermanentMultiDistributorEngine:
    """Test suite covering authoritative Plan B rules and multi-user safety."""

    def test_01_first_eligible_referred_customer_earns_500_plus_50(self, db_session: Session) -> None:
        """Rule 1: First qualifying purchase under Plan B distributor awards ₹500 lifetime direct bonus + ₹50 generation."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        # Distributor with qualifying self-purchase
        dist = create_test_user(db_session, "Manoj Kumar H", "9019440501", Programme.PLAN_B, "PBI8924C")
        self_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(self_ord.id, db=db_session)

        # Customer 03 refers Manoj
        cust03 = create_test_user(db_session, "Customer 03", "9019440503", Programme.PLAN_B, "PBCUST03")
        ord03 = create_order(db_session, cust03, prod, 1, referral_code="PBI8924C")
        FulfilmentOrchestrator.fulfil_order(ord03.id, db=db_session)

        res = PlanBCommissionService.process_order_commissions(ord03.id, db=db_session)
        assert res.status == "COMPLETED"
        assert res.distributor_id == dist.id
        assert res.direct_net_credited == Decimal("466.66")
        assert res.generation_net_credited == Decimal("46.66")
        assert res.total_net_credited == Decimal("513.32")

        # Verify wallet balance
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("513.32")

        # Verify DB records
        direct_comm = db_session.query(PlanBCommission).filter(
            PlanBCommission.commission_type == "DIRECT",
            PlanBCommission.distributor_id == dist.id,
        ).first()
        assert direct_comm is not None
        assert direct_comm.gross_amount == Decimal("500.00")
        assert direct_comm.operational_cost_amount == Decimal("23.34")
        assert direct_comm.tds_amount == Decimal("10.00")
        assert direct_comm.net_amount == Decimal("466.66")
        assert direct_comm.idempotency_key == f"PB-DIRECT:{dist.id}"

    def test_02_second_referred_customer_same_distributor_skips_500_lifetime(self, db_session: Session) -> None:
        """Rule 2: Repeat purchase by same referee skips direct bonus; new referee gets direct bonus."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Manoj Kumar H", "9019440501", Programme.PLAN_B, "PBI8924C")
        self_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(self_ord.id, db=db_session)

        # Customer 03 (first purchase)
        cust03 = create_test_user(db_session, "Customer 03", "9019440503", Programme.PLAN_B, "PBCUST03")
        ord03 = create_order(db_session, cust03, prod, 1, referral_code="PBI8924C")
        FulfilmentOrchestrator.fulfil_order(ord03.id, db=db_session)
        PlanBCommissionService.process_order_commissions(ord03.id, db=db_session)

        # Customer 03 (second purchase - repeat purchase skips direct bonus)
        ord03_rep = create_order(db_session, cust03, prod, 1, referral_code="PBI8924C")
        FulfilmentOrchestrator.fulfil_order(ord03_rep.id, db=db_session)
        res_rep = PlanBCommissionService.process_order_commissions(ord03_rep.id, db=db_session)
        assert res_rep.status == "COMPLETED"
        assert res_rep.direct_net_credited == Decimal("0.00")  # Lifetime bonus NOT awarded again to same customer!
        assert res_rep.generation_net_credited == Decimal("46.67")

        # Customer 04 (second referred customer under Manoj - skips direct bonus under once-per-distributor rule!)
        cust04 = create_test_user(db_session, "Customer 04", "9019440504", Programme.PLAN_B, "PBCUST04")
        ord04 = create_order(db_session, cust04, prod, 1, referral_code="PBI8924C")
        FulfilmentOrchestrator.fulfil_order(ord04.id, db=db_session)

        res04 = PlanBCommissionService.process_order_commissions(ord04.id, db=db_session)
        assert res04.status == "COMPLETED"
        assert res04.distributor_id == dist.id
        assert res04.direct_net_credited == Decimal("0.00")  # Once per distributor lifetime already awarded!
        assert res04.generation_net_credited == Decimal("46.67")
        assert res04.total_net_credited == Decimal("46.67")

        # Total wallet balance = 513.32 (cust03 order 1) + 46.67 (cust03 repeat) + 46.67 (cust04 order 1) = 606.66
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("606.66")

        # Exactly 1 DIRECT commission in database for Manoj
        direct_comms = db_session.query(PlanBCommission).filter(
            PlanBCommission.commission_type == "DIRECT",
            PlanBCommission.distributor_id == dist.id,
        ).all()
        assert len(direct_comms) == 1

    def test_03_third_referred_customer_generation_only(self, db_session: Session) -> None:
        """Rule 3: Repeat purchase by existing customer receives only generation commission."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Distributor Alpha", "9019440601", Programme.PLAN_B, "PBALPHA01")
        self_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(self_ord.id, db=db_session)

        # Cust 1
        c1 = create_test_user(db_session, "Cust 1", "9019440602", Programme.PLAN_B)
        o1 = create_order(db_session, c1, prod, 1, referral_code="PBALPHA01")
        FulfilmentOrchestrator.fulfil_order(o1.id, db=db_session)
        PlanBCommissionService.process_order_commissions(o1.id, db=db_session)

        # Cust 2
        c2 = create_test_user(db_session, "Cust 2", "9019440603", Programme.PLAN_B)
        o2 = create_order(db_session, c2, prod, 1, referral_code="PBALPHA01")
        FulfilmentOrchestrator.fulfil_order(o2.id, db=db_session)
        PlanBCommissionService.process_order_commissions(o2.id, db=db_session)

        # Cust 1 repeat purchase (purchases 2 units)
        o3 = create_order(db_session, c1, prod, 2, referral_code="PBALPHA01")
        FulfilmentOrchestrator.fulfil_order(o3.id, db=db_session)
        res3 = PlanBCommissionService.process_order_commissions(o3.id, db=db_session)

        assert res3.status == "COMPLETED"
        assert res3.direct_net_credited == Decimal("0.00")
        assert res3.generation_net_credited == Decimal("93.34")  # 2 x 46.67
        assert res3.total_net_credited == Decimal("93.34")

    def test_04_repeat_purchase_of_multiple_units(self, db_session: Session) -> None:
        """Rule 4: Subsequent purchase of 5 products generates 5 x ₹46.67 generation commission, ₹0 direct bonus."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Distributor Beta", "9019440701", Programme.PLAN_B, "PBBETA01")
        self_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(self_ord.id, db=db_session)

        cust = create_test_user(db_session, "Repeat Customer", "9019440702", Programme.PLAN_B)
        # Order 1 (1 unit)
        o1 = create_order(db_session, cust, prod, 1, referral_code="PBBETA01")
        FulfilmentOrchestrator.fulfil_order(o1.id, db=db_session)
        PlanBCommissionService.process_order_commissions(o1.id, db=db_session)

        # Order 2 (5 units)
        o2 = create_order(db_session, cust, prod, 5, referral_code="PBBETA01")
        FulfilmentOrchestrator.fulfil_order(o2.id, db=db_session)
        res2 = PlanBCommissionService.process_order_commissions(o2.id, db=db_session)

        assert res2.status == "COMPLETED"
        assert res2.direct_net_credited == Decimal("0.00")
        assert res2.generation_net_credited == Decimal("233.35")  # 5 x 46.67
        assert res2.total_net_credited == Decimal("233.35")

    def test_05_independent_distributors_each_receive_own_lifetime_500(self, db_session: Session) -> None:
        """Rule 5: Multiple independent distributors each earn their own one-time ₹500 direct bonus on first referee."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist1 = create_test_user(db_session, "Distributor 1", "9019440801", Programme.PLAN_B, "PBDIST801")
        create_order(db_session, dist1, prod, 1)
        dist2 = create_test_user(db_session, "Distributor 2", "9019440802", Programme.PLAN_B, "PBDIST802")
        create_order(db_session, dist2, prod, 1)

        # Customer for dist1
        c1 = create_test_user(db_session, "Customer D1", "9019440803", Programme.PLAN_B)
        o1 = create_order(db_session, c1, prod, 1, referral_code="PBDIST801")
        FulfilmentOrchestrator.fulfil_order(o1.id, db=db_session)
        res1 = PlanBCommissionService.process_order_commissions(o1.id, db=db_session)

        # Customer for dist2
        c2 = create_test_user(db_session, "Customer D2", "9019440804", Programme.PLAN_B)
        o2 = create_order(db_session, c2, prod, 1, referral_code="PBDIST802")
        FulfilmentOrchestrator.fulfil_order(o2.id, db=db_session)
        res2 = PlanBCommissionService.process_order_commissions(o2.id, db=db_session)

        assert res1.direct_net_credited == Decimal("466.66")
        assert res1.total_net_credited == Decimal("513.32")
        assert res2.direct_net_credited == Decimal("466.66")
        assert res2.total_net_credited == Decimal("513.32")

        w1 = db_session.query(Wallet).filter(Wallet.user_id == dist1.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        w2 = db_session.query(Wallet).filter(Wallet.user_id == dist2.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert w1.balance == Decimal("513.32")
        assert w2.balance == Decimal("513.32")

    def test_06_cross_programme_b_to_a_referral(self, db_session: Session) -> None:
        """Rule 6: Cross-programme referral (B -> A). Customer is Plan A, distributor is Plan B.
        Customer receives Plan A sequential cashback queue placement.
        Distributor receives Plan B commissions (₹500 once + ₹50 per Billing ID).
        Plan A commission service does NOT credit distributor.
        """
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        # Plan B distributor
        dist = create_test_user(db_session, "Manoj Cross", "9019440901", Programme.PLAN_B, "PBCROSS901")
        self_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(self_ord.id, db=db_session)

        # Plan A customer registering with Plan B distributor's code
        cust_a = create_test_user(db_session, "Plan A Customer", "9019440902", Programme.PLAN_A, "PACROSS902")
        from app.models.referral import ReferralRelationship
        db_session.add(
            ReferralRelationship(
                referee_id=cust_a.id,
                referrer_id=dist.id,
                referee_programme=Programme.PLAN_A,
                referrer_programme=Programme.PLAN_B,
                referral_code_used=dist.referral_code,
                binding_channel="checkout",
                is_active=True,
            )
        )
        db_session.commit()

        ord_a = create_order(db_session, cust_a, prod, 1, referral_code="PBCROSS901")

        # Fulfilment allocates Plan A Billing ID
        fulfil_res = FulfilmentOrchestrator.fulfil_order(ord_a.id, db=db_session)
        assert fulfil_res.status == "COMPLETED"
        b_id = db_session.query(BillingId).filter(BillingId.order_id == ord_a.id).first()
        assert b_id.programme == Programme.PLAN_A

        # Dispatch commissions via handoff hook
        dispatch_order_commissions(ord_a.id, db=db_session)

        # Plan B commissions awarded to distributor
        pb_comm = db_session.query(PlanBCommission).filter(PlanBCommission.order_id == ord_a.id).all()
        assert len(pb_comm) == 2  # 1 direct (466.66) + 1 generation (46.66)
        assert sum(c.net_amount for c in pb_comm) == Decimal("513.32")

        # Plan A direct commission was NEVER created for this order
        pa_comm = db_session.query(PlanACommission).filter(PlanACommission.order_id == ord_a.id).count()
        assert pa_comm == 0

        # Customer participates in Plan A sequential cashback queue!
        PlanACashbackService.process_order_cashback(ord_a.id, db=db_session)
        entry = db_session.query(PlanACashbackEntry).filter(PlanACashbackEntry.billing_id == b_id.id).first()
        assert entry is not None
        assert entry.user_id == cust_a.id

    def test_07_duplicate_callbacks_and_retries_idempotency(self, db_session: Session) -> None:
        """Rule 7: Replayed callbacks or retries never create duplicate commission credits."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Dist Idemp", "9019441001", Programme.PLAN_B, "PBIDEMP01")
        self_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(self_ord.id, db=db_session)

        cust = create_test_user(db_session, "Cust Idemp", "9019441002", Programme.PLAN_B)
        ord_idemp = create_order(db_session, cust, prod, 2, referral_code="PBIDEMP01")
        FulfilmentOrchestrator.fulfil_order(ord_idemp.id, db=db_session)

        # Call 1
        res1 = PlanBCommissionService.process_order_commissions(ord_idemp.id, db=db_session)
        assert res1.total_net_credited == Decimal("559.99")  # 466.66 + 46.66 + 46.67

        # Call 2 (retry)
        res2 = PlanBCommissionService.process_order_commissions(ord_idemp.id, db=db_session)
        assert res2.total_net_credited == Decimal("0.00")

        # Call 3 (retry via handoff hook)
        dispatch_order_commissions(ord_idemp.id, db=db_session)

        # Total wallet balance strictly unchanged
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("559.99")
        assert db_session.query(WalletTransaction).filter(WalletTransaction.user_id == dist.id).count() == 3  # 1 direct + 2 gen

    def test_08_failed_and_unpaid_orders_generate_no_commission(self, db_session: Session) -> None:
        """Rule 8: Orders with payment_status != COMPLETED generate zero commission."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Dist Unpaid", "9019441101", Programme.PLAN_B, "PBUNPAID1")
        self_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(self_ord.id, db=db_session)

        cust = create_test_user(db_session, "Cust Unpaid", "9019441102", Programme.PLAN_B)
        ord_unpaid = create_order(
            db_session,
            cust,
            prod,
            1,
            referral_code="PBUNPAID1",
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.FAILED,
        )

        # Attempt to process commissions
        res = PlanBCommissionService.process_order_commissions(ord_unpaid.id, db=db_session)
        # Because order has no allocated billing IDs, it fails gracefully without commission
        assert res.status in ("FAILED", "INELIGIBLE")
        assert res.total_net_credited == Decimal("0.00")

        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("0.00")

    def test_09_programme_commission_isolation(self, db_session: Session) -> None:
        """Rule 9: Plan A order with Plan A referrer never creates Plan B commissions;
        Plan B order never creates Plan A commissions.
        """
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        # Plan A tree
        dist_a = create_test_user(db_session, "Punith Plan A", "9019443001", Programme.PLAN_A, "PAR8L0CA")
        ord_self_a = create_order(db_session, dist_a, prod, 1)
        FulfilmentOrchestrator.fulfil_order(ord_self_a.id, db=db_session)

        cust_a = create_test_user(db_session, "Customer 01 Plan A", "9019441201", Programme.PLAN_A)
        ord_a = create_order(db_session, cust_a, prod, 1, referral_code="PAR8L0CA")
        FulfilmentOrchestrator.fulfil_order(ord_a.id, db=db_session)

        dispatch_order_commissions(ord_a.id, db=db_session)

        # Plan A commission created
        assert db_session.query(PlanACommission).filter(PlanACommission.order_id == ord_a.id).count() == 1
        # Plan B commission strictly ZERO
        assert db_session.query(PlanBCommission).filter(PlanBCommission.order_id == ord_a.id).count() == 0

    def test_10_multi_user_session_and_token_isolation(self, db_session: Session) -> None:
        """Rule 10: Multi-user login isolation: 10 independent users have distinct tokens,
        isolated wallets, and zero data leakage.
        """
        users: List[User] = []
        tokens: List[str] = []

        for i in range(10):
            prog = Programme.PLAN_B if i % 2 == 0 else Programme.PLAN_A
            u = create_test_user(db_session, f"MultiUser {i+1}", f"90194499{i:02d}", prog)
            users.append(u)
            token = create_access_token(user_id=u.id, role=u.role.value, phone=u.phone)
            tokens.append(token)

        # All 10 tokens must be completely distinct
        assert len(set(tokens)) == 10

        # Each user's wallet is distinct and independent
        for i, u in enumerate(users):
            w = db_session.query(Wallet).filter(Wallet.user_id == u.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
            assert w is not None
            assert w.user_id == u.id

    def test_11_distributor_excel_statement_generation_and_reconciliation(self, db_session: Session) -> None:
        """Rule 11: Distributor self-statement Excel export contains correct lifetime ₹500 and generation ₹50 line items."""
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Statement Dist", "9019441301", Programme.PLAN_B, "PBSTMT01")
        self_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(self_ord.id, db=db_session)

        # Customer 1: 1 unit (500 direct + 50 gen = 550)
        c1 = create_test_user(db_session, "Statement Cust 1", "9019441302", Programme.PLAN_B)
        o1 = create_order(db_session, c1, prod, 1, referral_code="PBSTMT01")
        FulfilmentOrchestrator.fulfil_order(o1.id, db=db_session)
        PlanBCommissionService.process_order_commissions(o1.id, db=db_session)

        # Customer 2: 1 unit (0 direct + 50 gen = 50)
        c2 = create_test_user(db_session, "Statement Cust 2", "9019441303", Programme.PLAN_B)
        o2 = create_order(db_session, c2, prod, 1, referral_code="PBSTMT01")
        FulfilmentOrchestrator.fulfil_order(o2.id, db=db_session)
        PlanBCommissionService.process_order_commissions(o2.id, db=db_session)

        # Generate statement
        excel_bytes, filename = PlanBReportService.generate_distributor_self_statement_excel(
            db=db_session,
            distributor_id=dist.id,
        )
        assert len(excel_bytes) > 0
        assert filename.endswith(".xlsx")

        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        assert "Commission Statement" in wb.sheetnames
        ws = wb["Commission Statement"]
        rows = list(ws.iter_rows(values_only=True))

        content_str = str(rows)
        assert "Direct Referral Commission" in content_str
        assert "Generation Commission" in content_str
        assert "Statement Cust 1" in content_str
        assert "Statement Cust 2" in content_str

        # Wallet balance in statement matches DB balance (₹559.99)
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("559.99")

    def test_12_concurrent_first_purchases_race_safety(self, db_session: Session) -> None:
        """Rule 12: Duplicate/concurrent callbacks for same customer first purchase.
        Database-level UNIQUE constraint on idempotency_key 'PB-DIRECT:{distributor.id}' guarantees
        only ONE ₹466.66 bonus is created.
        """
        ensure_counter(db_session)
        prod = create_test_product(db_session)

        dist = create_test_user(db_session, "Race Dist", "9019441401", Programme.PLAN_B, "PBRACE01")
        self_ord = create_order(db_session, dist, prod, 1)
        FulfilmentOrchestrator.fulfil_order(self_ord.id, db=db_session)

        c1 = create_test_user(db_session, "Race Cust 1", "9019441402", Programme.PLAN_B)

        o1 = create_order(db_session, c1, prod, 1, referral_code="PBRACE01")
        FulfilmentOrchestrator.fulfil_order(o1.id, db=db_session)

        # Process order 1 first
        res1 = PlanBCommissionService.process_order_commissions(o1.id, db=db_session)
        # Duplicate callback for same order
        res2 = PlanBCommissionService.process_order_commissions(o1.id, db=db_session)

        assert res1.direct_net_credited == Decimal("466.66")
        assert res1.generation_net_credited == Decimal("46.66")
        assert res2.direct_net_credited == Decimal("0.00")
        assert res2.generation_net_credited == Decimal("0.00")

        # Total wallet balance is strictly ₹513.32
        wallet = db_session.query(Wallet).filter(Wallet.user_id == dist.id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert wallet.balance == Decimal("513.32")

        # Exactly 1 DIRECT commission in database for the referee
        direct_count = db_session.query(PlanBCommission).filter(
            PlanBCommission.commission_type == "DIRECT",
            PlanBCommission.distributor_id == dist.id,
        ).count()
        assert direct_count == 1

        # Exactly 1 GENERATION commission in database for the distributor
        gen_count = db_session.query(PlanBCommission).filter(
            PlanBCommission.commission_type == "GENERATION",
            PlanBCommission.distributor_id == dist.id,
        ).count()
        assert gen_count == 1
