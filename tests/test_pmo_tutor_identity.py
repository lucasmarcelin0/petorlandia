"""Identidade e contato das contas criadas pela campanha PMO.

A planilha e redigitada a cada dia de campanha e o telefone e frequentemente
compartilhado entre familias. Estes testes fixam as tres decisoes que isso
forca: quando duas grafias sao a mesma pessoa, que o endereco chegue no campo
que a ficha do tutor le, e que o e-mail interno nao se passe por contato real.
"""

from __future__ import annotations

import pytest

from extensions import db
from models import PmoVaccinationVisit, User
from services.vacina_pmo_service import (
    _apply_visit_address,
    _ensure_tutor_account,
    _password,
    _same_person_name,
    _unique_provisional_email,
)


def _visit(**overrides) -> PmoVaccinationVisit:
    defaults = dict(
        spreadsheet_id="sheet-1",
        sheet_gid="0",
        sheet_title="23/06",
        source_row=2,
        tutor_name="Ana Marcia Pinheiro",
        address="Rua das Flores, 120, Centro",
        phone1="16999990001",
        dogs=1,
        cats=0,
        password="PMOABCDE",
    )
    defaults.update(overrides)
    visit = PmoVaccinationVisit(**defaults)
    db.session.add(visit)
    db.session.flush()
    return visit


# --------------------------------------------------------------------------
# Nome
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "left, right, same",
    [
        # Mesma tutora, a planilha abreviou numa das campanhas.
        ("Ana Marcia Pinheiro", "Ana Marcia da Costa Pinheiro", True),
        ("Ana Maria da Silva", "Ana Maria Silva", True),
        ("Maria", "Maria", True),
        # Familias diferentes no mesmo telefone: nunca unir.
        ("Maria Silva", "Joao Silva", False),
        ("Jose Santos", "Jose Carlos Santos", False),
        ("Ana Silva", "Ana Paula Silva", False),
        # Sobrenomes trocados de ordem nao sao abreviacao.
        ("Maria Souza Lima", "Maria Lima Souza", False),
        ("", "Ana Silva", False),
    ],
)
def test_same_person_name(left, right, same):
    assert _same_person_name(left, right) is same


# --------------------------------------------------------------------------
# Senha
# --------------------------------------------------------------------------

def test_password_is_not_derivable_from_phone():
    """O telefone e o identificador de login; a senha nao pode sair dele."""
    phone = "16999990001"
    passwords = {_password(phone) for _ in range(200)}

    # A versao antiga tinha 24 possibilidades para um mesmo telefone.
    assert len(passwords) > 100
    for password in passwords:
        assert password.startswith("PMO")
        assert phone[-4:] not in password


# --------------------------------------------------------------------------
# Endereco
# --------------------------------------------------------------------------

def test_tutor_account_gets_structured_address(app):
    """A ficha do tutor le user.endereco, nao user.address."""
    with app.app_context():
        visit = _visit(geocode_lat=-20.72, geocode_lng=-47.88)
        _ensure_tutor_account(visit)
        db.session.commit()

        tutor = visit.tutor_user
        assert tutor is not None
        assert tutor.endereco is not None
        assert tutor.endereco.rua == "Rua das Flores"
        assert tutor.endereco.numero == "120"
        assert tutor.endereco.bairro == "Centro"
        assert tutor.endereco.cidade == "Orlândia"
        assert tutor.endereco.estado == "SP"
        # Coordenada ja calculada pela otimizacao de rota e reaproveitada.
        assert tutor.endereco.latitude == pytest.approx(-20.72)
        # O texto livre continua preenchido para as impressoes.
        assert tutor.address == "Rua das Flores, 120, Centro"


def test_structured_address_does_not_overwrite_manual_fix(app):
    """Endereco corrigido na clinica vale mais que o texto da planilha.

    A procedencia e detectada pelo texto: se user.address nao bate com o de
    nenhuma visita, alguem editou na ficha. Nesse caso o endereco da planilha
    vai para observacoes em vez de sobrescrever.
    """
    with app.app_context():
        visit = _visit()
        _ensure_tutor_account(visit)
        db.session.commit()

        tutor = visit.tutor_user
        original_id = tutor.endereco_id
        tutor.address = "Rua Corrigida A Mao, 45, Centro"
        tutor.endereco.rua = "Rua Corrigida A Mao"
        db.session.commit()

        visit.address = "Outra Rua, 999, Bairro Novo"
        _apply_visit_address(tutor, visit)
        db.session.commit()

        assert tutor.endereco_id == original_id
        assert tutor.endereco.rua == "Rua Corrigida A Mao"
        assert tutor.address == "Rua Corrigida A Mao, 45, Centro"
        # O endereco da planilha nao se perde.
        assert "Outra Rua, 999, Bairro Novo" in tutor.observacoes


def test_second_address_keeps_newest_and_archives_previous(app):
    """Tutora com animais em locais diferentes: o modelo so tem uma vaga.

    Vale o endereco da campanha mais recente; o anterior vai para observacoes
    em vez de sumir.
    """
    from datetime import date

    with app.app_context():
        antiga = _visit(
            address="Rua das Flores, 120, Centro",
            vaccine_date=date(2026, 6, 1),
        )
        _ensure_tutor_account(antiga)
        db.session.commit()
        tutor = antiga.tutor_user

        nova = _visit(
            source_row=3,
            address="Avenida J, 1701, Jardim Novo",
            vaccine_date=date(2026, 8, 1),
            tutor_user_id=tutor.id,
        )
        _apply_visit_address(tutor, nova)
        db.session.commit()

        assert tutor.address == "Avenida J, 1701, Jardim Novo"
        assert tutor.endereco.rua == "Avenida J"
        assert tutor.endereco.numero == "1701"
        assert "Rua das Flores, 120, Centro" in tutor.observacoes


def test_older_visit_does_not_overwrite_newer_address(app):
    """A ordem de iteracao do banco nao pode decidir qual endereco vence."""
    from datetime import date

    with app.app_context():
        nova = _visit(
            address="Avenida J, 1701, Jardim Novo",
            vaccine_date=date(2026, 8, 1),
        )
        _ensure_tutor_account(nova)
        db.session.commit()
        tutor = nova.tutor_user

        antiga = _visit(
            source_row=3,
            address="Rua das Flores, 120, Centro",
            vaccine_date=date(2026, 6, 1),
            tutor_user_id=tutor.id,
        )
        _apply_visit_address(tutor, antiga)
        db.session.commit()

        assert tutor.address == "Avenida J, 1701, Jardim Novo"
        assert "Rua das Flores, 120, Centro" in tutor.observacoes


def test_repeated_sync_does_not_duplicate_archived_address(app):
    """_ensure_tutor_account roda a cada carregamento do painel."""
    from datetime import date

    with app.app_context():
        antiga = _visit(
            address="Rua das Flores, 120, Centro",
            vaccine_date=date(2026, 6, 1),
        )
        _ensure_tutor_account(antiga)
        db.session.commit()
        tutor = antiga.tutor_user

        nova = _visit(
            source_row=3,
            address="Avenida J, 1701, Jardim Novo",
            vaccine_date=date(2026, 8, 1),
            tutor_user_id=tutor.id,
        )
        for _ in range(5):
            _apply_visit_address(tutor, nova)
            _apply_visit_address(tutor, antiga)
        db.session.commit()

        assert tutor.observacoes.count("Rua das Flores, 120, Centro") == 1
        assert tutor.address == "Avenida J, 1701, Jardim Novo"


def test_long_address_is_truncated_to_column_size(app):
    """visit.address e String(500); User.address e String(200)."""
    with app.app_context():
        visit = _visit(address="Rua " + ("muito longa " * 60) + ", 10, Centro")
        _ensure_tutor_account(visit)
        db.session.commit()

        tutor = visit.tutor_user
        assert len(tutor.address) <= 200
        assert len(tutor.endereco.rua) <= 120


# --------------------------------------------------------------------------
# E-mail
# --------------------------------------------------------------------------

def test_provisional_email_is_marked_as_placeholder(app):
    with app.app_context():
        visit = _visit()
        _ensure_tutor_account(visit)
        db.session.commit()

        tutor = visit.tutor_user
        assert tutor.email.endswith("@petorlandia.local")
        assert tutor.email_is_placeholder is True


def test_provisional_email_is_unique_after_relink(app):
    """Revincular a visita nao pode reproduzir um e-mail ja usado.

    Quando a identidade muda na planilha, tutor_user_id e zerado e uma conta
    nova nasce para a MESMA visita -- o sufixo por visita sozinho colidia.
    """
    with app.app_context():
        visit = _visit()
        _ensure_tutor_account(visit)
        db.session.commit()
        first_email = visit.tutor_user.email

        # Outra familia no mesmo telefone ja ocupou o endereco base.
        visit.tutor_user_id = None
        visit.tutor_name = "Beatriz Nogueira Ramos"
        db.session.commit()
        _ensure_tutor_account(visit)
        db.session.commit()

        second_email = visit.tutor_user.email
        assert second_email != first_email

        # E um terceiro relink continua achando endereco livre.
        visit.tutor_user_id = None
        visit.tutor_name = "Carla Teixeira Moraes"
        db.session.commit()
        _ensure_tutor_account(visit)
        db.session.commit()

        assert visit.tutor_user.email not in {first_email, second_email}
        assert User.query.filter(
            User.email.ilike("%@petorlandia.local")
        ).count() == 3


def test_unique_provisional_email_survives_taken_visit_suffix(app):
    with app.app_context():
        visit = _visit()
        taken = User(
            name="Ja Existe",
            email=f"pmo-5516999990001-{visit.id}@petorlandia.local",
            email_is_placeholder=True,
        )
        taken.set_password("x")
        base = User(
            name="Base Ocupada",
            email="pmo-5516999990001@petorlandia.local",
            email_is_placeholder=True,
        )
        base.set_password("x")
        db.session.add_all([taken, base])
        db.session.commit()

        candidate = _unique_provisional_email("5516999990001", visit)

        assert candidate not in {taken.email, base.email}
