# 02 — PRD Gap Analysis

Classification: **FIT** fully implemented & tested · **PART** partially implemented · **DEFECT** existing but defective vs PRD · **NONE** not implemented · **BLOCKED** blocked by clarification (see `05_BUSINESS_RULE_DECISIONS.md`).
No existing feature is FIT: the repository has no automated tests.

## 1. Platform & cross-cutting

| Capability | PRD ref | Status | Gap / required change |
|---|---|---|---|
| Programme concept (PLAN_A / PLAN_B) on every relevant record | B §19.3, §26.1 | NONE | New `programme` columns + service-level validation |
| Programme selection at registration, permanent | B §2.1, §2.3 | NONE | Registration UI/API, immutable programme |
| Phone unique across programmes | A §4.1, B §2.2 | PART | Global unique index exists; keep it and test cross-programme rejection |
| Decimal money | A §15.1, B §20 | PART | Already Decimal/NUMERIC; widen to DECIMAL(14,2); one rounding helper |
| Configurable financial settings & deduction rates | A §3, §24 | NONE | Effective-dated `financial_settings`; remove hard-coded CHECKs/constants |
| Audit log of admin & financial actions | A §14, B §20.2 | NONE | `audit_logs` append-only |
| Notifications (in-dashboard) | A §11, §13.2; B §16 | NONE | `notifications` with programme-specific triggers (R-10) |
| Payment provider abstraction + verified events | A §16, B §8.2 | DEFECT | Payment fused into checkout; `ENABLE_MOCK_PAYMENT` unused |
| Idempotent fulfilment & crash recovery | A §5.3, §16 | PART | Order idempotency exists; fulfilment recovery absent |
| Security hardening | A §18, B §19.4 | PART | S1–S10 in audit |
| Automated tests | A §21, B (throughout) | NONE | Full pytest suite + UI tests |
| Backups | B §19.5 | NONE | TiDB Cloud backup config + restore runbook |
| Dev/prod separation | B §19.6 | PART | Env flags exist but unsafe defaults (S1–S3) |

## 2. Registration, login, referral

| Capability | PRD ref | Status | Gap |
|---|---|---|---|
| Register without referral code | A §4.1(1), B §4.3 | FIT-untested | Customers and distributors in both programmes register without entering referral codes |
| Permanent unique referral code | A §4.1(2,6), B §4.1 | PART | Exists; needs per-programme prefix (e.g. `PA…`/`PB…`), copy button, tests |
| "Invalid Referral" (Plan A) / "Wrong Referral ID" (Plan B) messages | A §4.1(5), B §4.3 | DEFECT | Generic messages today; must display exact programme-specific error messages |
| Referral entry at checkout (both Plan A and Plan B) | A §4.1, B §4.3 | PART | Confirmed business rule: entered during checkout for both programmes (supersedes Plan A §4.1 registration timing); bound only after successful order; repeat-order question open (BR-X1) |
| Plan B code validated at checkout, show distributor name, confirm | B §4.3, §8.1 | PART | Checkout validation exists; distributor name preview (no other PII) and customer confirmation to implement |
| Allowed directions A→A, B→A only | B §4.2 | NONE | Direction check in referral service |
| Inactive Plan A referrer rejected | A §4.1(9–10) | PART | "Active" today = account active, not "has purchased" |
| Self-referral incl. other account/phone | A §4.1(8) | PART | Same-account blocked; cross-account detection needs a rule (same phone impossible; other heuristics undefined) |
| No referral change by customer/admin | A §4.2, B §4.4 | PART | No API exists to change; add DB/service immutability + tests |
| Separate login per programme, programme dashboards | B §2.2(4–5), §3.3 | NONE | Programme-aware login & routing |
| Blocked distributor can log in (read-only) | B §11.1 | DEFECT | `is_active=False` denies login entirely |
| Rate limiting | A §18(14) | NONE | Add |

## 3. Products, orders, Billing IDs

| Capability | PRD ref | Status | Gap |
|---|---|---|---|
| Power Bank ₹3,999 fixed price/name/description/image | B §7.2 | DEFECT | Admin can edit/delete price and details |
| Only admin adds products | B §7.1 | FIT-untested | — |
| Stock shown as In Stock / Out of Stock only; block order if none | B §7.3 | PART | Check stock count exposure in public API/UI |
| Stock replenishment | B §22.2 | BLOCKED (OP-01) | Append-only stock receipts proposed |
| Cart / checkout / no-cancel notice | B §8.1, §8.5 | PART | Notice text must match PRD exactly |
| One Billing ID per unit, backend-generated, unique, permanent | A §5, B §8.3 | NONE | `billing_ids` table + locked counter |
| No Billing ID for failed/pending payment | A §8.2, §26.4 | NONE | Requires payment state machine |
| Recovery without duplicates | A §5.3 | NONE | Idempotent fulfilment keyed by payment event |
| Admin Billing ID search | A §5.1(10), B §14.3 | NONE | |
| Purchase history with Billing IDs | A §12.2 | NONE | |
| Delivery status + distributor notification | B §16.2(1) | NONE/BLOCKED (OP-02) | |

## 4. Plan A engine

| Capability | PRD ref | Status | Gap |
|---|---|---|---|
| ₹750 gross / ₹35 / ₹15 / ₹700 net per Billing ID | A §6 | DEFECT | Old: ₹750 once per referee, no deductions |
| Commission auto-credited, no approval, unique ref, no duplicates | A §6.2 | PART | Auto & idempotent but per-referee |
| Separate commission wallet & history | A §7 | PART | Wallet exists (as "direct_referral") |
| Commission withdrawal request, unique ref, no duplicates, independent of cashback | A §7 | DEFECT/BLOCKED (BR-A6) | Instant payout; rule unclear |
| ₹250 contribution per eligible Billing ID | A §8 | DEFECT/BLOCKED | Per-order; allocation BR-A1..A5 |
| Multiple independent FIFO queues, Billing-ID recipients, WAITING/ACTIVE/COMPLETED | A §9 | DEFECT/BLOCKED | Single global per-customer queue |
| 16 × ₹250 = ₹4,000 cycle | A §8.1 | PART | Constant exists; per-customer lifetime only |
| 48-bulb indicator (3 per contribution), sequential display | A §10 | NONE | |
| Cashback withdrawal: full ₹4,000, admin approve/reject with reason, one active request per cycle, history | A §11 | NONE | |
| Admin notified: cycle completed, withdrawal requested, important failures | A §11(12–13), §13.2 | NONE | |
| Customer dashboard sections | A §12 | PART | Old-model dashboard |
| No customer downloadable statements | A §12.5 | FIT-untested | Ensure none added |

## 5. Plan B engine

| Capability | PRD ref | Status | Gap |
|---|---|---|---|
| ₹500 once per referred customer after first qualifying purchase | B §5.2, §26.3 | NONE (BR-B1) | |
| ₹50 per eligible Billing ID to direct distributor | B §5.3 | NONE | |
| Commission record fields | B §6.3 | NONE | |
| Distributor wallet (earned/direct/generation/withdrawn/available) | B §9 | NONE | |
| No admin manual credit/debit | B §9.2 | NONE | Enforce by absence of API + tests |
| First withdrawal ≥ ₹750, then no minimum, full balance only | B §10 | NONE | |
| Auto withdrawal for eligible active unfrozen wallet | B §10.4 | NONE | Simulated payout states |
| Withdrawal receipt | B §10.5 | NONE | |
| Block/deactivate/reactivate + status history | B §11 | NONE | |
| Blocked distributor withdrawal by request + admin review + admin notification | B §11.2 | NONE | |
| Wallet freeze/unfreeze with reason, visibility, history, unfreeze notification | B §12 | NONE | |
| Distributor dashboard incl. negative requirements | B §13 | NONE | |
| Distributor Excel statement (no PDF) | B §13.7 | NONE | |
| Admin distributor management, profile, hierarchy, sections, stats, payout summary, Billing-ID inspection | B §14 | NONE | |
| Excel reports with filters | B §15 | NONE | |

## 6. Admin portal (common)

| Capability | PRD ref | Status |
|---|---|---|
| Dashboard / customers / orders / products | A §13, B §14 | PART |
| Search by name / phone / Billing ID / order ID | A §13.1, B §14.3 | PART (name/phone partial) |
| Commission, cashback, queues, withdrawals views | A §13.1 | NONE |
| PDF & Excel exports | A §14 | NONE |
| Financial configuration UI | A §3 | NONE |
| Audit log viewer | A §14 | NONE |
| Restrictions: no referral edits, no balance edits, no duplicate financial actions | A §13.3, B §9.2 | PART (by omission; untested) |

## 7. Frontend / UX

| Capability | PRD ref | Status |
|---|---|---|
| Premium minimalist original design, responsive | A §2, B §18 | PART (clean ShopEasy CSS; generic multi-category store, ShopEasy branding) |
| Pages: Home, products, details, register (programme select), login, cart/checkout, payment status, dashboards, referral, wallets, cashback, withdrawals, admin pages | A §2.2, B §17 | PART |
| About, Contact (form), Terms, Privacy, Programme info | B §17 | NONE |
| Hard-coded sample catalogue (`js/data.js`) | A §22(19–20) | DEFECT — must be removed |

## 8. Deployment

| Capability | PRD ref | Status |
|---|---|---|
| Render web service, `$PORT`, env vars, TLS to TiDB | A §20 | PART (works as single service) |
| Controlled Alembic migrations | A §20.3 | PART (manual, undocumented) |
| Topology decision | §26.5.6 | BLOCKED (OP-03) |
| `.env.example` placeholders only | A §20.4 | FIT |
