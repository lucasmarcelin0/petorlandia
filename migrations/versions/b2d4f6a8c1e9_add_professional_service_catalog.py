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
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'professional_service' not in set(inspector.get_table_names()):
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
        inspector = sa.inspect(bind)

    existing_indexes = {index['name'] for index in inspector.get_indexes('professional_service')}
    if op.f('ix_professional_service_active') not in existing_indexes:
        op.create_index(op.f('ix_professional_service_active'), 'professional_service', ['active'], unique=False)
    if op.f('ix_professional_service_veterinario_id') not in existing_indexes:
        op.create_index(op.f('ix_professional_service_veterinario_id'), 'professional_service', ['veterinario_id'], unique=False)

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
    if not vet_row:
        return

    vet_id = vet_row[0]
    services = [
        {
            'service_type': 'ultrassom',
            'title': 'Ultrassonografia veterin\u00e1ria',
            'description': 'Exame ultrassonogr\u00e1fico para cl\u00ednicas e tutores, com laudo digital pela plataforma.',
            'audience': 'both',
            'mode': 'clinica_ou_domicilio',
            'duration_minutes': 60,
            'business_start': '09:00',
            'business_end': '19:00',
            'tutor_price': 260.00,
            'clinic_business_price': 170.00,
            'clinic_after_hours_price': 270.00,
        },
        {
            'service_type': 'consulta',
            'title': 'Consulta veterin\u00e1ria domiciliar',
            'description': 'Consulta veterin\u00e1ria em domic\u00edlio para tutores.',
            'audience': 'tutor',
            'mode': 'domicilio',
            'duration_minutes': 60,
            'business_start': '09:00',
            'business_end': '19:00',
            'tutor_price': 160.00,
            'clinic_business_price': None,
            'clinic_after_hours_price': None,
        },
    ]

    for service in services:
        exists = bind.execute(sa.text("""
            SELECT 1
            FROM professional_service
            WHERE veterinario_id = :vet_id
              AND service_type = :service_type
              AND title = :title
            LIMIT 1
        """), {'vet_id': vet_id, **service}).fetchone()
        if exists:
            continue

        bind.execute(sa.text("""
            INSERT INTO professional_service
              (veterinario_id, service_type, title, description, audience, mode,
               duration_minutes, active, business_start, business_end,
               tutor_price, clinic_business_price, clinic_after_hours_price)
            VALUES
              (:vet_id, :service_type, :title, :description, :audience, :mode,
               :duration_minutes, true, :business_start, :business_end,
               :tutor_price, :clinic_business_price, :clinic_after_hours_price)
        """), {'vet_id': vet_id, **service})


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'professional_service' not in set(inspector.get_table_names()):
        return

    existing_indexes = {index['name'] for index in inspector.get_indexes('professional_service')}
    if op.f('ix_professional_service_veterinario_id') in existing_indexes:
        op.drop_index(op.f('ix_professional_service_veterinario_id'), table_name='professional_service')
    if op.f('ix_professional_service_active') in existing_indexes:
        op.drop_index(op.f('ix_professional_service_active'), table_name='professional_service')
    op.drop_table('professional_service')
