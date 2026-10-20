"""Link de receita/tratamento aberto sem a chave de acesso.

Caso real: a tutora abriu um link antigo (/r/<id>, sem token) e caiu num
login que pedia uma senha que ela nunca criou; no primeiro acesso, o celular
dela "não existia". Estes testes travam o fluxo que resolve isso:

- sem chave, a pessoa cai no primeiro acesso já no contexto da receita, com
  três saídas: confirmar o celular, entrar com senha ou pedir à clínica um
  link novo pelo WhatsApp;
- o celular é reconhecido mesmo digitado sem o 9, sem DDD ou com +55;
- nada disso abre a receita ou a conta sem o fluxo de confirmação.
"""

from urllib.parse import parse_qs, unquote, urlparse

from flask import g

from extensions import db
from models import Animal, BlocoPrescricao, Clinica, User
from models.usuarios import build_placeholder_email


def _reset_db():
    db.drop_all()
    db.create_all()


def _criar_receita(*, tutor_phone="16991234567", tutor_email=None, clinic_phone="(16) 3826-1234"):
    clinica = Clinica(nome="Clinica Vida Animal", telefone=clinic_phone)
    db.session.add(clinica)
    db.session.flush()

    tutor = User(name="Vilma Souza", email=tutor_email or build_placeholder_email(), phone=tutor_phone)
    tutor.set_password("senha-que-ninguem-sabe")
    animal = Animal(name="Simba", owner=tutor, clinica=clinica)
    db.session.add_all([tutor, animal])
    db.session.flush()

    bloco = BlocoPrescricao(animal=animal, clinica=clinica)
    db.session.add(bloco)
    db.session.commit()
    return bloco.id, tutor.id


def _logout_shared_context():
    # Nos testes as requisições compartilham o app context da fixture; o
    # Flask-Login guarda o usuário em ``g``. Em produção cada requisição tem o seu.
    g.pop("_login_user", None)


def test_link_sem_chave_leva_ao_primeiro_acesso_da_receita(app):
    with app.app_context():
        _reset_db()
        bloco_id, _ = _criar_receita()

    client = app.test_client()
    resp = client.get(f"/r/{bloco_id}", follow_redirects=False)
    resp = client.get(resp.headers["Location"], follow_redirects=False)
    assert resp.status_code == 302
    destino = urlparse(resp.headers["Location"])
    assert destino.path == "/primeiro-acesso"
    assert parse_qs(destino.query)["next"] == [f"/bloco_prescricao/{bloco_id}/imprimir"]

    corpo = client.get(resp.headers["Location"]).get_data(as_text=True)
    # Contexto da receita e as três saídas.
    assert "Para abrir a receita de Clinica Vida Animal" in corpo
    assert "Pedir novo link à clínica" in corpo
    assert "Já tenho senha — entrar" in corpo
    # Sem chave, nada do tutor nem do pet aparece.
    assert "Simba" not in corpo
    assert "Vilma" not in corpo
    with client.session_transaction() as sessao:
        assert "_user_id" not in sessao


def test_botao_da_clinica_pede_novo_link_pelo_whatsapp(app):
    with app.app_context():
        _reset_db()
        bloco_id, _ = _criar_receita(clinic_phone="(16) 3826-1234")

    corpo = app.test_client().get(
        f"/primeiro-acesso?next=/bloco_prescricao/{bloco_id}/imprimir"
    ).get_data(as_text=True)
    assert "https://wa.me/551638261234?text=" in corpo
    texto = unquote(corpo.split("https://wa.me/551638261234?text=", 1)[1].split('"', 1)[0])
    assert f"receita nº {bloco_id}" in texto
    assert "reenviar o link" in texto


def test_link_expirado_avisa_e_nao_entra(app):
    with app.app_context():
        _reset_db()
        bloco_id, _ = _criar_receita()

    client = app.test_client()
    resp = client.get(f"/bloco_prescricao/{bloco_id}/imprimir?token=token-velho-invalido", follow_redirects=True)
    corpo = resp.get_data(as_text=True)
    assert "Este link de acesso expirou ou é inválido" in corpo
    assert "Simba" not in corpo
    with client.session_transaction() as sessao:
        assert "_user_id" not in sessao


def test_primeiro_acesso_da_receita_completa_e_abre_a_receita(app):
    """Do link sem chave até a receita aberta, digitando o celular sem DDD."""
    with app.app_context():
        _reset_db()
        bloco_id, tutor_id = _criar_receita(tutor_phone="(16) 99123-4567")

    client = app.test_client()
    destino = f"/bloco_prescricao/{bloco_id}/imprimir"
    resp = client.post(
        f"/primeiro-acesso?next={destino}",
        data={"phone": "99123-4567", "next": destino},  # sem DDD: usa o da clínica
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/primeiro-acesso/senha")

    resp = client.post(
        "/primeiro-acesso/senha",
        data={"email": "", "password": "senhadavilma", "confirm_password": "senhadavilma"},
    )
    assert resp.headers["Location"].endswith(destino)
    corpo = client.get(destino).get_data(as_text=True)
    assert "Simba" in corpo
    with client.session_transaction() as sessao:
        assert sessao.get("_user_id") == str(tutor_id)


def test_celular_sem_o_nove_e_reconhecido(app):
    """Cadastro antigo sem o 9 da frente; a tutora digita com o 9."""
    with app.app_context():
        _reset_db()
        bloco_id, _ = _criar_receita(tutor_phone="(16) 9123-4567")

    destino = f"/bloco_prescricao/{bloco_id}/imprimir"
    resp = app.test_client().post(
        f"/primeiro-acesso?next={destino}",
        data={"phone": "+55 (16) 99123-4567", "next": destino},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/primeiro-acesso/senha")


def test_sem_ddd_e_sem_contexto_pede_o_ddd(app):
    with app.app_context():
        _reset_db()

    corpo = app.test_client().post("/primeiro-acesso", data={"phone": "99123-4567"}).get_data(as_text=True)
    assert "Faltou o DDD" in corpo


def test_falha_no_primeiro_acesso_destaca_pedir_link_a_clinica(app):
    with app.app_context():
        _reset_db()
        bloco_id, _ = _criar_receita(tutor_email="vilma@example.com")

    destino = f"/bloco_prescricao/{bloco_id}/imprimir"
    corpo = app.test_client().post(
        f"/primeiro-acesso?next={destino}",
        data={"phone": "16991234567", "next": destino},
    ).get_data(as_text=True)
    assert "Não foi possível liberar o primeiro acesso" in corpo
    assert "Não conseguiu entrar?" in corpo
    assert "Pedir novo link à clínica" in corpo


def test_variante_do_nove_nao_vale_para_checagem_de_cadastro(app):
    """A tolerância é só para entrar: checar 'celular já usado' segue exato."""
    with app.app_context():
        _reset_db()
        _criar_receita(tutor_phone="(16) 9123-4567")
        from app import find_users_by_phone

        assert find_users_by_phone("16991234567") == []
        assert len(find_users_by_phone("16991234567", tolerant=True)) == 1


def test_grafia_exata_vence_a_variante(app):
    with app.app_context():
        _reset_db()
        exato = User(name="Exato", email="exato@example.com", phone="16991234567")
        variante = User(name="Variante", email="variante@example.com", phone="1691234567")
        for u in (exato, variante):
            u.set_password("x")
        db.session.add_all([exato, variante])
        db.session.commit()
        from app import find_users_by_phone

        achados = find_users_by_phone("(16) 99123-4567", tolerant=True)
        assert [u.name for u in achados] == ["Exato"]


def test_login_com_celular_sem_o_nove(app):
    with app.app_context():
        _reset_db()
        user = User(name="Ana", email="ana@example.com", phone="1691234567")
        user.set_password("senha-da-ana")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _logout_shared_context()
    client = app.test_client()
    client.post("/login", data={"login": "(16) 99123-4567", "password": "senha-da-ana"})
    with client.session_transaction() as sessao:
        assert sessao.get("_user_id") == str(user_id)
