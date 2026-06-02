"""add appointment_request table (privacy-safe scheduling requests)

Revision ID: c2e5a7b9d3f1
Revises: b1d4f6a8c2e3
Create Date: 2026-06-02 00:00:00.000000

Aditiva e não destrutiva: cria a tabela ``appointment_request``, onde o tutor
registra solicitações de agendamento (consulta/exame/vacina) sem acessar a
agenda do profissional. Nenhum dado existente é alterado.
"""

from alembic import op
import sqlalchemy as sa


revision = 'c2e5a7b9d3f1'
down_revision = 'b1d4f6a8c2e3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'appointment_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tutor_id', sa.Integer(), nullable=False),
        sa.Column('animal_id', sa.Integer(), nullable=False),
        sa.Column('veterinario_id', sa.Integer(), nullable=False),
        sa.Column('clinica_id', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(length=20), nullable=False, server_default='consulta'),
        sa.Column('mode', sa.String(length=20), nullable=False, server_default='clinica'),
        sa.Column('preferred_date', sa.Date(), nullable=False),
        sa.Column('preferred_time', sa.Time(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('response_note', sa.Text(), nullable=True),
        sa.Column('appointment_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tutor_id'], ['user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['animal_id'], ['animal.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['veterinario_id'], ['veterinario.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['clinica_id'], ['clinica.id']),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointment.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_appointment_request_tutor_id', 'appointment_request', ['tutor_id'])
    op.create_index('ix_appointment_request_veterinario_id', 'appointment_request', ['veterinario_id'])
    op.create_index('ix_appointment_request_status', 'appointment_request', ['status'])


def downgrade():
    op.drop_index('ix_appointment_request_status', table_name='appointment_request')
    op.drop_index('ix_appointment_request_veterinario_id', table_name='appointment_request')
    op.drop_index('ix_appointment_request_tutor_id', table_name='appointment_request')
    op.drop_table('appointment_request')
