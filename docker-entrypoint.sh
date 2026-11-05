#!/bin/sh
set -e

echo "=== ShopEasy Container Initialization ==="

# Database operations are intentionally manual and are not part of web-service
# startup. Run these explicitly from /app/backend when appropriate:
#   alembic upgrade head
#   python -m app.core.seed

# Render supplies PORT at runtime. Keep a local/container fallback.
APP_PORT="${PORT:-10000}"
echo "Starting FastAPI application server on 0.0.0.0:${APP_PORT}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}"
