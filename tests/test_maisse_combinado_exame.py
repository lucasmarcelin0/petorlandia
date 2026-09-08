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
    ServicoClinica,
    Veterinario,
    ExameModelo,
    BlocoExames,
    ExameSolicitado,
    ProfessionalService,
)


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


def test_maisse_combinado_exame_isolation(app, client):
    """Testa que o exame Combinado da Maisse é exibido na PetOrlandia e isolado de outras clínicas."""
    with app.app_context():
        # Setup: Clínicas e Usuários
        user_petorlandia = User(id=1, name='Dr Lucas', email='lucas@petorlandia.com.br', password_hash='x', worker='veterinario')
        clinica_petorlandia = Clinica(id=1, nome='PetOrlandia', owner_id=user_petorlandia.id)

        user_outra_clinica = User(id=2, name='Outro Vet', email='outro@clinica.com.br', password_hash='x', worker='veterinario')
        clinica_outra = Clinica(id=99, nome='Outra Clínica', owner_id=user_outra_clinica.id)

        # Exame exclusivo da PetOrlandia (Maisse)
        exame_combinado = ExameModelo(
            id=1,
            nome='Combinado - Hemograma, ALT, FA, ureia, creatinina',
            justificativa='Avaliação bioquímica e hematológica completa.',
            created_by=user_petorlandia.id,
            clinica_id=1,
        )

        # Exame global (ex: Raio-X genérico)
        exame_global = ExameModelo(
            id=2,
            nome='Raio-X de Tórax',
            justificativa='Avaliação de campos pulmonares e silhueta cardíaca.',
            created_by=user_petorlandia.id,
            clinica_id=None,
        )

        # Exame de outra clínica
        exame_outra = ExameModelo(
            id=3,
            nome='Ecocardiograma Exclusivo Outra',
            justificativa='Avaliação cardiológica especializada.',
            created_by=user_outra_clinica.id,
            clinica_id=99,
        )

        db.session.add_all([
            user_petorlandia, clinica_petorlandia,
            user_outra_clinica, clinica_outra,
            exame_combinado, exame_global, exame_outra,
        ])
        db.session.commit()

    # 1. Testar busca na Clínica PetOrlandia (clinica_id = 1)
    login(client, user_id=1)
    resp = client.get('/buscar_exames?q=combinado&clinica_id=1')
    assert resp.status_code == 200
    data = resp.get_json()
    assert any(item['nome'] == 'Combinado - Hemograma, ALT, FA, ureia, creatinina' for item in data)

    # PetOrlandia também vê o exame global
    resp = client.get('/buscar_exames?q=raio-x&clinica_id=1')
    assert resp.status_code == 200
    data = resp.get_json()
    assert any('Raio-X' in item['nome'] for item in data)

    # PetOrlandia NÃO vê o exame exclusivo da outra clínica
    resp = client.get('/buscar_exames?q=ecocardiograma&clinica_id=1')
    assert resp.status_code == 200
    data = resp.get_json()
    assert not any('Ecocardiograma Exclusivo Outra' in item['nome'] for item in data)

    # 2. Testar busca na Outra Clínica (clinica_id = 99)
    login(client, user_id=2)
    resp = client.get('/buscar_exames?q=combinado&clinica_id=99')
    assert resp.status_code == 200
    data = resp.get_json()
    # NÃO deve conter o Combinado da Maisse / PetOrlandia
    assert not any('Combinado' in item['nome'] for item in data)

    # Outra clínica vê exame global
    resp = client.get('/buscar_exames?q=raio-x&clinica_id=99')
    assert resp.status_code == 200
    data = resp.get_json()
    assert any('Raio-X' in item['nome'] for item in data)


def test_exames_frequentes_endpoint(app, client):
    """Testa o endpoint de atalhos rápidos / exames frequentes."""
    with app.app_context():
        user_pet = User(id=1, name='Dr Lucas', email='lucas@petorlandia.com.br', password_hash='x', worker='veterinario')
        clinica_pet = Clinica(id=1, nome='PetOrlandia', owner_id=user_pet.id)
        user_outro = User(id=2, name='Outro Vet', email='outro@clinica.com.br', password_hash='x', worker='veterinario')
        clinica_outra = Clinica(id=99, nome='Outra Clínica', owner_id=user_outro.id)

        exame_combinado = ExameModelo(
            id=1,
            nome='Combinado - Hemograma, ALT, FA, ureia, creatinina',
            justificativa='Avaliação geral de rotina.',
            created_by=user_pet.id,
            clinica_id=1,
        )
        db.session.add_all([user_pet, clinica_pet, user_outro, clinica_outra, exame_combinado])
        db.session.commit()

    # PetOrlandia (clinica_id = 1): deve trazer o Combinado como chip
    login(client, user_id=1)
    resp = client.get('/exames_frequentes?clinica_id=1')
    assert resp.status_code == 200
    itens = resp.get_json()
    assert len(itens) > 0
    assert itens[0]['nome'] == 'Combinado - Hemograma, ALT, FA, ureia, creatinina'
    assert itens[0]['is_clinic_exclusive'] is True

    # Outra Clínica (clinica_id = 99): NÃO deve trazer o Combinado da Maisse
    login(client, user_id=2)
    resp = client.get('/exames_frequentes?clinica_id=99')
    assert resp.status_code == 200
    itens = resp.get_json()
    assert not any('combinado' in item['nome'].lower() for item in itens)


def test_seed_maisse_combinado_service(app):
    """Testa a execução do seed idempotente para o serviço da Dra Maisse."""
    from scripts.seed_maisse_combinado_service import seed_maisse_combinado

    with app.app_context():
        # Setup: Dra Maisse e Clínica PetOrlandia
        owner = User(id=1, name='Dr Lucas', email='lucas@petorlandia.com.br', password_hash='x')
        clinica = Clinica(id=1, nome='PetOrlandia', owner_id=owner.id)

        maisse_user = User(id=2939, name='Dra Maisse Cividanes', email='maissecividanes@hotmail.com', password_hash='x', worker='veterinario')
        maisse_vet = Veterinario(id=430, user_id=maisse_user.id, crmv='SP-12345')

        db.session.add_all([owner, clinica, maisse_user, maisse_vet])
        db.session.commit()

        # Executar seed
        seed_maisse_combinado()

        # Validar ExameModelo
        exame = ExameModelo.query.filter(ExameModelo.nome.ilike('%combinado%hemograma%')).first()
        assert exame is not None
        assert exame.clinica_id == 1

        # Validar ServicoClinica
        servico = ServicoClinica.query.filter_by(clinica_id=1, descricao='Combinado - Hemograma, ALT, FA, ureia, creatinina').first()
        assert servico is not None
        assert servico.valor == Decimal('110.00')
        assert servico.procedure_code == 'LAB-MAISSE'

        # Validar ProfessionalService
        ps = ProfessionalService.query.filter_by(veterinario_id=430, service_type='exame').first()
        assert ps is not None
        assert ps.clinic_business_price == Decimal('100.00')
        assert ps.tutor_price == Decimal('110.00')
        assert ps.active is True
