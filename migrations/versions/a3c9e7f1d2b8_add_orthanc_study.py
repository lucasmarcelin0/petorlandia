"""Add orthanc_study table (webhook PACS Orthanc -> PetOrlandia)

Revision ID: a3c9e7f1d2b8
Revises: b7d4e1f9c2a6
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'a3c9e7f1d2b8'
down_revision = 'b7d4e1f9c2a6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'orthanc_study',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('study_instance_uid', sa.String(length=128), nullable=False),
        sa.Column('orthanc_study_id', sa.String(length=64), nullable=True),
        sa.Column('accession_number', sa.String(length=64), nullable=True),
        sa.Column('study_description', sa.String(length=255), nullable=True),
        sa.Column('study_date', sa.Date(), nullable=True),
        sa.Column('patient_name', sa.String(length=160), nullable=True),
        sa.Column('patient_dicom_id', sa.String(length=64), nullable=True),
        sa.Column('patient_sex', sa.String(length=16), nullable=True),
        sa.Column('series_count', sa.Integer(), nullable=True),
        sa.Column('raw_payload', sa.Text(), nullable=True),
        sa.Column('match_status', sa.String(length=20), nullable=False, server_default='unmatched'),
        sa.Column('animal_id', sa.Integer(), nullable=True),
        sa.Column('exame_imagem_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['animal_id'], ['animal.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['exame_imagem_id'], ['exame_imagem.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_orthanc_study_study_instance_uid', 'orthanc_study', ['study_instance_uid'], unique=True)
    op.create_index('ix_orthanc_study_match_status', 'orthanc_study', ['match_status'])
    op.create_index('ix_orthanc_study_animal_id', 'orthanc_study', ['animal_id'])


def downgrade():
    op.drop_index('ix_orthanc_study_animal_id', table_name='orthanc_study')
    op.drop_index('ix_orthanc_study_match_status', table_name='orthanc_study')
    op.drop_index('ix_orthanc_study_study_instance_uid', table_name='orthanc_study')
    op.drop_table('orthanc_study')
