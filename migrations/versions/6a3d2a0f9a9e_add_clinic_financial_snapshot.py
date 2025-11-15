"""create clinic financial snapshot table

Revision ID: 6a3d2a0f9a9e
Revises: 1a9f4e4c5b2c
Create Date: 2025-05-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '6a3d2a0f9a9e'
down_revision = '1a9f4e4c5b2c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'clinic_financial_snapshot',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=False),
        sa.Column('month', sa.Date(), nullable=False),
        sa.Column('total_receitas_servicos', sa.Numeric(14, 2), nullable=False),
        sa.Column('total_receitas_produtos', sa.Numeric(14, 2), nullable=False),
        sa.Column('total_receitas_gerais', sa.Numeric(14, 2), nullable=False),
        sa.Column('gerado_em', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinica.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('clinic_id', 'month', name='uq_snapshot_clinic_month')
    )
    op.create_index('ix_clinic_financial_snapshot_clinic_id', 'clinic_financial_snapshot', ['clinic_id'])
    op.create_index('ix_clinic_financial_snapshot_month', 'clinic_financial_snapshot', ['month'])


def downgrade():
    op.drop_index('ix_clinic_financial_snapshot_month', table_name='clinic_financial_snapshot')
    op.drop_index('ix_clinic_financial_snapshot_clinic_id', table_name='clinic_financial_snapshot')
    op.drop_table('clinic_financial_snapshot')
