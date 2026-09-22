"""SFA: cadastros base unificados e reconciliacao de schema.

Revision ID: 8d9c2e1f4a5b
Revises: d3a7c4e1f300
"""
from alembic import op
import sqlalchemy as sa


revision = '8d9c2e1f4a5b'
down_revision = 'd3a7c4e1f300'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    # Garantir a coluna ativo com idempotencia caso sfa_locais exista no banco
    if 'sfa_locais' in tables:
        columns = [c['name'] for c in insp.get_columns('sfa_locais')]
        if 'ativo' not in columns:
            op.add_column('sfa_locais', sa.Column('ativo', sa.Boolean(), server_default='true', nullable=False))


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'sfa_locais' in insp.get_table_names():
        columns = [c['name'] for c in insp.get_columns('sfa_locais')]
        if 'ativo' in columns:
            op.drop_column('sfa_locais', 'ativo')
