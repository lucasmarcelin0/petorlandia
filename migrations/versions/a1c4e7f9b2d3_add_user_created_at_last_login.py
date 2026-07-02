"""Add created_at and last_login to user

Revision ID: a1c4e7f9b2d3
Revises: fb9f33ae1c23
Create Date: 2026-07-02

Usuários existentes ficam com created_at NULL (cadastro anterior ao
rastreamento); apenas novos cadastros recebem a data automaticamente.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1c4e7f9b2d3'
down_revision = 'fb9f33ae1c23'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing_columns = {column['name'] for column in sa.inspect(bind).get_columns('user')}

    with op.batch_alter_table('user', schema=None) as batch_op:
        if 'created_at' not in existing_columns:
            batch_op.add_column(sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))
        if 'last_login' not in existing_columns:
            batch_op.add_column(sa.Column('last_login', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    bind = op.get_bind()
    existing_columns = {column['name'] for column in sa.inspect(bind).get_columns('user')}

    with op.batch_alter_table('user', schema=None) as batch_op:
        if 'last_login' in existing_columns:
            batch_op.drop_column('last_login')
        if 'created_at' in existing_columns:
            batch_op.drop_column('created_at')
