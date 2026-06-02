"""add exam_name to exam_appointment

Revision ID: d4f7a9c2e6b1
Revises: c2e5a7b9d3f1
Create Date: 2026-06-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'd4f7a9c2e6b1'
down_revision = 'c2e5a7b9d3f1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('exam_appointment', sa.Column('exam_name', sa.String(length=120), nullable=True))


def downgrade():
    op.drop_column('exam_appointment', 'exam_name')
