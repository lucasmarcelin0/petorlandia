"""Equipe da loja: quem opera o caixa e o dia a dia além do dono.

O dono cadastra o operador e liga ou desliga o acesso quando quiser (ex.:
alguém contratado por uma temporada). Desligar não apaga nada: as vendas,
os ajustes de estoque e o caixa continuam com o nome de quem fez.
"""
from __future__ import annotations

try:
    from extensions import db
except ImportError:  # pragma: no cover
    from ..extensions import db

from time_utils import now_in_brazil


class LojaMembro(db.Model):
    __tablename__ = "loja_membro"
    __table_args__ = (db.UniqueConstraint("casa_de_racao_id", "user_id", name="uq_loja_membro"),)

    id = db.Column(db.Integer, primary_key=True)
    casa_de_racao_id = db.Column(
        db.Integer, db.ForeignKey("casa_de_racao.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    desativado_em = db.Column(db.DateTime(timezone=True), nullable=True)

    casa_de_racao = db.relationship("CasaDeRacao")
    user = db.relationship("User", foreign_keys=[user_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])
