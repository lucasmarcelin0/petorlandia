"""add consulta authorization fields

Revision ID: a3f7a1c72891
Revises: f51ee31de1dd
Create Date: 2025-11-15 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f7a1c72891'
down_revision = 'f51ee31de1dd'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('consulta', sa.Column('authorization_status', sa.String(length=20), nullable=True))
    op.add_column('consulta', sa.Column('authorization_reference', sa.String(length=80), nullable=True))
    op.add_column('consulta', sa.Column('authorization_checked_at', sa.DateTime(), nullable=True))
    op.add_column('consulta', sa.Column('authorization_notes', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('consulta', 'authorization_notes')
    op.drop_column('consulta', 'authorization_checked_at')
    op.drop_column('consulta', 'authorization_reference')
    op.drop_column('consulta', 'authorization_status')
