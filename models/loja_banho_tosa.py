"""Agenda de banho e tosa da loja: cada sessão agendada, feita ou cancelada.

Sessão de plano mensal consome o pacote do mês; sessão avulsa guarda o
preço cobrado e, quando paga no caixa, a venda correspondente.
"""
from __future__ import annotations

try:
    from extensions import db
except ImportError:  # pragma: no cover
    from ..extensions import db

from time_utils import now_in_brazil


SESSAO_STATUS_LABELS = {
    "agendado": "Agendado",
    "realizado": "Feito",
    "cancelado": "Cancelado",
    "faltou": "Não veio",
}


class GroomingSessao(db.Model):
    __tablename__ = "grooming_sessao"

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(
        db.Integer, db.ForeignKey("casa_de_racao.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id = db.Column(db.Integer, db.ForeignKey("grooming_plan.id", ondelete="SET NULL"), nullable=True)
    subscription_id = db.Column(
        db.Integer, db.ForeignKey("grooming_subscription.id", ondelete="SET NULL"), nullable=True, index=True
    )
    animal_id = db.Column(db.Integer, db.ForeignKey("animal.id", ondelete="CASCADE"), nullable=False, index=True)
    agendado_para = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    status = db.Column(db.String(12), nullable=False, default="agendado", index=True)
    valor = db.Column(db.Numeric(10, 2), nullable=True)
    venda_id = db.Column(db.Integer, db.ForeignKey("loja_venda.id", ondelete="SET NULL"), nullable=True)
    observacao = db.Column(db.String(255), nullable=True)
    realizado_em = db.Column(db.DateTime(timezone=True), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)

    plan = db.relationship("GroomingPlan")
    subscription = db.relationship("GroomingSubscription")
    animal = db.relationship("Animal")
    venda = db.relationship("VendaBalcao")

    @property
    def status_label(self) -> str:
        return SESSAO_STATUS_LABELS.get(self.status, self.status)
