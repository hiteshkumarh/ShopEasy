# 05 — Business Rule Decisions & Conflict Register

Source: `PLAN A & PLAN B in detail.pdf`. Page numbers refer to the PDF (52 pages).
Precedence: **§26 Final Clarifications** > Plan B > Plan A where they explicitly conflict; otherwise each programme's own section governs its own records.

Status legend:
- **RESOLVED-PRD** — the PRD itself resolves it (cited).
- **PROPOSED** — engineering default that does not change any payout; can proceed, client may override.
- **OPEN-BLOCKING** — affects money or referral binding; the corresponding feature ships **disabled/blocked** until written confirmation.
- **OPEN-NONBLOCKING** — operational/UX question; a safe placeholder is used.

---

## A. Conflicts resolved by the PRD

| ID | Conflict | Resolution | Source |
|---|---|---|---|
| R-01 | Plan A p.1–2: "implement Plan A only; Plan B must not be implemented" | Superseded: both programmes required on one site with one admin system | §26.1 (p.51) |
| R-02 | Plan A cashback was framed as "sequential commission" in the old ShopEasy model | PRD treats ₹250 as **cashback**, separate ledger from ₹700 commission | Plan A §7, §8, §15.1; §26.2 |
| R-03 | Plan A & Plan B commission on same Billing ID | Never both. Exactly one programme engine per Billing ID | Plan B §5.6–5.7; §26.4 |
| R-04 | Same phone in both programmes | Not allowed; different numbers may hold one account each | Plan B §2.2 |
| R-05 | Plan B generation commission: five generations (original doc) vs ₹50 to direct distributor | ₹50 per eligible Billing ID to the **direct referring distributor only**; no upstream payouts | Plan B §5.7, §22.1; §26.3 |
| R-06 | Refunds/cancellations | None under current rules; display no-cancel notice before checkout | Plan A §17; Plan B §8.5 |
| R-07 | Plan A customers downloading statements | Not provided to Plan A customers | Plan A §12.5 |
| R-08 | Plan B distributor statement format | Excel (.xlsx) only, **no PDF** | Plan B §13.7 |
| R-09 | Admin reports format | Plan A admin reports: PDF + Excel. Plan B admin reports: Excel | Plan A §13.1(20), §14; Plan B §15 |
| R-10 | Notifications | Programme-scoped: Plan A — admin notified on cycle completion, cashback withdrawal request, important transaction failures. Plan B — only the 4 listed (order delivered → distributor; blocked-distributor withdrawal request → admin; wallet unfrozen → distributor; withdrawal success → distributor). No SMS/email. | Plan A §11, §13.2; Plan B §16 |
| R-11 | Real payments / withdrawals | Simulated only until gateway, rules and security verified | Plan B §8.2, §22.6; §26.6 |
| R-12 | Referral code entry timing: Plan A §4.1 (registration) vs Plan B §4.3 (checkout) | Confirmed by Arya Global Digital: Referral codes are entered during ORDERING / CHECKOUT for BOTH Plan A and Plan B. Neither programme enters referral codes at registration. Validation occurs at checkout ("Invalid Referral" for Plan A; "Wrong Referral ID" with distributor name preview for Plan B). Relationship saved permanently only after successful order placement. | Business owner confirmed decision; supersedes Plan A §4.1 |

---

## B. Open items — financial / referral (BLOCKING)

| ID | Question | Why it matters | Options | Engineering default (until confirmed) | Status |
|---|---|---|---|---|---|
| **BR-A1** | Can multiple Billing IDs owned by the **same purchasing customer** contribute to the **same** cashback cycle? (§25.1 example: F2's 203/204/205 all → 201, vs an earlier clarification forbidding it) | Changes who receives ₹250 contributions | (a) Allowed (example table); (b) Only one contribution per contributing customer per cycle; excess goes to next eligible recipient | **Blocked.** Policy interface `ContributorPolicy` with no production implementation. Test-only policies labelled `SAMPLE_*`. | OPEN-BLOCKING |
| **BR-A2** | Rule that assigns a new Billing ID to an independent queue (F1 queue vs J1 queue) | Determines queue membership and therefore all cashback | (a) Queue per "root" customer who had no referrer — referred customers' Billing IDs join their root referrer's queue; (b) queue per direct referrer; (c) new queue whenever a customer without referrer buys; (d) other | **Blocked.** `QueueAssignmentPolicy` interface; no production implementation. | OPEN-BLOCKING |
| **BR-A3** | Which purchases count as **contributors** for a given queue; does a contributing Billing ID **also** become a recipient in that queue? (Example queue lists 203–205 as both F1-queue contributors and later recipients) | Double role affects cash flow (₹250 allocation per unit is fixed at ₹250) | (a) Each Billing ID: contributes ₹250 to the current ACTIVE recipient of its queue, then joins the tail as WAITING; (b) other | **Blocked**; sample policy (a) used in tests only. | OPEN-BLOCKING |
| **BR-A4** | Does the first Billing ID in a new queue (no ACTIVE recipient yet) contribute to anyone? Where does that unit's ₹250 go? | Unallocated cashback must be accounted for | (a) Becomes ACTIVE recipient, ₹250 recorded as "unallocated cashback reserve"; (b) other | Record as `UNALLOCATED` reserve entry in the cashback ledger (no customer credit). | OPEN-BLOCKING |
| **BR-A5** | May a recipient's own later Billing IDs contribute to its own cycle? (Own-purchase exclusion existed in ShopEasy) | Self-funding of cashback | (a) Excluded; (b) allowed | Part of `ContributorPolicy`; blocked. | OPEN-BLOCKING |
| **BR-X1** | Repeat-order referral attribution: Referral code entry at checkout is confirmed for both Plan A and Plan B (superseding Plan A §4.1). If a customer completes their first order without entering any referral code, can that customer enter a referral code on a later order? | Determines whether completing an order without a code permanently locks the customer as unreferred, or whether referral attribution can occur on a subsequent order before any relationship exists. Once established on a successful order, the referral relationship is permanent and cannot be replaced. | (a) First order only: if an order is placed without a referral code, customer cannot enter one later; (b) Later order allowed: customer without an established referral relationship may enter a referral code on a subsequent order; once placed, it locks permanently; (c) other | **Open question.** Do not assume repeat orders can bind referrals without explicit business confirmation. Under no circumstances may a later order overwrite an already established referral relationship (single-referrer invariant). | OPEN-BLOCKING |
| **BR-X2** | Plan A §4.1(9–10): an inactive Plan A customer (no Power Bank purchase) cannot refer. Does an equivalent "must have purchased" rule apply to **Plan B distributors**? | Eligibility of ₹500/₹50 | (a) No purchase requirement for distributors (only blocked/deactivated distributors cannot refer); (b) same as Plan A | (a) — Plan B lists only blocking as a referral restriction (§11.1). | OPEN-BLOCKING (confirm) |
| **BR-B1** | Plan B ₹500 timing: "after their **first** successful purchase" (§26.3) and §6.1(3) "check whether the customer has completed a previous successful purchase". If the customer's first-ever purchase happened **without** the distributor code (Plan B binding at checkout), is ₹500 still due on the first purchase that carries the code? | ₹500 eligibility | (a) ₹500 on the first successful order that establishes the relationship (even if a later order); (b) only if that order is the customer's first-ever purchase; (c) other | Independent open decision: concerns whether Plan B ₹500 direct commission is payable when a customer's first-ever purchase occurred without a distributor code, but a distributor code is entered on a later order. Resolution depends on the confirmed BR-X1 later-order referral rule, but is not automatically resolved by either BR-X1 option. Blocked pending explicit confirmation. | OPEN-BLOCKING |
| **BR-B2** | Do the Plan A deduction rates (Operational Cost 4.6667 %, TDS 2 %) apply to Plan B ₹500 and ₹50? Plan B states only gross ("₹650 gross"). | Net payable to distributors | (a) Same deductions; (b) none; (c) different rates | Ledger stores gross, op-cost, TDS, net for every commission; Plan B rates set to **0 % pending confirmation**; Plan B withdrawals disabled in production until confirmed. | OPEN-BLOCKING |
| **BR-B3** | Can Plan B distributors purchase Power Banks themselves? If so, which programme do those Billing IDs belong to, and does anyone earn on them? (Plan B→Plan B referrals forbidden.) | Billing IDs and commissions for distributor purchases | (a) Distributors may buy; Billing IDs tagged PLAN_B; no commission, no cashback; (b) distributors cannot buy | (a) — no commission generated (no eligible referrer exists). | OPEN-BLOCKING (confirm) |
| **BR-A6** | Plan A commission withdrawal rules: minimum amount? full balance only? admin approval? (Plan A §7 gives none; old ShopEasy used ≥ ₹750 full balance; Plan B rules are distributor-specific) | Payout rules | (a) Any amount ≤ available, no approval; (b) Full balance only; (c) Minimum ₹X | Request lifecycle implemented; **amount rule configurable**, default *full available balance, no minimum, no approval*; production payouts disabled until confirmed. | OPEN-BLOCKING |
| **BR-A7** | What happens to the ₹750 commission pool for a Billing ID whose purchaser has **no** referrer, and to the ₹250 cashback when no recipient is eligible? | Company accounting / reconciliation | Retained as company income; or reserved | Record `UNALLOCATED` allocation rows (no wallet credit) for reconciliation. | OPEN-BLOCKING (accounting confirm) |
| **BR-T1** | GST/TDS/operational cost legal validity | Tax compliance | — | Rates configurable with effective-dated versions; each ledger row stores the rate version used. | OPEN (accountant, §24, §26.5.7) |

---

## C. Open items — operational (NON-BLOCKING, safe placeholder)

| ID | Question | Placeholder | Status |
|---|---|---|---|
| OP-01 | Stock replenishment: stock quantity "not editable" (Plan B §7.3) but In/Out of Stock must be shown | Admin can only **append** audited stock-receipt entries (`inventory_movements`, positive only, reason required); no direct edits. Customers see only In Stock / Out of Stock. | OPEN-NONBLOCKING (§22.2, §26.5.4) |
| OP-02 | Delivery status update method (needed for Plan B "order delivered" notification) | Admin marks delivery status per order (audited); triggers distributor notification | OPEN-NONBLOCKING (§22.3) |
| OP-03 | Deployment topology: §20.1–20.2 "separate frontend and backend Render services" vs Plan B §22.4 "must **not** be deployed as separate services" | Keep current **single Render Web Service** (API + static frontend, same origin) as recommended; configurable CORS supports split later | OPEN-NONBLOCKING (§26.5.6) |
| OP-04 | OTP / email verification at registration | Not required at registration; existing SMS-OTP login remains dev-only until an SMS provider is chosen | OPEN-NONBLOCKING (Plan B §22.5) |
| OP-05 | Real payment gateway | `PaymentProvider` abstraction; only `SimulatedPaymentProvider` (disabled in production) | OPEN-NONBLOCKING (§26.5.5) |
| OP-06 | Billing ID display format (examples: 201, 202 …) | Globally unique numeric sequence allocated from a locked counter; displayed as `AGD-000201`. Start value configurable. | PROPOSED |
| OP-07 | Non-Power-Bank products | Catalogue limited to Power Bank (₹3,999). Billing IDs generated for every purchased unit of any product; only units flagged `commission_eligible` enter commission/cashback engines. | PROPOSED |
| OP-08 | "Deactivated" vs "Blocked" distributor | Blocked: per §11.1 (login yes, refer no, earn no, withdraw by request). Deactivated: same as blocked **plus** no new withdrawal requests? — not specified → treated identically to blocked | OPEN-NONBLOCKING |
| OP-09 | Plan A account blocking | Not specified for Plan A; admin may block (login + view allowed, no referral, no withdrawals) — only if confirmed; default: not exposed | OPEN-NONBLOCKING |
| OP-10 | "One administrator account" (Plan A §13) vs role model | One seeded admin; RBAC structure in code supports more roles later | PROPOSED |
| OP-11 | Legacy ShopEasy data (existing users, orders, ₹750/₹250 ledger rows) | **Preserved untouched**; legacy rows tagged `programme = LEGACY`; no recomputation; no automatic re-attribution to Plan A. Client decides treatment. | OPEN-BLOCKING for production migration |
| OP-12 | Plan B dashboard negative requirements | Do **not** show total referred count or combined units purchased on distributor dashboard; admin dashboard must **not** show combined lifetime withdrawals or daily/weekly/monthly ₹500/₹50 breakdown | RESOLVED-PRD (Plan B §13.3, §14.6) |

---

## D. Engineering decisions (no business impact)

| ID | Decision | Rationale |
|---|---|---|
| ED-01 | Money: `DECIMAL(14,2)` in DB, `Decimal` in Python, `ROUND_HALF_UP` to paise at ledger-entry level only; rates stored `DECIMAL(9,6)` | PRD §3 "full-precision rates, round once, documented method". 750 × 4.6667 % = 35.00025 → **35.00**; 750 × 2 % = **15.00**; net **700.00**. |
| ED-02 | Commission deduction rates and amounts are **effective-dated configuration**; each ledger row stores the rate version applied | Rates editable by admin (§3) without rewriting history |
| ED-03 | Every financial row has a deterministic idempotency key derived from the source event (e.g. `PA-COMM:{billing_id}`, `PB-DIRECT:{customer_id}`, `PB-GEN:{billing_id}`, `CB-CONTRIB:{billing_id}`) with a UNIQUE index | Duplicate-credit prevention on retries/replays (§16, §20.1) |
| ED-04 | Payment success and fulfilment separated: order → payment attempt → verified `payment_events` (unique provider event id) → fulfilment job (Billing IDs, commission, cashback) in one DB transaction, re-runnable | Recovery requirement §5.3, §16 |
| ED-05 | Lock ordering: counter rows → queue rows (by queue id ascending) → wallet rows (by wallet id ascending) | Deadlock avoidance under TiDB pessimistic locking |
| ED-06 | Ledgers are append-only; balances are cached columns verified by a reconciliation job against the ledger sum | Admin must not edit balances; audit |
| ED-07 | No financial invariant relies solely on DB `CHECK` | TiDB CHECK enforcement may be off (audit §4.1) |
| ED-08 | Programme column (`PLAN_A`, `PLAN_B`, `LEGACY`) on users, orders, billing IDs, referral relationships, commissions, wallets, withdrawals | Plan B §19.3 |

---

## E. Questions to send to the client (copy-ready)

1. **BR-A1** — When F2 buys three Power Banks (Billing IDs 203, 204, 205), may all three contribute ₹250 each to F1's Billing ID 201 cycle, or only one?
2. **BR-A2** — What exactly creates a new independent cashback queue, and which queue does a new Billing ID join?
3. **BR-A3** — Does each new Billing ID both (i) contribute ₹250 to the current active recipient in its queue and (ii) join the end of that queue as a future recipient?
4. **BR-A4/A7** — Where does the ₹250 go when a queue has no active recipient yet, and where does the ₹750 go when the buyer has no referrer?
5. **BR-A5** — May a recipient's own later purchases contribute to their own active cycle?
6. **BR-X1** — Confirmed: Referral codes are entered during ordering/checkout for both Plan A and Plan B (superseding Plan A §4.1 registration timing). Remaining open question: If a customer completes an order without entering any referral code, can that customer enter a referral code on a later order, or does their first order permanently lock them as unreferred? (Once established on a successful order, referral relationships are strictly permanent and cannot be replaced).
7. **BR-X2** — Must a Plan B distributor have purchased a Power Bank before their referral code is accepted?
8. **BR-B1** — If a referred customer's first order happened without the distributor's code, is ₹500 still paid on a later order?
9. **BR-B2** — Do Operational Cost (4.6667 %) and TDS (2 %) apply to Plan B ₹500/₹50 commissions?
10. **BR-B3** — Can Plan B distributors buy Power Banks? If yes, does anyone earn commission on those units?
11. **BR-A6** — Plan A commission withdrawal: minimum amount, full-balance-only, and approval rules?
12. **OP-01/02** — How should stock be replenished and delivery status be updated?
13. **OP-03** — Final hosting: one Render service (recommended) or separate frontend/backend services?
14. **OP-11** — How should existing ShopEasy customers, orders and wallet balances be treated?
