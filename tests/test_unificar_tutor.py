"""Unificar o tutor quando o e-mail digitado já é de outro cadastro.

Caso real (2026-10-26): a clínica cadastrou a tutora com o e-mail errado e
lançou os animais nesse cadastro. A pessoa criou a própria conta com o e-mail
certo e entrou sem ver os animais. Ao corrigir o e-mail na ficha, a tela só
dizia "Este e-mail já está no cadastro de ...". Agora oferece unificar.
"""
from __future__ import annotations

import pytest

from extensions import db
from models import Animal, User, Veterinario

JSON = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
ENDERECO = {
    "cep": "14620-000", "rua": "Avenida N", "numero": "1261", "cidade": "Orlândia", "estado": "SP",
    "latitude": "-20.72", "longitude": "-47.88",
}


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


@pytest.fixture()
def vet_id(app, client):
    with app.app_context():
        vet = User(name="Dr. Unifica", email="unifica.vet@example.com", worker="veterinario")
        vet.set_password("senha-segura")
        vet.veterinario = Veterinario(crmv="CRMV-UNIFICA")
        db.session.add(vet)
        db.session.commit()
        vet_id = vet.id
    _login(client, vet_id)
    return vet_id


def _cenario(app, vet_id, *, added_by_vet=True):
    """Cadastro da clínica (e-mail errado, com animais) e a conta da pessoa."""
    with app.app_context():
        conta = User(name="Rosilda Mochiute", email="rosilda@example.com", added_by_id=vet_id)
        conta.set_password("senha-da-tutora")
        errado = User(
            name="Rosilda M.", email="rosilda@exmple.com", phone="16991234567",
            added_by_id=vet_id if added_by_vet else None,
        )
        errado.set_password("x")
        db.session.add_all([conta, errado])
        db.session.flush()
        db.session.add_all([
            Animal(name="Thor", user_id=errado.id),
            Animal(name="Mel", user_id=errado.id),
        ])
        db.session.commit()
        return errado.id, conta.id, conta.password_hash


def test_email_de_outro_cadastro_oferece_unificar(app, client, vet_id):
    origem_id, destino_id, _ = _cenario(app, vet_id)

    resposta = client.post(
        f"/update_tutor/{origem_id}", data={**ENDERECO, "email": "rosilda@example.com"}, headers=JSON
    )

    assert resposta.status_code == 409
    corpo = resposta.get_json()
    # O aviso de sempre continua lá; a oferta vem junto.
    assert "Este e-mail já está no cadastro de Rosilda Mochiute" in corpo["message"]
    oferta = corpo["merge_offer"]
    assert oferta["source_id"] == origem_id
    assert oferta["target_id"] == destino_id
    assert oferta["source_animals"] == 2
    assert oferta["url"].endswith(f"/tutor/{origem_id}/unificar")


def test_unificar_leva_animais_para_a_conta_da_pessoa(app, client, vet_id):
    origem_id, destino_id, senha_hash = _cenario(app, vet_id)

    resposta = client.post(
        f"/tutor/{origem_id}/unificar", data={"target_id": destino_id}, headers=JSON
    )

    assert resposta.status_code == 200, resposta.get_json()
    corpo = resposta.get_json()
    assert corpo["success"] is True
    assert corpo["redirect"].endswith(f"/ficha_tutor/{destino_id}")
    with app.app_context():
        assert db.session.get(User, origem_id) is None
        destino = db.session.get(User, destino_id)
        assert {a.name for a in Animal.query.filter_by(user_id=destino_id)} == {"Thor", "Mel"}
        # Login da pessoa intacto; o que faltava veio do cadastro da clínica.
        assert destino.email == "rosilda@example.com"
        assert destino.password_hash == senha_hash
        assert destino.phone == "16991234567"
        assert f"#{origem_id}" in destino.observacoes


def _cadastro_da_clinica_e_conta_propria(app, added_by_id):
    with app.app_context():
        from models import Clinica

        clinica = Clinica(nome="Clínica Teste")
        db.session.add(clinica)
        db.session.flush()
        conta = User(name="Conta Própria", email="propria@example.com")
        conta.set_password("s")
        errado = User(name="Cadastro Clínica", email="clinica@exmple.com",
                      added_by_id=added_by_id, clinica_id=clinica.id)
        errado.set_password("s")
        db.session.add_all([conta, errado])
        db.session.commit()
        return errado.id, conta.id, clinica.id


def test_vet_nao_unifica_com_conta_que_nao_enxerga(app, client, vet_id):
    origem_id, destino_id, _ = _cadastro_da_clinica_e_conta_propria(app, vet_id)

    resposta = client.post(f"/tutor/{origem_id}/unificar", data={"target_id": destino_id}, headers=JSON)

    assert resposta.status_code == 403
    with app.app_context():
        assert db.session.get(User, origem_id) is not None


def test_unificar_mantem_o_tutor_visivel_para_a_clinica(app, client):
    with app.app_context():
        admin = User(name="Admin", email="admin.unifica@example.com", role="admin", worker="veterinario")
        admin.set_password("s")
        admin.veterinario = Veterinario(crmv="CRMV-ADMIN")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id
    _login(client, admin_id)
    origem_id, destino_id, clinica_id = _cadastro_da_clinica_e_conta_propria(app, admin_id)

    resposta = client.post(f"/tutor/{origem_id}/unificar", data={"target_id": destino_id}, headers=JSON)

    assert resposta.status_code == 200, resposta.get_json()
    with app.app_context():
        destino = db.session.get(User, destino_id)
        # Sem isso o tutor sumiria da lista da clínica que o atendia.
        assert destino.clinica_id == clinica_id
        assert destino.added_by_id == admin_id


def test_quem_nao_cadastrou_a_origem_nao_unifica(app, client, vet_id):
    origem_id, destino_id, _ = _cenario(app, vet_id, added_by_vet=False)

    with app.app_context():
        outro = User(name="Dra. Outra", email="outra.vet@example.com", worker="veterinario")
        outro.set_password("s")
        outro.veterinario = Veterinario(crmv="CRMV-OUTRA")
        db.session.add(outro)
        db.session.commit()
        db.session.get(User, origem_id).added_by_id = outro.id
        db.session.commit()

    resposta = client.post(f"/tutor/{origem_id}/unificar", data={"target_id": destino_id}, headers=JSON)

    assert resposta.status_code in (403, 404)
    with app.app_context():
        assert db.session.get(User, origem_id) is not None
        assert Animal.query.filter_by(user_id=origem_id).count() == 2


def test_conta_de_equipe_nunca_e_unificada(app, client, vet_id):
    with app.app_context():
        errado = User(name="Tutor", email="tutor@exmple.com", added_by_id=vet_id)
        errado.set_password("s")
        db.session.add(errado)
        db.session.commit()
        origem_id = errado.id

    resposta = client.post(
        f"/update_tutor/{origem_id}", data={**ENDERECO, "email": "unifica.vet@example.com"}, headers=JSON
    )
    assert resposta.status_code == 409
    assert "merge_offer" not in resposta.get_json()

    resposta = client.post(f"/tutor/{origem_id}/unificar", data={"target_id": vet_id}, headers=JSON)
    assert resposta.status_code == 403
    with app.app_context():
        assert db.session.get(User, origem_id) is not None
