"""add pmo_vaccination_day_stock

Correções manuais do controle de frascos por dia de campanha. Tudo nulável de
propósito: nulo = "calcule automaticamente", zero = afirmação do vacinador.

Revision ID: a7d1c3e9f240
Revises: d4b7a2c91e60
Create Date: 2026-09-02

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7d1c3e9f240'
down_revision = 'd4b7a2c91e60'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'pmo_vaccination_day_stock' in inspector.get_table_names():
        return

    op.create_table(
        'pmo_vaccination_day_stock',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('spreadsheet_id', sa.String(length=128), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('leftover_start', sa.Integer(), nullable=True),
        sa.Column('leftover_opened_on', sa.Date(), nullable=True),
        sa.Column('vials_opened', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['updated_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'spreadsheet_id', 'day', name='uq_pmo_vaccination_day_stock_day'
        ),
    )
    op.create_index(
        op.f('ix_pmo_vaccination_day_stock_spreadsheet_id'),
        'pmo_vaccination_day_stock',
        ['spreadsheet_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_pmo_vaccination_day_stock_day'),
        'pmo_vaccination_day_stock',
        ['day'],
        unique=False,
    )
    op.create_index(
        op.f('ix_pmo_vaccination_day_stock_updated_by_id'),
        'pmo_vaccination_day_stock',
        ['updated_by_id'],
        unique=False,
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'pmo_vaccination_day_stock' not in inspector.get_table_names():
        return
    op.drop_index(
        op.f('ix_pmo_vaccination_day_stock_updated_by_id'),
        table_name='pmo_vaccination_day_stock',
    )
    op.drop_index(
        op.f('ix_pmo_vaccination_day_stock_day'), table_name='pmo_vaccination_day_stock'
    )
    op.drop_index(
        op.f('ix_pmo_vaccination_day_stock_spreadsheet_id'),
        table_name='pmo_vaccination_day_stock',
    )
    op.drop_table('pmo_vaccination_day_stock')
