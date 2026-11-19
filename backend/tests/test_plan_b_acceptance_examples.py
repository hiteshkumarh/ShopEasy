"""Authoritative verification of the 5 Mandatory Acceptance Examples for Plan B.
Directly implements Section 2 requirements of the authoritative Plan B specification:
- Example 1: 1 customer buys 2 Power Banks in 1st purchase -> ₹600 gross, ₹559.99 net.
- Example 2: 2nd customer buys 1 Power Bank later -> Direct ₹0, Gen ₹50 -> ₹50 gross, ₹46.67 net.
- Example 3: 2 different customers each buy 1 Power Bank -> Cust 1: ₹550 gross (₹513.32 net), Cust 2: ₹50 gross (₹46.67 net) -> Total ₹600 gross (₹559.99 net).
- Example 4: Distributor refers 10 different customers, each buying 1 Power Bank -> Direct ₹500 total (once), Gen 10x₹50=₹500 -> Total ₹1,000 gross.
- Example 5: Same customer repeat purchase -> Direct ₹0, Gen ₹50 for every new eligible Billing ID.
"""

from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.models.billing import BillingCounter, BillingId
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
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.models.wallet import Wallet
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
from app.services.reports.plan_b_reports import PlanBReportService

_seq = 50000


def get_seq() -> int:
    global _seq
    _seq += 1
    return _seq


def ensure_counter(db: Session) -> BillingCounter:
    counter = db.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
    if not counter:
        counter = BillingCounter(sequence_name="GLOBAL_BILLING_ID", current_value=60000)
        db.add(counter)
        db.flush()
    return counter


def create_product(db: Session) -> Product:
    s = get_seq()
    prod = Product(
        name=f"Power Bank {s}",
        product_code=f"PB-{s}",
        price=Decimal("3999.00"),
        stock=5000,
        is_active=True,
        is_power_bank=True,
    )
    db.add(prod)
    db.flush()
    return prod


def create_user(
    db: Session,
    name: str,
    phone: str,
    programme: Programme = Programme.PLAN_B,
    referral_code: str = None,
    referred_by_id: int = None,
) -> User:
    s = get_seq()
    user = User(
        full_name=name,
        phone=phone,
        programme=programme,
        account_status=AccountStatus.ACTIVE,
        referral_code=referral_code or f"PBX{s:06d}",
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


def create_and_fulfil_order(
    db: Session,
    user: User,
    product: Product,
    quantity: int = 1,
    referral_code: str = None,
) -> Order:
    s = get_seq()
    addr = Address(
        user_id=user.id,
        recipient_name=user.full_name,
        phone=user.phone,
        address_line1="123 Example Rd",
        city="Bengaluru",
        state="Karnataka",
        pincode="560001",
    )
    db.add(addr)
    db.flush()

    ord_obj = Order(
        user_id=user.id,
        order_number=f"ORD-EX-{user.id}-{s}",
        idempotency_key=f"IDEMP-EX-{user.id}-{s}",
        address_id=addr.id,
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
        total_amount=product.price * quantity,
        applied_referral_code=referral_code,
        is_first_successful_order=True,
        is_fulfilled=False,
    )
    db.add(ord_obj)
    db.flush()

    item = OrderItem(
        order_id=ord_obj.id,
        product_id=product.id,
        product_name=product.name,
        unit_price=product.price,
        quantity=quantity,
        line_total=product.price * quantity,
    )
    db.add(item)
    db.flush()

    FulfilmentOrchestrator.fulfil_order(ord_obj.id, db=db)
    return ord_obj


class TestPlanBMandatoryAcceptanceExamples:
    """Verifies all 5 authoritative acceptance examples from Section 2."""

    def test_example_1_one_customer_buys_two_power_banks_first_purchase(self, db_session: Session) -> None:
        """Example 1: 1 customer buys 2 Power Banks in first purchase:
        - Direct Referral Commission = ₹500 (Gross ₹500, Op Cost ₹23.34, TDS ₹10.00, Net ₹466.66)
        - Generation Commission = 2 × ₹50 = ₹100
          * Unit 1: Gross ₹50, Op Cost ₹2.34, TDS ₹1.00, Net ₹46.66
          * Unit 2: Gross ₹50, Op Cost ₹2.33, TDS ₹1.00, Net ₹46.67
        - Total Gross = ₹600.00
        - Deductions: Op Cost = ₹28.01, TDS = ₹12.00
        - Total Net = ₹559.99
        """
        ensure_counter(db_session)
        prod = create_product(db_session)

        # Distributor qualifies with own purchase
        dist = create_user(db_session, "Dist Example 1", "9019445001", Programme.PLAN_B, "EX1DIST")
        create_and_fulfil_order(db_session, dist, prod, 1)

        # Customer 1 buys 2 Power Banks in 1st purchase
        cust = create_user(db_session, "Cust Example 1", "9019445002", Programme.PLAN_B, referred_by_id=dist.id)
        ord1 = create_and_fulfil_order(db_session, cust, prod, 2, referral_code="EX1DIST")

        res = PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)
        assert res.status == "COMPLETED"
        assert res.direct_net_credited == Decimal("466.66")
        assert len(res.generation_commission_ids) == 2
        assert res.total_net_credited == Decimal("559.99")

        # Verify wallet balance
        wallet = db_session.query(Wallet).filter(
            Wallet.user_id == dist.id,
            Wallet.wallet_type == WalletType.DIRECT_REFERRAL,
        ).first()
        assert wallet.balance == Decimal("559.99")

        # Verify commission records
        comms = db_session.query(PlanBCommission).filter(PlanBCommission.distributor_id == dist.id).all()
        assert len(comms) == 3

        direct_comms = [c for c in comms if c.commission_type == "DIRECT"]
        gen_comms = [c for c in comms if c.commission_type == "GENERATION"]
        assert len(direct_comms) == 1
        assert len(gen_comms) == 2

        assert direct_comms[0].gross_amount == Decimal("500.00")
        assert direct_comms[0].operational_cost_amount == Decimal("23.34")
        assert direct_comms[0].tds_amount == Decimal("10.00")
        assert direct_comms[0].net_amount == Decimal("466.66")

        gen_sorted = sorted(gen_comms, key=lambda c: c.id)
        assert gen_sorted[0].gross_amount == Decimal("50.00")
        assert gen_sorted[0].operational_cost_amount == Decimal("2.34")
        assert gen_sorted[0].tds_amount == Decimal("1.00")
        assert gen_sorted[0].net_amount == Decimal("46.66")

        assert gen_sorted[1].gross_amount == Decimal("50.00")
        assert gen_sorted[1].operational_cost_amount == Decimal("2.33")
        assert gen_sorted[1].tds_amount == Decimal("1.00")
        assert gen_sorted[1].net_amount == Decimal("46.67")

        # Verify overview
        overview = PlanBReportService.get_distributor_dashboard_overview(db_session, dist.id)
        assert overview["summary_metrics"]["total_gross_commission"] == Decimal("600.00")
        assert overview["summary_metrics"]["total_operational_cost"] == Decimal("28.01")
        assert overview["summary_metrics"]["total_tds"] == Decimal("12.00")
        assert overview["summary_metrics"]["total_net_commission_earned"] == Decimal("559.99")
        assert overview["summary_metrics"]["has_received_direct_bonus"] is True
        assert overview["summary_metrics"]["eligible_generation_billing_ids_count"] == 2

    def test_example_2_second_customer_buys_one_power_bank_later(self, db_session: Session) -> None:
        """Example 2: Continuing from Example 1, a 2nd customer buys 1 Power Bank later:
        - Direct Referral Commission = ₹0 (distributor already received lifetime ₹500)
        - Generation Commission = 1 × ₹50 = ₹50
        - Deductions: Op Cost = ₹2.33, TDS = ₹1.00
        - Total Net = ₹46.67
        - Cumulative wallet = ₹559.99 + ₹46.67 = ₹606.66
        """
        ensure_counter(db_session)
        prod = create_product(db_session)

        # Distributor qualifies
        dist = create_user(db_session, "Dist Example 2", "9019445101", Programme.PLAN_B, "EX2DIST")
        create_and_fulfil_order(db_session, dist, prod, 1)

        # Cust 1 buys 2 Power Banks (Example 1)
        cust1 = create_user(db_session, "Cust 1 Ex 2", "9019445102", Programme.PLAN_B, referred_by_id=dist.id)
        ord1 = create_and_fulfil_order(db_session, cust1, prod, 2, referral_code="EX2DIST")
        PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)

        # Cust 2 buys 1 Power Bank later (Example 2)
        cust2 = create_user(db_session, "Cust 2 Ex 2", "9019445103", Programme.PLAN_B, referred_by_id=dist.id)
        ord2 = create_and_fulfil_order(db_session, cust2, prod, 1, referral_code="EX2DIST")
        res2 = PlanBCommissionService.process_order_commissions(ord2.id, db=db_session)

        assert res2.status == "COMPLETED"
        assert res2.direct_net_credited == Decimal("0.00")  # ₹0 Direct Referral
        assert len(res2.generation_commission_ids) == 1
        assert res2.total_net_credited == Decimal("46.67")

        # Verify wallet balance
        wallet = db_session.query(Wallet).filter(
            Wallet.user_id == dist.id,
            Wallet.wallet_type == WalletType.DIRECT_REFERRAL,
        ).first()
        assert wallet.balance == Decimal("606.66")  # 559.99 + 46.67

        # Check latest generation commission record
        latest_gen = db_session.query(PlanBCommission).filter(
            PlanBCommission.order_id == ord2.id,
            PlanBCommission.commission_type == "GENERATION",
        ).first()
        assert latest_gen.gross_amount == Decimal("50.00")
        assert latest_gen.operational_cost_amount == Decimal("2.33")
        assert latest_gen.tds_amount == Decimal("1.00")
        assert latest_gen.net_amount == Decimal("46.67")

    def test_example_3_two_different_customers_each_buy_one_power_bank(self, db_session: Session) -> None:
        """Example 3: 2 different customers each buy 1 Power Bank (Cust 1 first, Cust 2 second):
        - Customer 1: Direct = ₹500, Gen = ₹50. Gross = ₹550. Net = ₹466.66 + ₹46.66 = ₹513.32.
        - Customer 2: Direct = ₹0, Gen = ₹50. Gross = ₹50. Net = ₹46.67.
        - Total across both customers: Gross = ₹600. Net = ₹559.99.
        """
        ensure_counter(db_session)
        prod = create_product(db_session)

        # Distributor qualifies
        dist = create_user(db_session, "Dist Example 3", "9019445201", Programme.PLAN_B, "EX3DIST")
        create_and_fulfil_order(db_session, dist, prod, 1)

        # Customer 1
        cust1 = create_user(db_session, "Cust 1 Ex 3", "9019445202", Programme.PLAN_B, referred_by_id=dist.id)
        ord1 = create_and_fulfil_order(db_session, cust1, prod, 1, referral_code="EX3DIST")
        res1 = PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)
        assert res1.status == "COMPLETED"
        assert res1.direct_net_credited == Decimal("466.66")
        assert len(res1.generation_commission_ids) == 1
        assert res1.total_net_credited == Decimal("513.32")  # 466.66 + 46.66

        # Customer 2
        cust2 = create_user(db_session, "Cust 2 Ex 3", "9019445203", Programme.PLAN_B, referred_by_id=dist.id)
        ord2 = create_and_fulfil_order(db_session, cust2, prod, 1, referral_code="EX3DIST")
        res2 = PlanBCommissionService.process_order_commissions(ord2.id, db=db_session)
        assert res2.status == "COMPLETED"
        assert res2.direct_net_credited == Decimal("0.00")  # ₹0 Direct
        assert len(res2.generation_commission_ids) == 1
        assert res2.total_net_credited == Decimal("46.67")

        # Total across both customers
        wallet = db_session.query(Wallet).filter(
            Wallet.user_id == dist.id,
            Wallet.wallet_type == WalletType.DIRECT_REFERRAL,
        ).first()
        assert wallet.balance == Decimal("559.99")  # 513.32 + 46.67

        overview = PlanBReportService.get_distributor_dashboard_overview(db_session, dist.id)
        assert overview["summary_metrics"]["total_gross_commission"] == Decimal("600.00")
        assert overview["summary_metrics"]["total_operational_cost"] == Decimal("28.01")
        assert overview["summary_metrics"]["total_tds"] == Decimal("12.00")
        assert overview["summary_metrics"]["total_net_commission_earned"] == Decimal("559.99")
        assert overview["summary_metrics"]["eligible_generation_billing_ids_count"] == 2

    def test_example_4_distributor_refers_ten_different_customers_each_buying_one(self, db_session: Session) -> None:
        """Example 4: Distributor refers 10 different customers, each buying 1 Power Bank:
        - Direct Referral Commission = ₹500 total (credited only on 1st customer's 1st purchase; 0 on other 9)
        - Generation Commission = 10 × ₹50 = ₹500 total
        - Total Gross = ₹1,000.00
        - Deductions: Op Cost = ₹23.34 + ₹2.34 + 9×₹2.33 = ₹23.34 + ₹2.34 + ₹20.97 = ₹46.65
        - TDS: ₹10.00 + 10×₹1.00 = ₹20.00
        - Total Net: ₹466.66 + ₹46.66 + 9×₹46.67 = ₹466.66 + ₹46.66 + ₹420.03 = ₹933.35
        """
        ensure_counter(db_session)
        prod = create_product(db_session)

        # Distributor qualifies
        dist = create_user(db_session, "Dist Example 4", "9019445300", Programme.PLAN_B, "EX4DIST")
        create_and_fulfil_order(db_session, dist, prod, 1)

        # 10 different customers
        for i in range(1, 11):
            cust = create_user(
                db_session,
                f"Cust {i} Ex 4",
                f"90194453{i:02d}",
                Programme.PLAN_B,
                referred_by_id=dist.id,
            )
            ord_obj = create_and_fulfil_order(db_session, cust, prod, 1, referral_code="EX4DIST")
            res = PlanBCommissionService.process_order_commissions(ord_obj.id, db=db_session)
            assert res.status == "COMPLETED"
            if i == 1:
                assert res.direct_net_credited == Decimal("466.66")
                assert len(res.generation_commission_ids) == 1
                assert res.total_net_credited == Decimal("513.32")
            else:
                assert res.direct_net_credited == Decimal("0.00")
                assert len(res.generation_commission_ids) == 1
                assert res.total_net_credited == Decimal("46.67")

        overview = PlanBReportService.get_distributor_dashboard_overview(db_session, dist.id)
        assert overview["summary_metrics"]["total_gross_commission"] == Decimal("1000.00")
        assert overview["summary_metrics"]["lifetime_direct_earned"] == Decimal("466.66")
        assert overview["summary_metrics"]["generation_commission_earned"] == Decimal("466.69")  # 46.66 + 9*46.67
        assert overview["summary_metrics"]["total_operational_cost"] == Decimal("46.65")
        assert overview["summary_metrics"]["total_tds"] == Decimal("20.00")
        assert overview["summary_metrics"]["total_net_commission_earned"] == Decimal("933.35")
        assert overview["summary_metrics"]["eligible_generation_billing_ids_count"] == 10

        # Exactly 1 DIRECT record and 10 GENERATION records
        comms = db_session.query(PlanBCommission).filter(PlanBCommission.distributor_id == dist.id).all()
        assert len([c for c in comms if c.commission_type == "DIRECT"]) == 1
        assert len([c for c in comms if c.commission_type == "GENERATION"]) == 10

    def test_example_5_repeat_purchase_by_same_customer(self, db_session: Session) -> None:
        """Example 5: Repeat purchase by the same customer:
        - Direct Referral Commission = ₹0
        - Generation Commission = ₹50 for every new eligible Billing ID.
        """
        ensure_counter(db_session)
        prod = create_product(db_session)

        # Distributor qualifies
        dist = create_user(db_session, "Dist Example 5", "9019445401", Programme.PLAN_B, "EX5DIST")
        create_and_fulfil_order(db_session, dist, prod, 1)

        # Cust 1 purchases 1 unit
        cust = create_user(db_session, "Cust Ex 5", "9019445402", Programme.PLAN_B, referred_by_id=dist.id)
        ord1 = create_and_fulfil_order(db_session, cust, prod, 1, referral_code="EX5DIST")
        res1 = PlanBCommissionService.process_order_commissions(ord1.id, db=db_session)
        assert res1.status == "COMPLETED"
        assert res1.direct_net_credited == Decimal("466.66")
        assert res1.total_net_credited == Decimal("513.32")

        # Same customer makes repeat purchase of 3 units
        ord2 = create_and_fulfil_order(db_session, cust, prod, 3, referral_code="EX5DIST")
        res2 = PlanBCommissionService.process_order_commissions(ord2.id, db=db_session)
        assert res2.status == "COMPLETED"
        assert res2.direct_net_credited == Decimal("0.00")  # ₹0 Direct Referral
        assert len(res2.generation_commission_ids) == 3
        # 3 units * ₹46.67 = ₹140.01
        assert res2.total_net_credited == Decimal("140.01")

        # Total wallet balance: 513.32 + 140.01 = 653.33
        wallet = db_session.query(Wallet).filter(
            Wallet.user_id == dist.id,
            Wallet.wallet_type == WalletType.DIRECT_REFERRAL,
        ).first()
        assert wallet.balance == Decimal("653.33")

        # Overview verification
        overview = PlanBReportService.get_distributor_dashboard_overview(db_session, dist.id)
        assert overview["summary_metrics"]["total_gross_commission"] == Decimal("700.00")  # 500 + 4*50
        assert overview["summary_metrics"]["eligible_generation_billing_ids_count"] == 4
