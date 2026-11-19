"""Tests for ShopEasy - Plan A Test 2: Fix ₹250 Sequential Cashback Visibility.

Validates:
1. At 15/16 contributions:
   - Active cycle earnings: ₹3,750.00.
   - Sequential Commission Wallet available balance: ₹0.00 (ineligible for withdrawal).
   - All 15 individual ₹250 contributions are visible and traceable via /api/v1/cashback/contributions
     and /api/v1/cashback/progress.
   - Wallet transaction ledger remains empty (no premature wallet credit).
2. UI requirements:
   - dashboard.html contains dedicated active cycle earnings and contribution ledger table.
   - api.js defines ShopEasyCashback.getContributions().
   - dashboard.js populates active cycle earnings and renders individual contributions.
3. At 16/16 contributions:
   - 16th contribution transitions cycle to COMPLETED.
   - Exactly ₹4,000.00 credited to Sequential Commission Wallet once.
   - Immutable WalletTransaction ledger entry created.
   - Withdrawal eligibility becomes True.
   - Re-running process_billing_id is strictly idempotent and does not create duplicate credits.
4. Security & Programme Isolation:
   - Plan B user rejected with 403 Forbidden.
   - Unauthenticated request rejected with 401 Unauthorized.
"""

from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.billing import BillingId
from app.models.cashback import (
    PlanACashbackContribution,
    PlanACashbackCycle,
    PlanACashbackEntry,
    PlanACashbackQueue,
    PlanAUnallocatedCashbackReserve,
)
from app.models.enums import (
    AccountStatus,
    OrderStatus,
    PaymentStatus,
    Programme,
    UserRole,
    WalletType,
)
from app.models.order import Order
from app.models.product import Product
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.models.wallet import Wallet, WalletTransaction
from app.services.cashback.plan_a import PlanACashbackService


def test_ui_templates_contain_active_cycle_earnings_and_contribution_ledger():
    """Verify frontend HTML, JS, CSS templates include active cycle earnings and contribution table."""
    with open("frontend/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="sc-active-cycle-earnings"' in html
    assert 'id="sc-contributions-container"' in html
    assert 'id="sc-contributions-body"' in html
    assert 'id="sc-contributions-summary-badge"' in html
    assert "Active Cycle Contribution Ledger (₹250 per Eligible Billing ID)" in html
    assert "Active Cycle Earnings (Pending Completion)" in html

    with open("frontend/js/api.js", "r", encoding="utf-8") as f:
        api_js = f.read()

    assert "getContributions" in api_js
    assert "/cashback/contributions" in api_js

    with open("frontend/js/dashboard.js", "r", encoding="utf-8") as f:
        dash_js = f.read()

    assert "sc-active-cycle-earnings" in dash_js
    assert "sc-contributions-body" in dash_js
    assert "ShopEasyCashback.getContributions" in dash_js
    assert "No wallet ledger transactions yet. The full cycle credit of" in dash_js

    with open("frontend/css/dashboard.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".wallet-balances-group" in css
    assert ".wallet-balance-divider" in css
    assert ".billing-badge" in css


def test_plan_a_cashback_contributions_api_fifteen_contributions_state(api_client: TestClient, db_session: Session):
    """Verify backend API responses at 15/16 contributions matching Punith Kumar H's live scenario."""
    # 1. Create Customer 1 (Punith) and Customer 2 (Referred)
    u1 = User(
        phone="9999443001",
        full_name="Punith Kumar H",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_A,
        account_status=AccountStatus.ACTIVE,
        referral_code="TESTPAR8",
    )
    u2 = User(
        phone="9999443002",
        full_name="Customer 02",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_A,
        account_status=AccountStatus.ACTIVE,
        referral_code="TESTPA7N",
        referred_by_id=None,
    )
    db_session.add_all([u1, u2])
    db_session.commit()

    token1 = create_access_token(user_id=u1.id, role=u1.role.value, phone=u1.phone)
    headers1 = {"Authorization": f"Bearer {token1}"}

    # 2. Setup Queue, Entry, and Cycle for u1
    queue = PlanACashbackQueue(root_user_id=u1.id, last_allocated_position=16)
    db_session.add(queue)
    db_session.flush()

    # Recipient billing for u1
    b_recip = BillingId(
        billing_number="AGD-000999",
        sequence_number=999,
        order_id=1,
        order_item_id=1,
        unit_index=0,
        user_id=u1.id,
        product_id=1,
        programme=Programme.PLAN_A,
    )
    db_session.add(b_recip)
    db_session.flush()

    entry = PlanACashbackEntry(
        queue_id=queue.id,
        user_id=u1.id,
        billing_id=b_recip.id,
        queue_position=1,
        status="ACTIVE",
    )
    db_session.add(entry)
    db_session.flush()

    cycle = PlanACashbackCycle(
        queue_id=queue.id,
        queue_entry_id=entry.id,
        recipient_user_id=u1.id,
        recipient_billing_id=b_recip.id,
        cycle_number=1,
        completed_contributions=15,
        total_earned=Decimal("3750.00"),
        status="ACTIVE",
    )
    db_session.add(cycle)
    db_session.flush()
    queue.active_cycle_id = cycle.id

    # 3. Create 15 contributions from u2
    for i in range(1, 16):
        b_contrib = BillingId(
            billing_number=f"AGD-0010{i:02d}",
            sequence_number=1000 + i,
            order_id=2,
            order_item_id=2,
            unit_index=i - 1,
            user_id=u2.id,
            product_id=1,
            programme=Programme.PLAN_A,
        )
        db_session.add(b_contrib)
        db_session.flush()

        contrib = PlanACashbackContribution(
            queue_id=queue.id,
            cycle_id=cycle.id,
            contributing_billing_id=b_contrib.id,
            contributing_user_id=u2.id,
            recipient_user_id=u1.id,
            amount=Decimal("250.00"),
            status="ALLOCATED",
            idempotency_key=f"TEST-CB-CONTRIB:{b_contrib.id}",
        )
        db_session.add(contrib)
    db_session.commit()

    # 4. Query /api/v1/cashback/progress
    resp_prog = api_client.get("/api/v1/cashback/progress", headers=headers1)
    assert resp_prog.status_code == 200
    prog = resp_prog.json()
    assert prog["has_active_cycle"] is True
    assert prog["completed_contributions"] == 15
    assert Decimal(prog["cashback_amount_earned"]) == Decimal("3750.00")
    assert Decimal(prog["active_cycle_earnings"]) == Decimal("3750.00")
    assert Decimal(prog["current_wallet_balance"]) == Decimal("0.00")
    assert prog["is_completed"] is False
    assert prog["is_withdrawable"] is False
    assert prog["bulbs_on"] == 45
    assert prog["bulbs_off"] == 3
    assert len(prog["active_contributions"]) == 15

    # 5. Query /api/v1/cashback/contributions
    resp_contribs = api_client.get("/api/v1/cashback/contributions", headers=headers1)
    assert resp_contribs.status_code == 200
    contribs = resp_contribs.json()
    assert len(contribs) == 15

    for idx, c in enumerate(contribs):
        assert Decimal(c["amount"]) == Decimal("250.00")
        assert c["status"] == "ALLOCATED"
        assert c["recipient_reference"] == "Cycle #1 (AGD-000999)"
        assert c["contributing_billing_number"] == f"AGD-0010{idx + 1:02d}"

    # 6. Query /api/v1/wallets/transactions for sequential_commission
    resp_tx = api_client.get("/api/v1/wallets/transactions?wallet_type=sequential_commission", headers=headers1)
    assert resp_tx.status_code == 200
    tx_data = resp_tx.json()
    assert len(tx_data["items"]) == 0
    assert tx_data["total"] == 0


def test_sixteenth_contribution_completes_cycle_and_credits_wallet(api_client: TestClient, db_session: Session):
    """Verify that when 16th contribution arrives:
    - Cycle becomes COMPLETED.
    - Exactly ₹4,000.00 is credited once to Sequential Commission Wallet.
    - Immutable ledger entry is created.
    - Full withdrawal eligibility is unlocked.
    - Re-processing 16th contribution is idempotent and does not create duplicate credits.
    """
    # 1. Product
    prod = Product(
        name="Arya Power Bank 10000mAh",
        product_code="PB-TEST-16",
        price=Decimal("3999.00"),
        stock=10000,
        is_power_bank=True,
        is_active=True,
    )
    db_session.add(prod)
    db_session.flush()

    # 2. Customers
    u1 = User(
        phone="9999553001",
        full_name="Recipient 16 Test",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_A,
        account_status=AccountStatus.ACTIVE,
        referral_code="TEST16R1",
    )
    u2 = User(
        phone="9999553002",
        full_name="Contributor 16 Test",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_A,
        account_status=AccountStatus.ACTIVE,
        referral_code="TEST16R2",
        referred_by_id=None,
    )
    db_session.add_all([u1, u2])
    db_session.commit()

    # Referral relationship: u2 referred by u1 (BR-A2)
    rel = ReferralRelationship(
        referrer_id=u1.id,
        referee_id=u2.id,
        referrer_programme=Programme.PLAN_A,
        referee_programme=Programme.PLAN_A,
        referral_code_used="TEST16R1",
        binding_channel="REGISTRATION",
        is_active=True,
    )
    db_session.add(rel)
    db_session.commit()

    token1 = create_access_token(user_id=u1.id, role=u1.role.value, phone=u1.phone)
    headers1 = {"Authorization": f"Bearer {token1}"}

    # Addresses & Orders
    addr1 = Address(user_id=u1.id, recipient_name=u1.full_name, phone=u1.phone, address_line1="123 Test", city="Blr", state="KA", pincode="560001")
    addr2 = Address(user_id=u2.id, recipient_name=u2.full_name, phone=u2.phone, address_line1="123 Test", city="Blr", state="KA", pincode="560001")
    db_session.add_all([addr1, addr2])
    db_session.flush()

    ord1 = Order(user_id=u1.id, address_id=addr1.id, order_number="ORD-T16-1", idempotency_key="IDEMP-T16-1", total_amount=Decimal("3999.00"), order_status=OrderStatus.CONFIRMED, payment_status=PaymentStatus.COMPLETED)
    ord2 = Order(user_id=u2.id, address_id=addr2.id, order_number="ORD-T16-2", idempotency_key="IDEMP-T16-2", total_amount=Decimal("3999.00") * 16, order_status=OrderStatus.CONFIRMED, payment_status=PaymentStatus.COMPLETED)
    db_session.add_all([ord1, ord2])
    db_session.commit()

    # Queue & Cycle for u1
    queue = PlanACashbackQueue(root_user_id=u1.id, last_allocated_position=1)
    db_session.add(queue)
    db_session.flush()

    b_recip = BillingId(billing_number="AGD-002001", sequence_number=2001, order_id=ord1.id, order_item_id=1, unit_index=0, user_id=u1.id, product_id=prod.id, programme=Programme.PLAN_A)
    db_session.add(b_recip)
    db_session.flush()

    entry = PlanACashbackEntry(queue_id=queue.id, user_id=u1.id, billing_id=b_recip.id, queue_position=1, status="ACTIVE")
    db_session.add(entry)
    db_session.flush()

    cycle = PlanACashbackCycle(queue_id=queue.id, queue_entry_id=entry.id, recipient_user_id=u1.id, recipient_billing_id=b_recip.id, cycle_number=1, completed_contributions=15, total_earned=Decimal("3750.00"), status="ACTIVE")
    db_session.add(cycle)
    db_session.flush()
    queue.active_cycle_id = cycle.id

    # Add 15 existing contributions
    for i in range(1, 16):
        b = BillingId(billing_number=f"AGD-0020{i+1:02d}", sequence_number=2001 + i, order_id=ord2.id, order_item_id=2, unit_index=i-1, user_id=u2.id, product_id=prod.id, programme=Programme.PLAN_A)
        db_session.add(b)
        db_session.flush()
        c = PlanACashbackContribution(queue_id=queue.id, cycle_id=cycle.id, contributing_billing_id=b.id, contributing_user_id=u2.id, recipient_user_id=u1.id, amount=Decimal("250.00"), status="ALLOCATED", idempotency_key=f"T16-CB:{b.id}")
        db_session.add(c)
    db_session.commit()

    # 16th Billing ID arrives!
    b16 = BillingId(billing_number="AGD-002017", sequence_number=2017, order_id=ord2.id, order_item_id=2, unit_index=15, user_id=u2.id, product_id=prod.id, programme=Programme.PLAN_A)
    db_session.add(b16)
    db_session.commit()

    # Process 16th billing ID through domain engine
    result = PlanACashbackService.process_billing_id(billing_id=b16.id, db=db_session)
    assert result.status == "CONTRIBUTED"
    assert result.cycle_completed is True
    assert result.credited_amount == Decimal("4000.00")

    # Verify cycle state
    db_session.refresh(cycle)
    assert cycle.status == "COMPLETED"
    assert cycle.completed_contributions == 16
    assert cycle.total_earned == Decimal("4000.00")

    # Verify wallet balance and transaction ledger
    w = db_session.query(Wallet).filter(Wallet.user_id == u1.id, Wallet.wallet_type == WalletType.SEQUENTIAL_COMMISSION).first()
    assert w is not None
    assert w.balance == Decimal("4000.00")

    tx = db_session.query(WalletTransaction).filter(WalletTransaction.wallet_id == w.id).all()
    assert len(tx) == 1
    assert tx[0].amount == Decimal("4000.00")
    assert tx[0].idempotency_key == f"CB-CREDIT:{cycle.id}"

    # Verify API responses at 16/16
    resp_prog = api_client.get("/api/v1/cashback/progress", headers=headers1)
    assert resp_prog.status_code == 200
    prog = resp_prog.json()
    assert prog["completed_contributions"] == 16
    assert prog["is_completed"] is True
    assert prog["is_withdrawable"] is True
    assert Decimal(prog["current_wallet_balance"]) == Decimal("4000.00")
    assert prog["bulbs_on"] == 48
    assert prog["bulbs_off"] == 0

    resp_contribs = api_client.get("/api/v1/cashback/contributions", headers=headers1)
    assert resp_contribs.status_code == 200
    assert len(resp_contribs.json()) == 16

    resp_tx = api_client.get("/api/v1/wallets/transactions?wallet_type=sequential_commission", headers=headers1)
    assert resp_tx.status_code == 200
    tx_resp = resp_tx.json()
    assert len(tx_resp["items"]) == 1
    assert Decimal(tx_resp["items"][0]["amount"]) == Decimal("4000.00")

    # Verify Idempotency: re-running process_billing_id returns ALREADY_PROCESSED and does not duplicate
    result2 = PlanACashbackService.process_billing_id(billing_id=b16.id, db=db_session)
    assert result2.status == "ALREADY_PROCESSED"
    db_session.refresh(w)
    assert w.balance == Decimal("4000.00")
    tx_after = db_session.query(WalletTransaction).filter(WalletTransaction.wallet_id == w.id).all()
    assert len(tx_after) == 1


def test_programme_and_auth_isolation(api_client: TestClient, db_session: Session):
    """Verify Plan B users receive 403 Forbidden and unauthenticated users receive 401 Unauthorized."""
    # Unauthenticated
    resp_anon = api_client.get("/api/v1/cashback/contributions")
    assert resp_anon.status_code == 401

    # Plan B user
    u_plan_b = User(
        phone="9999663001",
        full_name="Plan B User",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_B,
        account_status=AccountStatus.ACTIVE,
        referral_code="PLANBCODE1",
    )
    db_session.add(u_plan_b)
    db_session.commit()

    token_b = create_access_token(user_id=u_plan_b.id, role=u_plan_b.role.value, phone=u_plan_b.phone)
    headers_b = {"Authorization": f"Bearer {token_b}"}

    resp_b = api_client.get("/api/v1/cashback/contributions", headers=headers_b)
    assert resp_b.status_code == 403
    assert "Plan A participants" in resp_b.json()["detail"]
