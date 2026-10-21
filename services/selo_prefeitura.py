"""Selo de registro na Prefeitura (ex.: equinos — art. 143 da LC 3.607/2008).

O selo é um ``AnimalHealthRecord`` com ``kind='registro_prefeitura'``: não
altera o cadastro do animal nem exige migração. Só administradores concedem
ou retiram o selo; a validade é de 12 meses a partir da data escolhida.
"""
from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta

from extensions import db
from models import AnimalHealthRecord

SELO_KIND = 'registro_prefeitura'
SELO_TITULO = 'Registro na Prefeitura de Orlândia'
SELO_VALIDADE_MESES = 12


def validade_do_selo(inicio: date) -> date:
    return inicio + relativedelta(months=SELO_VALIDADE_MESES)


def garantir_tabela() -> None:
    """A tabela é criada sob demanda (mesmo padrão de ``blueprints/mcp.py``)."""
    AnimalHealthRecord.__table__.create(db.engine, checkfirst=True)


def selo_atual(animal):
    """Selo mais recente do animal (válido ou vencido) ou ``None``.

    Nunca derruba a página que o exibe: se a consulta falhar (tabela ainda
    inexistente, por exemplo), devolve ``None``.
    """
    if animal is None or animal.id is None:
        return None
    try:
        return (
            AnimalHealthRecord.query
            .filter_by(animal_id=animal.id, kind=SELO_KIND)
            .order_by(AnimalHealthRecord.occurred_on.desc(), AnimalHealthRecord.id.desc())
            .first()
        )
    except Exception:
        db.session.rollback()
        return None


def situacao_do_selo(selo, hoje: date | None = None) -> dict | None:
    if selo is None or selo.next_due_on is None:
        return None
    hoje = hoje or date.today()
    dias = (selo.next_due_on - hoje).days
    # Início futuro: o registro ainda não vale (nem válido, nem vencido).
    futuro = selo.occurred_on is not None and selo.occurred_on > hoje
    valido = not futuro and dias >= 0
    return {
        'registro': selo,
        'inicio': selo.occurred_on,
        'validade': selo.next_due_on,
        'futuro': futuro,
        'valido': valido,
        'dias_restantes': dias,
        'vence_em_breve': valido and dias <= 30,
    }


def conceder_selo(animal, inicio: date, admin_id: int | None, observacao: str | None = None):
    selo = AnimalHealthRecord(
        animal_id=animal.id,
        created_by_id=admin_id,
        kind=SELO_KIND,
        title=SELO_TITULO,
        occurred_on=inicio,
        next_due_on=validade_do_selo(inicio),
        notes=(observacao or '').strip() or None,
        source='admin',
    )
    db.session.add(selo)
    return selo


def retirar_selo(animal) -> int:
    """Remove todos os selos do animal; devolve quantos foram removidos."""
    registros = AnimalHealthRecord.query.filter_by(animal_id=animal.id, kind=SELO_KIND).all()
    for registro in registros:
        db.session.delete(registro)
    return len(registros)
