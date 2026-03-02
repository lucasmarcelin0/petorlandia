"""add oauth server tables

Revision ID: c1d2e3f4a5b6
Revises: d5e2c9a1c3f4
Create Date: 2026-03-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1d2e3f4a5b6'
down_revision = 'd5e2c9a1c3f4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'oauth_client',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.String(length=120), nullable=False),
        sa.Column('client_secret', sa.String(length=255), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('redirect_uris', sa.Text(), nullable=False),
        sa.Column('scope', sa.String(length=255), nullable=False),
        sa.Column('is_confidential', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_id'),
    )
    op.create_index(op.f('ix_oauth_client_client_id'), 'oauth_client', ['client_id'], unique=True)

    op.create_table(
        'oauth_authorization_code',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=255), nullable=False),
        sa.Column('client_id', sa.String(length=120), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('redirect_uri', sa.String(length=512), nullable=False),
        sa.Column('scope', sa.String(length=255), nullable=False),
        sa.Column('nonce', sa.String(length=255), nullable=True),
        sa.Column('state', sa.String(length=255), nullable=True),
        sa.Column('code_challenge', sa.String(length=255), nullable=False),
        sa.Column('code_challenge_method', sa.String(length=10), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index(op.f('ix_oauth_authorization_code_client_id'), 'oauth_authorization_code', ['client_id'], unique=False)
    op.create_index(op.f('ix_oauth_authorization_code_code'), 'oauth_authorization_code', ['code'], unique=True)

    op.create_table(
        'oauth_token',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.String(length=120), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('access_token', sa.String(length=255), nullable=False),
        sa.Column('refresh_token', sa.String(length=255), nullable=True),
        sa.Column('token_type', sa.String(length=40), nullable=False),
        sa.Column('scope', sa.String(length=255), nullable=False),
        sa.Column('id_token', sa.Text(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('access_token'),
        sa.UniqueConstraint('refresh_token'),
    )
    op.create_index(op.f('ix_oauth_token_client_id'), 'oauth_token', ['client_id'], unique=False)
    op.create_index(op.f('ix_oauth_token_access_token'), 'oauth_token', ['access_token'], unique=True)
    op.create_index(op.f('ix_oauth_token_refresh_token'), 'oauth_token', ['refresh_token'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_oauth_token_refresh_token'), table_name='oauth_token')
    op.drop_index(op.f('ix_oauth_token_access_token'), table_name='oauth_token')
    op.drop_index(op.f('ix_oauth_token_client_id'), table_name='oauth_token')
    op.drop_table('oauth_token')

    op.drop_index(op.f('ix_oauth_authorization_code_code'), table_name='oauth_authorization_code')
    op.drop_index(op.f('ix_oauth_authorization_code_client_id'), table_name='oauth_authorization_code')
    op.drop_table('oauth_authorization_code')

    op.drop_index(op.f('ix_oauth_client_client_id'), table_name='oauth_client')
    op.drop_table('oauth_client')
