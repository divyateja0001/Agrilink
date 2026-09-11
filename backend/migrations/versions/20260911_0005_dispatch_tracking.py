"""Add per-dispatch driver vehicle tracking."""

import sqlalchemy as sa
from alembic import op


revision = "20260911_0005"
down_revision = "20260911_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "driver_dispatch_assignments",
        sa.Column("dispatch_id", sa.Uuid(), nullable=False),
        sa.Column("driver_user_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("vehicle_registration", sa.String(40), nullable=False),
        sa.Column("tracking_mode", sa.String(16), nullable=False, server_default="real"),
        sa.Column("sharing_status", sa.String(20), nullable=False, server_default="not_started"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.Column("arrived_at", sa.DateTime(timezone=True)),
        sa.Column("last_location_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("tracking_mode IN ('real', 'simulated')", name="ck_driver_assignment_tracking_mode"),
        sa.CheckConstraint("sharing_status IN ('not_started', 'sharing', 'stopped', 'arrived')", name="ck_driver_assignment_sharing_status"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["dispatch_id"], ["dispatches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["driver_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dispatch_id"),
    )
    op.create_index("ix_driver_dispatch_assignments_dispatch_id", "driver_dispatch_assignments", ["dispatch_id"])
    op.create_index("ix_driver_dispatch_assignments_driver_user_id", "driver_dispatch_assignments", ["driver_user_id"])
    op.create_index("ix_driver_dispatch_assignments_sharing_status", "driver_dispatch_assignments", ["sharing_status"])
    op.create_index("ix_driver_dispatch_assignments_is_active", "driver_dispatch_assignments", ["is_active"])

    op.create_table(
        "dispatch_locations",
        sa.Column("dispatch_id", sa.Uuid(), nullable=False),
        sa.Column("driver_user_id", sa.Uuid(), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("accuracy_m", sa.Numeric(10, 2), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("client_update_id", sa.String(80), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("accuracy_m > 0 AND accuracy_m <= 5000", name="ck_dispatch_location_accuracy"),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_dispatch_location_latitude"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_dispatch_location_longitude"),
        sa.ForeignKeyConstraint(["dispatch_id"], ["dispatches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["driver_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dispatch_id", "client_update_id", name="uq_dispatch_location_client_update"),
    )
    for column in ("dispatch_id", "driver_user_id", "captured_at"):
        op.create_index(f"ix_dispatch_locations_{column}", "dispatch_locations", [column])


def downgrade():
    op.drop_table("dispatch_locations")
    op.drop_table("driver_dispatch_assignments")
