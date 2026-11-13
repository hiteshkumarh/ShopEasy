import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi import status
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app

pytestmark = pytest.mark.unit


def test_api_health_endpoint(api_client: TestClient) -> None:
    """Verify root /api/health endpoint returns 200 and expected payload."""
    response = api_client.get("/api/health")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data == {"message": "ShopEasy backend is running"}


def test_api_health_db_endpoint(api_client: TestClient) -> None:
    """Verify /api/health/db successfully executes SELECT 1 against isolated test database."""
    response = api_client.get("/api/health/db")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


def test_api_health_db_failure_handling() -> None:
    """Verify /api/health/db returns HTTP 503 when the database query fails."""
    class FailingSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("Simulated database failure for testing")

    def broken_get_db():
        yield FailingSession()

    app.dependency_overrides[get_db] = broken_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/api/health/db")
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            data = response.json()
            assert data["status"] == "unhealthy"
            assert data["database"] == "disconnected"
            assert data["message"] == "Database connection could not be established."
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_safety_guard_blocks_tidb_connection_attempt() -> None:
    """Verify that automated tests are actively blocked from connecting to TiDB Cloud."""
    fake_tidb_engine = create_engine(
        "mysql+pymysql://user:pass@gateway01.ap-southeast-1.prod.aws.tidbcloud.com:4000/shopeasy_arya"
    )
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*live TiDB Cloud host"):
        fake_tidb_engine.connect()
