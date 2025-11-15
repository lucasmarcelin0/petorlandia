"""add classified transactions table"""

from alembic import op
import sqlalchemy as sa

revision = 'b0415360aa2f'
down_revision = 'fe3b6f9d7e2d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'classified_transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.DateTime(), nullable=False),
        sa.Column('month', sa.Date(), nullable=False),
        sa.Column('origin', sa.String(length=50), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=False),
        sa.Column('value', sa.Numeric(14, 2), nullable=False),
        sa.Column('category', sa.String(length=80), nullable=False),
        sa.Column('subcategory', sa.String(length=80), nullable=True),
        sa.Column('raw_id', sa.String(length=80), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinica.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('clinic_id', 'raw_id', name='uq_classified_raw_id'),
    )
    op.create_index('ix_classified_transactions_category', 'classified_transactions', ['category'])
    op.create_index('ix_classified_transactions_clinic_id', 'classified_transactions', ['clinic_id'])
    op.create_index('ix_classified_transactions_date', 'classified_transactions', ['date'])
    op.create_index('ix_classified_transactions_month', 'classified_transactions', ['month'])


def downgrade():
    op.drop_index('ix_classified_transactions_month', table_name='classified_transactions')
    op.drop_index('ix_classified_transactions_date', table_name='classified_transactions')
    op.drop_index('ix_classified_transactions_clinic_id', table_name='classified_transactions')
    op.drop_index('ix_classified_transactions_category', table_name='classified_transactions')
    op.drop_table('classified_transactions')
