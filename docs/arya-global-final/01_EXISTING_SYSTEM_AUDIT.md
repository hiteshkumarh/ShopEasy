# 01 — Existing System Audit (ShopEasy → Arya Global Digital)

| Item | Value |
|---|---|
| Audit date | 2026-11-13 |
| Repository | `github.com/hiteshkumarh/ShopEasy` (cloned into `D:\HiteshKumar`) |
| Base commit | `59d1783` (`main`) |
| Working branch | `feature/arya-dual-plan-referral-platform` (created from `main`; no uncommitted changes existed) |
| Primary spec | `PLAN A & PLAN B in detail.pdf` (52 pages; Plan A §1–25, Plan B §1–23, Final Clarifications §26) |
| Auditor scope | Static code review, dependency install, compile/import checks, one scripted end-to-end smoke run against in-memory SQLite. **No production system, database or deployment was touched.** |

> Note on setup: the session working folder was empty. The deployed storefront (`shopeasy-jhls.onrender.com`) links to the GitHub repository above, which was cloned read-only. If a different or newer source tree exists (e.g. unpushed work), this audit must be re-run against it.

---

## 1. Executive summary

ShopEasy is a **real, database-backed FastAPI + vanilla-JS application** — not a frontend mock. Its backend is reasonably well engineered (bcrypt, JWT, row locks, idempotency keys, ledger table, composite FKs). However, it implements an **older, different referral business model** that does not match the Arya PRD:

| Area | ShopEasy today | Arya PRD requires |
|---|---|---|
| Programmes | One (no programme concept) | Plan A **and** Plan B, separated in every record |
| Billing IDs | **Do not exist** | One permanent, unique Billing ID per purchased unit |
| Referral reward | ₹750 **once per referee**, on first order, **no deductions** | Plan A: ₹750 gross → ₹35 op-cost → ₹15 TDS → **₹700 net per Billing ID** |
| "Sequential" ₹250 | ₹250 **per order** to one **global** active beneficiary; one lifetime cycle per customer | ₹250 **per eligible Billing ID** into **multiple independent FIFO queues** whose recipients are **Billing IDs**, not customers (allocation rules still unconfirmed) |
| Cashback withdrawal | Instant simulated payout, no admin approval | Full ₹4,000 only, **admin approval/rejection with reason** |
| Plan B (₹500 once + ₹50/Billing ID, distributor wallet, freeze/block) | Not implemented | Required |
| Admin notifications, audit log, reports (PDF/Excel) | Not implemented | Required |
| Automated tests | **None** | Comprehensive |

**Baseline evidence (smoke run, SQLite, scratch only):** F1 buys 2 Power Banks; F2 buys 3 Power Banks using F1's code. Result: F1 receives **one ₹750.00** referral credit and **one ₹250.00** sequential credit; no Billing IDs exist. PRD expects F1 to receive **three ₹700.00 net** commission transactions linked to Billing IDs 203/204/205 (and cashback contributions per the yet-to-be-confirmed queue rule). The core earning engine is therefore classified **Existing but defective (against PRD)** and must be replaced, not patched.

Reusable with modification: auth/security primitives, user/address/cart/order/product scaffolding, wallet-ledger pattern, locking pattern, Docker/Render packaging, frontend shell and CSS system.

---

## 2. Technology stack (as found)

| Layer | Technology | Notes |
|---|---|---|
| Backend | Python 3.12, FastAPI (resolved 0.162.x), Uvicorn | `backend/app` |
| ORM / migrations | SQLAlchemy 2.x, Alembic (3 revisions) | `backend/alembic/versions` |
| Validation | Pydantic v2 | `backend/app/schemas` |
| DB driver | PyMySQL + `cryptography`, TLS with `ssl_verify_cert` + `ssl_verify_identity` | `app/core/database.py` |
| Database | MySQL 8 (docker-compose) / TiDB Cloud (Render) | `DB_SSL_CA` mandatory at import |
| Auth | bcrypt (12 rounds), PyJWT HS256 access tokens, HMAC-SHA256 hashed OTPs, admin password+OTP MFA | `app/core/security.py`, `app/services/otp_service.py` |
| Frontend | Static HTML/CSS/vanilla JS, served by FastAPI `StaticFiles` at `/` | `frontend/` (same-origin) |
| Packaging | Single `Dockerfile` (backend + frontend in one image), `docker-entrypoint.sh` runs Uvicorn on `$PORT` | Migrations/seed are **manual** |
| Tests | None (no `tests/`, no pytest config) | |
| CI | None | |

Dependencies are range-pinned (`>=x,<y`), not locked. A fresh install today resolved FastAPI 0.162.5, SQLAlchemy 2.1.8, Pydantic 2.14.3, bcrypt 5.0.0, PyJWT 2.15.1. **Recommendation:** add a lock file (`requirements.lock` / `pip-tools`).

---

## 3. Repository structure

```text
backend/
  alembic/versions/   ed2396d847bc_initial_schema, c895961fa0f1_cart_items, 71dba0e1425f_otp_varchar_64
  app/api/            addresses, admin_auth, admin_dashboard, admin_products, cart, customer_auth,
                      dashboard, dependencies, identity, orders, products, referrals, wallets
  app/core/           config, database, security, seed, cleanup_test_data
  app/models/         user(User, OTP, Address), product, cart, order(Order, OrderItem, OrderAllocation),
                      queue(BeneficiaryQueue, CommissionCycle, QueueControl),
                      commission(SequentialCommission, ReferralCommission),
                      wallet(Wallet, WalletTransaction, Withdrawal), enums
  app/schemas/        Pydantic request/response models
  app/services/       allocation, checkout, earning_engine, otp_service, queue_service, referral, wallet_service
frontend/             index, products, product-details, cart, checkout, login, dashboard, orders, profile
frontend/admin/       login, dashboard, products, product-form, orders, customers
docs/                 PRD.md, ShopEasy_PRD.md, architeture.md, design.md, memory.md, rules.md, tasks.md (ShopEasy-era)
```

37 OpenAPI paths are registered (customer auth ×7, admin auth ×5, identity, products ×2, admin products ×5, admin dashboard ×4, cart ×5, addresses ×4, orders ×3, wallets ×4, dashboard ×2, referrals ×1, health ×2).

---

## 4. Data model (16 tables)

`users, otps, addresses, products, cart_items, orders, order_items, order_allocations, beneficiary_queue, commission_cycles, queue_control, referral_commissions, sequential_commissions, wallets, wallet_transactions, withdrawals`

Strengths:
- Money stored as `NUMERIC(10,2)`; Python uses `Decimal`.
- Unique constraints on phone, referral code, order number, `(user_id, idempotency_key)` for orders and withdrawals, and `wallet_transactions.idempotency_key`.
- Composite FKs enforce ownership (e.g. wallet transaction ↔ wallet ↔ user ↔ wallet type).
- Ledger rows carry `balance_after`.

Weaknesses vs PRD:
- No `programme` column anywhere; no `billing_ids`; no per-unit records.
- `referral_commissions` has `UNIQUE(referee_id)` and `CHECK(amount = 750.00)` — hard-codes the old one-time rule and **prevents** per-Billing-ID commission.
- `commission_cycles` has `UNIQUE(beneficiary_id)` + `CHECK(cycle_number = 1)` — one lifetime cycle per customer; PRD needs one cycle **per recipient Billing ID**.
- `beneficiary_queue` / `queue_control` model **one global queue** with a singleton active row; PRD needs **many independent queues**.
- `withdrawals.status` only `completed|failed`; no request/approval/payout lifecycle, no rejection reason.
- `order_allocations` CHECKs hard-code ₹1,500/₹400/₹150/₹150/₹100 and `direct_referral_reward IN (0, 750)` — PRD requires these to be **configurable**.
- No audit log, notification, account-status history, wallet-freeze history, financial-settings tables.
- `users.is_active` is the only status flag (no blocked/deactivated distinction).

### 4.1 TiDB compatibility findings (must be verified on the chosen TiDB Cloud tier)

| Finding | Impact | Action |
|---|---|---|
| TiDB only enforces `CHECK` constraints when `tidb_enable_check_constraint = ON` (introduced v7.2; default OFF). | All financial invariants expressed as `CHECK` (amounts, counts, balances ≥ 0) may be **silently unenforced** in production. | Never rely on `CHECK` alone; enforce in service layer + tests; optionally enable the variable after verification. |
| Foreign-key enforcement in TiDB arrived in v6.6 (experimental) and is GA only in later releases. | Composite FKs may be ignored on older clusters. | Verify cluster version; service-layer ownership checks remain mandatory. |
| `AUTO_INCREMENT` values in TiDB are unique but **not guaranteed monotonic** across TiDB server nodes (per-node ID caching) unless `AUTO_ID_CACHE=1`. | FIFO ordering or "Billing ID 201, 202…" must **not** be derived from `id` order. | Allocate Billing ID numbers and queue positions from a locked counter row (or TiDB `SEQUENCE`) inside the transaction. |
| Pessimistic locking (`SELECT … FOR UPDATE`) is the default TiDB transaction mode since v3.0.8. | Existing locking pattern works. | Keep; add lock-ordering rules to avoid deadlocks. |
| Stored generated columns + unique index (used for "single active" flags). | Supported by TiDB. | Retain pattern where useful; verify with migration test. |

---

## 5. Authentication & authorisation

| Control | Status |
|---|---|
| Password hashing | bcrypt, 12 rounds — **OK** |
| Customer login | Phone+password or phone+OTP — OK |
| Admin login | Pre-provisioned (seed from env), password + OTP MFA — OK |
| JWT | HS256, 24 h expiry, `role` claim re-checked against DB — OK |
| Role guards | `require_customer`, `require_admin` dependencies — OK |
| Programme-aware authorisation | **Missing** (no programme concept) |
| Rate limiting | **Missing** on login/OTP endpoints |
| Token storage | `localStorage` in browser — XSS-exposed (see §9) |
| Account status | `is_active` blocks login entirely — conflicts with Plan B "blocked distributor can still log in" |

---

## 6. Purchase flow (as found)

`POST /api/v1/orders/checkout` → `services/checkout.execute_checkout`:
1. Idempotency lookup on `(user_id, idempotency_key)`.
2. Address ownership check; cart load; `SELECT … FOR UPDATE` on each product; stock decrement.
3. Optional referral code validated **at checkout**; binds `referred_by_id` on first successful order.
4. **Payment is always simulated as successful** inside the same transaction (`SIM-…` reference). `ENABLE_MOCK_PAYMENT` is defined in config but **never read** — there is no payment abstraction and no way to represent pending/failed payments.
5. Locks the global `queue_control` row (serialises **all** checkouts system-wide).
6. Writes `order_allocations` snapshot; credits ₹750 one-time referral and/or one ₹250 sequential commission per order.
7. Clears cart; commits.

Single-transaction design is atomic (good) but there is no recovery path for "payment succeeded, downstream failed", because payment and fulfilment are not separated.

Power Bank detection uses `is_power_bank OR product_code == 'PB-3999' OR 'power bank' in name.lower()` — name-substring matching is fragile.

---

## 7. Referral, wallet & withdrawal (as found)

- Referral codes: `REF` + 6 random chars, uniqueness checked with retry; permanent. Self-referral blocked; admin codes rejected; inactive referrers rejected.
- **Referral is bound at checkout**, matching Plan B §4.3 but **not** Plan A §4.1 (registration).
- Two wallets per user: `direct_referral`, `sequential_commission`; credits via `credit_wallet()` with idempotency key and row lock — a sound pattern to reuse.
- Withdrawal: full balance only; direct-referral wallet needs ≥ ₹750; sequential wallet needs a 16/16 cycle; **executed instantly as COMPLETED** — no request, approval, payout or reconciliation state.

---

## 8. Admin portal (as found)

Backend: dashboard stats (products, customers, orders, revenue), order list, customer list, one admin action endpoint, product CRUD + base64 image upload.
Frontend: login, dashboard, products, product form, orders, customers.

Missing vs PRD: Billing ID search, commission/cashback/queue views, withdrawal approvals, Plan B distributor management, block/freeze, notifications, audit log, financial configuration, PDF/Excel reports, referral hierarchy view.

Conflicts: admin can **edit product price and delete products** — Plan B §7.2 says price/name/description/image are fixed and not admin-editable.

---

## 9. Security findings

| # | Severity | Finding | Location |
|---|---|---|---|
| S1 | **High** | `ENVIRONMENT` defaults to `development`. If unset on Render, OTP generation returns the fixed `DEV_OTP_CODE` (`123456`) **and** the OTP is echoed in API responses → full account takeover via OTP login. | `core/config.py`, `services/otp_service.py`, `api/customer_auth.py`, `api/admin_auth.py` |
| S2 | **High** | `SECRET_KEY` defaults to a public placeholder with no production guard → forgeable JWTs if unset. | `core/config.py` |
| S3 | Medium | `DEBUG` defaults to `True` → SQLAlchemy `echo=True` logs every SQL statement (incl. personal data) in production if unset. | `core/config.py`, `core/database.py` |
| S4 | Medium | No rate limiting / lockout on password login, OTP request, OTP verify. | `api/customer_auth.py`, `api/admin_auth.py` |
| S5 | Medium | Access tokens in `localStorage`; 61 `innerHTML` usages in frontend JS → any XSS = token theft. Needs output-encoding review / CSP. | `frontend/js/*` |
| S6 | Medium | Image upload validates extension only, not content/magic bytes; files written under the statically served `frontend/uploads`. On Render the filesystem is **ephemeral** → uploads lost on redeploy. | `api/admin_products.py` |
| S7 | Medium | Financial invariants rely on `CHECK` constraints that TiDB may not enforce (§4.1). | models |
| S8 | Low | No security headers (CSP, HSTS, X-Frame-Options, Referrer-Policy). | `main.py` |
| S9 | Low | `cleanup_test_data.py` can hard-delete orders, wallets and ledger rows (dry-run default, phone-scoped). Must never be runnable against production. | `core/cleanup_test_data.py` |
| S10 | Low | Database import-time engine creation requires `DB_SSL_CA` file → app cannot be imported for tests without a CA file. | `core/database.py` |
| S11 | Info | No committed secrets found; `.gitignore` excludes `.env`, `*.pem`, `*.key`. `.env.example` files contain placeholders only. | — |

---

## 10. Deployment (as found)

- One Docker image serves API + static frontend (same origin, CORS empty by default) → **single Render Web Service**.
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Migrations and seeding are manual.
- Health: `/api/health`, `/api/health/db` (DB check returns DB name — minor info disclosure).
- No `render.yaml`, no CI, no backup procedure documented.

---

## 11. Frontend

- Generic multi-category "ShopEasy" storefront (Electronics/Fashion/Beauty…) with `js/data.js` **hard-coded sample catalogue** (12 products with fake ratings/stock) still referenced by product pages. Catalogue must become backend-driven Power Bank catalogue.
- Clean CSS component system (`components.css`, `style.css`) — reusable as the base for the Arya design.
- Customer dashboard shows the old two-wallet model; no Billing IDs, no 48-bulb indicator, no programme split.
- Branding: "ShopEasy" throughout; must become Arya Global Digital (original design, no Apple assets).

---

## 12. Baseline checks executed

| Check | Result |
|---|---|
| `git status` on clone | Clean; no uncommitted work to preserve |
| Branch created | `feature/arya-dual-plan-referral-platform` |
| `pip install -r requirements.txt` into `backend/.venv` | OK |
| `python -m compileall app alembic` | OK |
| `import app.main` without `DB_SSL_CA` | **Fails** (`ValueError: DB_SSL_CA must be configured`) — finding S10 |
| `import app.main` with placeholder CA path | OK; 16 tables in metadata; 37 API paths |
| Existing automated tests | None to run |
| Scripted E2E smoke (SQLite, scratch, not committed) | Registration, login, address, cart, checkout all return 2xx. Financial result demonstrates PRD mismatch (one ₹750 + one ₹250 for a 3-unit referred order; no Billing IDs). |
| Alembic migration against MySQL/TiDB | **Not run** — no local MySQL; Docker daemon not running. Must be done before Stage 3 sign-off. |
| Deployed demo | Fetched `/` and `/admin/dashboard.html` read-only (HTTP 200). No logins or writes performed. |

---

## 13. Feature classification (summary)

| Feature | Classification |
|---|---|
| Customer registration / login / OTP / password reset | Partially implemented (no programme selection; dev-OTP default risk) |
| Admin login with MFA | Fully implemented, **not tested** |
| Unique phone | Implemented globally — PRD needs uniqueness *across* programmes (same phone cannot join both) → compatible |
| Permanent referral codes | Implemented, untested |
| Referral binding | Existing but defective for Plan A (checkout instead of registration); matches Plan B timing |
| Product catalogue / admin CRUD | Partially implemented; defective vs fixed-product rule |
| Cart / checkout / orders | Partially implemented (simulated payment fused into checkout) |
| Billing IDs | Not implemented |
| Plan A commission (₹700 net per Billing ID) | Existing but defective |
| Plan A cashback queues | Existing but defective (single global queue, per-order) + **Blocked by clarification** (BR-A1…A4) |
| 48-bulb indicator | Not implemented |
| Cashback withdrawal approval | Not implemented |
| Plan A commission withdrawal | Existing but defective (rules differ, no request lifecycle) |
| Plan B (all) | Not implemented |
| Notifications / audit log / reports | Not implemented |
| Financial configuration | Not implemented (hard-coded constants and CHECKs) |
| Automated tests | Not implemented |
| Render + TiDB deployment | Partially implemented (single service; manual migrations) |

None of the existing features qualify as "Fully implemented and tested" because there is no test suite.
