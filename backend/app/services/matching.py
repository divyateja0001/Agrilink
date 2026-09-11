from __future__ import annotations

from datetime import date
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import func, select

from ..models import ProduceLot, StockReservation


QUALITY_RANK = {"A": 3, "B": 2, "C": 1}


def available_expression():
    active_reserved = (
        select(func.coalesce(func.sum(
            StockReservation.reserved_quantity_kg
            - StockReservation.dispatched_quantity_kg
            - StockReservation.released_quantity_kg
        ), 0))
        .where(StockReservation.produce_lot_id == ProduceLot.id, StockReservation.status == "active")
        .correlate(ProduceLot)
        .scalar_subquery()
    )
    return ProduceLot.quantity_on_hand_kg - active_reserved


def available_quantity(db, lot_id) -> Decimal:
    value = db.scalar(select(available_expression()).where(ProduceLot.id == lot_id))
    return Decimal(value or 0)


def haversine_km(a_lat, a_lon, b_lat, b_lon):
    earth = 6371.0
    dlat, dlon = radians(float(b_lat - a_lat)), radians(float(b_lon - a_lon))
    x = sin(dlat / 2) ** 2 + cos(radians(float(a_lat))) * cos(radians(float(b_lat))) * sin(dlon / 2) ** 2
    return round(earth * 2 * asin(sqrt(x)), 1)


def match_requirement(db, requirement):
    lots = list(db.scalars(select(ProduceLot).where(
        func.lower(ProduceLot.crop) == requirement.crop.lower(),
        ProduceLot.status == "active",
        ProduceLot.available_from <= requirement.delivery_deadline,
        ProduceLot.available_until >= date.today(),
    )))
    eligible = []
    for lot in lots:
        if requirement.variety and lot.variety.lower() != requirement.variety.lower():
            continue
        if QUALITY_RANK.get(lot.quality_grade, 0) < QUALITY_RANK.get(requirement.acceptable_quality, 0):
            continue
        if lot.delivery_mode != requirement.delivery_mode:
            continue
        distance = None
        if requirement.delivery_mode == "seller_delivery" and lot.delivery_service_location:
            same_area = lot.delivery_service_location.casefold() in requirement.destination.casefold() or requirement.destination.casefold() in lot.delivery_service_location.casefold()
            if not same_area:
                if None in (lot.latitude, lot.longitude, requirement.destination_latitude, requirement.destination_longitude, lot.delivery_radius_km):
                    continue
                distance = haversine_km(lot.latitude, lot.longitude, requirement.destination_latitude, requirement.destination_longitude)
                if distance > float(lot.delivery_radius_km):
                    continue
        available = available_quantity(db, lot.id)
        if available <= 0:
            continue
        eligible.append((lot, available, distance))
    if not eligible:
        return []
    lowest = min(lot.asking_price_paise for lot, _, _ in eligible)
    matches = []
    for lot, available, distance in eligible:
        coverage = min(Decimal("1"), available / requirement.quantity_kg)
        quantity_score = float(coverage) * 50
        if requirement.budget_price_paise:
            price_score = 30.0 if lot.asking_price_paise <= requirement.budget_price_paise else 30 * requirement.budget_price_paise / lot.asking_price_paise
        else:
            price_score = 30 * lowest / lot.asking_price_paise
        buffer_days = max(0, (requirement.delivery_deadline - lot.available_from).days)
        delivery_score = 20 * min(buffer_days / 14, 1)
        explanations = [f"Covers {round(float(coverage) * 100)}% of your requirement.", "Available before your delivery deadline."]
        if requirement.budget_price_paise and lot.asking_price_paise <= requirement.budget_price_paise:
            explanations.append("Within your stated budget.")
        explanations.append("Delivery mode matches your requirement." if requirement.delivery_mode == "seller_delivery" else "Available for buyer pickup.")
        if distance is not None:
            explanations.append(f"About {distance} km straight-line distance, within the seller's delivery radius.")
        matches.append({
            "lot": lot,
            "available_kg": available,
            "score": round(quantity_score + price_score + delivery_score, 1),
            "score_components": {"quantity": round(quantity_score, 1), "price": round(price_score, 1), "delivery": round(delivery_score, 1)},
            "explanations": explanations,
        })
    return sorted(matches, key=lambda item: (-item["score"], item["lot"].asking_price_paise, str(item["lot"].id)))


def allocation_preview(db, requirement):
    remaining = Decimal(requirement.quantity_kg)
    allocations = []
    for item in match_requirement(db, requirement):
        quantity = min(item["available_kg"], remaining)
        if quantity <= 0:
            break
        allocations.append({**item, "suggested_quantity_kg": quantity})
        remaining -= quantity
    return allocations, remaining
