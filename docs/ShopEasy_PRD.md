# ShopEasy --- Product Requirements Document (PRD)

**Document status:** Draft for owner review\
**Project:** ShopEasy\
**Document type:** Product Requirements Document\
**Scope:** Learning and portfolio e-commerce application\
**Last updated:** 3 November 2026

------------------------------------------------------------------------

## 1. Product Overview

ShopEasy is a learning and portfolio e-commerce application. It provides
a customer-facing online store and an administrator interface for
managing products and orders.

The project is intended for learning and demonstration, not for
production commercial use. The frontend prototype has been developed
using HTML, CSS, and Vanilla JavaScript. The planned backend uses Python
FastAPI and MySQL.

The application includes two separate customer earning mechanisms:

1.  **Sequential commission:** An eligible successfully placed order
    generates one ₹250 commission for the currently assigned
    beneficiary. A beneficiary completes a cycle after receiving 16
    commissions, totalling ₹4,000.
2.  **Direct referral reward:** When a referred customer places their
    first successful order using a valid referral code, the direct
    referrer receives ₹750 once.

These mechanisms are separate. A single eligible order may trigger both
mechanisms if the applicable conditions are met.

## 2. Product Goals

-   Provide a simple e-commerce experience for browsing products and
    placing simulated orders.
-   Provide an admin interface for managing the product catalogue and
    reviewing operational information.
-   Support customer and admin authentication with role separation.
-   Support permanent direct referral attribution.
-   Track sequential ₹250 commissions and direct ₹750 referral rewards.
-   Keep order, product, stock, and reward calculations authoritative on
    the backend.
-   Demonstrate a clear frontend/backend/database architecture suitable
    for a learning project.

## 3. Project Scope

### 3.1 In Scope

-   Customer registration and authentication.
-   Admin authentication and role-based access.
-   Product listing, search, filtering, sorting, and product details.
-   Shopping cart and address selection/management.
-   Checkout with simulated payment.
-   Order creation and order history.
-   Admin product management.
-   Admin views for orders and customers.
-   Customer referral code generation and display.
-   Optional referral code entry during checkout.
-   Direct referral reward of ₹750, once per referred customer.
-   Sequential commission of ₹250 per eligible order, with a
    16-commission beneficiary cycle.
-   Customer views for referral and sequential commission progress,
    subject to the remaining UI decisions.
-   Basic testing and deployment to Render.

### 3.2 Out of Scope

-   Real payment gateway integration.
-   Collection or storage of real card details.
-   Customer cancellation after a successfully placed order.
-   Product return and refund workflows.
-   Production-grade financial disbursement or banking integration
    unless separately approved.
-   Multi-level/upline referral commissions.
-   Public admin registration.
-   Production commercial accounting, tax filing, or regulatory
    compliance workflows.

## 4. User Roles and Permissions

### 4.1 Customer

Customers can:

-   Register and log in.
-   Browse and search active products.
-   View product details and availability.
-   Add products to and manage their cart.
-   Select or manage delivery addresses.
-   Place orders using simulated payment.
-   View their order history and order status.
-   View their own permanent referral code.
-   Enter an optional referral code during checkout.
-   View eligible referral and sequential commission information when
    the relevant UI is implemented.

Customers cannot:

-   Access admin-only functions.
-   Change their role to admin.
-   Use their own referral code.
-   Change their direct referrer after attribution has been established.
-   Cancel a successfully placed order.

### 4.2 Administrator

Administrators are pre-provisioned. There is no public admin
registration.

Administrators can:

-   Log in through the approved admin authentication flow.
-   View the admin dashboard.
-   Create, edit, activate/deactivate, and delete products as supported
    by the application rules.
-   Manage product stock.
-   View customer information.
-   View orders and manage order fulfilment status, once the relevant
    functionality is implemented.

Administrators cannot:

-   Receive or generate customer referral codes.
-   Participate as a direct referrer.
-   Participate as a sequential beneficiary.
-   Change their role through customer-facing functionality.

Admin records must have `referral_code = NULL` and `referred_by = NULL`.

## 5. Authentication and Authorization Requirements

### 5.1 Customer Authentication

The documented target supports both:

-   Phone number + OTP.
-   Phone number + password.

Both methods must authenticate the same customer account.

Password reset is intended to use OTP verification.

### 5.2 Admin Authentication

The documented target supports:

-   Phone number + OTP.
-   Phone number + password, followed by mandatory OTP multi-factor
    verification.

An admin session must not be issued after password verification alone.

### 5.3 Security Requirements

-   The backend is the authority for authentication and authorization.
-   Customer and admin permissions must be enforced on the backend, not
    only by hiding frontend controls.
-   Passwords must be stored using a suitable password hashing algorithm
    such as Argon2id or bcrypt.
-   Plaintext passwords must never be stored or logged.
-   OTPs must expire and be single-use.
-   OTP verification must enforce attempt limits and resend cooldowns.
-   Production OTP values must not be returned in API responses or
    written to logs.
-   Client-side `localStorage` and `sessionStorage` values must not be
    trusted as proof of identity or authorization.
-   Sensitive endpoints must verify the authenticated user's role and
    account status.

**Implementation parameters such as exact password complexity, lockout
thresholds, OTP lifetime, and resend cooldown must be finalized in the
security rules before implementation.**

## 6. Customer Referral Code

### 6.1 Referral Code Generation

-   Each customer receives a unique referral code after registration.
-   The code is stored by the backend and displayed on the customer's
    profile.
-   The customer can copy or share the code.
-   A customer's referral code is permanent and cannot be edited,
    changed, or regenerated through normal customer functionality.
-   Admin accounts do not receive referral codes.

### 6.2 Referral Code Entry

-   Referral code entry is optional.
-   The code is entered during checkout, not during registration.
-   A customer can complete registration without a referral code.
-   A customer can place an order without entering a referral code.
-   Self-referral is prohibited.

### 6.3 Direct Referrer Attribution

-   A valid referral code used on the customer's first successful order
    establishes the direct referrer.
-   The direct referrer is stored as a permanent relationship.
-   Later orders cannot change the customer's direct referrer.
-   A different referral code supplied on a later order must not replace
    the established attribution.
-   If the customer's first successful order is completed without a
    referral code, the direct referrer remains empty under the current
    rule; a later order cannot establish a new direct referrer.

## 7. Customer Earning Mechanisms

The two earning mechanisms below are independent. They must be recorded
distinctly and must not be confused with one another.

### 7.1 Sequential ₹250 Commission

-   Each eligible successfully placed order generates exactly one ₹250
    commission for the currently assigned beneficiary.
-   The commission is per order, not per product unit.
-   An order containing one unit or multiple units still generates only
    one ₹250 commission.
-   Each beneficiary receives 16 commissions.
-   16 × ₹250 = ₹4,000.
-   After the beneficiary receives 16 commissions, that beneficiary's
    cycle is completed and the next beneficiary is activated.
-   The sequence is intended to continue in order: C1, C2, C3, and so
    on.
-   This is a sequential beneficiary allocation mechanism, not a
    multi-level referral commission system.
-   The purchasing customer's direct referrer does not determine who
    receives the sequential ₹250 commission.
-   One eligible order may generate both a ₹250 sequential commission
    and a ₹750 direct referral reward, when both sets of conditions are
    satisfied.

**The following details are not yet finalized and must not be assumed:**

-   When a customer enters the beneficiary queue.
-   How the exact queue position is assigned.
-   Whether a customer whose first order has no referral code can enter
    the queue.
-   Which products/orders qualify.
-   Whether the queue is global across products or separate per product.
-   Whether the current beneficiary's own purchase can count.
-   How progress is displayed for customers who are not the active
    beneficiary.

### 7.2 Direct ₹750 Referral Reward

-   When a referred customer places their first successful order using a
    valid referral code, the direct referrer receives ₹750.
-   The reward is paid only once for each referred customer.
-   Subsequent orders by the same referred customer do not generate
    another ₹750 reward.
-   The full ₹750 is credited.
-   No 2% TDS or 3% service charge deduction is applied in this project.
-   Self-referrals are prohibited.
-   Admin accounts cannot receive direct referral rewards.

### 7.3 Reward Trigger and Duplicate Prevention

-   A failed checkout or failed simulated payment must not trigger
    either reward.
-   Rewards must be associated with the successful order that triggered
    them.
-   Duplicate processing of the same order must not create duplicate
    reward records.
-   The backend must enforce reward eligibility and duplicate
    prevention.
-   Reward records and wallet/ledger changes must be committed
    consistently with the successful order transaction.

### 7.4 Reward Balance and Progress Display

The customer experience is expected to show referral-related earnings
and sequential commission progress.

Proposed sequential progress model:

-   16 progress slots, each representing ₹250.
-   The active beneficiary sees their actual progress, such as 5/16 and
    ₹1,250 / ₹4,000.
-   A customer who is not the active beneficiary sees inactive/grey
    slots and an explanation that they are not the current beneficiary.
-   A completed beneficiary cycle displays 16/16 and ₹4,000.

The exact balance presentation---one combined balance or separate direct
referral and sequential commission balances---remains undecided.

## 8. Orders, Checkout, and Simulated Payment

### 8.1 Checkout

-   Customers can select or provide a delivery address.
-   The checkout page displays the order summary.
-   Payment is simulated; no real payment gateway is integrated.
-   The referral code field is optional and appears during checkout.
-   The backend recalculates prices and totals using current database
    product prices.
-   The backend validates product availability and stock before
    confirming an order.

### 8.2 Order Placement

-   An order is considered successfully placed only after the simulated
    payment/checkout flow succeeds according to the approved
    implementation.
-   A failed checkout must not create reward credits.
-   A successfully placed order cannot be cancelled by the customer.
-   Returns and refunds are outside the current project scope.
-   Order items must preserve the product price at the time of order
    creation as a historical price snapshot.
-   Order creation, stock updates, payment simulation result, and
    eligible reward processing must be handled consistently to avoid
    partial or duplicate processing.

### 8.3 Order History and Status

Customers can view their orders and the available order status
information.

Administrators are expected to view orders and manage fulfilment status.
The exact set of order statuses and permitted transitions must be
specified during implementation planning.

## 9. Product Catalogue and Administration

### 9.1 Customer Catalogue

-   Customers can view active products.
-   Customers can search and filter products.
-   Customers can view product details, price, description, images, and
    stock availability.
-   Inactive products must not be exposed through public customer
    catalogue endpoints.

### 9.2 Admin Product Management

Administrators can:

-   Add products.
-   Edit product information.
-   Update prices and stock.
-   Activate or deactivate products.
-   Delete products where permitted by order-history and data-integrity
    rules.
-   Manage product images.

The backend must validate product data and stock changes. Client-side
validation is not sufficient.

### 9.3 Product Financial Allocation Example

The PRD includes the following illustrative allocation for a Power Bank
priced at ₹3,999:

  Allocation                             Amount   Percentage of ₹3,999
  -------------------------------- ------------ ----------------------
  Import cost reserve                    ₹1,500                 37.50%
  Output GST reserve                       ₹400                 10.00%
  Packing/courier                          ₹150                  3.75%
  Sequential commission reserve            ₹250                  6.25%
  Direct referral reward reserve           ₹750                 18.75%
  Gift and achievement reserve             ₹150                  3.75%
  Office/staff reserve                     ₹100                  2.50%
  **Total allocation**               **₹3,300**             **82.52%**
  **Remaining amount**                 **₹699**             **17.48%**

This is an example for the ₹3,999 Power Bank, not an approved universal
allocation formula for every product.

The existing catalogue contains products at different prices. The
allocation model for other products is unresolved. Do not apply these
fixed amounts to every product without owner approval.

The following decisions remain open:

-   Whether allocation configuration is shared or product-specific.
-   Whether allocation values are fixed or configurable by an admin.
-   Whether allocation values are stored as an order-level financial
    snapshot or calculated dynamically.
-   How the allocation model applies to lower-priced products.

## 10. Proposed Technology Stack

  Layer                         Technology
  ----------------------------- ---------------------------------
  Frontend                      HTML5, CSS3, Vanilla JavaScript
  Backend                       Python, FastAPI
  Database                      MySQL 8.0
  ORM                           SQLAlchemy
  Request/response validation   Pydantic
  Deployment                    Render
  Payment                       Simulated/dummy payment only

This stack describes the planned application architecture. It does not
mean backend implementation or database setup is already complete.

## 11. Proposed Backend Architecture

The backend is planned as a layered FastAPI application.

### 11.1 API Layer

Responsible for:

-   Defining REST endpoints.
-   Receiving customer and admin requests.
-   Applying authentication and role dependencies.
-   Validating request and response formats.
-   Returning consistent responses.

Planned route groups include:

-   Authentication.
-   Products and categories.
-   Cart.
-   Addresses.
-   Orders and checkout.
-   Simulated payments.
-   Referrals.
-   Sequential commissions.
-   Wallets and withdrawals, if approved.

### 11.2 Schema Layer

Pydantic schemas define and validate API input and output data. They
separate public API payloads from internal database models.

### 11.3 Service Layer

Business logic is kept out of route handlers. Planned services include:

-   Authentication service.
-   Product/catalogue service.
-   Cart service.
-   Order and checkout service.
-   Direct referral reward service.
-   Sequential commission service.
-   Wallet/ledger service, if approved.

### 11.4 Data Access Layer

SQLAlchemy models and database sessions provide access to MySQL.
Financial and order operations must use database transactions and
appropriate constraints/locking.

### 11.5 Security and Authorization

-   Customer endpoints require an authenticated customer.
-   Admin endpoints require an authenticated active admin.
-   Role checks must be performed on the backend.
-   Customer input must never be allowed to set privileged roles or
    reward amounts.
-   Financial values must be calculated and validated on the server.

## 12. Proposed Database Entities

The following are candidate entities for design discussion. The final
schema must be approved after the unresolved business rules are decided.

### 12.1 Core Entities

  -----------------------------------------------------------------------
  Entity                              Purpose
  ----------------------------------- -----------------------------------
  `users`                             Customer and admin identity, phone,
                                      password hash, role, account
                                      status, referral code, and direct
                                      referrer relationship.

  `addresses`                         Customer delivery addresses.

  `categories`                        Product categories.

  `products`                          Product details, category, price,
                                      stock, status, and image
                                      references.

  `cart_items`                        Products and quantities in a
                                      customer's cart.

  `orders`                            Customer order header, address
                                      reference, totals, status, and
                                      timestamps.

  `order_items`                       Products, quantities, and
                                      historical price snapshots for each
                                      order item.

  `payments`                          Simulated payment method, status,
                                      and transaction reference.

  `otp_records`                       OTP verification state, expiry,
                                      attempts, and consumption status,
                                      if persisted separately.
  -----------------------------------------------------------------------

### 12.2 Earning and Wallet Entities

These entities are proposed to support the documented earning
mechanisms. Their final design depends on the unresolved rules.

  -----------------------------------------------------------------------
  Entity                              Purpose
  ----------------------------------- -----------------------------------
  `cashback_cycles`                   Tracks a beneficiary's
                                      16-commission sequential cycle.

  `cashback_transactions`             Records each ₹250 sequential
                                      commission and its source order.

  `referral_commissions`              Records the one-time ₹750 direct
                                      referral reward for a referee's
                                      first successful order.

  `wallet_transactions`               Auditable credit/debit ledger for
                                      customer earning balances.

  `withdrawal_requests`               Tracks withdrawal requests, if
                                      withdrawal functionality is
                                      approved.
  -----------------------------------------------------------------------

### 12.3 Important Relationships

-   One customer can have multiple addresses.
-   One category can contain multiple products.
-   One customer can place multiple orders.
-   One order can contain multiple order items.
-   One order can have simulated payment records according to the
    selected payment design.
-   A customer can have one direct referrer.
-   A direct referrer can refer multiple customers.
-   A sequential beneficiary can have a cycle containing up to 16
    commission transactions.
-   Each reward transaction must reference its source order.
-   Wallet ledger entries must reference the relevant reward or
    withdrawal event.

### 12.4 Data Integrity Requirements

-   Phone numbers and referral codes must be unique where applicable.
-   Admin accounts must have no referral code or direct referrer.
-   Self-referral must be rejected.
-   A referee must not receive more than one direct referral reward
    event.
-   An eligible order must not create more than one sequential
    commission event.
-   Order item price snapshots must not change when catalogue prices
    change later.
-   Financial records must use appropriate decimal currency types, not
    floating-point storage.
-   Database transactions and constraints must prevent duplicate or
    inconsistent reward processing.
-   Queue updates must be concurrency-safe.

No database or tables are authorized by this document alone.

## 13. Non-Functional Requirements

### Security

-   Enforce authentication and role authorization on the backend.
-   Hash passwords securely.
-   Protect OTP verification against guessing and replay.
-   Validate all API input.
-   Avoid exposing sensitive customer data.
-   Do not trust browser storage for authorization or financial
    calculations.

### Reliability and Data Integrity

-   Prevent duplicate order and reward processing.
-   Use transactions for order and reward updates.
-   Preserve historical order prices.
-   Use database constraints for uniqueness and relationships.
-   Handle invalid, expired, or unavailable products safely.

### Usability

-   Maintain a responsive layout for desktop and mobile.
-   Keep customer and admin interfaces distinct.
-   Provide clear validation and error messages.
-   Display order and reward information in understandable terms.

### Maintainability

-   Keep API routes, schemas, services, models, and configuration
    separated.
-   Keep business rules centralized in services.
-   Use environment variables for secrets and database configuration.
-   Maintain clear setup and deployment instructions.

## 14. Acceptance Criteria

The project can be considered functionally complete for its approved
scope when:

1.  Customers can register and authenticate using the approved methods.
2.  Admins can authenticate with the required admin security checks.
3.  Customers can browse active products and view product details.
4.  Customers can manage their cart and delivery addresses.
5.  Checkout validates product prices and stock on the backend.
6.  Simulated payment success creates an order; simulated failure does
    not create reward credits.
7.  Successfully placed orders cannot be cancelled by customers.
8.  Customers can view their order history.
9.  Admins can manage products and stock.
10. Admins can view customer and order information and perform approved
    order-status actions.
11. Each customer receives a unique permanent referral code.
12. Optional checkout referral attribution is validated and permanently
    recorded on the first successful order.
13. A valid direct referrer receives exactly one ₹750 reward for the
    referee's first successful order.
14. Each eligible order creates exactly one ₹250 sequential commission
    for the active beneficiary.
15. A beneficiary's sequential cycle completes after 16 commissions,
    totalling ₹4,000.
16. Duplicate requests cannot create duplicate orders or reward credits.
17. Customer and admin access boundaries are enforced by the backend.
18. The application can be deployed to the approved Render environment.

Acceptance criteria dependent on unresolved business rules must be
finalized before implementation.

## 15. Unresolved Business Decisions

The following decisions remain open. They must be answered by the
project owner. Do not assume answers.

### Sequential Commission System

1.  **Beneficiary queue enrolment:** Is a customer added to the queue at
    registration or after their first successful order? How is the exact
    queue position assigned?
2.  **Customers without referral codes:** Can a customer who places
    their first order without a referral code become a sequential
    beneficiary?
3.  **Product eligibility:** Does every product/order qualify for the
    ₹250 commission, or is there a minimum product price/order subtotal
    or a list of qualifying products?
4.  **Queue scope:** Is there one global queue across all products or a
    separate queue per product?
5.  **Self-purchase:** Can the active beneficiary's own eligible order
    count toward their 16 commissions?

### Wallet and Withdrawals

6.  **Sequential commission use:** Can sequential commissions be
    withdrawn, or are they only usable as ShopEasy shopping credit?
7.  **Withdrawal threshold:** Once the direct referral balance reaches
    ₹4,000, can the customer withdraw the full available balance or only
    the amount above a retained threshold?
8.  **Withdrawal workflow:** Is withdrawal a simulated request/approval
    workflow for admins, or is withdrawal functionality outside the
    project scope?
9.  **Balance presentation:** Should direct referral rewards and
    sequential commissions appear as separate balances or one combined
    balance?

### Product Financial Allocation

10. **Allocation configuration:** Are allocation values fixed for the
    example Power Bank, shared across products, or configurable
    separately for each product?
11. **Allocation persistence:** Should allocation values be stored as an
    order-level financial snapshot, or calculated dynamically when
    needed?

## 16. Development Guardrails

-   Treat this as a learning and portfolio project, not a production
    financial platform.
-   Do not implement real payment processing.
-   Do not invent answers to unresolved business decisions.
-   Do not start implementation of unresolved reward/withdrawal
    behaviour.
-   Keep the backend authoritative for pricing, stock, authentication,
    authorization, and reward calculations.
-   Do not trust client-side storage for security or financial state.
-   Do not modify protected documentation unless the owner explicitly
    approves the exact changes.
-   Do not mark tasks complete without implementation and verification.
-   Review the existing frontend before changing it.
-   Implement incrementally and verify each phase before proceeding.

## 17. Current Project Status

The customer and admin frontend prototypes have been developed using
HTML, CSS, and Vanilla JavaScript. They use browser storage and mock
data for prototype behaviour.

The frontend is not a backend-connected application. UI functionality
must not be described as completed backend functionality.

The planned backend and database implementation have not been approved
by this PRD alone. The owner must first review this document and resolve
the relevant open business decisions.

------------------------------------------------------------------------

**End of PRD**
