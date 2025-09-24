"""add scheduler metadata to appointment"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6e9a3f4c2b18'
down_revision = '529be1d96219'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('appointment') as batch_op:
        batch_op.add_column(sa.Column('created_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            'fk_appointment_created_by_user',
            'user',
            ['created_by'],
            ['id'],
            ondelete='SET NULL'
        )

    op.execute(
        "UPDATE appointment SET created_at = COALESCE(created_at, scheduled_at, CURRENT_TIMESTAMP)"
    )

    with op.batch_alter_table('appointment') as batch_op:
        batch_op.alter_column('created_at', existing_type=sa.DateTime(), nullable=False)


def downgrade():
    with op.batch_alter_table('appointment') as batch_op:
        batch_op.drop_constraint('fk_appointment_created_by_user', type_='foreignkey')
        batch_op.drop_column('created_at')
        batch_op.drop_column('created_by')
