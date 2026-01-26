"""add nfse tables"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9b2f6fd0f6b2'
down_revision = 'e1b9a8e9d0f1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'nfse_issues' not in inspector.get_table_names():
        op.create_table(
            'nfse_issues',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('clinica_id', sa.Integer(), sa.ForeignKey('clinica.id'), nullable=False),
            sa.Column('internal_identifier', sa.String(length=80), nullable=True),
            sa.Column('rps', sa.String(length=50), nullable=True),
            sa.Column('numero_nfse', sa.String(length=50), nullable=True),
            sa.Column('serie', sa.String(length=50), nullable=True),
            sa.Column('protocolo', sa.String(length=80), nullable=True),
            sa.Column('status', sa.String(length=40), nullable=True),
            sa.Column('data_emissao', sa.DateTime(timezone=True), nullable=True),
            sa.Column('valor_total', sa.Numeric(12, 2), nullable=True),
            sa.Column('valor_iss', sa.Numeric(12, 2), nullable=True),
            sa.Column('tomador', sa.Text(), nullable=True),
            sa.Column('prestador', sa.Text(), nullable=True),
            sa.Column('xml_envio', sa.Text(), nullable=True),
            sa.Column('xml_retorno', sa.Text(), nullable=True),
            sa.Column('cancelada_em', sa.DateTime(timezone=True), nullable=True),
            sa.Column('cancelamento_motivo', sa.String(length=255), nullable=True),
            sa.Column('cancelamento_protocolo', sa.String(length=80), nullable=True),
            sa.Column('substituida_por_nfse', sa.String(length=50), nullable=True),
            sa.Column('substitui_nfse', sa.String(length=50), nullable=True),
            sa.Column('erro_codigo', sa.String(length=50), nullable=True),
            sa.Column('erro_mensagem', sa.Text(), nullable=True),
            sa.Column('erro_detalhes', sa.Text(), nullable=True),
            sa.Column('erro_em', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_nfse_issues_clinica_id', 'nfse_issues', ['clinica_id'])

    if 'nfse_events' not in inspector.get_table_names():
        op.create_table(
            'nfse_events',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('clinica_id', sa.Integer(), sa.ForeignKey('clinica.id'), nullable=False),
            sa.Column('nfse_issue_id', sa.Integer(), sa.ForeignKey('nfse_issues.id'), nullable=False),
            sa.Column('event_type', sa.String(length=50), nullable=False),
            sa.Column('status', sa.String(length=40), nullable=True),
            sa.Column('protocolo', sa.String(length=80), nullable=True),
            sa.Column('descricao', sa.Text(), nullable=True),
            sa.Column('payload', sa.Text(), nullable=True),
            sa.Column('data_evento', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_nfse_events_clinica_id', 'nfse_events', ['clinica_id'])
        op.create_index('ix_nfse_events_nfse_issue_id', 'nfse_events', ['nfse_issue_id'])

    if 'nfse_xmls' not in inspector.get_table_names():
        op.create_table(
            'nfse_xmls',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('clinica_id', sa.Integer(), sa.ForeignKey('clinica.id'), nullable=False),
            sa.Column('nfse_issue_id', sa.Integer(), sa.ForeignKey('nfse_issues.id'), nullable=False),
            sa.Column('rps', sa.String(length=50), nullable=True),
            sa.Column('numero_nfse', sa.String(length=50), nullable=True),
            sa.Column('serie', sa.String(length=50), nullable=True),
            sa.Column('tipo', sa.String(length=30), nullable=False),
            sa.Column('protocolo', sa.String(length=80), nullable=True),
            sa.Column('xml', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_nfse_xmls_clinica_id', 'nfse_xmls', ['clinica_id'])
        op.create_index('ix_nfse_xmls_nfse_issue_id', 'nfse_xmls', ['nfse_issue_id'])


def downgrade():
    op.drop_index('ix_nfse_xmls_nfse_issue_id', table_name='nfse_xmls')
    op.drop_index('ix_nfse_xmls_clinica_id', table_name='nfse_xmls')
    op.drop_table('nfse_xmls')

    op.drop_index('ix_nfse_events_nfse_issue_id', table_name='nfse_events')
    op.drop_index('ix_nfse_events_clinica_id', table_name='nfse_events')
    op.drop_table('nfse_events')

    op.drop_index('ix_nfse_issues_clinica_id', table_name='nfse_issues')
    op.drop_table('nfse_issues')
