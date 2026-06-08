"""expand oauth scope columns

Revision ID: e2a7c4d9f6b1
Revises: c9f2a7d4e8b1, e8b2c4d7f1a9
Create Date: 2026-06-08 00:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e2a7c4d9f6b1"
down_revision = ("c9f2a7d4e8b1", "e8b2c4d7f1a9")
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("oauth_client", schema=None) as batch_op:
        batch_op.alter_column(
            "scopes",
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=False,
            existing_server_default="openid profile email",
        )

    with op.batch_alter_table("oauth_authorization_code", schema=None) as batch_op:
        batch_op.alter_column(
            "scope",
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=False,
        )

    with op.batch_alter_table("oauth_access_token", schema=None) as batch_op:
        batch_op.alter_column(
            "scope",
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=False,
            existing_server_default="",
        )

    with op.batch_alter_table("oauth_refresh_token", schema=None) as batch_op:
        batch_op.alter_column(
            "scope",
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=False,
            existing_server_default="",
        )

    with op.batch_alter_table("oauth_consent", schema=None) as batch_op:
        batch_op.alter_column(
            "scopes",
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=False,
            existing_server_default="",
        )


def downgrade():
    with op.batch_alter_table("oauth_consent", schema=None) as batch_op:
        batch_op.alter_column(
            "scopes",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=False,
            existing_server_default="",
        )

    with op.batch_alter_table("oauth_refresh_token", schema=None) as batch_op:
        batch_op.alter_column(
            "scope",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=False,
            existing_server_default="",
        )

    with op.batch_alter_table("oauth_access_token", schema=None) as batch_op:
        batch_op.alter_column(
            "scope",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=False,
            existing_server_default="",
        )

    with op.batch_alter_table("oauth_authorization_code", schema=None) as batch_op:
        batch_op.alter_column(
            "scope",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=False,
        )

    with op.batch_alter_table("oauth_client", schema=None) as batch_op:
        batch_op.alter_column(
            "scopes",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=False,
            existing_server_default="openid profile email",
        )
