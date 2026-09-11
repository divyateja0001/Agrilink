"""Add structured reviews, browser push, and assistant conversations."""

import sqlalchemy as sa
from alembic import op


revision = "20260911_0004"
down_revision = "20260910_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("order_ratings_order_id_key", "order_ratings", type_="unique")
    op.alter_column("order_ratings", "score", new_column_name="overall_rating")
    op.add_column("order_ratings", sa.Column("buyer_organization_id", sa.Uuid(), nullable=True))
    op.add_column("order_ratings", sa.Column("reviewed_role", sa.String(16), nullable=False, server_default="supplier"))
    op.add_column("order_ratings", sa.Column("quality_rating", sa.Integer(), nullable=True))
    op.add_column("order_ratings", sa.Column("delivery_rating", sa.Integer(), nullable=True))
    op.add_column("order_ratings", sa.Column("communication_rating", sa.Integer(), nullable=True))
    op.add_column("order_ratings", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.execute(sa.text(
        "UPDATE order_ratings AS r SET buyer_organization_id=o.buyer_organization_id, "
        "quality_rating=r.overall_rating, delivery_rating=r.overall_rating, communication_rating=r.overall_rating "
        "FROM orders AS o WHERE o.id=r.order_id"
    ))
    op.alter_column("order_ratings", "buyer_organization_id", nullable=False)
    op.alter_column("order_ratings", "quality_rating", nullable=False)
    op.alter_column("order_ratings", "delivery_rating", nullable=False)
    op.alter_column("order_ratings", "communication_rating", nullable=False)
    op.drop_constraint("ck_order_rating_score", "order_ratings", type_="check")
    op.create_foreign_key("fk_order_ratings_buyer_organization", "order_ratings", "organizations", ["buyer_organization_id"], ["id"])
    op.create_index("ix_order_ratings_buyer_organization_id", "order_ratings", ["buyer_organization_id"])
    op.create_index("ix_order_ratings_order_id", "order_ratings", ["order_id"])
    op.create_unique_constraint("uq_order_rating_target", "order_ratings", ["order_id", "supplier_organization_id"])
    op.create_check_constraint("ck_order_rating_role", "order_ratings", "reviewed_role IN ('supplier', 'fpo')")
    for suffix, column in (("overall", "overall_rating"), ("quality", "quality_rating"), ("delivery", "delivery_rating"), ("communication", "communication_rating")):
        op.create_check_constraint(f"ck_order_rating_{suffix}", "order_ratings", f"{column} BETWEEN 1 AND 5")
    op.create_check_constraint("ck_order_rating_comment_length", "order_ratings", "char_length(comment) <= 1000")

    op.create_table(
        "push_subscriptions",
        sa.Column("user_id", sa.Uuid(), nullable=False), sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False), sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.String(300), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_success_at", sa.DateTime(timezone=True)), sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("endpoint"),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
    op.create_index("ix_push_subscriptions_is_active", "push_subscriptions", ["is_active"])

    op.create_table(
        "notification_deliveries",
        sa.Column("notification_id", sa.Uuid(), nullable=False), sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_error", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)), sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subscription_id"], ["push_subscriptions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("notification_id", "subscription_id", name="uq_notification_delivery"),
    )
    for column in ("notification_id", "subscription_id", "status", "available_at"):
        op.create_index(f"ix_notification_deliveries_{column}", "notification_deliveries", [column])

    op.create_table(
        "assistant_conversations",
        sa.Column("user_id", sa.Uuid(), nullable=False), sa.Column("title", sa.String(120), nullable=False, server_default="New conversation"),
        sa.Column("role_context", sa.String(20), nullable=False), sa.Column("language", sa.String(5), nullable=False, server_default="en"),
        sa.Column("archived_at", sa.DateTime(timezone=True)), sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role_context IN ('buyer', 'farmer', 'fpo_manager')", name="ck_assistant_conversation_role"),
        sa.CheckConstraint("language IN ('en', 'te', 'hi', 'ta')", name="ck_assistant_conversation_language"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assistant_conversations_user_id", "assistant_conversations", ["user_id"])
    op.create_index("ix_assistant_conversations_archived_at", "assistant_conversations", ["archived_at"])

    op.create_table(
        "assistant_messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False), sa.Column("sender_role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False), sa.Column("source", sa.String(24), nullable=False, server_default="user"),
        sa.Column("model", sa.String(80)), sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("token_count", sa.Integer()), sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sender_role IN ('user', 'assistant')", name="ck_assistant_message_role"),
        sa.CheckConstraint("char_length(content) BETWEEN 1 AND 5000", name="ck_assistant_message_content_length"),
        sa.ForeignKeyConstraint(["conversation_id"], ["assistant_conversations.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assistant_messages_conversation_id", "assistant_messages", ["conversation_id"])


def downgrade():
    op.drop_table("assistant_messages")
    op.drop_table("assistant_conversations")
    op.drop_table("notification_deliveries")
    op.drop_table("push_subscriptions")
    for name in ("ck_order_rating_comment_length", "ck_order_rating_communication", "ck_order_rating_delivery", "ck_order_rating_quality", "ck_order_rating_overall", "ck_order_rating_role"):
        op.drop_constraint(name, "order_ratings", type_="check")
    op.drop_constraint("uq_order_rating_target", "order_ratings", type_="unique")
    op.drop_index("ix_order_ratings_order_id", table_name="order_ratings")
    op.drop_index("ix_order_ratings_buyer_organization_id", table_name="order_ratings")
    op.drop_constraint("fk_order_ratings_buyer_organization", "order_ratings", type_="foreignkey")
    op.drop_column("order_ratings", "version")
    op.drop_column("order_ratings", "communication_rating")
    op.drop_column("order_ratings", "delivery_rating")
    op.drop_column("order_ratings", "quality_rating")
    op.drop_column("order_ratings", "reviewed_role")
    op.drop_column("order_ratings", "buyer_organization_id")
    op.alter_column("order_ratings", "overall_rating", new_column_name="score")
    op.create_check_constraint("ck_order_rating_score", "order_ratings", "score BETWEEN 1 AND 5")
    op.create_unique_constraint("order_ratings_order_id_key", "order_ratings", ["order_id"])
