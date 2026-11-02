# ShopEasy --- Development Tasks

## Project workflow

Complete one task at a time. Do not start the next task until the
project owner reviews and approves the current task.

For each task: 1. Read all project documentation and memory. 2. Inspect
existing files. 3. Implement only the approved scope. 4. Run relevant
tests or manual checks. 5. Update this file and `memory.md`. 6. Report
changed files, commands, test results, and limitations. 7. Stop and wait
for approval.

## TASK-001 --- Project foundation and documentation

**Objective:** Establish architecture, design, rules, roadmap, and
project memory.

**Expected files:** - `docs/architeture.md` - `docs/rules.md` -
`docs/design.md` - `docs/tasks.md` - `docs/memory.md`

**Acceptance criteria:** - All five documents exist. - Technology stack
and role separation are documented. - Customer-only referral requirement
is explicit. - Development process and task roadmap are clear.

**Status:** COMPLETED. All five documentation files verified in repository, aligned with architectural and development invariants.

## TASK-002 --- Customer frontend foundation

**Objective:** Build the Apple-inspired customer storefront using HTML,
CSS, and Vanilla JavaScript.

**Scope:** - Customer navigation and responsive menu. - Homepage hero
section. - Product categories. - Featured/latest product sections. -
Reusable product cards. - Footer. - Initial sample product data for UI
demonstration only. - Product listing with search, category filtering, and sorting.
- Product details with gallery and quantity selector. - Login UI prototype with phone & OTP inputs.
- Shopping cart with localStorage persistence. - Checkout UI prototype with simulated payment.
- Orders history prototype. - Profile prototype with customer-exclusive referral placeholder.

**Expected files:** Customer HTML (`frontend/*.html`), shared CSS (`frontend/css/*.css`),
and modular JavaScript (`frontend/js/*.js`).

**Acceptance criteria:** - All 8 customer pages render correctly. - Responsive
desktop, tablet, and mobile layouts. - Navigation works across all pages. - Product cards
display sample products with INR pricing. - No React or other frontend framework. - No
backend integration unless explicitly approved.

**Status:** COMPLETED. Fully tested with automated suite verifying file existence, JS syntax, link/asset integrity, and localStorage cart persistence.

## TASK-002.1 --- Customer frontend review and refinement

**Objective:** Refine layout, navigation, hero presentation, and sample data consistency across all customer pages.

**Scope:**
- Widen desktop container layout and improve fluid responsiveness (`--container-max: 1260px`, fluid clamp padding).
- Enhance navigation sizing, spacing, and mobile drawer consistency across all 8 pages.
- Refine hero section presentation with studio lighting image and improved shadow/border framing.
- Ensure all sample customer information and addresses are strictly fictional (`Aarav Mehta`, fictional address and contact details).
- Replace third-party branded product photography (e.g. Nike swoosh) with clean unbranded images.
- Standardize product card title heights and alignments.
- Complete functional verification of navigation, search, filters, sorting, cart operations, checkout, and referral placeholder.

**Acceptance criteria:**
- Desktop layout is spacious and fluid across viewport widths.
- Navigation header and drawer are consistent on all 8 customer pages.
- Hero presentation reflects Apple-inspired minimalist aesthetic with unbranded studio imagery.
- Customer names and addresses are clearly fictional.
- Third-party brand logos removed from sample products.
- All functional tests pass without errors.

**Status:** COMPLETED. Verified via 187 automated checks with 0 failures.

## TASK-003 --- Admin frontend foundation

**Objective:** Build a separate admin interface.

**Scope:** - Admin login screen UI. - Admin dashboard. - Product
management table. - Add/edit product form. - Order management table. -
Customer listing.

**Acceptance criteria:** - Admin interface is visually distinct. - Forms
and navigation work as UI prototypes. - No referral code appears
anywhere in the admin experience. - Backend authorization will be
implemented in a later task.

## TASK-004 --- FastAPI backend initialization

**Objective:** Create a modular FastAPI application.

**Scope:** - Application entry point. - Configuration using environment
variables. - Health-check endpoint. - Router registration structure. -
CORS configuration appropriate to the deployment arrangement. - Static
frontend serving plan.

**Acceptance criteria:** - Backend starts locally. - Health-check
endpoint responds. - API documentation loads. - No secrets are
hardcoded.

## TASK-005 --- MySQL database and models

**Objective:** Connect MySQL and implement the initial schema.

**Expected entities:** - Users - OTP verifications - Categories -
Products - Cart items - Addresses - Orders - Order items - Payments

**Acceptance criteria:** - Database connection uses environment
variables. - SQLAlchemy models and relationships are valid. - Admin
referral fields are nullable and remain NULL. - Customer referral codes
have a unique database constraint. - Schema changes are managed
consistently.

## TASK-006 --- Phone OTP authentication

**Objective:** Implement customer registration/login and authorized
admin login.

**Scope:** - Request development OTP. - Verify OTP. - Create customer
account when appropriate. - Authenticate existing customers. -
Authenticate pre-provisioned admin accounts. - Issue and validate secure
sessions/tokens. - Add expiry and attempt limits.

**Acceptance criteria:** - Customer cannot self-assign admin role. -
Unknown phone numbers cannot become admins. - OTP expires and cannot be
reused. - Development OTP is unavailable in production mode. - Admin
receives no referral code.

## TASK-007 --- Admin product management

**Objective:** Allow admins to manage the catalog.

**Scope:** - Add product. - Edit product. - Delete/deactivate product. -
Upload product image to external storage. - Set price and stock. -
Manage categories.

**Acceptance criteria:** - Admin authorization is enforced
server-side. - Customers cannot access admin mutations. - Invalid prices
and stock values are rejected. - Active products can be listed publicly.

## TASK-008 --- Customer product browsing

**Objective:** Display admin-managed products to customers.

**Scope:** - Product listing API. - Product details API. - Search. -
Category filtering. - Sorting. - Loading, empty, and error states.

**Acceptance criteria:** - Homepage uses backend product data. -
Inactive products are not publicly visible. - Product details show
current backend data. - Search and filters work.

## TASK-009 --- Shopping cart

**Objective:** Implement customer cart operations.

**Scope:** - Add item. - View cart. - Update quantity. - Remove item. -
Validate product availability and stock.

**Acceptance criteria:** - Cart belongs to the authenticated customer. -
Quantity must be positive. - Stock is checked on the backend. -
Browser-provided prices are not trusted.

## TASK-010 --- Checkout and dummy payment

**Objective:** Create orders and simulate payment.

**Scope:** - Select delivery address. - Review order summary. -
Calculate totals on backend. - Create order and order items. - Simulate
successful/failed payment. - Store payment simulation result.

**Acceptance criteria:** - Backend calculates all prices and totals. -
Order-item price snapshots are saved. - No real card information is
collected. - UI clearly identifies payment as simulated. - Order/payment
states remain consistent.

## TASK-011 --- Orders, tracking, and referrals

**Objective:** Complete customer account functionality.

**Scope:** - Customer order history. - Customer order details. - Admin
order status updates. - Customer order tracking timeline. - Unique
referral code generation. - Referral code display and validation. -
Optional referred-by relationship.

**Acceptance criteria:** - Customers can access only their own orders. -
Admin can manage all orders. - Every customer receives one unique
referral code. - Admin referral code and referred-by fields are NULL. -
Admin UI and APIs do not expose referral functionality.

## TASK-012 --- Testing and Render deployment

**Objective:** Verify the application and deploy it.

**Scope:** - Backend tests. - API integration tests. - Frontend manual
testing. - Role/permission testing. - MySQL external connection. -
Render environment variables. - Static frontend serving. - Deployment
and smoke tests.

**Acceptance criteria:** - Application is accessible through the Render
URL. - Database data persists externally. - Customer and admin
permissions work. - No secrets are committed. - Core shopping workflow
passes testing.

## Task status convention

Use: - `NOT STARTED` - `IN PROGRESS` - `BLOCKED` - `COMPLETED`

Never mark a task completed without evidence from testing.
