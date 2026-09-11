"""Initial AgriLink marketplace schema."""
from alembic import op

from app.db import Base
from app import models  # noqa: F401

revision = "20260910_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)

