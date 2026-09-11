from __future__ import annotations

from sqlalchemy import func, select

from ..models import Order, OrderLine, OrderRating, Organization


def rating_summary(db, organization_id) -> dict:
    row = db.execute(
        select(
            func.count(OrderRating.id),
            func.avg(OrderRating.overall_rating),
            func.avg(OrderRating.quality_rating),
            func.avg(OrderRating.delivery_rating),
            func.avg(OrderRating.communication_rating),
        ).where(OrderRating.supplier_organization_id == organization_id)
    ).one()
    return {
        "average_rating": round(float(row[1] or 0), 1),
        "quality_rating": round(float(row[2] or 0), 1),
        "delivery_rating": round(float(row[3] or 0), 1),
        "communication_rating": round(float(row[4] or 0), 1),
        "review_count": int(row[0] or 0),
    }


def review_json(db, review: OrderRating, *, include_buyer=False) -> dict:
    order = db.get(Order, review.order_id)
    supplier = db.get(Organization, review.supplier_organization_id)
    lines = list(db.scalars(select(OrderLine).where(OrderLine.order_id == review.order_id)))
    result = {
        "review_id": str(review.id),
        "order_id": str(review.order_id),
        "order_number": order.order_number if order else "",
        "supplier_id": str(review.supplier_organization_id),
        "supplier_name": supplier.name if supplier else "Supplier",
        "reviewed_role": review.reviewed_role,
        "overall_rating": review.overall_rating,
        "quality_rating": review.quality_rating,
        "delivery_rating": review.delivery_rating,
        "communication_rating": review.communication_rating,
        "comment": review.comment,
        "version": review.version,
        "created_at": review.created_at.isoformat(),
        "updated_at": review.updated_at.isoformat(),
        "buyer_label": "Verified buyer",
        "order": {
            "crops": [line.crop for line in lines],
            "quantity_kg": sum(float(line.agreed_quantity_kg) for line in lines),
            "delivery_deadline": order.delivery_deadline.isoformat() if order else None,
        },
    }
    if include_buyer:
        result["buyer_organization_id"] = str(review.buyer_organization_id)
    return result

