# -*- coding: utf-8 -*-
import os
import sys
from decimal import Decimal
import pytest

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db
from models import (
    User,
    Clinica,
    Veterinario,
    Animal,
    Consulta,
    BlocoExames,
    ExameSolicitado,
    ServicoClinica,
    ProfessionalService,
)
from services.payments import PaymentPreferenceResult


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_imprimir_bloco_exames_mostra_opcao_contratacao(app, client):
    """Verifica que imprimir_bloco_exames exibe a opção de contratar o exame da Maisse a R$ 110,00."""
    with app.app_context():
        tutor = User(id=1, name='Pedro Tutor', email='tutor@test.com', password_hash='x')
        vet_user = User(id=2, name='Dr Lucas', email='lucas@petorlandia.com.br', password_hash='x', worker='veterinario')
        clinica = Clinica(id=1, nome='PetOrlandia', owner_id=vet_user.id)
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='SP-12345', clinica_id=1)

        maisse_user = User(id=2939, name='Dra Maisse Cividanes', email='maisse@test.com', password_hash='x', worker='veterinario')
        maisse_vet = Veterinario(id=430, user_id=maisse_user.id, crmv='SP-67890')

        animal = Animal(id=10, name='Paloma', user_id=tutor.id, clinica_id=1)
        consulta = Consulta(id=100, animal_id=animal.id, created_by=vet_user.id, clinica_id=1)

        bloco = BlocoExames(id=1552, animal_id=animal.id)
        exame = ExameSolicitado(
            id=200,
            bloco_id=1552,
            nome='Combinado - Hemograma, ALT, FA, ureia, creatinina',
            justificativa='Avaliação clínica completa.',
            status='pendente',
        )

        servico = ServicoClinica(
            clinica_id=1,
            descricao='Combinado - Hemograma, ALT, FA, ureia, creatinina',
            valor=Decimal('110.00'),
            procedure_code='LAB-MAISSE',
        )

        db.session.add_all([
            tutor, vet_user, clinica, vet, maisse_user, maisse_vet,
            animal, consulta, bloco, exame, servico,
        ])
        db.session.commit()

    login(client, user_id=1)  # Logado como o tutor
    resp = client.get('/imprimir_bloco_exames/1552')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Verifica elementos do card de contratação
    assert 'Contratar Exames Desta Requisição' in html
    assert 'Mercado Pago' in html
    assert 'R$ 110,00' in html
    assert 'Combinado - Hemograma, ALT, FA, ureia, creatinina' in html
    assert '/bloco_exames/1552/contratar' in html
    assert 'name="csrf-token"' in html
    assert 'data-csrf' in html
    assert 'csrf_fetch.js' in html


def test_contratar_bloco_exames_gera_preferencia_mercado_pago(app, client, monkeypatch):
    """Verifica que o endpoint /contratar gera a preferência de pagamento no Mercado Pago com R$ 110,00."""
    with app.app_context():
        tutor = User(id=1, name='Pedro Tutor', email='tutor@test.com', password_hash='x')
        vet_user = User(id=2, name='Dr Lucas', email='lucas@petorlandia.com.br', password_hash='x', worker='veterinario')
        clinica = Clinica(id=1, nome='PetOrlandia', owner_id=vet_user.id)
        animal = Animal(id=10, name='Paloma', user_id=tutor.id, clinica_id=1)
        bloco = BlocoExames(id=1552, animal_id=animal.id)
        exame = ExameSolicitado(
            id=200,
            bloco_id=1552,
            nome='Combinado - Hemograma, ALT, FA, ureia, creatinina',
            status='pendente',
        )
        servico = ServicoClinica(
            clinica_id=1,
            descricao='Combinado - Hemograma, ALT, FA, ureia, creatinina',
            valor=Decimal('110.00'),
        )
        db.session.add_all([tutor, vet_user, clinica, animal, bloco, exame, servico])
        db.session.commit()

    # Mock do gerador de preferência
    chamadas_mp = []
    def fake_criar_preferencia(items, ext_ref, back_url):
        chamadas_mp.append({
            'items': items,
            'ext_ref': ext_ref,
            'back_url': back_url,
        })
        return {
            'payment_url': 'https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=fake-pref-123',
            'payment_reference': 'fake-pref-123',
        }

    from blueprints import consulta as consulta_blueprint
    monkeypatch.setattr(consulta_blueprint, '_criar_preferencia_pagamento', fake_criar_preferencia)

    login(client, user_id=1)
    # Requisição AJAX POST
    resp = client.post(
        '/bloco_exames/1552/contratar',
        headers={'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'},
    )
    assert resp.status_code == 200
    dados = resp.get_json()
    assert dados['success'] is True
    assert 'fake-pref-123' in dados['payment_url']

    assert len(chamadas_mp) == 1
    call = chamadas_mp[0]
    assert call['ext_ref'] == 'bloco_exames-1552'
    assert len(call['items']) == 1
    assert call['items'][0]['unit_price'] == 110.0

    # Verifica persistência no banco
    with app.app_context():
        b = BlocoExames.query.get(1552)
        assert b.payment_reference == 'fake-pref-123'
        assert b.payment_status == 'pending'


def test_contratar_bloco_exames_com_csrf_global_ativado(app, client, monkeypatch):
    """Garante que com WTF_CSRF_ENABLED=True a rota @csrf.exempt não falha com CSRFError."""
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        with app.app_context():
            tutor = User(id=1, name='Pedro Tutor', email='tutor@test.com', password_hash='x')
            vet_user = User(id=2, name='Dr Lucas', email='lucas@petorlandia.com.br', password_hash='x', worker='veterinario')
            clinica = Clinica(id=1, nome='PetOrlandia', owner_id=vet_user.id)
            animal = Animal(id=10, name='Paloma', user_id=tutor.id, clinica_id=1)
            bloco = BlocoExames(id=1552, animal_id=animal.id)
            exame = ExameSolicitado(
                id=200,
                bloco_id=1552,
                nome='Combinado - Hemograma, ALT, FA, ureia, creatinina',
                status='pendente',
            )
            servico = ServicoClinica(
                clinica_id=1,
                descricao='Combinado - Hemograma, ALT, FA, ureia, creatinina',
                valor=Decimal('110.00'),
            )
            db.session.add_all([tutor, vet_user, clinica, animal, bloco, exame, servico])
            db.session.commit()

        def fake_criar_preferencia(items, ext_ref, back_url):
            return {
                'payment_url': 'https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=fake-csrf-ok',
                'payment_reference': 'fake-csrf-ok',
            }

        from blueprints import consulta as consulta_blueprint
        monkeypatch.setattr(consulta_blueprint, '_criar_preferencia_pagamento', fake_criar_preferencia)

        login(client, user_id=1)

        # POST sem CSRF token - não pode retornar 400 Falha de validação!
        resp_post = client.post(
            '/bloco_exames/1552/contratar?exame_id=200',
            headers={'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'},
        )
        assert resp_post.status_code == 200
        dados = resp_post.get_json()
        assert dados['success'] is True
        assert 'fake-csrf-ok' in dados['payment_url']

        # GET direto - fallback via navegador deve redirecionar (302) para o checkout
        resp_get = client.get('/bloco_exames/1552/contratar?exame_id=200')
        assert resp_get.status_code == 302
        assert 'mercadopago.com.br' in resp_get.headers['Location']
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


def test_webhook_aprova_pagamento_bloco_exames(app, client, monkeypatch):
    """Verifica que o webhook do Mercado Pago atualiza o status para pago."""
    with app.app_context():
        tutor = User(id=1, name='Pedro Tutor', email='tutor@test.com', password_hash='x')
        vet_user = User(id=2, name='Dr Lucas', email='lucas@petorlandia.com.br', password_hash='x', worker='veterinario')
        clinica = Clinica(id=1, nome='PetOrlandia', owner_id=vet_user.id)
        animal = Animal(id=10, name='Paloma', user_id=tutor.id, clinica_id=1)
        bloco = BlocoExames(id=1552, animal_id=animal.id, payment_status='pending')
        exame = ExameSolicitado(
            id=200,
            bloco_id=1552,
            nome='Combinado - Hemograma, ALT, FA, ureia, creatinina',
            status='pendente',
            payment_status='pending',
        )
        db.session.add_all([tutor, vet_user, clinica, animal, bloco, exame])
        db.session.commit()

    # Mock do SDK Mercado Pago para simular retorno de pagamento aprovado
    class FakePaymentSDK:
        def get(self, mp_id):
            return {
                'status': 200,
                'response': {
                    'status': 'approved',
                    'external_reference': 'bloco_exames-1552',
                    'date_approved': '2026-09-08T15:00:00.000-03:00',
                }
            }

    class FakeMPSDK:
        def payment(self):
            return FakePaymentSDK()

    from blueprints import loja as loja_blueprint
    monkeypatch.setattr(loja_blueprint, 'mp_sdk', lambda: FakeMPSDK())
    monkeypatch.setattr(loja_blueprint, 'verify_mp_signature', lambda r, s: True)

    resp = client.post(
        '/notificacoes?type=payment',
        json={'data': {'id': '123456789'}},
    )
    assert resp.status_code == 200

    # Verifica atualização no banco
    with app.app_context():
        b = BlocoExames.query.get(1552)
        assert b.payment_status == 'paid'
        assert b.paid_at is not None
        e = ExameSolicitado.query.get(200)
        assert e.payment_status == 'paid'
        assert e.status == 'em_andamento'
