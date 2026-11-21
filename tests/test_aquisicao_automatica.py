"""Aquisição no automático: lead de demonstração, régua de ativação e resumo do dono."""

from datetime import timedelta

import pytest

from extensions import db
from models import AdminActionNotification, Clinica, ClinicHours, User, WaitlistLead
from time_utils import utcnow


@pytest.fixture
def emails(monkeypatch):
    enviados = []

    def _fake_send(recipients, subject, body):
        enviados.append({'to': list(recipients), 'subject': subject, 'body': body})
        return True

    monkeypatch.setattr('services.notifications._send_email', _fake_send)
    return enviados


def _admin():
    admin = User(name='Fundador', email='fundador@petorlandia.com.br', role='admin')
    admin.set_password('x')
    db.session.add(admin)
    db.session.commit()
    return admin


def _owner_in_trial(nome='Dra. Teste', email='dra@clinica.com.br', dias=1, phone='16999990000'):
    from helpers import ensure_veterinarian_membership, grant_veterinarian_role

    user = User(name=nome, email=email, phone=phone)
    user.set_password('x')
    db.session.add(user)
    db.session.flush()
    clinic = Clinica(nome=f'Clínica de {nome}', owner_id=user.id)
    db.session.add(clinic)
    db.session.flush()
    vet = grant_veterinarian_role(user, crmv=f'{user.id}0001', clinica=clinic)
    user.clinica_id = clinic.id
    db.session.commit()
    membership = ensure_veterinarian_membership(vet)
    membership.started_at = utcnow() - timedelta(days=dias)
    membership.trial_ends_at = utcnow() + timedelta(days=30 - dias)
    db.session.commit()
    return user, clinic, membership


# ------------------------------------------------------------ lead de demo


def test_pedido_de_demo_avisa_o_dono_e_confirma_ao_lead(app, client, emails):
    _admin()

    resp = client.post('/lista-de-espera', json={
        'feature': 'demo_clinica', 'contact': 'contato@clinicanova.com.br', 'city': 'Orlândia',
    })
    assert resp.status_code == 200 and resp.get_json()['success'] is True

    alertas = AdminActionNotification.query.filter_by(event_type='demo_clinica_lead').all()
    assert len(alertas) == 1
    assert alertas[0].priority == 'high'
    assert 'contato@clinicanova.com.br' in alertas[0].title

    destinatarios = [e['to'] for e in emails]
    assert ['fundador@petorlandia.com.br'] in destinatarios
    confirmacao = next(e for e in emails if e['to'] == ['contato@clinicanova.com.br'])
    assert 'Recebemos seu pedido de demonstração' in confirmacao['subject']
    assert '/precos' in confirmacao['body']

    # Reenvio do mesmo contato não duplica o alerta.
    client.post('/lista-de-espera', json={'feature': 'demo_clinica', 'contact': 'contato@clinicanova.com.br'})
    assert AdminActionNotification.query.filter_by(event_type='demo_clinica_lead').count() == 1


def test_pedido_de_demo_por_whatsapp_traz_link_de_resposta(app, client, emails):
    _admin()
    client.post('/lista-de-espera', json={'feature': 'demo_clinica', 'contact': '(16) 98888-7777'})

    alerta = AdminActionNotification.query.filter_by(event_type='demo_clinica_lead').one()
    assert 'https://wa.me/5516988887777' in alerta.body
    # Telefone não recebe e-mail de confirmação.
    assert all(e['to'] == ['fundador@petorlandia.com.br'] for e in emails)


def test_lista_de_espera_comum_nao_dispara_alerta_de_venda(app, client, emails):
    _admin()
    client.post('/lista-de-espera', json={'feature': 'loja', 'contact': 'tutor@gmail.com'})
    assert WaitlistLead.query.count() == 1
    assert AdminActionNotification.query.count() == 0
    assert emails == []


def test_falha_no_aviso_nao_perde_o_lead(app, client, monkeypatch):
    def _quebra(*_a, **_k):
        raise RuntimeError('SMTP fora do ar')

    monkeypatch.setattr('services.acquisition.notify_demo_lead', _quebra)
    resp = client.post('/lista-de-espera', json={'feature': 'demo_clinica', 'contact': 'x@clinica.com.br'})
    assert resp.status_code == 200 and resp.get_json()['success'] is True
    assert WaitlistLead.query.filter_by(contact='x@clinica.com.br').count() == 1


# --------------------------------------------------------- régua de ativação


def test_regua_de_ativacao_lembra_so_nos_dias_previstos(app, emails):
    from services.acquisition import send_activation_nudges

    user, _clinic, membership = _owner_in_trial(dias=1)
    assert send_activation_nudges(base_url='https://www.petorlandia.com.br') == 1
    corpo = emails[-1]['body']
    assert emails[-1]['to'] == [user.email]
    assert 'https://www.petorlandia.com.br/clinica/' in corpo  # link absoluto do passo
    assert 'primeiro paciente' in corpo

    membership.started_at = utcnow() - timedelta(days=2)
    db.session.commit()
    emails.clear()
    assert send_activation_nudges(base_url='https://www.petorlandia.com.br') == 0
    assert emails == []


def test_regua_de_ativacao_some_quando_os_passos_estao_feitos(app, emails):
    from datetime import time as dtime

    from models import Animal, Appointment
    from services.acquisition import send_activation_nudges

    user, clinic, _membership = _owner_in_trial(dias=4)
    db.session.add(ClinicHours(clinica_id=clinic.id, dia_semana='Segunda',
                               hora_abertura=dtime(8), hora_fechamento=dtime(18)))
    tutor = User(name='Tutor', email='tutor@exemplo.com.br')
    tutor.set_password('x')
    db.session.add(tutor)
    db.session.flush()
    animal = Animal(name='Rex', user_id=tutor.id, clinica_id=clinic.id)
    db.session.add(animal)
    db.session.flush()
    db.session.add(Appointment(animal_id=animal.id, tutor_id=tutor.id, clinica_id=clinic.id,
                               veterinario_id=user.veterinario.id,
                               scheduled_at=utcnow() + timedelta(days=1)))
    db.session.commit()

    assert send_activation_nudges(base_url='https://www.petorlandia.com.br') == 0


# ------------------------------------------------------- resumo para o dono


def test_resumo_diario_lista_o_que_exige_contato_e_nao_repete(app, emails):
    from services.acquisition import build_acquisition_digest, send_acquisition_digest

    _admin()
    db.session.add(WaitlistLead(feature='demo_clinica', contact='(16) 97777-6666', city='Guará'))
    db.session.commit()
    _owner_in_trial(nome='Travada', email='travada@clinica.com.br', dias=3)
    _user, _c, acabando = _owner_in_trial(nome='Acabando', email='acabando@clinica.com.br', dias=27)
    acabando.trial_ends_at = utcnow() + timedelta(days=3)
    db.session.commit()

    digest = build_acquisition_digest(base_url='https://www.petorlandia.com.br')
    assert any('97777-6666' in line for line in digest['leads'])
    assert any('Travada' in line and 'wa.me' in line for line in digest['stalled'])
    assert any('Acabando' in line for line in digest['ending'])
    assert digest['new_clinics']  # as clínicas criadas agora

    assert send_acquisition_digest(base_url='https://www.petorlandia.com.br') is True
    resumo = AdminActionNotification.query.filter_by(event_type='acquisition_digest').one()
    assert 'Pedidos de demonstração' in resumo.body
    enviados = len(emails)

    # Reexecução no mesmo dia (reinício do dyno) não repete o e-mail.
    assert send_acquisition_digest(base_url='https://www.petorlandia.com.br') is False
    assert len(emails) == enviados


def test_resumo_diario_fica_quieto_sem_pendencias(app, emails):
    from services.acquisition import send_acquisition_digest

    _admin()
    assert send_acquisition_digest(base_url='https://www.petorlandia.com.br') is False
    assert emails == []


def test_pedido_de_demo_tem_limite_por_ip(app, emails):
    _admin()
    app.config['RATELIMIT_ENABLED'] = True
    client = app.test_client()
    statuses = [
        client.post('/lista-de-espera', json={
            'feature': 'demo_clinica', 'contact': f'spam{i}@exemplo.com.br',
        }).status_code
        for i in range(7)
    ]
    assert 429 in statuses
    # Nenhum e-mail sai além do que o limite deixou passar.
    assert WaitlistLead.query.count() == statuses.count(200)


@pytest.mark.parametrize('hora_utc', [1, 2, 3, 13, 23])
def test_regua_de_ativacao_nao_depende_da_hora_do_dia(app, emails, monkeypatch, hora_utc):
    """Entre 21h e 0h de Brasília o "dia da avaliação" já pulou um dia por fuso."""
    from datetime import datetime, timezone as tz
    from zoneinfo import ZoneInfo

    import services.acquisition as acquisition

    agora = datetime(2026, 11, 21, hora_utc, 30, tzinfo=tz.utc)
    monkeypatch.setattr(acquisition, 'utcnow', lambda: agora)
    monkeypatch.setattr(acquisition, 'now_in_brazil', lambda: agora.astimezone(ZoneInfo('America/Sao_Paulo')))

    _user, _clinic, membership = _owner_in_trial(dias=1)
    membership.started_at = agora - timedelta(days=1)
    membership.trial_ends_at = agora + timedelta(days=29)
    db.session.commit()

    assert acquisition.send_activation_nudges(base_url='https://www.petorlandia.com.br') == 1
