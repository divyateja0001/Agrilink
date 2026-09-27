import os
import sys
from pathlib import Path

# Add backend directory to sys.path so app imports work
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Ensure writable temp upload folder on Vercel lambda
os.environ.setdefault("UPLOAD_FOLDER", "/tmp/uploads")

from app import create_app

app = create_app()

class ApiPrefixMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path and not path.startswith("/api") and not path.startswith("/uploads"):
            environ["PATH_INFO"] = "/api" + path
        return self.app(environ, start_response)

app.wsgi_app = ApiPrefixMiddleware(app.wsgi_app)
