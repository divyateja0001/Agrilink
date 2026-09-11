from __future__ import annotations

from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .config import Config
from .db import get_session, init_engine
from .security import load_principal


def create_app(config_overrides=None):
    app = Flask(__name__, instance_relative_config=True, static_folder=None)
    app.config.from_object(Config)
    if config_overrides: app.config.update(config_overrides)
    if app.config["ENV_NAME"] == "production":
        if app.config["SECRET_KEY"] == "dev-only-change-me" or len(app.config["SECRET_KEY"]) < 32:
            raise RuntimeError("Production requires a random SECRET_KEY of at least 32 characters.")
        if not app.config["SESSION_COOKIE_SECURE"]:
            raise RuntimeError("Production requires SESSION_COOKIE_SECURE=true.")
        if app.config["DATABASE_TARGET"] != "supabase":
            raise RuntimeError("Production deployment requires AGRILINK_DATABASE_TARGET=supabase.")
        if app.config["DEMO_MODE"] and len(app.config["DEMO_PASSWORD"]) < 12:
            raise RuntimeError("DEMO_MODE requires a DEMO_PASSWORD of at least 12 characters.")
    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)
    init_engine(app)
    CORS(app, origins=[app.config["FRONTEND_ORIGIN"]], supports_credentials=True, allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"])
    limiter = Limiter(get_remote_address, app=app, default_limits=["300 per minute"], storage_uri="memory://")
    app.extensions["limiter"] = limiter

    from .routes.auth import bp as auth_bp
    from .routes.assistant import bp as assistant_bp
    from .routes.marketplace import bp as marketplace_bp
    from .routes.negotiations import bp as negotiations_bp
    from .routes.orders import bp as orders_bp
    from .routes.shared import bp as shared_bp
    from .routes.tracking import bp as tracking_bp
    app.register_blueprint(auth_bp); app.register_blueprint(marketplace_bp); app.register_blueprint(negotiations_bp); app.register_blueprint(assistant_bp); app.register_blueprint(orders_bp); app.register_blueprint(shared_bp); app.register_blueprint(tracking_bp)
    limiter.limit("60 per minute")(app.view_functions["auth.login"])
    limiter.limit("30 per minute")(app.view_functions["orders.confirm"])
    limiter.limit("10 per minute")(app.view_functions["assistant.procurement"])
    limiter.limit("20 per minute")(app.view_functions["assistant.send_conversation_message"])
    limiter.limit("60 per minute")(app.view_functions["negotiations.add_message"])
    limiter.limit("12 per minute")(app.view_functions["marketplace.begin_photo_capture"])
    limiter.limit("12 per minute")(app.view_functions["marketplace.upload_photo"])
    limiter.limit("10 per minute")(app.view_functions["orders.create_razorpay_order"])
    limiter.limit("30 per minute")(app.view_functions["orders.verify_razorpay_payment"])
    limiter.limit("30 per minute")(app.view_functions["tracking.start_tracking"])
    limiter.limit("30 per minute")(app.view_functions["tracking.stop_tracking"])
    limiter.limit("30 per minute")(app.view_functions["tracking.mark_arrival"])
    limiter.limit("120 per minute")(app.view_functions["tracking.add_location"])

    @app.before_request
    def principal_loader():
        load_principal()

    @app.get("/api/health")
    def health():
        try:
            get_session().execute(text("SELECT 1"))
        except SQLAlchemyError:
            app.logger.warning("Database readiness check failed")
            return jsonify(
                status="unavailable",
                service="agrilink-api",
                database="unavailable",
                target=app.config["DATABASE_TARGET"],
            ), 503
        return jsonify(
            status="ok",
            service="agrilink-api",
            database="ok",
            target=app.config["DATABASE_TARGET"],
        )

    @app.get("/uploads/<path:filename>")
    def uploads(filename):
        from flask import send_from_directory
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    if app.config["SERVE_FRONTEND"]:
        static_folder = Path(app.config["STATIC_FOLDER"])
        if not (static_folder / "index.html").is_file():
            raise RuntimeError(f"Built frontend was not found at {static_folder}.")

        @app.get("/")
        @app.get("/<path:frontend_path>")
        def frontend(frontend_path=""):
            if frontend_path == "api" or frontend_path.startswith(("api/", "uploads/")):
                abort(404)
            requested = static_folder / frontend_path
            if frontend_path and requested.is_file() and requested.resolve().is_relative_to(static_folder):
                response = send_from_directory(static_folder, frontend_path)
                if frontend_path.startswith("assets/"):
                    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return response
            return send_from_directory(static_folder, "index.html")

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(self), geolocation=(self), payment=(self)")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' https://checkout.razorpay.com; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https://tile.openstreetmap.org; font-src 'self'; "
            "connect-src 'self' https://api.razorpay.com https://checkout.razorpay.com https://*.razorpay.com wss://*.razorpay.com; "
            "frame-src https://api.razorpay.com https://checkout.razorpay.com https://*.razorpay.com; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc): return jsonify(error=exc.name.lower().replace(" ", "_"), message=exc.description), exc.code

    @app.errorhandler(Exception)
    def unexpected(exc):
        app.logger.exception("Unhandled request error")
        return jsonify(error="internal_error", message="An unexpected server error occurred."), 500

    return app
