"""Modelos do módulo Petsitter, Carreiras (parceiros) e Indicações.

Mantidos em arquivo próprio para não interferir nos modelos existentes.
"""
from __future__ import annotations

import secrets

from extensions import db
from time_utils import utcnow


# ---------------------------------------------------------------------------
# Petsitter
# ---------------------------------------------------------------------------

PETSITTER_STATUS = ("pendente", "aprovado", "rejeitado", "inativo")
SOLICITACAO_STATUS = ("aberta", "atribuida", "concluida", "cancelada")
CANDIDATURA_STATUS = ("pendente", "aprovada", "rejeitada")
CANDIDATURA_CATEGORIAS = (
    "petsitter",
    "clinica",
    "petshop",
    "laboratorio",
    "especialista",
)


class PetsitterProfile(db.Model):
    """Perfil de cuidador(a) aprovado ou em análise."""

    __tablename__ = "petsitter_profile"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    bio = db.Column(db.Text, nullable=True)
    experiencia = db.Column(db.Text, nullable=True)
    cidade = db.Column(db.String(120), nullable=True)
    bairro = db.Column(db.String(120), nullable=True)
    atende_domicilio = db.Column(db.Boolean, default=True, nullable=False)
    hospeda_em_casa = db.Column(db.Boolean, default=False, nullable=False)
    preco_diaria = db.Column(db.Numeric(10, 2), nullable=True)
    status = db.Column(db.String(20), default="pendente", nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship(
        "User",
        backref=db.backref("petsitter_profile", uselist=False),
        foreign_keys=[user_id],
    )

    @property
    def aprovado(self) -> bool:
        return self.status == "aprovado"

    def __repr__(self):  # pragma: no cover
        return f"<PetsitterProfile user={self.user_id} status={self.status}>"


petsitter_request_animal = db.Table(
    "petsitter_request_animal",
    db.Column(
        "request_id",
        db.Integer,
        db.ForeignKey("petsitter_request.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "animal_id",
        db.Integer,
        db.ForeignKey("animal.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class PetsitterRequest(db.Model):
    """Solicitação de cuidado feita por um tutor que vai viajar."""

    __tablename__ = "petsitter_request"

    id = db.Column(db.Integer, primary_key=True)
    tutor_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sitter_id = db.Column(
        db.Integer,
        db.ForeignKey("petsitter_profile.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    data_inicio = db.Column(db.Date, nullable=False)
    data_fim = db.Column(db.Date, nullable=False)
    local_atendimento = db.Column(
        db.String(30), default="domicilio_tutor", nullable=False
    )  # domicilio_tutor | casa_sitter
    endereco = db.Column(db.String(255), nullable=True)
    observacoes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="aberta", nullable=False, index=True)
    preco_total = db.Column(db.Numeric(10, 2), nullable=True)
    payment_id = db.Column(
        db.Integer,
        db.ForeignKey("payment.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    tutor = db.relationship(
        "User", backref="petsitter_requests", foreign_keys=[tutor_id]
    )
    sitter = db.relationship(
        "PetsitterProfile", backref="atendimentos", foreign_keys=[sitter_id]
    )
    payment = db.relationship("Payment", foreign_keys=[payment_id])
    animais = db.relationship(
        "Animal", secondary=petsitter_request_animal, lazy="selectin"
    )

    @property
    def dias(self) -> int:
        if not (self.data_inicio and self.data_fim):
            return 0
        return max((self.data_fim - self.data_inicio).days, 0) + 1

    def __repr__(self):  # pragma: no cover
        return f"<PetsitterRequest {self.id} tutor={self.tutor_id} status={self.status}>"


# ---------------------------------------------------------------------------
# Carreiras / Parceiros
# ---------------------------------------------------------------------------

class CareerApplication(db.Model):
    """Candidatura enviada pela página Carreiras (petsitter, clínica, petshop,
    laboratório ou profissional especialista)."""

    __tablename__ = "career_application"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    categoria = db.Column(db.String(30), nullable=False, index=True)
    nome = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    telefone = db.Column(db.String(20), nullable=True)
    cidade = db.Column(db.String(120), nullable=True)
    especialidade = db.Column(db.String(150), nullable=True)
    mensagem = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="pendente", nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reviewed_by_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    user = db.relationship("User", foreign_keys=[user_id])
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id])

    def __repr__(self):  # pragma: no cover
        return f"<CareerApplication {self.id} {self.categoria} {self.status}>"


# ---------------------------------------------------------------------------
# Indicações
# ---------------------------------------------------------------------------

class ReferralCode(db.Model):
    """Código de indicação único por usuário."""

    __tablename__ = "referral_code"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    code = db.Column(db.String(16), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship(
        "User", backref=db.backref("referral_code", uselist=False)
    )

    @staticmethod
    def generate_code() -> str:
        return secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")[:10].upper()

    @classmethod
    def get_or_create(cls, user_id: int) -> "ReferralCode":
        existing = cls.query.filter_by(user_id=user_id).first()
        if existing:
            return existing
        code = cls.generate_code()
        while cls.query.filter_by(code=code).first() is not None:
            code = cls.generate_code()
        referral = cls(user_id=user_id, code=code)
        db.session.add(referral)
        return referral

    def __repr__(self):  # pragma: no cover
        return f"<ReferralCode {self.code} user={self.user_id}>"


class ReferralSignup(db.Model):
    """Registro de um novo usuário que chegou por um código de indicação."""

    __tablename__ = "referral_signup"

    id = db.Column(db.Integer, primary_key=True)
    code_id = db.Column(
        db.Integer,
        db.ForeignKey("referral_code.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    referred_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    code = db.relationship(
        "ReferralCode", backref=db.backref("signups", lazy="selectin")
    )
    referred_user = db.relationship("User", foreign_keys=[referred_user_id])

    def __repr__(self):  # pragma: no cover
        return f"<ReferralSignup code={self.code_id} user={self.referred_user_id}>"
