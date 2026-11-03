# ShopEasy — Development Tasks

**Status:** Phase 1 Documentation Alignment completed; backend development roadmap established.  
**Implementation Rule:** Do not mark unimplemented development tasks as completed. Preserve existing completed frontend prototype records.

---

## Status Legend

- `[x]` Completed and verified.
- `[~]` Partially completed / in progress.
- `[ ]` Not started (approved for upcoming phases).
- `[!]` Blocked by external dependency or owner input.

---

## Phase 1 — Project Setup and Documentation Alignment

- [x] **TASK-001:** Create ShopEasy project repository, directory structure, and frontend base.
- [x] **TASK-002:** Establish core technology stack: HTML5/CSS3/Vanilla JS, FastAPI, MySQL 8.0, SQLAlchemy 2.0, Pydantic v2, Render.
- [x] **TASK-003.1:** Draft architecture, design, rules, tasks, and memory documentation.
- [x] **TASK-003.2:** Build ShopEasy Admin Dashboard and Product Management UI prototype.
- [x] **TASK-003.3:** Document Dual-Mode Authentication Requirements (Phone + OTP and Phone + Password for Customer & Admin).
- [x] **TASK-003.4:** Execute Final PRD Reconciliation Report aligning all 21 confirmed business decisions and 4 independent financial scenarios.
- [x] **TASK-003.5:** Execute Phase 1 Documentation Alignment:
  - Create authoritative [docs/PRD.md](file:///d:/projects/ShopEasy/docs/PRD.md).
  - Update [docs/architeture.md](file:///d:/projects/ShopEasy/docs/architeture.md) with data models and queue activation rules.
  - Update [docs/rules.md](file:///d:/projects/ShopEasy/docs/rules.md) with confirmed earning, wallet, and allocation rules.
  - Update [docs/tasks.md](file:///d:/projects/ShopEasy/docs/tasks.md) resolving duplicate TASK-004 and defining backend roadmap.
  - Update [docs/design.md](file:///d:/projects/ShopEasy/docs/design.md) with 16-circle progress display and dual wallet cards.
  - Update [docs/memory.md](file:///d:/projects/ShopEasy/docs/memory.md) recording verified baseline.

---

## Phase 2 — Customer Frontend Prototype (Completed)

- [x] Build home storefront page (`frontend/index.html`).
- [x] Build customer login page (`frontend/login.html`).
- [x] Build product listing catalog (`frontend/products.html`).
- [x] Build product details view (`frontend/product-details.html`).
- [x] Build cart management page (`frontend/cart.html`).
- [x] Build checkout page prototype (`frontend/checkout.html`).
- [x] Build customer orders history page (`frontend/orders.html`).
- [x] Build customer profile page (`frontend/profile.html`).
- [~] Add optional referral code input field to checkout page (scheduled for TASK-010).
- [~] Add customer earnings dashboard with 16 progress circles and dual wallet cards (scheduled for TASK-010).

---

## Phase 3 — Admin Frontend Prototype (Completed)

- [x] Build admin login prototype (`frontend/admin/login.html`).
- [x] Build admin dashboard overview (`frontend/admin/dashboard.html`).
- [x] Build admin product management table (`frontend/admin/products.html`).
- [x] Build admin add/edit product form (`frontend/admin/product-form.html`).
- [x] Build admin orders fulfillment placeholder (`frontend/admin/orders.html`).
- [x] Build admin customer directory placeholder (`frontend/admin/customers.html`).
- [x] Implement browser localStorage product CRUD prototype with sequential IDs (`prod-013`).
- [x] Fix image storage quota using 600x600 JPEG compression and sanitization fallback.
- [x] Verify product creation, persistence after refresh, editing, and deletion via manual test.

---

## Phase 4 — Business Decisions & Architecture Approval (Completed)

- [x] Confirm single purchasable product for initial launch: Power Bank at ₹3,999.
- [x] Confirm automatic sequential commission eligibility for initial Power Bank.
- [x] Confirm ₹750 direct referral reward paid once on referee's first successful order with valid code.
- [x] Confirm ₹250 sequential commission per eligible order, independent of item quantity.
- [x] Confirm 16 commissions = ₹4,000 per lifetime cycle per beneficiary.
- [x] Confirm initial queue activation: first buyer enters queue and becomes active beneficiary if queue empty; own order earns ₹0 and does not count toward 16.
- [x] Confirm active beneficiary earns only from other customers' purchases; own order gives ₹0 and does not advance counter.
- [x] Confirm single global FIFO queue ordered chronologically by first successful order timestamp.
- [x] Confirm separate wallets: Direct Referral Wallet (min ₹4,000 full withdrawal) and Sequential Commission Wallet (₹4,000 full withdrawal).
- [x] Confirm the 4 independent financial allocation scenarios (Scenarios A, B, C, D) and "remaining amount after listed allocations" terminology.
- [x] Confirm admin accounts never receive referral codes and cannot use customer referral codes.
- [x] Confirm non-cancellable orders, out-of-scope returns/refunds, and simulated payment/withdrawal flows.

---

## Phase 5 — Backend Implementation Roadmap (Unstarted — Approved Baseline)

*Do not begin until Phase 1 documentation review is formally acknowledged by the project owner.*

### TASK-004 — Backend Project Setup & FastAPI Initialization
- [ ] Create FastAPI backend directory structure under `backend/app/` (`main.py`, `core/`, `api/`, `models/`, `schemas/`, `services/`).
- [ ] Implement application settings using Pydantic `BaseSettings` (`backend/app/core/config.py`).
- [ ] Configure CORS middleware to permit requests from the frontend origin.
- [ ] Create health check endpoint (`/api/v1/health`) returning application status.
- [ ] Configure basic error handlers and centralized exception handling.

### TASK-005 — MySQL Database Setup, SQLAlchemy Models & Alembic Migrations
- [ ] Configure database engine and session maker (`backend/app/core/database.py`).
- [ ] Create SQLAlchemy 2.0 declarative models matching approved conceptual schema:
  - `User`, `BeneficiaryQueue`, `CommissionCycle`, `SequentialCommission`, `ReferralCommission`, `WalletTransaction`, `OrderAllocation`.
  - Core e-commerce: `Product`, `Order`, `OrderItem`, `Address`, `CartItem`, `OTPVerification`.
- [ ] Configure Alembic migrations environment.
- [ ] Generate and execute initial database migration script.
- [ ] Create database seed script with pre-provisioned Admin account and initial Power Bank product (₹3,999).

### TASK-006 — Customer & Admin Authentication, Authorization & Security
- [ ] Implement password hashing utilities using Argon2id or bcrypt.
- [ ] Implement JWT token generator and authentication dependencies (`get_current_user`, `require_admin`).
- [ ] Implement customer registration endpoint with auto-generated unique referral code.
- [ ] Implement customer login via Phone + Password and Phone + OTP (simulated OTP service for development).
- [ ] Implement admin login via Phone + OTP and Phone + Password with mandatory OTP MFA verification.
- [ ] Implement OTP request, verification, expiration, and rate-limiting controls.
- [ ] Verify security boundary: admin accounts never receive referral codes and cannot access customer referral features.

### TASK-007 — Product Catalog & Admin Product Management API
- [ ] Implement public product listing and details API (`GET /api/v1/products`, `GET /api/v1/products/{id}`).
- [ ] Implement admin product CRUD endpoints (`POST`, `PUT`, `DELETE /api/v1/admin/products`).
- [ ] Enforce initial Power Bank automatic qualification for Sequential Commission in backend configuration.
- [ ] Implement inventory stock validation and admin stock adjustment endpoints.

### TASK-008 — Cart, Checkout, Order Placement & Allocation Snapshot Engine
- [ ] Implement customer cart management APIs (`GET`, `POST`, `PUT`, `DELETE /api/v1/cart`).
- [ ] Implement customer address management APIs (`GET`, `POST`, `PUT`, `DELETE /api/v1/addresses`).
- [ ] Implement checkout submission endpoint (`POST /api/v1/orders/checkout`):
  - Optional referral code validation (prohibiting self-referral).
  - Atomic stock validation and inventory decrement.
  - Simulated payment execution.
  - Order record creation with price and item snapshots.
  - Immutable `order_allocations` snapshot generation across the 4 independent financial scenarios.
- [ ] Enforce non-cancellable order policy.

### TASK-009 — Dual Earning Engine, Beneficiary Queue & Simulated Withdrawals
- [ ] Implement Direct Referral Reward service:
  - Check if ordering customer is referred and placing their first successful order.
  - If valid, record permanent attribution and credit ₹750 to referrer's `Direct Referral Wallet`.
- [ ] Implement Sequential Commission Queue engine:
  - FIFO queue enrollment on first successful order.
  - Initial queue bootstrap: activate first customer if queue empty (own order earns ₹0; 0/16 count).
  - Credit ₹250 to active beneficiary on eligible orders placed by other customers.
  - Track cycle progress; advance queue to next beneficiary upon reaching 16 commissions (₹4,000).
- [ ] Implement auditable `wallet_transactions` ledger for both earning categories.
- [ ] Implement simulated withdrawal API (`POST /api/v1/wallets/withdraw`):
  - Direct Referral: Validate balance $\ge$ ₹4,000; execute full withdrawal; reset to ₹0.
  - Sequential Commission: Validate cycle completed (₹4,000); execute full withdrawal; reset to ₹0.
  - Record auditable debit transaction and mark successful immediately.

### TASK-010 — Frontend API Integration, Customer Dashboard & Deployment
- [ ] Replace prototype localStorage in customer frontend with live Fetch calls to FastAPI backend.
- [ ] Add optional Referral Code input field to `frontend/checkout.html` with real-time validation.
- [ ] Add Password login option to `frontend/login.html`.
- [ ] Build customer earnings dashboard:
  - 16-circle visual progress indicator displaying live beneficiary state, non-beneficiary grey state, or completed state.
  - Separate Direct Referral and Sequential Commission wallet balance cards, plus Total Earnings card.
  - Full-balance withdrawal action buttons with eligibility gating.
- [ ] Replace localStorage product management in admin frontend with `/api/v1/admin/` endpoints.
- [ ] Configure Render deployment settings for web service and external MySQL database.
- [ ] Execute comprehensive end-to-end integration and smoke tests.
