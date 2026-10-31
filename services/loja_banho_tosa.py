"""Banho e tosa da loja: tabela por porte, pacote do mês e agenda.

- Plano "avulso": preço por sessão, cobrado no caixa quando o banho é feito.
- Plano "mensal": assinatura (Mercado Pago) com N sessões no mês; cada
  sessão agendada consome o pacote, e o saldo é recalculado pelas sessões.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_

from extensions import db
from models import (
    Animal,
    CaixaSessao,
    CasaDeRacao,
    GroomingPlan,
    GroomingSessao,
    GroomingSubscription,
)
from services.loja_caixa import pdv
from services.loja_caixa.pdv import CaixaError
from time_utils import BR_TZ, now_in_brazil


STATUS_QUE_OCUPAM = ("agendado", "realizado")


class BanhoTosaError(ValueError):
    """Mensagem pronta para a tela."""


def planos_da_loja(casa_id: int, *, so_ativos: bool = True) -> list[GroomingPlan]:
    query = GroomingPlan.query.filter_by(casa_de_racao_id=casa_id)
    if so_ativos:
        query = query.filter_by(active=True)
    return query.order_by(GroomingPlan.cobranca, GroomingPlan.peso_min_kg, GroomingPlan.price).all()


def planos_para_peso(planos: list[GroomingPlan], peso) -> list[GroomingPlan]:
    return [plano for plano in planos if plano.atende_peso(peso)]


def animais_da_loja(casa_id: int) -> list[Animal]:
    """Animais cadastrados pela loja e os de quem assina plano da loja."""
    assinantes = (
        db.session.query(GroomingSubscription.animal_id)
        .join(GroomingPlan, GroomingSubscription.plan_id == GroomingPlan.id)
        .filter(GroomingPlan.casa_de_racao_id == casa_id, GroomingSubscription.active.is_(True))
    )
    return (
        Animal.query.filter(
            or_(Animal.casa_de_racao_id == casa_id, Animal.id.in_(assinantes.scalar_subquery()))
        )
        .filter(Animal.removido_em.is_(None))
        .order_by(Animal.name)
        .all()
    )


def _inicio_do_mes(momento: datetime) -> datetime:
    local = momento.astimezone(BR_TZ)
    return datetime(local.year, local.month, 1, tzinfo=BR_TZ)


def _fim_do_mes(momento: datetime) -> datetime:
    inicio = _inicio_do_mes(momento)
    proximo = date(inicio.year + (inicio.month // 12), inicio.month % 12 + 1, 1)
    return datetime.combine(proximo, time.min, tzinfo=BR_TZ)


def sessoes_no_mes(subscription: GroomingSubscription, momento: datetime) -> int:
    return (
        GroomingSessao.query.filter(
            GroomingSessao.subscription_id == subscription.id,
            GroomingSessao.status.in_(STATUS_QUE_OCUPAM),
            GroomingSessao.agendado_para >= _inicio_do_mes(momento),
            GroomingSessao.agendado_para < _fim_do_mes(momento),
        ).count()
    )


def _atualizar_contador(subscription: Optional[GroomingSubscription]) -> None:
    """Mantém o contador antigo (``sessions_used_this_month``) em dia com o mês corrente."""
    if subscription is None:
        return
    agora = now_in_brazil()
    subscription.sessions_used_this_month = (
        GroomingSessao.query.filter(
            GroomingSessao.subscription_id == subscription.id,
            GroomingSessao.status == "realizado",
            GroomingSessao.agendado_para >= _inicio_do_mes(agora),
            GroomingSessao.agendado_para < _fim_do_mes(agora),
        ).count()
    )


def assinatura_ativa(plano: GroomingPlan, animal: Animal) -> Optional[GroomingSubscription]:
    return GroomingSubscription.query.filter_by(plan_id=plano.id, animal_id=animal.id, active=True).first()


def agendar(
    casa: CasaDeRacao,
    *,
    animal_id: int,
    plan_id: int,
    quando: datetime,
    observacao: str | None = None,
    usuario_id: int | None = None,
) -> GroomingSessao:
    plano = GroomingPlan.query.filter_by(id=plan_id, casa_de_racao_id=casa.id).first()
    if plano is None:
        raise BanhoTosaError("Escolha um serviço da tabela da loja.")
    animal = next((a for a in animais_da_loja(casa.id) if a.id == int(animal_id)), None)
    if animal is None:
        raise BanhoTosaError("Escolha um animal cadastrado na loja.")
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=BR_TZ)
    if not plano.atende_peso(animal.peso):
        raise BanhoTosaError(
            f"{animal.name} pesa {str(animal.peso).replace('.', ',')} kg; este serviço é para {plano.porte_label.lower()}."
        )

    subscription = None
    valor = None
    if plano.avulso:
        valor = Decimal(plano.price)
    else:
        subscription = assinatura_ativa(plano, animal)
        if subscription is None:
            raise BanhoTosaError(
                f"{animal.name} não tem o plano mensal \"{plano.name}\" ativo. Agende como serviço avulso."
            )
        usados = sessoes_no_mes(subscription, quando)
        if usados >= int(plano.sessions_per_month or 1):
            raise BanhoTosaError(
                f"O pacote de {plano.sessions_per_month} sessões de {animal.name} neste mês já foi usado. "
                "Agende como serviço avulso."
            )

    sessao = GroomingSessao(
        casa_de_racao_id=casa.id,
        plan_id=plano.id,
        subscription_id=subscription.id if subscription else None,
        animal_id=animal.id,
        agendado_para=quando,
        status="agendado",
        valor=valor,
        observacao=" ".join((observacao or "").split())[:255] or None,
        created_by_id=usuario_id,
    )
    db.session.add(sessao)
    db.session.commit()
    return sessao


def mudar_status(sessao: GroomingSessao, status: str) -> GroomingSessao:
    if status not in {"agendado", "realizado", "cancelado", "faltou"}:
        raise BanhoTosaError("Situação inválida.")
    if sessao.venda_id and status != "realizado":
        raise BanhoTosaError("Esta sessão já foi paga no caixa; cancele a venda antes.")
    sessao.status = status
    sessao.realizado_em = now_in_brazil() if status == "realizado" else None
    _atualizar_contador(sessao.subscription)
    db.session.commit()
    return sessao


def cobrar_no_caixa(
    casa: CasaDeRacao,
    sessao: GroomingSessao,
    *,
    caixa: Optional[CaixaSessao],
    pagamentos: list[dict],
    usuario_id: int | None = None,
):
    """Recebe a sessão avulsa no caixa aberto e marca como feita."""
    if sessao.casa_de_racao_id != casa.id:
        raise BanhoTosaError("Sessão de outra loja.")
    if sessao.subscription_id:
        raise BanhoTosaError("Sessão do plano mensal: o pagamento é a mensalidade.")
    if sessao.venda_id and sessao.venda and sessao.venda.status == "concluida":
        raise BanhoTosaError("Esta sessão já foi paga.")
    if sessao.status in {"cancelado", "faltou"}:
        raise BanhoTosaError("Sessão cancelada não é cobrada.")
    plano = sessao.plan
    descricao = f"{plano.service_label if plano else 'Banho e tosa'} — {sessao.animal.name}"
    if plano is not None:
        descricao += f" ({plano.porte_label.lower()})"
    try:
        venda = pdv.registrar_servico(
            casa.id,
            caixa,
            codigo=f"SERV-BT{plano.id if plano else ''}",
            descricao=descricao,
            valor=sessao.valor or (plano.price if plano else 0),
            pagamentos=pagamentos,
            usuario_id=usuario_id,
        )
    except CaixaError as exc:
        db.session.rollback()
        raise BanhoTosaError(str(exc)) from exc
    sessao.venda_id = venda.id
    sessao.status = "realizado"
    sessao.realizado_em = sessao.realizado_em or now_in_brazil()
    db.session.commit()
    return venda


def agenda_do_dia(casa_id: int, dia: date) -> list[GroomingSessao]:
    inicio = datetime.combine(dia, time.min, tzinfo=BR_TZ)
    return (
        GroomingSessao.query.filter(
            GroomingSessao.casa_de_racao_id == casa_id,
            GroomingSessao.agendado_para >= inicio,
            GroomingSessao.agendado_para < inicio + timedelta(days=1),
        )
        .order_by(GroomingSessao.agendado_para)
        .all()
    )
