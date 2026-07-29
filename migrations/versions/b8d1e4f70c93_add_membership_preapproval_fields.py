"""Add preapproval fields to veterinarian_membership

Revision ID: b8d1e4f70c93
Revises: a3f7c2e91b64
Create Date: 2026-07-29 10:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8d1e4f70c93'
down_revision = 'a3f7c2e91b64'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'veterinarian_membership',
        sa.Column('preapproval_id', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'veterinarian_membership',
        sa.Column('payment_method_set_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column('veterinarian_membership', 'payment_method_set_at')
    op.drop_column('veterinarian_membership', 'preapproval_id')
