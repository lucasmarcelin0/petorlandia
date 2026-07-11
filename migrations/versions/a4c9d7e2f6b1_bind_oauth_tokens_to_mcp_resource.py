"""bind oauth grants and tokens to the requested MCP resource

Revision ID: a4c9d7e2f6b1
Revises: d1ad23eb2fcb
Create Date: 2026-07-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a4c9d7e2f6b1'
down_revision = 'd1ad23eb2fcb'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('oauth_authorization_code', sa.Column('resource', sa.String(length=512), nullable=True))
    op.add_column('oauth_access_token', sa.Column('resource', sa.String(length=512), nullable=True))
    op.create_index(op.f('ix_oauth_access_token_resource'), 'oauth_access_token', ['resource'], unique=False)
    op.add_column('oauth_refresh_token', sa.Column('resource', sa.String(length=512), nullable=True))
    op.create_index(op.f('ix_oauth_refresh_token_resource'), 'oauth_refresh_token', ['resource'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_oauth_refresh_token_resource'), table_name='oauth_refresh_token')
    op.drop_column('oauth_refresh_token', 'resource')
    op.drop_index(op.f('ix_oauth_access_token_resource'), table_name='oauth_access_token')
    op.drop_column('oauth_access_token', 'resource')
    op.drop_column('oauth_authorization_code', 'resource')
