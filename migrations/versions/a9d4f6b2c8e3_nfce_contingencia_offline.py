"""loja: NFC-e em contingência off-line (tpEmis=9)

Revision ID: a9d4f6b2c8e3
Revises: f7c3a9d5e2b8
Create Date: 2026-10-31 23:00:00.000000

Duas colunas opcionais: a opção da loja (desligada) e o vínculo da nota em
contingência com a nota normal que ficou sem resposta.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a9d4f6b2c8e3'
down_revision = 'f7c3a9d5e2b8'
branch_labels = None
depends_on = None


def _columns(table):
    return {col['name'] for col in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if 'contingencia_automatica' not in _columns('loja_fiscal_config'):
        op.add_column(
            'loja_fiscal_config',
            sa.Column('contingencia_automatica', sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if 'substitui_id' not in _columns('nfce_documento'):
        op.add_column('nfce_documento', sa.Column('substitui_id', sa.Integer(), nullable=True))
        if op.get_bind().dialect.name != 'sqlite':
            op.create_foreign_key(
                'fk_nfce_documento_substitui_id',
                'nfce_documento',
                'nfce_documento',
                ['substitui_id'],
                ['id'],
                ondelete='SET NULL',
            )


def downgrade():
    if 'substitui_id' in _columns('nfce_documento'):
        if op.get_bind().dialect.name != 'sqlite':
            op.drop_constraint('fk_nfce_documento_substitui_id', 'nfce_documento', type_='foreignkey')
        op.drop_column('nfce_documento', 'substitui_id')
    if 'contingencia_automatica' in _columns('loja_fiscal_config'):
        op.drop_column('loja_fiscal_config', 'contingencia_automatica')
