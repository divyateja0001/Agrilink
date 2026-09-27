import os
import sys
from pathlib import Path

# Add root backend directory to sys.path so app imports work
backend_dir = Path(__file__).resolve().parent.parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Set safe environment defaults for Vercel serverless execution
os.environ.setdefault("AGRILINK_ENV", "development")
os.environ.setdefault("SECRET_KEY", "local-dev-secret-change-before-production-2026")
os.environ.setdefault("UPLOAD_FOLDER", "/tmp/uploads")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("DEMO_PASSWORD", "AgriLinkDemo!2026")

from app import create_app

app = create_app()
