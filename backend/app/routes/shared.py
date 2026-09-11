from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select

from ..db import get_session
from ..models import AuditEvent, Dispute, Membership, Notification, Organization, PushSubscription, User, UserSession
from ..security import require_auth, require_roles
from ..serializers import org_json, user_json
from ..services.audit import record_audit


bp = Blueprint("shared", __name__, url_prefix="/api")


@bp.get("/notifications")
@require_auth
def notifications():
    db = get_session(); items = list(db.scalars(select(Notification).where(Notification.user_id == g.principal.user.id).order_by(Notification.created_at.desc()).limit(50)))
    return jsonify(items=[{"id": str(x.id), "title": x.title, "body": x.body, "link": x.link, "read": bool(x.read_at), "created_at": x.created_at.isoformat()} for x in items], unread=sum(1 for x in items if not x.read_at))


@bp.post("/notifications/<uuid:notification_id>/read")
@require_auth
def read_notification(notification_id):
    db = get_session(); item = db.get(Notification, notification_id)
    if not item or item.user_id != g.principal.user.id: return jsonify(error="not_found", message="Notification not found."), 404
    item.read_at = datetime.now(timezone.utc); db.commit(); return jsonify(ok=True)


@bp.post("/notifications/read-all")
@require_auth
def read_all_notifications():
    db = get_session(); now = datetime.now(timezone.utc)
    for item in db.scalars(select(Notification).where(Notification.user_id == g.principal.user.id, Notification.read_at.is_(None))): item.read_at = now
    db.commit(); return jsonify(ok=True)


@bp.get("/push/config")
@require_auth
def push_config():
    from flask import current_app
    db = get_session()
    subscriptions = db.scalars(select(PushSubscription).where(PushSubscription.user_id == g.principal.user.id, PushSubscription.is_active.is_(True))).all()
    enabled = bool(current_app.config.get("PUSH_ENABLED") and current_app.config.get("VAPID_PUBLIC_KEY") and current_app.config.get("VAPID_PRIVATE_KEY"))
    return jsonify(enabled=enabled, public_key=current_app.config.get("VAPID_PUBLIC_KEY", "") if enabled else "", subscribed=bool(subscriptions), subscriptions=[{"id": str(item.id), "created_at": item.created_at.isoformat()} for item in subscriptions])


@bp.post("/push/subscriptions")
@require_auth
def create_push_subscription():
    data = request.get_json(silent=True) or {}; keys = data.get("keys") or {}
    endpoint = str(data.get("endpoint", "")).strip(); p256dh = str(keys.get("p256dh", "")).strip(); auth = str(keys.get("auth", "")).strip()
    if not endpoint.startswith("https://") or len(endpoint) > 4000 or not (20 <= len(p256dh) <= 500) or not (8 <= len(auth) <= 200):
        return jsonify(error="validation_error", message="The browser push subscription is invalid."), 422
    db = get_session(); item = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if item and item.user_id != g.principal.user.id:
        return jsonify(error="subscription_conflict", message="This browser subscription belongs to another account. Sign out there first."), 409
    if not item:
        item = PushSubscription(user_id=g.principal.user.id, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=request.headers.get("User-Agent", "")[:300]); db.add(item)
    else:
        item.p256dh = p256dh; item.auth = auth; item.is_active = True; item.failure_count = 0
    db.commit(); return jsonify(id=str(item.id), subscribed=True), 201


@bp.delete("/push/subscriptions/<uuid:subscription_id>")
@require_auth
def delete_push_subscription(subscription_id):
    db = get_session(); item = db.get(PushSubscription, subscription_id)
    if not item or item.user_id != g.principal.user.id: return jsonify(error="not_found", message="Push subscription not found."), 404
    item.is_active = False; db.commit(); return jsonify(subscribed=False)


@bp.patch("/profile")
@require_auth
def update_profile():
    data = request.get_json(silent=True) or {}; user = g.principal.user
    if "full_name" in data and str(data["full_name"]).strip(): user.full_name = str(data["full_name"]).strip()[:120]
    if "phone" in data: user.phone = str(data["phone"]).strip()[:30]
    if data.get("locale") in {"en", "te", "hi", "ta"}: user.locale = data["locale"]
    record_audit(get_session(), "profile.updated", "user", user.id, actor=user); get_session().commit()
    return jsonify(user_json(user))


@bp.get("/admin/participants")
@require_roles("admin")
def participants():
    db = get_session(); users = list(db.scalars(select(User).order_by(User.full_name)))
    items = []
    for user in users:
        memberships = list(db.scalars(select(Membership).where(Membership.user_id == user.id)))
        items.append({**user_json(user), "memberships": [{"role": m.role, "organization": org_json(db.get(Organization, m.organization_id))} for m in memberships]})
    return jsonify(items=items)


@bp.post("/admin/users/<uuid:user_id>/suspension")
@require_roles("admin")
def suspend(user_id):
    db = get_session(); user = db.get(User, user_id); data = request.get_json(silent=True) or {}
    if not user: return jsonify(error="not_found", message="User not found."), 404
    if user.id == g.principal.user.id: return jsonify(error="invalid_operation", message="You cannot suspend your own account."), 422
    user.is_active = not bool(data.get("suspended", True))
    if not user.is_active:
        for session in db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))): session.revoked_at = datetime.now(timezone.utc)
    record_audit(db, "admin.user_suspension_changed", "user", user.id, actor=g.principal.user, details={"is_active": user.is_active}); db.commit()
    return jsonify(user=user_json(user))


@bp.get("/admin/disputes")
@require_roles("admin")
def disputes():
    db = get_session(); items = db.scalars(select(Dispute).order_by(Dispute.created_at.desc())).all()
    return jsonify(items=[{"id": str(x.id), "order_id": str(x.order_id), "category": x.category, "affected_quantity_kg": float(x.affected_quantity_kg) if x.affected_quantity_kg is not None else None, "reason": x.reason, "requested_resolution": x.requested_resolution, "status": x.status, "resolution": x.resolution, "created_at": x.created_at.isoformat()} for x in items])


@bp.patch("/admin/disputes/<uuid:dispute_id>")
@require_roles("admin")
def review_dispute(dispute_id):
    db = get_session(); dispute = db.get(Dispute, dispute_id); data = request.get_json(silent=True) or {}
    if not dispute: return jsonify(error="not_found", message="Dispute not found."), 404
    if data.get("status") not in {"under_review", "resolved", "rejected"}: return jsonify(error="validation_error", message="Invalid dispute status."), 422
    dispute.status = data["status"]; dispute.resolution = str(data.get("resolution", "")).strip(); dispute.reviewed_by_user_id = g.principal.user.id
    record_audit(db, "admin.dispute_reviewed", "dispute", dispute.id, actor=g.principal.user, details={"status": dispute.status}); db.commit()
    return jsonify(id=str(dispute.id), status=dispute.status, resolution=dispute.resolution)


@bp.get("/admin/audit")
@require_roles("admin")
def audit():
    db = get_session(); events = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(200)).all()
    return jsonify(items=[{"id": str(x.id), "action": x.action, "entity_type": x.entity_type, "entity_id": str(x.entity_id) if x.entity_id else None, "actor_user_id": str(x.actor_user_id) if x.actor_user_id else None, "details": x.details, "created_at": x.created_at.isoformat()} for x in events])
