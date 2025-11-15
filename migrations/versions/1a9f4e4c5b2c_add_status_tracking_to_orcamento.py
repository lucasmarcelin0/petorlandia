"""add status tracking to orcamento

Revision ID: 1a9f4e4c5b2c
Revises: f51ee31de1dd
Create Date: 2024-05-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1a9f4e4c5b2c'
down_revision = 'f51ee31de1dd'
branch_labels = None
depends_on = None


STATUS_DEFAULT = 'draft'


def upgrade():
    op.add_column(
        'orcamento',
        sa.Column('status', sa.String(length=20), nullable=False, server_default=STATUS_DEFAULT),
    )
    op.add_column(
        'orcamento',
        sa.Column(
            'updated_at',
            sa.DateTime(),
            server_default=sa.text('CURRENT_TIMESTAMP'),
            nullable=False,
        ),
    )
    op.add_column(
        'orcamento',
        sa.Column('email_sent_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'orcamento',
        sa.Column('whatsapp_sent_count', sa.Integer(), nullable=False, server_default='0'),
    )

    op.execute("UPDATE orcamento SET updated_at = COALESCE(created_at, updated_at)")

    op.alter_column('orcamento', 'status', server_default=None)
    op.alter_column('orcamento', 'email_sent_count', server_default=None)
    op.alter_column('orcamento', 'whatsapp_sent_count', server_default=None)
    op.alter_column('orcamento', 'updated_at', server_default=None)


def downgrade():
    op.drop_column('orcamento', 'whatsapp_sent_count')
    op.drop_column('orcamento', 'email_sent_count')
    op.drop_column('orcamento', 'updated_at')
    op.drop_column('orcamento', 'status')
