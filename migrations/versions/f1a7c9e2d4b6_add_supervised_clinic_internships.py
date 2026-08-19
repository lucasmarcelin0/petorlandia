"""Add supervised internship permissions and explicit case assignments."""

from alembic import op
import sqlalchemy as sa


revision = 'f1a7c9e2d4b6'
down_revision = 'e9b6c3a41d72'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('clinic_staff', sa.Column('is_intern', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('clinic_staff', sa.Column('internship_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clinic_staff', sa.Column('internship_ends_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clinic_staff', sa.Column('internship_supervisor_id', sa.Integer(), nullable=True))
    op.add_column('clinic_staff', sa.Column('can_view_all_patients', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('clinic_staff', sa.Column('can_draft_clinical_notes', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('clinic_staff', sa.Column('can_print_signed_documents', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_foreign_key('fk_clinic_staff_internship_supervisor', 'clinic_staff', 'user', ['internship_supervisor_id'], ['id'])
    op.create_table(
        'clinic_internship_case',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('clinic_id', sa.Integer(), sa.ForeignKey('clinica.id'), nullable=False, index=True),
        sa.Column('intern_user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('animal_id', sa.Integer(), sa.ForeignKey('animal.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('assigned_by_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table('clinic_internship_case')
    op.drop_constraint('fk_clinic_staff_internship_supervisor', 'clinic_staff', type_='foreignkey')
    for name in ('can_print_signed_documents', 'can_draft_clinical_notes', 'can_view_all_patients', 'internship_supervisor_id', 'internship_ends_at', 'internship_started_at', 'is_intern'):
        op.drop_column('clinic_staff', name)
