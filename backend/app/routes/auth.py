from __future__ import annotations

import re
from datetime import datetime, timezone

from flask import Blueprint, current_app, g, jsonify, make_response, request
from sqlalchemy import func, select
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_session
from ..models import AuditEvent, Membership, Organization, User, UserSession
from ..security import create_user_session, hash_token, load_principal, require_auth
from ..serializers import org_json, user_json
from ..services.audit import record_audit


bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def set_session_cookie(response, raw, expires):
    response.set_cookie(
        current_app.config["SESSION_COOKIE_NAME"], raw,
        httponly=True, secure=current_app.config["SESSION_COOKIE_SECURE"], samesite="Lax",
        expires=expires, path="/",
    )


@bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    role = data.get("role")
    if role not in {"farmer", "buyer"}:
        return jsonify(error="invalid_role", message="Public registration is available only for farmers and buyers."), 422
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    full_name = str(data.get("full_name", "")).strip()
    org_name = str(data.get("organization_name", "")).strip()
    location = str(data.get("location", "")).strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) or len(password) < 10 or not full_name or not org_name or not location:
        return jsonify(error="validation_error", message="Enter a valid email, a 10-character password, name, organization, and location."), 422
    db = get_session()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        return jsonify(error="email_exists", message="An account already uses this email."), 409
    user = User(email=email, password_hash=generate_password_hash(password), full_name=full_name)
    org = Organization(name=org_name, org_type="farm" if role == "farmer" else "buyer", location=location)
    db.add_all([user, org]); db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=role))
    record_audit(db, "auth.registered", "user", user.id, actor=user, organization_id=org.id)
    session_record, raw = create_user_session(user)
    db.commit()
    response = make_response(jsonify(user=user_json(user), memberships=[{"role": role, "organization": org_json(org)}], csrf_token=session_record.csrf_token), 201)
    set_session_cookie(response, raw, session_record.expires_at)
    return response


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    db = get_session()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if not user or not user.is_active or not check_password_hash(user.password_hash, password):
        return jsonify(error="invalid_credentials", message="Email or password is incorrect, or this account is suspended."), 401
    record, raw = create_user_session(user)
    record_audit(db, "auth.login", "user", user.id, actor=user)
    db.commit()
    memberships = list(db.scalars(select(Membership).where(Membership.user_id == user.id, Membership.is_active.is_(True))))
    organizations = {m.organization_id: db.get(Organization, m.organization_id) for m in memberships}
    response = make_response(jsonify(
        authenticated=True,
        user=user_json(user),
        memberships=[{"id": str(m.id), "role": m.role, "organization": org_json(organizations[m.organization_id])} for m in memberships],
        roles=sorted({m.role for m in memberships}),
        csrf_token=record.csrf_token,
    ), 200)
    set_session_cookie(response, raw, record.expires_at)
    return response


@bp.post("/logout")
@require_auth
def logout():
    g.session_record.revoked_at = datetime.now(timezone.utc)
    record_audit(get_session(), "auth.logout", "user", g.principal.user.id, actor=g.principal.user)
    get_session().commit()
    response = make_response(jsonify(ok=True))
    response.delete_cookie(current_app.config["SESSION_COOKIE_NAME"], path="/")
    return response


@bp.get("/session")
def current_session():
    principal = load_principal()
    if not principal:
        return jsonify(authenticated=False)
    memberships = [{"id": str(m.id), "role": m.role, "organization": org_json(principal.organizations[m.organization_id])} for m in principal.memberships]
    return jsonify(authenticated=True, user=user_json(principal.user), memberships=memberships, roles=sorted(principal.roles), csrf_token=g.session_record.csrf_token)
