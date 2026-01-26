"""add clinica nfse fields

Revision ID: 7fa1e39ece61
Revises: bcafa8e99f34, 9b2f6fd0f6b2
Create Date: 2026-01-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7fa1e39ece61'
down_revision = ('bcafa8e99f34', '9b2f6fd0f6b2')
branch_labels = None
depends_on = None


CLINICA_COLUMNS = [
    ('inscricao_municipal', sa.String(length=40)),
    ('inscricao_estadual', sa.String(length=40)),
    ('regime_tributario', sa.String(length=60)),
    ('cnae', sa.String(length=20)),
    ('codigo_servico', sa.String(length=30)),
    ('aliquota_iss', sa.Numeric(5, 2)),
    ('aliquota_pis', sa.Numeric(5, 2)),
    ('aliquota_cofins', sa.Numeric(5, 2)),
    ('aliquota_csll', sa.Numeric(5, 2)),
    ('aliquota_ir', sa.Numeric(5, 2)),
    ('municipio_nfse', sa.String(length=60)),
    ('nfse_username', sa.String(length=120)),
    ('nfse_password', sa.String(length=120)),
    ('nfse_cert_path', sa.String(length=200)),
    ('nfse_cert_password', sa.String(length=120)),
    ('nfse_token', sa.String(length=200)),
]



def _missing_columns(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column['name'] for column in inspector.get_columns(table_name)}
    return [column for column in CLINICA_COLUMNS if column[0] not in existing]


def upgrade():
    missing = _missing_columns('clinica')
    if not missing:
        return
    with op.batch_alter_table('clinica', schema=None) as batch_op:
        for name, column_type in missing:
            batch_op.add_column(sa.Column(name, column_type))


def downgrade():
    missing = _missing_columns('clinica')
    columns_to_drop = [column for column in CLINICA_COLUMNS if column not in missing]
    if not columns_to_drop:
        return
    with op.batch_alter_table('clinica', schema=None) as batch_op:
        for name, _column_type in reversed(columns_to_drop):
            batch_op.drop_column(name)
