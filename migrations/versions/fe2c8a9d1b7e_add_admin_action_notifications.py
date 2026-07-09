"""add admin action notifications

Revision ID: fe2c8a9d1b7e
Revises: bb7354ce1427
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa


revision = 'fe2c8a9d1b7e'
down_revision = 'bb7354ce1427'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'admin_action_notification',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recipient_user_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=80), nullable=False),
        sa.Column('entity_type', sa.String(length=80), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('priority', sa.String(length=20), nullable=False, server_default='normal'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='unread'),
        sa.Column('idempotency_key', sa.String(length=180), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['recipient_user_id'], ['user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['resolved_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'recipient_user_id',
            'idempotency_key',
            name='uq_admin_action_notification_recipient_key',
        ),
    )
    op.create_index('ix_admin_action_notification_recipient_user_id', 'admin_action_notification', ['recipient_user_id'])
    op.create_index('ix_admin_action_notification_event_type', 'admin_action_notification', ['event_type'])
    op.create_index('ix_admin_action_notification_entity_type', 'admin_action_notification', ['entity_type'])
    op.create_index('ix_admin_action_notification_entity_id', 'admin_action_notification', ['entity_id'])
    op.create_index('ix_admin_action_notification_priority', 'admin_action_notification', ['priority'])
    op.create_index('ix_admin_action_notification_status', 'admin_action_notification', ['status'])


def downgrade():
    op.drop_index('ix_admin_action_notification_status', table_name='admin_action_notification')
    op.drop_index('ix_admin_action_notification_priority', table_name='admin_action_notification')
    op.drop_index('ix_admin_action_notification_entity_id', table_name='admin_action_notification')
    op.drop_index('ix_admin_action_notification_entity_type', table_name='admin_action_notification')
    op.drop_index('ix_admin_action_notification_event_type', table_name='admin_action_notification')
    op.drop_index('ix_admin_action_notification_recipient_user_id', table_name='admin_action_notification')
    op.drop_table('admin_action_notification')
