"""Emissão própria de NFC-e pelas lojas (pet shops e casas de ração).

Tabelas novas e independentes do módulo fiscal das clínicas
(``fiscal_emitters``/``fiscal_documents``), que exige ``clinic_id``. Nada
aqui altera as notas das clínicas nem a loja online.

Segredos (certificado A1, senha, CSC e XMLs com CPF do consumidor) ficam
cifrados com chave derivada de ``FISCAL_MASTER_KEY`` + identificador da
loja (``loja-<id>``), no mesmo esquema por clínica já usado no fiscal.
"""
from __future__ import annotations

try:
    from extensions import db
except ImportError:  # pragma: no cover
    from ..extensions import db

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import synonym

from security.crypto import (
    decrypt_bytes_for_clinic,
    decrypt_text_for_clinic,
    encrypt_bytes_for_clinic,
    encrypt_text_for_clinic,
    looks_encrypted_text,
)
from time_utils import now_in_brazil


AMBIENTE_HOMOLOGACAO = "homologacao"
AMBIENTE_PRODUCAO = "producao"

NFCE_STATUS_LABELS = {
    "pendente": "Pendente",
    "autorizada": "Autorizada",
    "rejeitada": "Rejeitada",
    "denegada": "Denegada",
    "cancelada": "Cancelada",
    "erro": "Falha de comunicação",
    "inutilizada": "Número inutilizado",
}


def chave_cripto_loja(casa_de_racao_id: int) -> str:
    """Identificador usado na derivação da chave de cifra da loja."""
    return f"loja-{int(casa_de_racao_id)}"


class LojaFiscalConfig(db.Model):
    __tablename__ = "loja_fiscal_config"

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(
        db.Integer,
        db.ForeignKey("casa_de_racao.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    cnpj = db.Column(db.String(18), nullable=False)
    razao_social = db.Column(db.String(200), nullable=False)
    nome_fantasia = db.Column(db.String(200), nullable=True)
    inscricao_estadual = db.Column(db.String(30), nullable=False)
    # 1 = Simples Nacional; 4 = Simples Nacional - MEI.
    crt = db.Column(db.String(1), nullable=False, default="1")
    logradouro = db.Column(db.String(120), nullable=False)
    numero = db.Column(db.String(20), nullable=False, default="S/N")
    complemento = db.Column(db.String(60), nullable=True)
    bairro = db.Column(db.String(80), nullable=False)
    codigo_municipio = db.Column(db.String(7), nullable=False, default="3534302")
    municipio = db.Column(db.String(80), nullable=False, default="Orlândia")
    uf = db.Column(db.String(2), nullable=False, default="SP")
    cep = db.Column(db.String(9), nullable=True)
    telefone = db.Column(db.String(20), nullable=True)

    ambiente = db.Column(db.String(12), nullable=False, default=AMBIENTE_HOMOLOGACAO)
    serie = db.Column(db.Integer, nullable=False, default=1)
    ultimo_numero_homologacao = db.Column(db.Integer, nullable=False, default=0)
    ultimo_numero_producao = db.Column(db.Integer, nullable=False, default=0)

    qrcode_versao = db.Column(db.String(1), nullable=False, default="3")
    csc_id = db.Column(db.String(10), nullable=True)
    _csc_token = db.Column("csc_token_encrypted", db.Text, nullable=True)

    csosn_padrao = db.Column(db.String(3), nullable=False, default="102")
    pis_cst = db.Column(db.String(2), nullable=False, default="99")
    cofins_cst = db.Column(db.String(2), nullable=False, default="99")
    percentual_tributos = db.Column(db.Numeric(5, 2), nullable=True)
    mensagem_cupom = db.Column(db.String(500), nullable=True)
    credenciadora_cnpj = db.Column(db.String(18), nullable=True)
    tp_integra = db.Column(db.String(1), nullable=False, default="2")

    certificado_pfx_encrypted = db.Column(db.LargeBinary, nullable=True)
    _certificado_senha = db.Column("certificado_senha_encrypted", db.Text, nullable=True)
    certificado_validade = db.Column(db.DateTime(timezone=True), nullable=True)
    certificado_cnpj = db.Column(db.String(14), nullable=True)
    certificado_fingerprint = db.Column(db.String(64), nullable=True)

    # Liga a emissão no caixa da loja. Desligado, nada muda para a loja.
    ativo = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    updated_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, onupdate=now_in_brazil)

    casa_de_racao = db.relationship(
        "CasaDeRacao",
        backref=db.backref("fiscal_config", uselist=False, cascade="all, delete-orphan"),
    )

    @property
    def em_producao(self) -> bool:
        return self.ambiente == AMBIENTE_PRODUCAO

    @property
    def tp_amb(self) -> str:
        return "1" if self.em_producao else "2"

    @property
    def tem_certificado(self) -> bool:
        return bool(self.certificado_pfx_encrypted and self._certificado_senha)

    @property
    def _crypto_id(self) -> str:
        return chave_cripto_loja(self.casa_de_racao_id)

    def definir_certificado(self, pfx_bytes: bytes, senha: str) -> None:
        self.certificado_pfx_encrypted = encrypt_bytes_for_clinic(self._crypto_id, pfx_bytes)
        self._certificado_senha = encrypt_text_for_clinic(self._crypto_id, senha)

    def certificado_pfx(self) -> bytes | None:
        if not self.certificado_pfx_encrypted:
            return None
        return decrypt_bytes_for_clinic(self._crypto_id, self.certificado_pfx_encrypted)

    def certificado_senha(self) -> str | None:
        if not self._certificado_senha:
            return None
        return decrypt_text_for_clinic(self._crypto_id, self._certificado_senha)

    def definir_csc(self, csc_id: str | None, token: str | None) -> None:
        self.csc_id = (csc_id or "").strip() or None
        token = (token or "").strip()
        self._csc_token = encrypt_text_for_clinic(self._crypto_id, token) if token else None

    def csc_token(self) -> str | None:
        if not self._csc_token:
            return None
        return decrypt_text_for_clinic(self._crypto_id, self._csc_token)


class NfceDocumento(db.Model):
    __tablename__ = "nfce_documento"
    __table_args__ = (
        db.UniqueConstraint("config_id", "ambiente", "serie", "numero", name="uq_nfce_documento_numero"),
    )

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(
        db.Integer,
        db.ForeignKey("casa_de_racao.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    config_id = db.Column(
        db.Integer,
        db.ForeignKey("loja_fiscal_config.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "teste" (nota de homologação) ou "venda_balcao".
    origem = db.Column(db.String(20), nullable=False, default="teste")
    origem_id = db.Column(db.Integer, nullable=True, index=True)
    ambiente = db.Column(db.String(12), nullable=False)
    serie = db.Column(db.Integer, nullable=False)
    numero = db.Column(db.Integer, nullable=False)
    chave = db.Column(db.String(44), nullable=True, unique=True)
    tp_emis = db.Column(db.String(1), nullable=False, default="1")
    dh_emi = db.Column(db.String(25), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pendente", index=True)
    c_stat = db.Column(db.String(5), nullable=True)
    x_motivo = db.Column(db.String(255), nullable=True)
    protocolo = db.Column(db.String(20), nullable=True)
    dh_recbto = db.Column(db.String(25), nullable=True)
    valor_total = db.Column(db.Numeric(12, 2), nullable=True)
    # Itens e pagamentos para reimprimir o cupom (sem CPF do consumidor).
    payload_json = db.Column(db.JSON, nullable=True)
    qrcode = db.Column(db.Text, nullable=True)
    url_chave = db.Column(db.String(100), nullable=True)
    _xml_assinado = db.Column("xml_assinado", db.Text, nullable=True)
    _xml_autorizado = db.Column("xml_autorizado", db.Text, nullable=True)
    # procEventoNFe do cancelamento (evento assinado + retorno), para o contador.
    _xml_cancelamento = db.Column("xml_cancelamento", db.Text, nullable=True)
    cancel_protocolo = db.Column(db.String(20), nullable=True)
    cancel_motivo = db.Column(db.String(255), nullable=True)
    cancelada_em = db.Column(db.DateTime(timezone=True), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)
    updated_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, onupdate=now_in_brazil)

    config = db.relationship("LojaFiscalConfig", backref=db.backref("documentos", lazy="dynamic"))
    casa_de_racao = db.relationship("CasaDeRacao")

    @property
    def status_label(self) -> str:
        return NFCE_STATUS_LABELS.get(self.status, self.status)

    @property
    def autorizada(self) -> bool:
        return self.status == "autorizada"

    def _decrypt(self, blob: str | None) -> str | None:
        if not blob:
            return blob
        try:
            return decrypt_text_for_clinic(chave_cripto_loja(self.casa_de_racao_id), blob)
        except InvalidToken:
            return blob

    def _encrypt(self, value: str | None) -> str | None:
        if not value or looks_encrypted_text(value):
            return value
        if not self.casa_de_racao_id:
            raise ValueError("casa_de_racao_id deve estar definido antes de guardar o XML.")
        return encrypt_text_for_clinic(chave_cripto_loja(self.casa_de_racao_id), value)

    def _get_xml_assinado(self):
        return self._decrypt(self._xml_assinado)

    def _set_xml_assinado(self, value):
        self._xml_assinado = self._encrypt(value)

    xml_assinado = synonym("_xml_assinado", descriptor=property(_get_xml_assinado, _set_xml_assinado))

    def _get_xml_autorizado(self):
        return self._decrypt(self._xml_autorizado)

    def _set_xml_autorizado(self, value):
        self._xml_autorizado = self._encrypt(value)

    xml_autorizado = synonym("_xml_autorizado", descriptor=property(_get_xml_autorizado, _set_xml_autorizado))

    def _get_xml_cancelamento(self):
        return self._decrypt(self._xml_cancelamento)

    def _set_xml_cancelamento(self, value):
        self._xml_cancelamento = self._encrypt(value)

    xml_cancelamento = synonym(
        "_xml_cancelamento", descriptor=property(_get_xml_cancelamento, _set_xml_cancelamento)
    )


class NfceEvento(db.Model):
    """Histórico de cada conversa com a SEFAZ (XMLs já mascarados)."""

    __tablename__ = "nfce_evento"

    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(
        db.Integer,
        db.ForeignKey("loja_fiscal_config.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    documento_id = db.Column(
        db.Integer,
        db.ForeignKey("nfce_documento.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    tipo = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(20), nullable=True)
    c_stat = db.Column(db.String(5), nullable=True)
    x_motivo = db.Column(db.String(255), nullable=True)
    protocolo = db.Column(db.String(20), nullable=True)
    detalhe = db.Column(db.String(255), nullable=True)
    request_xml = db.Column(db.Text, nullable=True)
    response_xml = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil)

    documento = db.relationship("NfceDocumento", backref=db.backref("eventos", lazy="dynamic"))
