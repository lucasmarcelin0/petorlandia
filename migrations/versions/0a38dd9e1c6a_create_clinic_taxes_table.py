"""create clinic taxes table"""

from alembic import op
import sqlalchemy as sa

revision = '0a38dd9e1c6a'
down_revision = 'fe3b6f9d7e2d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'clinic_taxes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=False),
        sa.Column('month', sa.Date(), nullable=False),
        sa.Column('iss_total', sa.Numeric(14, 2), nullable=False, server_default='0.00'),
        sa.Column('das_total', sa.Numeric(14, 2), nullable=False, server_default='0.00'),
        sa.Column('retencoes_pj', sa.Numeric(14, 2), nullable=False, server_default='0.00'),
        sa.Column('fator_r', sa.Numeric(6, 4), nullable=False, server_default='0.0000'),
        sa.Column('faixa_simples', sa.Integer(), nullable=True),
        sa.Column('projecao_anual', sa.Numeric(14, 2), nullable=False, server_default='0.00'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinica.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('clinic_id', 'month', name='uq_clinic_taxes_clinic_month'),
    )
    op.create_index('ix_clinic_taxes_clinic_id', 'clinic_taxes', ['clinic_id'])
    op.create_index('ix_clinic_taxes_month', 'clinic_taxes', ['month'])


def downgrade():
    op.drop_index('ix_clinic_taxes_month', table_name='clinic_taxes')
    op.drop_index('ix_clinic_taxes_clinic_id', table_name='clinic_taxes')
    op.drop_table('clinic_taxes')
