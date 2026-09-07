"""Dismissing a reminder is personal and never removes it from the central view."""
from bs4 import BeautifulSoup
from flask import g
from extensions import db
from models import User, Notification


def test_dismissal_persists_and_is_isolated(client, app):
    with app.app_context():
        users = [User(name='Admin', email=f'alerts-{i}@example.test', role='admin', password_hash='x') for i in range(2)]
        db.session.add_all(users)
        db.session.commit()
        ids = [u.id for u in users]

    def login(user_id):
        # The shared fixture holds an app context across requests.
        g.pop('_login_user', None)
        g.pop('user_experience', None)
        with client.session_transaction() as session:
            session['_user_id'] = str(user_id)
            session['_fresh'] = True

    login(ids[0])
    page = BeautifulSoup(client.get('/').data, 'html.parser')
    alert = page.select_one('.home-alert')
    label = alert.select_one('strong').text
    token = alert.select_one('[name=token]')['value']
    login(ids[1])
    assert client.post('/inicio/alertas/dispensar', data={'token': token}).status_code == 400
    login(ids[0])
    assert client.post('/inicio/alertas/dispensar', data={'token': token}).status_code == 302
    assert client.post('/inicio/alertas/dispensar', data={'token': token}).status_code == 302
    home = BeautifulSoup(client.get('/').data, 'html.parser')
    assert label not in [node.text for node in home.select('.home-alert strong')]
    central = BeautifulSoup(client.get('/?alertas=1').data, 'html.parser')
    dismissed = next(node for node in central.select('.home-alert') if node.select_one('strong').text == label)
    assert dismissed.select_one('.home-alert-dismissed')
    assert dismissed.select_one('a')['href'] == alert.select_one('a')['href']
    assert not dismissed.select_one('form')
    login(ids[1])
    other_home = BeautifulSoup(client.get('/').data, 'html.parser')
    assert label in [node.text for node in other_home.select('.home-alert strong')]
    with app.app_context():
        assert Notification.query.filter_by(kind='home_alert_dismissed').count() == 1


def test_dismissal_rejects_invalid_tokens_and_requires_csrf(client, app):
    with app.app_context():
        user = User(name='Tutor', email='alerts-csrf@example.test', password_hash='x')
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    assert client.post('/inicio/alertas/dispensar', data={'token': 'invalid'}).status_code == 400
    previous = app.config['WTF_CSRF_ENABLED']
    from services.home_alerts import serializer
    valid_token = serializer().dumps({'user_id': user_id, 'key': 'test-key'})
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        assert client.post('/inicio/alertas/dispensar', data={'token': valid_token}).status_code == 400
    finally:
        app.config['WTF_CSRF_ENABLED'] = previous
