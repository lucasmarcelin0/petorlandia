"""Modelos SQLAlchemy para o módulo SFA — Síndromes Febris Agudas de Orlândia."""
from __future__ import annotations

import enum
import uuid

from extensions import db
from sqlalchemy import Text, UniqueConstraint
from time_utils import utcnow


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SfaGrupo(str, enum.Enum):
    A = "A"
    B = "B"
    PENDENTE_REVISAO = "PENDENTE_REVISAO"


class SfaStatusGeral(str, enum.Enum):
    SINAN_NOTIFICADO = "SINAN_Notificado"
    EM_ANDAMENTO = "Em_Andamento"
    COMPLETO = "COMPLETO"
    PERDA_SEGUIMENTO = "PERDA_SEGUIMENTO"


class SfaStatusEtapa(str, enum.Enum):
    AGUARDANDO = "Aguardando"
    COMPLETO = "Completo"
    ATRASADO = "ATRASADO"
    SINAN_AGUARDANDO = "SINAN_Aguardando_T0"
    T0_COMPLETO = "T0_Completo"
    T10_COMPLETO = "T10_Completo"
    T30_COMPLETO = "T30_Completo"


class SfaPrioridade(str, enum.Enum):
    ALTA = "Alta"
    MEDIA = "Media"
    BAIXA = "Baixa"


class SfaStatusWhatsapp(str, enum.Enum):
    NAO_ENVIADO = "NAO_ENVIADO"
    ENVIADO = "ENVIADO"
    RESPONDIDO = "RESPONDIDO"
    SEM_WHATSAPP = "SEM_WHATSAPP"
    NAO_SE_APLICA = "NAO_SE_APLICA"


class SfaRetornoContato(str, enum.Enum):
    PENDENTE = "PENDENTE"
    ACEITOU = "ACEITOU"
    RECUSOU = "RECUSOU"
    SEM_RETORNO = "SEM_RETORNO"
    NAO_LOCALIZADO = "NAO_LOCALIZADO"


# ---------------------------------------------------------------------------
# Paciente (registro principal — espelha a aba Cadastro do GAS)
# ---------------------------------------------------------------------------

class SfaPaciente(db.Model):
    __tablename__ = "sfa_paciente"

    id = db.Column(db.Integer, primary_key=True)
    id_estudo = db.Column(db.String(30), unique=True, nullable=False, index=True)
    ficha_sinan = db.Column(db.String(50), index=True)

    # Identificação
    nome = db.Column(db.String(200))
    data_nascimento = db.Column(db.String(20))
    telefone = db.Column(db.String(25))
    bairro = db.Column(db.String(120))
    endereco = db.Column(db.String(300))

    # Classificação
    grupo = db.Column(db.String(30), default=SfaGrupo.PENDENTE_REVISAO.value)

    # Status das etapas
    status_t0 = db.Column(db.String(30), default=SfaStatusEtapa.SINAN_AGUARDANDO.value)
    status_t10 = db.Column(db.String(30))
    status_t30 = db.Column(db.String(30))
    status_geral = db.Column(db.String(30), default=SfaStatusGeral.SINAN_NOTIFICADO.value)

    # Datas de acompanhamento (armazenadas como string DD/MM/YYYY para compatibilidade)
    data_t0 = db.Column(db.String(15))
    data_t10 = db.Column(db.String(15))
    data_t30 = db.Column(db.String(15))

    # Operacional (espelha colunas calculadas da planilha)
    fase_atual = db.Column(db.String(60))
    proxima_fase = db.Column(db.String(60))
    proxima_acao = db.Column(db.String(60))
    prioridade_operacional = db.Column(db.String(10))
    dias_para_acao = db.Column(db.Integer)
    data_proxima_acao = db.Column(db.String(15))

    # Contato WhatsApp
    status_whatsapp = db.Column(db.String(30), default=SfaStatusWhatsapp.NAO_ENVIADO.value)
    data_ultimo_whatsapp = db.Column(db.String(15))
    retorno_contato = db.Column(db.String(30), default=SfaRetornoContato.PENDENTE.value)

    # Notas
    observacao_operacional = db.Column(db.Text)

    # Acesso seguro ao Web App (substitui o token do GAS)
    token_acesso = db.Column(db.String(72), unique=True, index=True)

    # Timestamps
    timestamp_cadastro = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relacionamentos
    resposta_t0 = db.relationship("SfaRespostaT0", backref="paciente", uselist=False,
                                   foreign_keys="SfaRespostaT0.id_estudo",
                                   primaryjoin="SfaPaciente.id_estudo == SfaRespostaT0.id_estudo")
    respostas_t10 = db.relationship("SfaRespostaT10", backref="paciente",
                                     foreign_keys="SfaRespostaT10.id_estudo",
                                     primaryjoin="SfaPaciente.id_estudo == SfaRespostaT10.id_estudo")
    respostas_t30 = db.relationship("SfaRespostaT30", backref="paciente",
                                     foreign_keys="SfaRespostaT30.id_estudo",
                                     primaryjoin="SfaPaciente.id_estudo == SfaRespostaT30.id_estudo")

    def gerar_token(self) -> str:
        """Gera e salva um token único de acesso."""
        self.token_acesso = uuid.uuid4().hex + uuid.uuid4().hex[:8]
        return self.token_acesso

    @property
    def primeiro_nome(self) -> str:
        return (self.nome or "Participante").split()[0]

    def __repr__(self) -> str:
        return f"<SfaPaciente {self.id_estudo} {self.nome}>"


# ---------------------------------------------------------------------------
# Respostas dos formulários (espelham as abas T0_raw, T10_raw, T30_raw)
# ---------------------------------------------------------------------------

class SfaRespostaT0(db.Model):
    __tablename__ = "sfa_resposta_t0"

    id = db.Column(db.Integer, primary_key=True)
    id_estudo = db.Column(db.String(30), db.ForeignKey("sfa_paciente.id_estudo"), index=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=utcnow)

    nome = db.Column(db.String(200))
    data_nascimento = db.Column(db.String(20))
    tipo_residencia = db.Column(db.String(60))
    data_inicio_sintomas = db.Column(db.String(15))

    # Impacto socioeconômico
    dias_incap = db.Column(db.Integer, default=0)
    internacao = db.Column(db.String(80))
    custo_total = db.Column(db.Numeric(10, 2), default=0)
    ausencia_familiar = db.Column(db.String(80))

    # JSON completo da resposta
    dados_json = db.Column(db.Text)


class SfaRespostaT10(db.Model):
    __tablename__ = "sfa_resposta_t10"

    id = db.Column(db.Integer, primary_key=True)
    id_estudo = db.Column(db.String(30), db.ForeignKey("sfa_paciente.id_estudo"), index=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=utcnow)

    dias_incap_novos = db.Column(db.Integer, default=0)
    custo_remedios = db.Column(db.Numeric(10, 2), default=0)
    custo_consultas = db.Column(db.Numeric(10, 2), default=0)
    custo_transporte = db.Column(db.Numeric(10, 2), default=0)
    custo_outros = db.Column(db.Numeric(10, 2), default=0)

    dados_json = db.Column(db.Text)

    @property
    def custo_total(self):
        return (
            (self.custo_remedios or 0)
            + (self.custo_consultas or 0)
            + (self.custo_transporte or 0)
            + (self.custo_outros or 0)
        )


class SfaRespostaT30(db.Model):
    __tablename__ = "sfa_resposta_t30"

    id = db.Column(db.Integer, primary_key=True)
    id_estudo = db.Column(db.String(30), db.ForeignKey("sfa_paciente.id_estudo"), index=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=utcnow)

    dias_incap_novos = db.Column(db.Integer, default=0)
    custo_remedios = db.Column(db.Numeric(10, 2), default=0)
    custo_consultas = db.Column(db.Numeric(10, 2), default=0)
    custo_transporte = db.Column(db.Numeric(10, 2), default=0)
    custo_outros = db.Column(db.Numeric(10, 2), default=0)

    dados_json = db.Column(db.Text)

    @property
    def custo_total(self):
        return (
            (self.custo_remedios or 0)
            + (self.custo_consultas or 0)
            + (self.custo_transporte or 0)
            + (self.custo_outros or 0)
        )


# ---------------------------------------------------------------------------
# Log de importação SINAN (espelha aba SINAN_Importado)
# ---------------------------------------------------------------------------

class SfaSinanLog(db.Model):
    __tablename__ = "sfa_sinan_log"

    id = db.Column(db.Integer, primary_key=True)
    chave_dedup = db.Column(db.String(60), unique=True, nullable=False, index=True)
    ficha_sinan = db.Column(db.String(50))
    n_caso = db.Column(db.String(20))
    nome = db.Column(db.String(200))
    telefone = db.Column(db.String(25))
    bairro = db.Column(db.String(120))
    data_notificacao = db.Column(db.String(20))
    data_inicio_sintomas = db.Column(db.String(20))
    tipo_exame = db.Column(db.String(120))
    resultado = db.Column(db.String(120))
    grupo = db.Column(db.String(20))
    id_estudo_vinculado = db.Column(db.String(30))
    timestamp_importacao = db.Column(db.DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# Auditoria (espelha aba Auditoria do GAS)
# ---------------------------------------------------------------------------

class SfaAuditoria(db.Model):
    __tablename__ = "sfa_auditoria"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)
    nivel = db.Column(db.String(10))    # INFO | WARN | ERROR
    categoria = db.Column(db.String(60))
    funcao = db.Column(db.String(60))
    id_estudo = db.Column(db.String(30))
    mensagem = db.Column(db.Text)
    detalhes_json = db.Column(db.Text)
