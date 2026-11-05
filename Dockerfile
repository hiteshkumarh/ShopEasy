# =============================================================================
# ShopEasy — Production Container Image
# Multi-tiered Architecture: FastAPI Backend + Vanilla Frontend
# =============================================================================
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python runtime dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend application and database migrations
COPY backend /app/backend

# Copy frontend assets and templates
COPY frontend /app/frontend

# Copy and prepare entrypoint script (normalize Windows CRLF line endings)
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh && \
    chmod +x /app/docker-entrypoint.sh

# Ensure uploads directory exists inside container
RUN mkdir -p /app/frontend/uploads

# Set working directory to backend for direct Alembic and Python module resolution
WORKDIR /app/backend

# Expose Render's default web-service port. Render still routes the runtime
# PORT environment variable to the process started by docker-entrypoint.sh.
EXPOSE 10000

# Container entrypoint launches Uvicorn only; migrations and seeding are manual.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
