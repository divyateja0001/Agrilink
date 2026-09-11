from __future__ import annotations

import csv
import hashlib
import io
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import Blueprint, Response, current_app, g, jsonify, request, send_from_directory
from sqlalchemy import func, or_, select
from werkzeug.utils import secure_filename

from ..db import get_session
from ..models import (
    BuyerRequirement, FpoAuthorization, Membership, Order, OrderLine, Organization,
    PhotoCaptureSession, ProduceLot, ProducePhoto, Quotation, QuoteAllocation, QuoteRevision,
)
from ..security import can_access_farmer_org, require_auth, require_roles
from ..serializers import lot_json, org_json, requirement_json
from ..services.audit import record_audit
from ..services.matching import QUALITY_RANK, allocation_preview, available_quantity, match_requirement
from ..services.marketplace_alerts import compatible_buyer_user_ids, compatible_supplier_user_ids
from ..services.outbox import enqueue
from ..services.reviews import rating_summary


bp = Blueprint("marketplace", __name__, url_prefix="/api")
ALLOWED_IMAGES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
DELIVERY_MODES = {"buyer_pickup", "seller_delivery"}


def parse_date(value, field):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an ISO date.")


def parse_positive_decimal(value, field):
    try:
        result = Decimal(str(value))
        if result <= 0:
            raise InvalidOperation
        return result.quantize(Decimal("0.001"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be greater than zero.")


def actor_org(role):
    for membership in g.principal.memberships:
        if membership.role == role:
            return membership.organization_id
    return None


def lot_eligibility_error(lot, requirement, available):
    if lot.status != "active":
        return "The produce lot is archived or inactive."
    if lot.crop.casefold() != requirement.crop.casefold():
        return f"Choose a {requirement.crop} produce lot."
    if requirement.variety and lot.variety.casefold() != requirement.variety.casefold():
        return f"Choose the {requirement.variety} variety."
    if QUALITY_RANK.get(lot.quality_grade, 0) < QUALITY_RANK.get(requirement.acceptable_quality, 0):
        return f"The lot must be grade {requirement.acceptable_quality} or better."
    if lot.available_from > requirement.delivery_deadline or lot.available_until < date.today():
        return "The lot is not available within the buyer's delivery window."
    if available <= 0:
        return "The produce lot has no unreserved stock available."
    if lot.delivery_mode != requirement.delivery_mode:
        return "The produce lot cannot satisfy the buyer's delivery mode."
    if requirement.delivery_mode == "seller_delivery" and lot.delivery_service_location:
        service_area = lot.delivery_service_location.casefold()
        destination = requirement.destination.casefold()
        if service_area not in destination and destination not in service_area:
            if None in (lot.latitude, lot.longitude, requirement.destination_latitude, requirement.destination_longitude, lot.delivery_radius_km):
                return "The buyer's destination is outside the seller's recorded delivery area."
            from ..services.matching import haversine_km
            if haversine_km(lot.latitude, lot.longitude, requirement.destination_latitude, requirement.destination_longitude) > float(lot.delivery_radius_km):
                return "The buyer's destination is outside the seller's delivery radius."
    return None


def remaining_requirement_quantity(db, requirement):
    committed = db.scalar(
        select(func.coalesce(func.sum(OrderLine.agreed_quantity_kg), 0))
        .join(Order, Order.id == OrderLine.order_id)
        .where(Order.requirement_id == requirement.id, Order.status != "cancelled")
    )
    return max(Decimal("0"), Decimal(requirement.quantity_kg) - Decimal(committed or 0))


@bp.get("/dashboard")
@require_auth
def dashboard():
    db = get_session(); principal = g.principal
    result = {"role": next(iter(sorted(principal.roles)), "buyer")}
    if principal.has_role("admin"):
        result.update(participants=db.scalar(select(func.count()).select_from(Organization)), open_disputes=0, active_orders=0, audit_events=db.scalar(select(func.count()).select_from(__import__('app.models', fromlist=['AuditEvent']).AuditEvent)))
    elif principal.has_role("farmer", "fpo_manager"):
        org_ids = list(principal.organization_ids)
        lots = list(db.scalars(select(ProduceLot).where(ProduceLot.farmer_organization_id.in_(org_ids), ProduceLot.status == "active")))
        result.update(
            available_produce_kg=sum(float(available_quantity(db, lot.id)) for lot in lots),
            active_orders=db.scalar(select(func.count()).select_from(__import__('app.models', fromlist=['Order']).Order).where(__import__('app.models', fromlist=['Order']).Order.supplier_organization_id.in_(org_ids), __import__('app.models', fromlist=['Order']).Order.status.notin_(["received", "cancelled"]))),
            pending_quotations=db.scalar(select(func.count()).select_from(Quotation).where(Quotation.supplier_organization_id.in_(org_ids), Quotation.status.in_(["awaiting_buyer", "awaiting_supplier", "agreed"]))),
            upcoming_dispatches=0, outstanding_receivables_paise=0,
        )
    else:
        org_ids = list(principal.organization_ids)
        Order = __import__('app.models', fromlist=['Order']).Order
        result.update(
            open_requirements=db.scalar(select(func.count()).select_from(BuyerRequirement).where(BuyerRequirement.buyer_organization_id.in_(org_ids), BuyerRequirement.status == "open")),
            quotations_awaiting_review=db.scalar(select(func.count()).select_from(Quotation).join(BuyerRequirement).where(BuyerRequirement.buyer_organization_id.in_(org_ids), Quotation.status.in_(["awaiting_buyer", "agreed"]))),
            active_orders=db.scalar(select(func.count()).select_from(Order).where(Order.buyer_organization_id.in_(org_ids), Order.status.notin_(["received", "cancelled"]))),
            pending_deliveries=0, outstanding_payments_paise=0,
        )
    return jsonify(result)


@bp.get("/produce")
@require_auth
def list_produce():
    db = get_session()
    query = select(ProduceLot).order_by(ProduceLot.created_at.desc())
    if request.args.get("mine") == "true":
        query = query.where(ProduceLot.farmer_organization_id.in_(g.principal.organization_ids))
    else:
        query = query.where(ProduceLot.status == "active")
    if crop := request.args.get("crop"):
        query = query.where(func.lower(ProduceLot.crop).contains(crop.lower()))
    if quality := request.args.get("quality"):
        query = query.where(ProduceLot.quality_grade == quality)
    if location := request.args.get("location"):
        query = query.where(func.lower(ProduceLot.location).contains(location.lower()))
    lots = list(db.scalars(query.limit(100)))
    items = []
    for lot in lots:
        item = lot_json(lot, available_quantity(db, lot.id))
        supplier = db.get(Organization, lot.farmer_organization_id)
        item["supplier"] = org_json(supplier, rating_summary(db, supplier.id))
        items.append(item)
    return jsonify(items=items)


@bp.post("/produce")
@require_roles("farmer", "fpo_manager")
def create_produce():
    data = request.get_json(silent=True) or {}
    org_id = uuid.UUID(data.get("farmer_organization_id")) if data.get("farmer_organization_id") else actor_org("farmer")
    if not org_id or not can_access_farmer_org(g.principal, org_id):
        return jsonify(error="permission_denied", message="You cannot create stock for that farm."), 403
    try:
        delivery_mode = str(data.get("delivery_mode", "")).strip()
        if delivery_mode not in DELIVERY_MODES:
            raise ValueError("Choose Buyer Pickup or Delivery Available.")
        radius = Decimal(str(data["delivery_radius_km"])).quantize(Decimal("0.01")) if data.get("delivery_radius_km") else None
        charge = int(Decimal(str(data.get("delivery_charge_inr") or 0)) * 100)
        service_location = str(data.get("delivery_service_location") or "").strip() or None
        if delivery_mode == "seller_delivery" and (not service_location or not radius or radius <= 0):
            raise ValueError("Delivery Available requires a service location and positive delivery radius.")
        if charge < 0:
            raise ValueError("Delivery charge cannot be negative.")
        lot = ProduceLot(
            farmer_organization_id=org_id, created_by_user_id=g.principal.user.id,
            crop=str(data["crop"]).strip(), variety=str(data.get("variety", "Standard")).strip(),
            quality_grade=str(data["quality_grade"]).upper(), quantity_on_hand_kg=parse_positive_decimal(data["quantity_kg"], "quantity_kg"),
            asking_price_paise=int(Decimal(str(data["asking_price_inr"])) * 100), location=str(data["location"]).strip(),
            harvest_date=parse_date(data["harvest_date"], "harvest_date"), available_from=parse_date(data["available_from"], "available_from"),
            available_until=parse_date(data["available_until"], "available_until"), description=str(data.get("description", "")).strip(),
            delivery_mode=delivery_mode, delivery_service_location=service_location if delivery_mode == "seller_delivery" else None,
            delivery_radius_km=radius if delivery_mode == "seller_delivery" else None,
            delivery_charge_paise=charge if delivery_mode == "seller_delivery" else 0,
            status="draft",
        )
        if not lot.crop or not lot.location or lot.quality_grade not in {"A", "B", "C"} or lot.asking_price_paise <= 0 or lot.available_until < lot.available_from:
            raise ValueError("Provide valid crop, grade, price, location, and availability dates.")
    except (KeyError, ValueError, InvalidOperation) as exc:
        return jsonify(error="validation_error", message=str(exc)), 422
    db = get_session(); db.add(lot); db.flush()
    record_audit(db, "produce.created", "produce_lot", lot.id, actor=g.principal.user, organization_id=org_id)
    db.commit()
    result = lot_json(lot, lot.quantity_on_hand_kg)
    result["message"] = "Draft saved. Capture a geotagged photo to publish it."
    return jsonify(result), 201


@bp.patch("/produce/<uuid:lot_id>")
@require_roles("farmer", "fpo_manager")
def update_produce(lot_id):
    db = get_session(); lot = db.get(ProduceLot, lot_id)
    if not lot:
        return jsonify(error="not_found", message="Produce lot not found."), 404
    if not can_access_farmer_org(g.principal, lot.farmer_organization_id):
        return jsonify(error="permission_denied", message="You cannot update this produce lot."), 403
    data = request.get_json(silent=True) or {}
    if int(data.get("version", -1)) != lot.version:
        return jsonify(error="stale_update", message="This listing changed. Refresh before saving."), 409
    for field in ("crop", "variety", "quality_grade", "location", "description"):
        if field in data:
            setattr(lot, field, str(data[field]).strip())
    if "status" in data:
        status = str(data["status"])
        if status not in {"active", "archived"}:
            return jsonify(error="validation_error", message="A listing can only be active or archived."), 422
        if status == "active" and not lot.photo_path:
            return jsonify(error="photo_required", message="Capture a geotagged website photo before publishing."), 409
        lot.status = status
    if "delivery_mode" in data:
        mode = str(data["delivery_mode"])
        if mode not in DELIVERY_MODES:
            return jsonify(error="validation_error", message="Choose a valid delivery mode."), 422
        lot.delivery_mode = mode
    if "asking_price_inr" in data:
        lot.asking_price_paise = int(Decimal(str(data["asking_price_inr"])) * 100)
    if "quantity_kg" in data:
        desired = parse_positive_decimal(data["quantity_kg"], "quantity_kg")
        reserved = Decimal(lot.quantity_on_hand_kg) - available_quantity(db, lot.id)
        if desired < reserved:
            return jsonify(error="reserved_stock", message="Quantity cannot be below active reservations."), 409
        lot.quantity_on_hand_kg = desired
    lot.version += 1
    record_audit(db, "produce.updated", "produce_lot", lot.id, actor=g.principal.user, organization_id=lot.farmer_organization_id)
    db.commit()
    return jsonify(lot_json(lot, available_quantity(db, lot.id)))


@bp.post("/produce/<uuid:lot_id>/archive")
@require_roles("farmer", "fpo_manager")
def archive_produce(lot_id):
    db = get_session(); lot = db.get(ProduceLot, lot_id); data = request.get_json(silent=True) or {}
    if not lot or not can_access_farmer_org(g.principal, lot.farmer_organization_id):
        return jsonify(error="not_found", message="Produce lot not found."), 404
    if int(data.get("version", -1)) != lot.version:
        return jsonify(error="stale_update", message="This listing changed. Refresh and try again."), 409
    lot.status = "archived"; lot.version += 1
    record_audit(db, "produce.archived", "produce_lot", lot.id, actor=g.principal.user, organization_id=lot.farmer_organization_id)
    db.commit(); return jsonify(lot_json(lot, available_quantity(db, lot.id)))


@bp.post("/produce/<uuid:lot_id>/restore")
@require_roles("farmer", "fpo_manager")
def restore_produce(lot_id):
    db = get_session(); lot = db.get(ProduceLot, lot_id); data = request.get_json(silent=True) or {}
    if not lot or not can_access_farmer_org(g.principal, lot.farmer_organization_id):
        return jsonify(error="not_found", message="Produce lot not found."), 404
    if int(data.get("version", -1)) != lot.version:
        return jsonify(error="stale_update", message="This listing changed. Refresh and try again."), 409
    if not lot.photo_path:
        return jsonify(error="photo_required", message="Capture a geotagged website photo before restoring."), 409
    lot.status = "active"; lot.version += 1
    record_audit(db, "produce.restored", "produce_lot", lot.id, actor=g.principal.user, organization_id=lot.farmer_organization_id)
    db.flush()
    recipients = compatible_buyer_user_ids(db, lot)
    enqueue(db, "produce.published", {"user_ids": recipients, "title": f"{lot.crop} supply is available", "body": f"A compatible supplier published {float(available_quantity(db, lot.id)):g} kg, grade {lot.quality_grade}.", "link": "/produce"}, f"produce:{lot.id}:restored:v{lot.version}")
    db.commit(); result = lot_json(lot, available_quantity(db, lot.id)); result["notified_users"] = len(recipients); return jsonify(result)


@bp.post("/produce/<uuid:lot_id>/photo-capture-session")
@require_roles("farmer", "fpo_manager")
def begin_photo_capture(lot_id):
    db = get_session(); lot = db.get(ProduceLot, lot_id)
    if not lot or not can_access_farmer_org(g.principal, lot.farmer_organization_id):
        return jsonify(error="not_found", message="Produce lot not found."), 404
    raw = secrets.token_urlsafe(32)
    capture = PhotoCaptureSession(produce_lot_id=lot.id, user_id=g.principal.user.id, token_hash=hashlib.sha256(raw.encode()).hexdigest(), expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    db.add(capture); db.commit()
    return jsonify(capture_token=raw, expires_in_seconds=300)


@bp.post("/produce/<uuid:lot_id>/photo")
@require_roles("farmer", "fpo_manager")
def upload_photo(lot_id):
    db = get_session(); lot = db.get(ProduceLot, lot_id)
    if not lot or not can_access_farmer_org(g.principal, lot.farmer_organization_id):
        return jsonify(error="not_found", message="Produce lot not found."), 404
    file = request.files.get("photo")
    raw_token = str(request.form.get("capture_token", ""))
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    capture = db.scalar(select(PhotoCaptureSession).where(PhotoCaptureSession.token_hash == token_hash).with_for_update())
    now = datetime.now(timezone.utc)
    if not capture or capture.produce_lot_id != lot.id or capture.user_id != g.principal.user.id or capture.used_at or capture.expires_at < now:
        return jsonify(error="invalid_capture_session", message="The camera session expired or was already used. Start capture again."), 409
    if not file or file.mimetype not in ALLOWED_IMAGES:
        return jsonify(error="invalid_image", message="Upload a JPEG, PNG, or WebP image."), 422
    content = file.read()
    header = content[:16]
    signatures = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n", "image/webp": b"RIFF"}
    if not header.startswith(signatures[file.mimetype]):
        return jsonify(error="invalid_image", message="The file content does not match its image type."), 422
    try:
        latitude = Decimal(str(request.form["latitude"])); longitude = Decimal(str(request.form["longitude"])); accuracy = Decimal(str(request.form["accuracy_m"]))
        captured_at = datetime.fromisoformat(str(request.form["captured_at"]).replace("Z", "+00:00"))
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180) or accuracy <= 0 or accuracy > 500:
            raise ValueError
        if captured_at.tzinfo is None or abs((now - captured_at.astimezone(timezone.utc)).total_seconds()) > 600:
            raise ValueError
    except (KeyError, ValueError, InvalidOperation):
        return jsonify(error="invalid_geotag", message="Capture a current location with accuracy of 500 metres or better."), 422
    filename = f"{lot.id}-{uuid.uuid4().hex[:8]}{ALLOWED_IMAGES[file.mimetype]}"
    current_app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)
    (Path(current_app.config["UPLOAD_FOLDER"]) / secure_filename(filename)).write_bytes(content)
    for previous in db.scalars(select(ProducePhoto).where(ProducePhoto.produce_lot_id == lot.id, ProducePhoto.is_current.is_(True))):
        previous.is_current = False
    photo = ProducePhoto(produce_lot_id=lot.id, captured_by_user_id=g.principal.user.id, file_path=filename, sha256=hashlib.sha256(content).hexdigest(), latitude=latitude, longitude=longitude, accuracy_m=accuracy, captured_at=captured_at, source="web_camera")
    db.add(photo); capture.used_at = now
    lot.photo_path = filename; lot.latitude = latitude; lot.longitude = longitude; lot.status = "active"; lot.version += 1
    record_audit(db, "produce.photo_captured", "produce_lot", lot.id, actor=g.principal.user, organization_id=lot.farmer_organization_id, details={"source": "web_camera", "accuracy_m": float(accuracy)})
    db.flush()
    recipients = compatible_buyer_user_ids(db, lot)
    enqueue(db, "produce.published", {"user_ids": recipients, "title": f"{lot.crop} supply is available", "body": f"A compatible supplier published {float(available_quantity(db, lot.id)):g} kg, grade {lot.quality_grade}.", "link": "/produce"}, f"produce:{lot.id}:published:v{lot.version}")
    db.commit()
    return jsonify(photo_url=f"/uploads/{filename}", notified_users=len(recipients))


@bp.get("/requirements")
@require_auth
def list_requirements():
    db = get_session(); query = select(BuyerRequirement).order_by(BuyerRequirement.delivery_deadline)
    if request.args.get("mine") == "true":
        query = query.where(BuyerRequirement.buyer_organization_id.in_(g.principal.organization_ids))
    return jsonify(items=[requirement_json(x) for x in db.scalars(query.limit(100))])


@bp.post("/requirements")
@require_roles("buyer")
def create_requirement():
    data = request.get_json(silent=True) or {}; org_id = actor_org("buyer")
    try:
        delivery_mode = str(data.get("delivery_mode", "")).strip()
        if delivery_mode not in DELIVERY_MODES:
            raise ValueError("Choose Buyer Pickup or Delivery Required.")
        req = BuyerRequirement(
            buyer_organization_id=org_id, created_by_user_id=g.principal.user.id, crop=str(data["crop"]).strip(),
            variety=str(data.get("variety") or "").strip() or None, quantity_kg=parse_positive_decimal(data["quantity_kg"], "quantity_kg"),
            acceptable_quality=str(data["acceptable_quality"]).upper(), destination=str(data["destination"]).strip(),
            delivery_deadline=parse_date(data["delivery_deadline"], "delivery_deadline"),
            budget_price_paise=int(Decimal(str(data["budget_price_inr"])) * 100) if data.get("budget_price_inr") else None,
            notes=str(data.get("notes", "")).strip(),
            delivery_mode=delivery_mode,
            destination_latitude=Decimal(str(data["destination_latitude"])) if data.get("destination_latitude") is not None else None,
            destination_longitude=Decimal(str(data["destination_longitude"])) if data.get("destination_longitude") is not None else None,
        )
        if not req.crop or not req.destination or req.acceptable_quality not in {"A", "B", "C"} or req.delivery_deadline < date.today():
            raise ValueError("Provide a valid crop, quality, destination, and future deadline.")
    except (KeyError, ValueError, InvalidOperation) as exc:
        return jsonify(error="validation_error", message=str(exc)), 422
    db = get_session(); db.add(req); db.flush()
    record_audit(db, "requirement.created", "buyer_requirement", req.id, actor=g.principal.user, organization_id=org_id)
    recipients = compatible_supplier_user_ids(db, req)
    enqueue(db, "requirement.published", {"user_ids": recipients, "title": f"New {req.crop} requirement", "body": f"A buyer needs {float(req.quantity_kg):g} kg, grade {req.acceptable_quality}, by {req.delivery_deadline.isoformat()}.", "link": f"/requirements?requirement={req.id}"}, f"requirement:{req.id}:published")
    db.commit(); result = requirement_json(req); result["notified_users"] = len(recipients); return jsonify(result), 201


@bp.get("/requirements/<uuid:req_id>/matches")
@require_auth
def requirement_matches(req_id):
    db = get_session(); req = db.get(BuyerRequirement, req_id)
    if not req:
        return jsonify(error="not_found", message="Requirement not found."), 404
    items = []
    for match in match_requirement(db, req):
        org = db.get(Organization, match["lot"].farmer_organization_id)
        items.append({"lot": lot_json(match["lot"], match["available_kg"]), "supplier": org_json(org, rating_summary(db, org.id)), "score": match["score"], "score_components": match["score_components"], "explanations": match["explanations"]})
    return jsonify(items=items, formula={"quantity_coverage": 50, "price_fit": 30, "delivery_fit": 20, "trained_ai": False})


@bp.get("/requirements/<uuid:req_id>/allocation-preview")
@require_auth
def preview_allocation(req_id):
    db = get_session(); req = db.get(BuyerRequirement, req_id)
    if not req: return jsonify(error="not_found", message="Requirement not found."), 404
    allocations, shortfall = allocation_preview(db, req)
    return jsonify(allocations=[{"lot": lot_json(x["lot"], x["available_kg"]), "suggested_quantity_kg": float(x["suggested_quantity_kg"]), "score": x["score"]} for x in allocations], shortfall_kg=float(shortfall), reserves_stock=False)


@bp.get("/requirements/<uuid:req_id>/eligible-lots")
@require_roles("farmer", "fpo_manager")
def eligible_lots(req_id):
    db = get_session()
    requirement = db.get(BuyerRequirement, req_id)
    if not requirement or requirement.status not in {"open", "partially_fulfilled"}:
        return jsonify(error="not_found", message="Open requirement not found."), 404
    items = []
    for lot in db.scalars(select(ProduceLot).order_by(ProduceLot.created_at.desc()).limit(250)):
        if not can_access_farmer_org(g.principal, lot.farmer_organization_id):
            continue
        available = available_quantity(db, lot.id)
        if lot_eligibility_error(lot, requirement, available):
            continue
        items.append(lot_json(lot, available))
    accessible_farm_ids = {uuid.UUID(item["farmer_organization_id"]) for item in items}
    fpo_ids = [membership.organization_id for membership in g.principal.memberships if membership.role == "fpo_manager"]
    quote_scope = []
    if accessible_farm_ids:
        quote_scope.append(Quotation.supplier_organization_id.in_(accessible_farm_ids))
    if fpo_ids:
        quote_scope.append(Quotation.coordinating_fpo_id.in_(fpo_ids))
    existing = []
    if quote_scope:
        existing = list(
            db.scalars(
                select(Quotation)
                .where(Quotation.requirement_id == requirement.id, or_(*quote_scope))
                .order_by(Quotation.updated_at.desc())
            )
        )
    remaining = remaining_requirement_quantity(db, requirement)
    return jsonify(
        items=items,
        existing_negotiations=[
            {
                "id": str(quote.id),
                "supplier_organization_id": str(quote.supplier_organization_id),
                "status": quote.status,
            }
            for quote in existing
        ],
        remaining_requirement_kg=float(remaining),
        requirement_id=str(requirement.id),
    )


@bp.post("/requirements/<uuid:req_id>/quotations")
@require_roles("farmer", "fpo_manager")
def submit_quote(req_id):
    db = get_session()
    req = db.scalar(select(BuyerRequirement).where(BuyerRequirement.id == req_id).with_for_update())
    data = request.get_json(silent=True) or {}
    if not req or req.status not in {"open", "partially_fulfilled"}: return jsonify(error="not_found", message="Open requirement not found."), 404
    allocations_data = data.get("allocations") or []
    try:
        if not isinstance(allocations_data, list) or len(allocations_data) > 50:
            raise ValueError("Provide between 1 and 50 produce-lot allocations.")
        allocation_ids = [uuid.UUID(str(x["produce_lot_id"])) for x in allocations_data]
        if len(allocation_ids) != len(set(allocation_ids)):
            raise ValueError("Each produce lot may appear only once in an offer.")
        locked_lots = {
            lot.id: lot
            for lot in db.scalars(
                select(ProduceLot)
                .where(ProduceLot.id.in_(sorted(allocation_ids, key=str)))
                .order_by(ProduceLot.id)
                .with_for_update()
            )
        }
        allocations = [
            (locked_lots.get(lot_id), parse_positive_decimal(item["quantity_kg"], "quantity_kg"))
            for lot_id, item in zip(allocation_ids, allocations_data)
        ]
        if not allocations:
            raise ValueError("Select at least one compatible produce lot.")
        if any(not lot or not can_access_farmer_org(g.principal, lot.farmer_organization_id) for lot, _ in allocations):
            return jsonify(error="permission_denied", message="Every allocation must use an authorized produce lot."), 403
        for lot, quantity in allocations:
            available = available_quantity(db, lot.id)
            incompatibility = lot_eligibility_error(lot, req, available)
            if incompatibility:
                raise ValueError(incompatibility)
            if quantity > available:
                raise ValueError(f"{lot.crop} has only {available} kg of unreserved stock available.")
        supplier_org_id = allocations[0][0].farmer_organization_id
        if any(lot.farmer_organization_id != supplier_org_id for lot, _ in allocations) and not g.principal.has_role("fpo_manager"):
            return jsonify(error="permission_denied", message="Only an FPO manager can coordinate multiple farms."), 403
        offered = sum((qty for _, qty in allocations), Decimal("0"))
        remaining = remaining_requirement_quantity(db, req)
        if offered > remaining:
            raise ValueError(f"The requirement has only {remaining} kg remaining.")
        price = Decimal(str(data["price_inr_per_kg"]))
        if not price.is_finite() or price <= 0 or price != price.quantize(Decimal("0.01")):
            raise ValueError("Price must be positive and use at most two decimal places.")
        price_paise = int(price * 100)
        delivery_date = parse_date(data["delivery_date"], "delivery_date")
        if delivery_date < date.today() or delivery_date > req.delivery_deadline:
            raise ValueError("Delivery date must be today or before the buyer's deadline.")
        delivery_terms = str(data.get("delivery_terms", "")).strip()
        note = str(data.get("note", "")).strip()
        if not delivery_terms or len(delivery_terms) > 500 or len(note) > 1000:
            raise ValueError("Provide delivery terms up to 500 characters and a note up to 1,000 characters.")
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        return jsonify(error="validation_error", message=str(exc)), 422
    quote = db.scalar(select(Quotation).where(Quotation.requirement_id == req.id, Quotation.supplier_organization_id == supplier_org_id))
    revision_no = 1
    if quote:
        if quote.status in {"accepted", "rejected", "withdrawn"}: return jsonify(error="invalid_status", message="A closed negotiation cannot be revised."), 409
        if quote.status != "awaiting_supplier": return jsonify(error="invalid_status", message="Wait for the buyer to respond before sending another offer."), 409
        revision_no = quote.current_revision_number + 1; quote.current_revision_number = revision_no; quote.status = "awaiting_buyer"; quote.version += 1
    else:
        fpo_id = actor_org("fpo_manager") if g.principal.has_role("fpo_manager") else None
        quote = Quotation(requirement_id=req.id, supplier_organization_id=supplier_org_id, coordinating_fpo_id=fpo_id)
        db.add(quote); db.flush()
    acting_org_id = actor_org("fpo_manager") if g.principal.has_role("fpo_manager") else supplier_org_id
    quoted_quality = min((lot.quality_grade for lot, _ in allocations), key=lambda grade: QUALITY_RANK.get(grade, 0))
    delivery_charge = max((lot.delivery_charge_paise or 0 for lot, _ in allocations), default=0) if req.delivery_mode == "seller_delivery" else 0
    revision = QuoteRevision(quotation_id=quote.id, revision_number=revision_no, actor_user_id=g.principal.user.id, actor_organization_id=acting_org_id, action="offer" if revision_no == 1 else "counter", offered_quantity_kg=offered, price_paise_per_kg=price_paise, quality_grade=quoted_quality, delivery_date=delivery_date, delivery_terms=delivery_terms, delivery_mode=req.delivery_mode, delivery_charge_paise=delivery_charge, note=note)
    db.add(revision); db.flush()
    for lot, qty in allocations:
        db.add(QuoteAllocation(quote_revision_id=revision.id, produce_lot_id=lot.id, farmer_organization_id=lot.farmer_organization_id, quantity_kg=qty))
    record_audit(db, "quotation.submitted", "quotation", quote.id, actor=g.principal.user, organization_id=supplier_org_id, details={"revision": revision_no})
    enqueue(db, "quotation.submitted", {"organization_id": str(req.buyer_organization_id), "title": "New quotation", "body": f"A supplier quoted for {req.crop}.", "link": f"/requirements/{req.id}"}, f"quote:{quote.id}:r{revision_no}")
    db.commit(); return jsonify(id=str(quote.id), revision_number=revision_no, status=quote.status), 201


@bp.get("/quotations")
@require_auth
def list_quotes():
    db = get_session(); query = select(Quotation).order_by(Quotation.updated_at.desc())
    if g.principal.has_role("buyer"):
        query = query.join(BuyerRequirement).where(BuyerRequirement.buyer_organization_id.in_(g.principal.organization_ids))
    elif not g.principal.has_role("admin"):
        query = query.where(or_(Quotation.supplier_organization_id.in_(g.principal.organization_ids), Quotation.coordinating_fpo_id.in_(g.principal.organization_ids)))
    result = []
    for quote in db.scalars(query):
        rev = db.scalar(select(QuoteRevision).where(QuoteRevision.quotation_id == quote.id, QuoteRevision.revision_number == quote.current_revision_number))
        req = db.get(BuyerRequirement, quote.requirement_id); supplier = db.get(Organization, quote.supplier_organization_id)
        result.append({"id": str(quote.id), "status": quote.status, "version": quote.version, "requirement": requirement_json(req), "supplier": org_json(supplier, rating_summary(db, supplier.id)), "revision": {"number": rev.revision_number, "quantity_kg": float(rev.offered_quantity_kg), "price_paise_per_kg": rev.price_paise_per_kg, "price_inr_per_kg": rev.price_paise_per_kg / 100, "total_paise": int(Decimal(rev.offered_quantity_kg) * rev.price_paise_per_kg), "quality_grade": rev.quality_grade, "delivery_date": rev.delivery_date.isoformat(), "delivery_terms": rev.delivery_terms, "delivery_mode": rev.delivery_mode, "delivery_charge_paise": rev.delivery_charge_paise, "delivery_charge_inr": rev.delivery_charge_paise / 100, "note": rev.note}})
    return jsonify(items=result)


def safe_csv(value):
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


@bp.get("/requirements/export.csv")
@require_roles("buyer", "admin")
def export_requirements():
    db = get_session(); rows = db.scalars(select(BuyerRequirement).where(BuyerRequirement.buyer_organization_id.in_(g.principal.organization_ids))).all()
    stream = io.StringIO(); writer = csv.writer(stream, lineterminator="\r\n"); writer.writerow(["Crop", "Variety", "Quantity kg", "Quality", "Destination", "Deadline", "Status"])
    for x in rows: writer.writerow([safe_csv(x.crop), safe_csv(x.variety), x.quantity_kg, x.acceptable_quality, safe_csv(x.destination), x.delivery_deadline, x.status])
    return Response("\ufeff" + stream.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=agrilink-requirements.csv"})
