"""Estagiário pode iniciar atendimento a partir da agenda.

O botão "Iniciar consulta" era liberado por um teste manual de ``worker`` no
template (``worker in ['veterinario', 'colaborador']``), o que deixava de fora
o estagiário — e também o veterinário legado que tem o perfil mas está sem
``worker`` preenchido. A permissão passou para ``helpers.can_start_consulta``,
fonte única da rota e do template; estes testes travam esse contrato.
"""

import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import timedelta

import flask_login.utils as login_utils
import pytest

from app import app as flask_app, db
from helpers import can_start_consulta, is_active_intern, internship_clinic_id
from models import Animal, ClinicStaff, Clinica, Consulta, User, Veterinario
from time_utils import utcnow

#: O app mascara 403 como 404 quando o cliente prefere JSON (defesa contra
#: vazar existencia de recurso entre clinicas -- ver request_hooks). Um
#: navegador manda Accept de HTML, entao e assim que o teste enxerga o status
#: real.
HTML = {'Accept': 'text/html,application/xhtml+xml'}


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.create_all()
        yield client
        with flask_app.app_context():
            db.drop_all()


def login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def _build_clinic(*, internship_ends_at=..., with_staff=True):
    """Clínica com tutor, animal, veterinário supervisor e um estagiário.

    ``internship_ends_at`` elipse = estágio sem prazo (ativo). Passe uma data
    no passado para simular estágio vencido, ou ``with_staff=False`` para um
    usuário 'estudante' que nunca foi vinculado.
    """

    clinic = Clinica(id=1, nome='Clinica')
    tutor = User(id=1, name='Tutor', email='tutor@test', worker='adotante')
    tutor.set_password('x')
    vet_user = User(id=2, name='Vet', email='vet@test', worker='veterinario')
    vet_user.set_password('x')
    vet = Veterinario(id=1, user=vet_user, crmv='123', clinica_id=clinic.id)
    intern_user = User(id=3, name='Estagiario', email='estagio@test', worker='estudante')
    intern_user.set_password('x')
    animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)

    db.session.add_all([clinic, tutor, vet_user, vet, intern_user, animal])
    db.session.commit()

    if with_staff:
        staff = ClinicStaff(
            clinic_id=clinic.id,
            user_id=intern_user.id,
            is_intern=True,
            internship_started_at=utcnow(),
            internship_ends_at=(
                None if internship_ends_at is ... else internship_ends_at
            ),
            internship_supervisor_id=vet_user.id,
        )
        db.session.add(staff)
        db.session.commit()

    return clinic, tutor, vet_user, intern_user, animal


def test_estagio_ativo_reconhecido(client):
    with flask_app.app_context():
        _build_clinic()
        intern = User.query.get(3)
        assert is_active_intern(intern) is True
        assert can_start_consulta(intern) is True
        assert internship_clinic_id(intern) == 1


def test_estagio_vencido_nao_da_permissao(client):
    with flask_app.app_context():
        _build_clinic(internship_ends_at=utcnow() - timedelta(days=1))
        intern = User.query.get(3)
        assert is_active_intern(intern) is False
        assert can_start_consulta(intern) is False


def test_estudante_sem_vinculo_nao_da_permissao(client):
    with flask_app.app_context():
        _build_clinic(with_staff=False)
        intern = User.query.get(3)
        assert is_active_intern(intern) is False
        assert can_start_consulta(intern) is False


def test_tutor_nunca_inicia_consulta(client):
    with flask_app.app_context():
        _build_clinic()
        tutor = User.query.get(1)
        assert can_start_consulta(tutor) is False


def test_veterinario_sem_worker_preenchido_ainda_inicia(client):
    """Regressão do bug que a mudança corrige de lambuja.

    Cadastro legado tem ``Veterinario`` mas ``User.worker`` vazio; o teste
    manual antigo no template escondia o botão desses profissionais.
    """

    with flask_app.app_context():
        _build_clinic()
        vet_user = User.query.get(2)
        vet_user.worker = None
        db.session.commit()
        assert can_start_consulta(vet_user) is True


def test_estagiario_abre_consulta_pela_rota(client, monkeypatch):
    with flask_app.app_context():
        _build_clinic()
        intern = User.query.get(3)
        login(monkeypatch, intern)

        resp = client.get('/consulta/1', headers=HTML)
        assert resp.status_code == 200

        consulta = Consulta.query.filter_by(animal_id=1).first()
        assert consulta is not None, 'estagiário deve abrir o atendimento, não só ver a página'
        assert consulta.created_by == intern.id
        assert consulta.clinica_id == 1
        assert consulta.status == 'in_progress'


def test_estagio_vencido_recebe_403_na_rota(client, monkeypatch):
    with flask_app.app_context():
        _build_clinic(internship_ends_at=utcnow() - timedelta(days=1))
        intern = User.query.get(3)
        login(monkeypatch, intern)

        resp = client.get('/consulta/1', headers=HTML)
        assert resp.status_code == 403
        assert Consulta.query.count() == 0


def test_tutor_recebe_403_na_rota(client, monkeypatch):
    with flask_app.app_context():
        _build_clinic()
        tutor = User.query.get(1)
        login(monkeypatch, tutor)

        resp = client.get('/consulta/1', headers=HTML)
        assert resp.status_code == 403
