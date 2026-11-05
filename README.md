# ShopEasy — E-Commerce & Commission Platform

ShopEasy is an e-commerce platform built with **FastAPI**, **MySQL**, and **Vanilla HTML, CSS, and JavaScript**.

It includes product management, customer accounts, shopping cart, order processing, direct referral rewards, sequential commission distribution, separate customer wallets, simulated payments, and an admin dashboard.

> **Project status:** Development / testing project. Payments and withdrawals are simulated. This project is not currently a production-ready financial platform.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI |
| ORM | SQLAlchemy 2.0 |
| Database migrations | Alembic |
| Database | MySQL 8.0 |
| Database driver | PyMySQL |
| Validation | Pydantic v2 |
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Deployment | Docker, Docker Compose |
| API server | Uvicorn |

The frontend does not require Node.js or npm.

---

## Prerequisites

Install the following software before running the project:

1. **Git:** https://git-scm.com/download/win
2. **Docker Desktop:** https://www.docker.com/products/docker-desktop/

Make sure Docker Desktop is running before executing Docker commands.

For native Windows setup without Docker, Python 3.12 and MySQL 8.0 are required.

---

## Quick Start — Docker Setup (Recommended)

### Step 1: Clone the repository

Open PowerShell and execute:

```powershell
git clone https://github.com/hiteshkumarh/ShopEasy.git
cd ShopEasy
```

### Step 2: Create the environment file

Run:

```powershell
copy .env.example .env
```

Open the `.env` file:

```powershell
notepad .env
```

Configure the required values:

| Variable | Description |
|---|---|
| `DB_PASSWORD` | MySQL database password |
| `SECRET_KEY` | Secret key for authentication (minimum 32 characters) |
| `OTP_HMAC_SECRET` | Separate OTP security secret (minimum 32 characters) |
| `ADMIN_NAME` | Administrator's name |
| `ADMIN_PHONE` | Administrator's mobile number |
| `ADMIN_PASSWORD` | Administrator's login password (minimum 12 characters) |

Use strong, unique secrets. Do not use example or placeholder values.

**Important:** Never upload your `.env` file to GitHub. It contains private credentials and is excluded through `.gitignore`.

### Step 3: Build and start the application

Run:

```powershell
docker compose up --build -d
```

Docker Compose automatically:

1. Starts the MySQL database.
2. Waits for MySQL to become healthy.
3. Builds the ShopEasy application image.
4. Applies database migrations using Alembic.
5. Creates the initial administrator account if it does not already exist.
6. Initializes the sequential commission queue controller.
7. Starts the FastAPI application on port `8000`.

### Step 4: Verify the containers

Run:

```powershell
docker compose ps
```

Both services should be running:

- `shopeasy_app`
- `shopeasy_mysql` — healthy

To view application logs:

```powershell
docker compose logs -f app
```

Press `Ctrl + C` to stop viewing logs. This does not stop the containers.

---

## Accessing ShopEasy

After successful startup, open these URLs in your browser:

| Interface | URL |
|---|---|
| Customer Storefront | http://localhost:8000/ |
| Customer Login | http://localhost:8000/login.html |
| Customer Earnings Dashboard | http://localhost:8000/dashboard.html |
| Admin Login | http://localhost:8000/admin/login.html |
| API Documentation | http://localhost:8000/docs |

---

## Admin Login Credentials

The administrator account is created automatically during the first application startup.

| Field | Login credential |
|---|---|
| Admin username | `ADMIN_PHONE` from `.env` |
| Admin password | `ADMIN_PASSWORD` from `.env` |
| Admin login page | http://localhost:8000/admin/login.html |

**Current local development configuration:**

- Admin mobile number: `9800000000`
- Admin password: Use the password configured in your local `.env` file.

For other users cloning the repository, the admin credentials are the values they configure in their own `.env` file.

**Never publish the actual admin password in this README or commit it to GitHub.**

There is no public administrator registration. The initial admin account is provisioned through the backend seed process.

---

## Adding the First Product

The database starts with an empty product catalog. An administrator must add products manually.

1. Open http://localhost:8000/admin/login.html.
2. Log in using the configured admin credentials.
3. Open the **Products** section.
4. Click **Add New Product**.
5. Enter the following example details:

| Field | Example |
|---|---|
| Product Name | Power Bank |
| SKU | PB-3999 |
| Category | Electronics |
| Price | ₹3,999 |
| Stock Quantity | 1,000 |
| Visibility | Active |
| Description | High-capacity 20,000mAh Power Bank with fast charging. |

6. Upload a product image or provide an image URL.
7. Save the product.
8. Open the customer storefront and verify that the product appears.

---

## Project Features

### Customer Features

- Customer registration and login.
- Product browsing.
- Shopping cart.
- Order placement.
- Order history.
- Direct referral rewards.
- Sequential commission tracking.
- Separate referral and commission wallets.
- Simulated withdrawals.

### Admin Features

- Secure administrator login.
- Dashboard.
- Product creation and management.
- Stock management.
- Order management.
- Customer management.

### Referral and Commission System

- ₹750 direct referral reward after an eligible referred customer's first successful order.
- Sequential commission cycle of 16 eligible commissions.
- ₹250 commission per eligible order.
- ₹4,000 total sequential commission per completed cycle.
- Separate referral and sequential commission wallets.

---

## Managing Docker Containers

### Stop the application

```powershell
docker compose down
```

This stops and removes the containers but preserves database records and uploaded images.

### Start the application again

```powershell
docker compose up -d
```

### Rebuild after code changes

```powershell
docker compose up --build -d
```

### View running containers

```powershell
docker compose ps
```

### View application logs

```powershell
docker compose logs --tail=100 app
```

### Data persistence

Docker Compose uses persistent volumes:

- `shopeasy_mysql_data`: Stores database records, including customers, orders, wallets, and commissions.
- `shopeasy_uploads_data`: Stores uploaded product images.

Stopping or rebuilding containers does not normally delete these volumes.

**Warning — destructive operation:**

```powershell
docker compose down -v
```

This removes the Compose-managed volumes and permanently deletes their stored data, including database records and uploaded images. Only use it when you intentionally want a complete reset.

---
## Running ShopEasy Locally

ShopEasy uses Docker Compose to run the FastAPI application and MySQL database.

### Prerequisites

Install the following software:

- [Git](https://git-scm.com/downloads)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)

Make sure Docker Desktop is running before executing Docker commands.

### 1. Clone the Repository

Open PowerShell and execute:

```powershell
git clone https://github.com/hiteshkumarh/ShopEasy.git
cd ShopEasy
```

### 2. Configure Environment Variables

Create your local `.env` file from the example:

```powershell
Copy-Item .env.example .env
```

Open the file:

```powershell
notepad .env
```

Configure the required variables:

```env
DB_PASSWORD=your_mysql_password

SECRET_KEY=your_generated_secret_key
OTP_HMAC_SECRET=your_generated_otp_hmac_secret

ADMIN_NAME=System Admin
ADMIN_PHONE=your_admin_mobile_number
ADMIN_PASSWORD=your_strong_admin_password
```

**Important configuration requirements:**

- Use your own MySQL password.
- Generate separate random values for `SECRET_KEY` and `OTP_HMAC_SECRET`.
- Both secret keys must contain at least 32 characters.
- The two secret keys must be different.
- Use an admin password of at least 12 characters.
- Do not share or commit your `.env` file to GitHub.

To generate a random secret, execute this PowerShell command:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Run it twice to generate two different secrets.

### 3. Validate Docker Configuration

Execute:

```powershell
docker compose config --quiet
```

If the command finishes without errors, your Docker Compose configuration is valid.

### 4. Build and Start ShopEasy

Execute:

```powershell
docker compose up --build -d
```

This command builds the application image and starts the application and MySQL containers in the background.

### 5. Verify Containers

Execute:

```powershell
docker compose ps
```

Expected services:

| Service | Expected status |
|---|---|
| shopeasy_app | Up |
| shopeasy_mysql | Up (healthy) |

MySQL may take a little time to become healthy during its first startup.

### 6. Check Application Logs

To inspect application startup logs:

```powershell
docker compose logs --tail=100 app
```

To follow logs continuously:

```powershell
docker compose logs -f app
```

A successful startup should show:

- Database migrations completed.
- Baseline data seeding completed.
- FastAPI application startup completed.
- Uvicorn running on port 8000.

Press `Ctrl + C` to stop viewing live logs. This does not stop the containers.

### 7. Access ShopEasy

Once the containers are running, open these URLs:

| Application | URL |
|---|---|
| Customer Storefront | http://localhost:8000/ |
| Customer Login | http://localhost:8000/login.html |
| Customer Dashboard | http://localhost:8000/dashboard.html |
| Admin Login | http://localhost:8000/admin/login.html |
| API Documentation | http://localhost:8000/docs |

### 8. Admin Account Setup

During initial database initialization, the application provisions the admin account using:

- `ADMIN_NAME`
- `ADMIN_PHONE`
- `ADMIN_PASSWORD`

**Important:** Admin credentials are initialized only when an admin account does not already exist.

If an admin account already exists in the database, changing the values in `.env` will not automatically update its existing phone number or password.

For an existing database, use the credentials already stored in that database or perform a secure admin credential update using an appropriate application-level procedure.

### 9. Common Problems and Solutions

**Problem 1: Docker daemon is not running**

Example error:

```text
failed to connect to the Docker API
```

Solution:

1. Open Docker Desktop.
2. Wait until the Docker engine is running.
3. Execute:

```powershell
docker version
```

Confirm that both Client and Server information are available.

**Problem 2: MySQL connection refused**

Example error:

```text
Can't connect to MySQL server on 'mysql'
```

Solution:

Check container status:

```powershell
docker compose ps
```

Inspect MySQL logs:

```powershell
docker compose logs --tail=100 mysql
```

If MySQL is still initializing, wait for it to become healthy and restart the application:

```powershell
docker compose restart app
```

Check application logs again:

```powershell
docker compose logs --tail=100 app
```

**Problem 3: Admin login fails**

Check the following:

1. Confirm that you are using the correct admin mobile number and password.
2. Check whether the database already contains an admin account.
3. Remember that changing `.env` does not automatically update an existing admin account.
4. Check application logs for authentication errors.

Do not delete the database just to change admin credentials.

**Problem 4: Port 8000 is already in use**

Another application may already be using port 8000.

Stop the conflicting application or change the host port mapping in `docker-compose.yml`, then restart the containers.

**Problem 5: Environment configuration error**

Validate your configuration:

```powershell
docker compose config --quiet
```

Check that all required environment variables are present in `.env` and contain valid values.

### 10. Stop ShopEasy

To stop the containers without deleting database data:

```powershell
docker compose down
```

To start them again:

```powershell
docker compose up -d
```

### Important: Database and Uploaded Files

ShopEasy uses Docker volumes to persist MySQL data and uploaded files.

Stopping containers or removing the containers with `docker compose down` does not delete these named volumes.

**Warning:** The following command permanently removes the Compose project's containers and associated named volumes, including database and uploaded-file data:

```powershell
docker compose down -v
```

Use this command only when you intentionally want to reset the local database and uploaded files.

### Development Notes

- Payment processing is simulated.
- Withdrawal processing is simulated.
- Use test customer accounts and test data during development.
- Never use production credentials or real payment information for local testing.
## Repository

GitHub: https://github.com/hiteshkumarh/ShopEasy

## License

Add a license file if you intend to distribute this project under a specific open-source license.
