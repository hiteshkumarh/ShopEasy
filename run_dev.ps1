# ShopEasy local development server launcher with optimized WatchFiles reload configuration
$ErrorActionPreference = "Stop"
Write-Host "Starting ShopEasy dev server with optimized reload watcher..." -ForegroundColor Cyan

python -m uvicorn app.main:app `
    --reload `
    --reload-dir "$PSScriptRoot/backend/app" `
    --reload-delay 0.5 `
    --reload-exclude "*.pytest_cache*" `
    --reload-exclude "*__pycache__*" `
    --reload-exclude "*.log*" `
    --host 127.0.0.1 `
    --port 8000 `
    --app-dir "$PSScriptRoot/backend"
