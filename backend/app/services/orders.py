from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..models import (
    BuyerRequirement,
    Dispatch,
    DispatchLine,
    IdempotencyRecord,
    Order,
    OrderGroup,
    OrderLine,
    PaymentEvent,
    ProduceLot,
    Quotation,
    QuoteAllocation,
    QuoteRevision,
    Receipt,
    ReceiptLine,
    StockReservation,
    TrackingEvent,
)
from .audit import record_audit
from .matching import available_quantity
from .outbox import enqueue


class DomainError(Exception):
    def __init__(self, message: str, status: int = 422, code: str = "invalid_operation"):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def canonical_hash(payload: dict) -> str:
    value = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(value.encode()).hexdigest()


def begin_idempotent(db, actor_id, operation: str, key: str, payload: dict):
    if not key or len(key) > 120:
        raise DomainError("A valid Idempotency-Key header is required.", 400, "idempotency_key_required")
    digest = canonical_hash(payload)
    record = db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.actor_user_id == actor_id,
        IdempotencyRecord.operation == operation,
        IdempotencyRecord.idempotency_key == key,
    ).with_for_update())
    if record:
        if record.request_hash != digest:
            raise DomainError("This idempotency key was already used with a different payload.", 409, "idempotency_conflict")
        if record.response_body:
            return record, record.response_body
        raise DomainError("The original request is still being processed.", 409, "request_in_progress")
    record = IdempotencyRecord(actor_user_id=actor_id, operation=operation, idempotency_key=key, request_hash=digest)
    db.add(record)
    db.flush()
    return record, None


def _order_dict(order):
    return {"order_id": str(order.id), "order_number": order.order_number, "order_group_id": str(order.order_group_id)}


def confirm_quotes(db, *, actor, buyer_org_id, requirement_id, quotation_ids, key, payload):
    idem, prior = begin_idempotent(db, actor.id, "confirm_quotes", key, payload)
    if prior:
        return prior
    requirement = db.scalar(select(BuyerRequirement).where(BuyerRequirement.id == requirement_id).with_for_update())
    if not requirement or requirement.buyer_organization_id != buyer_org_id:
        raise DomainError("Requirement not found.", 404, "not_found")
    if requirement.status not in {"open", "partially_fulfilled"}:
        raise DomainError("This requirement cannot accept more quotations.", 409, "invalid_status")
    existing_committed = Decimal(db.scalar(select(func.coalesce(func.sum(OrderLine.agreed_quantity_kg), 0)).join(Order).where(
        Order.requirement_id == requirement.id,
        Order.status != "cancelled",
    )) or 0)
    remaining_demand = Decimal(requirement.quantity_kg) - existing_committed
    if remaining_demand <= 0:
        raise DomainError("The requirement is already fully allocated.", 409, "requirement_filled")

    quotes = list(db.scalars(select(Quotation).where(Quotation.id.in_(quotation_ids), Quotation.requirement_id == requirement.id).with_for_update()))
    if len(quotes) != len(set(quotation_ids)):
        raise DomainError("One or more quotations were not found.", 404, "not_found")
    quote_data = []
    lot_ids = []
    total_new = Decimal("0")
    for quote in quotes:
        if quote.status not in {"awaiting_buyer", "agreed"}:
            raise DomainError("Only supplier-authored or mutually agreed terms can be confirmed.", 409, "invalid_quote_status")
        revision = db.scalar(select(QuoteRevision).where(
            QuoteRevision.quotation_id == quote.id,
            QuoteRevision.revision_number == quote.current_revision_number,
        ))
        allocations = list(db.scalars(select(QuoteAllocation).where(QuoteAllocation.quote_revision_id == revision.id)))
        if not allocations:
            raise DomainError("A quotation must contain at least one lot allocation.")
        allocated = sum((Decimal(a.quantity_kg) for a in allocations), Decimal("0"))
        if allocated != Decimal(revision.offered_quantity_kg):
            raise DomainError("Quotation allocations do not equal the offered quantity.")
        total_new += allocated
        lot_ids.extend(a.produce_lot_id for a in allocations)
        quote_data.append((quote, revision, allocations))
    if total_new > remaining_demand:
        raise DomainError("Selected quotations exceed the requirement's remaining quantity.", 409, "requirement_overallocated")

    locked_lots = {lot.id: lot for lot in db.scalars(select(ProduceLot).where(ProduceLot.id.in_(sorted(set(lot_ids), key=str))).order_by(ProduceLot.id).with_for_update())}
    requested_by_lot = {}
    for _, _, allocations in quote_data:
        for allocation in allocations:
            requested_by_lot[allocation.produce_lot_id] = requested_by_lot.get(allocation.produce_lot_id, Decimal("0")) + Decimal(allocation.quantity_kg)
    for lot_id, requested in requested_by_lot.items():
        lot = locked_lots.get(lot_id)
        if not lot or lot.status != "active" or available_quantity(db, lot_id) < requested:
            raise DomainError("Stock changed before confirmation. Refresh allocations and try again.", 409, "stock_unavailable")

    group = OrderGroup(requirement_id=requirement.id, buyer_organization_id=buyer_org_id)
    db.add(group)
    db.flush()
    created = []
    order_index = 0
    for quote, revision, allocations in quote_data:
        by_farmer = {}
        for allocation in allocations:
            by_farmer.setdefault(allocation.farmer_organization_id, []).append(allocation)
        for farmer_org_id, farmer_allocations in by_farmer.items():
            order_index += 1
            order = Order(
                order_number=f"AG-{datetime.now(timezone.utc):%y%m%d}-{str(group.id)[:4].upper()}{order_index}",
                order_group_id=group.id,
                requirement_id=requirement.id,
                quotation_id=quote.id,
                buyer_organization_id=buyer_org_id,
                supplier_organization_id=farmer_org_id,
                coordinating_fpo_id=quote.coordinating_fpo_id,
                delivery_deadline=revision.delivery_date,
                delivery_mode=revision.delivery_mode,
                delivery_charge_paise=revision.delivery_charge_paise,
            )
            db.add(order)
            db.flush()
            for allocation in farmer_allocations:
                lot = locked_lots[allocation.produce_lot_id]
                line = OrderLine(
                    order_id=order.id,
                    produce_lot_id=lot.id,
                    farmer_organization_id=allocation.farmer_organization_id,
                    crop=lot.crop,
                    variety=lot.variety,
                    quality_grade=revision.quality_grade,
                    agreed_quantity_kg=allocation.quantity_kg,
                    agreed_price_paise_per_kg=revision.price_paise_per_kg,
                    delivery_terms=revision.delivery_terms,
                )
                db.add(line)
                db.flush()
                db.add(StockReservation(order_line_id=line.id, produce_lot_id=lot.id, reserved_quantity_kg=allocation.quantity_kg))
            created.append(order)
            db.add(TrackingEvent(order_id=order.id, actor_user_id=actor.id, status="confirmed", note="Buyer confirmed the agreed quotation."))
            record_audit(db, "order.confirmed", "order", order.id, actor=actor, organization_id=buyer_org_id, details={"order_number": order.order_number})
            enqueue(db, "order.confirmed", {
                "organization_id": str(order.supplier_organization_id),
                "title": "New confirmed order",
                "body": f"Order {order.order_number} is ready for dispatch.",
                "link": f"/orders/{order.id}",
            }, f"order.confirmed:{order.id}")
        quote.status = "accepted"
        quote.version += 1
    allocated_after = existing_committed + total_new
    requirement.status = "fulfilled" if allocated_after == Decimal(requirement.quantity_kg) else "partially_fulfilled"
    requirement.version += 1
    response = {"order_group_id": str(group.id), "orders": [_order_dict(o) for o in created], "idempotent_replay": False}
    idem.response_status = 201
    idem.response_body = response
    db.flush()
    return response


def dispatch_order(db, *, actor, order, lines, reference, note, key, payload):
    idem, prior = begin_idempotent(db, actor.id, "dispatch_order", key, payload)
    if prior:
        return prior
    order = db.scalar(select(Order).where(Order.id == order.id).with_for_update())
    if order.status not in {"confirmed", "partially_dispatched"}:
        raise DomainError("This order cannot be dispatched in its current state.", 409, "invalid_status")
    line_map = {line.id: line for line in db.scalars(select(OrderLine).where(OrderLine.order_id == order.id).with_for_update())}
    reservation_map = {r.order_line_id: r for r in db.scalars(select(StockReservation).where(StockReservation.order_line_id.in_(line_map)).with_for_update())}
    dispatch = Dispatch(order_id=order.id, reference=reference, note=note, carrier_name=str(payload.get("carrier_name") or "")[:120] or None, carrier_phone=str(payload.get("carrier_phone") or "")[:30] or None)
    db.add(dispatch)
    db.flush()
    for item in lines:
        line_id, quantity = uuid.UUID(item["order_line_id"]), Decimal(str(item["quantity_kg"]))
        if quantity <= 0 or line_id not in line_map:
            raise DomainError("Dispatch lines must reference this order with positive quantities.")
        reservation = reservation_map[line_id]
        remaining = Decimal(reservation.reserved_quantity_kg) - Decimal(reservation.dispatched_quantity_kg) - Decimal(reservation.released_quantity_kg)
        if quantity > remaining:
            raise DomainError("Dispatch quantity exceeds reserved stock.", 409, "dispatch_exceeds_reservation")
        lot = db.scalar(select(ProduceLot).where(ProduceLot.id == reservation.produce_lot_id).with_for_update())
        if quantity > Decimal(lot.quantity_on_hand_kg):
            raise DomainError("Physical stock is no longer sufficient.", 409, "stock_unavailable")
        lot.quantity_on_hand_kg -= quantity
        lot.version += 1
        reservation.dispatched_quantity_kg += quantity
        if Decimal(reservation.dispatched_quantity_kg) + Decimal(reservation.released_quantity_kg) == Decimal(reservation.reserved_quantity_kg):
            reservation.status = "fulfilled"
        db.add(DispatchLine(dispatch_id=dispatch.id, order_line_id=line_id, quantity_kg=quantity))
    total_reserved = sum((Decimal(r.reserved_quantity_kg) for r in reservation_map.values()), Decimal("0"))
    total_dispatched = sum((Decimal(r.dispatched_quantity_kg) for r in reservation_map.values()), Decimal("0"))
    order.status = "dispatched" if total_dispatched == total_reserved else "partially_dispatched"
    order.version += 1
    db.add(TrackingEvent(order_id=order.id, actor_user_id=actor.id, status="in_transit" if order.delivery_mode == "seller_delivery" else "ready_for_pickup", note=note or reference))
    response = {"dispatch_id": str(dispatch.id), "order_id": str(order.id), "status": order.status}
    idem.response_status, idem.response_body = 201, response
    record_audit(db, "order.dispatched", "dispatch", dispatch.id, actor=actor, organization_id=order.supplier_organization_id)
    enqueue(db, "order.dispatched", {"organization_id": str(order.buyer_organization_id), "title": "Produce dispatched", "body": f"{order.order_number} has a new dispatch.", "link": f"/orders/{order.id}"}, f"dispatch:{dispatch.id}")
    return response


def receive_order(db, *, actor, order, lines, note, key, payload):
    idem, prior = begin_idempotent(db, actor.id, "receive_order", key, payload)
    if prior:
        return prior
    order = db.scalar(select(Order).where(Order.id == order.id).with_for_update())
    if order.status not in {"partially_dispatched", "dispatched", "partially_received"}:
        raise DomainError("This order has no receivable dispatch.", 409, "invalid_status")
    valid_lines = {line.id: line for line in db.scalars(select(OrderLine).where(OrderLine.order_id == order.id))}
    receipt = Receipt(order_id=order.id, recorded_by_user_id=actor.id, note=note)
    db.add(receipt)
    db.flush()
    for item in lines:
        line_id, quantity = uuid.UUID(item["order_line_id"]), Decimal(str(item["quantity_kg"]))
        if quantity <= 0 or line_id not in valid_lines:
            raise DomainError("Receipt lines must reference this order with positive quantities.")
        dispatched = Decimal(db.scalar(select(func.coalesce(func.sum(DispatchLine.quantity_kg), 0)).where(DispatchLine.order_line_id == line_id)) or 0)
        received = Decimal(db.scalar(select(func.coalesce(func.sum(ReceiptLine.quantity_kg), 0)).where(ReceiptLine.order_line_id == line_id)) or 0)
        if quantity > dispatched - received:
            raise DomainError("Received quantity cannot exceed dispatched quantity.", 409, "receipt_exceeds_dispatch")
        deduction = int(item.get("deduction_paise", 0))
        if deduction < 0:
            raise DomainError("Deductions cannot be negative.")
        db.add(ReceiptLine(receipt_id=receipt.id, order_line_id=line_id, quantity_kg=quantity, deduction_paise=deduction, deduction_reason=item.get("deduction_reason", "")))
    ordered = Decimal(db.scalar(select(func.sum(OrderLine.agreed_quantity_kg)).where(OrderLine.order_id == order.id)) or 0)
    previous_received = Decimal(db.scalar(select(func.coalesce(func.sum(ReceiptLine.quantity_kg), 0)).join(Receipt).where(Receipt.order_id == order.id)) or 0)
    new_received = previous_received + sum((Decimal(str(x["quantity_kg"])) for x in lines), Decimal("0"))
    order.status = "received" if new_received == ordered else "partially_received"
    order.version += 1
    db.add(TrackingEvent(order_id=order.id, actor_user_id=actor.id, status="delivered" if order.status == "received" else "partially_received", note=note))
    response = {"receipt_id": str(receipt.id), "order_id": str(order.id), "status": order.status}
    idem.response_status, idem.response_body = 201, response
    record_audit(db, "order.received", "receipt", receipt.id, actor=actor, organization_id=order.buyer_organization_id)
    enqueue(db, "order.received", {"organization_id": str(order.supplier_organization_id), "title": "Receipt recorded", "body": f"The buyer recorded produce received for {order.order_number}.", "link": f"/orders/{order.id}"}, f"receipt:{receipt.id}")
    return response


def record_payment(db, *, actor, order, amount_paise, outcome, key, payload):
    idem, prior = begin_idempotent(db, actor.id, "simulate_payment", key, payload)
    if prior:
        return prior
    if amount_paise <= 0 or outcome not in {"success", "failure"}:
        raise DomainError("Provide a positive amount and a simulated success or failure outcome.")
    event = PaymentEvent(order_id=order.id, actor_user_id=actor.id, amount_paise=amount_paise, outcome=outcome, external_reference=f"SIM-{uuid.uuid4().hex[:14].upper()}")
    db.add(event)
    db.flush()
    if outcome == "success":
        due = int(db.scalar(select(func.sum(OrderLine.agreed_quantity_kg * OrderLine.agreed_price_paise_per_kg)).where(OrderLine.order_id == order.id)) or 0)
        paid = int(db.scalar(select(func.coalesce(func.sum(PaymentEvent.amount_paise), 0)).where(PaymentEvent.order_id == order.id, PaymentEvent.outcome == "success")) or 0) + amount_paise
        order.payment_status = "paid" if paid >= due else "partially_paid"
    response = {"payment_event_id": str(event.id), "outcome": outcome, "payment_status": order.payment_status, "simulated": True}
    idem.response_status, idem.response_body = 201, response
    record_audit(db, f"payment.{outcome}", "payment_event", event.id, actor=actor, organization_id=order.buyer_organization_id, details={"simulated": True})
    return response
