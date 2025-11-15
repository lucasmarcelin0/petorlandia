"""backfill plantonista scale data and hours"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from decimal import Decimal, InvalidOperation
from datetime import datetime


revision = '2f8a5b4d1234'
down_revision = '784cfdc924d2'

branch_labels = None
depends_on = None


LEGACY_CANDIDATES = (
    'plantao',
    'plantoes',
    'plantao_escalas',
    'plantao_escala',
    'plantao_agendamentos',
    'plantao_pagamentos',
    'plantonistas',
    'plantonista_pagamentos',
    'plantonista_escalas_tmp',
)

REQUIRED_LEGACY_COLUMNS = {'clinic_id', 'medico_nome', 'turno', 'inicio', 'fim', 'valor_previsto'}
OPTIONAL_LEGACY_COLUMNS = {
    'medico_id',
    'medico_cnpj',
    'status',
    'nota_fiscal_recebida',
    'retencao_validada',
    'observacoes',
    'realizado_em',
    'pj_payment_id',
    'created_at',
    'updated_at',
}


def _ensure_plantao_horas_column(inspector):
    columns = {col['name'] for col in inspector.get_columns('plantonista_escalas')}
    if 'plantao_horas' not in columns:
        op.add_column('plantonista_escalas', sa.Column('plantao_horas', sa.Numeric(5, 2), nullable=True))


def _compute_hours(inicio, fim):
    if not inicio or not fim:
        return None
    total_seconds = (fim - inicio).total_seconds()
    if total_seconds <= 0:
        return None
    try:
        horas = Decimal(str(total_seconds)) / Decimal('3600')
        return horas.quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError):
        return None


def _find_legacy_table(inspector):
    existing_tables = inspector.get_table_names()
    for name in existing_tables:
        if name == 'plantonista_escalas':
            continue
        if not any(candidate in name for candidate in ('plantao', 'plantonista')):
            continue
        columns = {col['name'] for col in inspector.get_columns(name)}
        if REQUIRED_LEGACY_COLUMNS.issubset(columns):
            return name
    return None


def _migrate_legacy_plantoes(bind, inspector):
    legacy_table = _find_legacy_table(inspector)
    if not legacy_table:
        return

    column_names = {col['name'] for col in inspector.get_columns(legacy_table)}
    if not REQUIRED_LEGACY_COLUMNS.issubset(column_names):
        return

    selected_columns = list(REQUIRED_LEGACY_COLUMNS | (OPTIONAL_LEGACY_COLUMNS & column_names))
    selected_columns.sort()
    select_clause = ', '.join(selected_columns)
    rows = bind.execute(sa.text(f"SELECT {select_clause} FROM {legacy_table}")).mappings().all()
    if not rows:
        return

    existing_links = {
        record['pj_payment_id']
        for record in bind.execute(sa.text(
            """
            SELECT DISTINCT pj_payment_id
            FROM plantonista_escalas
            WHERE pj_payment_id IS NOT NULL
        """
        )).mappings()
        if record['pj_payment_id'] is not None
    }

    insert_stmt = sa.text(
        """
        INSERT INTO plantonista_escalas (
            clinic_id,
            medico_id,
            medico_nome,
            medico_cnpj,
            turno,
            inicio,
            fim,
            plantao_horas,
            valor_previsto,
            status,
            nota_fiscal_recebida,
            retencao_validada,
            observacoes,
            realizado_em,
            pj_payment_id,
            created_at,
            updated_at
        ) VALUES (
            :clinic_id,
            :medico_id,
            :medico_nome,
            :medico_cnpj,
            :turno,
            :inicio,
            :fim,
            :plantao_horas,
            :valor_previsto,
            :status,
            :nota_fiscal_recebida,
            :retencao_validada,
            :observacoes,
            :realizado_em,
            :pj_payment_id,
            :created_at,
            :updated_at
        )
        """
    )

    now = datetime.utcnow()
    for row in rows:
        payload = {col: row.get(col) for col in selected_columns}
        payload.setdefault('medico_id', None)
        payload.setdefault('medico_cnpj', None)
        payload.setdefault('status', 'agendado')
        payload.setdefault('nota_fiscal_recebida', False)
        payload.setdefault('retencao_validada', False)
        payload.setdefault('observacoes', None)
        payload.setdefault('realizado_em', None)
        payload.setdefault('created_at', now)
        payload.setdefault('updated_at', now)
        pj_payment_id = payload.get('pj_payment_id')
        if pj_payment_id in existing_links:
            payload['pj_payment_id'] = None
        horas = _compute_hours(payload.get('inicio'), payload.get('fim'))
        payload['plantao_horas'] = horas
        bind.execute(insert_stmt, payload)
        if pj_payment_id and pj_payment_id not in existing_links:
            existing_links.add(pj_payment_id)


def _backfill_hours_and_payments(bind):
    rows = bind.execute(sa.text(
        """
        SELECT id, inicio, fim, pj_payment_id
        FROM plantonista_escalas
    """
    )).mappings().all()

    scale_updates = []
    payment_hours = {}
    payment_ids = set()
    for row in rows:
        horas = _compute_hours(row['inicio'], row['fim'])
        if horas is not None:
            scale_updates.append({'id': row['id'], 'hours': horas})
            if row['pj_payment_id']:
                payment_hours[row['pj_payment_id']] = horas
        if row['pj_payment_id']:
            payment_ids.add(row['pj_payment_id'])

    if scale_updates:
        bind.execute(
            sa.text(
                """
                UPDATE plantonista_escalas
                SET plantao_horas = :hours
                WHERE id = :id
            """
            ),
            scale_updates,
        )

    if payment_hours:
        bind.execute(
            sa.text(
                """
                UPDATE pj_payments
                SET plantao_horas = :hours
                WHERE id = :id
            """
            ),
            [{'id': pid, 'hours': hours} for pid, hours in payment_hours.items()],
        )

    if payment_ids:
        bind.execute(
            sa.text(
                """
                UPDATE pj_payments
                SET tipo_prestador = 'plantonista'
                WHERE id = :id
            """
            ),
            [{'id': pid} for pid in payment_ids],
        )


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ensure_plantao_horas_column(inspector)
    # refresh inspector metadata after schema change
    inspector = inspect(bind)
    _migrate_legacy_plantoes(bind, inspector)
    _backfill_hours_and_payments(bind)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('plantonista_escalas')}
    if 'plantao_horas' in columns:
        op.drop_column('plantonista_escalas', 'plantao_horas')
