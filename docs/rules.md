# ShopEasy --- Development Rules

These rules apply to every Antigravity task.

## 1. Work process

1.  Read `docs/architeture.md`, `docs/rules.md`, `docs/design.md`,
    `docs/tasks.md`, and `docs/memory.md` before starting a task.
2.  Inspect the existing code before editing.
3.  Work only on the task explicitly approved by the project owner.
4.  Do not implement future phases early.
5.  Make small, reviewable changes.
6.  Run relevant checks and tests before marking a task complete.
7.  Update `docs/tasks.md` and `docs/memory.md` after completing a task.
8.  Report changed files, commands run, test results, and known
    limitations.
9.  Stop and wait for approval at the end of each task.

## 2. Technology constraints

-   Frontend: HTML5, CSS3, Vanilla JavaScript.
-   Backend: Python and FastAPI.
-   Database: MySQL using SQLAlchemy.
-   Validation: Pydantic.
-   Version control: Git and GitHub.
-   Deployment: Render.
-   Do not use React, Angular, Vue, or another backend framework without
    explicit approval.

## 3. Code quality

-   Use clear, descriptive names.
-   Keep functions focused and reasonably small.
-   Avoid duplicated code.
-   Separate routes, schemas, models, and business logic.
-   Add type hints to Python functions where practical.
-   Handle expected errors explicitly.
-   Validate all incoming data on the backend.
-   Do not swallow exceptions or return success when an operation
    failed.
-   Do not add dependencies unless they are needed; explain new
    dependencies.
-   Do not rewrite unrelated working files.

## 4. Security and roles

-   The backend is the authority for authentication and authorization.
-   Never trust a role, price, discount, order total, or stock value
    supplied by the browser.
-   Customers cannot select or change their own role.
-   Admin accounts are provisioned through a controlled setup process.
-   Admin endpoints must enforce admin authorization on the server.
-   Customer endpoints must enforce ownership of carts, addresses, and
    orders.
-   Do not expose OTPs, secrets, database credentials, or private user
    data in logs or API responses.
-   Store secrets in environment variables.
-   Commit `.env.example`, never `.env`.
-   Add `.env`, virtual environments, caches, and generated secrets to
    `.gitignore`.

## 5. OTP rules

-   Development OTP is allowed only in development mode.
-   Make the development OTP behavior explicit and easy to disable.
-   OTPs must expire and have a limited number of verification attempts.
-   Avoid storing plaintext OTPs; store a secure hash where feasible.
-   A successful OTP must be consumed so it cannot be reused.
-   Do not log OTP values.
-   Do not expose development OTP behavior in production.
-   Real SMS integration is a later task and must not be simulated as
    already configured.

## 6. Referral rules

-   Only customer accounts receive a referral code.
-   Every customer referral code must be unique and protected by a
    database unique constraint.
-   Admin `referral_code` and `referred_by` values must be `NULL`.
-   Admin accounts must never receive, display, or use customer referral
    codes.
-   Customers must not be able to choose another user's referral code as
    their own.
-   Validate a referral code on the backend before recording a referral
    relationship.
-   Do not award discounts or rewards unless a later approved task
    defines them.

## 7. Product, cart, order, and payment rules

-   Admins control product creation, editing, deletion, price, and
    stock.
-   Public customers can only see active products.
-   Validate product quantity and stock on the backend.
-   Calculate prices and order totals on the backend using database
    values.
-   Store an order-item price snapshot so later product price changes do
    not alter historical orders.
-   Do not trust totals calculated by the browser.
-   Dummy payment is a simulation only; never request or store real card
    details.
-   Clearly label simulated payment status.
-   Do not claim a real payment gateway is integrated.

## 8. Frontend rules

-   Use semantic HTML.
-   Use accessible labels, keyboard-friendly controls, and meaningful
    alternative text.
-   Keep CSS organized and responsive.
-   Keep JavaScript modular and avoid inline event handlers where
    practical.
-   Display loading, empty, success, and error states.
-   Do not put secrets or authorization logic in frontend code.
-   Treat frontend validation as user experience only; repeat validation
    on the backend.

## 9. Git rules

-   Use meaningful commit messages, for example
    `feat: add customer product listing`.
-   Commit only tested, relevant changes.
-   Never commit `.env`, credentials, OTP secrets, or database dumps.
-   Review `git status` before committing.
-   Do not force-push or rewrite shared history unless explicitly
    requested.
-   Push after the project owner has reviewed the changes.

## 10. Definition of done

A task is complete only when: - Its acceptance criteria are met. -
Relevant tests or manual checks have been run. - No known unrelated
files were changed. - Documentation and project memory are updated. -
The agent reports exactly what was tested and what remains incomplete. -
The agent stops for owner approval.
