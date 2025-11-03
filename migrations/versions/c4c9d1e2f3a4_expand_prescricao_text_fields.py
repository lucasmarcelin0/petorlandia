"""expand prescricao text fields

Revision ID: c4c9d1e2f3a4
Revises: 9a8b7c6d5e4f
Create Date: 2024-06-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4c9d1e2f3a4'
down_revision = '9a8b7c6d5e4f'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'prescricao',
        'dosagem',
        existing_type=sa.String(length=100),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'prescricao',
        'frequencia',
        existing_type=sa.String(length=100),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'prescricao',
        'duracao',
        existing_type=sa.String(length=100),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade():
    op.alter_column(
        'prescricao',
        'duracao',
        existing_type=sa.Text(),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
    op.alter_column(
        'prescricao',
        'frequencia',
        existing_type=sa.Text(),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
    op.alter_column(
        'prescricao',
        'dosagem',
        existing_type=sa.Text(),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
