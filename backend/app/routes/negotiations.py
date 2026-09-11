from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select

from ..db import get_session
from ..models import (
    BuyerRequirement,
    NegotiationMessage,
    Order,
    OrderLine,
    Organization,
    ProduceLot,
    Quotation,
    QuoteAllocation,
    QuoteRevision,
    User,
)
from ..security import can_access_farmer_org, require_auth
from ..serializers import lot_json, org_json, requirement_json
from ..services.audit import record_audit
from ..services.matching import available_quantity
from ..services.outbox import enqueue
from ..services.reviews import rating_summary


bp = Blueprint("negotiations", __name__, url_prefix="/api")
ACTIVE_STATUSES = {"awaiting_buyer", "awaiting_supplier", "agreed"}
TERMINAL_STATUSES = {"accepted", "rejected", "withdrawn"}


def _positive_quantity(value, field="quantity_kg") -> Decimal:
    try:
        quantity = Decimal(str(value)).quantize(Decimal("0.001"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a number.")
    if quantity <= 0:
        raise ValueError(f"{field} must be greater than zero.")
    return quantity


def _price_paise(value) -> int:
    try:
        price = int((Decimal(str(value)) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        raise ValueError("price_inr_per_kg must be a number.")
    if price <= 0:
        raise ValueError("Price must be greater than zero.")
    return price


def _quote_context(db, quote_id, *, lock=False):
    query = select(Quotation).where(Quotation.id == quote_id)
    quote = db.scalar(query.with_for_update() if lock else query)
    if not quote:
        return None, None
    return quote, db.get(BuyerRequirement, quote.requirement_id)


def _party(quote: Quotation, requirement: BuyerRequirement):
    principal = g.principal
    if principal.has_role("buyer") and requirement.buyer_organization_id in principal.organization_ids:
        return "buyer", requirement.buyer_organization_id
    if principal.has_role("farmer") and quote.supplier_organization_id in principal.organization_ids:
        return "supplier", quote.supplier_organization_id
    if (
        principal.has_role("fpo_manager")
        and quote.coordinating_fpo_id
        and quote.coordinating_fpo_id in principal.organization_ids
    ):
        return "supplier", quote.coordinating_fpo_id
    if principal.has_role("admin"):
        return "admin", next(iter(principal.organization_ids), None)
    return None, None


def _deny_unless_participant(quote, requirement):
    side, organization_id = _party(quote, requirement)
    if not side:
        return None, None, (jsonify(error="permission_denied", message="This negotiation is private to its participants."), 403)
    return side, organization_id, None


def _revision(db, quote):
    return db.scalar(
        select(QuoteRevision).where(
            QuoteRevision.quotation_id == quote.id,
            QuoteRevision.revision_number == quote.current_revision_number,
        )
    )


def _revision_json(db, revision):
    actor = db.get(User, revision.actor_user_id)
    actor_org = db.get(Organization, revision.actor_organization_id) if revision.actor_organization_id else None
    allocations = []
    for allocation in db.scalars(
        select(QuoteAllocation)
        .where(QuoteAllocation.quote_revision_id == revision.id)
        .order_by(QuoteAllocation.created_at)
    ):
        lot = db.get(ProduceLot, allocation.produce_lot_id)
        farm = db.get(Organization, allocation.farmer_organization_id)
        allocations.append(
            {
                "id": str(allocation.id),
                "quantity_kg": float(allocation.quantity_kg),
                "lot": lot_json(lot, available_quantity(db, lot.id)),
                "farmer": org_json(farm),
            }
        )
    return {
        "id": str(revision.id),
        "number": revision.revision_number,
        "action": revision.action,
        "actor": {"id": str(actor.id), "name": actor.full_name},
        "actor_organization": org_json(actor_org) if actor_org else None,
        "quantity_kg": float(revision.offered_quantity_kg),
        "price_paise_per_kg": revision.price_paise_per_kg,
        "price_inr_per_kg": revision.price_paise_per_kg / 100,
        "total_paise": int(Decimal(revision.offered_quantity_kg) * revision.price_paise_per_kg),
        "quality_grade": revision.quality_grade,
        "delivery_date": revision.delivery_date.isoformat(),
        "delivery_terms": revision.delivery_terms,
        "delivery_mode": revision.delivery_mode,
        "delivery_charge_paise": revision.delivery_charge_paise,
        "delivery_charge_inr": revision.delivery_charge_paise / 100,
        "note": revision.note,
        "created_at": revision.created_at.isoformat(),
        "allocations": allocations,
    }


def _actions(side, quote):
    return {
        "can_counter": (side == "buyer" and quote.status == "awaiting_buyer")
        or (side == "supplier" and quote.status == "awaiting_supplier"),
        "can_accept_terms": side == "supplier" and quote.status == "awaiting_supplier",
        "can_confirm_order": side == "buyer" and quote.status in {"awaiting_buyer", "agreed"},
        "can_reject": side == "buyer" and quote.status in {"awaiting_buyer", "awaiting_supplier", "agreed"},
        "can_withdraw": side == "supplier" and quote.status in ACTIVE_STATUSES,
        "can_message": side in {"buyer", "supplier"},
    }


def _summary_json(db, quote, requirement, side):
    current = _revision(db, quote)
    supplier = db.get(Organization, quote.supplier_organization_id)
    return {
        "id": str(quote.id),
        "status": quote.status,
        "version": quote.version,
        "side": side,
        "requirement": requirement_json(requirement),
        "supplier": org_json(supplier, rating_summary(db, supplier.id)),
        "revision": _revision_json(db, current),
        "actions": _actions(side, quote),
    }


def _notify_other_party(db, quote, requirement, *, title, body, event_key):
    current_side, _ = _party(quote, requirement)
    if current_side == "buyer":
        organization_id = quote.coordinating_fpo_id or quote.supplier_organization_id
    else:
        organization_id = requirement.buyer_organization_id
    enqueue(
        db,
        "negotiation.updated",
        {
            "organization_id": str(organization_id),
            "title": title,
            "body": body,
            "link": f"/negotiations/{quote.id}",
        },
        event_key,
    )


@bp.get("/negotiations")
@require_auth
def list_negotiations():
    db = get_session()
    query = select(Quotation).order_by(Quotation.updated_at.desc())
    if g.principal.has_role("buyer"):
        query = query.join(BuyerRequirement).where(
            BuyerRequirement.buyer_organization_id.in_(g.principal.organization_ids)
        )
    elif g.principal.has_role("fpo_manager"):
        query = query.where(Quotation.coordinating_fpo_id.in_(g.principal.organization_ids))
    elif g.principal.has_role("farmer"):
        query = query.where(Quotation.supplier_organization_id.in_(g.principal.organization_ids))
    elif not g.principal.has_role("admin"):
        return jsonify(items=[])
    items = []
    for quote in db.scalars(query.limit(100)):
        requirement = db.get(BuyerRequirement, quote.requirement_id)
        side, _ = _party(quote, requirement)
        if side:
            items.append(_summary_json(db, quote, requirement, side))
    return jsonify(items=items)


@bp.get("/quotations/<uuid:quote_id>")
@require_auth
def negotiation_detail(quote_id):
    db = get_session()
    quote, requirement = _quote_context(db, quote_id)
    if not quote:
        return jsonify(error="not_found", message="Negotiation not found."), 404
    side, _, denial = _deny_unless_participant(quote, requirement)
    if denial:
        return denial
    data = _summary_json(db, quote, requirement, side)
    data["revisions"] = [
        _revision_json(db, revision)
        for revision in db.scalars(
            select(QuoteRevision)
            .where(QuoteRevision.quotation_id == quote.id)
            .order_by(QuoteRevision.revision_number)
        )
    ]
    messages = []
    for message in db.scalars(
        select(NegotiationMessage)
        .where(NegotiationMessage.quotation_id == quote.id)
        .order_by(NegotiationMessage.created_at)
    ):
        author = db.get(User, message.author_user_id)
        organization = db.get(Organization, message.author_organization_id)
        messages.append(
            {
                "id": str(message.id),
                "body": message.body,
                "created_at": message.created_at.isoformat(),
                "mine": message.author_user_id == g.principal.user.id,
                "author": {"id": str(author.id), "name": author.full_name},
                "organization": org_json(organization),
            }
        )
    data["messages"] = messages
    return jsonify(data)


@bp.post("/quotations/<uuid:quote_id>/messages")
@require_auth
def add_message(quote_id):
    db = get_session()
    quote, requirement = _quote_context(db, quote_id)
    if not quote:
        return jsonify(error="not_found", message="Negotiation not found."), 404
    side, organization_id, denial = _deny_unless_participant(quote, requirement)
    if denial:
        return denial
    if side == "admin":
        return jsonify(error="permission_denied", message="Administrators can inspect but cannot join negotiations."), 403
    data = request.get_json(silent=True) or {}
    body = str(data.get("body", "")).strip()
    client_message_id = str(data.get("client_message_id", "")).strip()
    if not body or len(body) > 2000 or not client_message_id or len(client_message_id) > 80:
        return jsonify(error="validation_error", message="Enter a message between 1 and 2,000 characters."), 422
    existing = db.scalar(
        select(NegotiationMessage).where(
            NegotiationMessage.author_user_id == g.principal.user.id,
            NegotiationMessage.client_message_id == client_message_id,
        )
    )
    if existing:
        if existing.quotation_id != quote.id or existing.body != body:
            return jsonify(error="idempotency_conflict", message="That message key was already used for different content."), 409
        return jsonify(id=str(existing.id), duplicate=True), 200
    message = NegotiationMessage(
        quotation_id=quote.id,
        author_user_id=g.principal.user.id,
        author_organization_id=organization_id,
        body=body,
        client_message_id=client_message_id,
    )
    db.add(message)
    db.flush()
    record_audit(
        db,
        "negotiation.message_added",
        "quotation",
        quote.id,
        actor=g.principal.user,
        organization_id=organization_id,
    )
    _notify_other_party(
        db,
        quote,
        requirement,
        title="New negotiation message",
        body=f"A participant replied about {requirement.crop}.",
        event_key=f"negotiation-message:{message.id}",
    )
    db.commit()
    return jsonify(id=str(message.id), duplicate=False), 201


def _scaled_allocations(db, current, offered):
    previous = list(
        db.scalars(
            select(QuoteAllocation)
            .where(QuoteAllocation.quote_revision_id == current.id)
            .order_by(QuoteAllocation.created_at)
        )
    )
    if not previous or offered > Decimal(current.offered_quantity_kg):
        raise ValueError("A buyer counter cannot increase the supplier's offered quantity.")
    remaining = offered
    result = []
    ratio = offered / Decimal(current.offered_quantity_kg)
    for index, allocation in enumerate(previous):
        available_for_lot = Decimal(allocation.quantity_kg)
        if index == len(previous) - 1:
            quantity = min(available_for_lot, remaining)
        else:
            quantity = min(
                available_for_lot,
                remaining,
                (available_for_lot * ratio).quantize(Decimal("0.001"), rounding=ROUND_DOWN),
            )
        remaining -= quantity
        if quantity > 0:
            result.append((allocation.produce_lot_id, allocation.farmer_organization_id, quantity))
    if remaining > 0:
        raise ValueError("The counteroffer cannot be allocated across the supplier's lots.")
    return result


@bp.post("/quotations/<uuid:quote_id>/counter")
@require_auth
def counter_offer(quote_id):
    db = get_session()
    quote, requirement = _quote_context(db, quote_id, lock=True)
    if not quote:
        return jsonify(error="not_found", message="Negotiation not found."), 404
    side, organization_id, denial = _deny_unless_participant(quote, requirement)
    if denial:
        return denial
    expected = "awaiting_buyer" if side == "buyer" else "awaiting_supplier"
    if side not in {"buyer", "supplier"} or quote.status != expected:
        return jsonify(error="invalid_status", message="It is not your turn to counter this offer."), 409
    data = request.get_json(silent=True) or {}
    if int(data.get("version", -1)) != quote.version:
        return jsonify(error="stale_update", message="This negotiation changed. Refresh before replying."), 409
    current = _revision(db, quote)
    try:
        offered = _positive_quantity(data.get("quantity_kg"))
        price = _price_paise(data.get("price_inr_per_kg"))
        delivery_date = date.fromisoformat(str(data.get("delivery_date")))
        quality = str(data.get("quality_grade", current.quality_grade)).upper().strip()
        terms = str(data.get("delivery_terms", "")).strip()
        note = str(data.get("note", "")).strip()
        if quality not in {"A", "B", "C"} or not terms or len(terms) > 2000 or len(note) > 2000:
            raise ValueError("Provide valid quality, delivery terms, and a note under 2,000 characters.")
        if delivery_date > requirement.delivery_deadline:
            raise ValueError("Delivery must be on or before the buyer's deadline.")
        committed = db.scalar(
            select(func.coalesce(func.sum(OrderLine.agreed_quantity_kg), 0))
            .join(Order, Order.id == OrderLine.order_id)
            .where(Order.requirement_id == requirement.id, Order.status != "cancelled")
        )
        if offered > Decimal(requirement.quantity_kg) - Decimal(committed):
            raise ValueError("The counter exceeds the requirement's remaining quantity.")
        if side == "buyer":
            allocations = _scaled_allocations(db, current, offered)
        else:
            allocations = []
            for item in data.get("allocations") or []:
                lot = db.get(ProduceLot, uuid.UUID(str(item.get("produce_lot_id"))))
                quantity = _positive_quantity(item.get("quantity_kg"))
                if not lot or not can_access_farmer_org(g.principal, lot.farmer_organization_id):
                    raise PermissionError
                if quantity > available_quantity(db, lot.id):
                    raise ValueError(f"Only {available_quantity(db, lot.id)} kg is currently available from a selected lot.")
                allocations.append((lot.id, lot.farmer_organization_id, quantity))
            if not allocations or sum((x[2] for x in allocations), Decimal("0")) != offered:
                raise ValueError("Supplier allocations must exactly equal the offered quantity.")
    except PermissionError:
        return jsonify(error="permission_denied", message="Every allocation must use an authorized produce lot."), 403
    except (ValueError, InvalidOperation) as exc:
        return jsonify(error="validation_error", message=str(exc)), 422

    revision_number = quote.current_revision_number + 1
    revision = QuoteRevision(
        quotation_id=quote.id,
        revision_number=revision_number,
        actor_user_id=g.principal.user.id,
        actor_organization_id=organization_id,
        action="counter",
        offered_quantity_kg=offered,
        price_paise_per_kg=price,
        quality_grade=quality,
        delivery_date=delivery_date,
        delivery_terms=terms,
        delivery_mode=current.delivery_mode,
        delivery_charge_paise=current.delivery_charge_paise,
        note=note,
    )
    db.add(revision)
    db.flush()
    for lot_id, farmer_id, quantity in allocations:
        db.add(
            QuoteAllocation(
                quote_revision_id=revision.id,
                produce_lot_id=lot_id,
                farmer_organization_id=farmer_id,
                quantity_kg=quantity,
            )
        )
    quote.current_revision_number = revision_number
    quote.status = "awaiting_supplier" if side == "buyer" else "awaiting_buyer"
    quote.version += 1
    record_audit(
        db,
        "negotiation.countered",
        "quotation",
        quote.id,
        actor=g.principal.user,
        organization_id=organization_id,
        details={"revision": revision_number, "side": side},
    )
    _notify_other_party(
        db,
        quote,
        requirement,
        title="New counteroffer",
        body=f"New terms were proposed for {requirement.crop}.",
        event_key=f"negotiation-counter:{revision.id}",
    )
    db.commit()
    return jsonify(id=str(quote.id), revision_number=revision_number, status=quote.status, version=quote.version), 201


@bp.post("/quotations/<uuid:quote_id>/accept-terms")
@require_auth
def accept_terms(quote_id):
    db = get_session()
    quote, requirement = _quote_context(db, quote_id, lock=True)
    if not quote:
        return jsonify(error="not_found", message="Negotiation not found."), 404
    side, organization_id, denial = _deny_unless_participant(quote, requirement)
    if denial:
        return denial
    data = request.get_json(silent=True) or {}
    if side != "supplier" or quote.status != "awaiting_supplier":
        return jsonify(error="invalid_status", message="Only the supplier can agree to the buyer's latest counteroffer."), 409
    if int(data.get("version", -1)) != quote.version:
        return jsonify(error="stale_update", message="This negotiation changed. Refresh before accepting."), 409
    quote.status = "agreed"
    quote.version += 1
    record_audit(db, "negotiation.terms_agreed", "quotation", quote.id, actor=g.principal.user, organization_id=organization_id)
    _notify_other_party(
        db,
        quote,
        requirement,
        title="Supplier agreed to your terms",
        body=f"Review and confirm the {requirement.crop} order to reserve stock.",
        event_key=f"negotiation-agreed:{quote.id}:v{quote.version}",
    )
    db.commit()
    return jsonify(status=quote.status, version=quote.version)


def _close(quote_id, action):
    db = get_session()
    quote, requirement = _quote_context(db, quote_id, lock=True)
    if not quote:
        return jsonify(error="not_found", message="Negotiation not found."), 404
    side, organization_id, denial = _deny_unless_participant(quote, requirement)
    if denial:
        return denial
    if quote.status not in ACTIVE_STATUSES:
        return jsonify(error="invalid_status", message="This negotiation is already closed."), 409
    if action == "rejected" and side != "buyer":
        return jsonify(error="permission_denied", message="Only the buyer can reject this negotiation."), 403
    if action == "withdrawn" and side != "supplier":
        return jsonify(error="permission_denied", message="Only the supplier can withdraw this negotiation."), 403
    data = request.get_json(silent=True) or {}
    if int(data.get("version", -1)) != quote.version:
        return jsonify(error="stale_update", message="This negotiation changed. Refresh before closing it."), 409
    quote.status = action
    quote.version += 1
    record_audit(db, f"negotiation.{action}", "quotation", quote.id, actor=g.principal.user, organization_id=organization_id)
    _notify_other_party(
        db,
        quote,
        requirement,
        title="Negotiation closed",
        body=f"The {requirement.crop} negotiation was {action}.",
        event_key=f"negotiation-{action}:{quote.id}:v{quote.version}",
    )
    db.commit()
    return jsonify(status=quote.status, version=quote.version)


@bp.post("/quotations/<uuid:quote_id>/reject")
@require_auth
def reject(quote_id):
    return _close(quote_id, "rejected")


@bp.post("/quotations/<uuid:quote_id>/withdraw")
@require_auth
def withdraw(quote_id):
    return _close(quote_id, "withdrawn")
