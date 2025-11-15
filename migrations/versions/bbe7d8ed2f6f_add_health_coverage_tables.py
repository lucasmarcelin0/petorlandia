"""add health coverage related tables

Revision ID: bbe7d8ed2f6f
Revises: a3f7a1c72891
Create Date: 2025-11-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bbe7d8ed2f6f'
down_revision = 'a3f7a1c72891'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'health_coverage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(), sa.ForeignKey('health_plan.id'), nullable=False),
        sa.Column('procedure_code', sa.String(length=80), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('coverage_type', sa.String(length=40), nullable=False, server_default='procedimento'),
        sa.Column('monetary_limit', sa.Numeric(12, 2), nullable=True),
        sa.Column('limit_period', sa.String(length=20), nullable=False, server_default='lifetime'),
        sa.Column('waiting_period_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('deductible_amount', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('requires_authorization', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('notes', sa.Text(), nullable=True),
    )

    op.add_column('orcamento_item', sa.Column('coverage_id', sa.Integer(), nullable=True))
    op.add_column(
        'orcamento_item',
        sa.Column('coverage_status', sa.String(length=20), nullable=False, server_default='pending'),
    )
    op.add_column('orcamento_item', sa.Column('coverage_message', sa.Text(), nullable=True))
    op.create_foreign_key(
        'fk_orcamento_item_coverage_id',
        'orcamento_item',
        'health_coverage',
        ['coverage_id'],
        ['id'],
    )

    op.create_table(
        'health_plan_onboarding',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(), sa.ForeignKey('health_plan.id'), nullable=False),
        sa.Column('animal_id', sa.Integer(), sa.ForeignKey('animal.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('guardian_document', sa.String(length=40), nullable=False),
        sa.Column('animal_document', sa.String(length=60), nullable=True),
        sa.Column('contract_reference', sa.String(length=80), nullable=True),
        sa.Column('extra_notes', sa.Text(), nullable=True),
        sa.Column('consent_signed_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('consent_ip', sa.String(length=64), nullable=True),
        sa.Column('attachments', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending_payment'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'health_coverage_usage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('subscription_id', sa.Integer(), sa.ForeignKey('health_subscription.id'), nullable=False),
        sa.Column('coverage_id', sa.Integer(), sa.ForeignKey('health_coverage.id'), nullable=False),
        sa.Column('consulta_id', sa.Integer(), sa.ForeignKey('consulta.id'), nullable=True),
        sa.Column(
            'orcamento_item_id',
            sa.Integer(),
            sa.ForeignKey('orcamento_item.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column('amount_billed', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('amount_covered', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('subscription_id', 'coverage_id', 'orcamento_item_id', name='uq_subscription_coverage_item'),
    )

    op.create_table(
        'health_claim',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('subscription_id', sa.Integer(), sa.ForeignKey('health_subscription.id'), nullable=True),
        sa.Column('consulta_id', sa.Integer(), sa.ForeignKey('consulta.id'), nullable=True),
        sa.Column('coverage_id', sa.Integer(), sa.ForeignKey('health_coverage.id'), nullable=True),
        sa.Column('insurer_reference', sa.String(length=80), nullable=True),
        sa.Column('request_format', sa.String(length=20), nullable=False, server_default='json'),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='received'),
        sa.Column('response_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table('health_claim')
    op.drop_table('health_coverage_usage')
    op.drop_table('health_plan_onboarding')
    op.drop_constraint('fk_orcamento_item_coverage_id', 'orcamento_item', type_='foreignkey')
    op.drop_column('orcamento_item', 'coverage_message')
    op.drop_column('orcamento_item', 'coverage_status')
    op.drop_column('orcamento_item', 'coverage_id')
    op.drop_table('health_coverage')
