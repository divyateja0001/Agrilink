from __future__ import annotations

from decimal import Decimal


def iso(value):
    return value.isoformat() if value else None


def money(paise):
    return None if paise is None else round(paise / 100, 2)


def quantity(value):
    return float(Decimal(value or 0))


def user_json(user):
    return {"id": str(user.id), "email": user.email, "full_name": user.full_name, "phone": user.phone, "locale": user.locale, "is_active": user.is_active}


def org_json(org, rating_summary=None):
    result = {"id": str(org.id), "name": org.name, "type": org.org_type, "location": org.location, "verified": bool(org.verified_at), "is_active": org.is_active}
    if rating_summary is not None:
        result["rating_summary"] = rating_summary
    return result


def lot_json(lot, available=None):
    return {
        "id": str(lot.id), "farmer_organization_id": str(lot.farmer_organization_id), "crop": lot.crop,
        "variety": lot.variety, "quality_grade": lot.quality_grade, "quantity_on_hand_kg": quantity(lot.quantity_on_hand_kg),
        "available_quantity_kg": quantity(available if available is not None else lot.quantity_on_hand_kg),
        "asking_price_paise": lot.asking_price_paise, "asking_price_inr": money(lot.asking_price_paise), "location": lot.location,
        "harvest_date": iso(lot.harvest_date), "available_from": iso(lot.available_from), "available_until": iso(lot.available_until),
        "description": lot.description, "photo_url": f"/uploads/{lot.photo_path}" if lot.photo_path else None,
        "location_recorded": bool(lot.latitude is not None and lot.longitude is not None),
        "delivery_mode": lot.delivery_mode,
        "delivery_service_location": lot.delivery_service_location,
        "delivery_radius_km": quantity(lot.delivery_radius_km) if lot.delivery_radius_km is not None else None,
        "delivery_charge_paise": lot.delivery_charge_paise,
        "delivery_charge_inr": money(lot.delivery_charge_paise),
        "status": lot.status, "version": lot.version,
    }


def requirement_json(req):
    return {
        "id": str(req.id), "buyer_organization_id": str(req.buyer_organization_id), "crop": req.crop, "variety": req.variety,
        "quantity_kg": quantity(req.quantity_kg), "acceptable_quality": req.acceptable_quality, "destination": req.destination,
        "delivery_deadline": iso(req.delivery_deadline), "budget_price_paise": req.budget_price_paise,
        "delivery_mode": req.delivery_mode,
        "budget_price_inr": money(req.budget_price_paise), "notes": req.notes, "status": req.status, "version": req.version,
    }
