"""add owner to clinica

Revision ID: e82dc233fe3c
Revises: d423b058d278
Create Date: 2025-08-11 15:55:19.252384

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e82dc233fe3c'
down_revision = 'd423b058d278'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('clinica', sa.Column('owner_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_clinica_owner', 'clinica', 'user', ['owner_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_clinica_owner', 'clinica', type_='foreignkey')
    op.drop_column('clinica', 'owner_id')
