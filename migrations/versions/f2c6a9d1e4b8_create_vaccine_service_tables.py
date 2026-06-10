"""create vaccine service tables

Revision ID: f2c6a9d1e4b8
Revises: e1a4f8b2c6d9
Create Date: 2026-06-10 00:00:00.000000

Serviço de vacinas pagas: catálogo, pedidos e histórico de eventos.
"""

from alembic import op
import sqlalchemy as sa


revision = 'f2c6a9d1e4b8'
down_revision = 'e1a4f8b2c6d9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'vaccine_service_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('descricao', sa.Text(), nullable=True),
        sa.Column('especies', sa.String(length=40), nullable=False),
        sa.Column('preco', sa.Numeric(10, 2), nullable=False),
        sa.Column('doses_info', sa.String(length=200), nullable=True),
        sa.Column('ativo', sa.Boolean(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vaccine_service_item_ativo', 'vaccine_service_item', ['ativo'])

    op.create_table(
        'vaccine_service_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('animal_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('item_nome', sa.String(length=120), nullable=False),
        sa.Column('valor', sa.Numeric(10, 2), nullable=False),
        sa.Column('address_street', sa.String(length=200), nullable=True),
        sa.Column('address_number', sa.String(length=20), nullable=True),
        sa.Column('address_complement', sa.String(length=100), nullable=True),
        sa.Column('address_neighborhood', sa.String(length=100), nullable=True),
        sa.Column('phone', sa.String(length=32), nullable=True),
        sa.Column('preferred_date', sa.Date(), nullable=True),
        sa.Column('preferred_shift', sa.String(length=20), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('public_token', sa.String(length=96), nullable=False),
        sa.Column('payment_id', sa.Integer(), nullable=True),
        sa.Column('assigned_vet_id', sa.Integer(), nullable=True),
        sa.Column('scheduled_date', sa.Date(), nullable=True),
        sa.Column('scheduled_shift', sa.String(length=20), nullable=True),
        sa.Column('vaccinated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('vacina_id', sa.Integer(), nullable=True),
        sa.Column('cancel_reason', sa.String(length=255), nullable=True),
        sa.Column('refund_status', sa.String(length=30), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['animal_id'], ['animal.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['vaccine_service_item.id']),
        sa.ForeignKeyConstraint(['payment_id'], ['payment.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['assigned_vet_id'], ['veterinario.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['vacina_id'], ['vacina.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('public_token'),
    )
    op.create_index('ix_vaccine_service_request_user_id', 'vaccine_service_request', ['user_id'])
    op.create_index('ix_vaccine_service_request_animal_id', 'vaccine_service_request', ['animal_id'])
    op.create_index('ix_vaccine_service_request_status', 'vaccine_service_request', ['status'])
    op.create_index('ix_vaccine_service_request_public_token', 'vaccine_service_request', ['public_token'])
    op.create_index('ix_vaccine_service_request_assigned_vet_id', 'vaccine_service_request', ['assigned_vet_id'])

    op.create_table(
        'vaccine_service_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('event', sa.String(length=40), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['request_id'], ['vaccine_service_request.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_user_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vaccine_service_event_request_id', 'vaccine_service_event', ['request_id'])


def downgrade():
    op.drop_table('vaccine_service_event')
    op.drop_table('vaccine_service_request')
    op.drop_table('vaccine_service_item')
