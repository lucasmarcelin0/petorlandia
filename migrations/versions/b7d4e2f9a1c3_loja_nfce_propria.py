"""loja: emissão própria de NFC-e (configuração fiscal, notas e eventos)

Revision ID: b7d4e2f9a1c3
Revises: a8c3e5f1d7b2
Create Date: 2026-10-31 13:00:00.000000

Somente tabelas novas. O fiscal das clínicas (fiscal_*) e a loja online
não mudam. Cada loja só emite depois de configurar e ligar a emissão.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b7d4e2f9a1c3'
down_revision = 'a8c3e5f1d7b2'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    existing = _tables()

    if 'loja_fiscal_config' not in existing:
        op.create_table(
            'loja_fiscal_config',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
            sa.Column('cnpj', sa.String(length=18), nullable=False),
            sa.Column('razao_social', sa.String(length=200), nullable=False),
            sa.Column('nome_fantasia', sa.String(length=200), nullable=True),
            sa.Column('inscricao_estadual', sa.String(length=30), nullable=False),
            sa.Column('crt', sa.String(length=1), nullable=False, server_default='1'),
            sa.Column('logradouro', sa.String(length=120), nullable=False),
            sa.Column('numero', sa.String(length=20), nullable=False, server_default='S/N'),
            sa.Column('complemento', sa.String(length=60), nullable=True),
            sa.Column('bairro', sa.String(length=80), nullable=False),
            sa.Column('codigo_municipio', sa.String(length=7), nullable=False, server_default='3534302'),
            sa.Column('municipio', sa.String(length=80), nullable=False, server_default='Orlândia'),
            sa.Column('uf', sa.String(length=2), nullable=False, server_default='SP'),
            sa.Column('cep', sa.String(length=9), nullable=True),
            sa.Column('telefone', sa.String(length=20), nullable=True),
            sa.Column('ambiente', sa.String(length=12), nullable=False, server_default='homologacao'),
            sa.Column('serie', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('ultimo_numero_homologacao', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('ultimo_numero_producao', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('qrcode_versao', sa.String(length=1), nullable=False, server_default='3'),
            sa.Column('csc_id', sa.String(length=10), nullable=True),
            sa.Column('csc_token_encrypted', sa.Text(), nullable=True),
            sa.Column('csosn_padrao', sa.String(length=3), nullable=False, server_default='102'),
            sa.Column('pis_cst', sa.String(length=2), nullable=False, server_default='99'),
            sa.Column('cofins_cst', sa.String(length=2), nullable=False, server_default='99'),
            sa.Column('percentual_tributos', sa.Numeric(precision=5, scale=2), nullable=True),
            sa.Column('mensagem_cupom', sa.String(length=500), nullable=True),
            sa.Column('credenciadora_cnpj', sa.String(length=18), nullable=True),
            sa.Column('tp_integra', sa.String(length=1), nullable=False, server_default='2'),
            sa.Column('certificado_pfx_encrypted', sa.LargeBinary(), nullable=True),
            sa.Column('certificado_senha_encrypted', sa.Text(), nullable=True),
            sa.Column('certificado_validade', sa.DateTime(timezone=True), nullable=True),
            sa.Column('certificado_cnpj', sa.String(length=14), nullable=True),
            sa.Column('certificado_fingerprint', sa.String(length=64), nullable=True),
            sa.Column('ativo', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            op.f('ix_loja_fiscal_config_casa_de_racao_id'),
            'loja_fiscal_config',
            ['casa_de_racao_id'],
            unique=True,
        )

    if 'nfce_documento' not in existing:
        op.create_table(
            'nfce_documento',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
            sa.Column('config_id', sa.Integer(), nullable=False),
            sa.Column('origem', sa.String(length=20), nullable=False, server_default='teste'),
            sa.Column('origem_id', sa.Integer(), nullable=True),
            sa.Column('ambiente', sa.String(length=12), nullable=False),
            sa.Column('serie', sa.Integer(), nullable=False),
            sa.Column('numero', sa.Integer(), nullable=False),
            sa.Column('chave', sa.String(length=44), nullable=True),
            sa.Column('tp_emis', sa.String(length=1), nullable=False, server_default='1'),
            sa.Column('dh_emi', sa.String(length=25), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='pendente'),
            sa.Column('c_stat', sa.String(length=5), nullable=True),
            sa.Column('x_motivo', sa.String(length=255), nullable=True),
            sa.Column('protocolo', sa.String(length=20), nullable=True),
            sa.Column('dh_recbto', sa.String(length=25), nullable=True),
            sa.Column('valor_total', sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column('payload_json', sa.JSON(), nullable=True),
            sa.Column('qrcode', sa.Text(), nullable=True),
            sa.Column('url_chave', sa.String(length=100), nullable=True),
            sa.Column('xml_assinado', sa.Text(), nullable=True),
            sa.Column('xml_autorizado', sa.Text(), nullable=True),
            sa.Column('xml_cancelamento', sa.Text(), nullable=True),
            sa.Column('cancel_protocolo', sa.String(length=20), nullable=True),
            sa.Column('cancel_motivo', sa.String(length=255), nullable=True),
            sa.Column('cancelada_em', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_by_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['config_id'], ['loja_fiscal_config.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('chave'),
            sa.UniqueConstraint('config_id', 'ambiente', 'serie', 'numero', name='uq_nfce_documento_numero'),
        )
        op.create_index(op.f('ix_nfce_documento_casa_de_racao_id'), 'nfce_documento', ['casa_de_racao_id'], unique=False)
        op.create_index(op.f('ix_nfce_documento_config_id'), 'nfce_documento', ['config_id'], unique=False)
        op.create_index(op.f('ix_nfce_documento_origem_id'), 'nfce_documento', ['origem_id'], unique=False)
        op.create_index(op.f('ix_nfce_documento_status'), 'nfce_documento', ['status'], unique=False)

    if 'nfce_evento' not in existing:
        op.create_table(
            'nfce_evento',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('config_id', sa.Integer(), nullable=False),
            sa.Column('documento_id', sa.Integer(), nullable=True),
            sa.Column('tipo', sa.String(length=30), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=True),
            sa.Column('c_stat', sa.String(length=5), nullable=True),
            sa.Column('x_motivo', sa.String(length=255), nullable=True),
            sa.Column('protocolo', sa.String(length=20), nullable=True),
            sa.Column('detalhe', sa.String(length=255), nullable=True),
            sa.Column('request_xml', sa.Text(), nullable=True),
            sa.Column('response_xml', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['config_id'], ['loja_fiscal_config.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['documento_id'], ['nfce_documento.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_nfce_evento_config_id'), 'nfce_evento', ['config_id'], unique=False)
        op.create_index(op.f('ix_nfce_evento_documento_id'), 'nfce_evento', ['documento_id'], unique=False)


def downgrade():
    existing = _tables()
    if 'nfce_evento' in existing:
        op.drop_index(op.f('ix_nfce_evento_documento_id'), table_name='nfce_evento')
        op.drop_index(op.f('ix_nfce_evento_config_id'), table_name='nfce_evento')
        op.drop_table('nfce_evento')
    if 'nfce_documento' in existing:
        op.drop_index(op.f('ix_nfce_documento_status'), table_name='nfce_documento')
        op.drop_index(op.f('ix_nfce_documento_origem_id'), table_name='nfce_documento')
        op.drop_index(op.f('ix_nfce_documento_config_id'), table_name='nfce_documento')
        op.drop_index(op.f('ix_nfce_documento_casa_de_racao_id'), table_name='nfce_documento')
        op.drop_table('nfce_documento')
    if 'loja_fiscal_config' in existing:
        op.drop_index(op.f('ix_loja_fiscal_config_casa_de_racao_id'), table_name='loja_fiscal_config')
        op.drop_table('loja_fiscal_config')
