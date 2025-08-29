"""create clinic_staff table

Revision ID: 9d3d3cdb1de4
Revises: 2b3b6d9f4c1a
Create Date: 2025-08-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9d3d3cdb1de4'
down_revision = '2b3b6d9f4c1a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'clinic_staff',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('clinic_id', sa.Integer(), sa.ForeignKey('clinica.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('can_manage_clients', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('can_manage_animals', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('can_manage_staff', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('can_manage_schedule', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('can_manage_inventory', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade():
    op.drop_table('clinic_staff')
