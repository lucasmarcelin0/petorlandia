"""add pmo evaluation dimensions

Revision ID: c5d9a1e7f3b4
Revises: b9e3f5a2c7d8
Create Date: 2026-05-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'c5d9a1e7f3b4'
down_revision = 'b9e3f5a2c7d8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pmo_vaccination_visit', schema=None) as batch_op:
        batch_op.add_column(sa.Column('evaluation_registration_rating', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('evaluation_service_rating', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('evaluation_information_rating', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('evaluation_survey_rating', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('pmo_vaccination_visit', schema=None) as batch_op:
        batch_op.drop_column('evaluation_survey_rating')
        batch_op.drop_column('evaluation_information_rating')
        batch_op.drop_column('evaluation_service_rating')
        batch_op.drop_column('evaluation_registration_rating')
