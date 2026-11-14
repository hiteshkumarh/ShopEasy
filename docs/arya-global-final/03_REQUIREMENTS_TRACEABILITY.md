# 03 — Requirements Traceability Matrix

Page numbers are PDF pages (approximate where a section spans pages). Priority: **P0** must-have for any release · **P1** required for go-live · **P2** important, may follow.
Status (current repo): FIT / PART / DEFECT / NONE / BLOCKED (see `02_PRD_GAP_ANALYSIS.md`). Clarification column references `05_BUSINESS_RULE_DECISIONS.md`.
Test IDs are placeholders that will map 1:1 to pytest node IDs in `backend/tests/` as they are written.

## Common platform (CM)

| Req ID | PRD § / page | Requirement | Prog | Pri | Status | Module | Tests | Acceptance criteria | Clarif. |
|---|---|---|---|---|---|---|---|---|---|
| CM-01 | §26.1 p.51 | One site, one admin system, both programmes, separate records | A+B | P0 | NONE | programmes, all | T-CM-01 | Every financial record carries programme; cross-programme queries isolated | R-01 |
| CM-02 | B §19.3 p.44 | Programme identifier on every relevant record; engines validate programme | A+B | P0 | NONE | db, commissions | T-CM-02 | Engine rejects Billing ID whose programme ≠ engine | — |
| CM-03 | A §15.1, B §20 | Decimal-safe money, no floats | A+B | P0 | PART | core/money | T-CM-03 | Static check: no `float` in money paths; rounding unit tests | ED-01 |
| CM-04 | A §3 p.3 | Deduction rates editable, full-precision, round once to paise | A(+B?) | P0 | NONE | financial_settings | T-CM-04 | Rate change affects only future rows; old rows unchanged | ED-02, BR-B2 |
| CM-05 | A §14, B §20.2 | Permanent audit trail for admin and financial status changes | A+B | P0 | NONE | audit | T-CM-05 | Each admin mutation writes one audit row; no delete API | — |
| CM-06 | A §14 | Never silently delete/overwrite financial history | A+B | P0 | PART | ledgers | T-CM-06 | No UPDATE/DELETE path on ledger tables (service + tests) | ED-06 |
| CM-07 | A §16, B §20.1 | Idempotency keys / unique refs on all financial ops | A+B | P0 | PART | all engines | T-CM-07 | Replay of any event creates zero new rows | ED-03 |
| CM-08 | A §16(1–2) | Server-side payment verification; never trust frontend | A+B | P0 | DEFECT | payments | T-CM-08 | Fulfilment only from verified payment event | OP-05 |
| CM-09 | B §8.2, §26.6 | Simulated payment, isolated, off in production | A+B | P0 | DEFECT | payments/simulated | T-CM-09 | `ENVIRONMENT=production` + simulator → startup refuses | — |
| CM-10 | A §18, B §19.4 | Hashing, RBAC, validation, CORS, HTTPS, secrets via env, rate limiting | A+B | P0 | PART | auth, core | T-SEC-* | Security test suite green; S1–S4 fixed | — |
| CM-11 | A §18 | Customers cannot modify balances / Billing IDs / ledgers | A+B | P0 | PART | api | T-SEC-IDOR | No write endpoint; IDOR tests | — |
| CM-12 | B §19.5 | Automatic DB backups + restore procedure | A+B | P1 | NONE | ops | T-OPS-BKP | Documented & rehearsed restore on non-prod | — |
| CM-13 | B §19.6 | Separate dev and prod; no test data in prod | A+B | P1 | PART | config, seed | T-OPS-ENV | Seed refuses sample data when production | — |
| CM-14 | A §15.2 | State survives restart/redeploy/crash/reconnect | A+B | P0 | PART | db | T-OPS-PERSIST | Restart mid-fulfilment → recovery completes exactly once | — |
| CM-15 | A §13.2, B §16 | In-dashboard notifications per programme rules | A+B | P1 | NONE | notifications | T-NOTIF-* | Only listed events notify | R-10 |

## Registration & referral (RG)

| Req ID | PRD § / page | Requirement | Prog | Pri | Status | Module | Tests | Acceptance criteria | Clarif. |
|---|---|---|---|---|---|---|---|---|---|
| RG-01 | B §2.1 p.24 | Select programme before account creation, with explanation | A+B | P0 | NONE | auth, frontend | T-RG-01 | Registration fails without programme | — |
| RG-02 | B §2.2–2.3 | Same mobile cannot register in both; programme permanent; admin cannot change | A+B | P0 | PART | users | T-RG-02 | Second registration with same phone (any programme) → 409; no programme-change API | R-04 |
| RG-03 | A §4.1(2), B §4.1 | Unique permanent referral code generated on account creation | A+B | P0 | PART | referrals | T-RG-03 | Code non-editable; collision retry tested | — |
| RG-04 | A §4.1(1), B §4.3 | Both programmes register without referral code | A+B | P0 | FIT* | auth | T-RG-04 | 201 with no referral code on registration for both Plan A and Plan B | — |
| RG-05 | A §4.1(5) | Invalid Plan A code → "Invalid Referral" | A | P0 | DEFECT | referrals | T-RG-05 | Exact message "Invalid Referral" returned on invalid code | — |
| RG-06 | A §4.1(7–8), B §4.4 | No referrer change; no self-referral | A+B | P0 | PART | referrals | T-RG-06 | Relationship permanent once bound on successful order; attempts to change rejected; self-referral rejected; DB unique constraint per referee | — |
| RG-07 | A §4.1(9–10) | Inactive (no purchase) Plan A customer's code rejected | A | P0 | PART | referrals | T-RG-07 | Code of customer with 0 paid Billing IDs rejected | — |
| RG-08 | B §4.2 p.26 | Allowed: A→A, B→A. Forbidden: A→B, B→B | A+B | P0 | NONE | referrals | T-RG-08 | Matrix of 4 directions tested | — |
| RG-09 | Confirmed decision | Referral code entered during checkout for both programmes; bound on successful order | A+B | P0 | PART | referrals, checkout | T-RG-09 | Code entered at checkout for Plan A and Plan B; validated per programme rules; bound only after successful order placement; single referrer per referee. Per BR-X1 (Option B), customer without an established referral relationship may enter a code on a later order; prior orders not retroactively attributed | — |
| RG-10 | B §4.3 p.26 | Plan B checkout validation: "Wrong Referral ID", distributor name preview, confirmation | B→A | P0 | PART | referrals, checkout | T-RG-10 | Preview returns distributor name only (no other PII); confirmed before order; "Wrong Referral ID" on invalid. Per BR-X2 (Option A), distributor must have completed a successful purchase to be eligible | — |
| RG-10A | Confirmed decision (BR-X2) | Inactive (no purchase) Plan B distributor's code rejected | B | P0 | NONE | referrals | T-RG-10A | Newly registered distributor's code is inactive/ineligible until successful product purchase confirmation; cannot establish relationships or earn commissions prior | — |
| RG-11 | B §4.4 | Relationship permanent after successful order | A+B | P0 | PART | referrals, checkout | T-RG-11 | Saved to referral_relationships only after successful order; no update path; audit row on creation | — |
| RG-12 | B §3.3 | Separate Plan B login → distributor dashboard | B | P1 | NONE | auth, frontend | T-RG-12 | Plan A credentials cannot log into Plan B portal and vice versa | — |
| RG-13 | B §3.1 | Registration fields: name, mobile, email, password ×2, address | A+B | P1 | PART | auth | T-RG-13 | Validation tests | OP-04 |
| RG-14 | B §11.1 | Blocked distributor: login & view yes; refer/earn no | B | P0 | DEFECT | users | T-RG-14 | Blocked code rejected; login 200 | — |
| RG-15 | B §2.3 | Wrong programme → new account with different number, nothing transferred | A+B | P2 | FIT* | users | T-RG-15 | No transfer API exists | — |

## Products, orders, Billing IDs (OR)

| Req ID | PRD § / page | Requirement | Prog | Pri | Status | Module | Tests | Acceptance criteria | Clarif. |
|---|---|---|---|---|---|---|---|---|---|
| OR-01 | A §3, B §7.2 | Power Bank price ₹3,999 fixed; name/desc/image/price immutable once configured | A+B | P0 | DEFECT | products | T-OR-01 | Update endpoints reject fixed fields | — |
| OR-02 | B §7.1 | Only admin adds products | A+B | P0 | FIT* | products | T-OR-02 | Customer → 403 | — |
| OR-03 | B §7.3 | Show In Stock / Out of Stock only; disable & reject order when out | A+B | P0 | PART | inventory | T-OR-03 | Public API never returns count; checkout rejects | — |
| OR-04 | B §22.2 | Stock replenishment procedure | A+B | P1 | BLOCKED | inventory | T-OR-04 | Per confirmed rule | OP-01 |
| OR-05 | A §5.1, B §8.3 | One unique Billing ID per purchased unit; qty N → N IDs | A+B | P0 | NONE | billing | T-OR-05 | qty 1/2/3/5 → 1/2/3/5 rows | OP-06 |
| OR-06 | A §5.3 | Uniqueness under concurrency; DB constraint | A+B | P0 | NONE | billing | T-OR-06 | 20 parallel purchases → no duplicates, contiguous counter | — |
| OR-07 | A §8.2, §26.4 | Failed/pending payment → no Billing ID, no commission, no cashback | A+B | P0 | NONE | payments | T-OR-07 | Zero rows after failure | — |
| OR-08 | A §5.3, §16 | Idempotent fulfilment; recovery after partial failure | A+B | P0 | NONE | fulfilment | T-OR-08 | Crash injected after payment → retry completes once | ED-04 |
| OR-09 | B §8.4 | Duplicate order submissions → no duplicates | A+B | P0 | PART | orders | T-OR-09 | Same idempotency key ×5 → one order | — |
| OR-10 | B §8.5 | Show "Orders cannot be cancelled, returned or replaced after successful payment." | A+B | P0 | NONE | frontend | T-UI-OR-10 | Exact text visible before Place Order | — |
| OR-11 | A §17 | No cancellation/refund workflow | A+B | P0 | FIT* | orders | T-OR-11 | No endpoint | R-06 |
| OR-12 | A §12.2 | Purchase history with Billing IDs, payment status | A+B | P0 | NONE | orders, frontend | T-OR-12 | Dashboard lists IDs | — |
| OR-13 | A §5.1(10), B §14.3 | Admin search by Billing ID / Order ID | A+B | P0 | NONE | admin | T-OR-13 | Exact match lookup | — |
| OR-14 | B §16.2(1), §22.3 | Delivery status; distributor notified on delivery | B | P2 | BLOCKED | orders, notifications | T-OR-14 | Per confirmed rule | OP-02 |

## Plan A (PA)

| Req ID | PRD § / page | Requirement | Prog | Pri | Status | Module | Tests | Acceptance criteria | Clarif. |
|---|---|---|---|---|---|---|---|---|---|
| PA-01 | A §6.1 p.6 | Per eligible Billing ID: gross ₹750, op-cost ₹35, TDS ₹15, net ₹700 | A | P0 | DEFECT | commissions/plan_a | T-PA-01 | Ledger row shows all four values | BR-T1 |
| PA-02 | A §6.2(1–3) | Separate commission per Billing ID, not per order | A | P0 | DEFECT | commissions/plan_a | T-PA-02 | F2 buys 3 → F1 has 3 × ₹700 rows | — |
| PA-03 | A §6.2(4–7) | Auto credit after payment + Billing ID; no admin approval | A | P0 | PART | fulfilment | T-PA-03 | No approval step | — |
| PA-04 | A §6.2(9–10), §21.2 | Unique ref; duplicate payment notifications → no duplicate commission | A | P0 | PART | commissions | T-PA-04 | Replay event ×3 → 3 rows total (not 9) | ED-03 |
| PA-05 | A §4.2 | No multi-generation commission under Plan A | A | P0 | FIT* | commissions | T-PA-05 | Grand-referrer receives nothing | — |
| PA-06 | A §7 | Separate commission wallet, balance, history | A | P0 | PART | wallets | T-PA-06 | Commission & cashback balances independent | — |
| PA-07 | A §7(4–10) | Commission withdrawal request, unique ref, no duplicates, independent of cashback | A | P0 | BLOCKED | withdrawals | T-PA-07 | Per BR-A6 | **BR-A6** |
| PA-08 | A §8.1–8.2 | ₹250 per eligible contribution, auto, no manual step | A | P0 | BLOCKED | cashback | T-PA-08 | Contribution row per eligible Billing ID | **BR-A1–A4** |
| PA-09 | A §8.3 | Cycle tracks count/16, balance, remaining, status | A | P0 | PART | cashback/cycles | T-PA-09 | 3 contributions → 3/16, ₹750, 13 left, ₹3,250 left, ACTIVE | — |
| PA-10 | A §8.3 | 16 × ₹250 = ₹4,000 → COMPLETED | A | P0 | PART | cashback/cycles | T-PA-10 | 16th sets COMPLETED; 17th goes to next recipient | — |
| PA-11 | A §9 | ≥2 independent queues; no cross-queue effects | A | P0 | DEFECT | cashback/queues | T-PA-11 | F1 & J1 scenario isolation | — |
| PA-12 | A §9.3 | Correct queue assignment for new Billing IDs | A | P0 | BLOCKED | cashback/queues | T-PA-12 | Per BR-A2 | **BR-A2** |
| PA-13 | A §9.4 | FIFO, persistent DB queue, WAITING/ACTIVE/COMPLETED, locking | A | P0 | DEFECT | cashback/queues | T-PA-13 | Concurrency test: 50 parallel buys, positions strictly FIFO | — |
| PA-14 | A §10.1–10.2 | 48 bulbs; 3 per contribution; 0→0, 3→9, 8→24, 16→48 | A | P0 | NONE | cashback API + UI | T-PA-14 | API returns bulbs_on computed server-side from count | — |
| PA-15 | A §10.3 | Green ON / grey OFF grid, equal size, subtle animation, responsive | A | P1 | NONE | frontend | T-UI-PA-15 | Visual test desktop/mobile | — |
| PA-16 | A §10.4 | Show current active recipient; move to next on completion; keep history | A | P0 | NONE | cashback API + UI | T-PA-16 | After 16th, dashboard shows next Billing ID | — |
| PA-17 | A §10.5 | Backend is source of truth; bulbs only visual | A | P0 | NONE | api | T-PA-17 | No endpoint accepts bulb counts | — |
| PA-18 | A §11 | Cashback withdrawal: only after completion, full ₹4,000, admin approve/reject + reason, balance retained on reject, one active request/cycle, history | A | P0 | NONE | withdrawals/cashback | T-PA-18 | State-machine tests | — |
| PA-19 | A §11(12–13), §13.2 | Admin notified on cycle completion, withdrawal request, important failures | A | P1 | NONE | notifications | T-PA-19 | One notification per event | — |
| PA-20 | A §12 | Customer dashboard (profile, purchases, referrals, wallet, cashback) | A | P0 | PART | frontend | T-UI-PA-20 | All fields present, backend-sourced | — |
| PA-21 | A §12.5 | No downloadable statements for Plan A customers | A | P1 | FIT* | frontend | T-PA-21 | No export endpoint for customer role | R-07 |
| PA-22 | A §2.3, §10 | Hide internal queue mechanics from customers | A | P1 | NONE | api/frontend | T-PA-22 | Customer API omits queue IDs/positions | — |
| PA-23 | §25.3 | Product-level commission history + account-level balance, no duplication | A | P0 | PART | commissions | T-PA-23 | Sum(ledger) == balance | — |
| PA-24 | A §3 | Allocation table per unit (1500/400/150/250/750/150/100 → 699) configurable; GST not deducted from 750 | A | P1 | DEFECT | financial_settings | T-PA-24 | Allocation snapshot per Billing ID sums correctly | BR-A7 |

## Plan B (PB)

| Req ID | PRD § / page | Requirement | Prog | Pri | Status | Module | Tests | Acceptance criteria | Clarif. |
|---|---|---|---|---|---|---|---|---|---|
| PB-01 | B §5.2, §26.3 | ₹500 once per referred customer after first qualifying purchase | B | P0 | NONE | commissions/plan_b | T-PB-01 | Exactly one row per referee lifetime (DB unique). Per BR-B1 (Option A), payable on the first successful order establishing relationship (even on later order; non-retroactive) | — |
| PB-02 | B §5.3 | ₹50 per eligible Billing ID | B | P0 | NONE | commissions/plan_b | T-PB-02 | 3 units → ₹150; later 2 units → +₹100 | — |
| PB-03 | B §5.4–5.6 | Combined example: first order 3 units → ₹650; later 2 → ₹100 | B | P0 | NONE | commissions/plan_b | T-PB-03 | Exact totals | — |
| PB-04 | B §5.7, §22.1 | No upstream/multi-level ₹50 | B | P0 | NONE | commissions/plan_b | T-PB-04 | Only direct distributor credited | R-05 |
| PB-05 | B §5.6, §26.4 | Never both Plan A and Plan B commission on one Billing ID | A+B | P0 | NONE | fulfilment | T-PB-05 | DB unique `(billing_id)` on commission "engine claim" | R-03 |
| PB-06 | B §6.3 | Commission record fields (txn, distributor, customer, order, Billing ID, type, amount, status, time) | B | P0 | NONE | commissions | T-PB-06 | Schema test | — |
| PB-07 | B §9 | Independent distributor wallet; totals; history | B | P0 | NONE | wallets | T-PB-07 | Balance == ledger sum | — |
| PB-08 | B §9.2 | Admin cannot add/deduct wallet money | B | P0 | NONE | admin | T-PB-08 | No endpoint; attempt → 404/405 | — |
| PB-09 | B §10.1–10.2 | First withdrawal ≥ ₹750; afterwards no minimum | B | P0 | NONE | withdrawals | T-PB-09 | 500/700/749 rejected, 750/1200 accepted; second at ₹50 accepted | — |
| PB-10 | B §10.3 | Full available balance only | B | P0 | NONE | withdrawals | T-PB-10 | Partial amount rejected | — |
| PB-11 | B §10.4–10.5 | Auto-processing for eligible active unfrozen; receipt with txn id/time/updated balance | B | P0 | NONE | withdrawals, payouts | T-PB-11 | Request→reserved→(sandbox) paid; receipt fields | BR-B2 |
| PB-12 | B §11.2 | Blocked distributor: request only; admin review; approve/reject; money stays on reject; admin notified | B | P0 | NONE | withdrawals | T-PB-12 | State-machine tests | — |
| PB-13 | B §11.3 | Reactivation; account status history | B | P1 | NONE | users | T-PB-13 | History row per change | — |
| PB-14 | B §12 | Freeze/unfreeze with reason; visible to distributor; commissions still accrue; no withdrawals; unfreeze notification; history | B | P0 | NONE | wallets | T-PB-14 | Frozen → withdraw 409; commission credited | — |
| PB-15 | B §13 | Distributor dashboard; **no** total referred count / combined units | B | P1 | NONE | frontend | T-UI-PB-15 | Negative assertions | OP-12 |
| PB-16 | B §13.7 | Distributor Excel statement, no PDF | B | P1 | NONE | reports | T-PB-16 | .xlsx opens; columns present | R-08 |
| PB-17 | B §14.1–14.5 | Admin distributor management, profile, hierarchy (read-only), status sections | B | P1 | NONE | admin | T-PB-17 | — | — |
| PB-18 | B §14.6 | Admin stats; **not** combined lifetime withdrawals; **not** daily/weekly/monthly ₹500/₹50 split | B | P1 | NONE | admin | T-PB-18 | Negative assertions | OP-12 |
| PB-19 | B §14.7–14.8 | Payout summary; Billing ID commission inspection | B | P1 | NONE | admin | T-PB-19 | — | — |
| PB-20 | B §15 | Excel reports (purchase, commission, individual) with filters | B | P1 | NONE | reports | T-PB-20 | Totals reconcile with ledger | — |
| PB-21 | B §16.1 | Do NOT send listed notifications | B | P1 | NONE | notifications | T-PB-21 | Negative assertions | R-10 |
| PB-22 | B §5.x, §3 | Plan B deductions | B | P0 | BLOCKED | commissions | T-PB-22 | Per BR-B2 | **BR-B2** |

## Admin common (AD)

| Req ID | PRD § / page | Requirement | Prog | Pri | Status | Module | Tests | Acceptance criteria | Clarif. |
|---|---|---|---|---|---|---|---|---|---|
| AD-01 | A §13 | One admin account, full access | A+B | P0 | FIT* | admin | T-AD-01 | Seeded from env | OP-10 |
| AD-02 | A §13.1(1–18) | Customer search (name, phone, Billing ID), histories, queues, contributions, cycles, bulbs, withdrawals | A | P1 | PART | admin | T-AD-02 | — | — |
| AD-03 | A §13.1(19–20), §14 | Individual customer report; separate commission & cashback reports, PDF + Excel, filters | A | P1 | NONE | reports | T-AD-03 | Totals reconcile | R-09 |
| AD-04 | A §13.3 | No referral edits; approval only for cashback withdrawal; no duplicate financial actions by repeated clicks | A+B | P0 | PART | admin | T-AD-04 | Double-approve → one payout | — |
| AD-05 | A §2.2 | Admin pages list (21 pages) | A+B | P1 | PART | frontend | T-UI-AD-05 | — | — |
| AD-06 | Master prompt §10(21) | Financial configuration screen (rates, effective date) | A+B | P1 | NONE | admin | T-AD-06 | Change audited, prospective | ED-02 |

## Frontend & deployment (FE / DP)

| Req ID | PRD § / page | Requirement | Prog | Pri | Status | Module | Tests | Acceptance criteria | Clarif. |
|---|---|---|---|---|---|---|---|---|---|
| FE-01 | A §2, B §18 | Original premium minimalist responsive design; no Apple assets | A+B | P1 | PART | frontend | T-UI-FE-01 | Lighthouse a11y ≥ 90; 375px layouts | — |
| FE-02 | B §17 | Home, Programme info, About, Contact (form), Terms, Privacy | A+B | P1 | NONE | frontend | T-UI-FE-02 | Pages exist | — |
| FE-03 | A §22(19–20) | No hard-coded catalogue/balances/IDs in frontend | A+B | P0 | DEFECT | frontend | T-UI-FE-03 | `data.js` removed | — |
| DP-01 | A §20.1 | Render web service on `$PORT`, env vars, TLS to TiDB, CORS | A+B | P1 | PART | ops | T-DP-01 | Health checks green in staging | OP-03 |
| DP-02 | A §20.3 | Controlled Alembic migrations; verify tables | A+B | P0 | PART | alembic | T-DP-02 | Upgrade/downgrade on TiDB-compatible DB in CI | — |
| DP-03 | A §20.4 | `.env.example` placeholders; no secrets in Git | A+B | P0 | FIT | repo | T-SEC-SECRETS | Secret scan clean | — |
| DP-04 | §26.5.6 | Final hosting topology | A+B | P1 | BLOCKED | ops | — | Client decision | **OP-03** |

`FIT*` = behaviour present by design/omission but no test exists yet; becomes FIT only once its test passes.
