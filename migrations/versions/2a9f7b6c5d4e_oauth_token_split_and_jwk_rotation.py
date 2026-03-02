"""oauth token split and jwk rotation

Revision ID: 2a9f7b6c5d4e
Revises: c1d2e3f4a5b6
Create Date: 2026-03-02 00:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2a9f7b6c5d4e'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('oauth_client', sa.Column('grant_types', sa.String(length=255), nullable=False, server_default='authorization_code'))
    op.add_column('oauth_client', sa.Column('scopes', sa.String(length=255), nullable=False, server_default='openid profile email'))
    op.add_column('oauth_client', sa.Column('auth_method', sa.String(length=80), nullable=False, server_default='none'))
    op.execute("UPDATE oauth_client SET scopes = scope")
    op.drop_column('oauth_client', 'scope')

    op.add_column('oauth_authorization_code', sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_oauth_authorization_code_user_id', 'oauth_authorization_code', ['user_id'], unique=False)
    op.create_index('ix_oauth_authorization_code_expires_at', 'oauth_authorization_code', ['expires_at'], unique=False)

    op.create_table(
        'oauth_refresh_token',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jti', sa.String(length=64), nullable=False),
        sa.Column('client_id', sa.String(length=120), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('refresh_token', sa.String(length=255), nullable=False),
        sa.Column('scope', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('replaced_by_jti', sa.String(length=64), nullable=True),
        sa.Column('family_id', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('jti', name='uq_oauth_refresh_token_jti'),
        sa.UniqueConstraint('refresh_token', name='uq_oauth_refresh_token_value'),
    )
    op.create_index('ix_oauth_refresh_token_user_id', 'oauth_refresh_token', ['user_id'], unique=False)
    op.create_index('ix_oauth_refresh_token_client_id', 'oauth_refresh_token', ['client_id'], unique=False)
    op.create_index('ix_oauth_refresh_token_expires_at', 'oauth_refresh_token', ['expires_at'], unique=False)

    op.create_table(
        'oauth_access_token',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jti', sa.String(length=64), nullable=False),
        sa.Column('client_id', sa.String(length=120), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('access_token', sa.String(length=255), nullable=False),
        sa.Column('token_type', sa.String(length=40), nullable=False, server_default='Bearer'),
        sa.Column('scope', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('id_token', sa.Text(), nullable=True),
        sa.Column('refresh_token_id', sa.Integer(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['refresh_token_id'], ['oauth_refresh_token.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('jti', name='uq_oauth_access_token_jti'),
        sa.UniqueConstraint('access_token', name='uq_oauth_access_token_value'),
    )
    op.create_index('ix_oauth_access_token_user_id', 'oauth_access_token', ['user_id'], unique=False)
    op.create_index('ix_oauth_access_token_client_id', 'oauth_access_token', ['client_id'], unique=False)
    op.create_index('ix_oauth_access_token_expires_at', 'oauth_access_token', ['expires_at'], unique=False)

    op.create_table(
        'oauth_consent',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.String(length=120), nullable=False),
        sa.Column('scopes', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'client_id', name='uq_oauth_consent_user_client'),
    )
    op.create_index('ix_oauth_consent_user_id', 'oauth_consent', ['user_id'], unique=False)
    op.create_index('ix_oauth_consent_client_id', 'oauth_consent', ['client_id'], unique=False)

    op.create_table(
        'oauth_jwk_key',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kid', sa.String(length=64), nullable=False),
        sa.Column('kty', sa.String(length=16), nullable=False, server_default='RSA'),
        sa.Column('private_pem', sa.Text(), nullable=False),
        sa.Column('public_pem', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='active'),
        sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('grace_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rotated_from_kid', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kid', name='uq_oauth_jwk_key_kid'),
    )
    op.create_index('ix_oauth_jwk_key_kid', 'oauth_jwk_key', ['kid'], unique=True)
    op.create_index('ix_oauth_jwk_key_status', 'oauth_jwk_key', ['status'], unique=False)
    op.create_index('ix_oauth_jwk_key_valid_until', 'oauth_jwk_key', ['valid_until'], unique=False)


def downgrade():
    op.drop_index('ix_oauth_jwk_key_valid_until', table_name='oauth_jwk_key')
    op.drop_index('ix_oauth_jwk_key_status', table_name='oauth_jwk_key')
    op.drop_index('ix_oauth_jwk_key_kid', table_name='oauth_jwk_key')
    op.drop_table('oauth_jwk_key')

    op.drop_index('ix_oauth_consent_client_id', table_name='oauth_consent')
    op.drop_index('ix_oauth_consent_user_id', table_name='oauth_consent')
    op.drop_table('oauth_consent')

    op.drop_index('ix_oauth_access_token_expires_at', table_name='oauth_access_token')
    op.drop_index('ix_oauth_access_token_client_id', table_name='oauth_access_token')
    op.drop_index('ix_oauth_access_token_user_id', table_name='oauth_access_token')
    op.drop_table('oauth_access_token')

    op.drop_index('ix_oauth_refresh_token_expires_at', table_name='oauth_refresh_token')
    op.drop_index('ix_oauth_refresh_token_client_id', table_name='oauth_refresh_token')
    op.drop_index('ix_oauth_refresh_token_user_id', table_name='oauth_refresh_token')
    op.drop_table('oauth_refresh_token')

    op.drop_index('ix_oauth_authorization_code_expires_at', table_name='oauth_authorization_code')
    op.drop_index('ix_oauth_authorization_code_user_id', table_name='oauth_authorization_code')
    op.drop_column('oauth_authorization_code', 'revoked_at')

    op.add_column('oauth_client', sa.Column('scope', sa.String(length=255), nullable=False, server_default='openid profile email'))
    op.execute("UPDATE oauth_client SET scope = scopes")
    op.drop_column('oauth_client', 'auth_method')
    op.drop_column('oauth_client', 'scopes')
    op.drop_column('oauth_client', 'grant_types')
