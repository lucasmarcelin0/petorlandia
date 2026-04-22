"""Add accounting phase 3 operational tables

Revision ID: e7f3a9c2b4d1
Revises: b7c1a2d3e4f5
Create Date: 2026-04-21 23:50:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7f3a9c2b4d1'
down_revision = 'b7c1a2d3e4f5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'bank_statement_transactions' not in tables:
        op.create_table(
            'bank_statement_transactions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('clinic_id', sa.Integer(), nullable=False),
            sa.Column('posted_at', sa.Date(), nullable=False),
            sa.Column('amount', sa.Numeric(14, 2), nullable=False),
            sa.Column('memo', sa.String(length=255), nullable=True),
            sa.Column('fit_id', sa.String(length=120), nullable=True),
            sa.Column('matched_account_id', sa.Integer(), nullable=True),
            sa.Column('match_confidence', sa.Numeric(5, 2), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['clinic_id'], ['clinica.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('clinic_id', 'fit_id', name='uq_bank_statement_fit_id'),
        )
        op.create_index('ix_bank_statement_transactions_clinic_id', 'bank_statement_transactions', ['clinic_id'])
        op.create_index('ix_bank_statement_transactions_posted_at', 'bank_statement_transactions', ['posted_at'])

    if 'accounting_accounts' not in tables:
        op.create_table(
            'accounting_accounts',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('clinic_id', sa.Integer(), nullable=False),
            sa.Column('kind', sa.String(length=20), nullable=False),
            sa.Column('status', sa.String(length=20), server_default='open', nullable=False),
            sa.Column('description', sa.String(length=255), nullable=False),
            sa.Column('counterparty_name', sa.String(length=150), nullable=True),
            sa.Column('gross_amount', sa.Numeric(14, 2), nullable=False),
            sa.Column('tax_amount', sa.Numeric(14, 2), nullable=False),
            sa.Column('net_amount', sa.Numeric(14, 2), nullable=False),
            sa.Column('issue_date', sa.Date(), nullable=True),
            sa.Column('due_date', sa.Date(), nullable=True),
            sa.Column('paid_at', sa.Date(), nullable=True),
            sa.Column('source_type', sa.String(length=50), nullable=True),
            sa.Column('source_id', sa.Integer(), nullable=True),
            sa.Column('source_reference', sa.String(length=120), nullable=True),
            sa.Column('bank_transaction_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['bank_transaction_id'], ['bank_statement_transactions.id']),
            sa.ForeignKeyConstraint(['clinic_id'], ['clinica.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('clinic_id', 'source_type', 'source_id', 'kind', name='uq_accounting_account_source'),
        )
        op.create_index('ix_accounting_accounts_clinic_id', 'accounting_accounts', ['clinic_id'])
        op.create_index('ix_accounting_accounts_due_date', 'accounting_accounts', ['due_date'])
        op.create_index('ix_accounting_accounts_issue_date', 'accounting_accounts', ['issue_date'])
        op.create_index('ix_accounting_accounts_kind', 'accounting_accounts', ['kind'])
        op.create_index('ix_accounting_accounts_paid_at', 'accounting_accounts', ['paid_at'])
        op.create_index('ix_accounting_accounts_status', 'accounting_accounts', ['status'])


def downgrade():
    op.drop_index('ix_accounting_accounts_status', table_name='accounting_accounts')
    op.drop_index('ix_accounting_accounts_paid_at', table_name='accounting_accounts')
    op.drop_index('ix_accounting_accounts_kind', table_name='accounting_accounts')
    op.drop_index('ix_accounting_accounts_issue_date', table_name='accounting_accounts')
    op.drop_index('ix_accounting_accounts_due_date', table_name='accounting_accounts')
    op.drop_index('ix_accounting_accounts_clinic_id', table_name='accounting_accounts')
    op.drop_table('accounting_accounts')
    op.drop_index('ix_bank_statement_transactions_posted_at', table_name='bank_statement_transactions')
    op.drop_index('ix_bank_statement_transactions_clinic_id', table_name='bank_statement_transactions')
    op.drop_table('bank_statement_transactions')
