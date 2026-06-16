"""add pmo castration requests

Revision ID: c2a9f4e7b6d3
Revises: b7c4e2f1a8d9
Create Date: 2026-06-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'c2a9f4e7b6d3'
down_revision = 'b7c4e2f1a8d9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pmo_castration_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('spreadsheet_id', sa.String(length=128), nullable=False),
        sa.Column('sheet_gid', sa.String(length=64), nullable=False),
        sa.Column('sheet_title', sa.String(length=120), nullable=False),
        sa.Column('source_row', sa.Integer(), nullable=False),
        sa.Column('tutor_name', sa.String(length=255), nullable=False),
        sa.Column('cpf', sa.String(length=32), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('address', sa.String(length=500), nullable=True),
        sa.Column('phone1', sa.String(length=32), nullable=True),
        sa.Column('phone2', sa.String(length=32), nullable=True),
        sa.Column('dogs', sa.Integer(), nullable=False),
        sa.Column('cats', sa.Integer(), nullable=False),
        sa.Column('preferred_contact', sa.String(length=80), nullable=True),
        sa.Column('female_status', sa.String(length=120), nullable=True),
        sa.Column('health_notes', sa.Text(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('public_token', sa.String(length=96), nullable=True),
        sa.Column('tutor_user_id', sa.Integer(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tutor_user_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('spreadsheet_id', 'sheet_gid', 'source_row', name='uq_pmo_castration_request_sheet_row'),
    )
    op.create_index(op.f('ix_pmo_castration_request_public_token'), 'pmo_castration_request', ['public_token'], unique=True)
    op.create_index(op.f('ix_pmo_castration_request_sheet_gid'), 'pmo_castration_request', ['sheet_gid'], unique=False)
    op.create_index(op.f('ix_pmo_castration_request_sheet_title'), 'pmo_castration_request', ['sheet_title'], unique=False)
    op.create_index(op.f('ix_pmo_castration_request_spreadsheet_id'), 'pmo_castration_request', ['spreadsheet_id'], unique=False)
    op.create_index(op.f('ix_pmo_castration_request_status'), 'pmo_castration_request', ['status'], unique=False)
    op.create_index(op.f('ix_pmo_castration_request_tutor_user_id'), 'pmo_castration_request', ['tutor_user_id'], unique=False)

    op.create_table(
        'pmo_castration_animal',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('animal_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('species', sa.String(length=20), nullable=False),
        sa.Column('sex', sa.String(length=20), nullable=True),
        sa.Column('age_label', sa.String(length=80), nullable=True),
        sa.Column('weight_kg', sa.Float(), nullable=True),
        sa.Column('already_neutered', sa.Boolean(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['animal_id'], ['animal.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['request_id'], ['pmo_castration_request.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_pmo_castration_animal_animal_id'), 'pmo_castration_animal', ['animal_id'], unique=False)
    op.create_index(op.f('ix_pmo_castration_animal_request_id'), 'pmo_castration_animal', ['request_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_pmo_castration_animal_request_id'), table_name='pmo_castration_animal')
    op.drop_index(op.f('ix_pmo_castration_animal_animal_id'), table_name='pmo_castration_animal')
    op.drop_table('pmo_castration_animal')
    op.drop_index(op.f('ix_pmo_castration_request_tutor_user_id'), table_name='pmo_castration_request')
    op.drop_index(op.f('ix_pmo_castration_request_status'), table_name='pmo_castration_request')
    op.drop_index(op.f('ix_pmo_castration_request_spreadsheet_id'), table_name='pmo_castration_request')
    op.drop_index(op.f('ix_pmo_castration_request_sheet_title'), table_name='pmo_castration_request')
    op.drop_index(op.f('ix_pmo_castration_request_sheet_gid'), table_name='pmo_castration_request')
    op.drop_index(op.f('ix_pmo_castration_request_public_token'), table_name='pmo_castration_request')
    op.drop_table('pmo_castration_request')
