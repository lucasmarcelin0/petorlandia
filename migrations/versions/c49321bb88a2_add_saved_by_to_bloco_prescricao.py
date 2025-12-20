"""add saved_by to bloco_prescricao

Revision ID: c49321bb88a2
Revises: d5e2c9a1c3f4
Create Date: 2025-11-11 16:13:18.518729

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c49321bb88a2'
down_revision = 'd5e2c9a1c3f4'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('bloco_prescricao')]
    
    if 'saved_by_id' not in columns:
        with op.batch_alter_table('bloco_prescricao', schema=None) as batch_op:
            batch_op.add_column(sa.Column('saved_by_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                'fk_bloco_prescricao_saved_by_id_user',
                'user',
                ['saved_by_id'],
                ['id'],
            )


def downgrade():
    with op.batch_alter_table('bloco_prescricao', schema=None) as batch_op:
        batch_op.drop_constraint('fk_bloco_prescricao_saved_by_id_user', type_='foreignkey')
        batch_op.drop_column('saved_by_id')
