"""add idempotency key for delivery legs"""

from alembic import op
import sqlalchemy as sa


revision = "b7d4e1f9c2a6"
down_revision = "a4c9d7e2f6b1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("delivery_request", sa.Column("dedupe_key", sa.String(length=160), nullable=True))
    op.create_index("ix_delivery_request_dedupe_key", "delivery_request", ["dedupe_key"], unique=True)


def downgrade():
    op.drop_index("ix_delivery_request_dedupe_key", table_name="delivery_request")
    op.drop_column("delivery_request", "dedupe_key")
