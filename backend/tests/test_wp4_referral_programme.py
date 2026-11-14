"""WP-4 Programme Registration & Referral Rules Test Suite.

Comprehensive unit and integration tests covering:
  1. Programme selection at registration (Plan A vs Plan B; schema validation).
  2. Mobile uniqueness across programmes (one phone cannot register in both).
  3. Unique referral codes with programme prefixes (PA for Plan A, PB for Plan B).
  4. Referral direction matrix:
       - A -> A: ALLOWED
       - B -> A: ALLOWED
       - A -> B: FORBIDDEN
       - B -> B: FORBIDDEN
  5. Referrer eligibility:
       - Plan A referrer requires a paid purchase / Billing ID (RG-07).
       - Plan B distributor requires a qualifying purchase to activate code (BR-X2, RG-10A).
  6. Account status behaviors:
       - Blocked distributor: can log in and view, cannot refer or earn (RG-14).
       - Deactivated distributor: cannot log in.
  7. Programme-aware login separation (RG-12):
       - Plan A credentials cannot log into Plan B portal.
       - Plan B credentials cannot log into Plan A portal.
  8. Permanent referral binding at checkout:
       - Relationship saved to referral_relationships and users.referred_by_id.
       - Append-only audit log created.
       - Referrer cannot be changed.
  9. Later-order referral binding (BR-X1 Option B):
       - Order 1 without code: unreferred.
       - Order 2 with code: permanently bound; no retroactive changes to order 1.
  10. Exact error messages:
       - Plan A: "Invalid Referral"
       - Plan B: "Wrong Referral ID"
"""

from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.audit import AuditLog
from app.models.cart import CartItem
from app.models.enums import (
    AccountStatus,
    OrderStatus,
    PaymentStatus,
    Programme,
    UserRole,
)
from app.models.order import Order, OrderItem
from app.models.payment import PaymentAttempt
from app.models.product import Product
from app.models.queue import QueueControl
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.services.referral import generate_referral_code, validate_referral_code


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

def create_test_product(db: Session, name: str = "Arya Power Bank PB-3999", price: Decimal = Decimal("3999.00")) -> Product:
    """Helper to create an active test product."""
    prod = Product(
        name=name,
        description="High capacity power bank",
        price=price,
        stock=100,
        is_active=True,
        is_power_bank=True,
        product_code="PB-3999",
    )
    db.add(prod)
    db.flush()
    return prod


def create_test_address(db: Session, user: User) -> Address:
    """Helper to create a test delivery address for a user."""
    addr = Address(
        user_id=user.id,
        recipient_name=user.full_name,
        phone=user.phone,
        address_line1="123 Test Street",
        city="Mumbai",
        state="Maharashtra",
        pincode="400001",
        is_default=True,
    )
    db.add(addr)
    db.flush()
    return addr


def add_confirmed_paid_order(db: Session, user: User, product: Product, referral_code: str = None) -> Order:
    """Helper to record a confirmed, paid order for a user (simulating qualifying purchase)."""
    addr = create_test_address(db, user)
    order = Order(
        order_number=f"ORD-CONF-{user.id}-{user.programme.value}",
        idempotency_key=f"idemp-{user.id}-{user.phone}",
        user_id=user.id,
        address_id=addr.id,
        total_amount=product.price,
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
        payment_reference="SIM-PAID-001",
        applied_referral_code=referral_code,
        is_first_successful_order=True,
    )
    db.add(order)
    db.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        product_name=product.name,
        unit_price=product.price,
        quantity=1,
        line_total=product.price,
    )
    db.add(item)
    db.flush()
    return order


# ---------------------------------------------------------------------------
# 1. Programme Registration & Validation Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestProgrammeRegistration:
    """Tests for programme selection at registration and schema constraints."""

    def test_plan_a_customer_registration_success(self, api_client: TestClient) -> None:
        """Verify successful Plan A customer registration via customer portal."""
        payload = {
            "full_name": "Aarav Sharma",
            "phone": "9820011111",
            "password": "Password123!",
            "confirm_password": "Password123!",
            "programme": "PLAN_A",
        }
        res = api_client.post("/api/v1/auth/customer/register", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["full_name"] == "Aarav Sharma"
        assert data["phone"] == "9820011111"
        assert data["programme"] == "PLAN_A"
        assert data["account_status"] == "ACTIVE"
        assert data["referral_code"].startswith("PA")
        assert len(data["referral_code"]) == 8

    def test_plan_b_distributor_registration_success(self, api_client: TestClient) -> None:
        """Verify successful Plan B distributor registration via distributor portal."""
        payload = {
            "full_name": "Bhavin Patel",
            "phone": "9820022222",
            "password": "Password123!",
            "confirm_password": "Password123!",
            "programme": "PLAN_B",
        }
        res = api_client.post("/api/v1/auth/distributor/register", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["full_name"] == "Bhavin Patel"
        assert data["phone"] == "9820022222"
        assert data["programme"] == "PLAN_B"
        assert data["account_status"] == "ACTIVE"
        assert data["referral_code"].startswith("PB")
        assert len(data["referral_code"]) == 8

    def test_registration_fails_without_programme(self, api_client: TestClient) -> None:
        """Verify registration is rejected with 422 if programme is missing (RG-01)."""
        payload = {
            "full_name": "No Programme User",
            "phone": "9820033333",
            "password": "Password123!",
            "confirm_password": "Password123!",
        }
        res = api_client.post("/api/v1/auth/customer/register", json=payload)
        assert res.status_code == 422

    def test_registration_fails_with_invalid_programme(self, api_client: TestClient) -> None:
        """Verify registration is rejected with 422 if programme is invalid (e.g. LEGACY or arbitrary)."""
        payload = {
            "full_name": "Invalid Programme User",
            "phone": "9820044444",
            "password": "Password123!",
            "confirm_password": "Password123!",
            "programme": "LEGACY",
        }
        res = api_client.post("/api/v1/auth/customer/register", json=payload)
        assert res.status_code == 422

    def test_customer_portal_rejects_plan_b_registration(self, api_client: TestClient) -> None:
        """Customer endpoint rejects Plan B registration payload."""
        payload = {
            "full_name": "Wrong Portal User",
            "phone": "9820055555",
            "password": "Password123!",
            "confirm_password": "Password123!",
            "programme": "PLAN_B",
        }
        res = api_client.post("/api/v1/auth/customer/register", json=payload)
        assert res.status_code == 400
        assert "Customer portal registration is strictly for Plan A" in res.json()["detail"]

    def test_distributor_portal_rejects_plan_a_registration(self, api_client: TestClient) -> None:
        """Distributor endpoint rejects Plan A registration payload."""
        payload = {
            "full_name": "Wrong Portal User",
            "phone": "9820066666",
            "password": "Password123!",
            "confirm_password": "Password123!",
            "programme": "PLAN_A",
        }
        res = api_client.post("/api/v1/auth/distributor/register", json=payload)
        assert res.status_code == 400
        assert "Distributor registration is strictly for Plan B" in res.json()["detail"]


# ---------------------------------------------------------------------------
# 2. Mobile Uniqueness Across Programmes (RG-02)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMobileUniquenessAcrossProgrammes:
    """One mobile number cannot register in both programmes."""

    def test_cannot_register_same_phone_in_both_programmes(self, api_client: TestClient) -> None:
        """Registering phone in Plan A blocks registration of same phone in Plan B (and vice-versa)."""
        phone = "9820077777"
        payload_a = {
            "full_name": "Aarav A",
            "phone": phone,
            "password": "Password123!",
            "confirm_password": "Password123!",
            "programme": "PLAN_A",
        }
        res_a = api_client.post("/api/v1/auth/customer/register", json=payload_a)
        assert res_a.status_code == 201

        # Attempt to register same mobile under Plan B
        payload_b = {
            "full_name": "Aarav B",
            "phone": phone,
            "password": "Password123!",
            "confirm_password": "Password123!",
            "programme": "PLAN_B",
        }
        res_b = api_client.post("/api/v1/auth/distributor/register", json=payload_b)
        assert res_b.status_code == 409
        assert "A user with this mobile number already exists." in res_b.json()["detail"]

    def test_cannot_register_same_phone_in_same_programme_twice(self, api_client: TestClient) -> None:
        """Registering duplicate phone in the same programme also returns 409."""
        phone = "9820088888"
        payload = {
            "full_name": "User One",
            "phone": phone,
            "password": "Password123!",
            "confirm_password": "Password123!",
            "programme": "PLAN_B",
        }
        res1 = api_client.post("/api/v1/auth/distributor/register", json=payload)
        assert res1.status_code == 201

        res2 = api_client.post("/api/v1/auth/distributor/register", json=payload)
        assert res2.status_code == 409


# ---------------------------------------------------------------------------
# 3. Referral Code Generation & Prefixes (RG-03)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestReferralCodeGeneration:
    """Verify prefix assignment and collision retry behavior."""

    def test_referral_code_prefixes(self, db_session: Session) -> None:
        """Verify code prefix depends on programme."""
        code_a = generate_referral_code(db_session, programme=Programme.PLAN_A)
        assert code_a.startswith("PA")
        assert len(code_a) == 8

        code_b = generate_referral_code(db_session, programme=Programme.PLAN_B)
        assert code_b.startswith("PB")
        assert len(code_b) == 8

        code_legacy = generate_referral_code(db_session, programme=Programme.LEGACY)
        assert code_legacy.startswith("REF")
        assert len(code_legacy) == 9


# ---------------------------------------------------------------------------
# 4. Referral Direction Matrix (RG-08)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestReferralDirectionMatrix:
    """Verify:
      Allowed: A -> A, B -> A
      Forbidden: A -> B, B -> B
    """

    def test_allowed_direction_a_to_a(self, db_session: Session) -> None:
        """Plan A referrer referring Plan A customer (A->A) is ALLOWED."""
        prod = create_test_product(db_session)

        # Referrer A with 1 qualifying purchase
        referrer_a = User(
            full_name="Referrer Plan A",
            phone="9811100001",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PAAAAA01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(referrer_a)
        db_session.flush()
        add_confirmed_paid_order(db_session, referrer_a, prod)

        # Referee A
        referee_a = User(
            full_name="Referee Plan A",
            phone="9811100002",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PAAAAA02",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(referee_a)
        db_session.flush()

        # Validation must succeed
        validated = validate_referral_code(db_session, referee_a, "PAAAAA01")
        assert validated.id == referrer_a.id

    def test_allowed_direction_b_to_a(self, db_session: Session) -> None:
        """Plan B distributor referring Plan A customer (B->A) is ALLOWED."""
        prod = create_test_product(db_session)

        # Referrer B with 1 qualifying purchase (BR-X2)
        distributor_b = User(
            full_name="Distributor Plan B",
            phone="9811100003",
            programme=Programme.PLAN_B,
            account_status=AccountStatus.ACTIVE,
            referral_code="PBBBBB01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(distributor_b)
        db_session.flush()
        add_confirmed_paid_order(db_session, distributor_b, prod)

        # Referee A
        referee_a = User(
            full_name="Referee Plan A",
            phone="9811100004",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PAAAAA04",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(referee_a)
        db_session.flush()

        # Validation must succeed
        validated = validate_referral_code(db_session, referee_a, "PBBBBB01")
        assert validated.id == distributor_b.id

    def test_forbidden_direction_a_to_b(self, db_session: Session) -> None:
        """Plan A referrer attempting to refer Plan B distributor (A->B) is FORBIDDEN."""
        prod = create_test_product(db_session)

        referrer_a = User(
            full_name="Referrer Plan A",
            phone="9811100005",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PAAAAA05",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(referrer_a)
        db_session.flush()
        add_confirmed_paid_order(db_session, referrer_a, prod)

        # Referee B (distributor)
        distributor_referee = User(
            full_name="Referee Distributor",
            phone="9811100006",
            programme=Programme.PLAN_B,
            account_status=AccountStatus.ACTIVE,
            referral_code="PBBBBB06",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(distributor_referee)
        db_session.flush()

        with pytest.raises(Exception) as exc_info:
            validate_referral_code(db_session, distributor_referee, "PAAAAA05")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid Referral"

    def test_forbidden_direction_b_to_b(self, db_session: Session) -> None:
        """Plan B distributor attempting to refer another Plan B distributor (B->B) is FORBIDDEN."""
        prod = create_test_product(db_session)

        distributor_b1 = User(
            full_name="Distributor One",
            phone="9811100007",
            programme=Programme.PLAN_B,
            account_status=AccountStatus.ACTIVE,
            referral_code="PBBBBB07",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(distributor_b1)
        db_session.flush()
        add_confirmed_paid_order(db_session, distributor_b1, prod)

        # Referee B2 (another distributor)
        distributor_b2 = User(
            full_name="Distributor Two",
            phone="9811100008",
            programme=Programme.PLAN_B,
            account_status=AccountStatus.ACTIVE,
            referral_code="PBBBBB08",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(distributor_b2)
        db_session.flush()

        with pytest.raises(Exception) as exc_info:
            validate_referral_code(db_session, distributor_b2, "PBBBBB07")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Wrong Referral ID"


# ---------------------------------------------------------------------------
# 5. Referrer Purchase & Eligibility Requirements (RG-07, RG-10A, BR-X2)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestReferrerEligibilityRequirements:
    """Verify purchase requirement for both programmes."""

    def test_unpurchased_plan_a_referrer_rejected(self, db_session: Session) -> None:
        """Plan A referrer with 0 paid purchases is rejected with 'Invalid Referral' (RG-07)."""
        referrer_unpurchased = User(
            full_name="Unpurchased Plan A",
            phone="9811110001",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PAUNP001",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        referee = User(
            full_name="Buyer",
            phone="9811110002",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PABUY001",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add_all([referrer_unpurchased, referee])
        db_session.flush()

        with pytest.raises(Exception) as exc_info:
            validate_referral_code(db_session, referee, "PAUNP001")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid Referral"

    def test_unpurchased_plan_b_distributor_rejected(self, db_session: Session) -> None:
        """Newly registered Plan B distributor without a qualifying purchase is rejected with 'Wrong Referral ID' (BR-X2, RG-10A)."""
        distributor_unpurchased = User(
            full_name="Unpurchased Distributor",
            phone="9811110003",
            programme=Programme.PLAN_B,
            account_status=AccountStatus.ACTIVE,
            referral_code="PBUNP001",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        referee = User(
            full_name="Buyer Plan A",
            phone="9811110004",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PABUY002",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add_all([distributor_unpurchased, referee])
        db_session.flush()

        with pytest.raises(Exception) as exc_info:
            validate_referral_code(db_session, referee, "PBUNP001")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Wrong Referral ID"

    def test_purchased_plan_b_distributor_activates(self, db_session: Session) -> None:
        """Plan B distributor's referral code becomes eligible immediately after qualifying purchase."""
        prod = create_test_product(db_session)

        distributor = User(
            full_name="Eligible Distributor",
            phone="9811110005",
            programme=Programme.PLAN_B,
            account_status=AccountStatus.ACTIVE,
            referral_code="PBELIG01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        referee = User(
            full_name="Buyer Plan A",
            phone="9811110006",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PABUY003",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add_all([distributor, referee])
        db_session.flush()

        # Step 1: Before purchase, code is inactive
        with pytest.raises(Exception) as exc:
            validate_referral_code(db_session, referee, "PBELIG01")
        assert exc.value.detail == "Wrong Referral ID"

        # Step 2: Complete purchase
        add_confirmed_paid_order(db_session, distributor, prod)

        # Step 3: Now code is valid
        validated = validate_referral_code(db_session, referee, "PBELIG01")
        assert validated.id == distributor.id


# ---------------------------------------------------------------------------
# 6. Account Status Behaviors (RG-14)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAccountStatusBehaviors:
    """Verify BLOCKED and DEACTIVATED account behaviors."""

    def test_blocked_distributor_can_login_via_password(self, api_client: TestClient, db_session: Session) -> None:
        """Blocked distributor CAN log in via password and receive access token (RG-14)."""
        distributor = User(
            full_name="Blocked Distributor",
            phone="9830000001",
            password_hash=hash_password("Password123!"),
            programme=Programme.PLAN_B,
            account_status=AccountStatus.BLOCKED,
            referral_code="PBBLOK01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(distributor)
        db_session.commit()

        login_payload = {
            "phone": "9830000001",
            "password": "Password123!",
        }
        res = api_client.post("/api/v1/auth/distributor/login", json=login_payload)
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert data["account_status"] == "BLOCKED"
        assert data["programme"] == "PLAN_B"

    def test_blocked_distributor_can_view_profile(self, api_client: TestClient, db_session: Session) -> None:
        """Blocked distributor can view their profile via /api/v1/auth/me."""
        distributor = User(
            full_name="Blocked Profile Viewer",
            phone="9830000002",
            password_hash=hash_password("Password123!"),
            programme=Programme.PLAN_B,
            account_status=AccountStatus.BLOCKED,
            referral_code="PBBLOK02",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(distributor)
        db_session.commit()

        token = create_access_token(distributor.id, distributor.role.value, distributor.phone)
        res = api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = res.json()
        assert data["account_status"] == "BLOCKED"
        assert data["programme"] == "PLAN_B"

    def test_blocked_distributor_code_rejected_for_referrals(self, db_session: Session) -> None:
        """Blocked distributor's referral code CANNOT be used by customers (RG-14)."""
        prod = create_test_product(db_session)

        distributor = User(
            full_name="Blocked Seller",
            phone="9830000003",
            programme=Programme.PLAN_B,
            account_status=AccountStatus.BLOCKED,
            referral_code="PBBLOK03",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        referee = User(
            full_name="Buyer",
            phone="9830000004",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PABUY004",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add_all([distributor, referee])
        db_session.flush()
        add_confirmed_paid_order(db_session, distributor, prod)

        with pytest.raises(Exception) as exc:
            validate_referral_code(db_session, referee, "PBBLOK03")
        assert exc.value.status_code == 400
        assert exc.value.detail == "Wrong Referral ID"

    def test_deactivated_distributor_cannot_login(self, api_client: TestClient, db_session: Session) -> None:
        """Deactivated distributor CANNOT log in (403 Forbidden)."""
        distributor = User(
            full_name="Deactivated Distributor",
            phone="9830000005",
            password_hash=hash_password("Password123!"),
            programme=Programme.PLAN_B,
            account_status=AccountStatus.DEACTIVATED,
            referral_code="PBDEAC01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(distributor)
        db_session.commit()

        login_payload = {
            "phone": "9830000005",
            "password": "Password123!",
        }
        res = api_client.post("/api/v1/auth/distributor/login", json=login_payload)
        assert res.status_code == 403
        assert "Distributor account is deactivated." in res.json()["detail"]


# ---------------------------------------------------------------------------
# 7. Programme-Aware Login Separation (RG-12)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestProgrammeLoginSeparation:
    """Plan A credentials cannot log into Plan B portal and vice-versa."""

    def test_plan_a_cannot_login_to_distributor_portal(self, api_client: TestClient, db_session: Session) -> None:
        """Plan A credentials return 401 when attempting to log into distributor portal."""
        customer = User(
            full_name="Plan A User",
            phone="9840000001",
            password_hash=hash_password("Password123!"),
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PASEPA01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(customer)
        db_session.commit()

        res = api_client.post(
            "/api/v1/auth/distributor/login",
            json={"phone": "9840000001", "password": "Password123!"},
        )
        assert res.status_code == 401
        assert "Invalid credentials for Plan B distributor portal" in res.json()["detail"]

    def test_plan_b_cannot_login_to_customer_portal(self, api_client: TestClient, db_session: Session) -> None:
        """Plan B credentials return 401 when attempting to log into customer portal."""
        distributor = User(
            full_name="Plan B User",
            phone="9840000002",
            password_hash=hash_password("Password123!"),
            programme=Programme.PLAN_B,
            account_status=AccountStatus.ACTIVE,
            referral_code="PBSEPB01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(distributor)
        db_session.commit()

        res = api_client.post(
            "/api/v1/auth/customer/login",
            json={"phone": "9840000002", "password": "Password123!"},
        )
        assert res.status_code == 401
        assert "Invalid credentials for Plan A customer portal" in res.json()["detail"]


# ---------------------------------------------------------------------------
# 8. Permanent Referral Binding at Checkout (RG-06, RG-09, RG-11)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPermanentReferralBindingCheckout:
    """Referral relationships are saved only after successful checkout and become permanent."""

    def test_referral_binding_on_successful_checkout(self, api_client: TestClient, db_session: Session) -> None:
        """Customer placing order with valid referral code binds permanently to referrer."""
        prod = create_test_product(db_session)
        qc = QueueControl(id=1, last_allocated_position=0)
        db_session.add(qc)

        # Referrer A with 1 purchase
        referrer = User(
            full_name="Referrer A",
            phone="9850000001",
            password_hash=hash_password("Password123!"),
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PAREFA01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        # Customer A (unbound)
        customer = User(
            full_name="Customer A",
            phone="9850000002",
            password_hash=hash_password("Password123!"),
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PACUST01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add_all([referrer, customer])
        db_session.flush()
        add_confirmed_paid_order(db_session, referrer, prod)

        # Create address and cart item for customer
        addr = create_test_address(db_session, customer)
        cart = CartItem(user_id=customer.id, product_id=prod.id, quantity=1)
        db_session.add(cart)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        # Checkout with referrer code
        checkout_payload = {
            "address_id": addr.id,
            "idempotency_key": "idemp-bind-001",
            "referral_code": "PAREFA01",
        }
        res = api_client.post(
            "/api/v1/orders/checkout",
            json=checkout_payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 201

        # Simulate successful payment confirmation (WP-5)
        attempt = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == res.json()["id"]).first()
        assert attempt is not None
        pay_res = api_client.post(
            "/api/v1/payments/simulated/simulate",
            json={"attempt_reference": attempt.attempt_reference, "action": "success"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert pay_res.status_code == 200

        # Verify database binding in referral_relationships table
        rel = db_session.query(ReferralRelationship).filter(ReferralRelationship.referee_id == customer.id).first()
        assert rel is not None
        assert rel.referrer_id == referrer.id
        assert rel.referee_programme == Programme.PLAN_A
        assert rel.referrer_programme == Programme.PLAN_A
        assert rel.referral_code_used == "PAREFA01"
        assert rel.binding_channel == "checkout"

        # Verify users.referred_by_id
        db_session.refresh(customer)
        assert customer.referred_by_id == referrer.id

        # Verify audit log entry
        audit = db_session.query(AuditLog).filter(
            AuditLog.entity_type == "referral_relationship",
            AuditLog.entity_id == str(rel.id),
        ).first()
        assert audit is not None
        assert audit.action == "REFERRAL_RELATIONSHIP_CREATED"
        assert audit.actor_id == customer.id

    def test_cannot_change_established_referrer_on_subsequent_order(self, api_client: TestClient, db_session: Session) -> None:
        """Attempting to use a different referral code after already being bound is rejected."""
        prod = create_test_product(db_session)
        qc = QueueControl(id=1, last_allocated_position=0)
        db_session.add(qc)

        referrer1 = User(
            full_name="Original Referrer",
            phone="9850000003",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PAORIG01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        referrer2 = User(
            full_name="Attempted New Referrer",
            phone="9850000004",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PANEWW01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        customer = User(
            full_name="Bound Customer",
            phone="9850000005",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PABOUND1",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add_all([referrer1, referrer2, customer])
        db_session.flush()

        add_confirmed_paid_order(db_session, referrer1, prod)
        add_confirmed_paid_order(db_session, referrer2, prod)

        # Establish existing relationship with referrer1
        existing_rel = ReferralRelationship(
            referee_id=customer.id,
            referrer_id=referrer1.id,
            referee_programme=Programme.PLAN_A,
            referrer_programme=Programme.PLAN_A,
            referral_code_used="PAORIG01",
            binding_channel="checkout",
            is_active=True,
        )
        customer.referred_by_id = referrer1.id
        db_session.add(existing_rel)

        addr = create_test_address(db_session, customer)
        cart = CartItem(user_id=customer.id, product_id=prod.id, quantity=1)
        db_session.add(cart)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        # Attempt checkout with referrer2's code
        checkout_payload = {
            "address_id": addr.id,
            "idempotency_key": "idemp-switch-001",
            "referral_code": "PANEWW01",
        }
        res = api_client.post(
            "/api/v1/orders/checkout",
            json=checkout_payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 400
        assert res.json()["detail"] == "Invalid Referral"


# ---------------------------------------------------------------------------
# 9. Later-Order Referral Binding (BR-X1 Option B)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLaterOrderReferralBinding:
    """A customer who places their first order without a code may enter a code on a later order."""

    def test_later_order_binding_preserves_earlier_order(self, api_client: TestClient, db_session: Session) -> None:
        """First order without code: unreferred. Second order with distributor code: permanently bound. First order untouched."""
        prod = create_test_product(db_session)
        qc = QueueControl(id=1, last_allocated_position=0)
        db_session.add(qc)

        distributor = User(
            full_name="Later Referrer Distributor",
            phone="9860000001",
            programme=Programme.PLAN_B,
            account_status=AccountStatus.ACTIVE,
            referral_code="PBLATE01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        customer = User(
            full_name="Later Binding Customer",
            phone="9860000002",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PACUST02",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add_all([distributor, customer])
        db_session.flush()

        # Distributor qualifying purchase
        add_confirmed_paid_order(db_session, distributor, prod)

        addr = create_test_address(db_session, customer)
        token = create_access_token(customer.id, customer.role.value, customer.phone)

        # Order 1: Checkout WITHOUT referral code
        cart1 = CartItem(user_id=customer.id, product_id=prod.id, quantity=1)
        db_session.add(cart1)
        db_session.commit()

        res1 = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr.id, "idempotency_key": "idemp-order-1", "referral_code": None},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res1.status_code == 201
        order1_id = res1.json()["id"]

        # Simulate successful payment confirmation for order 1
        attempt1 = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == order1_id).first()
        assert attempt1 is not None
        pay_res1 = api_client.post(
            "/api/v1/payments/simulated/simulate",
            json={"attempt_reference": attempt1.attempt_reference, "action": "success"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert pay_res1.status_code == 200

        # Confirm customer is NOT bound after order 1
        db_session.refresh(customer)
        assert customer.referred_by_id is None
        rel_count_1 = db_session.query(ReferralRelationship).filter(ReferralRelationship.referee_id == customer.id).count()
        assert rel_count_1 == 0

        # Order 2: Checkout WITH distributor's referral code
        cart2 = CartItem(user_id=customer.id, product_id=prod.id, quantity=1)
        db_session.add(cart2)
        db_session.commit()

        res2 = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr.id, "idempotency_key": "idemp-order-2", "referral_code": "PBLATE01"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res2.status_code == 201
        order2_id = res2.json()["id"]

        # Simulate successful payment confirmation for order 2
        attempt2 = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == order2_id).first()
        assert attempt2 is not None
        pay_res2 = api_client.post(
            "/api/v1/payments/simulated/simulate",
            json={"attempt_reference": attempt2.attempt_reference, "action": "success"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert pay_res2.status_code == 200

        # Confirm customer IS bound after order 2 (BR-X1 Option B)
        db_session.refresh(customer)
        assert customer.referred_by_id == distributor.id

        rel = db_session.query(ReferralRelationship).filter(ReferralRelationship.referee_id == customer.id).first()
        assert rel is not None
        assert rel.referrer_id == distributor.id
        assert rel.referee_programme == Programme.PLAN_A
        assert rel.referrer_programme == Programme.PLAN_B
        assert rel.referral_code_used == "PBLATE01"

        # Verify Order 1 was NOT retroactively updated
        order1 = db_session.query(Order).filter(Order.id == order1_id).first()
        assert order1.applied_referral_code is None


# ---------------------------------------------------------------------------
# 10. Exact Error Messages Assertions
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExactReferralErrorMessages:
    """Verify exact message:
      Plan A -> 'Invalid Referral'
      Plan B -> 'Wrong Referral ID'
    """

    def test_exact_message_for_nonexistent_plan_a_code(self, api_client: TestClient, db_session: Session) -> None:
        """Non-existent code in Plan A validation returns exactly 'Invalid Referral'."""
        customer = User(
            full_name="Tester A",
            phone="9870000001",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PATEST01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(customer)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)
        res = api_client.post(
            "/api/v1/referrals/validate",
            json={"referral_code": "PANONEXIST", "programme": "PLAN_A"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 400
        assert res.json()["detail"] == "Invalid Referral"

    def test_exact_message_for_nonexistent_plan_b_code(self, api_client: TestClient, db_session: Session) -> None:
        """Non-existent code in Plan B validation returns exactly 'Wrong Referral ID'."""
        customer = User(
            full_name="Tester A",
            phone="9870000002",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PATEST02",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add(customer)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)
        res = api_client.post(
            "/api/v1/referrals/validate",
            json={"referral_code": "PBNONEXIST", "programme": "PLAN_B"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 400
        assert res.json()["detail"] == "Wrong Referral ID"

    def test_distributor_preview_returns_name_only_no_pii(self, api_client: TestClient, db_session: Session) -> None:
        """Validation of valid Plan B code returns distributor name preview without sensitive PII (RG-10)."""
        prod = create_test_product(db_session)

        distributor = User(
            full_name="Ramesh Bhai Distributor",
            phone="9870000003",
            programme=Programme.PLAN_B,
            account_status=AccountStatus.ACTIVE,
            referral_code="PBPVIE01",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        customer = User(
            full_name="Customer Checking Preview",
            phone="9870000004",
            programme=Programme.PLAN_A,
            account_status=AccountStatus.ACTIVE,
            referral_code="PACUST04",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        db_session.add_all([distributor, customer])
        db_session.flush()
        add_confirmed_paid_order(db_session, distributor, prod)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)
        res = api_client.post(
            "/api/v1/referrals/validate",
            json={"referral_code": "PBPVIE01", "programme": "PLAN_B"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_valid"] is True
        assert data["referral_code"] == "PBPVIE01"
        assert data["referrer_name"] == "Ramesh Bhai Distributor"
        # Must not contain PII
        assert "phone" not in data
        assert "email" not in data
        assert "id" not in data
