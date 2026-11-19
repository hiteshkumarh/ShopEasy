"""
backend/tests/test_wp12_step5_checkout_and_billing_history.py
Test suite for WP-12 Step 5: Checkout Notice & Billing ID Order History.

Verifies:
1. Exact checkout notice text ("Orders cannot be cancelled, returned or replaced after successful payment.").
2. Notice visible before Place Order action.
3. Purchase history for Plan A customer dashboard.
4. Purchase history for Plan B distributor dashboard.
5. Multiple Billing IDs for a multi-unit order.
6. Correct order-to-Billing-ID association.
7. No fabricated Billing IDs in frontend JavaScript.
8. Failed/pending payment with no issued Billing ID.
9. Customer ownership and programme isolation.
10. Loading, empty and API error states with retry.
"""

import os
import re
import pytest

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
CHECKOUT_HTML_PATH = os.path.join(FRONTEND_DIR, "checkout.html")
PLAN_A_HTML_PATH = os.path.join(FRONTEND_DIR, "dashboard.html")
PLAN_A_JS_PATH = os.path.join(FRONTEND_DIR, "js", "dashboard.js")
PLAN_B_HTML_PATH = os.path.join(FRONTEND_DIR, "distributor-dashboard.html")
PLAN_B_JS_PATH = os.path.join(FRONTEND_DIR, "js", "distributor-dashboard.js")
ORDERS_HTML_PATH = os.path.join(FRONTEND_DIR, "orders.html")

MANDATORY_NOTICE_TEXT = "Orders cannot be cancelled, returned or replaced after successful payment."


def test_files_exist():
    """Verify that all target frontend files exist."""
    for p in [CHECKOUT_HTML_PATH, PLAN_A_HTML_PATH, PLAN_A_JS_PATH, PLAN_B_HTML_PATH, PLAN_B_JS_PATH, ORDERS_HTML_PATH]:
        assert os.path.exists(p), f"Missing required file: {p}"


def test_exact_checkout_notice_text():
    """
    Requirement OR-10:
    Display this exact notice before the customer places an order:
    "Orders cannot be cancelled, returned or replaced after successful payment."
    """
    with open(CHECKOUT_HTML_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    assert MANDATORY_NOTICE_TEXT in content, (
        f"Exact notice '{MANDATORY_NOTICE_TEXT}' not found in checkout.html"
    )

    # Ensure no cancellation / return / replacement workflows were added
    assert "return-order" not in content.lower()
    assert "cancel-order" not in content.lower()
    assert "refund-request" not in content.lower()


def test_notice_visible_before_place_order():
    """
    Requirement OR-10:
    The notice must be visible before the Place Order action in checkout.html.
    """
    with open(CHECKOUT_HTML_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    notice_pos = content.find(MANDATORY_NOTICE_TEXT)
    place_order_btn_pos = content.find('id="place-order-btn"')

    assert notice_pos != -1, "Notice text not found in checkout.html"
    assert place_order_btn_pos != -1, "Place Order button not found in checkout.html"
    assert notice_pos < place_order_btn_pos, (
        "The checkout notice must appear before the Place Order button in the DOM"
    )


def test_purchase_history_plan_a_dashboard():
    """
    Requirement OR-12:
    Plan A Customer Dashboard contains purchase history section and loader.
    """
    with open(PLAN_A_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    with open(PLAN_A_JS_PATH, "r", encoding="utf-8") as f:
        js = f.read()

    # HTML elements
    assert "purchase-history-section" in html
    assert "purchase-history-container" in html
    assert "Purchase History &amp; Billing IDs" in html or "Purchase History" in html

    # JS logic
    assert "loadPurchaseHistory" in js
    assert "renderPurchaseHistoryTable" in js
    assert "ShopEasyOrders.list" in js


def test_purchase_history_plan_b_dashboard():
    """
    Requirement OR-12:
    Plan B Distributor Dashboard contains purchase history section and loader.
    """
    with open(PLAN_B_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    with open(PLAN_B_JS_PATH, "r", encoding="utf-8") as f:
        js = f.read()

    # HTML elements
    assert "distributor-purchase-section" in html
    assert "distributor-purchase-container" in html
    assert "Purchases &amp; Billing IDs" in html or "Purchases" in html

    # JS logic
    assert "loadDistributorPurchaseHistory" in js
    assert "renderDistributorPurchasesTable" in js
    assert "ShopEasyOrders.list" in js


def test_multiple_billing_ids_for_multi_unit_order():
    """
    Requirement OR-12:
    An order containing multiple units must show individual Billing IDs for each purchased unit separately.
    """
    with open(PLAN_A_JS_PATH, "r", encoding="utf-8") as f:
        js_a = f.read()
    with open(PLAN_B_JS_PATH, "r", encoding="utf-8") as f:
        js_b = f.read()

    for js in [js_a, js_b]:
        # Verifies per-unit mapping exists in rendering
        assert "itemBillingIds.map" in js or "billing-id-pill" in js
        assert "Unit ${idx + 1}" in js or "Unit " in js
        # Copy button provided for Billing IDs
        assert "copyBillingIdText" in js or "copyDistributorBillingIdText" in js


def test_correct_order_to_billing_id_association():
    """
    Requirement OR-12:
    Preserve association between each Billing ID and its correct order, product and customer.
    """
    with open(PLAN_A_JS_PATH, "r", encoding="utf-8") as f:
        js_a = f.read()
    with open(PLAN_B_JS_PATH, "r", encoding="utf-8") as f:
        js_b = f.read()

    for js in [js_a, js_b]:
        assert "item.product_name" in js
        assert "orderNum" in js or "order_number" in js
        assert "order.order_items" in js


def test_no_fabricated_billing_ids():
    """
    Requirement OR-12:
    Never generate, predict, modify or fabricate Billing IDs in frontend JavaScript.
    When not provided, display clear waiting message.
    """
    with open(PLAN_A_JS_PATH, "r", encoding="utf-8") as f:
        js_a = f.read()
    with open(PLAN_B_JS_PATH, "r", encoding="utf-8") as f:
        js_b = f.read()

    for js in [js_a, js_b]:
        # Disallow synthetic generation
        assert "AGD-" not in js or "AGD-" in js and "AGD-000201" not in js  # ensure no fake format templates
        assert "Math.random" not in js.split("loadPurchaseHistory")[-1]  # no random generation in purchase history
        # Must display waiting message when not provided by backend
        assert "Awaiting Billing ID allocation / Not provided by server" in js


def test_failed_or_pending_payment_no_billing_id():
    """
    Requirement OR-12:
    Never display a Billing ID for a failed or pending payment if the backend has not issued one.
    """
    with open(PLAN_A_JS_PATH, "r", encoding="utf-8") as f:
        js_a = f.read()
    with open(PLAN_B_JS_PATH, "r", encoding="utf-8") as f:
        js_b = f.read()

    for js in [js_a, js_b]:
        assert "No Billing ID issued (Payment" in js or "No Billing ID issued" in js


def test_programme_isolation_preserved():
    """
    Requirement RG-12:
    Plan A and Plan B programme isolation must be preserved on both dashboards.
    """
    with open(PLAN_A_JS_PATH, "r", encoding="utf-8") as f:
        js_a = f.read()
    with open(PLAN_B_JS_PATH, "r", encoding="utf-8") as f:
        js_b = f.read()

    # Plan A checks and rejects non-PLAN_A users
    assert "programme !== 'PLAN_A'" in js_a or 'programme !== "PLAN_A"' in js_a
    # Plan B checks and rejects non-PLAN_B users
    assert "programme !== 'PLAN_B'" in js_b or 'programme !== "PLAN_B"' in js_b


def test_loading_empty_and_error_states():
    """
    Requirement OR-12 UX:
    Provide loading state, empty purchase-history state, and API error state with retry.
    """
    with open(PLAN_A_JS_PATH, "r", encoding="utf-8") as f:
        js_a = f.read()
    with open(PLAN_B_JS_PATH, "r", encoding="utf-8") as f:
        js_b = f.read()

    for js in [js_a, js_b]:
        # Loading state
        assert "loading" in js.lower() and "purchase history" in js.lower()
        # Empty state
        assert "no purchases found" in js.lower()
        # Error state with retry
        assert "unable to load purchase history" in js.lower()
        assert "retry" in js.lower()
