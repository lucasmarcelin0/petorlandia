"""Notas de compra que a SEFAZ distribui para o CNPJ da loja (DF-e)."""
from __future__ import annotations

try:
    from extensions import db
except ImportError:  # pragma: no cover
    from ..extensions import db

from time_utils import now_in_brazil


DFE_SITUACAO_LABELS = {"1": "Autorizada", "2": "Denegada", "3": "Cancelada pelo emitente"}


class LojaDfeControle(db.Model):
    """Onde a loja parou na fila da SEFAZ (NSU) e quando pode consultar de novo."""

    __tablename__ = "loja_dfe_controle"

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(
        db.Integer, db.ForeignKey("casa_de_racao.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    ult_nsu = db.Column(db.String(15), nullable=False, default="000000000000000")
    max_nsu = db.Column(db.String(15), nullable=True)
    ultima_consulta = db.Column(db.DateTime(timezone=True), nullable=True)
    proxima_consulta = db.Column(db.DateTime(timezone=True), nullable=True)
    ultimo_c_stat = db.Column(db.String(4), nullable=True)
    ultimo_x_motivo = db.Column(db.String(255), nullable=True)
    # Dar ciência e baixar o XML sozinho, de hora em hora.
    ciencia_automatica = db.Column(db.Boolean, nullable=False, default=False)


class LojaDfeDocumento(db.Model):
    """Uma NF-e emitida contra a loja: resumo e, depois da ciência, o XML."""

    __tablename__ = "loja_dfe_documento"
    __table_args__ = (
        db.UniqueConstraint("casa_de_racao_id", "chave", name="uq_loja_dfe_documento_chave"),
    )

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(
        db.Integer, db.ForeignKey("casa_de_racao.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chave = db.Column(db.String(44), nullable=False)
    nsu = db.Column(db.String(15), nullable=True)
    emitente_cnpj = db.Column(db.String(14), nullable=True)
    emitente_nome = db.Column(db.String(160), nullable=True)
    dh_emi = db.Column(db.String(32), nullable=True)
    valor = db.Column(db.Numeric(12, 2), nullable=True)
    situacao = db.Column(db.String(1), nullable=True)
    protocolo = db.Column(db.String(20), nullable=True)
    xml_completo = db.Column(db.Text, nullable=True)
    ciencia_em = db.Column(db.DateTime(timezone=True), nullable=True)
    entrada_id = db.Column(
        db.Integer, db.ForeignKey("loja_entrada_nota.id", ondelete="SET NULL"), nullable=True
    )
    erro = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, onupdate=now_in_brazil)

    entrada = db.relationship("LojaEntradaNota")

    @property
    def situacao_label(self) -> str:
        return DFE_SITUACAO_LABELS.get(self.situacao or "", "—")
