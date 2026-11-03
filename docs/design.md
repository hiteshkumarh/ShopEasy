# ShopEasy — UI/UX Design Specification

**Status:** Approved Design Baseline (Phase 1 Documentation Alignment)  
**Design Direction:** Clean, minimal, responsive storefront with a consistent admin interface and clear financial gamification.  
**Styling Architecture:** Plain CSS3 with modern custom properties (CSS variables), mobile-first responsive layout, and vanilla JavaScript DOM interactions.

---

## 1. Design Principles

- Keep the customer shopping flow frictionless and straightforward.
- Use a clear visual hierarchy, accessible contrast, and readable typography.
- Maintain consistent spacing, button variants, input fields, cards, and modal elements.
- Ensure 100% responsive layouts across desktop, tablet, and mobile screens.
- Reuse existing frontend prototype templates; do not rebuild completed pages without a requirement.
- Clearly separate customer-facing information from administrative controls.
- Maintain transparent financial state: never fabricate or mock progress on the client side; render verified backend state.

---

## 2. Customer Pages & Navigation Structure

Existing customer prototype pages:

| Page | File Path | Main Purpose |
| :--- | :--- | :--- |
| **Home** | `frontend/index.html` | Hero banner, value propositions, featured Power Bank product, footer. |
| **Login / Auth** | `frontend/login.html` | Phone + OTP and Phone + Password authentication tabs. |
| **Catalog** | `frontend/products.html` | Product listing, category filter, search, and sorting. |
| **Product Details** | `frontend/product-details.html` | Image preview, price (₹3,999), specifications, stock, Add to Cart. |
| **Cart** | `frontend/cart.html` | Itemized review, quantity adjustment, subtotal, and Proceed to Checkout. |
| **Checkout** | `frontend/checkout.html` | Delivery address selection, optional referral code input, order summary, simulated payment. |
| **Orders** | `frontend/orders.html` | Customer order history, price snapshots, delivery status. |
| **Profile** | `frontend/profile.html` | Personal info, address book management, permanent referral code with copy button. |
| **Dashboard** | `frontend/dashboard.html` | Customer earnings dashboard: 16-circle progress indicator, separate wallet balance cards, and simulated withdrawals. |

---

## 3. Checkout Referral Code Specification

The checkout interface provides an optional input field for referral code entry before order confirmation:

```
+----------------------------------------------------------------+
| Have a Referral Code? (Optional)                               |
| [ ENTER CODE      ] [ Apply ]                                  |
| (i) Enter a friend's referral code to link your account.       |
+----------------------------------------------------------------+
```

### UX & Validation Rules:
1. **Optional Entry:** The field is completely optional; customers can checkout without entering a code.
2. **Interactive Validation:**
   - On clicking "Apply", the frontend queries `POST /api/v1/referrals/validate`.
   - **Valid Code:** Shows a green confirmation badge: `✓ Referral code applied: REF-XXXXX`. Replaces "Apply" button with a "Remove" link.
   - **Invalid Code:** Shows a red inline error message: `✗ Invalid referral code. Please check and try again.`
   - **Self-Referral:** Shows a warning: `✗ You cannot use your own referral code.`
3. **Non-Blocking Flow:** An invalid code does not prevent the user from removing the text and proceeding with the purchase.
4. **Order Confirmation:** When the order is placed, the validated code is passed in the payload. The order summary displays the applied code.

---

## 4. Customer Earnings Dashboard & Gamification

The customer earnings dashboard (`frontend/dashboard.html` or integrated tab) visualizes customer rewards and wallet liquidation:

```
+========================================================================+
| My Earnings & Commission Dashboard                                     |
+========================================================================+
| +--------------------+ +--------------------+ +--------------------+   |
| | Total Earnings     | | Direct Referral    | | Sequential Wallet  |   |
| | ₹1,250             | | ₹0                 | | ₹1,250             |   |
| | Lifetime Accrued   | | (1 Ref = ₹750)     | | (5 / 16 credited)  |   |
| +--------------------+ +--------------------+ +--------------------+   |
+------------------------------------------------------------------------+
| Sequential Commission Progress                                         |
| Active Beneficiary Progress: 5 / 16 Commissions (₹1,250 / ₹4,000)      |
|                                                                        |
|  [●] [●] [●] [●] [●] [○] [○] [○] [○] [○] [○] [○] [○] [○] [○] [○]       |
|                                                                        |
|  Each eligible order placed in the system contributes ₹250 to your turn|
+------------------------------------------------------------------------+
| Wallet Balances & Cashout                                              |
|                                                                        |
| Direct Referral Balance: ₹0.00                                         |
| [ Withdraw All (Requires Min ₹4,000) — DISABLED ]                      |
|                                                                        |
| Sequential Commission Balance: ₹1,250.00                               |
| [ Withdraw Completed ₹4,000 — DISABLED (Pending 11 orders) ]          |
+========================================================================+
```

### 4.1 The 16-Circle Progress Component
- **Component Title:** `Sequential Commission Progress`.
- **Visual Design:** A responsive grid or horizontal row of 16 circular badges (40px $\times$ 40px) numbered 1 through 16.

#### Three Display States:
1. **Active Beneficiary State:**
   - Credited slots (1 to $N$): Rendered in vibrant solid green (`var(--color-success)`) with a white checkmark or slot number.
   - Uncredited slots ($N+1$ to 16): Rendered as outlined neutral grey circles.
   - Summary label: `Active Beneficiary Progress: N / 16 Commissions (₹[N*250] / ₹4,000)`.
2. **Waiting / Non-Beneficiary State:**
   - All 16 circles rendered in muted neutral grey.
   - Prominent notification banner: `You are not the current beneficiary. Customers are placed in sequence based on their first successful order.`
   - No misleading partial progress is shown.
3. **Completed Cycle State:**
   - All 16 circles rendered in solid green.
   - Milestone banner: `✓ Cycle completed — ₹4,000 earned. Your sequential beneficiary cycle is complete.`

### 4.2 Dual Wallet Cards & Simulated Withdrawals
- **Direct Referral Wallet Card:**
  - Displays available balance.
  - Explanatory note: `₹750 earned per referred customer's first purchase.`
  - Action Button: `Withdraw Full Balance`.
  - Eligibility: Enabled only when balance $\ge$ ₹4,000. When clicked, dispatches simulated withdrawal, shows instant success alert, and resets balance display to ₹0.
- **Sequential Commission Wallet Card:**
  - Displays accrued cycle earnings.
  - Action Button: `Withdraw Completed ₹4,000`.
  - Eligibility: Enabled only when cycle is complete (balance = ₹4,000). When clicked, dispatches simulated withdrawal, shows instant success alert, and resets balance display to ₹0.

---

## 5. Administrator Pages

Existing admin prototype pages:

| Page | File Path | Main Purpose |
| :--- | :--- | :--- |
| **Admin Login** | `frontend/admin/login.html` | Phone + Password with mandatory OTP MFA verification. |
| **Admin Dashboard** | `frontend/admin/dashboard.html` | Total orders, total revenue (prototype label), catalog counts, quick actions. |
| **Product List** | `frontend/admin/products.html` | Responsive table of products, image preview, price, stock, active toggle, action buttons. |
| **Product Form** | `frontend/admin/product-form.html` | Add/Edit product form: name, price, stock quantity, description, category, image upload. |
| **Admin Orders** | `frontend/admin/orders.html` | Order list with customer name, timestamp, total, status badge, inspect allocation snapshots. |
| **Admin Customers**| `frontend/admin/customers.html` | Customer directory, phone, registration date, order count, account status. |

### Administrative Design Safeguards:
- Admin pages **never display referral codes** or customer referral controls.
- Product Form does not include financial allocation percentages or commission eligibility toggles; fixed financial allocations are managed server-side.
- Revenue metrics are clearly tagged as prototype demo totals.

---

## 6. Color Palette & UI Tokens

Consistent CSS custom properties used across customer and admin templates:

```css
:root {
  --color-primary: #2563eb;       /* Primary interactive blue */
  --color-primary-hover: #1d4ed8;
  --color-success: #16a34a;       /* Completed 16-circle green */
  --color-warning: #f59e0b;       /* Alerts & pending states */
  --color-danger: #dc2626;        /* Errors & remove actions */
  --color-neutral-bg: #f8fafc;    /* Page background */
  --color-surface: #ffffff;       /* Card surfaces */
  --color-border: #e2e8f0;        /* Subtle divider borders */
  --color-text-main: #0f172a;     /* Primary typography */
  --color-text-muted: #64748b;    /* Subheadings & labels */
  --color-slot-empty: #cbd5e1;    /* Unfilled 16-circle grey */
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-full: 9999px;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}
```

---

## 7. Status of Design Decisions

All previously pending design decisions are resolved:
1. **Wallet Card Layout:** Resolved — Separate cards for Direct Referral Wallet and Sequential Commission Wallet, accompanied by a combined Total Earnings card.
2. **16-Circle Progress Title:** Resolved — Titled "Sequential Commission Progress".
3. **Withdrawal Controls:** Resolved — Full-balance action buttons gated by minimum thresholds (₹4,000).
4. **Checkout Referral Field:** Resolved — Optional input field placed in checkout order summary with inline validation and remove capability.
