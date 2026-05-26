"""add pmo public links and feedback

Revision ID: f4a8c2e7b9d1
Revises: e3f6a8b2c9d4
Create Date: 2026-05-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'f4a8c2e7b9d1'
down_revision = 'e3f6a8b2c9d4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pmo_vaccination_visit', schema=None) as batch_op:
        batch_op.add_column(sa.Column('public_token', sa.String(length=96), nullable=True))
        batch_op.add_column(sa.Column('tutor_user_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('evaluation_rating', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('evaluation_comment', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f('ix_pmo_vaccination_visit_public_token'), ['public_token'], unique=True)
        batch_op.create_index(batch_op.f('ix_pmo_vaccination_visit_tutor_user_id'), ['tutor_user_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_pmo_vaccination_visit_tutor_user_id_user',
            'user',
            ['tutor_user_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('pmo_vaccination_visit', schema=None) as batch_op:
        batch_op.drop_constraint('fk_pmo_vaccination_visit_tutor_user_id_user', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_pmo_vaccination_visit_tutor_user_id'))
        batch_op.drop_index(batch_op.f('ix_pmo_vaccination_visit_public_token'))
        batch_op.drop_column('evaluated_at')
        batch_op.drop_column('evaluation_comment')
        batch_op.drop_column('evaluation_rating')
        batch_op.drop_column('tutor_user_id')
        batch_op.drop_column('public_token')
