"""Add delivery, camera evidence, tracking, complaints, ratings, and Razorpay fields."""

import sqlalchemy as sa
from alembic import op


revision = "20260910_0003"
down_revision = "20260910_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("produce_lots", sa.Column("delivery_mode", sa.String(24), nullable=False, server_default="buyer_pickup"))
    op.add_column("produce_lots", sa.Column("delivery_service_location", sa.String(200)))
    op.add_column("produce_lots", sa.Column("delivery_radius_km", sa.Numeric(8, 2)))
    op.add_column("produce_lots", sa.Column("delivery_charge_paise", sa.Integer()))
    op.create_index("ix_produce_lots_delivery_mode", "produce_lots", ["delivery_mode"])
    op.create_check_constraint("ck_lot_delivery_mode", "produce_lots", "delivery_mode IN ('buyer_pickup', 'seller_delivery')")
    op.create_check_constraint("ck_lot_delivery_radius", "produce_lots", "delivery_radius_km IS NULL OR delivery_radius_km > 0")
    op.create_check_constraint("ck_lot_delivery_charge", "produce_lots", "delivery_charge_paise IS NULL OR delivery_charge_paise >= 0")

    op.add_column("buyer_requirements", sa.Column("destination_latitude", sa.Numeric(9, 6)))
    op.add_column("buyer_requirements", sa.Column("destination_longitude", sa.Numeric(9, 6)))
    op.add_column("buyer_requirements", sa.Column("delivery_mode", sa.String(24), nullable=False, server_default="seller_delivery"))
    op.create_index("ix_buyer_requirements_delivery_mode", "buyer_requirements", ["delivery_mode"])
    op.create_check_constraint("ck_requirement_delivery_mode", "buyer_requirements", "delivery_mode IN ('buyer_pickup', 'seller_delivery')")

    op.add_column("quote_revisions", sa.Column("delivery_mode", sa.String(24), nullable=False, server_default="buyer_pickup"))
    op.add_column("quote_revisions", sa.Column("delivery_charge_paise", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("orders", sa.Column("delivery_mode", sa.String(24), nullable=False, server_default="buyer_pickup"))
    op.add_column("orders", sa.Column("delivery_charge_paise", sa.Integer(), nullable=False, server_default="0"))

    op.add_column("dispatches", sa.Column("carrier_name", sa.String(120)))
    op.add_column("dispatches", sa.Column("carrier_phone", sa.String(30)))
    op.create_table(
        "tracking_events",
        sa.Column("order_id", sa.Uuid(), nullable=False), sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tracking_events_order_id", "tracking_events", ["order_id"])
    op.create_index("ix_tracking_events_status", "tracking_events", ["status"])

    op.create_table(
        "photo_capture_sessions",
        sa.Column("produce_lot_id", sa.Uuid(), nullable=False), sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)), sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["produce_lot_id"], ["produce_lots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_photo_capture_sessions_produce_lot_id", "photo_capture_sessions", ["produce_lot_id"])
    op.create_index("ix_photo_capture_sessions_user_id", "photo_capture_sessions", ["user_id"])
    op.create_index("ix_photo_capture_sessions_token_hash", "photo_capture_sessions", ["token_hash"], unique=True)
    op.create_index("ix_photo_capture_sessions_expires_at", "photo_capture_sessions", ["expires_at"])
    op.create_table(
        "produce_photos",
        sa.Column("produce_lot_id", sa.Uuid(), nullable=False), sa.Column("captured_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.String(255), nullable=False), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False), sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("accuracy_m", sa.Numeric(10, 2), nullable=False), sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(24), nullable=False, server_default="web_camera"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["produce_lot_id"], ["produce_lots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["captured_by_user_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_produce_photos_produce_lot_id", "produce_photos", ["produce_lot_id"])
    op.create_index("ix_produce_photos_captured_by_user_id", "produce_photos", ["captured_by_user_id"])
    op.create_index("ix_produce_photos_sha256", "produce_photos", ["sha256"])
    op.create_index("ix_produce_photos_is_current", "produce_photos", ["is_current"])

    op.add_column("payment_events", sa.Column("provider", sa.String(24), nullable=False, server_default="simulation"))
    op.add_column("payment_events", sa.Column("provider_order_id", sa.String(100), unique=True))
    op.add_column("payment_events", sa.Column("provider_payment_id", sa.String(100), unique=True))
    op.add_column("payment_events", sa.Column("provider_event_id", sa.String(100), unique=True))

    op.add_column("disputes", sa.Column("category", sa.String(30), nullable=False, server_default="other"))
    op.add_column("disputes", sa.Column("affected_quantity_kg", sa.Numeric(12, 3)))
    op.add_column("disputes", sa.Column("requested_resolution", sa.Text(), nullable=False, server_default=""))
    op.create_index("ix_disputes_category", "disputes", ["category"])
    op.create_table(
        "dispute_evidence",
        sa.Column("dispute_id", sa.Uuid(), nullable=False), sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.String(255), nullable=False), sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dispute_id"], ["disputes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dispute_evidence_dispute_id", "dispute_evidence", ["dispute_id"])
    op.create_table(
        "order_ratings",
        sa.Column("order_id", sa.Uuid(), nullable=False, unique=True), sa.Column("buyer_user_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_organization_id", sa.Uuid(), nullable=False), sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""), sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("score BETWEEN 1 AND 5", name="ck_order_rating_score"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["buyer_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["supplier_organization_id"], ["organizations.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_ratings_supplier_organization_id", "order_ratings", ["supplier_organization_id"])


def downgrade():
    op.drop_table("order_ratings")
    op.drop_table("dispute_evidence")
    op.drop_index("ix_disputes_category", table_name="disputes")
    op.drop_column("disputes", "requested_resolution"); op.drop_column("disputes", "affected_quantity_kg"); op.drop_column("disputes", "category")
    for name in ("provider_event_id", "provider_payment_id", "provider_order_id", "provider"):
        op.drop_column("payment_events", name)
    op.drop_table("produce_photos"); op.drop_table("photo_capture_sessions"); op.drop_table("tracking_events")
    op.drop_column("dispatches", "carrier_phone"); op.drop_column("dispatches", "carrier_name")
    op.drop_column("orders", "delivery_charge_paise"); op.drop_column("orders", "delivery_mode")
    op.drop_column("quote_revisions", "delivery_charge_paise"); op.drop_column("quote_revisions", "delivery_mode")
    op.drop_constraint("ck_requirement_delivery_mode", "buyer_requirements", type_="check")
    op.drop_index("ix_buyer_requirements_delivery_mode", table_name="buyer_requirements")
    op.drop_column("buyer_requirements", "delivery_mode"); op.drop_column("buyer_requirements", "destination_longitude"); op.drop_column("buyer_requirements", "destination_latitude")
    op.drop_constraint("ck_lot_delivery_charge", "produce_lots", type_="check")
    op.drop_constraint("ck_lot_delivery_radius", "produce_lots", type_="check")
    op.drop_constraint("ck_lot_delivery_mode", "produce_lots", type_="check")
    op.drop_index("ix_produce_lots_delivery_mode", table_name="produce_lots")
    op.drop_column("produce_lots", "delivery_charge_paise"); op.drop_column("produce_lots", "delivery_radius_km"); op.drop_column("produce_lots", "delivery_service_location"); op.drop_column("produce_lots", "delivery_mode")
