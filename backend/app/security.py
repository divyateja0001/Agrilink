from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Callable
from uuid import UUID

from flask import current_app, g, jsonify, request
from sqlalchemy import select

from .db import get_session
from .models import FpoAuthorization, Membership, Organization, User, UserSession


@dataclass
class Principal:
    user: User
    memberships: list[Membership]
    organizations: dict[UUID, Organization]

    @property
    def roles(self) -> set[str]:
        return {m.role for m in self.memberships if m.is_active}

    @property
    def organization_ids(self) -> set[UUID]:
        return {m.organization_id for m in self.memberships if m.is_active}

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_user_session(user: User) -> tuple[UserSession, str]:
    raw = secrets.token_urlsafe(40)
    record = UserSession(
        user_id=user.id,
        token_hash=hash_token(raw),
        csrf_token=secrets.token_urlsafe(32),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=current_app.config["SESSION_HOURS"]),
    )
    get_session().add(record)
    return record, raw


def load_principal() -> Principal | None:
    raw = request.cookies.get(current_app.config["SESSION_COOKIE_NAME"])
    if not raw:
        return None
    db = get_session()
    session_record = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_token(raw))
    )
    now = datetime.now(timezone.utc)
    if not session_record or session_record.revoked_at or session_record.expires_at <= now:
        return None
    user = db.get(User, session_record.user_id)
    if not user or not user.is_active:
        return None
    memberships = list(
        db.scalars(select(Membership).where(Membership.user_id == user.id, Membership.is_active.is_(True)))
    )
    org_ids = [m.organization_id for m in memberships]
    organizations = {
        org.id: org for org in db.scalars(select(Organization).where(Organization.id.in_(org_ids or [UUID(int=0)])))
    }
    g.session_record = session_record
    g.principal = Principal(user=user, memberships=memberships, organizations=organizations)
    return g.principal


def require_auth(fn: Callable):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        principal = getattr(g, "principal", None) or load_principal()
        if not principal:
            return jsonify(error="authentication_required", message="Please sign in to continue."), 401
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = request.headers.get("X-CSRF-Token")
            if not csrf or not secrets.compare_digest(csrf, g.session_record.csrf_token):
                return jsonify(error="csrf_failed", message="Your form session expired. Refresh and try again."), 403
        return fn(*args, **kwargs)
    return wrapped


def require_roles(*roles: str):
    def decorator(fn: Callable):
        @wraps(fn)
        @require_auth
        def wrapped(*args, **kwargs):
            if not g.principal.has_role(*roles):
                return jsonify(error="permission_denied", message="You do not have access to this action."), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def can_access_farmer_org(principal: Principal, org_id: UUID) -> bool:
    if org_id in principal.organization_ids or principal.has_role("admin"):
        return True
    fpo_ids = [m.organization_id for m in principal.memberships if m.role == "fpo_manager"]
    if not fpo_ids:
        return False
    return get_session().scalar(
        select(FpoAuthorization.id).where(
            FpoAuthorization.fpo_organization_id.in_(fpo_ids),
            FpoAuthorization.farmer_organization_id == org_id,
            FpoAuthorization.is_active.is_(True),
        )
    ) is not None


def order_accessible(principal: Principal, order) -> bool:
    return (
        principal.has_role("admin")
        or order.buyer_organization_id in principal.organization_ids
        or order.supplier_organization_id in principal.organization_ids
        or (order.coordinating_fpo_id and order.coordinating_fpo_id in principal.organization_ids)
    )

