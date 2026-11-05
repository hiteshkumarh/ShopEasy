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

## Native Windows Setup (Without Docker)

If Docker Desktop is unavailable, you can run the application using Python and an installed MySQL server.

### Step 1: Install prerequisites

- Python 3.12: https://www.python.org/downloads/
- MySQL 8.0: https://dev.mysql.com/downloads/installer/

### Step 2: Create the database

Open MySQL and execute:

```sql
CREATE DATABASE shopeasy_db
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;
```

### Step 3: Configure environment variables

From the project root:

```powershell
copy .env.example .env
notepad .env
```

Configure your local MySQL connection, including:

```env
DB_HOST=localhost
```

Also configure the database credentials, secret keys, and admin credentials.

### Step 4: Create a Python virtual environment

```powershell
cd backend

python -m venv .venv

.\.venv\Scripts\Activate.ps1
```

### Step 5: Install dependencies

```powershell
pip install -r requirements.txt
```

### Step 6: Apply migrations and initialize baseline data

```powershell
alembic upgrade head

python -m app.core.seed
```

### Step 7: Start the application

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

http://127.0.0.1:8000/

---

## Repository

GitHub: https://github.com/hiteshkumarh/ShopEasy

## License

Add a license file if you intend to distribute this project under a specific open-source license.
