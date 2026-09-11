from __future__ import annotations

import os
from pathlib import Path

from .database_config import database_schema, database_target, database_url


BASE_DIR = Path(__file__).resolve().parents[1]


class Config:
    ENV_NAME = os.getenv("AGRILINK_ENV", "development")
    DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"
    DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "")
    DATABASE_TARGET = database_target()
    DATABASE_SCHEMA = database_schema(DATABASE_TARGET)
    DATABASE_URL = database_url(
        strict=os.getenv("AGRILINK_DATABASE_TARGET", "").lower() == "supabase"
    )
    DATABASE_POOL_SIZE = int(os.getenv("DATABASE_POOL_SIZE", "5"))
    DATABASE_MAX_OVERFLOW = int(os.getenv("DATABASE_MAX_OVERFLOW", "5"))
    DATABASE_POOL_TIMEOUT = int(os.getenv("DATABASE_POOL_TIMEOUT", "10"))
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    SESSION_COOKIE_NAME = "agrilink_session"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    SESSION_HOURS = int(os.getenv("SESSION_HOURS", "8"))
    UPLOAD_FOLDER = Path(os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "instance" / "uploads"))).resolve()
    STATIC_FOLDER = Path(os.getenv("STATIC_FOLDER", str(BASE_DIR.parent / "frontend" / "dist"))).resolve()
    SERVE_FRONTEND = os.getenv("SERVE_FRONTEND", "false").lower() == "true"
    TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() == "true"
    MAX_CONTENT_LENGTH = int(os.getenv("UPLOAD_MAX_MB", "5")) * 1024 * 1024
    OUTBOX_POLL_SECONDS = float(os.getenv("OUTBOX_POLL_SECONDS", "3"))
    AI_ENABLED = os.getenv("AI_ENABLED", "false").lower() == "true"
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
    MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
    MISTRAL_TIMEOUT_SECONDS = float(os.getenv("MISTRAL_TIMEOUT_SECONDS", "20"))
    MISTRAL_MAX_TOKENS = int(os.getenv("MISTRAL_MAX_TOKENS", "700"))
    SIMULATED_TRACKING_ENABLED = os.getenv(
        "SIMULATED_TRACKING_ENABLED", "true" if ENV_NAME != "production" else "false"
    ).lower() == "true"
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@agrilink.local")
    PUSH_ENABLED = os.getenv("PUSH_ENABLED", "false").lower() == "true"
    RAZORPAY_ENABLED = os.getenv("RAZORPAY_ENABLED", "false").lower() == "true"
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
