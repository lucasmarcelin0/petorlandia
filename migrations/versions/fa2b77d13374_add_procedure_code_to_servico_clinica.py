"""add procedure code to servico_clinica

Revision ID: fa2b77d13374
Revises: bbe7d8ed2f6f
Create Date: 2025-11-15 00:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fa2b77d13374'
down_revision = 'bbe7d8ed2f6f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('servico_clinica', sa.Column('procedure_code', sa.String(length=64), nullable=True))


def downgrade():
    op.drop_column('servico_clinica', 'procedure_code')
