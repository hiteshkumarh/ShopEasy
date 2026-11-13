# Dedicated Local MySQL 8.0 Test Environment

This guide explains how to start, use, and stop the isolated local MySQL 8.0 container for ShopEasy integration testing.

> [!WARNING]
> This environment is strictly intended for automated integration tests.
> - Never store production, staging, or user data in this test container.
> - The application runtime remains configured to connect directly to TiDB Cloud (`shopeasy_arya`).
> - This test container runs independently on port `3307` and does not interact with TiDB Cloud or Render.

---

## 1. Prerequisites

- **Docker Desktop** installed on your system.
- Docker daemon must be running (e.g. Docker Desktop running on Windows/macOS or `dockerd` on Linux).

---

## 2. Starting the Test Container

Run Docker Compose pointing explicitly to `docker-compose.test.yml` from the repository root:

```bash
docker compose -f docker-compose.test.yml up -d
```

### Checking Container Health

Wait a few seconds for the MySQL health check to pass:

```bash
docker compose -f docker-compose.test.yml ps
```

The status column will display `healthy` once MySQL 8.0 is ready to accept connections.

---

## 3. Configuring `TEST_MYSQL_URL`

Set the test environment variable in your terminal session to point to the local test database:

### PowerShell (Windows):
```powershell
$env:TEST_MYSQL_URL = "mysql+pymysql://test_user:test_password_123@127.0.0.1:3307/shopeasy_test_local"
```

### Command Prompt (Windows CMD):
```cmd
set TEST_MYSQL_URL=mysql+pymysql://test_user:test_password_123@127.0.0.1:3307/shopeasy_test_local
```

### Bash / Linux / macOS:
```bash
export TEST_MYSQL_URL="mysql+pymysql://test_user:test_password_123@127.0.0.1:3307/shopeasy_test_local"
```

> [!NOTE]
> The target database name **must** begin with `shopeasy_test_` (for example, `shopeasy_test_local`). The test runner's safety guard will reject any URL targeting non-local hosts, TiDB Cloud, `shopeasy_arya`, `shopeasy_app`, `shopeasy_dev`, or system databases.

---

## 4. Running Integration Tests

Navigate to `backend/` and run the MySQL-marked tests:

```bash
cd backend
python -m pytest -m mysql -v
```

To run both unit tests and MySQL integration tests:

```bash
python -m pytest -v
```

If `TEST_MYSQL_URL` is omitted or unset, all tests marked with `@pytest.mark.mysql` will automatically be skipped cleanly without error:
```text
Skipping MySQL test: TEST_MYSQL_URL not configured
```

---

## 5. Stopping the Test Container

When finished testing, stop the container:

```bash
docker compose -f docker-compose.test.yml down
```

---

## 6. Resetting Test Data

If you need a completely clean database state, remove the dedicated test volume:

```bash
docker compose -f docker-compose.test.yml down -v
```

> [!NOTE]
> This command removes only the dedicated `shopeasy_test_mysql_data` volume. It will not touch any production data, Docker images, or development volumes.

---

## 7. Automated Continuous Integration (GitHub Actions)

ShopEasy includes an automated GitHub Actions pipeline (`.github/workflows/ci.yml`) that runs on every push and pull request targeting `feature/arya-dual-plan-referral-platform`.

### What CI Runs
1. **Python Compilation:** Checks all backend Python files for syntax errors using `compileall`.
2. **Unit Tests:** Executes all fast, isolated SQLite tests (`python -m pytest -m unit`).
3. **MySQL Integration Tests:** Runs tests against a fresh ephemeral MySQL 8.0 service container (`python -m pytest -m mysql`).
4. **Full Regression Suite:** Runs the entire pytest suite (`python -m pytest`).
5. **Alembic Migration Verification:** Validates that `alembic upgrade head` runs cleanly against MySQL 8.0.

### Database Isolation in CI
- The CI pipeline spins up an isolated MySQL 8.0 service container initialized with database `shopeasy_test_ci` and ephemeral runner-only credentials.
- CI tests connect strictly to `127.0.0.1:3306/shopeasy_test_ci`.
- TiDB Cloud hosts and production schemas (`shopeasy_arya`, `shopeasy_app`, etc.) are actively blocked by the global connection guard.

### Local Development Independence
- Local Docker Desktop is **not** required for code development or unit testing; developers can run `python -m pytest -m unit` locally at any time.
- Full integration test coverage against real MySQL 8.0 is automatically guaranteed by GitHub-hosted Ubuntu runners in CI.

### Viewing Workflow Results
- Navigate to the **Actions** tab in the GitHub repository.
- Select the latest run under **ShopEasy CI** to view detailed logs and step-by-step verification output.
