"""create pmo vaccination tables

Revision ID: e3f6a8b2c9d4
Revises: d7a3b9c2e5f6
Create Date: 2026-05-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'e3f6a8b2c9d4'
down_revision = 'd7a3b9c2e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pmo_vaccination_visit',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('spreadsheet_id', sa.String(length=128), nullable=False),
        sa.Column('sheet_gid', sa.String(length=64), nullable=False),
        sa.Column('sheet_title', sa.String(length=120), nullable=False),
        sa.Column('source_row', sa.Integer(), nullable=False),
        sa.Column('tutor_name', sa.String(length=255), nullable=False),
        sa.Column('address', sa.String(length=500), nullable=True),
        sa.Column('phone1', sa.String(length=32), nullable=True),
        sa.Column('phone2', sa.String(length=32), nullable=True),
        sa.Column('dogs', sa.Integer(), nullable=False),
        sa.Column('cats', sa.Integer(), nullable=False),
        sa.Column('vaccine_date', sa.Date(), nullable=True),
        sa.Column('shift', sa.String(length=30), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('password', sa.String(length=32), nullable=False),
        sa.Column('certificate_url', sa.String(length=500), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'spreadsheet_id',
            'sheet_gid',
            'source_row',
            name='uq_pmo_vaccination_visit_sheet_row',
        ),
    )
    op.create_index(
        op.f('ix_pmo_vaccination_visit_sheet_gid'),
        'pmo_vaccination_visit',
        ['sheet_gid'],
        unique=False,
    )
    op.create_index(
        op.f('ix_pmo_vaccination_visit_sheet_title'),
        'pmo_vaccination_visit',
        ['sheet_title'],
        unique=False,
    )
    op.create_index(
        op.f('ix_pmo_vaccination_visit_spreadsheet_id'),
        'pmo_vaccination_visit',
        ['spreadsheet_id'],
        unique=False,
    )
    op.create_table(
        'pmo_vaccination_animal',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('visit_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('species', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('vaccinated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['visit_id'], ['pmo_vaccination_visit.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_pmo_vaccination_animal_visit_id'),
        'pmo_vaccination_animal',
        ['visit_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f('ix_pmo_vaccination_animal_visit_id'), table_name='pmo_vaccination_animal')
    op.drop_table('pmo_vaccination_animal')
    op.drop_index(op.f('ix_pmo_vaccination_visit_spreadsheet_id'), table_name='pmo_vaccination_visit')
    op.drop_index(op.f('ix_pmo_vaccination_visit_sheet_title'), table_name='pmo_vaccination_visit')
    op.drop_index(op.f('ix_pmo_vaccination_visit_sheet_gid'), table_name='pmo_vaccination_visit')
    op.drop_table('pmo_vaccination_visit')
