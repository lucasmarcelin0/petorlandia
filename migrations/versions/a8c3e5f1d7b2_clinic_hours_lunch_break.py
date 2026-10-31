"""horários da clínica: intervalo (almoço) opcional

Revision ID: a8c3e5f1d7b2
Revises: c5e1a7d3f9b4
Create Date: 2026-10-30 20:00:00.000000

- ``clinic_hours.intervalo_inicio`` / ``intervalo_fim``: pausa no meio do dia.
  Colunas novas e opcionais: os horários já cadastrados continuam iguais.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a8c3e5f1d7b2'
down_revision = 'c5e1a7d3f9b4'
branch_labels = None
depends_on = None


def _columns():
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns('clinic_hours')}


def upgrade():
    existing = _columns()
    if 'intervalo_inicio' not in existing:
        op.add_column('clinic_hours', sa.Column('intervalo_inicio', sa.Time(), nullable=True))
    if 'intervalo_fim' not in existing:
        op.add_column('clinic_hours', sa.Column('intervalo_fim', sa.Time(), nullable=True))


def downgrade():
    existing = _columns()
    if 'intervalo_fim' in existing:
        op.drop_column('clinic_hours', 'intervalo_fim')
    if 'intervalo_inicio' in existing:
        op.drop_column('clinic_hours', 'intervalo_inicio')
