"""add vaccine provider and payout

Revision ID: b6e2a8c4d9f1
Revises: a7d4e2c9f1b6
Create Date: 2026-06-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'b6e2a8c4d9f1'
down_revision = 'a7d4e2c9f1b6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('vaccine_service_item', sa.Column('fabricante', sa.String(length=120), nullable=True))
    op.add_column('vaccine_service_item', sa.Column('valor_repasse', sa.Numeric(10, 2), nullable=True))
    op.add_column('vaccine_service_item', sa.Column('provider_vet_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_vaccine_service_item_provider_vet',
        'vaccine_service_item',
        'veterinario',
        ['provider_vet_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_vaccine_service_item_provider_vet_id'),
        'vaccine_service_item',
        ['provider_vet_id'],
        unique=False,
    )
    op.add_column('vaccine_service_request', sa.Column('fabricante', sa.String(length=120), nullable=True))
    op.add_column('vaccine_service_request', sa.Column('valor_repasse', sa.Numeric(10, 2), nullable=True))


def downgrade():
    op.drop_column('vaccine_service_request', 'valor_repasse')
    op.drop_column('vaccine_service_request', 'fabricante')
    op.drop_index(op.f('ix_vaccine_service_item_provider_vet_id'), table_name='vaccine_service_item')
    op.drop_constraint('fk_vaccine_service_item_provider_vet', 'vaccine_service_item', type_='foreignkey')
    op.drop_column('vaccine_service_item', 'provider_vet_id')
    op.drop_column('vaccine_service_item', 'valor_repasse')
    op.drop_column('vaccine_service_item', 'fabricante')
