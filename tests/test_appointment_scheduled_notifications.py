"""Quem é agendado fica sabendo, não importa por qual caminho.

O aviso vive em gancho de sessão (``services/appointment_notifications``), não
numa chamada por rota: compromisso nasce em pelo menos sete lugares e o próximo
ponto de criação passaria batido. Estes testes exercitam a criação pelo ORM
direto e pelo serviço de retorno justamente para provar que o gancho pega os
dois sem ninguém lembrar de chamá-lo.
"""

import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import date, timedelta

import pytest

from app import app as flask_app, db
from models import (
    Animal,
    Appointment,
    Clinica,
    ExamAppointment,
    Notification,
    User,
    Vacina,
    Veterinario,
)
from time_utils import utcnow

TUTOR_ID = 1
VET_USER_ID = 2
VET_ID = 1
ANIMAL_ID = 1


@pytest.fixture
def app_ctx():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.create_all()
        _seed()
        yield
        db.drop_all()


def _seed():
    clinic = Clinica(id=1, nome='Clinica')
    tutor = User(id=TUTOR_ID, name='Tutor', email='tutor@test', worker='adotante', clinica_id=1)
    tutor.set_password('x')
    vet_user = User(id=VET_USER_ID, name='Dra. Ana', email='vet@test', worker='veterinario')
    vet_user.set_password('x')
    vet = Veterinario(id=VET_ID, user=vet_user, crmv='123', clinica_id=1)
    animal = Animal(id=ANIMAL_ID, name='Rex', user_id=TUTOR_ID, clinica_id=1)
    db.session.add_all([clinic, tutor, vet_user, vet, animal])
    db.session.commit()


def _notifications_for(user_id):
    return Notification.query.filter_by(user_id=user_id).all()


def _agendar(**overrides):
    payload = dict(
        animal_id=ANIMAL_ID,
        tutor_id=TUTOR_ID,
        veterinario_id=VET_ID,
        scheduled_at=utcnow() + timedelta(days=2),
        kind='consulta',
        clinica_id=1,
    )
    payload.update(overrides)
    appt = Appointment(**payload)
    db.session.add(appt)
    db.session.commit()
    return appt


def test_consulta_agendada_avisa_tutor_e_profissional(app_ctx):
    """Agendada por um terceiro (recepção): os dois envolvidos são avisados."""

    _agendar(created_by=None)

    tutor_msgs = _notifications_for(TUTOR_ID)
    vet_msgs = _notifications_for(VET_USER_ID)

    assert len(tutor_msgs) == 1
    assert len(vet_msgs) == 1
    assert tutor_msgs[0].kind == 'appointment'
    assert tutor_msgs[0].channel == 'app'
    assert 'Rex' in tutor_msgs[0].message
    assert 'Dra. Ana' in tutor_msgs[0].message


def test_quem_agenda_nao_recebe_aviso_da_propria_acao(app_ctx):
    _agendar(created_by=VET_USER_ID)

    assert _notifications_for(TUTOR_ID), 'o tutor precisa ser avisado'
    assert _notifications_for(VET_USER_ID) == [], (
        'o profissional que criou o agendamento não deve receber aviso de si mesmo'
    )


def test_retorno_usa_o_rotulo_certo(app_ctx):
    _agendar(kind='retorno', created_by=VET_USER_ID)

    mensagem = _notifications_for(TUTOR_ID)[0].message
    assert mensagem.startswith('Retorno de Rex')


def test_banho_e_tosa_tambem_avisa(app_ctx):
    _agendar(kind='banho_tosa', created_by=VET_USER_ID)

    mensagem = _notifications_for(TUTOR_ID)[0].message
    assert 'Banho e Tosa de Rex' in mensagem


def test_exame_com_especialista_avisa_os_dois(app_ctx):
    exam = ExamAppointment(
        animal_id=ANIMAL_ID,
        specialist_id=VET_ID,
        requester_id=TUTOR_ID,
        exam_name='Hemograma',
        scheduled_at=utcnow() + timedelta(days=3),
    )
    db.session.add(exam)
    db.session.commit()

    # Quem pediu foi o tutor, então só o especialista precisa ser avisado.
    assert _notifications_for(TUTOR_ID) == []
    vet_msgs = _notifications_for(VET_USER_ID)
    assert len(vet_msgs) == 1
    assert vet_msgs[0].kind == 'exam'
    assert "Hemograma" in vet_msgs[0].message


def test_vacina_futura_avisa_o_tutor(app_ctx):
    vacina = Vacina(
        animal_id=ANIMAL_ID,
        nome='V10',
        aplicada=False,
        aplicada_em=date.today() + timedelta(days=5),
        created_by=VET_USER_ID,
    )
    db.session.add(vacina)
    db.session.commit()

    msgs = _notifications_for(TUTOR_ID)
    assert len(msgs) == 1
    assert msgs[0].kind == 'vaccine'
    assert "V10" in msgs[0].message


def test_vacina_ja_aplicada_nao_gera_aviso(app_ctx):
    """Carteirinha importada é histórico, não agendamento.

    Sem esta distinção, cadastrar o passado de um paciente dispararia uma
    enxurrada de "vacina agendada" para o tutor.
    """

    vacina = Vacina(
        animal_id=ANIMAL_ID,
        nome='Antirrábica',
        aplicada=True,
        aplicada_em=date.today() - timedelta(days=30),
        created_by=VET_USER_ID,
    )
    db.session.add(vacina)
    db.session.commit()

    assert _notifications_for(TUTOR_ID) == []


def test_rollback_nao_deixa_aviso_orfao(app_ctx):
    """Aviso e compromisso vivem na mesma transação: ou os dois, ou nenhum."""

    appt = Appointment(
        animal_id=ANIMAL_ID,
        tutor_id=TUTOR_ID,
        veterinario_id=VET_ID,
        scheduled_at=utcnow() + timedelta(days=2),
        kind='consulta',
        clinica_id=1,
    )
    db.session.add(appt)
    db.session.flush()
    db.session.rollback()

    assert Notification.query.count() == 0
    assert Appointment.query.count() == 0


def test_alterar_agendamento_existente_nao_reavisa(app_ctx):
    """Só a criação avisa. Remarcar não deve repetir a notificação aqui."""

    appt = _agendar(created_by=VET_USER_ID)
    antes = Notification.query.count()

    appt.scheduled_at = utcnow() + timedelta(days=9)
    db.session.commit()

    assert Notification.query.count() == antes


def test_retorno_criado_pelo_servico_tambem_avisa(app_ctx):
    """O ponto de criação que uma chamada por rota deixaria escapar.

    ``services.appointments`` monta o retorno dentro do fluxo da consulta, bem
    longe da view de agendamento — é o caso que justifica o gancho.
    """

    from models import Consulta
    from services.appointments import ReturnAppointmentDTO, schedule_return_appointment

    consulta = Consulta(
        animal_id=ANIMAL_ID,
        created_by=VET_USER_ID,
        clinica_id=1,
        status='in_progress',
    )
    db.session.add(consulta)
    db.session.commit()

    alvo = (utcnow() + timedelta(days=4)).date()
    resultado = schedule_return_appointment(
        consulta=consulta,
        payload=ReturnAppointmentDTO(
            date=alvo,
            time=__import__('datetime').time(10, 0),
            veterinarian_id=VET_ID,
            reason='Reavaliação',
        ),
        actor_id=VET_USER_ID,
        actor_vet_id=VET_ID,
    )

    assert resultado.success, resultado.message
    msgs = _notifications_for(TUTOR_ID)
    assert len(msgs) == 1
    assert msgs[0].message.startswith('Retorno de Rex')

def test_entrega_de_push_roda_apos_o_commit_sem_quebrar_a_sessao(app_ctx, monkeypatch):
    """O push do agendamento precisa realmente sair.

    Regressao vista em producao: `_deliver` rodava dentro do gancho
    `after_commit`, onde a sessao esta em estado 'committed' e qualquer SQL
    levanta `InvalidRequestError`. `push_to_user` comeca justamente com um
    SELECT em PushSubscription, entao TODO push falhava -- e a excecao ainda
    abortava o laco, deixando os destinatarios seguintes sem nem o e-mail.

    Os demais testes deste arquivo so olham as linhas de Notification, gravadas
    em `before_flush`, e por isso nao viam nada disso.
    """

    import pywebpush

    from models import PushSubscription
    from services.push import _endpoint_hash

    flask_app.config.update(
        VAPID_PUBLIC_KEY='pub-teste',
        VAPID_PRIVATE_KEY='priv-teste',
        VAPID_CLAIM_EMAIL='mailto:contato@petorlandia.com.br',
    )

    def _inscricao(user_id, endpoint):
        return PushSubscription(
            user_id=user_id,
            endpoint=endpoint,
            endpoint_hash=_endpoint_hash(endpoint),
            p256dh='k-%s' % user_id,
            auth='a-%s' % user_id,
        )

    db.session.add_all([
        _inscricao(TUTOR_ID, 'https://push.example/tutor'),
        _inscricao(VET_USER_ID, 'https://push.example/vet'),
    ])
    db.session.commit()

    enviados = []
    monkeypatch.setattr(
        pywebpush, 'webpush',
        lambda **kwargs: enviados.append(kwargs['subscription_info']['endpoint']),
    )

    erros = []
    monkeypatch.setattr(
        flask_app.logger, 'exception',
        lambda *args, **kwargs: erros.append(args[0] if args else ''),
    )

    _agendar(created_by=None)

    assert erros == [], 'a entrega registrou excecao: %s' % (erros,)
    assert sorted(enviados) == [
        'https://push.example/tutor',
        'https://push.example/vet',
    ], 'tutor e profissional precisam receber push'
