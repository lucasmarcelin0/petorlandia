"""Selo de registro na Prefeitura: só admin concede, validade de 12 meses."""
from datetime import date

import flask_login.utils as login_utils

from extensions import db
from models import Animal, AnimalHealthRecord, User


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def _make_user(email, role="adotante"):
    user = User(name="Usuário Teste", email=email, role=role)
    user.set_password("x") if hasattr(user, "set_password") else setattr(user, "password_hash", "x")
    db.session.add(user)
    db.session.commit()
    return user


def _make_animal(user, name="Romeu"):
    animal = Animal(name=name, user_id=user.id, modo="pessoal")
    db.session.add(animal)
    db.session.commit()
    return animal


def _selos(animal):
    return AnimalHealthRecord.query.filter_by(animal_id=animal.id, kind="registro_prefeitura").all()


def test_validade_de_um_ano():
    from services.selo_prefeitura import validade_do_selo

    assert validade_do_selo(date(2026, 10, 21)) == date(2027, 10, 21)
    assert validade_do_selo(date(2028, 2, 29)) == date(2029, 2, 28)


def test_admin_concede_renova_e_retira_selo(app, client, monkeypatch):
    tutor = _make_user("tutor@test.com")
    admin = _make_user("admin@test.com", role="admin")
    animal = _make_animal(tutor)
    _login(monkeypatch, admin)

    resp = client.post(
        f"/animal/{animal.id}/selo-prefeitura",
        data={"inicio": "2026-10-21", "observacao": "AIE e Mormo negativos"},
    )
    assert resp.status_code == 302
    selos = _selos(animal)
    assert len(selos) == 1
    assert selos[0].occurred_on == date(2026, 10, 21)
    assert selos[0].next_due_on == date(2027, 10, 21)
    assert selos[0].created_by_id == admin.id

    from services.selo_prefeitura import selo_atual, situacao_do_selo

    situacao = situacao_do_selo(selo_atual(animal), hoje=date(2026, 11, 1))
    assert situacao["valido"] is True
    assert situacao_do_selo(selo_atual(animal), hoje=date(2027, 10, 22))["valido"] is False

    # renovação: o selo mais recente prevalece
    client.post(f"/animal/{animal.id}/selo-prefeitura", data={"inicio": "2027-10-01"})
    assert selo_atual(animal).next_due_on == date(2028, 10, 1)

    resp = client.post(f"/animal/{animal.id}/selo-prefeitura/remover")
    assert resp.status_code == 302
    assert _selos(animal) == []


def test_data_obrigatoria(app, client, monkeypatch):
    tutor = _make_user("tutor@test.com")
    admin = _make_user("admin@test.com", role="admin")
    animal = _make_animal(tutor)
    _login(monkeypatch, admin)

    resp = client.post(f"/animal/{animal.id}/selo-prefeitura", data={"inicio": ""})
    assert resp.status_code == 302
    assert _selos(animal) == []


def test_tutor_e_veterinario_nao_concedem_selo(app, client, monkeypatch):
    tutor = _make_user("tutor@test.com")
    animal = _make_animal(tutor)
    _login(monkeypatch, tutor)
    resp = client.post(f"/animal/{animal.id}/selo-prefeitura", data={"inicio": "2026-10-21"})
    assert resp.status_code in (403, 404)

    vet = _make_user("vet@test.com", role="veterinario")
    _login(monkeypatch, vet)
    resp = client.post(f"/animal/{animal.id}/selo-prefeitura", data={"inicio": "2026-10-21"})
    assert resp.status_code in (403, 404)
    resp = client.post(f"/animal/{animal.id}/selo-prefeitura/remover")
    assert resp.status_code in (403, 404)
    assert _selos(animal) == []


def test_selo_aparece_na_carteirinha_publica(app, client, monkeypatch):
    tutor = _make_user("tutor@test.com")
    admin = _make_user("admin@test.com", role="admin")
    animal = _make_animal(tutor)
    animal.public_token = "tok-selo-teste"
    db.session.commit()

    from flask_login import AnonymousUserMixin

    monkeypatch.setattr(login_utils, "_get_user", lambda: AnonymousUserMixin())
    resp = client.get("/carteirinha/tok-selo-teste")
    assert resp.status_code == 200
    assert "Registrado na Prefeitura".encode() not in resp.data

    _login(monkeypatch, admin)
    hoje = date.today().isoformat()
    client.post(f"/animal/{animal.id}/selo-prefeitura", data={"inicio": hoje})

    monkeypatch.setattr(login_utils, "_get_user", lambda: AnonymousUserMixin())
    resp = client.get("/carteirinha/tok-selo-teste")
    assert resp.status_code == 200
    assert "Registrado na Prefeitura".encode() in resp.data


def test_ficha_mostra_formulario_so_para_admin(app, client, monkeypatch):
    tutor = _make_user("tutor@test.com")
    admin = _make_user("admin@test.com", role="admin")
    animal = _make_animal(tutor)

    _login(monkeypatch, admin)
    resp = client.get(f"/animal/{animal.id}/ficha")
    assert resp.status_code == 200
    assert b"data-selo-prefeitura-admin" in resp.data
    client.post(f"/animal/{animal.id}/selo-prefeitura", data={"inicio": date.today().isoformat()})

    _login(monkeypatch, tutor)
    resp = client.get(f"/animal/{animal.id}/ficha")
    assert resp.status_code == 200
    assert b"data-selo-prefeitura-admin" not in resp.data
    assert "Registrado na Prefeitura".encode() in resp.data


def test_inicio_futuro_nao_aparece_como_valido(app):
    from services.selo_prefeitura import situacao_do_selo

    selo = AnimalHealthRecord(
        kind="registro_prefeitura", title="x",
        occurred_on=date(2027, 1, 1), next_due_on=date(2028, 1, 1),
    )
    antes = situacao_do_selo(selo, hoje=date(2026, 10, 21))
    assert antes["futuro"] is True and antes["valido"] is False and antes["vence_em_breve"] is False
    durante = situacao_do_selo(selo, hoje=date(2027, 1, 1))
    assert durante["futuro"] is False and durante["valido"] is True
