"""add payer type to orcamento item

Revision ID: f21e5b0a9d42
Revises: d2f5b90edc2e
Create Date: 2024-05-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f21e5b0a9d42'
down_revision = 'd2f5b90edc2e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orcamento_item', sa.Column('payer_type', sa.String(length=20), nullable=False, server_default='particular'))
    op.execute("""
        UPDATE orcamento_item AS oi
        SET payer_type = 'plan'
        FROM consulta AS c
        WHERE c.id = oi.consulta_id AND c.health_subscription_id IS NOT NULL
    """)
    op.alter_column('orcamento_item', 'payer_type', server_default=None)


def downgrade():
    op.drop_column('orcamento_item', 'payer_type')
