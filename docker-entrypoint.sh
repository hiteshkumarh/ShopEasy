#!/bin/sh
set -e

echo "=== ShopEasy Container Initialization ==="

# 1. Run database migrations to ensure all 16 tables exist
echo "Applying database migrations (alembic upgrade head)..."
alembic upgrade head

# 2. Seed baseline admin account and QueueControl (idempotent, 0 products)
echo "Provisioning baseline data (admin account & queue control)..."
python -m app.core.seed

# 3. Start Uvicorn application server
echo "Starting FastAPI application server on 0.0.0.0:8000..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
