from flask import flash, render_template

from extensions import db
from models import AdminActionNotification, Clinica, User
from services.public_stats import public_stats, reset_cache


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_admin_notification_cache_never_reuses_detached_orm_on_novo_animal(
    app,
    client,
):
    with app.app_context():
        admin = User(
            name='Admin Hotfix',
            email='admin-hotfix@example.test',
            password_hash='x',
            role='admin',
        )
        db.session.add(admin)
        db.session.flush()
        db.session.add(
            AdminActionNotification(
                recipient_user_id=admin.id,
                event_type='production_hotfix',
                title='Alerta de regressão',
                url='/novo_animal',
                idempotency_key='production-hotfix-detached-note',
            )
        )
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)

    first = client.get('/novo_animal')
    assert first.status_code == 200
    assert 'Alerta de regressão'.encode('utf-8') in first.data

    # O teardown já remove a sessão; a chamada explícita documenta a condição
    # de produção e impede que o teste passe por uma sessão ainda conectada.
    with app.app_context():
        db.session.remove()

    second = client.get('/novo_animal')
    assert second.status_code == 200
    assert 'Alerta de regressão'.encode('utf-8') in second.data


def test_layout_accepts_list_flash_without_raising_500(app):
    with app.test_request_context('/'):
        flash(['Primeiro erro.', 'Segundo erro.'], 'warning')
        html = render_template('layout.html')

    assert 'Primeiro erro. Segundo erro.' in html


def test_public_shell_keeps_shared_css_and_bootstrap_available_synchronously(
    client,
):
    response = client.get('/')

    assert response.status_code == 200
    assert b'/static/css/clinic.css' in response.data
    assert b'styles.css?v=20260729hotfix1' in response.data
    assert b'bootstrap.bundle.min.js?v=5.3&quot; defer' not in response.data
    assert b'bootstrap.bundle.min.js?v=5.3" defer' not in response.data


def test_public_clinic_stat_counts_only_founder_validated_clinics(app):
    with app.app_context():
        real = Clinica(nome='Clínica real', status='ativa')
        test = Clinica(nome='Clínica de teste', status='ativa')
        db.session.add_all([real, test])
        db.session.commit()

        app.config['PUBLIC_STATS_CLINIC_IDS'] = (real.id,)
        reset_cache()
        clinic_stats = [stat for stat in public_stats() if 'clínica' in stat.label]

    assert len(clinic_stats) == 1
    assert clinic_stats[0].value == 1
    assert clinic_stats[0].label == 'clínica usando o sistema'


def test_public_clinic_stat_fails_closed_without_validated_ids(app):
    with app.app_context():
        db.session.add(Clinica(nome='Cadastro técnico', status='ativa'))
        db.session.commit()

        app.config['PUBLIC_STATS_CLINIC_IDS'] = ()
        reset_cache()
        clinic_stats = [stat for stat in public_stats() if 'clínica' in stat.label]

    assert clinic_stats == []


def test_veterinarian_membership_page_can_read_preferred_plan_from_session(
    app,
    client,
):
    with app.app_context():
        admin = User(
            name='Admin Assinatura',
            email='admin-assinatura@example.test',
            password_hash='x',
            role='admin',
        )
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)
    with client.session_transaction() as session:
        session['preferred_membership_plan'] = 'anual'

    response = client.get('/veterinario/assinatura')
    assert response.status_code == 200
