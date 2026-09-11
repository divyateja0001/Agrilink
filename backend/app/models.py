from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class User(Base, IdMixin):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(30))
    locale: Mapped[str] = mapped_column(String(5), default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Organization(Base, IdMixin):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(160), unique=True)
    org_type: Mapped[str] = mapped_column(String(30))
    location: Mapped[str] = mapped_column(String(200))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(Base, IdMixin):
    __tablename__ = "memberships"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),)


class FpoAuthorization(Base, IdMixin):
    __tablename__ = "fpo_authorizations"
    fpo_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    farmer_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    granted_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("fpo_organization_id", "farmer_organization_id", name="uq_fpo_farmer"),)


class UserSession(Base, IdMixin):
    __tablename__ = "user_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(96))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProduceLot(Base, IdMixin):
    __tablename__ = "produce_lots"
    farmer_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    crop: Mapped[str] = mapped_column(String(80), index=True)
    variety: Mapped[str] = mapped_column(String(80))
    quality_grade: Mapped[str] = mapped_column(String(10), index=True)
    quantity_on_hand_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    asking_price_paise: Mapped[int] = mapped_column(Integer)
    location: Mapped[str] = mapped_column(String(200), index=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    harvest_date: Mapped[date] = mapped_column(Date)
    available_from: Mapped[date] = mapped_column(Date)
    available_until: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, default="")
    photo_path: Mapped[str | None] = mapped_column(String(255))
    delivery_mode: Mapped[str] = mapped_column(String(24), default="buyer_pickup", index=True)
    delivery_service_location: Mapped[str | None] = mapped_column(String(200))
    delivery_radius_km: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    delivery_charge_paise: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint("quantity_on_hand_kg >= 0", name="ck_lot_quantity_nonnegative"),
        CheckConstraint("asking_price_paise > 0", name="ck_lot_price_positive"),
        CheckConstraint("available_until >= available_from", name="ck_lot_date_range"),
        CheckConstraint("delivery_mode IN ('buyer_pickup', 'seller_delivery')", name="ck_lot_delivery_mode"),
        CheckConstraint("delivery_radius_km IS NULL OR delivery_radius_km > 0", name="ck_lot_delivery_radius"),
        CheckConstraint("delivery_charge_paise IS NULL OR delivery_charge_paise >= 0", name="ck_lot_delivery_charge"),
    )


class PhotoCaptureSession(Base, IdMixin):
    __tablename__ = "photo_capture_sessions"
    produce_lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("produce_lots.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProducePhoto(Base, IdMixin):
    __tablename__ = "produce_photos"
    produce_lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("produce_lots.id", ondelete="CASCADE"), index=True)
    captured_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    file_path: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    accuracy_m: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(24), default="web_camera")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class BuyerRequirement(Base, IdMixin):
    __tablename__ = "buyer_requirements"
    buyer_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    crop: Mapped[str] = mapped_column(String(80), index=True)
    variety: Mapped[str | None] = mapped_column(String(80))
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    acceptable_quality: Mapped[str] = mapped_column(String(10))
    destination: Mapped[str] = mapped_column(String(200))
    destination_latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    destination_longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    delivery_mode: Mapped[str] = mapped_column(String(24), default="seller_delivery", index=True)
    delivery_deadline: Mapped[date] = mapped_column(Date, index=True)
    budget_price_paise: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint("quantity_kg > 0", name="ck_requirement_quantity_positive"),
        CheckConstraint("budget_price_paise IS NULL OR budget_price_paise > 0", name="ck_requirement_budget_positive"),
        CheckConstraint("delivery_mode IN ('buyer_pickup', 'seller_delivery')", name="ck_requirement_delivery_mode"),
    )


class Quotation(Base, IdMixin):
    __tablename__ = "quotations"
    requirement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buyer_requirements.id"), index=True)
    supplier_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    coordinating_fpo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    status: Mapped[str] = mapped_column(String(24), default="awaiting_buyer", index=True)
    current_revision_number: Mapped[int] = mapped_column(Integer, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("requirement_id", "supplier_organization_id", name="uq_quote_requirement_supplier"),)


class QuoteRevision(Base, IdMixin):
    __tablename__ = "quote_revisions"
    quotation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quotations.id", ondelete="CASCADE"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    actor_organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    action: Mapped[str] = mapped_column(String(20), default="offer")
    offered_quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    price_paise_per_kg: Mapped[int] = mapped_column(Integer)
    quality_grade: Mapped[str] = mapped_column(String(10))
    delivery_date: Mapped[date] = mapped_column(Date)
    delivery_terms: Mapped[str] = mapped_column(Text)
    delivery_mode: Mapped[str] = mapped_column(String(24), default="buyer_pickup")
    delivery_charge_paise: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (
        UniqueConstraint("quotation_id", "revision_number", name="uq_quote_revision_number"),
        CheckConstraint("offered_quantity_kg > 0", name="ck_quote_quantity_positive"),
        CheckConstraint("price_paise_per_kg > 0", name="ck_quote_price_positive"),
    )


class NegotiationMessage(Base, IdMixin):
    __tablename__ = "negotiation_messages"
    quotation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quotations.id", ondelete="CASCADE"), index=True)
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    author_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    client_message_id: Mapped[str] = mapped_column(String(80))
    __table_args__ = (
        UniqueConstraint("author_user_id", "client_message_id", name="uq_negotiation_message_actor_client"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 2000", name="ck_negotiation_message_body_length"),
    )


class QuoteAllocation(Base, IdMixin):
    __tablename__ = "quote_allocations"
    quote_revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quote_revisions.id", ondelete="CASCADE"), index=True)
    produce_lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("produce_lots.id"), index=True)
    farmer_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    __table_args__ = (CheckConstraint("quantity_kg > 0", name="ck_quote_allocation_positive"),)


class OrderGroup(Base, IdMixin):
    __tablename__ = "order_groups"
    requirement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buyer_requirements.id"), index=True)
    buyer_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")


class Order(Base, IdMixin):
    __tablename__ = "orders"
    order_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    order_group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("order_groups.id"), index=True)
    requirement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buyer_requirements.id"), index=True)
    quotation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quotations.id"), index=True)
    buyer_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    supplier_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    coordinating_fpo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="confirmed", index=True)
    payment_status: Mapped[str] = mapped_column(String(30), default="unpaid", index=True)
    delivery_deadline: Mapped[date] = mapped_column(Date, index=True)
    delivery_mode: Mapped[str] = mapped_column(String(24), default="buyer_pickup")
    delivery_charge_paise: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)


class OrderLine(Base, IdMixin):
    __tablename__ = "order_lines"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    produce_lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("produce_lots.id"), index=True)
    farmer_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    crop: Mapped[str] = mapped_column(String(80))
    variety: Mapped[str] = mapped_column(String(80))
    quality_grade: Mapped[str] = mapped_column(String(10))
    agreed_quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    agreed_price_paise_per_kg: Mapped[int] = mapped_column(Integer)
    delivery_terms: Mapped[str] = mapped_column(Text)
    __table_args__ = (CheckConstraint("agreed_quantity_kg > 0", name="ck_order_line_quantity_positive"),)


class StockReservation(Base, IdMixin):
    __tablename__ = "stock_reservations"
    order_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("order_lines.id"), unique=True)
    produce_lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("produce_lots.id"), index=True)
    reserved_quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    dispatched_quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    released_quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(20), default="active")


class Dispatch(Base, IdMixin):
    __tablename__ = "dispatches"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    reference: Mapped[str] = mapped_column(String(80))
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="dispatched")
    carrier_name: Mapped[str | None] = mapped_column(String(120))
    carrier_phone: Mapped[str | None] = mapped_column(String(30))


class DispatchDriverAssignment(Base, IdMixin):
    __tablename__ = "driver_dispatch_assignments"
    dispatch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dispatches.id", ondelete="CASCADE"), unique=True, index=True)
    driver_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assigned_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    vehicle_registration: Mapped[str] = mapped_column(String(40))
    tracking_mode: Mapped[str] = mapped_column(String(16), default="real")
    sharing_status: Mapped[str] = mapped_column(String(20), default="not_started", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_location_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint("tracking_mode IN ('real', 'simulated')", name="ck_driver_assignment_tracking_mode"),
        CheckConstraint("sharing_status IN ('not_started', 'sharing', 'stopped', 'arrived')", name="ck_driver_assignment_sharing_status"),
    )


class DispatchLocation(Base, IdMixin):
    __tablename__ = "dispatch_locations"
    dispatch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dispatches.id", ondelete="CASCADE"), index=True)
    driver_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    accuracy_m: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    client_update_id: Mapped[str] = mapped_column(String(80))
    __table_args__ = (
        UniqueConstraint("dispatch_id", "client_update_id", name="uq_dispatch_location_client_update"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_dispatch_location_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_dispatch_location_longitude"),
        CheckConstraint("accuracy_m > 0 AND accuracy_m <= 5000", name="ck_dispatch_location_accuracy"),
    )


class TrackingEvent(Base, IdMixin):
    __tablename__ = "tracking_events"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), index=True)
    note: Mapped[str] = mapped_column(Text, default="")


class DispatchLine(Base, IdMixin):
    __tablename__ = "dispatch_lines"
    dispatch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dispatches.id", ondelete="CASCADE"), index=True)
    order_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("order_lines.id"), index=True)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    __table_args__ = (CheckConstraint("quantity_kg > 0", name="ck_dispatch_quantity_positive"),)


class Receipt(Base, IdMixin):
    __tablename__ = "receipts"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str] = mapped_column(Text, default="")


class ReceiptLine(Base, IdMixin):
    __tablename__ = "receipt_lines"
    receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"), index=True)
    order_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("order_lines.id"), index=True)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    deduction_paise: Mapped[int] = mapped_column(Integer, default=0)
    deduction_reason: Mapped[str] = mapped_column(Text, default="")


class PaymentEvent(Base, IdMixin):
    __tablename__ = "payment_events"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    amount_paise: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(20))
    external_reference: Mapped[str] = mapped_column(String(80), unique=True)
    provider: Mapped[str] = mapped_column(String(24), default="simulation")
    provider_order_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    note: Mapped[str] = mapped_column(Text, default="Simulated payment — no real funds transferred")


class OrderComment(Base, IdMixin):
    __tablename__ = "order_comments"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)


class Notification(Base, IdMixin):
    __tablename__ = "notifications"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_key: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(255))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("user_id", "event_key", name="uq_notification_user_event"),)


class PushSubscription(Base, IdMixin):
    __tablename__ = "push_subscriptions"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationDelivery(Base, IdMixin):
    __tablename__ = "notification_deliveries"
    notification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("push_subscriptions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("notification_id", "subscription_id", name="uq_notification_delivery"),)


class OutboxJob(Base, IdMixin):
    __tablename__ = "outbox_jobs"
    event_key: Mapped[str] = mapped_column(String(160), unique=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class AuditEvent(Base, IdMixin):
    __tablename__ = "audit_events"
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Dispute(Base, IdMixin):
    __tablename__ = "disputes"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    opened_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default="other", index=True)
    affected_quantity_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    requested_resolution: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    resolution: Mapped[str | None] = mapped_column(Text)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class DisputeEvidence(Base, IdMixin):
    __tablename__ = "dispute_evidence"
    dispute_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("disputes.id", ondelete="CASCADE"), index=True)
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    file_path: Mapped[str] = mapped_column(String(255))


class OrderRating(Base, IdMixin):
    __tablename__ = "order_ratings"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    buyer_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    buyer_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    supplier_organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    reviewed_role: Mapped[str] = mapped_column(String(16), default="supplier")
    overall_rating: Mapped[int] = mapped_column(Integer)
    quality_rating: Mapped[int] = mapped_column(Integer)
    delivery_rating: Mapped[int] = mapped_column(Integer)
    communication_rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("order_id", "supplier_organization_id", name="uq_order_rating_target"),
        CheckConstraint("reviewed_role IN ('supplier', 'fpo')", name="ck_order_rating_role"),
        CheckConstraint("overall_rating BETWEEN 1 AND 5", name="ck_order_rating_overall"),
        CheckConstraint("quality_rating BETWEEN 1 AND 5", name="ck_order_rating_quality"),
        CheckConstraint("delivery_rating BETWEEN 1 AND 5", name="ck_order_rating_delivery"),
        CheckConstraint("communication_rating BETWEEN 1 AND 5", name="ck_order_rating_communication"),
        CheckConstraint("char_length(comment) <= 1000", name="ck_order_rating_comment_length"),
    )


class AssistantConversation(Base, IdMixin):
    __tablename__ = "assistant_conversations"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New conversation")
    role_context: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(5), default="en")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (
        CheckConstraint("role_context IN ('buyer', 'farmer', 'fpo_manager')", name="ck_assistant_conversation_role"),
        CheckConstraint("language IN ('en', 'te', 'hi', 'ta')", name="ck_assistant_conversation_language"),
    )


class AssistantMessage(Base, IdMixin):
    __tablename__ = "assistant_messages"
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assistant_conversations.id", ondelete="CASCADE"), index=True)
    sender_role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(24), default="user")
    model: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="completed")
    token_count: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (
        CheckConstraint("sender_role IN ('user', 'assistant')", name="ck_assistant_message_role"),
        CheckConstraint("char_length(content) BETWEEN 1 AND 5000", name="ck_assistant_message_content_length"),
    )


class IdempotencyRecord(Base, IdMixin):
    __tablename__ = "idempotency_records"
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    operation: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("actor_user_id", "operation", "idempotency_key", name="uq_idempotency_scope"),)


Index("ix_lot_match", ProduceLot.crop, ProduceLot.quality_grade, ProduceLot.status)
Index("ix_order_parties", Order.buyer_organization_id, Order.supplier_organization_id)
