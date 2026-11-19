"""
backend/tests/test_plan_b_new_distributor_e2e_verification.py
End-to-end verification of Plan B Commission Dispatch and Dashboard Display for a new distributor:
1. End-to-end dispatch: Checkout -> Payment Hook -> Fulfilment Handoff -> Plan B Commission Engine.
2. Two distinct referred customers purchasing 1 eligible Power Bank each:
   - Order 1: ₹500 gross (₹466.66 net) Direct + ₹50 gross (₹46.66 net) Generation.
   - Order 2: ₹0 direct + ₹50 gross (₹46.67 net) Generation.
3. Combined reconciliation: Gross ₹600.00, Op Cost ₹28.01, TDS ₹12.00, Net ₹559.99.
4. Idempotency & ledger auditability: exactly 3 ledger transactions, 3 commission records, 0 duplicate credits.
5. Dashboard Overview API endpoint verification with distributor token.
6. Frontend HTML label cleanliness verification (zero leaked CSS attribute strings).
"""

from decimal import Decimal
import os
import re
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.billing import BillingCounter, BillingId
from app.models.commission import PlanBCommission
from app.models.enums import AccountStatus, OrderStatus, PaymentStatus, Programme, UserRole, WalletType
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User
from app.models.wallet import Wallet, WalletTransaction
from app.services.fulfilment_handoff import dispatch_order_fulfilment
from tests.test_plan_b_permanent_engine import create_order, ensure_counter


FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
DISTRIBUTOR_HTML_PATH = os.path.join(FRONTEND_DIR, "distributor-dashboard.html")


def test_new_plan_b_distributor_end_to_end_flow(db_session: Session):
    """Full end-to-end lifecycle verification for a new Plan B distributor in an isolated database."""
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        # Step 1: Initialize global counter and product
        ensure_counter(db_session)
        power_bank = Product(
            name="Solar Power Bank 20000mAh",
            price=Decimal("3999.00"),
            stock=500,
            is_active=True,
            is_power_bank=True,
        )
        db_session.add(power_bank)
        db_session.commit()

        # Step 2: Create a brand new Plan B distributor
        distributor = User(
            phone="9111222333",
            full_name="Rajesh Kumar Patel",
            referral_code="PBRAJESH01",
            programme=Programme.PLAN_B,
            role=UserRole.CUSTOMER,
            account_status=AccountStatus.ACTIVE,
            is_active=True,
        )
        db_session.add(distributor)
        db_session.commit()

        # Step 3: Distributor completes their own qualifying purchase
        dist_qual_order = create_order(db_session, distributor, power_bank, quantity=1)
        res_qual = dispatch_order_fulfilment(dist_qual_order.id, db=db_session)
        assert res_qual.status == "COMPLETED"

        # Distributor earns 0 commissions on self-purchase (BR-B3)
        self_comms = db_session.query(PlanBCommission).filter(PlanBCommission.distributor_id == distributor.id).all()
        assert len(self_comms) == 0

        # Step 4: Referred Customer 1 registers under Plan B with distributor's code
        c1 = User(
            phone="9111222444",
            full_name="Aarav Sharma",
            referral_code="PBAARAV01",
            referred_by_id=distributor.id,
            programme=Programme.PLAN_B,
            role=UserRole.CUSTOMER,
            account_status=AccountStatus.ACTIVE,
            is_active=True,
        )
        db_session.add(c1)
        db_session.commit()

        # Customer 1 purchases 1 Power Bank (Order 1)
        c1_order = create_order(db_session, c1, power_bank, quantity=1, referral_code=distributor.referral_code)
        
        # Payment confirmation triggers dispatch_order_fulfilment
        res_o1 = dispatch_order_fulfilment(c1_order.id, db=db_session)
        assert res_o1.status == "COMPLETED"

        # Check distributor commissions after Order 1
        comms_after_o1 = db_session.query(PlanBCommission).filter(
            PlanBCommission.distributor_id == distributor.id
        ).order_by(PlanBCommission.id).all()

        assert len(comms_after_o1) == 2
        
        # Commission 1: Direct Referral Commission (₹500 gross / ₹466.66 net)
        direct_c1 = comms_after_o1[0]
        assert direct_c1.commission_type == "DIRECT"
        assert direct_c1.gross_amount == Decimal("500.00")
        assert direct_c1.operational_cost_amount == Decimal("23.34")
        assert direct_c1.tds_amount == Decimal("10.00")
        assert direct_c1.net_amount == Decimal("466.66")
        assert direct_c1.idempotency_key == f"PB-DIRECT:{distributor.id}"
        assert direct_c1.status == "EARNED"

        # Commission 2: Generation Commission #1 (₹50 gross / ₹46.66 net)
        gen1_c1 = comms_after_o1[1]
        assert gen1_c1.commission_type == "GENERATION"
        assert gen1_c1.gross_amount == Decimal("50.00")
        assert gen1_c1.operational_cost_amount == Decimal("2.34")  # 1st unit rounding
        assert gen1_c1.tds_amount == Decimal("1.00")
        assert gen1_c1.net_amount == Decimal("46.66")
        assert gen1_c1.status == "EARNED"

        # Check distributor wallet after Order 1
        wallet = db_session.query(Wallet).filter(
            Wallet.user_id == distributor.id,
            Wallet.wallet_type == WalletType.DIRECT_REFERRAL,
        ).first()
        assert wallet.balance == Decimal("513.32")  # 466.66 + 46.66

        # Step 5: Referred Customer 2 registers under Plan A with distributor's code (cross-programme referral)
        c2 = User(
            phone="9111222555",
            full_name="Neha Verma",
            referral_code="PANNEHA01",
            referred_by_id=distributor.id,
            programme=Programme.PLAN_A,  # Cross-programme: Plan B distributor refers Plan A customer
            role=UserRole.CUSTOMER,
            account_status=AccountStatus.ACTIVE,
            is_active=True,
        )
        db_session.add(c2)
        db_session.commit()

        # Customer 2 purchases 1 Power Bank (Order 2)
        c2_order = create_order(db_session, c2, power_bank, quantity=1, referral_code=distributor.referral_code)
        
        # Payment confirmation triggers dispatch_order_fulfilment
        res_o2 = dispatch_order_fulfilment(c2_order.id, db=db_session)
        assert res_o2.status == "COMPLETED"

        # Check distributor commissions after Order 2
        comms_after_o2 = db_session.query(PlanBCommission).filter(
            PlanBCommission.distributor_id == distributor.id
        ).order_by(PlanBCommission.id).all()

        assert len(comms_after_o2) == 3

        # Commission 3: Generation Commission #2 (₹50 gross / ₹46.67 net)
        gen2_c2 = comms_after_o2[2]
        assert gen2_c2.commission_type == "GENERATION"
        assert gen2_c2.gross_amount == Decimal("50.00")
        assert gen2_c2.operational_cost_amount == Decimal("2.33")  # Subsequent unit rounding
        assert gen2_c2.tds_amount == Decimal("1.00")
        assert gen2_c2.net_amount == Decimal("46.67")
        assert gen2_c2.status == "EARNED"

        # Verify NO second Direct Referral Commission was created
        direct_comms = [c for c in comms_after_o2 if c.commission_type == "DIRECT"]
        assert len(direct_comms) == 1

        # Check distributor wallet after Order 2
        db_session.refresh(wallet)
        assert wallet.balance == Decimal("559.99")  # 513.32 + 46.67

        # Step 6: Verify Totals Reconciliation
        total_gross = sum(c.gross_amount for c in comms_after_o2)
        total_opcost = sum(c.operational_cost_amount for c in comms_after_o2)
        total_tds = sum(c.tds_amount for c in comms_after_o2)
        total_net = sum(c.net_amount for c in comms_after_o2)

        assert total_gross == Decimal("600.00")
        assert total_opcost == Decimal("28.01")
        assert total_tds == Decimal("12.00")
        assert total_net == Decimal("559.99")
        assert total_gross - total_opcost - total_tds == total_net

        # Step 7: Verify Ledger Transactions
        txs = db_session.query(WalletTransaction).filter(
            WalletTransaction.wallet_id == wallet.id
        ).order_by(WalletTransaction.id).all()
        assert len(txs) == 3
        assert sum(t.amount for t in txs) == Decimal("559.99")
        assert [t.idempotency_key for t in txs] == [c.idempotency_key for c in comms_after_o2]

        # Step 8: Verify Idempotency on repeated dispatch
        res_o1_retry = dispatch_order_fulfilment(c1_order.id, db=db_session)
        res_o2_retry = dispatch_order_fulfilment(c2_order.id, db=db_session)
        assert res_o1_retry.status == "ALREADY_FULFILLED"
        assert res_o2_retry.status == "ALREADY_FULFILLED"

        db_session.refresh(wallet)
        assert wallet.balance == Decimal("559.99")
        txs_after = db_session.query(WalletTransaction).filter(
            WalletTransaction.wallet_id == wallet.id
        ).all()
        assert len(txs_after) == 3

        # Step 9: Verify Distributor Dashboard Overview API endpoint
        with TestClient(app) as client:
            token = create_access_token(user_id=distributor.id, phone=distributor.phone, role="customer")
            res_api = client.get(
                "/api/v1/distributor/reports/dashboard-overview",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res_api.status_code == 200
            data = res_api.json()
            metrics = data["summary_metrics"]

            # Exact metrics verification
            assert Decimal(str(metrics["available_wallet_balance"])) == Decimal("559.99")
            assert Decimal(str(metrics["lifetime_direct_earned"])) == Decimal("466.66")
            assert metrics["has_received_direct_bonus"] is True
            assert Decimal(str(metrics["generation_commission_earned"])) == Decimal("93.33")
            assert metrics["eligible_generation_billing_ids_count"] == 2
            assert Decimal(str(metrics["total_gross_commission"])) == Decimal("600.00")
            assert Decimal(str(metrics["total_operational_cost"])) == Decimal("28.01")
            assert Decimal(str(metrics["total_tds"])) == Decimal("12.00")
            assert Decimal(str(metrics["total_net_commission_earned"])) == Decimal("559.99")
            assert Decimal(str(metrics["total_withdrawn"])) == Decimal("0.00")
            assert Decimal(str(metrics["available_withdrawable_balance"])) == Decimal("559.99")

            # Direct Referral Table list
            assert len(data["direct_commissions"]) == 1
            d_row = data["direct_commissions"][0]
            assert d_row["customer_name"] == "Aarav Sharma"
            assert Decimal(str(d_row["gross_amount"])) == Decimal("500.00")
            assert Decimal(str(d_row["operational_cost"])) == Decimal("23.34")
            assert Decimal(str(d_row["tds_amount"])) == Decimal("10.00")
            assert Decimal(str(d_row["net_amount"])) == Decimal("466.66")
            assert d_row["status"] == "EARNED"

            # Generation Commission Table list
            assert len(data["generation_commissions"]) == 2
            gen_rows = data["generation_commissions"]
            # Descending order from API (newest first)
            assert Decimal(str(gen_rows[0]["gross_amount"])) == Decimal("50.00")
            assert Decimal(str(gen_rows[0]["net_amount"])) == Decimal("46.67")
            assert Decimal(str(gen_rows[1]["gross_amount"])) == Decimal("50.00")
            assert Decimal(str(gen_rows[1]["net_amount"])) == Decimal("46.66")

        # Step 10: Verify HTML page cleanliness (zero raw CSS text in stat labels)
        with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
            html = f.read()

        assert '</span> style="font-size' not in html
        assert '</span>\n              style="font-size' not in html
        assert "₹500 ONCE PER CUSTOMER" not in html
        assert "₹500 ONCE PER DISTRIBUTOR LIFETIME" in html

    finally:
        app.dependency_overrides.pop(get_db, None)
