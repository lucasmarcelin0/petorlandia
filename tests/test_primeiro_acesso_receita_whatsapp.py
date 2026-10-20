"""Tutor que recebe a receita pelo WhatsApp precisa conseguir abri-la.

Caso real: a clínica cadastrou a tutora sem e-mail, mandou a receita pelo
WhatsApp e ela não conseguiu abrir — o link ia para o login, e o primeiro
acesso pelo celular respondia que ela "não tinha primeiro acesso ativo".
Estes testes travam as três portas que resolvem isso:

1. o link enviado no WhatsApp leva o token assinado do tutor e abre a receita;
2. o primeiro acesso pelo celular aceita quem foi cadastrado sem e-mail;
3. o login, quando a pessoa vem de uma receita, mostra o primeiro acesso em
   destaque — e os erros sempre dizem qual é o próximo passo.
"""

from extensions import db
from models import Animal, BlocoPrescricao, Clinica, User, Veterinario
from models.usuarios import build_placeholder_email


def _reset_db():
    db.drop_all()
    db.create_all()


def _criar_receita(*, tutor_email, tutor_phone="16991234567", tutor_password=None):
    clinica = Clinica(nome="Clinica Teste")
    db.session.add(clinica)
    db.session.flush()

    vet = User(name="Vet", email="vet@example.com", worker="veterinario", role="admin")
    vet.set_password("pw-vet")
    db.session.add(vet)
    db.session.flush()
    db.session.add(Veterinario(user=vet, crmv="SP-1", clinica=clinica))

    tutor = User(name="Vilma Souza", email=tutor_email, phone=tutor_phone)
    # Tutor cadastrado pela clínica: ninguém conhece a senha dele.
    tutor.set_password(tutor_password or "senha-aleatoria-que-ninguem-sabe")
    animal = Animal(name="Simba", owner=tutor, clinica=clinica)
    db.session.add_all([tutor, animal])
    db.session.flush()

    bloco = BlocoPrescricao(animal=animal, saved_by=vet, clinica=clinica)
    db.session.add(bloco)
    db.session.commit()
    return bloco.id, tutor.id


def _login(client, email, password):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)


def test_link_do_whatsapp_leva_token_e_abre_a_receita_sem_senha(app):
    with app.app_context():
        _reset_db()
        bloco_id, tutor_id = _criar_receita(tutor_email=build_placeholder_email())

    vet_client = app.test_client()
    _login(vet_client, "vet@example.com", "pw-vet")
    html = vet_client.get(f"/bloco_prescricao/{bloco_id}/imprimir").get_data(as_text=True)

    # O link curto que vai na mensagem do WhatsApp agora carrega o token.
    import json
    import re

    match = re.search(r"const shortPrescriptionUrl = (\".*?\");", html)
    assert match, "link curto da receita não foi renderizado"
    link = json.loads(match.group(1))
    assert f"/r/{bloco_id}?token=" in link

    # A tutora, sem conta, sem senha e sem e-mail, abre o link e vê a receita.
    tutora = app.test_client()
    caminho = link.split("://", 1)[-1].split("/", 1)[1]
    resp = tutora.get("/" + caminho, follow_redirects=True)
    assert resp.status_code == 200
    corpo = resp.get_data(as_text=True)
    assert "Simba" in corpo

    # E continua conectada: a próxima página (sem token) também abre, que é o
    # que permite seguir para o carrinho e o pagamento.
    resp = tutora.get(f"/bloco_prescricao/{bloco_id}/imprimir")
    assert resp.status_code == 200
    assert "Simba" in resp.get_data(as_text=True)


def test_token_de_outro_tutor_nao_abre_a_receita(app):
    with app.app_context():
        _reset_db()
        bloco_id, _ = _criar_receita(tutor_email=build_placeholder_email())
        intruso = User(name="Outro", email="outro@example.com", phone="16990000000")
        intruso.set_password("x")
        db.session.add(intruso)
        db.session.commit()

        from app import _first_access_token_for_user

        token_alheio = _first_access_token_for_user(intruso)

    client = app.test_client()
    corpo = client.get(f"/r/{bloco_id}?token={token_alheio}", follow_redirects=True).get_data(as_text=True)
    assert "Simba" not in corpo
    with client.session_transaction() as sessao:
        assert "_user_id" not in sessao


def test_primeiro_acesso_por_celular_aceita_tutor_cadastrado_sem_email(app):
    """O e-mail interno de quem foi cadastrado sem e-mail não pode travar o acesso."""
    with app.app_context():
        _reset_db()
        bloco_id, tutor_id = _criar_receita(
            tutor_email=build_placeholder_email(),
            tutor_phone="16991234567",
        )

    client = app.test_client()
    destino = f"/bloco_prescricao/{bloco_id}/imprimir"
    resp = client.post(
        f"/primeiro-acesso?next={destino}",
        data={"phone": "(16) 99123-4567", "next": destino},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/primeiro-acesso/senha")

    resp = client.post(
        "/primeiro-acesso/senha",
        data={"email": "", "password": "minhasenha", "confirm_password": "minhasenha"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(destino)

    corpo = client.get(destino).get_data(as_text=True)
    assert "Simba" in corpo
    with client.session_transaction() as sessao:
        assert sessao.get("_user_id") == str(tutor_id)


def test_primeiro_acesso_continua_bloqueado_para_conta_com_email_real(app):
    """A correção não abre contas com e-mail real a quem só sabe o celular."""
    with app.app_context():
        _reset_db()
        _criar_receita(tutor_email="vilma@example.com", tutor_phone="16991234567")

    client = app.test_client()
    resp = client.post("/primeiro-acesso", data={"phone": "16991234567"})
    assert resp.status_code == 200
    corpo = resp.get_data(as_text=True)
    assert "Esqueceu sua senha?" in corpo
    with client.session_transaction() as sessao:
        assert "first_access_user_id" not in sessao


def test_primeiro_acesso_nao_revela_se_o_celular_tem_conta(app):
    """Celular com conta bloqueada e celular sem conta recebem a mesma resposta."""
    with app.app_context():
        _reset_db()
        _criar_receita(tutor_email="vilma@example.com", tutor_phone="16991234567")

    com_conta = app.test_client().post("/primeiro-acesso", data={"phone": "16991234567"}).get_data(as_text=True)
    sem_conta = app.test_client().post("/primeiro-acesso", data={"phone": "16990001111"}).get_data(as_text=True)

    mensagem = "Não foi possível liberar o primeiro acesso para este celular."
    assert mensagem in com_conta
    assert mensagem in sem_conta
    assert "Confira o número" in sem_conta
    assert "já está ligado" not in com_conta
    assert "Não encontramos uma conta" not in sem_conta


def test_so_o_celular_nao_troca_a_senha_de_quem_ja_entrou(app):
    """Depois do primeiro acesso, saber o número não basta para trocar a senha."""
    with app.app_context():
        _reset_db()
        bloco_id, tutor_id = _criar_receita(
            tutor_email=build_placeholder_email(),
            tutor_phone="16991234567",
        )

    tutora = app.test_client()
    tutora.post("/primeiro-acesso", data={"phone": "16991234567"})
    tutora.post(
        "/primeiro-acesso/senha",
        data={"email": "", "password": "senhadavilma", "confirm_password": "senhadavilma"},
    )

    # Nos testes as requisições compartilham o app context da fixture, e o
    # Flask-Login guarda o usuário logado em ``g``: sem limpar, o próximo
    # cliente "herdaria" a tutora. Em produção cada requisição tem o seu ``g``.
    from flask import g

    g.pop("_login_user", None)

    # Outra pessoa, que só sabe o celular, tenta o primeiro acesso de novo.
    estranho = app.test_client()
    resp = estranho.post("/primeiro-acesso", data={"phone": "16991234567"})
    assert resp.status_code == 200
    assert "Não foi possível liberar o primeiro acesso" in resp.get_data(as_text=True)
    with estranho.session_transaction() as sessao:
        assert "first_access_user_id" not in sessao

    with app.app_context():
        tutor = db.session.get(User, tutor_id)
        assert tutor.check_password("senhadavilma")

        from app import _first_access_token_for_user

        token = _first_access_token_for_user(tutor)

    # Com o link assinado que a clínica envia, a própria tutora ainda consegue
    # refazer a senha se esquecer.
    g.pop("_login_user", None)
    reenvio = app.test_client()
    resp = reenvio.post(f"/primeiro-acesso?token={token}", data={"phone": "16991234567", "token": token})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/primeiro-acesso/senha")


def test_login_vindo_da_receita_destaca_primeiro_acesso(app):
    with app.app_context():
        _reset_db()

    client = app.test_client()
    corpo = client.get("/login?next=/bloco_prescricao/4324/imprimir").get_data(as_text=True)
    assert "data-first-access-hint" in corpo
    assert "Primeiro acesso com meu celular" in corpo

    corpo_comum = client.get("/login").get_data(as_text=True)
    assert "data-first-access-hint" not in corpo_comum
