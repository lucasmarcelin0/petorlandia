"""Papel "Combate à dengue": quem acessa a área de território e vigilância.

Administradores sempre acessam. As demais contas precisam de um vínculo ativo
em ``entomologia_equipe``, concedido por um administrador. O vínculo é um papel
adicional: ``User.role`` e os demais acessos da conta não mudam.
"""
from __future__ import annotations

from flask import g, has_request_context

from services.entomologia_service import consultar_sem_interromper

ROTULO_PAPEL = "Combate à dengue"


def eh_admin(user) -> bool:
    return bool(getattr(user, "is_authenticated", False)
                and (getattr(user, "role", "") or "").lower() == "admin")


def membro_equipe(user) -> bool:
    """Vínculo ativo na equipe; memorizado por requisição (navegação + rota)."""
    if not getattr(user, "is_authenticated", False) or not getattr(user, "id", None):
        return False
    cache = g.setdefault("_entomologia_membro", {}) if has_request_context() else {}
    if user.id not in cache:
        from models.entomologia import EntomologiaEquipe
        cache[user.id] = bool(consultar_sem_interromper(
            lambda: EntomologiaEquipe.query.filter_by(user_id=user.id, revogado_em=None).first() is not None,
            False))
    return cache[user.id]


def pode_acessar(user) -> bool:
    return eh_admin(user) or membro_equipe(user)


def membros_ativos():
    from models.entomologia import EntomologiaEquipe
    return (EntomologiaEquipe.query.filter_by(revogado_em=None)
            .order_by(EntomologiaEquipe.concedido_em).all())


def buscar_conta(email):
    from sqlalchemy import func
    from models import User
    email = (email or "").strip().lower()
    if not email or "@" not in email or len(email) > 254:
        raise ValueError("Informe um e-mail válido.")
    user = User.query.filter(func.lower(User.email) == email).first()
    if not user:
        raise ValueError("Nenhuma conta com esse e-mail. Peça para a pessoa criar a conta no site "
                         "com esse endereço e conceda o acesso em seguida.")
    return user


def conceder(user, por):
    """Idempotente: devolve (vínculo, criado)."""
    from extensions import db
    from models.entomologia import EntomologiaEquipe
    atual = EntomologiaEquipe.query.filter_by(user_id=user.id, revogado_em=None).first()
    if atual:
        return atual, False
    vinculo = EntomologiaEquipe(user_id=user.id, concedido_por=por)
    db.session.add(vinculo)
    if has_request_context():
        g.pop("_entomologia_membro", None)
    return vinculo, True


def revogar(user_id, por):
    from models.entomologia import EntomologiaEquipe
    from time_utils import utcnow
    vinculos = EntomologiaEquipe.query.filter_by(user_id=user_id, revogado_em=None).all()
    for vinculo in vinculos:
        vinculo.revogado_em, vinculo.revogado_por = utcnow(), por
    if has_request_context():
        g.pop("_entomologia_membro", None)
    return len(vinculos)
