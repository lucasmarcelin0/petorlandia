"""Régua dos anúncios de adoção: e-mails, tela de confirmação e pop-up mensal.

As três frentes usam as mesmas regras (services/adocao_lembretes.py); os
testes abaixo cobrem cada uma e, principalmente, que elas concordam sobre
quando um anúncio está "vencido".
"""

from datetime import timedelta
from io import BytesIO

import pytest

from extensions import db
from models import Animal, Notification, User
from services import adocao_lembretes
from time_utils import now_in_brazil


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _user(name='Doadora', email=None, phone=None) -> User:
    user = User(
        name=name,
        email=email or f'{name.lower().replace(" ", "-")}@example.test',
        password_hash='x',
        role='adotante',
        phone=phone,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _animal(owner, name='Luna', days=0, image=None, modo='doação', **extra) -> Animal:
    animal = Animal(
        name=name,
        modo=modo,
        status='disponível',
        user_id=owner.id,
        image=image,
        date_added=now_in_brazil() - timedelta(days=days),
        **extra,
    )
    db.session.add(animal)
    db.session.commit()
    return animal


@pytest.fixture()
def outbox(app, monkeypatch):
    """Captura o que o job tentaria enviar, sem SMTP."""
    sent = []

    def fake_send(recipients, subject, body):
        sent.append({'to': recipients, 'subject': subject, 'body': body})
        return True

    monkeypatch.setattr('services.notifications._send_email', fake_send)
    return sent


# ------------------------------------------------- e-mail: foto e telefone


def test_pede_foto_e_telefone_uma_unica_vez(app, outbox):
    with app.app_context():
        owner = _user()
        _animal(owner, 'Mel', days=2)

        adocao_lembretes.enviar_lembretes_adocao()

        assert len(outbox) == 1
        message = outbox[0]
        assert message['to'] == ['doadora@example.test']
        assert 'Complete o anúncio de Mel' in message['subject']
        assert 'Mel ainda está sem foto' in message['body']
        assert 'sem telefone' in message['body']
        assert '/adocao/revisar' in message['body']
        registro = Notification.query.filter_by(user_id=owner.id).one()
        assert registro.kind == adocao_lembretes.KIND_DATA_REQUEST

        adocao_lembretes.enviar_lembretes_adocao()
        assert len(outbox) == 1


def test_pedido_so_cita_o_que_falta(app, outbox):
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        _animal(owner, 'Mel', days=2)
        _animal(owner, 'Pirata', days=2, image='https://cdn.test/pirata.jpg')

        adocao_lembretes.enviar_lembretes_adocao()

        body = outbox[0]['body']
        assert 'Mel ainda está sem foto' in body
        assert 'Pirata ainda' not in body
        assert 'Telefone' not in body


def test_anuncio_completo_nao_recebe_pedido(app, outbox):
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        _animal(owner, 'Pirata', days=2, image='https://cdn.test/pirata.jpg')

        adocao_lembretes.enviar_lembretes_adocao()

        assert outbox == []


def test_cadastro_de_agora_ganha_carencia(app, outbox):
    with app.app_context():
        owner = _user()
        _animal(owner, 'Mel', days=0)

        adocao_lembretes.enviar_lembretes_adocao()

        assert outbox == []


# ------------------------------------------------------ e-mail: mensal


def test_pergunta_mensal_avisa_o_prazo_e_nao_repete(app, outbox):
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        animal = _animal(owner, 'Pirata', days=31, image='https://cdn.test/pirata.jpg')
        hoje = now_in_brazil()
        prazo = (hoje + timedelta(days=adocao_lembretes.EXPIRY_GRACE_DAYS)).strftime('%d/%m')

        adocao_lembretes.enviar_lembretes_adocao(hoje)
        assert len(outbox) == 1
        assert outbox[0]['subject'].startswith('Pirata ainda está para adoção?')
        assert 'há 31 dias' in outbox[0]['body']
        assert f'Se não tivermos resposta até {prazo}' in outbox[0]['body']
        assert 'Aproveite para completar' not in outbox[0]['body']

        # Até o último dia do prazo nada muda e ninguém é cobrado de novo.
        adocao_lembretes.enviar_lembretes_adocao(hoje + timedelta(days=1))
        adocao_lembretes.enviar_lembretes_adocao(hoje + timedelta(days=15))
        assert len(outbox) == 1
        assert db.session.get(Animal, animal.id).modo == 'doação'


def test_sem_resposta_no_prazo_o_anuncio_sai_da_lista(app, outbox):
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        animal = _animal(owner, 'Pirata', days=31, image='https://cdn.test/pirata.jpg')
        hoje = now_in_brazil()

        adocao_lembretes.enviar_lembretes_adocao(hoje)
        resultado = adocao_lembretes.enviar_lembretes_adocao(hoje + timedelta(days=16))

        animal = db.session.get(Animal, animal.id)
        assert animal.modo == 'adotado'
        assert animal.status == 'indisponível'
        assert animal.adocao_expirada_em is not None
        assert animal.user_id == owner.id
        assert adocao_lembretes.adoption_listings_query().count() == 0
        assert resultado[adocao_lembretes.KIND_EXPIRED] == 1
        assert len(outbox) == 2
        assert outbox[1]['subject'] == 'Tiramos Pirata da lista de adoção — PetOrlândia'
        assert '/adocao/revisar' in outbox[1]['body']

        adocao_lembretes.enviar_lembretes_adocao(hoje + timedelta(days=17))
        adocao_lembretes.enviar_lembretes_adocao(hoje + timedelta(days=60))
        assert len(outbox) == 2


def test_anuncio_antigo_nao_some_sem_aviso(app, outbox):
    """No dia em que a régua entra no ar, anúncio velho é perguntado, não removido."""
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        animal = _animal(owner, 'Pirata', days=200, image='https://cdn.test/pirata.jpg')

        adocao_lembretes.enviar_lembretes_adocao()

        assert db.session.get(Animal, animal.id).modo == 'doação'
        assert len(outbox) == 1
        assert outbox[0]['subject'].startswith('Pirata ainda está para adoção?')


def test_confirmacao_renova_o_anuncio_por_um_mes(app, outbox):
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        animal = _animal(owner, 'Pirata', days=31, image='https://cdn.test/pirata.jpg')
        hoje = now_in_brazil()

        adocao_lembretes.enviar_lembretes_adocao(hoje)
        adocao_lembretes.confirm_still_available(animal, hoje + timedelta(days=5))
        db.session.commit()

        adocao_lembretes.enviar_lembretes_adocao(hoje + timedelta(days=16))
        adocao_lembretes.enviar_lembretes_adocao(hoje + timedelta(days=34))
        assert len(outbox) == 1
        assert db.session.get(Animal, animal.id).modo == 'doação'

        adocao_lembretes.enviar_lembretes_adocao(hoje + timedelta(days=35))
        assert len(outbox) == 2
        assert outbox[1]['subject'].startswith('Pirata ainda está para adoção?')


def test_sem_email_o_prazo_conta_de_quando_o_popup_passou_a_perguntar(app, client, outbox):
    """Conta da campanha não recebe e-mail, mas tem o mesmo prazo de todo mundo."""
    with app.app_context():
        campanha = _user('Campanha', email='pmo-16999990001@petorlandia.local')
        animal = _animal(campanha, 'Lupita', days=50)
        hoje = now_in_brazil()
        prazo = (hoje + timedelta(days=adocao_lembretes.EXPIRY_GRACE_DAYS)).strftime('%d/%m')
        owner_id, animal_id = campanha.id, animal.id

        adocao_lembretes.enviar_lembretes_adocao(hoje)
        adocao_lembretes.enviar_lembretes_adocao(hoje + timedelta(days=15))
        assert db.session.get(Animal, animal_id).modo == 'doação'

    _login(client, owner_id)
    assert f'Sem resposta até {prazo}, o anúncio sai da lista.' in client.get('/animals').data.decode()

    with app.app_context():
        adocao_lembretes.enviar_lembretes_adocao(hoje + timedelta(days=16))

        animal = db.session.get(Animal, animal_id)
        assert animal.modo == 'adotado'
        assert animal.adocao_expirada_em is not None
        assert outbox == []


def test_mensal_leva_o_pedido_de_foto_e_nao_duplica_no_dia_seguinte(app, outbox):
    with app.app_context():
        owner = _user()
        _animal(owner, 'Pirata', days=40, image='https://cdn.test/pirata.jpg')
        _animal(owner, 'Mel', days=3)
        hoje = now_in_brazil()

        adocao_lembretes.enviar_lembretes_adocao(hoje)

        assert len(outbox) == 1
        assert outbox[0]['subject'].startswith('Pirata ainda está para adoção?')
        assert 'Mel ainda está sem foto' in outbox[0]['body']
        assert 'sem telefone' in outbox[0]['body']

        adocao_lembretes.enviar_lembretes_adocao(hoje + timedelta(days=1))
        assert len(outbox) == 1


def test_confirmar_reinicia_a_contagem(app, outbox):
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        animal = _animal(owner, 'Pirata', days=45, image='https://cdn.test/pirata.jpg')
        assert adocao_lembretes.pending_reviews(owner) == [animal]

        adocao_lembretes.confirm_still_available(animal)
        db.session.commit()

        assert adocao_lembretes.pending_reviews(owner) == []
        adocao_lembretes.enviar_lembretes_adocao()
        assert outbox == []


def test_email_provisorio_e_conta_de_teste_nao_recebem(app, outbox):
    with app.app_context():
        campanha = _user('Campanha', email='pmo-16999990001@petorlandia.local')
        convite = _user('Convite', email='x@convite.petorlandia.local')
        teste = _user('Teste')
        teste.is_test_account = True
        for owner in (campanha, convite, teste):
            _animal(owner, f'Pet de {owner.name}', days=40)

        adocao_lembretes.enviar_lembretes_adocao()

        assert outbox == []


def test_falha_no_envio_tenta_de_novo_no_dia_seguinte(app, monkeypatch):
    with app.app_context():
        owner = _user()
        animal = _animal(owner, 'Mel', days=45)
        monkeypatch.setattr('services.notifications._send_email', lambda *a, **k: False)

        adocao_lembretes.enviar_lembretes_adocao()

        animal = db.session.get(Animal, animal.id)
        assert animal.adocao_lembrete_em is None
        assert animal.adocao_pedido_dados_em is None
        assert Notification.query.count() == 0


def test_so_anuncio_no_ar_entra_na_regua(app, outbox):
    with app.app_context():
        owner = _user()
        _animal(owner, 'Meu pet', days=45, modo='adotado')
        _animal(owner, 'Removido', days=45, removido_em=now_in_brazil())
        _animal(owner, 'Falecido', days=45, is_alive=False)

        adocao_lembretes.enviar_lembretes_adocao()

        assert outbox == []
        assert adocao_lembretes.listings_of(owner) == []


def test_voltar_para_adocao_reinicia_a_contagem(app):
    with app.app_context():
        owner = _user()
        animal = _animal(owner, 'Antigo', days=400, modo='adotado')

        animal = db.session.get(Animal, animal.id)
        animal.modo = 'doação'
        db.session.commit()

        assert adocao_lembretes.pending_reviews(owner) == []


# ------------------------------------------------------- tela de revisão


def test_revisao_exige_login(app, client):
    response = client.get('/adocao/revisar')
    assert response.status_code in (301, 302)
    assert '/login' in response.headers['Location']


def test_tela_lista_os_anuncios_e_pede_telefone(app, client):
    with app.app_context():
        owner = _user()
        _animal(owner, 'Mel', days=2)
        owner_id = owner.id

    _login(client, owner_id)
    body = client.get('/adocao/revisar').data.decode()

    assert 'Seus animais para adoção' in body
    assert 'Mel' in body
    assert 'name="telefone"' in body
    assert 'Colocar uma foto' in body
    # A tela já é o formulário; o pop-up por cima seria redundante.
    assert 'id="adoptionReviewModal"' not in body


def test_ainda_disponivel_confirma_o_anuncio(app, client):
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        animal = _animal(owner, 'Pirata', days=45)
        owner_id, animal_id = owner.id, animal.id

    _login(client, owner_id)
    response = client.post('/adocao/revisar', data={
        'animal_id': str(animal_id),
        f'resposta_{animal_id}': 'disponivel',
        'next': '/animals',
    })

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/animals')
    with app.app_context():
        animal = db.session.get(Animal, animal_id)
        assert animal.modo == 'doação'
        assert animal.adocao_revisada_em is not None
        assert adocao_lembretes.pending_reviews(db.session.get(User, owner_id)) == []


def test_ja_foi_adotado_tira_o_anuncio_do_ar(app, client):
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        animal = _animal(owner, 'Pirata', days=45)
        owner_id, animal_id = owner.id, animal.id

    _login(client, owner_id)
    client.post('/adocao/revisar', data={
        'animal_id': str(animal_id),
        f'resposta_{animal_id}': 'adotado',
    })

    with app.app_context():
        animal = db.session.get(Animal, animal_id)
        assert animal.modo == 'adotado'
        assert animal.status == 'indisponível'
        assert animal.user_id == owner_id
        assert adocao_lembretes.adoption_listings_query().count() == 0


def test_nao_altera_anuncio_de_outra_pessoa(app, client):
    with app.app_context():
        dona = _user('Dona', phone='(16) 99999-0001')
        intruso = _user('Intruso', phone='(16) 99999-0002')
        animal = _animal(dona, 'Pirata', days=45)
        intruso_id, animal_id = intruso.id, animal.id

    _login(client, intruso_id)
    client.post('/adocao/revisar', data={
        'animal_id': str(animal_id),
        f'resposta_{animal_id}': 'adotado',
    })

    with app.app_context():
        animal = db.session.get(Animal, animal_id)
        assert animal.modo == 'doação'
        assert animal.adocao_revisada_em is None


def test_foto_nova_substitui_a_antiga_e_confirma(app, client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(
        app_module, 'upload_to_s3', lambda file, filename, folder='uploads', **kw: 'https://cdn.test/nova.jpg'
    )
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        animal = _animal(owner, 'Pirata', days=45, image='https://cdn.test/velha.jpg')
        owner_id, animal_id = owner.id, animal.id

    _login(client, owner_id)
    response = client.post('/adocao/revisar', data={
        'animal_id': str(animal_id),
        f'foto_{animal_id}': (BytesIO(b'fake-image'), 'pirata.jpg'),
    }, content_type='multipart/form-data', follow_redirects=True)

    assert 'Foto nova de Pirata salva.' in response.data.decode()
    with app.app_context():
        animal = db.session.get(Animal, animal_id)
        assert animal.image == 'https://cdn.test/nova.jpg'
        assert animal.adocao_revisada_em is not None


def test_arquivo_que_nao_e_imagem_e_recusado(app, client, monkeypatch):
    import app as app_module

    chamadas = []
    monkeypatch.setattr(
        app_module, 'upload_to_s3', lambda *a, **kw: chamadas.append(a) or 'https://cdn.test/x'
    )
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        animal = _animal(owner, 'Pirata', days=45)
        owner_id, animal_id = owner.id, animal.id

    _login(client, owner_id)
    client.post('/adocao/revisar', data={
        'animal_id': str(animal_id),
        f'foto_{animal_id}': (BytesIO(b'%PDF-1.4'), 'contrato.pdf'),
    }, content_type='multipart/form-data')

    assert chamadas == []
    with app.app_context():
        animal = db.session.get(Animal, animal_id)
        assert animal.image is None
        assert animal.adocao_revisada_em is None


def test_telefone_e_salvo_normalizado(app, client):
    with app.app_context():
        owner = _user()
        _animal(owner, 'Mel', days=2)
        owner_id = owner.id

    _login(client, owner_id)
    client.post('/adocao/revisar', data={'telefone': '16 99999-0001'})

    with app.app_context():
        from document_utils import same_phone

        assert same_phone(db.session.get(User, owner_id).phone, '(16) 99999-0001')


def test_telefone_invalido_ou_de_outra_conta_nao_e_salvo(app, client):
    with app.app_context():
        _user('Outra', phone='(16) 99999-0001')
        owner = _user()
        _animal(owner, 'Mel', days=2)
        owner_id = owner.id

    _login(client, owner_id)
    client.post('/adocao/revisar', data={'telefone': '123'})
    client.post('/adocao/revisar', data={'telefone': '(16) 99999-0001'})

    with app.app_context():
        assert not db.session.get(User, owner_id).phone


# ------------------------------------------------------------- pop-up


def test_popup_aparece_depois_de_um_mes_e_some_ao_responder(app, client):
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        animal = _animal(owner, 'Pirata', days=31)
        owner_id, animal_id = owner.id, animal.id

    _login(client, owner_id)
    body = client.get('/animals').data.decode()
    assert 'id="adoptionReviewModal"' in body
    assert 'Pirata ainda está para adoção?' in body
    assert f'name="resposta_{animal_id}"' in body
    assert f'name="foto_{animal_id}"' in body
    # Com telefone cadastrado o pop-up não pede de novo.
    assert 'name="telefone"' not in body

    client.post('/adocao/revisar', data={
        'animal_id': str(animal_id),
        f'resposta_{animal_id}': 'disponivel',
        'next': '/animals',
    })

    assert 'id="adoptionReviewModal"' not in client.get('/animals').data.decode()


def test_popup_nao_aparece_antes_de_um_mes_nem_para_visitante(app, client):
    with app.app_context():
        owner = _user()
        _animal(owner, 'Mel', days=10)
        owner_id = owner.id

    assert 'id="adoptionReviewModal"' not in client.get('/animals').data.decode()
    _login(client, owner_id)
    assert 'id="adoptionReviewModal"' not in client.get('/animals').data.decode()


def test_popup_pede_telefone_quando_falta(app, client):
    with app.app_context():
        owner = _user()
        _animal(owner, 'Mel', days=31)
        _animal(owner, 'Luna', days=35)
        owner_id = owner.id

    _login(client, owner_id)
    body = client.get('/animals').data.decode()

    assert 'Seus animais ainda estão para adoção?' in body
    assert 'name="telefone"' in body


def test_popup_mostra_o_prazo_depois_da_pergunta(app, client, outbox):
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        _animal(owner, 'Pirata', days=31)
        hoje = now_in_brazil()
        adocao_lembretes.enviar_lembretes_adocao(hoje)
        prazo = (hoje + timedelta(days=adocao_lembretes.EXPIRY_GRACE_DAYS)).strftime('%d/%m')
        owner_id = owner.id

    _login(client, owner_id)
    body = client.get('/animals').data.decode()

    assert f'Sem resposta até {prazo}, o anúncio sai da lista.' in body


def _anuncio_fora_da_lista(owner, name='Pirata'):
    """Anúncio perguntado há mais de 15 dias e já retirado pelo job."""
    animal = _animal(owner, name, days=60)
    hoje = now_in_brazil()
    adocao_lembretes.enviar_lembretes_adocao(hoje - timedelta(days=20))
    adocao_lembretes.enviar_lembretes_adocao(hoje)
    assert db.session.get(Animal, animal.id).modo == 'adotado'
    return animal


def test_popup_continua_perguntando_e_devolve_o_anuncio_a_lista(app, client, outbox):
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        animal = _anuncio_fora_da_lista(owner)
        owner_id, animal_id = owner.id, animal.id

    _login(client, owner_id)
    body = client.get('/animals').data.decode()
    assert 'id="adoptionReviewModal"' in body
    assert 'Saiu da lista por falta de resposta' in body

    response = client.post('/adocao/revisar', data={
        'animal_id': str(animal_id),
        f'resposta_{animal_id}': 'disponivel',
        'next': '/animals',
    }, follow_redirects=True)

    body = response.data.decode()
    assert 'Pirata voltou para a lista de adoção.' in body
    assert 'id="adoptionReviewModal"' not in body
    with app.app_context():
        animal = db.session.get(Animal, animal_id)
        assert animal.modo == 'doação'
        assert animal.status == 'disponível'
        assert animal.adocao_expirada_em is None
        assert adocao_lembretes.adoption_listings_query().count() == 1
        # Voltou com o relógio zerado: não nasce vencido de novo.
        assert adocao_lembretes.pending_reviews(db.session.get(User, owner_id)) == []


def test_confirmar_a_adocao_encerra_a_pergunta(app, client, outbox):
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        animal = _anuncio_fora_da_lista(owner)
        owner_id, animal_id = owner.id, animal.id

    _login(client, owner_id)
    client.post('/adocao/revisar', data={
        'animal_id': str(animal_id),
        f'resposta_{animal_id}': 'adotado',
        'next': '/animals',
    })

    assert 'id="adoptionReviewModal"' not in client.get('/animals').data.decode()
    with app.app_context():
        animal = db.session.get(Animal, animal_id)
        assert animal.modo == 'adotado'
        assert animal.adocao_expirada_em is None


def test_outra_pessoa_nao_devolve_anuncio_alheio_a_lista(app, client, outbox):
    with app.app_context():
        dona = _user('Dona', phone='(16) 99999-0001')
        intruso = _user('Intruso', phone='(16) 99999-0002')
        animal = _anuncio_fora_da_lista(dona)
        intruso_id, animal_id = intruso.id, animal.id

    _login(client, intruso_id)
    client.post('/adocao/revisar', data={
        'animal_id': str(animal_id),
        f'resposta_{animal_id}': 'disponivel',
    })

    with app.app_context():
        animal = db.session.get(Animal, animal_id)
        assert animal.modo == 'adotado'
        assert animal.adocao_expirada_em is not None


def test_transferir_ou_editar_o_modo_encerra_a_pendencia(app, outbox):
    """O novo tutor de um animal transferido não pode herdar a pergunta."""
    with app.app_context():
        owner = _user(phone='(16) 99999-0001')
        novo_tutor = _user('Novo Tutor', phone='(16) 99999-0002')
        animal = _anuncio_fora_da_lista(owner)

        animal = db.session.get(Animal, animal.id)
        animal.user_id = novo_tutor.id
        animal.modo = 'adotado'
        db.session.commit()

        assert adocao_lembretes.pending_reviews(novo_tutor) == []


def test_agendador_registra_o_job_diario():
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1] / 'scheduler.py').read_text(encoding='utf-8')
    assert "('lembretes-adocao', _run_adoption_reminders, 10, 30)" in source
