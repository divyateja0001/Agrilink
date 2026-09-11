from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from ..models import (
    BuyerRequirement,
    Dispatch,
    DispatchDriverAssignment,
    DispatchLocation,
    Membership,
    Order,
    Organization,
    User,
)


ACTIVE_ORDER_STATUSES = {"partially_dispatched", "dispatched", "partially_received"}


def driver_assignment(db, dispatch_id, *, user_id=None, lock=False):
    statement = select(DispatchDriverAssignment).where(
        DispatchDriverAssignment.dispatch_id == dispatch_id,
        DispatchDriverAssignment.is_active.is_(True),
    )
    if user_id is not None:
        statement = statement.where(DispatchDriverAssignment.driver_user_id == user_id)
    if lock:
        statement = statement.with_for_update()
    return db.scalar(statement)


def user_is_driver(db, user_id):
    return db.scalar(
        select(Membership.id).where(
            Membership.user_id == user_id,
            Membership.role == "driver",
            Membership.is_active.is_(True),
        )
    ) is not None


def assign_driver(db, *, dispatch, driver, actor, vehicle_registration):
    if not user_is_driver(db, driver.id):
        raise ValueError("The selected account is not an active driver.")
    vehicle = str(vehicle_registration or dispatch.reference).strip()[:40]
    if not vehicle:
        raise ValueError("Enter a vehicle registration or label.")
    existing = driver_assignment(db, dispatch.id, lock=True)
    if existing:
        existing.driver_user_id = driver.id
        existing.assigned_by_user_id = actor.id
        existing.vehicle_registration = vehicle
        existing.sharing_status = "not_started"
        existing.version += 1
        return existing
    item = DispatchDriverAssignment(
        dispatch_id=dispatch.id,
        driver_user_id=driver.id,
        assigned_by_user_id=actor.id,
        vehicle_registration=vehicle,
    )
    db.add(item)
    db.flush()
    return item


def tracking_payload(db, assignment):
    dispatch = db.get(Dispatch, assignment.dispatch_id)
    order = db.get(Order, dispatch.order_id)
    requirement = db.get(BuyerRequirement, order.requirement_id)
    supplier = db.get(Organization, order.supplier_organization_id)
    buyer = db.get(Organization, order.buyer_organization_id)
    driver = db.get(User, assignment.driver_user_id)
    recent_desc = list(
        db.scalars(
            select(DispatchLocation)
            .where(DispatchLocation.dispatch_id == dispatch.id)
            .order_by(DispatchLocation.captured_at.desc())
            .limit(100)
        )
    )
    locations = list(reversed(recent_desc))
    now = datetime.now(timezone.utc)
    last = locations[-1] if locations else None
    if assignment.sharing_status == "sharing":
        age = (now - last.received_at).total_seconds() if last else None
        health = "live" if age is not None and age <= 20 else "waiting" if age is None else "stale"
    else:
        health = assignment.sharing_status
    return {
        "dispatch": {
            "id": str(dispatch.id),
            "reference": dispatch.reference,
            "status": dispatch.status,
            "carrier_name": dispatch.carrier_name,
            "carrier_phone": dispatch.carrier_phone,
            "vehicle_registration": assignment.vehicle_registration,
            "tracking_mode": assignment.tracking_mode,
            "sharing_status": assignment.sharing_status,
            "started_at": assignment.started_at.isoformat() if assignment.started_at else None,
            "stopped_at": assignment.stopped_at.isoformat() if assignment.stopped_at else None,
            "arrived_at": assignment.arrived_at.isoformat() if assignment.arrived_at else None,
            "last_location_at": assignment.last_location_at.isoformat() if assignment.last_location_at else None,
            "version": assignment.version,
        },
        "order": {
            "id": str(order.id),
            "order_number": order.order_number,
            "status": order.status,
            "supplier_name": supplier.name,
            "buyer_name": buyer.name,
        },
        "driver": {"id": str(driver.id), "name": driver.full_name, "phone": driver.phone},
        "pickup": {
            "label": supplier.location,
            "latitude": float(supplier.latitude) if supplier.latitude is not None else None,
            "longitude": float(supplier.longitude) if supplier.longitude is not None else None,
        },
        "destination": {
            "label": requirement.destination,
            "latitude": float(requirement.destination_latitude) if requirement.destination_latitude is not None else None,
            "longitude": float(requirement.destination_longitude) if requirement.destination_longitude is not None else None,
        },
        "locations": [
            {
                "id": str(item.id),
                "latitude": float(item.latitude),
                "longitude": float(item.longitude),
                "accuracy_m": float(item.accuracy_m),
                "captured_at": item.captured_at.isoformat(),
                "received_at": item.received_at.isoformat(),
                "simulated": item.is_simulated,
            }
            for item in locations
        ],
        "tracking_health": health,
        "server_time": now.isoformat(),
        "notice": "Arrival does not confirm buyer receipt.",
    }
