"""A conta de estagiário pode ser marcada em ``role`` ou em ``worker``.

Os dois campos identificam a conta; nenhum dos dois concede permissão sozinho.
Essa separação não é preciosismo: ``worker='estudante'`` é auto-atribuível
(cadastro público, login Google e o botão "entrar como estudante" gravam
sozinhos), então tratá-lo como autorização deixaria qualquer visitante virar
estagiário de clínica. Quem manda na permissão continua sendo o vínculo
``ClinicStaff``.
"""

import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

from admin import USER_ROLE_CHOICES, USER_WORKER_CHOICES
from app import app as flask_app, db
from helpers import (
    INTERN_ROLE,
    INTERN_WORKER,
    can_start_consulta,
    is_active_intern,
    is_intern_account,
)
from models import Clinica, ClinicStaff, User
from time_utils import utcnow


@pytest.fixture
def app_ctx():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.create_all()
        db.session.add(Clinica(id=1, nome='Clinica'))
        db.session.commit()
        yield
        db.drop_all()


def _user(**kwargs):
    kwargs.setdefault('name', 'Fulano')
    kwargs.setdefault('email', f"u{kwargs.get('id', 1)}@test")
    user = User(**kwargs)
    user.set_password('x')
    db.session.add(user)
    db.session.commit()
    return user


def test_opcao_existe_nos_dois_seletores_do_admin():
    """É a razão de ser da mudança: antes não dava para escolher em lugar nenhum."""

    assert (INTERN_ROLE, 'Estagiário(a)') in USER_ROLE_CHOICES
    assert (INTERN_WORKER, 'Estagiário(a) / Estudante') in USER_WORKER_CHOICES


def test_marcador_reconhecido_pelo_role(app_ctx):
    user = _user(id=1, role=INTERN_ROLE)
    assert is_intern_account(user) is True


def test_marcador_reconhecido_pelo_worker(app_ctx):
    user = _user(id=2, worker=INTERN_WORKER)
    assert is_intern_account(user) is True


def test_conta_comum_nao_e_estagiaria(app_ctx):
    user = _user(id=3, role='adotante', worker='colaborador')
    assert is_intern_account(user) is False


def test_marcador_sozinho_nao_da_permissao(app_ctx):
    """O ponto de segurança: identificar não é autorizar.

    Qualquer visitante consegue se dar ``worker='estudante'`` pelo cadastro
    público. Se o marcador bastasse, isso viraria acesso à clínica.
    """

    por_worker = _user(id=4, worker=INTERN_WORKER)
    por_role = _user(id=5, role=INTERN_ROLE)

    for user in (por_worker, por_role):
        assert is_intern_account(user) is True
        assert is_active_intern(user) is False
        assert can_start_consulta(user) is False


def test_vinculo_de_estagio_e_que_da_permissao(app_ctx):
    user = _user(id=6, role=INTERN_ROLE)
    db.session.add(
        ClinicStaff(
            clinic_id=1,
            user_id=user.id,
            is_intern=True,
            internship_started_at=utcnow(),
        )
    )
    db.session.commit()

    assert is_active_intern(user) is True
    assert can_start_consulta(user) is True


def test_vinculo_derivado_do_role_ao_entrar_na_equipe(app_ctx):
    """Marcado só no ``role``, entrar na equipe já cria o vínculo de estágio.

    Antes a derivação olhava apenas ``worker``, então quem fosse marcado pelo
    ``role`` entrava como funcionário comum e a escolha do admin não valia nada.
    """

    from helpers import is_intern_account as marcador

    user = _user(id=7, role=INTERN_ROLE)
    assert marcador(user) is True

    staff = ClinicStaff(
        clinic_id=1,
        user_id=user.id,
        is_intern=marcador(user),
        internship_started_at=utcnow() if marcador(user) else None,
    )
    db.session.add(staff)
    db.session.commit()

    assert staff.is_intern is True
    assert is_active_intern(user) is True


def _clinic_with_owner():
    """Clínica com dono, para exercitar as rotas de equipe."""

    clinic = Clinica.query.get(1)
    owner = _user(id=90, name='Dono', email='dono@test')
    clinic.owner_id = owner.id
    db.session.commit()
    return clinic, owner


def _login(monkeypatch, user):
    import flask_login.utils as login_utils

    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def test_entrar_na_equipe_marcado_so_no_role_cria_vinculo_de_estagio(app_ctx, monkeypatch):
    """Pela rota real: antes a derivação olhava só ``worker``."""

    clinic, owner = _clinic_with_owner()
    intern = _user(id=91, name='Estagiario', email='estagio@test', role=INTERN_ROLE)
    _login(monkeypatch, owner)

    client = flask_app.test_client()
    client.post(
        f"/clinica/{clinic.id}/funcionarios",
        data={"email": "estagio@test"},
        follow_redirects=True,
    )

    staff = ClinicStaff.query.filter_by(clinic_id=clinic.id, user_id=intern.id).first()
    assert staff is not None
    assert staff.is_intern is True, 'marcar no role tem que valer tanto quanto no worker'
    assert staff.internship_started_at is not None


def test_salvar_permissoes_nao_apaga_o_marcador_no_worker(app_ctx, monkeypatch):
    """Bug encontrado junto: a visão de agenda sobrescrevia ``user.worker``.

    No POST do dashboard, "— padrão —" fazia o campo virar ``None`` e a conta
    deixava de ser identificável como estagiária — o que tornaria inútil
    escolher o estágio pelo ``worker``.
    """

    clinic, owner = _clinic_with_owner()
    intern = _user(id=92, name='Estagiario', email='estagio2@test', worker=INTERN_WORKER)
    db.session.add(
        ClinicStaff(
            clinic_id=clinic.id,
            user_id=intern.id,
            is_intern=True,
            internship_started_at=utcnow(),
        )
    )
    db.session.commit()
    _login(monkeypatch, owner)

    # Os formulários da equipe vão prefixados por usuário no dashboard.
    prefixo = f'perm_{intern.id}'
    client = flask_app.test_client()
    client.post(
        f"/clinica/{clinic.id}",
        data={
            f"{prefixo}-is_intern": "y",
            f"{prefixo}-can_draft_clinical_notes": "y",
            f"{prefixo}-appointments_view": "",
            f"{prefixo}-submit": "Salvar",
        },
        follow_redirects=True,
    )

    db.session.refresh(intern)
    assert intern.worker == INTERN_WORKER, 'salvar permissões não pode apagar o marcador'
    assert is_intern_account(intern) is True
