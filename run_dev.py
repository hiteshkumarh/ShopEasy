"""ShopEasy local development server launcher with optimized WatchFiles reload configuration.

Prevents KeyboardInterrupt and reload loops by:
- Setting reload directory explicitly to 'backend/app'.
- Debouncing rapid file modifications with a 0.5s reload delay.
- Excluding pytest cache, tests, virtual environment, and temporary files from watcher.
"""
import sys
import subprocess
from pathlib import Path

def main():
    root = Path(__file__).resolve().parent
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--reload",
        "--reload-dir",
        str(root / "backend" / "app"),
        "--reload-delay",
        "0.5",
        "--reload-exclude",
        "*.pytest_cache*",
        "--reload-exclude",
        "*__pycache__*",
        "--reload-exclude",
        "*.log",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--app-dir",
        str(root / "backend"),
    ]
    print("Starting ShopEasy dev server with optimized reload watcher:")
    print(" ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\nShopEasy server stopped gracefully.")

if __name__ == "__main__":
    main()
