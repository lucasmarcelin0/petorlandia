"""add health fields to consulta

Revision ID: f51ee31de1dd
Revises: 7de8c7e1dd0d, e1b9a8e9d0f1
Create Date: 2025-11-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f51ee31de1dd'
down_revision = ('7de8c7e1dd0d', 'e1b9a8e9d0f1')
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('consulta', sa.Column('health_plan_id', sa.Integer(), nullable=True))
    op.add_column('consulta', sa.Column('health_subscription_id', sa.Integer(), nullable=True))

    op.create_foreign_key(
        'fk_consulta_health_plan_id',
        'consulta',
        'health_plan',
        ['health_plan_id'],
        ['id'],
    )
    op.create_foreign_key(
        'fk_consulta_health_subscription_id',
        'consulta',
        'health_subscription',
        ['health_subscription_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('fk_consulta_health_subscription_id', 'consulta', type_='foreignkey')
    op.drop_constraint('fk_consulta_health_plan_id', 'consulta', type_='foreignkey')

    op.drop_column('consulta', 'health_subscription_id')
    op.drop_column('consulta', 'health_plan_id')
