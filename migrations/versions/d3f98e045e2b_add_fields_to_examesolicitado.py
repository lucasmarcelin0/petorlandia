"""add fields to ExameSolicitado

Revision ID: d3f98e045e2b
Revises: a1b2c3d4e5f
Create Date: 2025-09-02 18:14:19.378128

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3f98e045e2b'
down_revision = 'a1b2c3d4e5f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('exame_solicitado', sa.Column('status', sa.String(length=20), nullable=True, server_default='pendente'))
    op.add_column('exame_solicitado', sa.Column('resultado', sa.Text(), nullable=True))
    op.add_column('exame_solicitado', sa.Column('performed_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('exame_solicitado', 'performed_at')
    op.drop_column('exame_solicitado', 'resultado')
    op.drop_column('exame_solicitado', 'status')
