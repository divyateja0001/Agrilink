from __future__ import annotations

import csv
import base64
import hashlib
import hmac
import io
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from flask import Blueprint, Response, current_app, g, jsonify, request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from ..db import get_session
from ..models import (
    Dispatch, DispatchDriverAssignment, DispatchLine, Dispute, DisputeEvidence, Membership, Order, OrderComment, OrderLine, OrderRating, Organization,
    PaymentEvent, Quotation, Receipt, ReceiptLine, StockReservation, TrackingEvent, User,
)
from ..security import order_accessible, require_auth, require_roles
from ..services.audit import record_audit
from ..services.orders import DomainError, confirm_quotes, dispatch_order, receive_order, record_payment
from ..services.outbox import enqueue
from ..services.reviews import rating_summary, review_json
from ..services.tracking import assign_driver


bp = Blueprint("orders", __name__, url_prefix="/api")


def detail(db, order):
    lines = list(db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)))
    line_items = []
    for line in lines:
        reservation = db.scalar(select(StockReservation).where(StockReservation.order_line_id == line.id))
        dispatched = Decimal(db.scalar(select(func.coalesce(func.sum(DispatchLine.quantity_kg), 0)).where(DispatchLine.order_line_id == line.id)) or 0)
        received = Decimal(db.scalar(select(func.coalesce(func.sum(ReceiptLine.quantity_kg), 0)).where(ReceiptLine.order_line_id == line.id)) or 0)
        line_items.append({
            "id": str(line.id), "produce_lot_id": str(line.produce_lot_id), "farmer_organization_id": str(line.farmer_organization_id),
            "crop": line.crop, "variety": line.variety, "quality_grade": line.quality_grade,
            "agreed_quantity_kg": float(line.agreed_quantity_kg), "agreed_price_paise_per_kg": line.agreed_price_paise_per_kg,
            "total_paise": int(Decimal(line.agreed_quantity_kg) * line.agreed_price_paise_per_kg), "delivery_terms": line.delivery_terms,
            "reserved_remaining_kg": float(Decimal(reservation.reserved_quantity_kg) - Decimal(reservation.dispatched_quantity_kg) - Decimal(reservation.released_quantity_kg)),
            "dispatched_kg": float(dispatched), "received_kg": float(received), "outstanding_kg": float(Decimal(line.agreed_quantity_kg) - received),
        })
    paid_paise = int(db.scalar(select(func.coalesce(func.sum(PaymentEvent.amount_paise), 0)).where(PaymentEvent.order_id == order.id, PaymentEvent.outcome == "success")) or 0)
    receipt_value = sum(int(Decimal(str(x["received_kg"])) * x["agreed_price_paise_per_kg"]) for x in line_items)
    deductions = int(db.scalar(select(func.coalesce(func.sum(ReceiptLine.deduction_paise), 0)).join(Receipt).where(Receipt.order_id == order.id)) or 0)
    payable = max(0, receipt_value - deductions + (order.delivery_charge_paise if receipt_value else 0) - paid_paise)
    tracking = list(db.scalars(select(TrackingEvent).where(TrackingEvent.order_id == order.id).order_by(TrackingEvent.created_at)))
    dispatches = list(db.scalars(select(Dispatch).where(Dispatch.order_id == order.id).order_by(Dispatch.dispatched_at)))
    supplier = db.get(Organization, order.supplier_organization_id)
    coordinator = db.get(Organization, order.coordinating_fpo_id) if order.coordinating_fpo_id else None
    ratings = list(db.scalars(select(OrderRating).where(OrderRating.order_id == order.id).order_by(OrderRating.reviewed_role)))
    return {
        "id": str(order.id), "order_number": order.order_number, "order_group_id": str(order.order_group_id), "requirement_id": str(order.requirement_id),
        "buyer_organization_id": str(order.buyer_organization_id), "supplier_organization_id": str(order.supplier_organization_id),
        "coordinating_fpo_id": str(order.coordinating_fpo_id) if order.coordinating_fpo_id else None,
        "status": order.status, "payment_status": order.payment_status, "delivery_deadline": order.delivery_deadline.isoformat(), "version": order.version,
        "delivery_mode": order.delivery_mode, "delivery_charge_paise": order.delivery_charge_paise,
        "supplier": {"id": str(supplier.id), "name": supplier.name, "type": supplier.org_type} if supplier else None,
        "coordinating_fpo": {"id": str(coordinator.id), "name": coordinator.name, "type": coordinator.org_type} if coordinator else None,
        "review_eligible": order.status == "received" and bool(line_items) and all(x["outstanding_kg"] == 0 for x in line_items),
        "reviews": [review_json(db, rating, include_buyer=True) for rating in ratings],
        "lines": line_items, "total_paise": sum(x["total_paise"] for x in line_items), "payable_paise": payable,
        "tracking_events": [{"id": str(x.id), "status": x.status, "note": x.note, "created_at": x.created_at.isoformat()} for x in tracking],
        "dispatches": [dispatch_json(db, x) for x in dispatches],
    }


def dispatch_json(db, dispatch):
    assignment = db.scalar(select(DispatchDriverAssignment).where(DispatchDriverAssignment.dispatch_id == dispatch.id, DispatchDriverAssignment.is_active.is_(True)))
    driver = db.get(User, assignment.driver_user_id) if assignment else None
    return {
        "id": str(dispatch.id), "reference": dispatch.reference, "status": dispatch.status,
        "carrier_name": dispatch.carrier_name, "carrier_phone": dispatch.carrier_phone,
        "note": dispatch.note, "created_at": dispatch.dispatched_at.isoformat(),
        "tracking_assigned": bool(assignment),
        "sharing_status": assignment.sharing_status if assignment else None,
        "tracking_mode": assignment.tracking_mode if assignment else None,
        "vehicle_registration": assignment.vehicle_registration if assignment else None,
        "driver_name": driver.full_name if driver else None,
    }


@bp.get("/orders")
@require_auth
def list_orders():
    db = get_session(); principal = g.principal
    query = select(Order).order_by(Order.created_at.desc())
    if not principal.has_role("admin"):
        query = query.where(or_(
            Order.buyer_organization_id.in_(principal.organization_ids),
            Order.supplier_organization_id.in_(principal.organization_ids),
            Order.coordinating_fpo_id.in_(principal.organization_ids),
        ))
    return jsonify(items=[detail(db, x) for x in db.scalars(query.limit(100))])


@bp.get("/orders/<uuid:order_id>")
@require_auth
def get_order(order_id):
    db = get_session(); order = db.get(Order, order_id)
    if not order: return jsonify(error="not_found", message="Order not found."), 404
    if not order_accessible(g.principal, order): return jsonify(error="permission_denied", message="You cannot access this private order."), 403
    data = detail(db, order)
    data["comments"] = [{"id": str(x.id), "body": x.body, "author_user_id": str(x.author_user_id), "created_at": x.created_at.isoformat()} for x in db.scalars(select(OrderComment).where(OrderComment.order_id == order.id).order_by(OrderComment.created_at))]
    data["payment_events"] = [{"id": str(x.id), "amount_paise": x.amount_paise, "outcome": x.outcome, "reference": x.external_reference, "simulated": True, "created_at": x.created_at.isoformat()} for x in db.scalars(select(PaymentEvent).where(PaymentEvent.order_id == order.id))]
    return jsonify(data)


@bp.post("/requirements/<uuid:req_id>/confirm")
@require_roles("buyer")
def confirm(req_id):
    data = request.get_json(silent=True) or {}
    buyer_org_id = next((m.organization_id for m in g.principal.memberships if m.role == "buyer"), None)
    try:
        quote_ids = [uuid.UUID(x) for x in data.get("quotation_ids", [])]
        if not quote_ids: raise DomainError("Select at least one quotation.")
        db = get_session()
        response = confirm_quotes(db, actor=g.principal.user, buyer_org_id=buyer_org_id, requirement_id=req_id, quotation_ids=quote_ids, key=request.headers.get("Idempotency-Key", ""), payload=data)
        db.commit(); return jsonify(response), 201
    except DomainError as exc:
        get_session().rollback(); return jsonify(error=exc.code, message=exc.message), exc.status
    except (ValueError, TypeError):
        get_session().rollback(); return jsonify(error="validation_error", message="Quotation IDs are invalid."), 422


@bp.post("/orders/<uuid:order_id>/dispatches")
@require_roles("farmer", "fpo_manager")
def create_dispatch(order_id):
    db = get_session(); order = db.get(Order, order_id); data = request.get_json(silent=True) or {}
    if not order: return jsonify(error="not_found", message="Order not found."), 404
    if not order_accessible(g.principal, order) or order.buyer_organization_id in g.principal.organization_ids:
        return jsonify(error="permission_denied", message="Only an authorized supplier can dispatch this order."), 403
    try:
        driver = None
        if data.get("driver_email"):
            driver = db.scalar(select(User).where(func.lower(User.email) == str(data["driver_email"]).strip().lower(), User.is_active.is_(True)))
            if not driver or not db.scalar(select(Membership.id).where(Membership.user_id == driver.id, Membership.role == "driver", Membership.is_active.is_(True))):
                return jsonify(error="validation_error", message="Choose an active AgriLink driver account."), 422
        result = dispatch_order(db, actor=g.principal.user, order=order, lines=data.get("lines", []), reference=str(data.get("reference", "")).strip(), note=str(data.get("note", "")), key=request.headers.get("Idempotency-Key", ""), payload=data)
        if driver:
            dispatch = db.get(Dispatch, uuid.UUID(result["dispatch_id"]))
            assign_driver(db, dispatch=dispatch, driver=driver, actor=g.principal.user, vehicle_registration=data.get("vehicle_registration") or data.get("reference"))
        db.commit(); return jsonify(result), 201
    except (DomainError, ValueError) as exc:
        db.rollback(); return jsonify(error=getattr(exc, "code", "validation_error"), message=getattr(exc, "message", str(exc))), getattr(exc, "status", 422)


@bp.post("/orders/<uuid:order_id>/receipts")
@require_roles("buyer")
def create_receipt(order_id):
    db = get_session(); order = db.get(Order, order_id); data = request.get_json(silent=True) or {}
    if not order: return jsonify(error="not_found", message="Order not found."), 404
    if order.buyer_organization_id not in g.principal.organization_ids: return jsonify(error="permission_denied", message="Only the buyer can record receipt."), 403
    try:
        result = receive_order(db, actor=g.principal.user, order=order, lines=data.get("lines", []), note=str(data.get("note", "")), key=request.headers.get("Idempotency-Key", ""), payload=data)
        db.commit(); return jsonify(result), 201
    except (DomainError, ValueError) as exc:
        db.rollback(); return jsonify(error=getattr(exc, "code", "validation_error"), message=getattr(exc, "message", str(exc))), getattr(exc, "status", 422)


@bp.post("/orders/<uuid:order_id>/payments")
@require_roles("buyer")
def create_payment(order_id):
    db = get_session(); order = db.get(Order, order_id); data = request.get_json(silent=True) or {}
    if not order: return jsonify(error="not_found", message="Order not found."), 404
    if order.buyer_organization_id not in g.principal.organization_ids: return jsonify(error="permission_denied", message="Only the buyer can record payment."), 403
    try:
        result = record_payment(db, actor=g.principal.user, order=order, amount_paise=int(data.get("amount_paise", 0)), outcome=str(data.get("outcome", "")), key=request.headers.get("Idempotency-Key", ""), payload=data)
        db.commit(); return jsonify(result), 201
    except (DomainError, ValueError, TypeError) as exc:
        db.rollback(); return jsonify(error=getattr(exc, "code", "validation_error"), message=getattr(exc, "message", str(exc))), getattr(exc, "status", 422)


@bp.post("/orders/<uuid:order_id>/comments")
@require_auth
def add_comment(order_id):
    db = get_session(); order = db.get(Order, order_id); body = str((request.get_json(silent=True) or {}).get("body", "")).strip()
    if not order or not order_accessible(g.principal, order): return jsonify(error="permission_denied", message="You cannot comment on this order."), 403
    if not body or len(body) > 2000: return jsonify(error="validation_error", message="Comment must be between 1 and 2,000 characters."), 422
    comment = OrderComment(order_id=order.id, author_user_id=g.principal.user.id, body=body); db.add(comment); db.flush()
    record_audit(db, "order.comment_added", "order_comment", comment.id, actor=g.principal.user)
    db.commit(); return jsonify(id=str(comment.id), body=body), 201


@bp.post("/orders/<uuid:order_id>/disputes")
@require_auth
def open_dispute(order_id):
    db = get_session(); order = db.get(Order, order_id); data = request.get_json(silent=True) or {}; reason = str(data.get("reason", "")).strip()
    if not order or not order_accessible(g.principal, order): return jsonify(error="permission_denied", message="You cannot dispute this order."), 403
    if len(reason) < 10: return jsonify(error="validation_error", message="Describe the issue in at least 10 characters."), 422
    category = str(data.get("category", "other"))
    if category not in {"crop_damage", "quality_mismatch", "shortage", "late_delivery", "payment_issue", "other"}:
        return jsonify(error="validation_error", message="Choose a valid complaint category."), 422
    try:
        affected = Decimal(str(data["affected_quantity_kg"])) if data.get("affected_quantity_kg") else None
        if affected is not None and affected <= 0: raise ValueError
    except (ValueError, TypeError):
        return jsonify(error="validation_error", message="Affected quantity must be positive."), 422
    dispute = Dispute(order_id=order.id, opened_by_user_id=g.principal.user.id, reason=reason, category=category, affected_quantity_kg=affected, requested_resolution=str(data.get("requested_resolution", "")).strip()[:2000]); db.add(dispute); db.flush()
    record_audit(db, "dispute.opened", "dispute", dispute.id, actor=g.principal.user)
    db.commit(); return jsonify(id=str(dispute.id), status=dispute.status), 201


@bp.post("/orders/<uuid:order_id>/tracking")
@require_auth
def add_tracking(order_id):
    db = get_session(); order = db.get(Order, order_id); data = request.get_json(silent=True) or {}
    if not order or not order_accessible(g.principal, order):
        return jsonify(error="permission_denied", message="You cannot update this order."), 403
    if int(data.get("version", -1)) != order.version:
        return jsonify(error="stale_update", message="This order changed. Refresh before updating tracking."), 409
    status = str(data.get("status", "")); current = db.scalar(select(TrackingEvent).where(TrackingEvent.order_id == order.id).order_by(TrackingEvent.created_at.desc()))
    transitions = {"confirmed": {"preparing"}, "preparing": {"ready_for_pickup", "in_transit"}, "ready_for_pickup": {"picked_up"}, "picked_up": {"arrived"}, "in_transit": {"arrived"}, "arrived": set(), "partially_received": {"arrived", "delivered"}, "delivered": set()}
    current_status = current.status if current else "confirmed"
    if status not in transitions.get(current_status, set()):
        return jsonify(error="invalid_status", message=f"Cannot change tracking from {current_status} to {status}."), 409
    supplier_statuses = {"preparing", "ready_for_pickup", "in_transit"}
    buyer_statuses = {"picked_up", "arrived"}
    is_supplier = order.supplier_organization_id in g.principal.organization_ids or (order.coordinating_fpo_id and order.coordinating_fpo_id in g.principal.organization_ids)
    is_buyer = order.buyer_organization_id in g.principal.organization_ids
    if not g.principal.has_role("admin") and not ((status in supplier_statuses and is_supplier) or (status in buyer_statuses and is_buyer)):
        return jsonify(error="permission_denied", message="Your organization cannot record this tracking event."), 403
    event = TrackingEvent(order_id=order.id, actor_user_id=g.principal.user.id, status=status, note=str(data.get("note", "")).strip()[:1000]); db.add(event); order.version += 1
    record_audit(db, "order.tracking_updated", "tracking_event", event.id, actor=g.principal.user, details={"status": status}); db.commit()
    return jsonify(id=str(event.id), status=status, version=order.version), 201


def _review_payload(data, target_ids):
    entries = data.get("reviews")
    if not isinstance(entries, list) or not entries:
        entries = [data]
    parsed = []
    seen = set()
    for entry in entries:
        try:
            organization_id = uuid.UUID(str(entry.get("supplier_id") or entry.get("organization_id") or next(iter(target_ids))))
            values = {name: int(entry.get(name, entry.get("score", 0))) for name in ("overall_rating", "quality_rating", "delivery_rating", "communication_rating")}
        except (TypeError, ValueError, StopIteration):
            raise ValueError("Choose a valid review target and rate every category from 1 to 5.")
        if organization_id not in target_ids or organization_id in seen or any(value not in range(1, 6) for value in values.values()):
            raise ValueError("Rate each supplier or FPO once, with every rating from 1 to 5.")
        comment = str(entry.get("comment", "")).strip()
        if len(comment) > 1000:
            raise ValueError("Feedback must be 1,000 characters or fewer.")
        parsed.append((organization_id, values, comment, int(entry.get("version", 0) or 0)))
        seen.add(organization_id)
    if seen != set(target_ids):
        raise ValueError("Submit feedback for the supplier and coordinating FPO together.")
    return parsed


def _review_order(db, order_id):
    order = db.get(Order, order_id)
    if not order or order.buyer_organization_id not in g.principal.organization_ids:
        return None, (jsonify(error="permission_denied", message="Only this order's buyer may leave feedback."), 403)
    lines = list(db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)))
    received = {line.id: Decimal(db.scalar(select(func.coalesce(func.sum(ReceiptLine.quantity_kg), 0)).where(ReceiptLine.order_line_id == line.id)) or 0) for line in lines}
    if order.status != "received" or not lines or any(received[line.id] != Decimal(line.agreed_quantity_kg) for line in lines):
        return None, (jsonify(error="invalid_status", message="Feedback is available only after the complete order is received."), 409)
    return order, None


@bp.post("/orders/<uuid:order_id>/reviews")
@bp.post("/orders/<uuid:order_id>/ratings")
@require_roles("buyer")
def rate_order(order_id):
    db = get_session(); order, failure = _review_order(db, order_id)
    if failure: return failure
    targets = {order.supplier_organization_id: "supplier"}
    if order.coordinating_fpo_id: targets[order.coordinating_fpo_id] = "fpo"
    try: entries = _review_payload(request.get_json(silent=True) or {}, targets)
    except ValueError as exc: return jsonify(error="validation_error", message=str(exc)), 422
    if db.scalar(select(OrderRating.id).where(OrderRating.order_id == order.id)):
        return jsonify(error="duplicate_review", message="Feedback already exists for this order. Use Edit Feedback instead."), 409
    ratings = []
    try:
        for organization_id, values, comment, _ in entries:
            rating = OrderRating(order_id=order.id, buyer_user_id=g.principal.user.id, buyer_organization_id=order.buyer_organization_id, supplier_organization_id=organization_id, reviewed_role=targets[organization_id], comment=comment, **values)
            db.add(rating); ratings.append(rating)
        db.flush()
        record_audit(db, "review.created", "order", order.id, actor=g.principal.user, organization_id=order.buyer_organization_id, details={"targets": [str(x.supplier_organization_id) for x in ratings]})
        for rating in ratings:
            enqueue(db, "review.received", {"organization_id": str(rating.supplier_organization_id), "title": "New verified buyer review", "body": f"Feedback was recorded for {order.order_number}.", "link": "/reviews"}, f"review:{rating.id}:created")
        db.commit()
    except IntegrityError:
        db.rollback(); return jsonify(error="duplicate_review", message="Feedback already exists for this order."), 409
    return jsonify(items=[review_json(db, rating, include_buyer=True) for rating in ratings]), 201


@bp.patch("/orders/<uuid:order_id>/reviews")
@require_roles("buyer")
def update_review(order_id):
    db = get_session(); order, failure = _review_order(db, order_id)
    if failure: return failure
    targets = {order.supplier_organization_id: "supplier"}
    if order.coordinating_fpo_id: targets[order.coordinating_fpo_id] = "fpo"
    try: entries = _review_payload(request.get_json(silent=True) or {}, targets)
    except ValueError as exc: return jsonify(error="validation_error", message=str(exc)), 422
    updated = []
    for organization_id, values, comment, version in entries:
        rating = db.scalar(select(OrderRating).where(OrderRating.order_id == order.id, OrderRating.supplier_organization_id == organization_id).with_for_update())
        if not rating: return jsonify(error="not_found", message="Review not found."), 404
        if version != rating.version: return jsonify(error="stale_update", message="This review changed. Refresh before editing."), 409
        for name, value in values.items(): setattr(rating, name, value)
        rating.comment = comment; rating.version += 1; updated.append(rating)
    record_audit(db, "review.updated", "order", order.id, actor=g.principal.user, organization_id=order.buyer_organization_id, details={"targets": [str(x.supplier_organization_id) for x in updated]})
    for rating in updated:
        enqueue(db, "review.updated", {"organization_id": str(rating.supplier_organization_id), "title": "Buyer review updated", "body": f"Feedback was updated for {order.order_number}.", "link": "/reviews"}, f"review:{rating.id}:v{rating.version}")
    db.commit(); return jsonify(items=[review_json(db, rating, include_buyer=True) for rating in updated])


@bp.get("/reviews/mine")
@require_roles("buyer")
def my_reviews():
    db = get_session()
    rows = db.scalars(select(OrderRating).where(OrderRating.buyer_organization_id.in_(g.principal.organization_ids)).order_by(OrderRating.updated_at.desc())).all()
    return jsonify(items=[review_json(db, row, include_buyer=True) for row in rows])


@bp.get("/organizations/<uuid:organization_id>/reviews")
@require_auth
def organization_reviews(organization_id):
    db = get_session(); organization = db.get(Organization, organization_id)
    if not organization: return jsonify(error="not_found", message="Supplier organization not found."), 404
    rows = db.scalars(select(OrderRating).where(OrderRating.supplier_organization_id == organization_id).order_by(OrderRating.updated_at.desc()).limit(50)).all()
    return jsonify(organization={"id": str(organization.id), "name": organization.name, "type": organization.org_type}, summary=rating_summary(db, organization_id), items=[review_json(db, row) for row in rows])


@bp.post("/disputes/<uuid:dispute_id>/evidence")
@require_auth
def add_dispute_evidence(dispute_id):
    db = get_session(); dispute = db.get(Dispute, dispute_id); order = db.get(Order, dispute.order_id) if dispute else None
    if not dispute or not order or not order_accessible(g.principal, order):
        return jsonify(error="permission_denied", message="You cannot add evidence to this complaint."), 403
    if db.scalar(select(func.count()).select_from(DisputeEvidence).where(DisputeEvidence.dispute_id == dispute.id)) >= 5:
        return jsonify(error="evidence_limit", message="A complaint can contain up to five evidence images."), 409
    photo = request.files.get("photo")
    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if not photo or photo.mimetype not in allowed:
        return jsonify(error="invalid_image", message="Upload a JPEG, PNG, or WebP image."), 422
    content = photo.read(); signatures = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n", "image/webp": b"RIFF"}
    if not content.startswith(signatures[photo.mimetype]):
        return jsonify(error="invalid_image", message="The file content does not match its image type."), 422
    filename = f"complaint-{dispute.id}-{uuid.uuid4().hex[:8]}{allowed[photo.mimetype]}"
    current_app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)
    (current_app.config["UPLOAD_FOLDER"] / filename).write_bytes(content)
    evidence = DisputeEvidence(dispute_id=dispute.id, uploaded_by_user_id=g.principal.user.id, file_path=filename); db.add(evidence); db.commit()
    return jsonify(id=str(evidence.id), photo_url=f"/uploads/{filename}"), 201


def _razorpay_request(method, path, body=None):
    key_id = current_app.config["RAZORPAY_KEY_ID"]; secret = current_app.config["RAZORPAY_KEY_SECRET"]
    payload = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": "Basic " + base64.b64encode(f"{key_id}:{secret}".encode()).decode(),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "AgriLink/1.0 Razorpay-Test",
    }
    req = UrlRequest(f"https://api.razorpay.com/v1{path}", data=payload, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        description = ""
        try:
            error_payload = json.loads(exc.read(16_384))
            description = str((error_payload.get("error") or {}).get("description") or "").strip()
        except (ValueError, TypeError, AttributeError):
            pass
        current_app.logger.warning("Razorpay request rejected method=%s path=%s status=%s", method, path, exc.code)
        suffix = f" {description}" if description else ""
        raise ValueError(f"Razorpay rejected the request ({exc.code}).{suffix}") from exc
    except (URLError, TimeoutError) as exc:
        current_app.logger.warning("Razorpay request unavailable method=%s path=%s error_type=%s", method, path, type(exc).__name__)
        raise ValueError("Razorpay is temporarily unavailable. Try again later.") from exc


def _razorpay_ready():
    return bool(current_app.config["RAZORPAY_ENABLED"] and current_app.config["RAZORPAY_KEY_ID"].startswith("rzp_test_") and current_app.config["RAZORPAY_KEY_SECRET"])


@bp.get("/payments/config")
@require_auth
def payment_config():
    ready = _razorpay_ready()
    return jsonify(enabled=ready, test_mode=True, key_id=current_app.config["RAZORPAY_KEY_ID"] if ready else None, message=None if ready else "Razorpay test payment is not configured.")


@bp.post("/orders/<uuid:order_id>/razorpay-order")
@require_roles("buyer")
def create_razorpay_order(order_id):
    if not _razorpay_ready():
        return jsonify(error="payment_unavailable", message="Razorpay test payment is not configured."), 503
    db = get_session(); order = db.get(Order, order_id)
    if not order or order.buyer_organization_id not in g.principal.organization_ids:
        return jsonify(error="permission_denied", message="Only this order's buyer can pay."), 403
    amount = detail(db, order)["payable_paise"]
    if amount <= 0: return jsonify(error="nothing_due", message="No received amount is currently payable."), 409
    pending = db.scalar(
        select(PaymentEvent).where(
            PaymentEvent.order_id == order.id,
            PaymentEvent.provider == "razorpay_test",
            PaymentEvent.outcome == "pending",
            PaymentEvent.amount_paise == amount,
            PaymentEvent.provider_order_id.is_not(None),
        ).order_by(PaymentEvent.created_at.desc()).limit(1)
    )
    if pending:
        return jsonify(razorpay_order_id=pending.provider_order_id, amount_paise=amount, currency="INR", key_id=current_app.config["RAZORPAY_KEY_ID"], test_mode=True, idempotent_replay=True)
    try:
        remote = _razorpay_request("POST", "/orders", {"amount": amount, "currency": "INR", "receipt": order.order_number[:40], "notes": {"agrilink_order_id": str(order.id), "test_mode": "true"}})
    except ValueError as exc:
        return jsonify(error="payment_provider_error", message=str(exc)), 502
    event = PaymentEvent(order_id=order.id, actor_user_id=g.principal.user.id, amount_paise=amount, outcome="pending", external_reference=f"RZP-{remote['id']}", provider="razorpay_test", provider_order_id=remote["id"], note="Razorpay test payment pending; no live transfer is represented.")
    db.add(event); db.commit()
    return jsonify(razorpay_order_id=remote["id"], amount_paise=amount, currency="INR", key_id=current_app.config["RAZORPAY_KEY_ID"], test_mode=True), 201


@bp.post("/orders/<uuid:order_id>/razorpay-verify")
@require_roles("buyer")
def verify_razorpay_payment(order_id):
    db = get_session(); order = db.get(Order, order_id); data = request.get_json(silent=True) or {}
    if not order or order.buyer_organization_id not in g.principal.organization_ids:
        return jsonify(error="permission_denied", message="Only this order's buyer can verify payment."), 403
    provider_order_id = str(data.get("razorpay_order_id", "")); payment_id = str(data.get("razorpay_payment_id", "")); signature = str(data.get("razorpay_signature", ""))
    event = db.scalar(select(PaymentEvent).where(PaymentEvent.order_id == order.id, PaymentEvent.provider_order_id == provider_order_id).with_for_update())
    if not event: return jsonify(error="payment_not_found", message="Payment order does not belong to this AgriLink order."), 404
    if event.outcome == "success": return jsonify(payment_status=order.payment_status, idempotent_replay=True)
    expected = hmac.new(current_app.config["RAZORPAY_KEY_SECRET"].encode(), f"{provider_order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return jsonify(error="invalid_signature", message="Razorpay payment signature is invalid."), 422
    try: payment = _razorpay_request("GET", f"/payments/{payment_id}")
    except ValueError as exc: return jsonify(error="payment_provider_error", message=str(exc)), 502
    if payment.get("order_id") != provider_order_id or int(payment.get("amount", 0)) != event.amount_paise:
        return jsonify(error="payment_mismatch", message="The Razorpay payment does not match this AgriLink order."), 409
    if payment.get("status") == "authorized":
        try:
            payment = _razorpay_request("POST", f"/payments/{payment_id}/capture", {"amount": event.amount_paise, "currency": "INR"})
        except ValueError as exc:
            return jsonify(error="payment_provider_error", message=str(exc)), 502
    if payment.get("status") != "captured" or int(payment.get("amount", 0)) != event.amount_paise:
        return jsonify(error="payment_not_captured", message="The test payment has not been captured."), 409
    event.outcome = "success"; event.provider_payment_id = payment_id; event.external_reference = payment_id; event.note = "Verified Razorpay test payment; no live-mode transfer."
    remaining = detail(db, order)["payable_paise"] - event.amount_paise
    order.payment_status = "paid" if remaining <= 0 else "partially_paid"
    record_audit(db, "payment.razorpay_test_verified", "payment_event", event.id, actor=g.principal.user, organization_id=order.buyer_organization_id, details={"test_mode": True}); db.commit()
    return jsonify(payment_event_id=str(event.id), payment_status=order.payment_status, test_mode=True)


@bp.post("/payments/razorpay-webhook")
def razorpay_webhook():
    secret = current_app.config["RAZORPAY_WEBHOOK_SECRET"]
    raw = request.get_data(); received = request.headers.get("X-Razorpay-Signature", "")
    if not secret or not hmac.compare_digest(hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), received):
        return jsonify(error="invalid_signature", message="Webhook signature is invalid."), 401
    payload = request.get_json(silent=True) or {}; event_id = request.headers.get("X-Razorpay-Event-Id") or hashlib.sha256(raw).hexdigest()
    payment = (((payload.get("payload") or {}).get("payment") or {}).get("entity") or {})
    provider_order_id = payment.get("order_id")
    db = get_session(); event = db.scalar(select(PaymentEvent).where(PaymentEvent.provider_order_id == provider_order_id).with_for_update())
    if not event or event.provider_event_id == event_id: return jsonify(ok=True, duplicate=bool(event))
    if payload.get("event") == "payment.captured" and payment.get("id"):
        event.outcome = "success"; event.provider_payment_id = payment["id"]; event.provider_event_id = event_id; event.external_reference = payment["id"]
        order = db.get(Order, event.order_id); order.payment_status = "paid" if detail(db, order)["payable_paise"] <= event.amount_paise else "partially_paid"
    db.commit(); return jsonify(ok=True)


def safe_cell(value):
    text = str(value if value is not None else "")
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


@bp.get("/orders/export.csv")
@require_auth
def export_orders():
    db = get_session(); query = select(Order)
    if not g.principal.has_role("admin"):
        query = query.where(or_(Order.buyer_organization_id.in_(g.principal.organization_ids), Order.supplier_organization_id.in_(g.principal.organization_ids)))
    stream = io.StringIO(); writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["Order", "Status", "Payment status", "Supplier", "Deadline", "Quantity kg", "Total INR"])
    for order in db.scalars(query):
        d = detail(db, order); supplier = db.get(Organization, order.supplier_organization_id)
        writer.writerow([safe_cell(order.order_number), order.status, order.payment_status, safe_cell(supplier.name), order.delivery_deadline, sum(x["agreed_quantity_kg"] for x in d["lines"]), d["total_paise"] / 100])
    return Response("\ufeff" + stream.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=agrilink-orders.csv"})
