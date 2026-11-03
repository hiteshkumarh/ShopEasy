# ShopEasy — Project Memory and Current State

**Source of Truth:** Approved ShopEasy PRD (`docs/PRD.md`)  
**Status:** Phase 1 Documentation Alignment completed; backend roadmap established.  
**Rule:** Update this file after each completed task. Do not treat planned or unstarted work as completed.

---

## 1. Project Summary

- **Project Name:** ShopEasy.
- **Purpose:** Learning and portfolio e-commerce website; not intended for commercial production use.
- **Frontend:** HTML5, CSS3, Vanilla JavaScript (Existing responsive prototypes).
- **Backend (Planned):** Python FastAPI (>= 3.10).
- **Database (Planned):** MySQL 8.0 with SQLAlchemy 2.0.
- **Validation:** Pydantic v2.
- **Deployment Target:** Render.
- **Payments & Withdrawals:** Simulated mock flows; zero real banking or gateway integration.
- **Initial Product Scope:** Single purchasable product — Power Bank at ₹3,999 (automatically eligible for Sequential Commission).
- **GitHub Repository:** `https://github.com/hiteshkumarh/ShopEasy`.
- **Environment:** Windows, Git Bash, Antigravity.

---

## 2. Completed Milestones

### 2.1 Customer Frontend Prototype
Existing verified prototype pages under `frontend/`:
- `frontend/index.html` (Home)
- `frontend/login.html` (Customer login prototype)
- `frontend/products.html` (Catalog)
- `frontend/product-details.html` (Product view)
- `frontend/cart.html` (Cart review)
- `frontend/checkout.html` (Checkout flow)
- `frontend/orders.html` (Order history)
- `frontend/profile.html` (Profile and referral code view)

### 2.2 Admin Frontend Prototype & Verification
Existing verified prototype pages under `frontend/admin/`:
- `frontend/admin/login.html` (Admin login)
- `frontend/admin/dashboard.html` (Admin dashboard)
- `frontend/admin/products.html` (Product management table)
- `frontend/admin/product-form.html` (Product add/edit form)
- `frontend/admin/orders.html` (Orders placeholder)
- `frontend/admin/customers.html` (Customer directory placeholder)

**Admin Product CRUD Verification (Reported):**
- Client-side image compression: 600x600 JPEG at quality 0.8 with quota fallback.
- Sequential product ID generation (`prod-013`).
- Manual QA reported successful for product creation (`Test Wireless Mouse`, ₹799, stock 25), refresh persistence, editing (₹899, stock 30), and deletion.

### 2.3 Local Environment Verification
- MySQL Server 8.0.41 installed locally.
- Service `MYSQL80` verified active.
- Root login tested; ShopEasy database creation reserved for `TASK-005`.

### 2.4 Phase 1 Documentation Alignment (Completed)
- Promoted draft PRD to authoritative [docs/PRD.md](file:///d:/projects/ShopEasy/docs/PRD.md).
- Updated [docs/architeture.md](file:///d:/projects/ShopEasy/docs/architeture.md) with data models and queue activation rules.
- Updated [docs/rules.md](file:///d:/projects/ShopEasy/docs/rules.md) with confirmed earning, wallet, and allocation rules.
- Updated [docs/tasks.md](file:///d:/projects/ShopEasy/docs/tasks.md) resolving duplicate TASK-004 and setting backend roadmap through TASK-010.
- Updated [docs/design.md](file:///d:/projects/ShopEasy/docs/design.md) with 16-circle progress display and dual wallet cards.
- Synchronized all 21 confirmed business decisions and 4 financial allocation scenarios across all documentation files.

---

## 3. Confirmed Business Decisions Summary

### 3.1 Customer Authentication
- Registration requires Full Name and Mobile Number.
- Dual login: Mobile + Password or Mobile + OTP.
- Every customer receives a unique permanent referral code upon registration.
- Referral code entry is optional and happens during checkout.
- Admin accounts never receive referral codes and cannot participate in referral rewards.

### 3.2 Direct Referral Reward (₹750)
- Credited only on the referred customer's first successful order using a valid referral code.
- Credited once per referee; repeat purchases generate ₹0 reward.
- Self-referrals prohibited (`referrer_id != customer_id`).
- Permanent direct referrer attribution established on first order.
- Full ₹750 credited without deductions (no TDS or service fees).
- Withdrawal allowed only when Direct Referral Wallet reaches at least ₹4,000.
- Customer must withdraw entire available balance (no partial withdrawals).
- Simulated withdrawal automatically marked successful; wallet resets to ₹0.

### 3.3 Sequential Commission (₹250 per eligible order)
- Single global beneficiary queue; entered automatically upon customer's first successful order (with or without code).
- Queue sequence strictly follows chronological timestamp of first successful orders (FIFO).
- **Initial Queue Activation:** First customer placing first successful order enters queue and becomes first active beneficiary if queue empty. Own order earns ₹0 and does not count toward 16.
- Active beneficiary earns commissions only from other customers' purchases. Own purchases earn ₹0 and do not advance counter.
- Exactly one active beneficiary at a time; next customer's purchase generates ₹250 for active beneficiary.
- Each beneficiary receives 16 commissions = ₹4,000 per lifetime cycle.
- Upon 16 commissions, cycle permanently closes; next customer in queue activates automatically.
- Completed ₹4,000 is withdrawable in full; simulated withdrawal resets wallet to ₹0.
- **Product Eligibility:** Initial Power Bank (₹3,999) is automatically eligible. Future product eligibility is out of scope.

### 3.4 Wallet System
- Separate balances maintained in backend and UI:
  1. `Direct Referral Wallet`
  2. `Sequential Commission Wallet`
- Aggregate summary: `Total Earnings = Direct Referral Wallet + Sequential Commission Wallet`.
- Auditable transaction ledger (`wallet_transactions`) records all credits and debits.

### 3.5 Financial Allocation Scenarios (Power Bank ₹3,999)
- Regular per-order unit allocations (Total = ₹2,300): Import ₹1,500, GST ₹400, Packing ₹150, Gift ₹150, Office ₹100.
- Residual balance designated as **"remaining amount after listed allocations"**:
  - **Scenario A (Both Apply):** Regular ₹2,300 + Sequential ₹250 + Referral ₹750 = ₹3,300 total; remaining ₹699.
  - **Scenario B (Sequential Only):** Regular ₹2,300 + Sequential ₹250 + Referral ₹0 = ₹2,550 total; remaining ₹1,449.
  - **Scenario C (Neither Applies):** Regular ₹2,300 + Sequential ₹0 + Referral ₹0 = ₹2,300 total; remaining ₹1,699.
  - **Scenario D (Direct Referral Only):** Regular ₹2,300 + Sequential ₹0 + Referral ₹750 = ₹3,050 total; remaining ₹949.
- Order snapshot saved in `order_allocations`.

### 3.6 Customer Dashboard
- Displays 16-circle progress indicator titled "Sequential Commission Progress":
  - Active beneficiary: live progress (e.g., 5/16, ₹1,250 / ₹4,000).
  - Non-beneficiary: 16 grey circles + banner *"You are not the current beneficiary."*
  - Completed beneficiary: 16/16 circles + badge *"Cycle completed — ₹4,000 earned."*

### 3.7 Order & Inventory Integrity
- Failed payment generates no order and no rewards.
- Successfully placed orders cannot be cancelled by customers.
- Returns and refunds are out of scope.
- Idempotent reward processing prevents duplicate commissions.
- Stock decrements immediately upon successful order placement.

---

## 4. Current Development Status

- Documentation: **Phase 1 complete and fully aligned.**
- Frontend: Completed prototypes awaiting backend integration.
- Backend: **Not started** (Scheduled for TASK-004 through TASK-010).
- Database: **Not created** (Scheduled for TASK-005).

---

## 5. Working Instructions for Antigravity

- All 21 business decisions are approved and documented in `docs/PRD.md`.
- Do not invent business rules.
- Do not modify files outside the approved task scope.
- Wait for explicit user approval before proceeding to Phase 2 (`TASK-004`).
