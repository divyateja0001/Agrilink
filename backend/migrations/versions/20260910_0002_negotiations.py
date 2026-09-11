"""Add structured quote negotiations and participant messages."""

import sqlalchemy as sa
from alembic import op


revision = "20260910_0002"
down_revision = "20260910_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("quotations", "status", type_=sa.String(length=24), existing_type=sa.String(length=20))
    op.add_column("quote_revisions", sa.Column("actor_organization_id", sa.Uuid(), nullable=True))
    op.add_column("quote_revisions", sa.Column("action", sa.String(length=20), nullable=False, server_default="offer"))
    op.create_foreign_key(
        "fk_quote_revision_actor_org",
        "quote_revisions",
        "organizations",
        ["actor_organization_id"],
        ["id"],
    )
    op.create_index("ix_quote_revisions_actor_organization_id", "quote_revisions", ["actor_organization_id"])

    op.execute(
        """
        UPDATE quote_revisions AS revision
        SET actor_organization_id = quotation.supplier_organization_id
        FROM quotations AS quotation
        WHERE revision.quotation_id = quotation.id
          AND revision.actor_organization_id IS NULL
        """
    )
    op.execute("UPDATE quotations SET status = 'awaiting_buyer' WHERE status IN ('submitted', 'countered')")

    op.create_table(
        "negotiation_messages",
        sa.Column("quotation_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("author_organization_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("client_message_id", sa.String(length=80), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("char_length(body) BETWEEN 1 AND 2000", name="ck_negotiation_message_body_length"),
        sa.ForeignKeyConstraint(["author_organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["quotation_id"], ["quotations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("author_user_id", "client_message_id", name="uq_negotiation_message_actor_client"),
    )
    op.create_index("ix_negotiation_messages_quotation_id", "negotiation_messages", ["quotation_id"])
    op.create_index("ix_negotiation_messages_author_organization_id", "negotiation_messages", ["author_organization_id"])


def downgrade():
    op.drop_index("ix_negotiation_messages_author_organization_id", table_name="negotiation_messages")
    op.drop_index("ix_negotiation_messages_quotation_id", table_name="negotiation_messages")
    op.drop_table("negotiation_messages")
    op.drop_index("ix_quote_revisions_actor_organization_id", table_name="quote_revisions")
    op.drop_constraint("fk_quote_revision_actor_org", "quote_revisions", type_="foreignkey")
    op.drop_column("quote_revisions", "action")
    op.drop_column("quote_revisions", "actor_organization_id")
    op.execute("UPDATE quotations SET status = 'submitted' WHERE status IN ('awaiting_buyer', 'awaiting_supplier', 'agreed')")
    op.alter_column("quotations", "status", type_=sa.String(length=20), existing_type=sa.String(length=24))
