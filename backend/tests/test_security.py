from pathlib import Path

import pytest

from app import create_app


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json["status"] == "ok"
    assert response.json["database"] == "ok"
    assert response.json["target"] in {"local", "supabase"}


def test_anonymous_session_is_a_normal_signed_out_state(client):
    response = client.get("/api/auth/session")
    assert response.status_code == 200
    assert response.json == {"authenticated": False}


def test_admin_role_cannot_be_self_assigned(client):
    response = client.post("/api/auth/register", json={"email":"x@example.com","password":"long-enough-pass","full_name":"X","organization_name":"X org","location":"X","role":"admin"})
    assert response.status_code == 422


def test_suspended_account_gets_generic_login_failure(app):
    email = "suspended-farmer@example.com"
    registration = app.test_client().post("/api/auth/register", json={"email": email, "password": "long-enough-pass", "full_name": "Suspended Farmer", "organization_name": "Suspended Farm", "location": "Guntur", "role": "farmer"})
    assert registration.status_code == 201
    with app.app_context():
        from app.models import User
        session = app.extensions["session_factory"]()
        try:
            user = session.query(User).filter_by(email=email).one()
            user.is_active = False
            session.commit()
        finally:
            session.close()
    response = app.test_client().post("/api/auth/login", json={"email": email, "password": "long-enough-pass"})
    assert response.status_code == 401
    assert response.json["error"] == "invalid_credentials"
    assert "suspended" in response.json["message"]


def test_production_config_rejects_insecure_defaults(app):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({
            "ENV_NAME": "production",
            "DATABASE_URL": app.config["DATABASE_URL"],
            "SECRET_KEY": "dev-only-change-me",
        })


def test_built_frontend_and_security_headers_are_served(app):
    static_folder = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    production_like = create_app({
        "TESTING": True,
        "DATABASE_URL": app.config["DATABASE_URL"],
        "DATABASE_SCHEMA": app.config["DATABASE_SCHEMA"],
        "SERVE_FRONTEND": True,
        "STATIC_FOLDER": static_folder,
        "SESSION_COOKIE_SECURE": False,
    })
    client = production_like.test_client()
    home = client.get("/")
    assert home.status_code == 200
    assert b'<div id="root"></div>' in home.data
    assert home.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in home.headers["Content-Security-Policy"]
    assert client.get("/requirements/example").status_code == 200
    missing_api = client.get("/api/does-not-exist")
    assert missing_api.status_code == 404
    assert missing_api.is_json
