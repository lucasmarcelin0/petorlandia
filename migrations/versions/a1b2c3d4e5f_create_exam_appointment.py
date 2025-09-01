"""create exam appointment table

Revision ID: a1b2c3d4e5f
Revises: ee1a3963c0ed
Create Date: 2025-09-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f'
down_revision = 'ee1a3963c0ed'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'exam_appointment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('animal_id', sa.Integer(), nullable=False),
        sa.Column('specialist_id', sa.Integer(), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('request_time', sa.DateTime(), nullable=True),
        sa.Column('confirm_by', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['animal_id'], ['animal.id']),
        sa.ForeignKeyConstraint(['specialist_id'], ['veterinario.id']),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade():
    op.drop_table('exam_appointment')
