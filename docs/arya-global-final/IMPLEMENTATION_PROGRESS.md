# Implementation Progress

Branch: `feature/arya-dual-plan-referral-platform` · Last updated: 2026-11-15

| Task | Programme | Files | Status | Tests | Blocker |
|---|---|---|---|---|---|
| Stage 0 — Repository audit & baseline | A+B | `docs/01_EXISTING_SYSTEM_AUDIT.md` | COMPLETE | Compile ✔, import ✔ (with CA path), scripted smoke on SQLite ✔ (scratch, not committed) | Alembic on MySQL/TiDB not run (no local DB; Docker daemon stopped) |
| Stage 1 — PRD gap analysis | A+B | `docs/02_PRD_GAP_ANALYSIS.md` | COMPLETE | n/a (documentation) | — |
| Stage 1 — Traceability matrix | A+B | `docs/03_REQUIREMENTS_TRACEABILITY.md` | COMPLETE | Test IDs reserved | — |
| Stage 1 — Roadmap, architecture, test strategy, risks | A+B | `docs/04_IMPLEMENTATION_ROADMAP.md` | COMPLETE | n/a | — |
| Stage 1 — Business-rule conflict register | A+B | `docs/05_BUSINESS_RULE_DECISIONS.md` | COMPLETE | n/a | Remaining client question: BR-A7 (commission pool only) |
| WP-0 Safe config defaults, lazy engine | A+B | `app/core/config.py`, `app/core/database.py` | COMPLETE | 22 unit tests passing | — |
| WP-1 Test harness + MySQL CI | A+B | `backend/tests/`, CI | COMPLETE | 30 MySQL config + 7 MySQL integration tests in CI | — |
| WP-2 Money utils & financial settings | A+B | `app/core/money.py`, `app/models/financial_settings.py`, `app/services/financial_settings.py`, `app/core/seed.py` | COMPLETE | 140 unit tests + 10 MySQL integration tests passed in CI | — |
| WP-3 Additive migration (programme, status, referrals, audit, notifications) | A+B | `app/models/`, `alembic/versions/79b742f969d6_*.py` | COMPLETE | 160 unit + 11 MySQL integration in CI Run #12 (171 passed, 0 skipped); SQLite & isolated MySQL lifecycle tests; Alembic check clean | OP-11 before running on real data |
| WP-4 Programme registration & referral rules | A+B | `app/api/v1/endpoints/auth.py`, `app/api/v1/endpoints/admin_auth.py`, `app/services/referral.py` | COMPLETE | 32 dedicated unit/integration tests passing (`test_wp4_referral_programme.py`); registration validation, mobile uniqueness, prefix generation, direction matrix (A→A, B→A, B→B allowed; A→B forbidden per BR-X3), qualification checks, status enforcement, and checkout referral binding verified; BR-X1 resolved & implemented (Plan A repeat purchases award ₹700 net to new code owner; repeat Billing IDs bypass cashback cycles; root relationship immutable) | — (BR-X1, BR-X3 resolved and implemented) |
| WP-5 Payment abstraction | A+B | — | NOT_STARTED | — | — |
| WP-6 Billing IDs + fulfilment + recovery | A+B | `app/models/billing.py`, `app/services/billing/`, `app/services/fulfilment/`, `alembic/versions/b7f2d4e8c1a9_*.py` | COMPLETE | 283 passed in CI Run #21 (commit `0ca4c7e`; 13 MySQL integration); Alembic check clean | — |
| WP-7 Plan A commission | A | `app/models/commission.py`, `app/services/commission/plan_a.py`, `app/services/commission/recovery_plan_a.py`, `alembic/versions/c1e2d3f4a5b6_*.py` | COMPLETE | 13 dedicated unit/integration tests passing (`test_wp7_plan_a_commission.py`); ₹700 net direct commission (₹750 gross, ₹35 op cost, ₹15 TDS) per eligible Billing ID; BR-X1 repeat purchases award ₹700 net to new code owner; unallocated/ineligible purchases recorded neutrally without wallet credit (BR-A7 neutrality); atomic commission + wallet ledger transaction with `PA-COMM:{billing_id}` idempotency; recovery sweeper and concurrency guards verified | BR-A7 (for unallocated ₹750 pool accounting only; live payouts gated by BR-T1) |
| WP-8 | Plan B commission & distributor controls | B | `app/models/commission.py`, `app/services/commission/plan_b.py`, `app/services/commission/recovery_plan_b.py`, `alembic/versions/d2e3f4a5b6c7_*.py` | COMPLETE | 20 dedicated unit/integration tests passing (`test_wp8_plan_b_commission.py`); ₹500 gross direct commission once per referee lifetime (`PB-DIRECT:{referee_id}`); ₹50 gross generation commission per eligible Billing ID (`PB-GEN:{billing_id}`); Op Cost 4.6667% + TDS 2.0% deductions verified (₹500→₹466.66 net, ₹50→₹46.67 net, 5-unit sample totals ₹700 net per BR-B2); non-retroactive later-order direct commission (BR-B1 Option A); distributor purchase requirement (BR-X2); distributor self-purchase exclusion (BR-B3); blocked/deactivated distributor exclusion (RG-14); B→B allowed & A→B forbidden (BR-X3); recovery sweeper and concurrency guards verified | — (BR-B1, BR-X2, BR-B2, BR-B3 resolved; live payouts gated by BR-T1) |
| WP-9 | Wallets & withdrawals | A+B | `app/models/wallet.py`, `app/models/enums.py`, `app/services/wallet_service.py`, `app/api/wallets.py`, `app/api/admin_dashboard.py`, `alembic/versions/e3f4a5b6c7d8_*.py` | COMPLETE | 22 dedicated unit/integration tests passing (`test_wp9_wallet_withdrawals.py`); full state machine (`REQUESTED`, `APPROVED`, `REJECTED`, `PAYOUT_PENDING`, `COMPLETED`); first withdrawal ≥ ₹750 threshold and subsequent > ₹0 threshold; full available balance liquidation; blocked distributor admin approval/rejection review workflow; wallet freeze/unfreeze with audit logging; continued commission accrual during freeze; pessimistic row locking and double-approval concurrency protection; sandbox simulated payouts with unique receipt references; dual-programme direct referral wallet coexistence; BR-A6 and BR-B2 compliance verified | — (BR-A6, BR-B2 resolved; live payouts gated by BR-T1) |
| WP-10 Plan A cashback engine | A | — | NOT_STARTED | All cashback rules confirmed (BR-A1..A5, BR-X1, BR-A6) | — (BR-A1, BR-A2, BR-A3, BR-A4 Option A, BR-A5 Option A, BR-X1 resolved; BR-A7 does NOT block cashback engine) |
| WP-11 Admin, reports, notifications | A+B | `backend/app/services/audit_service.py`, `backend/app/services/notification_service.py`, `backend/app/services/reports/`, `backend/app/api/admin_financial_settings.py`, `backend/app/api/admin_search.py` | IN_PROGRESS (Steps 1, 2, 3 Complete; Step 4 AD-06 & OR-13 Complete) | 72 dedicated unit/integration/API/report tests passing (`test_wp11_services.py`, `test_wp11_notification_integration.py`, `test_wp11_api.py`, `test_wp11_reports.py`, `test_wp11_financial_settings_api.py`, `test_wp11_admin_search.py`); 440 full suite tests passing; 6 notification workflows operational; Plan A PDF & Excel reports; Plan B Excel reports; Admin Financial Settings API (AD-06); Unified Admin Search API (OR-13) | OP-01, OP-02 resolved; courier delivery notification deferred pending physical integration (OP-02 / R-26) |
| WP-12 Frontend | A+B | — | NOT_STARTED | — | — |
| WP-13 Hardening & reconciliation | A+B | — | NOT_STARTED | — | — |
| WP-14 Deployment package | A+B | — | NOT_STARTED | — | OP-03 resolved (single Render service); explicit deployment authorization |
| Post-Demo Gate — Client Review & Approval | A+B | — | NOT_STARTED | — | Formal client demonstration, review and sign-off (R-29 / OP-13) |
| Post-Approval 1 — Razorpay Gateway Integration | A+B | — | POST_APPROVAL | — | Blocked until client sign-off; integration-ready architecture |
| Post-Approval 2 — Live SMS/OTP Provider Integration | A+B | — | POST_APPROVAL | — | Blocked until client sign-off; dev-only OTP used during demo |
| Post-Approval 3 — Production Security & Reconciliation Launch | A+B | — | POST_APPROVAL | — | Blocked until post-approval integrations and accountant audit (BR-T1) |

## Stage 0–1 report

- **Implemented:** no application code changed. Five analysis documents + this tracker added.
- **Changed files:** `docs/01_…` through `docs/05_…`, `docs/IMPLEMENTATION_PROGRESS.md`.
- **Tests executed:** dependency install, `compileall`, application import, one scripted end-to-end smoke flow against in-memory SQLite.
- **Passed:** compile; import (with CA path); smoke flow HTTP statuses (register, login, address, cart, checkout all 2xx).
- **Failed / findings:** import without `DB_SSL_CA` fails (S10); smoke flow financial output contradicts PRD (one ₹750 + one ₹250 for a 3-unit referred order; no Billing IDs).
- **Not run:** Alembic migrations against MySQL/TiDB; no existing automated tests to run.
- **Unresolved:** see `05_BUSINESS_RULE_DECISIONS.md` §E (all Plan A cashback rules BR-A1..A5, BR-X1, BR-A6 confirmed including BR-A4 Option A and BR-A5 Option A; remaining question: BR-A7 unallocated commission pool accounting only).

## WP-2 Completion Report

- **Implemented:** Decimal-safe money utility functions (`round_currency`, `paise_to_rupees`, `rupees_to_paise`), versioned `financial_settings` and `financial_settings_history` models, effective-dated settings service (`get_active_settings`, `create_initial_settings_if_none`), and seed initialization.
- **Changed files:** `backend/app/core/money.py`, `backend/app/models/financial_settings.py`, `backend/app/services/financial_settings.py`, `backend/app/core/seed.py`, `backend/tests/test_money.py`, `backend/tests/test_financial_settings.py`.
- **Tests executed & passed:** 140 unit tests (money rounding, models, service, audit history) and 10 MySQL integration tests passed in CI (Run #10, commit `81a4dc4`). Zero floats in money paths.

## WP-3 Completion Report

- **Implemented:** Dual-programme core models and additive Alembic migration `79b742f969d6`.
  - `Programme` enum (`PLAN_A`, `PLAN_B`, `LEGACY`) and `AccountStatus` enum (`ACTIVE`, `BLOCKED`, `DEACTIVATED`).
  - `users` table extended with `programme` (server default `'LEGACY'`) and `account_status` (server default `'ACTIVE'`) plus composite indexes (`idx_users_programme`, `idx_users_account_status`, `idx_users_prog_role`).
  - Immutable audit trail `account_status_history` with foreign key `RESTRICT` and `passive_deletes=True`.
  - Authoritative `referral_relationships` model with `uq_referral_rel_referee` (single-referrer constraint) and `chk_ref_rel_no_self` (no self-referral).
  - Permanent append-only `audit_logs` model with `BigInteger` primary key, nullable `actor_id` (RESTRICT), and metadata JSON text.
  - In-dashboard `notifications` model scoped by user and programme with CASCADE deletion on user.
  - Linear Alembic migration `79b742f969d6` (parent `2270de96fe73`) with safe reverse foreign-key downgrade order.
- **Changed files:** `backend/app/models/__init__.py`, `backend/app/models/enums.py`, `backend/app/models/user.py`, `backend/app/models/referral.py`, `backend/app/models/audit.py`, `backend/app/models/notification.py`, `backend/alembic/versions/79b742f969d6_wp3_migration_a_dual_programme_core.py`, `backend/tests/test_wp3_models.py`, `backend/tests/test_wp3_migration.py`, `backend/tests/test_financial_settings.py`.
- **Tests executed & passed:** Complete regression suite green in CI Run #12 (commit `65c3597`, Run ID `43575777998`): 160 unit tests passed, 11 MySQL integration tests passed (0 skipped, 0 failed, 171 total). SQLite and isolated MySQL 8 migration lifecycle tests verified upgrade → downgrade → re-upgrade. Alembic upgrade and `alembic check` passed with zero schema drift.
- **Operational warning:** OP-11 resolved — client confirmed clean database for new system; old test data is archived separately and will not be imported into live DB. Legacy test data must not be deleted or overwritten.

## Confirmed Project Decision: Client-Demo-First Strategy (R-29 / OP-13)

- **Immediate Goal:** Complete the entire Arya Global Digital / ShopEasy project for client demonstration and review.
- **Development & Demonstration Phase:**
  - Utilize the existing simulated payment provider (`SimulatedPaymentProvider`).
  - Do not integrate Razorpay or enable real payment collection.
  - Do not integrate a live SMS/OTP delivery provider yet (development OTP remains in effect).
  - Clearly identify simulated or development-only functionality in user interfaces and API responses.
  - Do not treat simulated payment success as an actual financial transaction.
- **Post-Client-Approval Integration Phase:**
  - After the client reviews the completed project and formally approves it in writing:
    1. Integrate Razorpay payment gateway.
    2. Implement real OTP delivery and verification using an approved SMS provider.
    3. Configure production credentials, secrets, webhook verification, and security controls.
    4. Perform end-to-end payment, authentication, failure, retry, reconciliation, and security testing.
- **Enforcement & Invariants:**
  - Real payments and live OTP services must remain disabled until post-approval integrations are completed, tested, and explicitly approved for production.
  - The software architecture must remain integration-ready so Razorpay and a live OTP provider can be added without unnecessarily redesigning checkout, authentication, or order processing.

## WP-6 Completion Report: Billing IDs, Fulfilment Pipeline & Recovery Worker

- **Status:** COMPLETE
- **Latest Commit:** `0ca4c7e691d8c2b1d48ee3262fc4beaf4f1ee7df` (`fix(wp6): register fulfilment sweep index in order metadata`).
- **CI Verification:** GitHub Actions Run #21 passed. Full backend regression: 283 passed, 13 MySQL integration passed (0 failed, 0 skipped).
- **Alembic Schema Check:** `alembic upgrade head` and `alembic check` clean with zero schema drift against isolated MySQL. Index `idx_orders_fulfilment_sweep` registered in `backend/app/models/order.py`.
- **Worker Implementation:** `FulfilmentRecoveryWorker` (`backend/app/services/fulfilment/recovery.py`) sweeps confirmed, payment-completed orders where `is_fulfilled == False`.
  - Operates in bounded batches (`FULFILMENT_RECOVERY_BATCH_SIZE`, default 50).
  - Short-lived read session discovers candidate IDs and closes before order processing begins.
  - Each candidate is processed in its own dedicated transaction via `FulfilmentOrchestrator.fulfil_order(order_id)`.
  - Failures are isolated per order; a failure does not abort the remaining candidates.
  - CLI entry point `python -m app.services.fulfilment.recovery` exits 0 on full success and 1 if any order failed or a sweep error occurred.
- **In-Process Scheduler Guard:**
  - `FulfilmentRecoveryScheduler` (`backend/app/services/fulfilment/scheduler.py`) provides an asyncio background loop.
  - Guard `_is_running` is strictly process-local in memory.
  - `FULFILMENT_RECOVERY_ENABLED=False` must remain the default on multi-worker web deployments (e.g. Uvicorn `--workers > 1`) to prevent multiple uncoordinated scheduler loops.
- **Production Deployment Standard (OP-03):**
  - Keep `FULFILMENT_RECOVERY_ENABLED=False` on the single Render Web Service.
  - Schedule recovery sweeps via an external Render Cron Job running `python -m app.services.fulfilment.recovery` at regular intervals (e.g. `*/5 * * * *`).
  - If multiple cron or worker processes ever execute concurrently, database row-level locking (`with_for_update()`) and schema unique constraints (`uq_billing_ids_item_unit`, `uq_billing_engine_claims_billing_id`) strictly prevent duplicate sequence numbers or claim allocations.

## WP-11 Step 1 & Step 2 Progress Report: Audit, Notifications & Admin Inspection APIs

- **Status:** IN_PROGRESS (Steps 1A, 1B, and 2 implemented & verified; Step 3 pending)
- **Core Services Foundation (Step 1A):**
  - `AuditService` (`backend/app/services/audit_service.py`): Immutable administrative audit logging reusing existing `AuditLog` model; caller-owned transaction semantics; recursive sensitive-data redaction covering all forbidden secret keys (`password`, `token`, `otp`, `secret`, `jwt`, `api_key`, `private_key`, `cookie`, `authorization`).
  - `NotificationService` (`backend/app/services/notification_service.py`): In-dashboard notification dispatch enforcing exact R-10 whitelist, programme scoping, duplicate suppression, and caller-owned transaction semantics.
- **Workflow Notifications Integrated (6 of 7 operational):**
  1. `PA_ADMIN_CASHBACK_CYCLE_COMPLETED`: Emitted to active administrators upon 16th contribution completing a cashback cycle.
  2. `PA_ADMIN_CASHBACK_WITHDRAWAL_REQUESTED`: Emitted to active administrators upon Plan A cashback withdrawal request (`WalletType.SEQUENTIAL_COMMISSION`).
  3. `PA_ADMIN_TRANSACTION_FAILURE`: Emitted to active administrators upon Plan A payment transaction failure or post-fulfilment dispatch error.
  4. `PB_ADMIN_BLOCKED_WITHDRAWAL_REQUESTED`: Emitted to active administrators upon blocked distributor withdrawal request.
  5. `PB_DISTRIBUTOR_WALLET_UNFROZEN`: Emitted to affected distributor upon wallet unfreeze.
  6. `PB_DISTRIBUTOR_WITHDRAWAL_SUCCESS`: Emitted to affected distributor upon completed payout.
- **Plan B Delivery Notification Status (Deferred pending courier integration):**
  - Event `PB_DISTRIBUTOR_ORDER_DELIVERED` helper `notify_order_delivered()` is safety-guarded with `verified_delivery: bool = False` by default.
  - Per confirmed decision OP-02 / R-26, courier integration will automatically update delivery status once a provider is integrated; no courier provider is invented at this stage.
  - Physical delivery notifications are **not** claimed as operational in production. Calling the helper without verified delivery evidence safely returns `None` and emits zero notifications.
- **Notification APIs (Step 2 Part A):**
  - `GET /api/v1/notifications`: List current user's notifications with pagination (`page`, `page_size` max 100) and filters (`programme`, `is_read`).
  - `GET /api/v1/notifications/{id}`: Retrieve single notification owned by current user (strict IDOR protection).
  - `POST /api/v1/notifications/{id}/read`: Mark single notification read with `read_at` timestamp.
  - `POST /api/v1/notifications/read-all`: Mark all caller-owned unread notifications as read.
- **Plan A Admin Inspection APIs (Step 2 Part B):**
  - `GET /api/v1/admin/plan-a/commissions`: Filtered and paginated Plan A direct commissions.
  - `GET /api/v1/admin/plan-a/queues` & `GET /api/v1/admin/plan-a/queues/{queue_id}/entries`: Queue and entry inspections.
  - `GET /api/v1/admin/plan-a/cycles` & `GET /api/v1/admin/plan-a/cycles/{cycle_id}/contributions`: Cycle and contribution audits.
  - `GET /api/v1/admin/plan-a/reserve` & `GET /api/v1/admin/plan-a/reserve/summary`: Unallocated company-owned cashback reserve inspection returning status label `"UNALLOCATED — COMPANY OWNED"` with automated `AuditLog` entry.
  - `GET /api/v1/admin/plan-a/customers/{customer_id}/cashback-summary`: Customer cashback progress with 48 bulbs calculation and automated `AuditLog` entry.
- **Plan B Admin Inspection APIs (Step 2 Part C):**
  - `GET /api/v1/admin/plan-b/distributors` & `GET /api/v1/admin/plan-b/distributors/{distributor_id}`: Distributor search, status, and active direct referee counts.
  - `GET /api/v1/admin/plan-b/distributors/{distributor_id}/referrals`: Referral relationships hierarchy.
  - `GET /api/v1/admin/plan-b/commissions/direct` & `GET /api/v1/admin/plan-b/commissions/generation`: Separate direct and generation commission audits.
  - `GET /api/v1/admin/plan-b/distributors/{distributor_id}/wallet`: Distributor wallet, transaction ledger, and withdrawal history with automated `AuditLog` entry.
  - `GET /api/v1/admin/plan-b/billing-ids`: Plan B Billing IDs inspection.
- **Verification & Corrective Fixes (Step 2):**
  - Resolved Plan A inspection audit log persistence (`db.commit()` in `get_reserve_summary` and `get_customer_cashback_summary`).
  - Added full authorization coverage for sub-resources `/queues/{id}/entries` and `/cycles/{id}/contributions` (HTTP 403).
  - Added positive admin tests for `GET /admin/plan-a/cycles`, `GET /admin/plan-a/cycles/{id}/contributions`, and `GET /admin/plan-a/reserve`.
  - Added unauthenticated rejection tests (HTTP 401) on admin routers.
  - Added notification read operation IDOR test (HTTP 404, unread state preserved).
  - Automated tests in `backend/tests/test_wp11_api.py` (23 passing tests).
  - Multi-package regression suite passing: 189 tests in 9.29s.

## WP-11 Step 3 Progress Report: Plan A & Plan B Report Generation & Export APIs

- **Status:** COMPLETE (Services, API Endpoints, Filters, Formats, and Automated Verification Tests implemented)
- **Architecture & Services (`backend/app/services/reports/`):**
  - `ExcelReportBuilder` (`excel_builder.py`): Styled workbook generator using `openpyxl` with navy blue headers, gridlines, auto-fitted columns, number formatting (`#,##0.00`), and bold summary totals.
  - `PDFReportBuilder` (`pdf_builder.py`): Document generator using `reportlab` with landscape and portrait layouts, dynamic two-pass page numbering (`NumberedCanvas`), confidentiality footers, wrapping table cells, and styled totals.
  - `PlanAReportService` (`plan_a_reports.py`): Queries authoritative database records for Plan A direct commissions, 16-contribution cashback cycles, unallocated company-owned reserve entries, and consolidated individual customer statements.
  - `PlanBReportService` (`plan_b_reports.py`): Queries authoritative database records for Plan B purchases, direct and generation commissions, multi-worksheet distributor reports, and distributor self-service statements in Excel (.xlsx).
- **Approved Report Matrix & API Endpoints:**
  - **Plan A Admin Reports:**
    - `GET /api/v1/admin/plan-a/reports/commissions`: Excel (.xlsx) and PDF formats. Traceable details: Billing ID, order ID, purchaser, referrer, referral code, gross ₹750, op cost ₹35, TDS ₹15, net ₹700, transaction reference, status, timestamp.
    - `GET /api/v1/admin/plan-a/reports/cashback`: Excel (.xlsx) and PDF formats. Includes contributions table (queue, root, contributing billing, contributor, recipient, cycle, progress, status, timestamp) and dedicated Company-Owned Unallocated Reserve table (`UNALLOCATED — COMPANY OWNED`).
    - `GET /api/v1/admin/plan-a/reports/customers/{customer_id}/statement`: Excel (.xlsx) and PDF formats. Admin-only consolidation of customer purchases, direct referral commissions, wallet transactions, cashback cycles, contributions, attributable reserve entries, and withdrawals. Customer self-service download strictly prohibited per confirmed rule R-07.
  - **Plan B Admin Reports (Excel .xlsx Only):**
    - `GET /api/v1/admin/plan-b/reports/purchases`: Excel (.xlsx) only. Columns: Customer name, mobile, referring distributor, order ID, billing ID, product name, quantity, purchase date, payment status, commission details.
    - `GET /api/v1/admin/plan-b/reports/commissions`: Excel (.xlsx) only. Columns: Distributor name, customer name, billing ID, order ID, commission type (`DIRECT` or `GENERATION`), gross, op cost, TDS, net, transaction ID, date, status.
    - `GET /api/v1/admin/plan-b/reports/distributors/{distributor_id}`: Excel (.xlsx) only. Comprehensive multi-sheet workbook covering Profile & Wallet Summary, Referrals Hierarchy, Direct Commissions, Generation Commissions, Withdrawals, and Wallet Freeze History.
  - **Plan B Distributor Self-Service (Excel .xlsx Only):**
    - `GET /api/v1/distributor/reports/commission-statement`: Excel (.xlsx) only. Scoped strictly to authenticated distributor ID (`current_user.id`). Enforces rule R-08 / PB-16: strictly rejects PDF download requests with HTTP 400 Bad Request.
- **Filters & Validation:**
  - Plan A: Date range (`start_date`, `end_date`), customer (`customer_id`), queue (`queue_id`), billing ID (`billing_id`).
  - Plan B Admin: Date range, customer name, distributor name, mobile number, billing ID, order ID, commission type.
  - Range validation: Start date after end date raises HTTP 400 Bad Request.
  - Memory safety: Query results bounded to maximum 10,000 rows.
- **Security & Authorization Controls:**
  - Admin-only authorization dependency `require_admin` on all admin report routes (HTTP 403 for customers / non-admins; HTTP 401 for unauthenticated requests).
  - Distributor dependency `require_distributor` on distributor self-service route (HTTP 403 for Plan A users / non-distributors).
  - Strict IDOR protection: Distributor statement uses token-derived user ID; user-supplied ID parameters cannot hijack other distributors' data.
  - Audit logging: All administrative report downloads record an `AuditLog` entry and commit within caller transaction semantics.
  - Read-only guarantees: Repeated report requests execute zero mutations on financial state (wallets, commissions, cashback, withdrawals, orders, billing IDs).
- **Test Evidence:**
  - Dedicated report test suite (`backend/tests/test_wp11_reports.py`): 12 passed in 0.89s.
  - Complete WP-11 suite (`test_wp11_services.py`, `test_wp11_notification_integration.py`, `test_wp11_api.py`, `test_wp11_reports.py`): 54 passed in 1.79s.
  - Multi-package regression suite (WP-3 through WP-11, 12 test files): 201 passed in 11.08s.
- **Known Limitations & Operational Notes:**
  - Event `PB_DISTRIBUTOR_ORDER_DELIVERED` remains deferred with safe guard `verified_delivery: bool = False` pending physical courier webhook integration (OP-02 / R-26).
  - Legacy test harness interactions (Alembic head assertion and SQLite `StaticPool` foreign key isolation) are fully corrected; 100% of all 444 backend test items execute cleanly without errors or failures.

## WP-11 Step 4 Progress Report: Admin Financial Configuration API (AD-06 / ED-02)

- **Status:** COMPLETE (Schemas, Endpoints, Prospective Validation, Audit Logging, and Automated Verification Tests implemented)
- **Architecture & Components:**
  - `FinancialSettingResponse`, `FinancialSettingListResponse`, `FinancialSettingUpdateRequest` (`backend/app/schemas/financial_settings.py`): Pydantic request/response contracts for versioned, effective-dated settings without exposing sensitive internal user data or secrets.
  - `admin_financial_settings.py` (`backend/app/api/admin_financial_settings.py`): Admin router mounted at `/api/v1/admin/financial-settings`.
- **Approved API Endpoints:**
  - `GET /api/v1/admin/financial-settings`: List settings with filtering by `programme`, `setting_key`, `is_active`, and historical resolution via `as_of`.
  - `POST /api/v1/admin/financial-settings`: Create or prospectively update settings reusing `FinancialSettingsService`. Enforces:
    - `require_admin` dependency (HTTP 401 unauthenticated, HTTP 403 non-admin/customer/distributor).
    - ED-02 prospective effective-date validation: past `effective_from` dates strictly rejected with HTTP 400 Bad Request.
    - Automatic monotonic version increment (`version = latest.version + 1`) and closure of previous version (`effective_to = eff_from`, `is_active = False`).
    - Mandatory audit logging: Every creation or update records `AuditService.record_action` (`CREATE_FINANCIAL_SETTING` or `UPDATE_FINANCIAL_SETTING`) containing caller admin identity, setting key, version, and change reason.
- **Test Evidence:**
  - Dedicated API test suite (`backend/tests/test_wp11_financial_settings_api.py`): 7 passed in 0.41s.
  - Complete WP-11 test suite (5 test files): 61 passed in 1.70s.
  - Financial settings service & model tests (2 test files): 36 passed in 0.60s.
  - Full backend test suite: 444 collected items, 429 passed, 15 skipped, 0 failed, 0 errors in 15.68s.

## WP-11 Step 4 Progress Report: Unified Admin Search (OR-13)

- **Status:** COMPLETE (Schemas, Endpoints, Exact-Match Logic, Audit Logging, and Automated Verification Tests implemented)
- **Architecture & Components:**
  - `AdminSearchResultItem`, `AdminSearchResponse` (`backend/app/schemas/admin_search.py`): Unified schema for search results supporting both Billing IDs and Orders, cleanly labelled with `PLAN_A` or `PLAN_B`.
  - `admin_search.py` (`backend/app/api/admin_search.py`): Admin router mounted at `/api/v1/admin/search`.
- **Approved API Endpoint:**
  - `GET /api/v1/admin/search?q={query}`: Exact-match lookup across Plan A and Plan B.
  - Enforces:
    - `require_admin` dependency (HTTP 401 unauthenticated, HTTP 403 customer/distributor).
    - Query bounds: length strictly bounded between 1 and 64 characters (empty or excessive length rejected with HTTP 400 Bad Request).
    - Exact match only: substring, partial, or wildcard matches return zero results.
    - Ambiguous query safety: queries matching both an Order ID and a Billing ID return both records safely with distinct `record_type` and `programme` identifiers.
    - Zero mutations: strictly read-only execution.
    - Mandatory audit logging: Every search query records an `AuditLog` entry (`action="ADMIN_UNIFIED_SEARCH"`).
- **Test Evidence:**
  - Dedicated search test suite (`backend/tests/test_wp11_admin_search.py`): 11 passed in 0.48s.
  - Complete WP-11 test suite (6 test files): 72 passed in 1.87s.
  - Full backend test suite: 455 collected items, 440 passed, 15 skipped, 0 failed, 0 errors in 15.21s.



