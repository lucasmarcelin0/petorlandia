"""Salvar o tutor não pode depender do formato em que o dado foi gravado.

Três relatos de produção em 2026-10-09, todos em `/update_tutor/<id>`:

- CPF gravado com máscara pela ficha era recusado pela consulta (e vice-versa);
- o mesmo com o telefone;
- trocar o e-mail para um que já existia em outro cadastro devolvia 500
  "Unexpected error." (IntegrityError no autoflush, antes do try do commit).
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import User, Veterinario

JSON = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
ENDERECO = {
    "cep": "14620-000", "rua": "Rua Um", "numero": "1680A", "cidade": "Orlândia", "estado": "SP",
    # Com coordenadas no formulário a rota não chama o geocodificador externo.
    "latitude": "-20.72", "longitude": "-47.88",
}


@pytest.fixture()
def vet_id(app, client):
    with app.app_context():
        vet = User(name="Dra. Formatos", email="formatos.vet@example.com", worker="veterinario")
        vet.set_password("senha-segura")
        vet.veterinario = Veterinario(crmv="CRMV-FORMATOS")
        db.session.add(vet)
        db.session.commit()
        vet_id = vet.id
    with client.session_transaction() as session:
        session["_user_id"] = str(vet_id)
        session["_fresh"] = True
    return vet_id


def _tutor(app, vet_id, **campos) -> int:
    with app.app_context():
        dados = {"name": "Tutor Formatos", "email": "tutor.formatos@example.com", "added_by_id": vet_id}
        dados.update(campos)
        tutor = User(**dados)
        tutor.set_password("senha")
        db.session.add(tutor)
        db.session.commit()
        return tutor.id


def _salvar(client, tutor_id, **campos):
    return client.post(f"/update_tutor/{tutor_id}", data={**ENDERECO, **campos}, headers=JSON)


@pytest.mark.parametrize(
    "gravado, enviado",
    [
        ("362.430.268-09", "36243026809"),     # ficha gravou, consulta reenviou
        ("36243026809", "362.430.268-09"),     # consulta gravou, ficha reenviou
        ("99999", "99999"),                    # dado antigo fora do padrão
    ],
)
def test_cpf_ja_gravado_nunca_impede_o_salvamento(app, client, vet_id, gravado, enviado):
    tutor_id = _tutor(app, vet_id, cpf=gravado)

    resposta = _salvar(client, tutor_id, name="Nome Corrigido", cpf=enviado)

    assert resposta.status_code == 200, resposta.get_json()
    with app.app_context():
        tutor = db.session.get(User, tutor_id)
        assert tutor.name == "Nome Corrigido"
        assert tutor.cpf == gravado, "reenviar o mesmo CPF não pode regravar o dado"


@pytest.mark.parametrize(
    "gravado, enviado",
    [
        ("(16) 99269-0405", "16992690405"),
        ("16992690405", "(16) 99269-0405"),
        ("+5516992690405", "(16) 99269-0405"),  # importado da campanha de vacinação
        ("(16)992690405", "(16) 99269-0405"),
        ("999999999", "999999999"),             # dado antigo sem DDD
    ],
)
def test_telefone_ja_gravado_nunca_impede_o_salvamento(app, client, vet_id, gravado, enviado):
    tutor_id = _tutor(app, vet_id, phone=gravado)

    resposta = _salvar(client, tutor_id, name="Nome Corrigido", phone=enviado)

    assert resposta.status_code == 200, resposta.get_json()
    with app.app_context():
        tutor = db.session.get(User, tutor_id)
        assert tutor.name == "Nome Corrigido"
        assert tutor.phone == gravado, "o mesmo número não pode ser regravado em outro formato"


def test_cpf_e_telefone_novos_sao_gravados_sem_mascara(app, client, vet_id):
    tutor_id = _tutor(app, vet_id)

    resposta = _salvar(client, tutor_id, cpf="362.430.268-09", phone="(16) 99269-0405")

    assert resposta.status_code == 200, resposta.get_json()
    with app.app_context():
        tutor = db.session.get(User, tutor_id)
        assert tutor.cpf == "36243026809"
        assert tutor.phone == "16992690405"


def test_cpf_ou_telefone_incompleto_e_recusado_com_motivo(app, client, vet_id):
    tutor_id = _tutor(app, vet_id, cpf="36243026809", phone="16992690405")

    cpf = _salvar(client, tutor_id, cpf="362.430.268")
    assert cpf.status_code == 400
    assert "11 dígitos" in cpf.get_json()["message"]

    telefone = _salvar(client, tutor_id, phone="99269-0405")
    assert telefone.status_code == 400
    assert "DDD" in telefone.get_json()["message"]

    with app.app_context():
        tutor = db.session.get(User, tutor_id)
        assert (tutor.cpf, tutor.phone) == ("36243026809", "16992690405")


def test_email_de_outro_cadastro_vira_aviso_e_nao_erro_500(app, client, vet_id):
    """O caso do print: "Unexpected error." ao informar um e-mail já usado."""
    _tutor(app, vet_id, name="Daiane Primeira", email="Daiane@Example.com")
    tutor_id = _tutor(app, vet_id, name="Daiane Duplicada", email="tutor-sem-email-abc@nao-informado.petorlandia.invalid",
                      email_is_placeholder=True, cpf="36243026809")

    # A consulta envia o CPF junto: era a busca por ele que disparava o
    # autoflush com o e-mail repetido já no objeto.
    resposta = _salvar(client, tutor_id, email="daiane@example.com", cpf="362.430.268-00")

    assert resposta.status_code == 409
    corpo = resposta.get_json()
    assert corpo["success"] is False
    assert corpo["category"] == "warning"
    assert "Este e-mail já está no cadastro de Daiane Primeira" in corpo["message"]
    with app.app_context():
        tutor = db.session.get(User, tutor_id)
        assert tutor.email.startswith("tutor-sem-email-")
        assert tutor.cpf == "36243026809", "nada pode ser gravado quando o envio é recusado"


def test_cpf_de_outro_cadastro_e_recusado_ignorando_a_mascara(app, client, vet_id):
    _tutor(app, vet_id, name="Dono do CPF", email="dono@example.com", cpf="111.222.333-44")
    tutor_id = _tutor(app, vet_id, cpf="36243026809")

    resposta = _salvar(client, tutor_id, cpf="11122233344")

    assert resposta.status_code == 409
    assert "CPF já cadastrado para outro tutor" in resposta.get_json()["message"]
    with app.app_context():
        assert db.session.get(User, tutor_id).cpf == "36243026809"


def test_email_real_desmarca_o_identificador_interno(app, client, vet_id):
    tutor_id = _tutor(app, vet_id, email="tutor-sem-email-xyz@nao-informado.petorlandia.invalid",
                      email_is_placeholder=True)

    resposta = _salvar(client, tutor_id, email="  Novo.Email@Example.com ")

    assert resposta.status_code == 200, resposta.get_json()
    with app.app_context():
        tutor = db.session.get(User, tutor_id)
        assert tutor.email == "novo.email@example.com"
        assert tutor.email_is_placeholder is False
        assert tutor.email_informado == "novo.email@example.com"


def test_email_invalido_e_recusado_com_motivo(app, client, vet_id):
    tutor_id = _tutor(app, vet_id)

    resposta = _salvar(client, tutor_id, email="sem-arroba")

    assert resposta.status_code == 400
    assert "e-mail válido" in resposta.get_json()["message"]


def test_email_informado_decide_pelo_endereco_e_nao_pela_marca(app):
    """A coluna email_is_placeholder está desatualizada nos dois sentidos."""
    with app.app_context():
        real_marcado = User(name="A", email="real@gmail.com", email_is_placeholder=True)
        interno_sem_marca = User(name="B", email="pmo-5516999990000@petorlandia.local")
        assert real_marcado.email_informado == "real@gmail.com"
        assert interno_sem_marca.email_informado == ""


def test_ficha_do_tutor_mostra_os_dados_formatados_e_sem_formato_fixo(app, client, vet_id):
    tutor_id = _tutor(app, vet_id, cpf="36243026809", phone="+5516992690405", rg="12.345.678-X")

    resposta = client.get(f"/ficha_tutor/{tutor_id}")

    assert resposta.status_code == 200
    html = resposta.get_data(as_text=True)
    assert 'value="362.430.268-09"' in html
    assert 'value="(16) 99269-0405"' in html
    assert 'data-campo-br="cpf"' in html and 'data-campo-br="telefone"' in html
    assert "js/campos_br.js" in html
    assert "data-mask=" not in html


# --- rede de segurança global --------------------------------------------------

@pytest.mark.parametrize(
    "detalhe, esperado",
    [
        ('duplicate key value violates unique constraint "user_email_key"', "e-mail"),
        ("UNIQUE constraint failed: user.email", "e-mail"),
        ('duplicate key value violates unique constraint "user_cpf_key"', "CPF"),
        ("UNIQUE constraint failed: user.cpf", "CPF"),
    ],
)
def test_duplicata_conhecida_tem_mensagem_propria(detalhe, esperado):
    from request_hooks import _mensagem_de_dado_duplicado

    mensagem = _mensagem_de_dado_duplicado(IntegrityError("UPDATE", {}, Exception(detalhe)))
    assert mensagem and esperado in mensagem


def test_outros_erros_continuam_sendo_erro(app):
    from request_hooks import _mensagem_de_dado_duplicado

    assert _mensagem_de_dado_duplicado(ValueError("user_email_key")) is None
    outro = IntegrityError("INSERT", {}, Exception('violates foreign key constraint "animal_user_id_fkey"'))
    assert _mensagem_de_dado_duplicado(outro) is None
    nao_nulo = IntegrityError("INSERT", {}, Exception('null value in column "email" of relation "user"'))
    assert _mensagem_de_dado_duplicado(nao_nulo) is None


def test_rota_que_esquece_de_conferir_o_email_recebe_409_e_nao_500(app, client, vet_id):
    """`criar_tutor_ajax` grava sem tratar a corrida; a rede global cobre."""
    _tutor(app, vet_id, name="Dono do CPF", email="dono@example.com", cpf="36243026809")

    resposta = client.post(
        "/criar_tutor_ajax",
        data={"name": "Outro", "email": "outro@example.com", "cpf": "36243026809"},
        headers=JSON,
    )

    assert resposta.status_code == 409
    corpo = resposta.get_json()
    assert corpo["success"] is False
    assert "CPF já está em uso" in corpo["message"]
