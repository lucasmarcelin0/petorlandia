"""add vaccine request items

Revision ID: d4b7c1e9a2f6
Revises: c9f4a2d7e6b1
Create Date: 2026-06-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'd4b7c1e9a2f6'
down_revision = 'c9f4a2d7e6b1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'vaccine_service_request_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('fabricante', sa.String(length=120), nullable=True),
        sa.Column('valor', sa.Numeric(10, 2), nullable=False),
        sa.Column('valor_repasse', sa.Numeric(10, 2), nullable=True),
        sa.Column('vacina_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['item_id'],
            ['vaccine_service_item.id'],
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['request_id'],
            ['vaccine_service_request.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['vacina_id'],
            ['vacina.id'],
            ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_vaccine_service_request_item_request_id'),
        'vaccine_service_request_item',
        ['request_id'],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO vaccine_service_request_item
            (request_id, item_id, nome, fabricante, valor, valor_repasse, vacina_id, created_at)
        SELECT
            id, item_id, item_nome, fabricante, valor, valor_repasse, vacina_id, created_at
        FROM vaccine_service_request
        """
    )


def downgrade():
    op.drop_index(
        op.f('ix_vaccine_service_request_item_request_id'),
        table_name='vaccine_service_request_item',
    )
    op.drop_table('vaccine_service_request_item')
