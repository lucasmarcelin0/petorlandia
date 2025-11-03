"""expand medicamento field length

Revision ID: 3b4c5d6e7f80
Revises: 9b42c9abf8bc
Create Date: 2025-11-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3b4c5d6e7f80'
down_revision = '9b42c9abf8bc'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'prescricao',
        'medicamento',
        existing_type=sa.String(length=100),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        'prescricao',
        'medicamento',
        existing_type=sa.Text(),
        type_=sa.String(length=100),
        existing_nullable=False,
    )
