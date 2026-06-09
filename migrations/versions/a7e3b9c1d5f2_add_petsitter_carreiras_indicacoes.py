"""Add petsitter, carreiras e indicações tables

Revision ID: a7e3b9c1d5f2
Revises: 0b6d9e3f4a12
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7e3b9c1d5f2'
down_revision = '0b6d9e3f4a12'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'petsitter_profile',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('bio', sa.Text(), nullable=True),
        sa.Column('experiencia', sa.Text(), nullable=True),
        sa.Column('cidade', sa.String(length=120), nullable=True),
        sa.Column('bairro', sa.String(length=120), nullable=True),
        sa.Column('atende_domicilio', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('hospeda_em_casa', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('preco_diaria', sa.Numeric(10, 2), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pendente'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('ix_petsitter_profile_status', 'petsitter_profile', ['status'])

    op.create_table(
        'petsitter_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tutor_id', sa.Integer(), nullable=False),
        sa.Column('sitter_id', sa.Integer(), nullable=True),
        sa.Column('data_inicio', sa.Date(), nullable=False),
        sa.Column('data_fim', sa.Date(), nullable=False),
        sa.Column('local_atendimento', sa.String(length=30), nullable=False, server_default='domicilio_tutor'),
        sa.Column('endereco', sa.String(length=255), nullable=True),
        sa.Column('observacoes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='aberta'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tutor_id'], ['user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sitter_id'], ['petsitter_profile.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_petsitter_request_tutor_id', 'petsitter_request', ['tutor_id'])
    op.create_index('ix_petsitter_request_sitter_id', 'petsitter_request', ['sitter_id'])
    op.create_index('ix_petsitter_request_status', 'petsitter_request', ['status'])

    op.create_table(
        'petsitter_request_animal',
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('animal_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['request_id'], ['petsitter_request.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['animal_id'], ['animal.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('request_id', 'animal_id'),
    )

    op.create_table(
        'career_application',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('categoria', sa.String(length=30), nullable=False),
        sa.Column('nome', sa.String(length=150), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('telefone', sa.String(length=20), nullable=True),
        sa.Column('cidade', sa.String(length=120), nullable=True),
        sa.Column('especialidade', sa.String(length=150), nullable=True),
        sa.Column('mensagem', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pendente'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_career_application_categoria', 'career_application', ['categoria'])
    op.create_index('ix_career_application_status', 'career_application', ['status'])
    op.create_index('ix_career_application_user_id', 'career_application', ['user_id'])

    op.create_table(
        'referral_code',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
        sa.UniqueConstraint('code'),
    )

    op.create_table(
        'referral_signup',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code_id', sa.Integer(), nullable=False),
        sa.Column('referred_user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['code_id'], ['referral_code.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['referred_user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('referred_user_id'),
    )
    op.create_index('ix_referral_signup_code_id', 'referral_signup', ['code_id'])


def downgrade():
    op.drop_index('ix_referral_signup_code_id', table_name='referral_signup')
    op.drop_table('referral_signup')
    op.drop_table('referral_code')
    op.drop_index('ix_career_application_user_id', table_name='career_application')
    op.drop_index('ix_career_application_status', table_name='career_application')
    op.drop_index('ix_career_application_categoria', table_name='career_application')
    op.drop_table('career_application')
    op.drop_table('petsitter_request_animal')
    op.drop_index('ix_petsitter_request_status', table_name='petsitter_request')
    op.drop_index('ix_petsitter_request_sitter_id', table_name='petsitter_request')
    op.drop_index('ix_petsitter_request_tutor_id', table_name='petsitter_request')
    op.drop_table('petsitter_request')
    op.drop_index('ix_petsitter_profile_status', table_name='petsitter_profile')
    op.drop_table('petsitter_profile')
