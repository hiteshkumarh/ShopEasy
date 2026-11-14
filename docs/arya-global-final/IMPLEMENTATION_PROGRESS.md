# Implementation Progress

Branch: `feature/arya-dual-plan-referral-platform` · Last updated: 2026-11-14

| Task | Programme | Files | Status | Tests | Blocker |
|---|---|---|---|---|---|
| Stage 0 — Repository audit & baseline | A+B | `docs/01_EXISTING_SYSTEM_AUDIT.md` | COMPLETE | Compile ✔, import ✔ (with CA path), scripted smoke on SQLite ✔ (scratch, not committed) | Alembic on MySQL/TiDB not run (no local DB; Docker daemon stopped) |
| Stage 1 — PRD gap analysis | A+B | `docs/02_PRD_GAP_ANALYSIS.md` | COMPLETE | n/a (documentation) | — |
| Stage 1 — Traceability matrix | A+B | `docs/03_REQUIREMENTS_TRACEABILITY.md` | COMPLETE | Test IDs reserved | — |
| Stage 1 — Roadmap, architecture, test strategy, risks | A+B | `docs/04_IMPLEMENTATION_ROADMAP.md` | COMPLETE | n/a | — |
| Stage 1 — Business-rule conflict register | A+B | `docs/05_BUSINESS_RULE_DECISIONS.md` | COMPLETE | n/a | 14 client questions outstanding |
| WP-0 Safe config defaults, lazy engine | A+B | `app/core/config.py`, `app/core/database.py` | COMPLETE | 22 unit tests passing | — |
| WP-1 Test harness + MySQL CI | A+B | `backend/tests/`, CI | COMPLETE | 30 MySQL config + 7 MySQL integration tests in CI | — |
| WP-2 Money utils & financial settings | A+B | `app/core/money.py`, `app/models/financial_settings.py`, `app/services/financial_settings.py`, `app/core/seed.py` | COMPLETE | 140 unit tests + 10 MySQL integration tests passed in CI | — |
| WP-3 Additive migration (programme, status, referrals, audit, notifications) | A+B | `app/models/`, `alembic/versions/79b742f969d6_*.py` | COMPLETE | 160 unit + 11 MySQL integration in CI Run #12 (171 passed, 0 skipped); SQLite & isolated MySQL lifecycle tests; Alembic check clean | OP-11 before running on real data |
| WP-4 Programme registration & referral rules | A+B | — | NOT_STARTED | — | — (referral timing confirmed at checkout; BR-X1 confirmed Option B: later-order binding allowed) |
| WP-5 Payment abstraction | A+B | — | NOT_STARTED | — | — |
| WP-6 Billing IDs + fulfilment + recovery | A+B | — | NOT_STARTED | — | — |
| WP-7 Plan A commission | A | — | NOT_STARTED | — | — |
| WP-8 | Plan B commission & distributor controls | B | — | NOT_STARTED | — | BR-B2 (BR-B1 resolved: Option A; BR-X2 resolved: Option A) |
| WP-9 Wallets & withdrawals | A+B | — | NOT_STARTED | — | BR-A6, BR-B2 |
| WP-10 Plan A cashback engine | A | — | BLOCKED (production) | — | BR-A1–A5, BR-A7 |
| WP-11 Admin, reports, notifications | A+B | — | NOT_STARTED | — | — |
| WP-12 Frontend | A+B | — | NOT_STARTED | — | — |
| WP-13 Hardening & reconciliation | A+B | — | NOT_STARTED | — | — |
| WP-14 Deployment package | A+B | — | NOT_STARTED | — | OP-03, explicit approval |

## Stage 0–1 report

- **Implemented:** no application code changed. Five analysis documents + this tracker added.
- **Changed files:** `docs/01_…` through `docs/05_…`, `docs/IMPLEMENTATION_PROGRESS.md`.
- **Tests executed:** dependency install, `compileall`, application import, one scripted end-to-end smoke flow against in-memory SQLite.
- **Passed:** compile; import (with CA path); smoke flow HTTP statuses (register, login, address, cart, checkout all 2xx).
- **Failed / findings:** import without `DB_SSL_CA` fails (S10); smoke flow financial output contradicts PRD (one ₹750 + one ₹250 for a 3-unit referred order; no Billing IDs).
- **Not run:** Alembic migrations against MySQL/TiDB; no existing automated tests to run.
- **Unresolved:** see `05_BUSINESS_RULE_DECISIONS.md` §E (14 questions).

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
- **Operational warning:** OP-11 remains active — migration `79b742f969d6` must not be executed against real production data until client sign-off on legacy data treatment is provided.
