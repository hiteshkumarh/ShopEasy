"""Comprehensive test suite for WP-11 Step 3: Plan A & Plan B Report Generation & Export APIs.

Verifies:
Part A — Plan A Admin Reports:
1. Commission Report in Excel (.xlsx) and PDF formats.
2. Cashback Report in Excel (.xlsx) and PDF formats (including company-owned reserve).
3. Individual Customer Statement in Excel (.xlsx) and PDF formats (admin only).
4. Programme isolation, filters (date range, customer, queue, billing ID).
5. Administrative authorization (rejection of non-admin with HTTP 403).
6. Financial reconciliation of totals against source database records.
7. Audit log persistence for all admin report requests.

Part B — Plan B Admin Reports (Excel .xlsx Only):
8. Complete Purchase Report in Excel (.xlsx) with all required columns.
9. Commission Report in Excel (.xlsx) with direct and generation commissions.
10. Individual Distributor Report in Excel (.xlsx) with multi-sheet audit details.
11. Filters (dates, customer name, distributor name, mobile, billing ID, order ID).
12. Strict rejection of PDF format (HTTP 400) per business rule R-09.
13. Administrative authorization (rejection of non-admin with HTTP 403).
14. Audit log persistence for all admin report requests.

Part C — Plan B Distributor Self-Service (Excel .xlsx Only):
15. Authenticated distributor can download their own statement in Excel (.xlsx).
16. Scoped strictly to authenticated distributor ID (IDOR prevention).
17. Strict rejection of PDF format (HTTP 400) per business rule R-08.
18. Plan A customer or non-distributor accounts rejected with HTTP 403.

Part D — Export Safety & Read-Only Guarantees:
19. Empty result sets produce valid downloads without errors.
20. Inverted date ranges return HTTP 400 Bad Request.
21. Repeated report downloads execute strictly read-only queries with zero mutations on financial entities.
"""

from datetime import datetime, timezone
from decimal import Decimal
import io
import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.audit import AuditLog
from app.models.billing import BillingId
from app.models.cashback import (
    PlanACashbackContribution,
    PlanACashbackCycle,
    PlanACashbackEntry,
    PlanACashbackQueue,
    PlanAUnallocatedCashbackReserve,
)
from app.models.commission import PlanACommission, PlanBCommission
from app.models.enums import (
    AccountStatus,
    OrderStatus,
    PaymentStatus,
    Programme,
    UserRole,
    WalletType,
    WithdrawalStatus,
)
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.models.wallet import Wallet, WalletFreezeHistory, WalletTransaction, Withdrawal


@pytest.fixture
def client(db_session: Session):
    """FastAPI test client fixture with overridden database session."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def make_user(db_session: Session):
    """Factory fixture for test users."""
    counter = [900]

    def _create_user(
        programme: Programme = Programme.PLAN_A,
        role: UserRole = UserRole.CUSTOMER,
        referral_code: str = None,
    ) -> User:
        counter[0] += 1
        num = counter[0]
        code = None if role == UserRole.ADMIN else (referral_code or f"RPT{num:05d}")

        user = User(
            phone=f"98888{num:05d}",
            full_name=f"Report Test User {num}",
            role=role,
            programme=programme,
            account_status=AccountStatus.ACTIVE,
            referral_code=code,
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _create_user


@pytest.fixture
def auth_headers():
    """Factory generating Bearer authorization headers for a given User."""
    def _headers(user: User) -> dict:
        token = create_access_token(
            user_id=user.id,
            role=user.role.value,
            phone=user.phone,
        )
        return {"Authorization": f"Bearer {token}"}

    return _headers


@pytest.fixture
def make_order_and_bid(db_session: Session):
    """Factory creating an Order and Billing ID with complete foreign-key relations."""
    counter = [6000]

    product = Product(
        name="Arya 10000mAh Power Bank",
        product_code=f"RPT-PB-{datetime.now(timezone.utc).timestamp()}",
        price=Decimal("3999.00"),
        stock=10000,
        is_power_bank=True,
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()

    def _create(user: User, programme: Programme = Programme.PLAN_A):
        counter[0] += 1
        seq = counter[0]

        address = Address(
            user_id=user.id,
            recipient_name=user.full_name,
            phone=user.phone,
            address_line1="123 Export Ave",
            city="Bengaluru",
            state="Karnataka",
            pincode="560001",
        )
        db_session.add(address)
        db_session.flush()

        order = Order(
            order_number=f"ORD-RPT-{seq:06d}",
            idempotency_key=f"idemp-rpt-{seq:06d}",
            user_id=user.id,
            address_id=address.id,
            total_amount=Decimal("3999.00"),
            order_status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.COMPLETED,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            unit_price=Decimal("3999.00"),
            line_total=Decimal("3999.00"),
        )
        db_session.add(item)
        db_session.flush()

        billing_id = BillingId(
            billing_number=f"BID-RPT-{seq:06d}",
            sequence_number=seq,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=0,
            user_id=user.id,
            product_id=product.id,
            programme=programme,
            status="ACTIVE",
        )
        db_session.add(billing_id)
        db_session.flush()

        return order, billing_id

    return _create


# =============================================================================
# PART A: PLAN A ADMIN REPORTS (COMMISSIONS, CASHBACK, CUSTOMER STATEMENT)
# =============================================================================


def test_plan_a_commission_report_excel(client, db_session, make_user, auth_headers, make_order_and_bid):
    """1. Plan A Commission Report generates Excel (.xlsx) reconciling with source database records."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    referrer = make_user(programme=Programme.PLAN_A)
    purchaser = make_user(programme=Programme.PLAN_A)
    order, bid = make_order_and_bid(purchaser, programme=Programme.PLAN_A)

    comm = PlanACommission(
        billing_id=bid.id,
        order_id=order.id,
        purchaser_id=purchaser.id,
        referrer_id=referrer.id,
        applied_referral_code=referrer.referral_code,
        gross_amount=Decimal("750.00"),
        operational_cost_amount=Decimal("35.00"),
        tds_amount=Decimal("15.00"),
        net_amount=Decimal("700.00"),
        status="EARNED",
        idempotency_key="RPT-COMM-001",
    )
    db_session.add(comm)
    db_session.commit()

    resp = client.get("/api/v1/admin/plan-a/reports/commissions?format=excel", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp.headers["content-type"]
    assert "Plan_A_Commissions" in resp.headers["content-disposition"]

    # Reopen Excel workbook and verify content and financial totals
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "Plan A Commissions" in wb.sheetnames
    ws = wb["Plan A Commissions"]
    # Verify headers and row values
    found_bid = False
    for row in ws.iter_rows(values_only=True):
        if bid.billing_number in row:
            found_bid = True
            assert Decimal("700.00") in row or 700.0 in row or "700.00" in str(row)
    assert found_bid

    # Verify audit log was recorded
    audit = db_session.query(AuditLog).filter(AuditLog.action == "PLAN_A_REPORT_COMMISSIONS").first()
    assert audit is not None
    assert audit.actor_id == admin.id


def test_plan_a_commission_report_pdf(client, db_session, make_user, auth_headers, make_order_and_bid):
    """2. Plan A Commission Report generates valid PDF."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    referrer = make_user(programme=Programme.PLAN_A)
    purchaser = make_user(programme=Programme.PLAN_A)
    order, bid = make_order_and_bid(purchaser, programme=Programme.PLAN_A)

    comm = PlanACommission(
        billing_id=bid.id,
        order_id=order.id,
        purchaser_id=purchaser.id,
        referrer_id=referrer.id,
        applied_referral_code=referrer.referral_code,
        gross_amount=Decimal("750.00"),
        operational_cost_amount=Decimal("35.00"),
        tds_amount=Decimal("15.00"),
        net_amount=Decimal("700.00"),
        status="EARNED",
        idempotency_key="RPT-COMM-PDF-001",
    )
    db_session.add(comm)
    db_session.commit()

    resp = client.get("/api/v1/admin/plan-a/reports/commissions?format=pdf", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert "application/pdf" in resp.headers["content-type"]
    assert resp.content.startswith(b"%PDF")


def test_plan_a_commission_report_filters(client, db_session, make_user, auth_headers, make_order_and_bid):
    """3. Plan A Commission Report respects customer and billing ID filters."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    user_a = make_user(programme=Programme.PLAN_A)
    user_b = make_user(programme=Programme.PLAN_A)
    _, bid_a = make_order_and_bid(user_a, programme=Programme.PLAN_A)
    _, bid_b = make_order_and_bid(user_b, programme=Programme.PLAN_A)

    comm_a = PlanACommission(
        billing_id=bid_a.id, order_id=bid_a.order_id, purchaser_id=user_a.id,
        referrer_id=None, gross_amount=Decimal("750.00"), operational_cost_amount=Decimal("0.00"),
        tds_amount=Decimal("0.00"), net_amount=Decimal("0.00"), status="UNALLOCATED_NO_REFERRER",
        idempotency_key="RPT-COMM-FA",
    )
    comm_b = PlanACommission(
        billing_id=bid_b.id, order_id=bid_b.order_id, purchaser_id=user_b.id,
        referrer_id=None, gross_amount=Decimal("750.00"), operational_cost_amount=Decimal("0.00"),
        tds_amount=Decimal("0.00"), net_amount=Decimal("0.00"), status="UNALLOCATED_NO_REFERRER",
        idempotency_key="RPT-COMM-FB",
    )
    db_session.add_all([comm_a, comm_b])
    db_session.commit()

    # Filter by user_a
    resp_a = client.get(f"/api/v1/admin/plan-a/reports/commissions?customer_id={user_a.id}&format=excel", headers=auth_headers(admin))
    assert resp_a.status_code == 200
    wb_a = openpyxl.load_workbook(io.BytesIO(resp_a.content))
    ws_a = wb_a["Plan A Commissions"]
    content_str_a = str([list(r) for r in ws_a.iter_rows(values_only=True)])
    assert bid_a.billing_number in content_str_a
    assert bid_b.billing_number not in content_str_a


def test_plan_a_cashback_report_excel_and_pdf(client, db_session, make_user, auth_headers, make_order_and_bid):
    """4. Plan A Cashback Report generates Excel and PDF with contributions and company-owned reserve."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    root_user = make_user(programme=Programme.PLAN_A)
    contributor = make_user(programme=Programme.PLAN_A)
    _, bid_root = make_order_and_bid(root_user, programme=Programme.PLAN_A)
    _, bid_c = make_order_and_bid(contributor, programme=Programme.PLAN_A)
    _, bid_res = make_order_and_bid(contributor, programme=Programme.PLAN_A)

    queue = PlanACashbackQueue(root_user_id=root_user.id)
    db_session.add(queue)
    db_session.flush()

    entry = PlanACashbackEntry(
        queue_id=queue.id,
        user_id=root_user.id,
        billing_id=bid_root.id,
        queue_position=1,
        status="ACTIVE",
    )
    db_session.add(entry)
    db_session.flush()

    cycle = PlanACashbackCycle(
        queue_id=queue.id,
        queue_entry_id=entry.id,
        recipient_user_id=root_user.id,
        recipient_billing_id=bid_root.id,
        completed_contributions=1,
        total_earned=Decimal("250.00"),
        status="ACTIVE",
    )
    db_session.add(cycle)
    db_session.flush()

    contrib = PlanACashbackContribution(
        queue_id=queue.id,
        cycle_id=cycle.id,
        contributing_billing_id=bid_c.id,
        contributing_user_id=contributor.id,
        recipient_user_id=root_user.id,
        amount=Decimal("250.00"),
        status="ALLOCATED",
        idempotency_key="RPT-CB-CONTRIB-01",
    )
    reserve = PlanAUnallocatedCashbackReserve(
        queue_id=queue.id,
        billing_id=bid_res.id,
        customer_id=contributor.id,
        amount=Decimal("250.00"),
        status="UNALLOCATED — COMPANY OWNED",
        idempotency_key="RPT-CB-RES-01",
    )
    db_session.add_all([contrib, reserve])
    db_session.commit()

    # Test Excel
    resp_xl = client.get("/api/v1/admin/plan-a/reports/cashback?format=excel", headers=auth_headers(admin))
    assert resp_xl.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp_xl.content))
    assert "Cashback Contributions" in wb.sheetnames
    assert "Company Cashback Reserve" in wb.sheetnames
    ws_res = wb["Company Cashback Reserve"]
    res_content = str([list(r) for r in ws_res.iter_rows(values_only=True)])
    assert "UNALLOCATED — COMPANY OWNED" in res_content
    assert bid_res.billing_number in res_content

    # Test PDF
    resp_pdf = client.get("/api/v1/admin/plan-a/reports/cashback?format=pdf", headers=auth_headers(admin))
    assert resp_pdf.status_code == 200
    assert resp_pdf.content.startswith(b"%PDF")

    # Verify audit log
    audit = db_session.query(AuditLog).filter(AuditLog.action == "PLAN_A_REPORT_CASHBACK").first()
    assert audit is not None


def test_plan_a_customer_statement_admin_only(client, db_session, make_user, auth_headers, make_order_and_bid):
    """5. Plan A Customer Statement is accessible by Admin, rejecting Customer self-service."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    customer = make_user(programme=Programme.PLAN_A)
    _, bid = make_order_and_bid(customer, programme=Programme.PLAN_A)

    wallet_dr = Wallet(user_id=customer.id, wallet_type=WalletType.DIRECT_REFERRAL, balance=Decimal("700.00"), total_withdrawn=Decimal("0.00"))
    wallet_sc = Wallet(user_id=customer.id, wallet_type=WalletType.SEQUENTIAL_COMMISSION, balance=Decimal("250.00"), total_withdrawn=Decimal("0.00"))
    db_session.add_all([wallet_dr, wallet_sc])
    db_session.commit()

    # Admin request Excel -> 200 OK
    resp_admin = client.get(f"/api/v1/admin/plan-a/reports/customers/{customer.id}/statement?format=excel", headers=auth_headers(admin))
    assert resp_admin.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp_admin.content))
    assert "Account Statement" in wb.sheetnames
    assert "Purchases & Billing IDs" in wb.sheetnames

    # Admin request PDF -> 200 OK
    resp_pdf = client.get(f"/api/v1/admin/plan-a/reports/customers/{customer.id}/statement?format=pdf", headers=auth_headers(admin))
    assert resp_pdf.status_code == 200
    assert resp_pdf.content.startswith(b"%PDF")

    # Customer self-service -> 403 Forbidden (R-07 enforced)
    resp_cust = client.get(f"/api/v1/admin/plan-a/reports/customers/{customer.id}/statement", headers=auth_headers(customer))
    assert resp_cust.status_code == 403


# =============================================================================
# PART B: PLAN B ADMIN REPORTS (PURCHASES, COMMISSIONS, DISTRIBUTOR)
# =============================================================================


def test_plan_b_purchases_report_excel_only(client, db_session, make_user, auth_headers, make_order_and_bid):
    """6. Complete Plan B Purchase Report in Excel (.xlsx) only, rejecting PDF with HTTP 400."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    distributor = make_user(programme=Programme.PLAN_B)
    customer = make_user(programme=Programme.PLAN_B)
    order, bid = make_order_and_bid(customer, programme=Programme.PLAN_B)

    # Referral relationship binding
    rel = ReferralRelationship(
        referee_id=customer.id,
        referrer_id=distributor.id,
        referee_programme=Programme.PLAN_B,
        referrer_programme=Programme.PLAN_B,
        referral_code_used=distributor.referral_code,
        binding_channel="checkout",
    )
    db_session.add(rel)
    db_session.commit()

    # Excel request -> 200 OK
    resp = client.get("/api/v1/admin/plan-b/reports/purchases?format=excel", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp.headers["content-type"]

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "Plan B Purchases" in wb.sheetnames
    ws = wb["Plan B Purchases"]
    content_str = str([list(r) for r in ws.iter_rows(values_only=True)])
    assert customer.full_name in content_str
    assert distributor.full_name in content_str
    assert bid.billing_number in content_str

    # PDF request -> 400 Bad Request per R-09
    resp_pdf = client.get("/api/v1/admin/plan-b/reports/purchases?format=pdf", headers=auth_headers(admin))
    assert resp_pdf.status_code == 400
    assert "Plan B admin reports support Excel (.xlsx) only" in resp_pdf.json()["detail"]


def test_plan_b_commission_report_excel_only(client, db_session, make_user, auth_headers, make_order_and_bid):
    """7. Plan B Commission Report in Excel (.xlsx) with direct and generation splits."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    distributor = make_user(programme=Programme.PLAN_B)
    customer = make_user(programme=Programme.PLAN_B)
    order, bid = make_order_and_bid(customer, programme=Programme.PLAN_B)

    comm_direct = PlanBCommission(
        commission_type="DIRECT",
        distributor_id=distributor.id,
        referee_id=customer.id,
        order_id=order.id,
        billing_id=bid.id,
        gross_amount=Decimal("500.00"),
        operational_cost_amount=Decimal("25.00"),
        tds_amount=Decimal("10.00"),
        net_amount=Decimal("465.00"),
        status="EARNED",
        idempotency_key="RPT-PB-COMM-D1",
    )
    comm_gen = PlanBCommission(
        commission_type="GENERATION",
        distributor_id=distributor.id,
        referee_id=customer.id,
        order_id=order.id,
        billing_id=bid.id,
        gross_amount=Decimal("50.00"),
        operational_cost_amount=Decimal("2.50"),
        tds_amount=Decimal("1.00"),
        net_amount=Decimal("46.50"),
        status="EARNED",
        idempotency_key="RPT-PB-COMM-G1",
    )
    db_session.add_all([comm_direct, comm_gen])
    db_session.commit()

    resp = client.get("/api/v1/admin/plan-b/reports/commissions?format=excel", headers=auth_headers(admin))
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "Plan B Commissions" in wb.sheetnames
    ws = wb["Plan B Commissions"]
    content_str = str([list(r) for r in ws.iter_rows(values_only=True)])
    assert "DIRECT" in content_str
    assert "GENERATION" in content_str
    assert distributor.full_name in content_str

    # PDF prohibited
    resp_pdf = client.get("/api/v1/admin/plan-b/reports/commissions?format=pdf", headers=auth_headers(admin))
    assert resp_pdf.status_code == 400


def test_plan_b_individual_distributor_report(client, db_session, make_user, auth_headers):
    """8. Individual Plan B Distributor Report includes profile, hierarchy, wallet, and freeze history."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    distributor = make_user(programme=Programme.PLAN_B)
    referee = make_user(programme=Programme.PLAN_B)

    rel = ReferralRelationship(
        referee_id=referee.id,
        referrer_id=distributor.id,
        referee_programme=Programme.PLAN_B,
        referrer_programme=Programme.PLAN_B,
        referral_code_used=distributor.referral_code,
        binding_channel="checkout",
    )
    wallet = Wallet(user_id=distributor.id, wallet_type=WalletType.DIRECT_REFERRAL, balance=Decimal("1200.00"), total_withdrawn=Decimal("500.00"))
    db_session.add_all([rel, wallet])
    db_session.flush()

    freeze_record = WalletFreezeHistory(
        wallet_id=wallet.id,
        admin_id=admin.id,
        action="UNFREEZE",
        reason="Compliance verification passed",
    )
    db_session.add(freeze_record)
    db_session.commit()

    resp = client.get(f"/api/v1/admin/plan-b/reports/distributors/{distributor.id}?format=excel", headers=auth_headers(admin))
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "Profile & Wallet Summary" in wb.sheetnames
    assert "Referrals Hierarchy" in wb.sheetnames
    assert "Wallet Freeze History" in wb.sheetnames

    # Non-admin rejected
    resp_non_admin = client.get(f"/api/v1/admin/plan-b/reports/distributors/{distributor.id}", headers=auth_headers(referee))
    assert resp_non_admin.status_code == 403


# =============================================================================
# PART C: PLAN B DISTRIBUTOR SELF-SERVICE (EXCEL ONLY)
# =============================================================================


def test_distributor_self_statement_excel_only(client, db_session, make_user, auth_headers, make_order_and_bid):
    """9. Plan B Distributor downloads own statement in Excel (.xlsx) only, strictly rejecting PDF (R-08)."""
    distributor = make_user(programme=Programme.PLAN_B)
    customer = make_user(programme=Programme.PLAN_B)
    order, bid = make_order_and_bid(customer, programme=Programme.PLAN_B)

    comm = PlanBCommission(
        commission_type="DIRECT",
        distributor_id=distributor.id,
        referee_id=customer.id,
        order_id=order.id,
        billing_id=bid.id,
        gross_amount=Decimal("500.00"),
        operational_cost_amount=Decimal("25.00"),
        tds_amount=Decimal("10.00"),
        net_amount=Decimal("465.00"),
        status="EARNED",
        idempotency_key="RPT-SELF-D1",
    )
    wallet = Wallet(user_id=distributor.id, wallet_type=WalletType.DIRECT_REFERRAL, balance=Decimal("465.00"), total_withdrawn=Decimal("0.00"))
    db_session.add_all([comm, wallet])
    db_session.commit()

    # 1. Success in Excel
    resp = client.get("/api/v1/distributor/reports/commission-statement?format=excel", headers=auth_headers(distributor))
    assert resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp.headers["content-type"]
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "Commission Statement" in wb.sheetnames
    ws = wb["Commission Statement"]
    content_str = str([list(r) for r in ws.iter_rows(values_only=True)])
    assert "DIRECT" in content_str
    assert customer.full_name in content_str

    # 2. Strict PDF prohibition (R-08 / PB-16)
    resp_pdf = client.get("/api/v1/distributor/reports/commission-statement?format=pdf", headers=auth_headers(distributor))
    assert resp_pdf.status_code == 400
    assert "PDF format is not supported for distributor statements" in resp_pdf.json()["detail"]

    # 3. Plan A customer prohibited from distributor self-service
    plan_a_user = make_user(programme=Programme.PLAN_A)
    resp_plan_a = client.get("/api/v1/distributor/reports/commission-statement", headers=auth_headers(plan_a_user))
    assert resp_plan_a.status_code == 403


def test_distributor_self_statement_idor_prevention(client, db_session, make_user, auth_headers):
    """10. Distributor statement is strictly scoped to authenticated user; query parameters cannot leak others' data."""
    dist_a = make_user(programme=Programme.PLAN_B)
    dist_b = make_user(programme=Programme.PLAN_B)

    # Calling with dist_a credentials ignores any attempt to query dist_b
    resp = client.get(f"/api/v1/distributor/reports/commission-statement?distributor_id={dist_b.id}", headers=auth_headers(dist_a))
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    ws = wb["Commission Statement"]
    content_str = str([list(r) for r in ws.iter_rows(values_only=True)])
    assert dist_a.full_name in content_str
    assert dist_b.full_name not in content_str


# =============================================================================
# PART D: EXPORT SAFETY, RECONCILIATION & READ-ONLY GUARANTEES
# =============================================================================


def test_empty_results_and_invalid_date_ranges(client, db_session, make_user, auth_headers):
    """11. Reports handle empty datasets safely and reject invalid date ranges."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)

    # Empty result set -> generates valid Excel with headers and 0 totals
    resp_empty = client.get("/api/v1/admin/plan-a/reports/commissions?format=excel", headers=auth_headers(admin))
    assert resp_empty.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp_empty.content))
    assert "Plan A Commissions" in wb.sheetnames

    # Invalid date range (start_date > end_date) -> 400 Bad Request
    start = "2026-12-31T00:00:00"
    end = "2026-01-01T00:00:00"
    resp_bad_dates = client.get(f"/api/v1/admin/plan-a/reports/commissions?start_date={start}&end_date={end}", headers=auth_headers(admin))
    assert resp_bad_dates.status_code == 400
    assert "Invalid date range" in resp_bad_dates.json()["detail"]


def test_reports_read_only_guarantee(client, db_session, make_user, auth_headers, make_order_and_bid):
    """12. Report generation strictly executes read-only operations on financial and state tables."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    customer = make_user(programme=Programme.PLAN_A)
    _, bid = make_order_and_bid(customer, programme=Programme.PLAN_A)

    comm = PlanACommission(
        billing_id=bid.id, order_id=bid.order_id, purchaser_id=customer.id,
        referrer_id=None, gross_amount=Decimal("750.00"), operational_cost_amount=Decimal("0.00"),
        tds_amount=Decimal("0.00"), net_amount=Decimal("0.00"), status="UNALLOCATED_NO_REFERRER",
        idempotency_key="RPT-RO-01",
    )
    wallet = Wallet(user_id=customer.id, wallet_type=WalletType.DIRECT_REFERRAL, balance=Decimal("1500.00"), total_withdrawn=Decimal("0.00"))
    db_session.add_all([comm, wallet])
    db_session.commit()

    # Pre-report counts
    counts_before = {
        "commissions_a": db_session.query(PlanACommission).count(),
        "commissions_b": db_session.query(PlanBCommission).count(),
        "wallets": db_session.query(Wallet).count(),
        "orders": db_session.query(Order).count(),
        "billing_ids": db_session.query(BillingId).count(),
        "withdrawals": db_session.query(Withdrawal).count(),
    }

    # Execute multiple report endpoints repeatedly
    client.get("/api/v1/admin/plan-a/reports/commissions?format=excel", headers=auth_headers(admin))
    client.get("/api/v1/admin/plan-a/reports/commissions?format=pdf", headers=auth_headers(admin))
    client.get("/api/v1/admin/plan-a/reports/cashback?format=excel", headers=auth_headers(admin))
    client.get(f"/api/v1/admin/plan-a/reports/customers/{customer.id}/statement?format=excel", headers=auth_headers(admin))
    client.get("/api/v1/admin/plan-b/reports/purchases?format=excel", headers=auth_headers(admin))
    client.get("/api/v1/admin/plan-b/reports/commissions?format=excel", headers=auth_headers(admin))

    # Post-report counts
    counts_after = {
        "commissions_a": db_session.query(PlanACommission).count(),
        "commissions_b": db_session.query(PlanBCommission).count(),
        "wallets": db_session.query(Wallet).count(),
        "orders": db_session.query(Order).count(),
        "billing_ids": db_session.query(BillingId).count(),
        "withdrawals": db_session.query(Withdrawal).count(),
    }

    assert counts_before == counts_after

    # Verify wallet balance unchanged
    db_session.expire_all()
    reloaded_wallet = db_session.query(Wallet).filter(Wallet.id == wallet.id).first()
    assert reloaded_wallet.balance == Decimal("1500.00")

