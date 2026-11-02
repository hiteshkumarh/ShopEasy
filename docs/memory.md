# ShopEasy --- Persistent Project Memory

> This file is the project's durable source of truth for decisions and
> progress. Update it after every approved task. Do not rely on chat
> history as the only record.

## 1. Project identity

-   **Project name:** ShopEasy
-   **Repository:** `https://github.com/hiteshkumarh/ShopEasy`
-   **Local workspace observed:** `/d/projects/ShopEasy`
-   **Purpose:** Learning and portfolio project.
-   **Production expectation:** Not intended as a production-level
    commercial system.
-   **Design reference:** Apple.com-inspired minimalist visual
    direction. Do not copy Apple's branding, logo, proprietary assets,
    or exact layouts.

## 2. Approved technology decisions

-   Frontend: HTML5, CSS3, Vanilla JavaScript.
-   Backend: Python FastAPI.
-   ORM: SQLAlchemy.
-   Validation: Pydantic.
-   Database: MySQL, hosted externally for deployment.
-   Authentication: phone number and OTP.
-   Initial OTP: development-only OTP.
-   Future authentication extension: real SMS OTP.
-   Payment: dummy payment simulation; no real payment gateway in the
    initial scope.
-   Image hosting: Cloudinary or equivalent external storage.
-   Version control: Git and GitHub.
-   Deployment: Render.

Do not change these decisions without asking the project owner.

## 3. Roles and permissions

### Customer

-   Can register/login using phone number and OTP.
-   Can browse and search products.
-   Can manage their cart.
-   Can checkout using a delivery address.
-   Can use the dummy payment flow.
-   Can view their own orders and tracking.
-   Can manage their profile and addresses.
-   Must receive a unique referral code.
-   May optionally be associated with a referring customer.

### Admin

-   Must be provisioned through a controlled process.
-   Logs in using an authorized phone number and OTP.
-   Can manage products, categories, stock, customers, and orders.
-   Can update order status.
-   **Must never receive a referral code.**
-   Admin `referral_code` and `referred_by` must be `NULL`.
-   Must not see customer referral controls as an admin feature.

### Authorization invariant

The backend is the authority for roles and permissions. Hiding a button
in the browser is not security. Customers cannot assign themselves the
admin role.

## 4. Referral invariants

1.  Only customer accounts receive referral codes.
2.  Each customer code must be unique.
3.  Enforce uniqueness in the database, not only in application code.
4.  Admin referral fields must be NULL.
5.  Referral code generation happens when a customer account is created.
6.  Referral relationships must be validated on the backend.
7.  Do not add referral rewards or discounts unless separately approved.

## 5. Design decisions

-   White main background: `#FFFFFF`.
-   Light secondary background: `#F5F5F7`.
-   Main text: `#1D1D1F`.
-   Secondary text: `#6E6E73`.
-   Primary action: `#0071E3`.
-   Border: `#D2D2D7`.
-   Typography: system font stack or Inter.
-   Style: premium, clean, restrained, whitespace-rich, product-focused.
-   Responsive desktop, tablet, and mobile layouts.
-   Subtle animations only; respect reduced-motion preferences.

## 6. Architecture decisions

-   Three layers: browser presentation, FastAPI application, MySQL data
    layer.
-   Frontend and backend source remain organized separately.
-   FastAPI routes should delegate business logic to services.
-   SQLAlchemy models represent persistent entities.
-   Pydantic schemas validate API inputs and outputs.
-   The FastAPI application is intended to serve the frontend and API
    from one Render web service initially.
-   Product images should use external persistent storage rather than
    relying on ephemeral local deployment storage.

## 7. Engineering constraints

-   Read all five files in `docs/` before beginning a task.
-   Implement only the task approved by the project owner.
-   Work incrementally.
-   Inspect files before editing.
-   Do not overwrite unrelated work.
-   Never hardcode credentials or secrets.
-   Never commit `.env`.
-   Test before claiming completion.
-   Update this file and `tasks.md` after a task.
-   Report files changed, commands run, test results, and limitations.
-   Stop and request approval before the next task.

## 8. Development roadmap

1.  TASK-001: Project foundation and documentation.
2.  TASK-002: Customer frontend foundation.
3.  TASK-003: Admin frontend foundation.
4.  TASK-004: FastAPI backend initialization.
5.  TASK-005: MySQL database and models.
6.  TASK-006: Phone OTP authentication.
7.  TASK-007: Admin product management.
8.  TASK-008: Customer product browsing.
9.  TASK-009: Shopping cart.
10. TASK-010: Checkout and dummy payment.
11. TASK-011: Orders, tracking, and referrals.
12. TASK-012: Testing and Render deployment.

See `tasks.md` for detailed scope and acceptance criteria.

## 9. Current progress

-   GitHub repository has been created as a private repository:
    `hiteshkumarh/ShopEasy`.
-   Antigravity workspace was opened at `/d/projects/ShopEasy`.
-   The five project documentation files were verified under `docs/` (`architeture.md`, `rules.md`, `design.md`, `tasks.md`, `memory.md`). (TASK-001: COMPLETED).
-   Customer frontend foundation was built using pure HTML5, CSS3, and Vanilla JavaScript (TASK-002: COMPLETED).
-   Customer frontend review and refinement completed (TASK-002.1: COMPLETED):
    -   Layout width improved to `--container-max: 1260px` with fluid responsive padding.
    -   Navigation sizing, spacing, and mobile drawer standardized across all 8 customer pages.
    -   Hero section updated with sleek studio-lit unbranded photography and ambient frame styling.
    -   All sample customer names and addresses replaced with clearly fictional data (`Aarav Mehta`, fictional address).
    -   Third-party brand logos (e.g., Nike swoosh) replaced with clean unbranded images.
    -   Product cards standardized with uniform title/description clamping and aligned button baselines.
    -   Full automated test suite executed: 187 checks passed, 0 failures.
-   **Next task:** TASK-003 (Admin frontend foundation) --- Awaiting owner approval.

## 10. Decisions still to be made later

Do not guess these before the relevant task: - Exact external MySQL
provider. - Cloudinary account and credentials. - Admin phone number
provisioning method. - Production SMS provider. - Exact product
categories and initial catalog. - Final Render environment variable
values.

## 11. Session handoff instructions

At the start of a new Antigravity session: 1. Read this file. 2. Read
`architeture.md`, `rules.md`, `design.md`, and `tasks.md`. 3. Inspect
the repository and current Git status. 4. Identify the first incomplete
task. 5. Ask the project owner to approve the next task if it has not
already been approved.

At the end of a task: 1. Update task status accurately. 2. Record actual
implementation decisions and changed files. 3. Record tests and their
actual outcomes. 4. Record blockers and remaining work. 5. Do not mark
untested work as complete.
