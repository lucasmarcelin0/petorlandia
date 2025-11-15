"""add clinic notifications table

Revision ID: b9958a1f97c7
Revises: 6a3d2a0f9a9e
Create Date: 2025-05-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b9958a1f97c7'
down_revision = '6a3d2a0f9a9e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'clinic_notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('type', sa.String(length=20), nullable=False, server_default='info'),
        sa.Column('month', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('resolved', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('resolution_date', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinica.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        'ix_clinic_notifications_clinic_id',
        'clinic_notifications',
        ['clinic_id'],
    )
    op.create_index(
        'ix_clinic_notifications_month',
        'clinic_notifications',
        ['month'],
    )
    op.create_index(
        'ix_clinic_notifications_resolved',
        'clinic_notifications',
        ['resolved'],
    )


def downgrade():
    op.drop_index('ix_clinic_notifications_resolved', table_name='clinic_notifications')
    op.drop_index('ix_clinic_notifications_month', table_name='clinic_notifications')
    op.drop_index('ix_clinic_notifications_clinic_id', table_name='clinic_notifications')
    op.drop_table('clinic_notifications')
