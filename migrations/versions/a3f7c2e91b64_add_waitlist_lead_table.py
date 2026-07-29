"""Add waitlist_lead table

Revision ID: a3f7c2e91b64
Revises: d1e5f9a4c7b2
Create Date: 2026-07-29 08:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f7c2e91b64'
down_revision = 'd1e5f9a4c7b2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'waitlist_lead',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('feature', sa.String(length=60), nullable=False),
        sa.Column('contact', sa.String(length=180), nullable=False),
        sa.Column('city', sa.String(length=120), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('feature', 'contact', name='uq_waitlist_feature_contact'),
    )
    op.create_index(
        op.f('ix_waitlist_lead_feature'), 'waitlist_lead', ['feature'], unique=False
    )


def downgrade():
    op.drop_index(op.f('ix_waitlist_lead_feature'), table_name='waitlist_lead')
    op.drop_table('waitlist_lead')
