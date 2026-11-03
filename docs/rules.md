# ShopEasy — Business and Development Rules

**Source of Truth:** Approved ShopEasy PRD (`docs/PRD.md`)  
**Status:** Approved Business Rules Baseline (Phase 1 Documentation Alignment)  
**Project Type:** Learning and portfolio e-commerce application (Not for commercial production)  

---

## 1. General Project Rules

- Learning and portfolio project; not a production financial platform.
- Frontend: HTML5, CSS3, Vanilla JavaScript (No React, Vue, or Next.js).
- Backend: Python FastAPI (>= 3.10).
- Database: MySQL 8.0 with SQLAlchemy 2.0 and Pydantic v2.
- Deployment target: Render.
- Payments and withdrawals are simulated; do not integrate real payment gateways or banking APIs.
- Existing customer and admin frontend prototypes must be reused.
- Route handlers must remain thin; business rules belong in service layers.

---

## 2. Roles and Authentication

### Customer
- Registration requires Full Name and Mobile Number.
- Unique permanent referral code is generated automatically upon account creation.
- Login options: Phone + OTP or Phone + Password; both methods resolve to the same account record.
- Passwords must be securely hashed using Argon2id or bcrypt.
- OTPs must be single-use, expire within 5–10 minutes, and enforce a 60-second resend cooldown.

### Administrator
- Admin accounts are strictly pre-provisioned; no public admin registration.
- Login options: Phone + OTP, or Phone + Password followed by mandatory OTP MFA verification.
- Role assignment is backend-controlled.
- **Admin Referral Restriction:** Admin accounts **never receive referral codes** and **cannot use customer referral codes** or participate in referral rewards.

---

## 3. Referral Code Rules

1. Generate one unique permanent referral code automatically after customer registration.
2. Enforce database uniqueness on referral codes.
3. Display the referral code on the customer profile with a copy-to-clipboard action.
4. The code is permanent: it cannot be modified, edited, or regenerated.
5. Referral code entry is **optional** and happens during **checkout**, not registration.
6. A customer can place orders without a referral code.
7. A supplied referral code must belong to an existing customer record.
8. **Self-referral is strictly prohibited** (`referrer_id != customer_id`).
9. A valid referral code supplied on the customer's **first successful order** permanently establishes the direct referrer.
10. Later orders cannot alter, replace, or overwrite the direct referrer.
11. If the first successful order has no referral code, no direct referrer is established for that customer.
12. An invalid or self-referral code must be rejected with a clear message, allowing the customer to correct or remove it and proceed.

---

## 4. Direct Referral Reward Rules

- **Amount:** ₹750.
- **Trigger:** Credited only when a referred customer places their **first successful order** using a valid referral code.
- **Recipient:** The owner of that referral code (the permanent direct referrer).
- **Frequency:** Credited **only once** per referred customer. Repeat orders by the referee generate ₹0 direct referral reward.
- **Full Credit:** Full ₹750 is credited with **zero deductions** (no TDS or service charge deductions).
- **Independence:** Direct referral rewards are completely independent of sequential commissions.
- **Wallet & Withdrawal Rules:**
  - Credited to the customer's `Direct Referral Wallet`.
  - Withdrawal allowed only when Direct Referral Wallet balance reaches at least **₹4,000**.
  - Customer must withdraw the **entire available balance** (no partial withdrawals).
  - Simulated withdrawal is automatically marked successful, logging an auditable debit transaction and resetting the wallet to ₹0.

---

## 5. Sequential Commission Rules

- **Amount:** ₹250 per eligible successful order.
- **Order-Level Rule:** One eligible order generates exactly one ₹250 commission, regardless of product quantity ordered.
- **Global Beneficiary Queue:**
  - Every customer enters the single global beneficiary queue automatically upon their **first successful order**, regardless of whether a referral code was used.
  - Queue position follows the chronological timestamp of first successful orders (FIFO).
- **Initial Queue Activation (Bootstrap):**
  - When the first customer places their first successful order, they enter the queue and become the **first active beneficiary** if no active beneficiary exists.
  - Their own order generates **₹0 sequential commission** and does not count toward the 16 commissions.
- **Active Beneficiary Rules:**
  - Exactly **one active beneficiary** is active in the system at any given time.
  - The active beneficiary earns commissions only from **other customers' eligible purchases**.
  - Active beneficiary's own purchases generate **₹0 commission** and do not advance their counter.
  - The next customer's eligible order generates ₹250 for the active beneficiary.
- **Cycle Completion & Rotation:**
  - Each beneficiary receives exactly 16 commissions = **₹4,000 total**.
  - Upon reaching 16 commissions, the current beneficiary's cycle is marked completed and permanently closed.
  - The queue automatically advances to activate the next customer in sequence.
  - **Lifetime Limit:** Each customer can complete **only one beneficiary cycle for life**.
- **Product Eligibility:**
  - Initial Power Bank (₹3,999) automatically qualifies for Sequential Commission in backend configuration.
  - Future product eligibility is strictly outside the current scope; do not assume future products qualify and do not add admin eligibility checkboxes.
- **Wallet & Withdrawal Rules:**
  - Credited to the customer's `Sequential Commission Wallet`.
  - The completed ₹4,000 is withdrawable in full once the 16-commission cycle is complete.
  - Customer must withdraw the **entire ₹4,000** (no partial withdrawals).
  - Simulated withdrawal is automatically marked successful and resets the Sequential Commission Wallet to ₹0.

---

## 6. Wallet System Rules

- Maintain two distinct wallet balances in the backend:
  1. `Direct Referral Wallet`
  2. `Sequential Commission Wallet`
- Display metric: `Total Earnings = Direct Referral Wallet + Sequential Commission Wallet`.
- Maintain separate auditable transaction records in `wallet_transactions` for both earning categories.
- Balances are derived from and reconciled against auditable transaction records.

---

## 7. Order and Inventory Rules

- Referral code field is optional during checkout.
- Simulated payment result determines order completion.
- Failed payment generates no confirmed order, no stock decrement, and no rewards.
- Successfully placed orders cannot be cancelled by customers.
- Product returns, refunds, and commission reversals are strictly outside project scope.
- Order processing must be idempotent: duplicate submissions must never generate duplicate rewards.
- Stock decrements immediately and atomically upon successful order placement.
- Order captures an immutable snapshot of product items, unit prices, and financial allocations.

---

## 8. Financial Allocation Rules

Baseline financial allocations are calibrated for the initial Power Bank priced at **₹3,999**.

### Regular Fixed Unit Costs (Total = ₹2,300)
- Product import cost reserve: ₹1,500
- Output GST reserve: ₹400
- Packing and courier reserve: ₹150
- Gift and achievement reserve: ₹150
- Office and staff expense reserve: ₹100

### The Four Independent Allocation Scenarios
Residual balance is designated as **"remaining amount after listed allocations"** (not assumed company profit):

| Scenario | Conditions | Regular Allocations | Sequential Commission | Direct Referral Reward | Total Allocation | Remaining Amount after Listed Allocations |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Scenario A** | **Both Apply:** Referred customer's first successful order with valid code, placed while another user is active beneficiary. | ₹2,300 | ₹250 | ₹750 | **₹3,300** | **₹699** *(₹3,999 − ₹3,300)* |
| **Scenario B** | **Sequential Only:** Customer's first order placed without referral code (or any repeat order), placed while another user is active beneficiary. | ₹2,300 | ₹250 | ₹0 | **₹2,550** | **₹1,449** *(₹3,999 − ₹2,550)* |
| **Scenario C** | **Neither Applies:** Active beneficiary's own purchase placed without referral code (or repeat purchase by active beneficiary). | ₹2,300 | ₹0 | ₹0 | **₹2,300** | **₹1,699** *(₹3,999 − ₹2,300)* |
| **Scenario D** | **Direct Referral Only:** Active beneficiary's first purchase using a valid referral code. | ₹2,300 | ₹0 | ₹750 | **₹3,050** | **₹949** *(₹3,999 − ₹3,050)* |

Financial allocations are fixed in backend configuration and stored as an immutable snapshot in `order_allocations` per confirmed order.

---

## 9. Customer Dashboard & Earning UI Rules

- Display customer's unique referral code with one-click copy feedback.
- Display separate wallet balance cards: Direct Referral Wallet and Sequential Commission Wallet, plus Total Earnings card.
- Provide full-balance withdrawal action buttons with eligibility gating (disabled when conditions not met).
- Every customer sees a **16-circle visual progress indicator** titled "Sequential Commission Progress":
  - **Active Beneficiary:** Filled green circles for credited commissions, grey circles for remaining; displays count (e.g. `5/16`) and amount (e.g. `₹1,250 / ₹4,000`).
  - **Non-Beneficiary:** All 16 circles greyed out; displays explicit banner *"You are not the current beneficiary."*
  - **Completed Beneficiary:** All 16 circles filled; displays milestone badge *"Cycle completed — ₹4,000 earned."*
- Never fabricate progress for non-beneficiaries. All progress data must originate from verified backend state.

---

## 10. Backend Security and Integrity Rules

- The backend is the sole source of truth for pricing, stock, roles, referral attribution, commissions, and balances.
- Never trust client-submitted prices, discounts, reward amounts, or role identifiers.
- Passwords must be hashed using Argon2id or bcrypt.
- Enforce strict database unique constraints on phone numbers, referral codes, order allocations, and commission records.
- Use atomic transactions and row-level locking (`SELECT ... FOR UPDATE`) during order reward processing and queue pointer advancement to prevent concurrent race conditions.
- Store secrets and configuration in environment variables; do not commit `.env` files.

---

## 11. Explicitly Out of Scope

- Real payment gateway integration (Stripe, Razorpay, etc.).
- Real bank account, UPI, or payment payout integrations.
- TDS and service charge deductions (100% of ₹750 is credited).
- Order cancellations by customers, returns, refunds, and commission clawbacks.
- Multi-level / upline pyramid referral trees.
- Complex shipping/courier logistics integrations.

---

## 12. Status of Business Decisions

All 21 business decisions have been finalized and approved by the project owner. There are no remaining open business decisions. Technical development must adhere strictly to these rules.
