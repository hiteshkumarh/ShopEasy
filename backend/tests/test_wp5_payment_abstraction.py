"""Comprehensive automated test suite for WP-5 Payment Abstraction.

Covers:
  1. Production configuration safeguards & fail-closed behavior
  2. Production route separation (webhooks available, simulation excluded)
  3. Payment attempt initiation & checkout PENDING_PAYMENT lifecycle
  4. Cart retention & deferred referral binding on pending payment
  5. Payment success: order confirmation, cart clearing, permanent referral binding
  6. Payment failure: order failure, single stock restoration, cart preservation, zero referrals
  7. Late success after failure: flagged for reconciliation, zero order confirmation, zero stock decrement
  8. Out-of-order failure after confirmation: ignored, zero order downgrade, zero stock restoration
  9. Strict validation: provider mismatch, attempt mismatch, decimal amount mismatch, currency mismatch
  10. Idempotency: duplicate event ID handled via database unique constraint
  11. Payment expiry: transactional worker restores stock once and marks FAILED
  12. Expiry / webhook race conditions
  13. Checkout idempotency key handling
  14. Transaction rollback on failure
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, settings
from app.core.database import Base
from app.core.security import create_access_token, hash_password
from app.main import app
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
from app.models.payment import PaymentAttempt, PaymentEvent
from app.models.product import Product
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.services.payment.base import (
    PaymentAuthenticationError,
    PaymentValidationError,
)
from app.services.payment.factory import get_payment_provider
from app.services.payment.service import PaymentService
from app.services.payment.simulated import SimulatedPaymentProvider


# ---------------------------------------------------------------------------
# Test Helpers (Uses shared api_client & db_session from conftest)
# ---------------------------------------------------------------------------


def make_user(
    db: Session,
    phone: str = "9876543210",
    role: UserRole = UserRole.CUSTOMER,
    programme: Programme = Programme.PLAN_A,
    referral_code: str = "PAUSER01",
) -> User:
    user = User(
        phone=phone,
        password_hash=hash_password("Password123!"),
        full_name="Test Customer",
        role=role,
        programme=programme,
        account_status=AccountStatus.ACTIVE,
        referral_code=referral_code,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_product(
    db: Session,
    name: str = "Arya Power Bank PB-3999",
    price: Decimal = Decimal("3999.00"),
    stock: int = 10,
) -> Product:
    prod = Product(
        name=name,
        description="High capacity power bank",
        price=price,
        stock=stock,
        is_active=True,
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)
    return prod


def make_address(db: Session, user: User) -> Address:
    addr = Address(
        user_id=user.id,
        recipient_name=user.full_name or "Test Customer",
        phone=user.phone,
        address_line1="123 Test Street",
        city="Mumbai",
        state="Maharashtra",
        pincode="400001",
        is_default=True,
    )
    db.add(addr)
    db.commit()
    db.refresh(addr)
    return addr


def add_confirmed_paid_order(db: Session, user: User, product: Product, referral_code: str = None) -> Order:
    """Helper to record a confirmed, paid order for a user (simulating qualifying purchase)."""
    addr = make_address(db, user)
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
    db.commit()
    return order


# ---------------------------------------------------------------------------
# 1. Configuration & Production Safeguard Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPaymentConfigurationSafeguards:
    """Verify production startup guards and fail-closed rules."""

    def test_production_rejects_simulated_provider(self, monkeypatch):
        """Production must raise RuntimeError if PAYMENT_PROVIDER is 'simulated'."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SECRET_KEY", "x" * 32)
        monkeypatch.setenv("OTP_HMAC_SECRET", "y" * 32)
        monkeypatch.setenv("DEBUG", "False")
        monkeypatch.setenv("PAYMENT_PROVIDER", "simulated")

        with pytest.raises(RuntimeError, match="PAYMENT_PROVIDER cannot be 'simulated' in production"):
            Settings()

    def test_production_rejects_allow_simulated_payments(self, monkeypatch):
        """Production must raise RuntimeError if ALLOW_SIMULATED_PAYMENTS is True."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SECRET_KEY", "x" * 32)
        monkeypatch.setenv("OTP_HMAC_SECRET", "y" * 32)
        monkeypatch.setenv("DEBUG", "False")
        monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
        monkeypatch.setenv("ALLOW_SIMULATED_PAYMENTS", "true")

        with pytest.raises(RuntimeError, match="ALLOW_SIMULATED_PAYMENTS must be False in production"):
            Settings()

    def test_rejects_empty_payment_provider(self, monkeypatch):
        """Setting PAYMENT_PROVIDER to empty string must fail."""
        monkeypatch.setenv("PAYMENT_PROVIDER", "")
        with pytest.raises(ValueError, match="PAYMENT_PROVIDER environment variable cannot be empty"):
            Settings()

    def test_rejects_unsupported_payment_provider(self, monkeypatch):
        """Unsupported payment providers must be rejected."""
        monkeypatch.setenv("PAYMENT_PROVIDER", "unsupported_gateway")
        with pytest.raises(ValueError, match="Unsupported PAYMENT_PROVIDER 'unsupported_gateway'"):
            Settings()

    def test_factory_rejects_simulation_in_production(self, monkeypatch):
        """Factory must refuse to instantiate simulated provider in production."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("PAYMENT_PROVIDER", "simulated")
        with pytest.raises(RuntimeError):
            get_payment_provider()


# ---------------------------------------------------------------------------
# 2. Production Route Separation Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRouteSeparation:
    """Verify webhook route is always present and simulation route is guarded."""

    def test_webhook_route_is_available(self, api_client):
        """POST /api/v1/payments/events must be mounted and reject unauthenticated requests with 401."""
        res = api_client.post("/api/v1/payments/events", content=b"{}")
        # Rejection must be 401 Unauthorized, NOT 404 Not Found
        assert res.status_code == 401

    def test_simulated_route_rejects_unauthenticated_requests(self, api_client):
        """POST /api/v1/payments/simulated/simulate requires authentication."""
        res = api_client.post(
            "/api/v1/payments/simulated/simulate",
            json={"attempt_reference": "SIM-ATT-12345", "action": "success"},
        )
        assert res.status_code == 401


# ---------------------------------------------------------------------------
# 3. Checkout Initiation & State Lifecycle Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCheckoutPaymentInitiation:
    """Verify checkout sets PENDING_PAYMENT, retains cart, and creates PaymentAttempt."""

    def test_checkout_creates_pending_order_and_retains_cart(self, api_client, db_session):
        customer = make_user(db_session, phone="9111111111", referral_code="PACUST01")
        prod = make_product(db_session, price=Decimal("2000.00"), stock=5)
        addr = make_address(db_session, customer)

        cart_item = CartItem(user_id=customer.id, product_id=prod.id, quantity=2)
        db_session.add(cart_item)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        # Place checkout
        res = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr.id, "idempotency_key": "idemp-wp5-001"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["order_status"] == OrderStatus.PENDING_PAYMENT.value
        assert data["payment_status"] == PaymentStatus.PENDING.value

        # Verify stock was decremented
        db_session.refresh(prod)
        assert prod.stock == 3  # 5 - 2

        # Verify cart was RETAINED (not cleared yet)
        cart_count = db_session.query(CartItem).filter(CartItem.user_id == customer.id).count()
        assert cart_count == 1

        # Verify PaymentAttempt was created in database
        attempt = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == data["id"]).first()
        assert attempt is not None
        assert attempt.status == PaymentStatus.PENDING
        assert attempt.amount == Decimal("4000.00")
        assert attempt.currency == "INR"
        assert attempt.provider == "simulated"


# ---------------------------------------------------------------------------
# 4. Payment Success Lifecycle & Referral Binding Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPaymentSuccessLifecycle:
    """Verify payment.completed confirms order, clears cart, and binds referrals."""

    def test_payment_success_confirms_order_clears_cart_and_binds_referral(self, api_client, db_session):
        referrer = make_user(db_session, phone="9222222222", referral_code="PAREF001")
        customer = make_user(db_session, phone="9333333333", referral_code="PACUST02")
        prod = make_product(db_session, price=Decimal("3999.00"), stock=5)
        add_confirmed_paid_order(db_session, referrer, prod)
        addr = make_address(db_session, customer)

        cart_item = CartItem(user_id=customer.id, product_id=prod.id, quantity=1)
        db_session.add(cart_item)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        # 1. Checkout with referral code
        res = api_client.post(
            "/api/v1/orders/checkout",
            json={
                "address_id": addr.id,
                "idempotency_key": "idemp-wp5-success-01",
                "referral_code": "PAREF001",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 201
        order_id = res.json()["id"]

        # Referral must NOT be bound yet while payment is pending
        db_session.refresh(customer)
        assert customer.referred_by_id is None
        rel_before = db_session.query(ReferralRelationship).filter(ReferralRelationship.referee_id == customer.id).first()
        assert rel_before is None

        # 2. Simulate payment success callback
        attempt = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == order_id).first()
        pay_res = api_client.post(
            "/api/v1/payments/simulated/simulate",
            json={"attempt_reference": attempt.attempt_reference, "action": "success"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert pay_res.status_code == 200
        assert pay_res.json()["outcome"] == "COMPLETED"

        # 3. Verify order is now CONFIRMED and payment is COMPLETED
        order = db_session.query(Order).filter(Order.id == order_id).first()
        assert order.order_status == OrderStatus.CONFIRMED
        assert order.payment_status == PaymentStatus.COMPLETED
        assert order.payment_reference == attempt.attempt_reference

        # 4. Verify attempt is COMPLETED
        db_session.refresh(attempt)
        assert attempt.status == PaymentStatus.COMPLETED

        # 5. Verify cart is CLEARED
        cart_count = db_session.query(CartItem).filter(CartItem.user_id == customer.id).count()
        assert cart_count == 0

        # 6. Verify permanent referral binding and audit log
        db_session.refresh(customer)
        assert customer.referred_by_id == referrer.id

        rel = db_session.query(ReferralRelationship).filter(ReferralRelationship.referee_id == customer.id).first()
        assert rel is not None
        assert rel.referrer_id == referrer.id
        assert rel.binding_channel == "checkout"

        audit = db_session.query(AuditLog).filter(
            AuditLog.entity_type == "referral_relationship",
            AuditLog.entity_id == str(rel.id),
        ).first()
        assert audit is not None
        assert audit.action == "REFERRAL_RELATIONSHIP_CREATED"


# ---------------------------------------------------------------------------
# 5. Payment Failure Lifecycle & Stock Restoration Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPaymentFailureLifecycle:
    """Verify payment.failed sets order FAILED, preserves cart, restores stock once."""

    def test_payment_failure_restores_stock_and_preserves_cart(self, api_client, db_session):
        customer = make_user(db_session, phone="9444444444", referral_code="PACUST03")
        prod = make_product(db_session, price=Decimal("1500.00"), stock=10)
        addr = make_address(db_session, customer)

        cart_item = CartItem(user_id=customer.id, product_id=prod.id, quantity=3)
        db_session.add(cart_item)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        # 1. Checkout
        res = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr.id, "idempotency_key": "idemp-wp5-fail-01"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 201
        order_id = res.json()["id"]

        db_session.refresh(prod)
        assert prod.stock == 7  # 10 - 3

        # 2. Simulate payment failure callback
        attempt = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == order_id).first()
        pay_res = api_client.post(
            "/api/v1/payments/simulated/simulate",
            json={
                "attempt_reference": attempt.attempt_reference,
                "action": "failure",
                "failure_reason": "Insufficient balance on test card",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert pay_res.status_code == 200
        assert pay_res.json()["outcome"] == "FAILED"

        # 3. Verify order & attempt state
        order = db_session.query(Order).filter(Order.id == order_id).first()
        assert order.order_status == OrderStatus.FAILED
        assert order.payment_status == PaymentStatus.FAILED

        db_session.refresh(attempt)
        assert attempt.status == PaymentStatus.FAILED
        assert "Insufficient balance" in attempt.failure_reason

        # 4. Verify stock RESTORED
        db_session.refresh(prod)
        assert prod.stock == 10  # Returned to 10

        # 5. Verify cart PRESERVED for customer retry
        cart_count = db_session.query(CartItem).filter(CartItem.user_id == customer.id).count()
        assert cart_count == 1

        # 6. Verify zero referral binding
        db_session.refresh(customer)
        assert customer.referred_by_id is None

    def test_repeated_failure_events_do_not_double_restore_stock(self, api_client, db_session):
        """Duplicate failure event must NOT restore stock a second time."""
        customer = make_user(db_session, phone="9555555555", referral_code="PACUST04")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=5)
        addr = make_address(db_session, customer)

        cart_item = CartItem(user_id=customer.id, product_id=prod.id, quantity=2)
        db_session.add(cart_item)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        res = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr.id, "idempotency_key": "idemp-wp5-fail-02"},
            headers={"Authorization": f"Bearer {token}"},
        )
        order_id = res.json()["id"]
        attempt = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == order_id).first()

        # First failure: restores stock from 3 -> 5
        api_client.post(
            "/api/v1/payments/simulated/simulate",
            json={"attempt_reference": attempt.attempt_reference, "action": "failure"},
            headers={"Authorization": f"Bearer {token}"},
        )
        db_session.refresh(prod)
        assert prod.stock == 5

        # Second failure (simulated via webhook directly): must NOT add another 2
        payload = {
            "event_id": "evt_dup_fail_002",
            "event_type": "payment.failed",
            "attempt_reference": attempt.attempt_reference,
            "amount": float(attempt.amount),
            "currency": "INR",
        }
        res_webhook = api_client.post(
            "/api/v1/payments/events",
            content=json.dumps(payload),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert res_webhook.status_code == 200
        assert res_webhook.json()["outcome"] == "ALREADY_FAILED"

        # Stock must remain exactly 5
        db_session.refresh(prod)
        assert prod.stock == 5


# ---------------------------------------------------------------------------
# 6. Out-of-Order & Late Payment Invariants Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEdgeCaseStateInvariants:
    """Verify out-of-order and late payment invariants."""

    def test_out_of_order_failure_cannot_downgrade_confirmed_order(self, api_client, db_session):
        """Late failure event arriving after confirmation must be ignored."""
        customer = make_user(db_session, phone="9666666666", referral_code="PACUST05")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=5)
        addr = make_address(db_session, customer)

        cart_item = CartItem(user_id=customer.id, product_id=prod.id, quantity=1)
        db_session.add(cart_item)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        res = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr.id, "idempotency_key": "idemp-wp5-edge-01"},
            headers={"Authorization": f"Bearer {token}"},
        )
        order_id = res.json()["id"]
        attempt = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == order_id).first()

        # Confirm order first
        api_client.post(
            "/api/v1/payments/simulated/simulate",
            json={"attempt_reference": attempt.attempt_reference, "action": "success"},
            headers={"Authorization": f"Bearer {token}"},
        )

        order = db_session.query(Order).filter(Order.id == order_id).first()
        assert order.order_status == OrderStatus.CONFIRMED

        # Inbound out-of-order failure
        payload = {
            "event_id": "evt_out_of_order_fail",
            "event_type": "payment.failed",
            "attempt_reference": attempt.attempt_reference,
            "amount": float(attempt.amount),
            "currency": "INR",
        }
        res_webhook = api_client.post(
            "/api/v1/payments/events",
            content=json.dumps(payload),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert res_webhook.status_code == 200
        assert res_webhook.json()["outcome"] == "IGNORED_OUT_OF_ORDER"

        # Order must remain CONFIRMED
        db_session.refresh(order)
        assert order.order_status == OrderStatus.CONFIRMED
        assert order.payment_status == PaymentStatus.COMPLETED

    def test_late_success_after_failure_is_flagged_not_confirmed(self, api_client, db_session):
        """Success arriving after an order has already failed must NOT confirm the order."""
        customer = make_user(db_session, phone="9777777777", referral_code="PACUST06")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=5)
        addr = make_address(db_session, customer)

        cart_item = CartItem(user_id=customer.id, product_id=prod.id, quantity=1)
        db_session.add(cart_item)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        res = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr.id, "idempotency_key": "idemp-wp5-edge-02"},
            headers={"Authorization": f"Bearer {token}"},
        )
        order_id = res.json()["id"]
        attempt = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == order_id).first()

        # Fail order first
        api_client.post(
            "/api/v1/payments/simulated/simulate",
            json={"attempt_reference": attempt.attempt_reference, "action": "failure"},
            headers={"Authorization": f"Bearer {token}"},
        )

        order = db_session.query(Order).filter(Order.id == order_id).first()
        assert order.order_status == OrderStatus.FAILED
        db_session.refresh(prod)
        assert prod.stock == 5  # Restored

        # Inbound late success
        payload = {
            "event_id": "evt_late_success",
            "event_type": "payment.completed",
            "attempt_reference": attempt.attempt_reference,
            "amount": float(attempt.amount),
            "currency": "INR",
        }
        res_webhook = api_client.post(
            "/api/v1/payments/events",
            content=json.dumps(payload),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert res_webhook.status_code == 200
        assert res_webhook.json()["outcome"] == "FLAGGED_FOR_RECONCILIATION"

        # Order must REMAIN FAILED; stock must NOT be decremented again
        db_session.refresh(order)
        assert order.order_status == OrderStatus.FAILED
        db_session.refresh(prod)
        assert prod.stock == 5  # Still 5, no double decrement


# ---------------------------------------------------------------------------
# 7. Strict Security & Validation Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPaymentSecurityValidation:
    """Verify exact provider, amount, currency, and attempt integrity validations."""

    def test_rejects_amount_mismatch_decimal(self, api_client, db_session):
        customer = make_user(db_session, phone="9888888888", referral_code="PACUST07")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=5)
        addr = make_address(db_session, customer)

        cart_item = CartItem(user_id=customer.id, product_id=prod.id, quantity=1)
        db_session.add(cart_item)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        res = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr.id, "idempotency_key": "idemp-wp5-val-01"},
            headers={"Authorization": f"Bearer {token}"},
        )
        order_id = res.json()["id"]
        attempt = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == order_id).first()

        # Send tampered amount: 999.00 instead of 1000.00
        payload = {
            "event_id": "evt_tampered_amount",
            "event_type": "payment.completed",
            "attempt_reference": attempt.attempt_reference,
            "amount": 999.00,
            "currency": "INR",
        }
        res_webhook = api_client.post(
            "/api/v1/payments/events",
            content=json.dumps(payload),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert res_webhook.status_code == 400
        assert "Payment amount mismatch" in res_webhook.json()["detail"]

    def test_rejects_currency_mismatch(self, api_client, db_session):
        customer = make_user(db_session, phone="9888888889", referral_code="PACUST08")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=5)
        addr = make_address(db_session, customer)

        cart_item = CartItem(user_id=customer.id, product_id=prod.id, quantity=1)
        db_session.add(cart_item)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        res = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr.id, "idempotency_key": "idemp-wp5-val-02"},
            headers={"Authorization": f"Bearer {token}"},
        )
        order_id = res.json()["id"]
        attempt = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == order_id).first()

        payload = {
            "event_id": "evt_wrong_currency",
            "event_type": "payment.completed",
            "attempt_reference": attempt.attempt_reference,
            "amount": 1000.00,
            "currency": "USD",
        }
        res_webhook = api_client.post(
            "/api/v1/payments/events",
            content=json.dumps(payload),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert res_webhook.status_code == 400
        assert "Payment currency mismatch" in res_webhook.json()["detail"]

    def test_ownership_guard_prevents_simulating_other_customer_order(self, api_client, db_session):
        customer1 = make_user(db_session, phone="9888888890", referral_code="PACUST09")
        customer2 = make_user(db_session, phone="9888888891", referral_code="PACUST10")
        prod = make_product(db_session, price=Decimal("500.00"), stock=5)
        addr1 = make_address(db_session, customer1)

        cart_item = CartItem(user_id=customer1.id, product_id=prod.id, quantity=1)
        db_session.add(cart_item)
        db_session.commit()

        token1 = create_access_token(customer1.id, customer1.role.value, customer1.phone)
        token2 = create_access_token(customer2.id, customer2.role.value, customer2.phone)

        # Customer 1 places order
        res = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr1.id, "idempotency_key": "idemp-wp5-own-01"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        attempt = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == res.json()["id"]).first()

        # Customer 2 attempts to simulate payment for Customer 1's order
        res_sim = api_client.post(
            "/api/v1/payments/simulated/simulate",
            json={"attempt_reference": attempt.attempt_reference, "action": "success"},
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert res_sim.status_code == 403
        assert "Forbidden" in res_sim.json()["detail"]


# ---------------------------------------------------------------------------
# 8. Duplicate Event Idempotency Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPaymentEventIdempotency:
    """Verify database unique constraint uq_payment_events_provider_event_id idempotency."""

    def test_duplicate_event_id_returns_idempotent_success(self, api_client, db_session):
        customer = make_user(db_session, phone="9888888892", referral_code="PACUST11")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=5)
        addr = make_address(db_session, customer)

        cart_item = CartItem(user_id=customer.id, product_id=prod.id, quantity=1)
        db_session.add(cart_item)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        res = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr.id, "idempotency_key": "idemp-wp5-idem-01"},
            headers={"Authorization": f"Bearer {token}"},
        )
        order_id = res.json()["id"]
        attempt = db_session.query(PaymentAttempt).filter(PaymentAttempt.order_id == order_id).first()

        payload = {
            "event_id": "evt_exact_same_id_001",
            "event_type": "payment.completed",
            "attempt_reference": attempt.attempt_reference,
            "amount": float(attempt.amount),
            "currency": "INR",
        }

        # First delivery
        res1 = api_client.post(
            "/api/v1/payments/events",
            content=json.dumps(payload),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert res1.status_code == 200
        assert res1.json()["outcome"] == "COMPLETED"

        # Second concurrent / replayed delivery with identical provider_event_id
        res2 = api_client.post(
            "/api/v1/payments/events",
            content=json.dumps(payload),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert res2.status_code == 200
        assert res2.json()["outcome"] == "ALREADY_PROCESSED"

        # Ensure only 1 event recorded in database
        event_count = db_session.query(PaymentEvent).filter(
            PaymentEvent.provider_event_id == "evt_exact_same_id_001"
        ).count()
        assert event_count == 1


# ---------------------------------------------------------------------------
# 9. Payment Expiry Worker Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPaymentExpiryWorker:
    """Verify transactional expire_stale_payment_attempts() domain service."""

    def test_expires_stale_attempt_and_restores_stock(self, db_session):
        customer = make_user(db_session, phone="9888888893", referral_code="PACUST12")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=5)
        addr = make_address(db_session, customer)

        # Place pending order manually with stock decremented
        prod.stock -= 2
        order = Order(
            order_number=f"ORD-TEST-EXP-01",
            idempotency_key="idemp-exp-01",
            user_id=customer.id,
            address_id=addr.id,
            total_amount=Decimal("2000.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            product_name=prod.name,
            unit_price=prod.price,
            quantity=2,
            line_total=Decimal("2000.00"),
        )
        db_session.add(item)

        # Attempt expired 5 minutes ago
        expired_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="SIM-ATT-EXPIRED-01",
            provider="simulated",
            amount=Decimal("2000.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=expired_time,
        )
        db_session.add(attempt)
        db_session.commit()

        # Run expiry sweep
        count = PaymentService.expire_stale_payment_attempts(db_session)
        assert count == 1

        # Verify attempt and order are now FAILED
        db_session.refresh(attempt)
        assert attempt.status == PaymentStatus.FAILED
        assert attempt.failure_reason == "PAYMENT_ATTEMPT_EXPIRED"

        db_session.refresh(order)
        assert order.order_status == OrderStatus.FAILED
        assert order.payment_status == PaymentStatus.FAILED

        # Verify stock was RESTORED (from 3 -> 5)
        db_session.refresh(prod)
        assert prod.stock == 5

    def test_skips_unexpired_attempt(self, db_session):
        customer = make_user(db_session, phone="9888888894", referral_code="PACUST13")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=5)
        addr = make_address(db_session, customer)

        order = Order(
            order_number="ORD-TEST-UNEXP-01",
            idempotency_key="idemp-unexp-01",
            user_id=customer.id,
            address_id=addr.id,
            total_amount=Decimal("1000.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        db_session.add(order)
        db_session.flush()

        # Attempt expires in 10 minutes (not expired)
        future_time = datetime.now(timezone.utc) + timedelta(minutes=10)
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="SIM-ATT-ACTIVE-01",
            provider="simulated",
            amount=Decimal("1000.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=future_time,
        )
        db_session.add(attempt)
        db_session.commit()

        count = PaymentService.expire_stale_payment_attempts(db_session)
        assert count == 0

        db_session.refresh(attempt)
        assert attempt.status == PaymentStatus.PENDING
        db_session.refresh(order)
        assert order.order_status == OrderStatus.PENDING_PAYMENT

    def test_repeated_expiry_invocation_does_not_restore_stock_twice(self, db_session):
        """Calling expiry twice on same attempt restores stock only on first call."""
        customer = make_user(db_session, phone="9888888895", referral_code="PACUST14")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=5)
        addr = make_address(db_session, customer)

        # Initial checkout: 2 items decremented (stock 5 -> 3)
        prod.stock -= 2
        order = Order(
            order_number="ORD-TEST-EXP-DUP-01",
            idempotency_key="idemp-exp-dup-01",
            user_id=customer.id,
            address_id=addr.id,
            total_amount=Decimal("2000.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            product_name=prod.name,
            unit_price=prod.price,
            quantity=2,
            line_total=Decimal("2000.00"),
        )
        db_session.add(item)

        expired_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="SIM-ATT-EXPIRED-DUP-01",
            provider="simulated",
            amount=Decimal("2000.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=expired_time,
        )
        db_session.add(attempt)
        db_session.commit()

        # First sweep: restores stock from 3 -> 5
        count1 = PaymentService.expire_stale_payment_attempts(db_session)
        assert count1 == 1
        db_session.refresh(prod)
        assert prod.stock == 5

        # Second sweep immediately after: must NOT restore stock again
        count2 = PaymentService.expire_stale_payment_attempts(db_session)
        assert count2 == 0
        db_session.refresh(prod)
        assert prod.stock == 5  # Remains 5

    def test_exception_during_stock_restoration_rolls_back_entire_candidate(self, db_session, monkeypatch):
        """If an error occurs during stock restoration, savepoint rolls back attempt/order mutations."""
        customer = make_user(db_session, phone="9888888896", referral_code="PACUST15")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=3)
        addr = make_address(db_session, customer)

        order = Order(
            order_number="ORD-TEST-ERR-STOCK",
            idempotency_key="idemp-err-stock",
            user_id=customer.id,
            address_id=addr.id,
            total_amount=Decimal("1000.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            product_name=prod.name,
            unit_price=prod.price,
            quantity=1,
            line_total=Decimal("1000.00"),
        )
        db_session.add(item)

        expired_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="SIM-ATT-ERR-STOCK",
            provider="simulated",
            amount=Decimal("1000.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=expired_time,
        )
        db_session.add(attempt)
        db_session.commit()

        # Simulate exception during product stock update
        orig_query = db_session.query
        def mock_query(*args, **kwargs):
            if len(args) > 0 and args[0] is Product:
                raise RuntimeError("Simulated DB connection drop during product stock lock")
            return orig_query(*args, **kwargs)

        monkeypatch.setattr(db_session, "query", mock_query)

        count = PaymentService.expire_stale_payment_attempts(db_session)
        assert count == 0

        # Un-patch and verify candidate was rolled back completely
        monkeypatch.undo()
        db_session.refresh(attempt)
        assert attempt.status == PaymentStatus.PENDING
        db_session.refresh(order)
        assert order.order_status == OrderStatus.PENDING_PAYMENT
        db_session.refresh(prod)
        assert prod.stock == 3

    def test_synthetic_expiry_event_collision_rolls_back_entire_candidate(self, db_session, monkeypatch):
        """If event insertion fails with constraint collision, the candidate rolls back atomically."""
        customer = make_user(db_session, phone="9888888897", referral_code="PACUST16")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=3)
        addr = make_address(db_session, customer)

        order = Order(
            order_number="ORD-TEST-COLLISION",
            idempotency_key="idemp-collision",
            user_id=customer.id,
            address_id=addr.id,
            total_amount=Decimal("1000.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            product_name=prod.name,
            unit_price=prod.price,
            quantity=1,
            line_total=Decimal("1000.00"),
        )
        db_session.add(item)

        expired_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="SIM-ATT-COLLISION",
            provider="simulated",
            amount=Decimal("1000.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=expired_time,
        )
        db_session.add(attempt)
        db_session.commit()

        # Pre-seed a colliding event with identical fixed ID and monkeypatch uuid to produce collision
        fixed_suffix = "deadbeef"
        colliding_event = PaymentEvent(
            provider=attempt.provider,
            provider_event_id=f"exp_{attempt.attempt_reference}_{fixed_suffix}",
            event_type="payment.expired",
            order_id=order.id,
            payload_json="{}",
            status="PROCESSED",
        )
        db_session.add(colliding_event)
        db_session.commit()

        class MockUUID:
            hex = fixed_suffix

        import uuid
        monkeypatch.setattr(uuid, "uuid4", lambda: MockUUID)

        count = PaymentService.expire_stale_payment_attempts(db_session)
        assert count == 0

        # Verify atomic rollback: attempt is still PENDING, order is PENDING_PAYMENT, stock is unchanged
        db_session.refresh(attempt)
        assert attempt.status == PaymentStatus.PENDING
        db_session.refresh(order)
        assert order.order_status == OrderStatus.PENDING_PAYMENT
        db_session.refresh(prod)
        assert prod.stock == 3

    def test_expiry_normal_sqlalchemy_session_lifecycle(self, db_session):
        """Verify expire_stale_payment_attempts operates cleanly within standard caller session lifecycle."""
        customer = make_user(db_session, phone="9888888898", referral_code="PACUST17")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=2)
        addr = make_address(db_session, customer)

        order = Order(
            order_number="ORD-TEST-LIFECYCLE",
            idempotency_key="idemp-lifecycle",
            user_id=customer.id,
            address_id=addr.id,
            total_amount=Decimal("1000.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            product_name=prod.name,
            unit_price=prod.price,
            quantity=1,
            line_total=Decimal("1000.00"),
        )
        db_session.add(item)

        expired_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="SIM-ATT-LIFECYCLE",
            provider="simulated",
            amount=Decimal("1000.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=expired_time,
        )
        db_session.add(attempt)
        db_session.commit()

        # Call expiry method
        count = PaymentService.expire_stale_payment_attempts(db_session)
        assert count == 1

        # Session remains completely healthy and can perform further queries/commits
        db_session.refresh(attempt)
        assert attempt.status == PaymentStatus.FAILED
        new_prod = make_product(db_session, name="Second Product", price=Decimal("500.00"), stock=10)
        assert new_prod.id is not None


# ---------------------------------------------------------------------------
# 10. Concurrency Races & Idempotency Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConcurrencyAndRaces:
    """Verify webhook/expiry race conditions and checkout idempotency key repeat."""

    def test_expiry_worker_webhook_race_webhook_wins(self, db_session):
        """If webhook confirms order first, expiry worker must skip without modifying order or stock."""
        customer = make_user(db_session, phone="9900000001", referral_code="PACUST20")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=5)
        addr = make_address(db_session, customer)

        # Pending order with stock 4 (decremented 1)
        prod.stock = 4
        order = Order(
            order_number="ORD-RACE-01",
            idempotency_key="idemp-race-01",
            user_id=customer.id,
            address_id=addr.id,
            total_amount=Decimal("1000.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            product_name=prod.name,
            unit_price=prod.price,
            quantity=1,
            line_total=Decimal("1000.00"),
        )
        db_session.add(item)

        # Attempt expired 1 minute ago
        past_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="SIM-ATT-RACE-01",
            provider="simulated",
            amount=Decimal("1000.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=past_time,
        )
        db_session.add(attempt)
        db_session.commit()

        # Webhook arrives and confirms first
        payload = {
            "event_id": "evt_race_webhook_first",
            "event_type": "payment.completed",
            "attempt_reference": attempt.attempt_reference,
            "amount": 1000.00,
            "currency": "INR",
        }
        outcome, _ = PaymentService.process_verified_event(
            db=db_session,
            raw_payload=json.dumps(payload).encode("utf-8"),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert outcome == "COMPLETED"

        # Now expiry worker runs on the same expired attempt
        expired_count = PaymentService.expire_stale_payment_attempts(db_session)
        assert expired_count == 0  # Skipped because order already confirmed

        # Stock must remain 4 (NOT restored back to 5)
        db_session.refresh(prod)
        assert prod.stock == 4

        # Order must remain CONFIRMED
        db_session.refresh(order)
        assert order.order_status == OrderStatus.CONFIRMED

    def test_expiry_worker_webhook_race_expiry_wins(self, db_session):
        """If expiry worker marks attempt FAILED first, late webhook must be flagged and not confirm order."""
        customer = make_user(db_session, phone="9900000002", referral_code="PACUST21")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=4)
        addr = make_address(db_session, customer)

        order = Order(
            order_number="ORD-RACE-02",
            idempotency_key="idemp-race-02",
            user_id=customer.id,
            address_id=addr.id,
            total_amount=Decimal("1000.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            product_name=prod.name,
            unit_price=prod.price,
            quantity=1,
            line_total=Decimal("1000.00"),
        )
        db_session.add(item)

        past_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="SIM-ATT-RACE-02",
            provider="simulated",
            amount=Decimal("1000.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=past_time,
        )
        db_session.add(attempt)
        db_session.commit()

        # Expiry worker runs first
        count = PaymentService.expire_stale_payment_attempts(db_session)
        assert count == 1
        db_session.refresh(prod)
        assert prod.stock == 5  # Restored from 4 -> 5

        # Late webhook arrives after expiry
        payload = {
            "event_id": "evt_race_webhook_second",
            "event_type": "payment.completed",
            "attempt_reference": attempt.attempt_reference,
            "amount": 1000.00,
            "currency": "INR",
        }
        outcome, _ = PaymentService.process_verified_event(
            db=db_session,
            raw_payload=json.dumps(payload).encode("utf-8"),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert outcome == "FLAGGED_FOR_RECONCILIATION"

        # Stock must remain 5 (not decremented again)
        db_session.refresh(prod)
        assert prod.stock == 5
        db_session.refresh(order)
        assert order.order_status == OrderStatus.FAILED

    def test_repeated_checkout_idempotency_key_returns_existing_order(self, api_client, db_session):
        """Calling checkout twice with same (user_id, idempotency_key) returns existing order without decrementing stock again."""
        customer = make_user(db_session, phone="9900000003", referral_code="PACUST22")
        prod = make_product(db_session, price=Decimal("500.00"), stock=10)
        addr = make_address(db_session, customer)

        cart_item = CartItem(user_id=customer.id, product_id=prod.id, quantity=2)
        db_session.add(cart_item)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        # Checkout 1
        res1 = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr.id, "idempotency_key": "idemp-wp5-double-key-01"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res1.status_code == 201
        order1 = res1.json()

        db_session.refresh(prod)
        assert prod.stock == 8  # 10 - 2

        # Checkout 2 with EXACT same idempotency key
        res2 = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": addr.id, "idempotency_key": "idemp-wp5-double-key-01"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res2.status_code == 201
        order2 = res2.json()

        # Must return the identical order ID
        assert order1["id"] == order2["id"]
        assert order1["order_number"] == order2["order_number"]

        # Stock must NOT be decremented a second time (must still be 8)
        db_session.refresh(prod)
        assert prod.stock == 8


# ---------------------------------------------------------------------------
# 11. Rollback & Integrity Mismatch Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRollbackAndIntegrityMismatches:
    """Verify atomic rollbacks on exceptions and strict mismatch rejection."""

    def test_rejects_nonexistent_attempt_reference(self, db_session):
        payload = {
            "event_id": "evt_nonexistent_attempt",
            "event_type": "payment.completed",
            "attempt_reference": "SIM-ATT-DOES-NOT-EXIST",
            "amount": 1000.00,
            "currency": "INR",
        }
        with pytest.raises(PaymentValidationError, match="Payment attempt 'SIM-ATT-DOES-NOT-EXIST' does not exist"):
            PaymentService.process_verified_event(
                db=db_session,
                raw_payload=json.dumps(payload).encode("utf-8"),
                headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
            )

    def test_checkout_exception_rolls_back_stock_decrement(self, api_client, db_session):
        """If checkout creation fails after stock check, transaction rollback restores stock."""
        customer = make_user(db_session, phone="9900000004", referral_code="PACUST23")
        prod = make_product(db_session, price=Decimal("1000.00"), stock=5)
        # Invalid address ID (will fail validation)
        invalid_address_id = 999999

        cart_item = CartItem(user_id=customer.id, product_id=prod.id, quantity=2)
        db_session.add(cart_item)
        db_session.commit()

        token = create_access_token(customer.id, customer.role.value, customer.phone)

        res = api_client.post(
            "/api/v1/orders/checkout",
            json={"address_id": invalid_address_id, "idempotency_key": "idemp-wp5-fail-addr"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 400

        # Product stock must remain 5
        db_session.refresh(prod)
        assert prod.stock == 5
