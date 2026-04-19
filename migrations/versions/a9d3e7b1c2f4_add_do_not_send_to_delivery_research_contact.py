"""add do_not_send to delivery research contact

Revision ID: a9d3e7b1c2f4
Revises: f6c1a3d9e2b4
Create Date: 2026-04-19 17:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'a9d3e7b1c2f4'
down_revision = 'f6c1a3d9e2b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('delivery_research_contact', schema=None) as batch_op:
        batch_op.add_column(sa.Column('do_not_send', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('do_not_send_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('do_not_send_by_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_delivery_research_contact_do_not_send_by_id_user',
            'user',
            ['do_not_send_by_id'],
            ['id'],
            ondelete='SET NULL',
        )

    op.execute("UPDATE delivery_research_contact SET do_not_send = FALSE WHERE do_not_send IS NULL")

    with op.batch_alter_table('delivery_research_contact', schema=None) as batch_op:
        batch_op.alter_column('do_not_send', server_default=None)


def downgrade():
    with op.batch_alter_table('delivery_research_contact', schema=None) as batch_op:
        batch_op.drop_constraint('fk_delivery_research_contact_do_not_send_by_id_user', type_='foreignkey')
        batch_op.drop_column('do_not_send_by_id')
        batch_op.drop_column('do_not_send_at')
        batch_op.drop_column('do_not_send')
