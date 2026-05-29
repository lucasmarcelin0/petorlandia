"""create pmo route optimization backup

Revision ID: fb8c2d1e4a6f
Revises: d2e7f1a8b3c5
Create Date: 2026-05-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'fb8c2d1e4a6f'
down_revision = 'd2e7f1a8b3c5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pmo_route_optimization_backup',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('spreadsheet_id', sa.String(length=128), nullable=False),
        sa.Column('sheet_gid', sa.String(length=64), nullable=False),
        sa.Column('sheet_title', sa.String(length=120), nullable=False),
        sa.Column('shift', sa.String(length=30), nullable=False),
        sa.Column('source_rows_json', sa.Text(), nullable=False),
        sa.Column('before_values_json', sa.Text(), nullable=False),
        sa.Column('after_values_json', sa.Text(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('undone_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_pmo_route_optimization_backup_created_at'), 'pmo_route_optimization_backup', ['created_at'], unique=False)
    op.create_index(op.f('ix_pmo_route_optimization_backup_created_by_id'), 'pmo_route_optimization_backup', ['created_by_id'], unique=False)
    op.create_index(op.f('ix_pmo_route_optimization_backup_sheet_gid'), 'pmo_route_optimization_backup', ['sheet_gid'], unique=False)
    op.create_index(op.f('ix_pmo_route_optimization_backup_sheet_title'), 'pmo_route_optimization_backup', ['sheet_title'], unique=False)
    op.create_index(op.f('ix_pmo_route_optimization_backup_shift'), 'pmo_route_optimization_backup', ['shift'], unique=False)
    op.create_index(op.f('ix_pmo_route_optimization_backup_spreadsheet_id'), 'pmo_route_optimization_backup', ['spreadsheet_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_pmo_route_optimization_backup_spreadsheet_id'), table_name='pmo_route_optimization_backup')
    op.drop_index(op.f('ix_pmo_route_optimization_backup_shift'), table_name='pmo_route_optimization_backup')
    op.drop_index(op.f('ix_pmo_route_optimization_backup_sheet_title'), table_name='pmo_route_optimization_backup')
    op.drop_index(op.f('ix_pmo_route_optimization_backup_sheet_gid'), table_name='pmo_route_optimization_backup')
    op.drop_index(op.f('ix_pmo_route_optimization_backup_created_by_id'), table_name='pmo_route_optimization_backup')
    op.drop_index(op.f('ix_pmo_route_optimization_backup_created_at'), table_name='pmo_route_optimization_backup')
    op.drop_table('pmo_route_optimization_backup')
