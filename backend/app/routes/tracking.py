from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..db import get_session
from ..models import (
    Dispatch,
    DispatchDriverAssignment,
    DispatchLocation,
    Membership,
    Order,
    TrackingEvent,
    User,
)
from ..security import order_accessible, require_auth, require_roles
from ..services.audit import record_audit
from ..services.outbox import enqueue
from ..services.tracking import ACTIVE_ORDER_STATUSES, assign_driver, driver_assignment, tracking_payload


bp = Blueprint("tracking", __name__, url_prefix="/api")


def _dispatch_order(db, dispatch_id):
    dispatch = db.get(Dispatch, dispatch_id)
    return dispatch, db.get(Order, dispatch.order_id) if dispatch else None


def _assigned_to_principal(db, dispatch_id, *, lock=False):
    return driver_assignment(db, dispatch_id, user_id=g.principal.user.id, lock=lock)


def _parse_timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise ValueError("captured_at must be an ISO timestamp with a timezone.")


@bp.get("/tracking/drivers")
@require_roles("farmer", "fpo_manager", "admin")
def list_drivers():
    db = get_session()
    users = db.scalars(
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(User.is_active.is_(True), Membership.is_active.is_(True), Membership.role == "driver")
        .order_by(User.full_name)
    ).all()
    return jsonify(items=[{"id": str(user.id), "name": user.full_name, "email": user.email, "phone": user.phone} for user in users])


@bp.post("/dispatches/<uuid:dispatch_id>/driver")
@require_roles("farmer", "fpo_manager", "admin")
def set_dispatch_driver(dispatch_id):
    db = get_session(); dispatch, order = _dispatch_order(db, dispatch_id); data = request.get_json(silent=True) or {}
    if not dispatch or not order:
        return jsonify(error="not_found", message="Dispatch not found."), 404
    supplier = order.supplier_organization_id in g.principal.organization_ids or (order.coordinating_fpo_id and order.coordinating_fpo_id in g.principal.organization_ids)
    if not g.principal.has_role("admin") and not supplier:
        return jsonify(error="permission_denied", message="Only this dispatch's supplier can assign its driver."), 403
    email = str(data.get("driver_email", "")).strip().lower()
    driver = db.scalar(select(User).where(func.lower(User.email) == email, User.is_active.is_(True)))
    if not driver:
        return jsonify(error="validation_error", message="Choose an active AgriLink driver account."), 422
    try:
        assignment = assign_driver(db, dispatch=dispatch, driver=driver, actor=g.principal.user, vehicle_registration=data.get("vehicle_registration"))
    except ValueError as exc:
        return jsonify(error="validation_error", message=str(exc)), 422
    record_audit(db, "dispatch.driver_assigned", "dispatch", dispatch.id, actor=g.principal.user, organization_id=order.supplier_organization_id, details={"driver_user_id": str(driver.id)})
    db.commit()
    return jsonify(tracking_payload(db, assignment)), 200


@bp.get("/driver/dispatches")
@require_roles("driver")
def driver_dispatches():
    db = get_session()
    assignments = db.scalars(
        select(DispatchDriverAssignment)
        .where(DispatchDriverAssignment.driver_user_id == g.principal.user.id, DispatchDriverAssignment.is_active.is_(True))
        .order_by(DispatchDriverAssignment.updated_at.desc())
    ).all()
    return jsonify(items=[tracking_payload(db, item) for item in assignments])


@bp.get("/dispatches/<uuid:dispatch_id>/tracking")
@require_auth
def get_dispatch_tracking(dispatch_id):
    db = get_session(); dispatch, order = _dispatch_order(db, dispatch_id)
    if not dispatch or not order:
        return jsonify(error="not_found", message="Dispatch not found."), 404
    assignment = driver_assignment(db, dispatch.id)
    permitted_driver = assignment and assignment.driver_user_id == g.principal.user.id
    if not assignment:
        return jsonify(error="tracking_not_assigned", message="No driver is assigned to this dispatch."), 404
    if not permitted_driver and not order_accessible(g.principal, order):
        return jsonify(error="permission_denied", message="You cannot view this private dispatch."), 403
    return jsonify(tracking_payload(db, assignment))


@bp.post("/dispatches/<uuid:dispatch_id>/tracking/start")
@require_roles("driver")
def start_tracking(dispatch_id):
    db = get_session(); assignment = _assigned_to_principal(db, dispatch_id, lock=True); data = request.get_json(silent=True) or {}
    if not assignment:
        return jsonify(error="permission_denied", message="This dispatch is not assigned to you."), 403
    dispatch, order = _dispatch_order(db, dispatch_id)
    if order.status not in ACTIVE_ORDER_STATUSES or assignment.sharing_status == "arrived":
        return jsonify(error="invalid_status", message="Tracking cannot start after this delivery is completed or cancelled."), 409
    mode = str(data.get("mode", "real"))
    if mode not in {"real", "simulated"}:
        return jsonify(error="validation_error", message="Choose real or simulated tracking."), 422
    if mode == "simulated" and not current_app.config["SIMULATED_TRACKING_ENABLED"]:
        return jsonify(error="simulation_disabled", message="Simulated tracking is disabled in this environment."), 403
    assignment.tracking_mode = mode
    assignment.sharing_status = "sharing"
    assignment.started_at = datetime.now(timezone.utc)
    assignment.stopped_at = None
    assignment.version += 1
    dispatch.status = "in_transit"
    record_audit(db, "dispatch.tracking_started", "dispatch", dispatch.id, actor=g.principal.user, details={"mode": mode})
    db.commit()
    return jsonify(tracking_payload(db, assignment))


@bp.post("/dispatches/<uuid:dispatch_id>/locations")
@require_roles("driver")
def add_location(dispatch_id):
    db = get_session(); assignment = _assigned_to_principal(db, dispatch_id, lock=True); data = request.get_json(silent=True) or {}
    if not assignment:
        return jsonify(error="permission_denied", message="This dispatch is not assigned to you."), 403
    dispatch, order = _dispatch_order(db, dispatch_id)
    if assignment.sharing_status != "sharing" or order.status not in ACTIVE_ORDER_STATUSES:
        return jsonify(error="tracking_stopped", message="Location sharing is not active for this dispatch."), 409
    try:
        latitude = Decimal(str(data.get("latitude")))
        longitude = Decimal(str(data.get("longitude")))
        accuracy = Decimal(str(data.get("accuracy_m")))
        captured_at = _parse_timestamp(data.get("captured_at"))
    except (InvalidOperation, ValueError) as exc:
        return jsonify(error="validation_error", message=str(exc) if str(exc) else "Enter valid coordinates and accuracy."), 422
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180) or not (0 < accuracy <= 5000):
        return jsonify(error="validation_error", message="Coordinates or accuracy are outside valid ranges."), 422
    now = datetime.now(timezone.utc)
    if captured_at < now - timedelta(minutes=2) or captured_at > now + timedelta(seconds=30):
        return jsonify(error="stale_location", message="This location timestamp is stale or too far in the future."), 409
    client_update_id = str(data.get("client_update_id", "")).strip()
    try:
        uuid.UUID(client_update_id)
    except (ValueError, TypeError):
        return jsonify(error="validation_error", message="client_update_id must be a UUID."), 422
    existing = db.scalar(select(DispatchLocation).where(DispatchLocation.dispatch_id == dispatch_id, DispatchLocation.client_update_id == client_update_id))
    if existing:
        return jsonify(id=str(existing.id), duplicate=True), 200
    latest = db.scalar(select(DispatchLocation).where(DispatchLocation.dispatch_id == dispatch_id).order_by(DispatchLocation.captured_at.desc()).limit(1))
    if latest and captured_at <= latest.captured_at:
        return jsonify(error="stale_location", message="A newer location is already stored for this dispatch."), 409
    item = DispatchLocation(
        dispatch_id=dispatch.id,
        driver_user_id=g.principal.user.id,
        latitude=latitude,
        longitude=longitude,
        accuracy_m=accuracy,
        captured_at=captured_at,
        received_at=now,
        is_simulated=assignment.tracking_mode == "simulated",
        client_update_id=client_update_id,
    )
    db.add(item); assignment.last_location_at = captured_at; assignment.version += 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return jsonify(duplicate=True), 200
    return jsonify(id=str(item.id), captured_at=item.captured_at.isoformat(), simulated=item.is_simulated), 201


@bp.post("/dispatches/<uuid:dispatch_id>/tracking/stop")
@require_roles("driver")
def stop_tracking(dispatch_id):
    db = get_session(); assignment = _assigned_to_principal(db, dispatch_id, lock=True)
    if not assignment:
        return jsonify(error="permission_denied", message="This dispatch is not assigned to you."), 403
    if assignment.sharing_status == "arrived":
        return jsonify(error="invalid_status", message="This dispatch has already arrived."), 409
    assignment.sharing_status = "stopped"; assignment.stopped_at = datetime.now(timezone.utc); assignment.version += 1
    record_audit(db, "dispatch.tracking_stopped", "dispatch", dispatch_id, actor=g.principal.user)
    db.commit()
    return jsonify(tracking_payload(db, assignment))


@bp.post("/dispatches/<uuid:dispatch_id>/tracking/arrival")
@require_roles("driver")
def mark_arrival(dispatch_id):
    db = get_session(); assignment = _assigned_to_principal(db, dispatch_id, lock=True)
    if not assignment:
        return jsonify(error="permission_denied", message="This dispatch is not assigned to you."), 403
    dispatch, order = _dispatch_order(db, dispatch_id)
    if assignment.sharing_status == "arrived":
        return jsonify(tracking_payload(db, assignment))
    if order.status not in ACTIVE_ORDER_STATUSES:
        return jsonify(error="invalid_status", message="This delivery can no longer be marked arrived."), 409
    now = datetime.now(timezone.utc)
    assignment.sharing_status = "arrived"; assignment.arrived_at = now; assignment.stopped_at = now; assignment.version += 1
    dispatch.status = "arrived"
    event = TrackingEvent(order_id=order.id, actor_user_id=g.principal.user.id, status="arrived", note=f"Vehicle {assignment.vehicle_registration} reached the recorded destination. Buyer receipt is still required.")
    db.add(event); db.flush()
    enqueue(db, "dispatch.arrived", {"organization_id": str(order.buyer_organization_id), "title": "Delivery vehicle arrived", "body": f"{dispatch.reference} arrived for {order.order_number}. Record receipt separately after checking the produce.", "link": "/tracking"}, f"dispatch:{dispatch.id}:arrived")
    record_audit(db, "dispatch.arrived", "dispatch", dispatch.id, actor=g.principal.user)
    db.commit()
    return jsonify(tracking_payload(db, assignment))
