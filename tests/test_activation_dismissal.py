from datetime import timedelta
import pytest
from flask import g
from extensions import db
from models import User, Veterinario, VeterinarianMembership
from services.activation import membership_attention
from time_utils import utcnow


@pytest.mark.parametrize('trial_days,paid_days,automatic,urgent', [
    (20, None, False, False), (2, None, False, True),
    (2, None, True, False), (-1, None, True, True),
    (-10, 20, False, False), (-10, 2, False, True),
    (-10, 2, True, False), (-10, -1, True, True),
])
def test_membership_attention_uses_actual_access_dates(trial_days, paid_days, automatic, urgent):
    membership = VeterinarianMembership(trial_ends_at=utcnow() + timedelta(days=trial_days),
        paid_until=utcnow() + timedelta(days=paid_days) if paid_days is not None else None,
        preapproval_id='authorized' if automatic else None,
        payment_method_set_at=utcnow() if automatic else None)
    assert bool(membership_attention(membership)) is urgent


def test_dismissed_activation_returns_when_access_expires(client, app, monkeypatch):
    from services import activation
    monkeypatch.setattr(activation, 'activation_steps', lambda user: [
        dict(done=False, label='Configurar renovação', url='/veterinarian-membership', cta='Ver assinatura')])
    with app.app_context():
        user = User(name='Vet', email='activation@example.test', password_hash='x')
        vet = Veterinario(user=user, crmv='TEST')
        membership = VeterinarianMembership(veterinario=vet, trial_ends_at=utcnow() + timedelta(days=20))
        db.session.add_all([user, vet, membership])
        db.session.commit()
        user_id, membership_id = user.id, membership.id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    assert 'Dispensar aviso de configuração' in client.get('/').get_data(as_text=True)
    assert client.post('/inicio/ativacao/dispensar').status_code == 302
    assert 'class="activation-bar"' not in client.get('/').get_data(as_text=True)
    with app.app_context():
        db.session.get(VeterinarianMembership, membership_id).trial_ends_at = utcnow() - timedelta(days=1)
        db.session.commit()
    g.pop('_login_user', None)
    page = client.get('/').get_data(as_text=True)
    assert 'activation-bar--urgent' in page
    assert 'Avaliação encerrada' in page
    assert 'Dispensar aviso de configuração' not in page
    assert client.post('/inicio/ativacao/dispensar').status_code == 409
