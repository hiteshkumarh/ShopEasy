# ShopEasy --- Architecture

## 1. Project overview

ShopEasy is a learning and portfolio e-commerce website. It is not
intended for production use.

The application has two roles: - **Customer:** browses products, manages
a cart, checks out, views orders, and receives a unique referral code. -
**Admin:** manages products, inventory, customers, and orders. Admin
accounts never receive referral codes.

## 2. Technology stack

  Area              Technology
  ----------------- -------------------------------------------
  IDE               Google Antigravity
  Frontend          HTML5, CSS3, Vanilla JavaScript
  Backend           Python, FastAPI
  ORM               SQLAlchemy
  Validation        Pydantic
  Database          MySQL
  Authentication    Phone number + OTP
  Initial OTP       Development-only OTP
  Payment           Dummy payment simulation
  Image hosting     Cloudinary or equivalent external storage
  Version control   Git and GitHub
  Deployment        Render

Do not introduce React, Angular, Vue, or another backend framework
unless the project owner explicitly approves a change.

## 3. High-level architecture

``` text
Browser
  |
  | HTML / CSS / JavaScript
  | HTTP requests carrying JSON
  v
FastAPI application (Render)
  |
  | Routers -> Services -> SQLAlchemy
  v
External MySQL database
```

The FastAPI application should eventually serve the frontend static
files and API from one Render web service. The MySQL database is hosted
externally and accessed through environment-based connection settings.

## 4. Backend responsibilities

-   `routers/`: HTTP endpoints and request/response handling.
-   `schemas/`: Pydantic request and response models.
-   `models/`: SQLAlchemy database models.
-   `services/`: business logic, such as checkout and referral
    generation.
-   `utils/`: shared helpers.
-   `config.py`: environment-based application configuration.
-   `database.py`: SQLAlchemy engine, session factory, and database
    dependency.
-   `main.py`: FastAPI application, router registration, and static
    frontend serving.

Keep route handlers thin. Put business rules in services.

## 5. Frontend responsibilities

-   `index.html`: customer storefront.
-   Other customer pages: product details, cart, checkout, orders,
    profile, and login.
-   `admin/`: admin dashboard and management pages.
-   `css/`: shared design tokens and page/component styles.
-   `js/`: API client and page-specific behavior.
-   `assets/`: local static assets. Product uploads should use external
    image storage for deployment persistence.

Frontend code must call backend APIs for persistent data. `localStorage`
may be used for non-sensitive UI preferences or a temporary cart
prototype, but it must not be the source of truth for orders, payments,
roles, prices, or inventory.

## 6. Initial database entities

Create only the tables required by the implemented phase. Expected
entities:

-   `users`: phone number, role, account status, customer referral code,
    and optional referred-by relationship.
-   `otp_verifications`: phone number, hashed OTP or secure verification
    data, expiry, attempt count, and consumed status.
-   `categories`: category name and metadata.
-   `products`: name, description, price, image URL, stock, category,
    active status, and timestamps.
-   `cart_items`: customer, product, and quantity.
-   `addresses`: customer delivery addresses.
-   `orders`: customer, address, status, total, and timestamps.
-   `order_items`: order, product reference, quantity, and price
    snapshot.
-   `payments`: order, simulated payment status, transaction reference,
    and timestamps.

Referral fields belong to customer accounts. Admin `referral_code` and
`referred_by` must be `NULL`.

## 7. Important relationships

-   One customer can have multiple cart items.
-   One customer can have multiple addresses and orders.
-   One order can contain multiple order items.
-   Each order item stores the product price at purchase time.
-   A product belongs to a category when categories are used.
-   A customer may optionally have been referred by another customer.
-   An admin is a user with the admin role, but has no referral
    identity.

## 8. API organization

Use versioned routes, for example `/api/v1`.

Expected route groups: - `/auth`: request and verify OTP, current user,
logout. - `/products`: public product listing and product details. -
`/categories`: public category listing. - `/cart`: customer cart
operations. - `/addresses`: customer address operations. - `/orders`:
customer order creation and history. - `/payments`: dummy payment
simulation. - `/referrals`: customer referral information. -
`/admin/products`: admin product management. - `/admin/orders`: admin
order management. - `/admin/customers`: admin customer listing.

Only implement routes when their corresponding phase is approved.

## 9. Deployment architecture

-   Deploy FastAPI on Render.
-   Serve frontend static files from FastAPI in the initial deployment.
-   Use an external MySQL provider.
-   Store secrets and connection strings in Render environment
    variables.
-   Store product images on Cloudinary or equivalent external storage.
-   Never rely on a Render instance's local filesystem for persistent
    user uploads.

## 10. Architecture change control

Do not change the stack, database design, route conventions, or folder
structure silently. Explain the reason and ask the project owner before
making a material architectural change.
