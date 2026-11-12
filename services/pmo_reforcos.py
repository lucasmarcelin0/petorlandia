"""Exibe apenas o reforço automático PMO mais distante de cada animal."""

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import aliased

from models import Vacina

OBS = "Reforço anual previsto após a campanha PMO."
NOMES = ("Reforço Vacina Antirrábica", "Reforco Vacina Antirrabica")
TIPOS = ("Reforço PMO", "Reforco PMO")


def filtrar_reforcos_automaticos(query):
    outra = aliased(Vacina)
    automatico = and_(func.coalesce(Vacina.nome, "").in_(NOMES), func.coalesce(Vacina.tipo, "").in_(TIPOS),
                      func.coalesce(Vacina.observacoes, "") == OBS)
    posterior = exists().where(and_(
        outra.animal_id == Vacina.animal_id, outra.aplicada.is_(False),
        outra.nome.in_(NOMES), outra.tipo.in_(TIPOS), outra.observacoes == OBS,
        or_(outra.aplicada_em > Vacina.aplicada_em,
            and_(outra.aplicada_em == Vacina.aplicada_em, outra.id > Vacina.id)),
    )).correlate(Vacina)
    return query.filter(or_(~automatico, ~posterior))
