"""Medição no GA4: tag, User-ID e eventos de funil enfileirados."""

from extensions import db
from models import User


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _tutor(email="ga-tutor@example.com"):
    user = User(name="Tutor GA", email=email, role="adotante")
    user.set_password("senha-forte-123")
    db.session.add(user)
    db.session.commit()
    return user


def test_sem_measurement_id_nenhum_script_de_analytics_e_carregado(app, client):
    app.config["GA_MEASUREMENT_ID"] = None

    html = client.get("/").get_data(as_text=True)

    assert "googletagmanager.com/gtag/js" not in html
    assert "gtag(" not in html


def test_visitante_anonimo_recebe_a_tag_sem_user_id(app, client):
    app.config["GA_MEASUREMENT_ID"] = "G-TESTE123"

    html = client.get("/").get_data(as_text=True)

    assert "googletagmanager.com/gtag/js?id=' + encodeURIComponent(measurementId)" in html
    assert 'data-analytics-accept' in html
    assert 'data-analytics-reject' in html
    assert "readChoice() !== 'granted'" in html
    assert "'anonymize_ip': true" in html
    # Sem login não há quem costurar: mandar user_id vazio sujaria o relatório.
    assert "user_id" not in html
    assert "user_properties" not in html


def test_usuario_logado_envia_user_id_e_papel(app, client):
    app.config["GA_MEASUREMENT_ID"] = "G-TESTE123"
    user = _tutor()
    _login(client, user.id)

    html = client.get("/").get_data(as_text=True)

    assert f"'user_id': \"{user.id}\"" in html
    assert "'user_role': \"adotante\"" in html


def test_ga4_nao_carrega_recurso_externo_antes_do_consentimento(app, client):
    app.config["GA_MEASUREMENT_ID"] = "G-TESTE123"

    html = client.get("/").get_data(as_text=True)

    assert '<script async src="https://www.googletagmanager.com/' not in html
    assert "localStorage.setItem(storageKey, value)" in html
    assert "setChoice('denied')" in html
    assert 'recusar não limita nenhuma função' in html


def test_politica_explicita_analytics_opcionais(app, client):
    html = client.get('/privacy').get_data(as_text=True)
    texto = ' '.join(html.split())

    assert 'Cookies e analytics' in texto
    assert 'só é carregado depois de uma escolha afirmativa' in texto
    assert 'Não enviamos ao Google nome, e-mail, telefone nem conteúdo clínico' in texto


def test_user_id_nunca_carrega_email_ou_nome(app, client):
    """O GA proíbe dado que identifique alguém — o id interno é o limite."""
    app.config["GA_MEASUREMENT_ID"] = "G-TESTE123"
    user = _tutor(email="pessoa.real@example.com")
    _login(client, user.id)

    html = client.get("/").get_data(as_text=True)
    bloco_gtag = html.split("gtag('js'")[1].split("</script>")[0]

    assert "pessoa.real@example.com" not in bloco_gtag
    assert "Tutor GA" not in bloco_gtag


def test_cadastro_dispara_sign_up_na_pagina_seguinte_e_uma_vez_so(app, client):
    app.config["GA_MEASUREMENT_ID"] = "G-TESTE123"

    resposta = client.post(
        "/register",
        data={
            "name": "Novo Tutor",
            "email": "novo-tutor@example.com",
            "password": "senha-forte-123",
            "confirm_password": "senha-forte-123",
        },
        follow_redirects=True,
    )
    html = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "gtag('event', \"sign_up\"" in html
    assert '"method": "email"' in html

    # A fila é drenada no primeiro render: recarregar não pode inflar a
    # contagem de conversões.
    seguinte = client.get("/").get_data(as_text=True)
    assert "sign_up" not in seguinte


def test_login_dispara_evento_login(app, client):
    app.config["GA_MEASUREMENT_ID"] = "G-TESTE123"
    _tutor(email="volta@example.com")

    resposta = client.post(
        "/login",
        data={"email": "volta@example.com", "password": "senha-forte-123"},
        follow_redirects=True,
    )
    html = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "gtag('event', \"login\"" in html
    assert '"method": "email"' in html


def test_fila_nao_acumula_eventos_indefinidamente(app):
    """Uma sessão que só chama API não pode despejar um histórico depois."""
    from services.product_analytics import pop_ga_events, queue_ga_event

    with app.test_request_context("/"):
        for indice in range(12):
            queue_ga_event("login", method=f"tentativa-{indice}")

        eventos = pop_ga_events()

    assert len(eventos) == 5
    assert eventos[-1]["params"]["method"] == "tentativa-11"
    assert eventos[0]["params"]["method"] == "tentativa-7"


def test_fila_vazia_nao_emite_nada(app, client):
    app.config["GA_MEASUREMENT_ID"] = "G-TESTE123"

    html = client.get("/").get_data(as_text=True)

    assert "gtag('event'" not in html
