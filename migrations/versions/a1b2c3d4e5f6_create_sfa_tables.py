"""create sfa tables

Revision ID: a1b2c3d4e5f6
Revises: f2a1c3d4e5f6
Create Date: 2026-03-17 00:00:00.000000

Cria as tabelas do módulo SFA — Síndromes Febris Agudas de Orlândia:
  - sfa_paciente
  - sfa_resposta_t0
  - sfa_resposta_t10
  - sfa_resposta_t30
  - sfa_sinan_log
  - sfa_auditoria
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f2a1c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = inspector.get_table_names()

    # ------------------------------------------------------------------
    # sfa_paciente
    # ------------------------------------------------------------------
    if "sfa_paciente" not in existing:
        op.create_table(
            "sfa_paciente",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("id_estudo", sa.String(30), nullable=False),
            sa.Column("ficha_sinan", sa.String(50), nullable=True),
            sa.Column("nome", sa.String(200), nullable=True),
            sa.Column("data_nascimento", sa.String(20), nullable=True),
            sa.Column("telefone", sa.String(25), nullable=True),
            sa.Column("bairro", sa.String(120), nullable=True),
            sa.Column("endereco", sa.String(300), nullable=True),
            sa.Column("grupo", sa.String(30), nullable=True, server_default="PENDENTE_REVISAO"),
            sa.Column("status_t0", sa.String(30), nullable=True),
            sa.Column("status_t10", sa.String(30), nullable=True),
            sa.Column("status_t30", sa.String(30), nullable=True),
            sa.Column("status_geral", sa.String(30), nullable=True),
            sa.Column("data_t0", sa.String(15), nullable=True),
            sa.Column("data_t10", sa.String(15), nullable=True),
            sa.Column("data_t30", sa.String(15), nullable=True),
            sa.Column("fase_atual", sa.String(60), nullable=True),
            sa.Column("proxima_fase", sa.String(60), nullable=True),
            sa.Column("proxima_acao", sa.String(60), nullable=True),
            sa.Column("prioridade_operacional", sa.String(10), nullable=True),
            sa.Column("dias_para_acao", sa.Integer(), nullable=True),
            sa.Column("data_proxima_acao", sa.String(15), nullable=True),
            sa.Column("status_whatsapp", sa.String(30), nullable=True, server_default="NAO_ENVIADO"),
            sa.Column("data_ultimo_whatsapp", sa.String(15), nullable=True),
            sa.Column("retorno_contato", sa.String(30), nullable=True, server_default="PENDENTE"),
            sa.Column("observacao_operacional", sa.Text(), nullable=True),
            sa.Column("token_acesso", sa.String(72), nullable=True),
            sa.Column("timestamp_cadastro", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("id_estudo"),
            sa.UniqueConstraint("token_acesso"),
        )
        op.create_index("ix_sfa_paciente_id_estudo", "sfa_paciente", ["id_estudo"])
        op.create_index("ix_sfa_paciente_ficha_sinan", "sfa_paciente", ["ficha_sinan"])
        op.create_index("ix_sfa_paciente_token_acesso", "sfa_paciente", ["token_acesso"])

    # ------------------------------------------------------------------
    # sfa_resposta_t0
    # ------------------------------------------------------------------
    if "sfa_resposta_t0" not in existing:
        op.create_table(
            "sfa_resposta_t0",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("id_estudo", sa.String(30), sa.ForeignKey("sfa_paciente.id_estudo"), nullable=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("nome", sa.String(200), nullable=True),
            sa.Column("data_nascimento", sa.String(20), nullable=True),
            sa.Column("tipo_residencia", sa.String(60), nullable=True),
            sa.Column("data_inicio_sintomas", sa.String(15), nullable=True),
            sa.Column("dias_incap", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("internacao", sa.String(80), nullable=True),
            sa.Column("custo_total", sa.Numeric(10, 2), nullable=True, server_default="0"),
            sa.Column("ausencia_familiar", sa.String(80), nullable=True),
            sa.Column("dados_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sfa_resposta_t0_id_estudo", "sfa_resposta_t0", ["id_estudo"])

    # ------------------------------------------------------------------
    # sfa_resposta_t10
    # ------------------------------------------------------------------
    if "sfa_resposta_t10" not in existing:
        op.create_table(
            "sfa_resposta_t10",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("id_estudo", sa.String(30), sa.ForeignKey("sfa_paciente.id_estudo"), nullable=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dias_incap_novos", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("custo_remedios", sa.Numeric(10, 2), nullable=True, server_default="0"),
            sa.Column("custo_consultas", sa.Numeric(10, 2), nullable=True, server_default="0"),
            sa.Column("custo_transporte", sa.Numeric(10, 2), nullable=True, server_default="0"),
            sa.Column("custo_outros", sa.Numeric(10, 2), nullable=True, server_default="0"),
            sa.Column("dados_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sfa_resposta_t10_id_estudo", "sfa_resposta_t10", ["id_estudo"])

    # ------------------------------------------------------------------
    # sfa_resposta_t30
    # ------------------------------------------------------------------
    if "sfa_resposta_t30" not in existing:
        op.create_table(
            "sfa_resposta_t30",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("id_estudo", sa.String(30), sa.ForeignKey("sfa_paciente.id_estudo"), nullable=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dias_incap_novos", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("custo_remedios", sa.Numeric(10, 2), nullable=True, server_default="0"),
            sa.Column("custo_consultas", sa.Numeric(10, 2), nullable=True, server_default="0"),
            sa.Column("custo_transporte", sa.Numeric(10, 2), nullable=True, server_default="0"),
            sa.Column("custo_outros", sa.Numeric(10, 2), nullable=True, server_default="0"),
            sa.Column("dados_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sfa_resposta_t30_id_estudo", "sfa_resposta_t30", ["id_estudo"])

    # ------------------------------------------------------------------
    # sfa_sinan_log
    # ------------------------------------------------------------------
    if "sfa_sinan_log" not in existing:
        op.create_table(
            "sfa_sinan_log",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("chave_dedup", sa.String(60), nullable=False),
            sa.Column("ficha_sinan", sa.String(50), nullable=True),
            sa.Column("n_caso", sa.String(20), nullable=True),
            sa.Column("nome", sa.String(200), nullable=True),
            sa.Column("telefone", sa.String(25), nullable=True),
            sa.Column("bairro", sa.String(120), nullable=True),
            sa.Column("data_notificacao", sa.String(20), nullable=True),
            sa.Column("data_inicio_sintomas", sa.String(20), nullable=True),
            sa.Column("tipo_exame", sa.String(120), nullable=True),
            sa.Column("resultado", sa.String(120), nullable=True),
            sa.Column("grupo", sa.String(20), nullable=True),
            sa.Column("id_estudo_vinculado", sa.String(30), nullable=True),
            sa.Column("timestamp_importacao", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("chave_dedup"),
        )
        op.create_index("ix_sfa_sinan_log_chave_dedup", "sfa_sinan_log", ["chave_dedup"])

    # ------------------------------------------------------------------
    # sfa_auditoria
    # ------------------------------------------------------------------
    if "sfa_auditoria" not in existing:
        op.create_table(
            "sfa_auditoria",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("nivel", sa.String(10), nullable=True),
            sa.Column("categoria", sa.String(60), nullable=True),
            sa.Column("funcao", sa.String(60), nullable=True),
            sa.Column("id_estudo", sa.String(30), nullable=True),
            sa.Column("mensagem", sa.Text(), nullable=True),
            sa.Column("detalhes_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sfa_auditoria_timestamp", "sfa_auditoria", ["timestamp"])


def downgrade():
    op.drop_table("sfa_auditoria")
    op.drop_table("sfa_sinan_log")
    op.drop_table("sfa_resposta_t30")
    op.drop_table("sfa_resposta_t10")
    op.drop_table("sfa_resposta_t0")
    op.drop_table("sfa_paciente")
