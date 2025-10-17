"""add request idempotency keys

Revision ID: e0b1d4f7c3b4
Revises: ('def340caa273', 'cd4535f122b0', '31b09172852f', '1e5b8c4d2f3a', '9a8b7c6d5e4f', 'b4a6aa4bce3f', '6e9a3f4c2b18', 'c592f5b733c6', '8c5e4d7c9b1a', '762f0e69f93c', 'c1d9e6e54a3b')
Create Date: 2024-09-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e0b1d4f7c3b4'
down_revision = ('def340caa273', 'cd4535f122b0', '31b09172852f', '1e5b8c4d2f3a', '9a8b7c6d5e4f', 'b4a6aa4bce3f', '6e9a3f4c2b18', 'c592f5b733c6', '8c5e4d7c9b1a', '762f0e69f93c', 'c1d9e6e54a3b')
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'request_idempotency_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('endpoint', sa.String(length=255), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('response_code', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('response_mimetype', sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token')
    )


def downgrade():
    op.drop_table('request_idempotency_keys')
