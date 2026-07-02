"""add professional service catalog

Revision ID: b2d4f6a8c1e9
Revises: a1c4e7f9b2d3
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa


revision = 'b2d4f6a8c1e9'
down_revision = 'a1c4e7f9b2d3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'professional_service',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('veterinario_id', sa.Integer(), nullable=False),
        sa.Column('service_type', sa.String(length=40), nullable=False, server_default='consulta'),
        sa.Column('title', sa.String(length=140), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('audience', sa.String(length=20), nullable=False, server_default='tutor'),
        sa.Column('mode', sa.String(length=40), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('business_start', sa.Time(), nullable=True),
        sa.Column('business_end', sa.Time(), nullable=True),
        sa.Column('tutor_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('clinic_business_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('clinic_after_hours_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['veterinario_id'], ['veterinario.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_professional_service_active'), 'professional_service', ['active'], unique=False)
    op.create_index(op.f('ix_professional_service_veterinario_id'), 'professional_service', ['veterinario_id'], unique=False)

    bind = op.get_bind()
    vet_row = bind.execute(sa.text("""
        SELECT v.id
        FROM veterinario v
        JOIN "user" u ON u.id = v.user_id
        WHERE lower(u.name) LIKE '%robson%'
        ORDER BY
          CASE
            WHEN lower(u.name) LIKE '%santos%' THEN 0
            WHEN lower(u.name) LIKE '%oliveira%' THEN 1
            ELSE 2
          END,
          v.id
        LIMIT 1
    """)).fetchone()
    if vet_row:
        vet_id = vet_row[0]
        bind.execute(sa.text("""
            INSERT INTO professional_service
              (veterinario_id, service_type, title, description, audience, mode,
               duration_minutes, active, business_start, business_end,
               tutor_price, clinic_business_price, clinic_after_hours_price)
            VALUES
              (:vet_id, 'ultrassom', 'Ultrassonografia veterinária',
               'Exame ultrassonográfico para clínicas e tutores, com laudo digital pela plataforma.',
               'both', 'clinica_ou_domicilio', 60, true, '09:00', '19:00',
               260.00, 170.00, 270.00),
              (:vet_id, 'consulta', 'Consulta veterinária domiciliar',
               'Consulta veterinária em domicílio para tutores.',
               'tutor', 'domicilio', 60, true, '09:00', '19:00',
               160.00, NULL, NULL)
        """), {'vet_id': vet_id})


def downgrade():
    op.drop_index(op.f('ix_professional_service_veterinario_id'), table_name='professional_service')
    op.drop_index(op.f('ix_professional_service_active'), table_name='professional_service')
    op.drop_table('professional_service')
