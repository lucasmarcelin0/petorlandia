import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from unittest.mock import MagicMock
from app import app as flask_app, db
from models import User, Clinica, Veterinario, VetClinicInvite


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    yield flask_app


def login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_accepting_invite_sets_clinic(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        owner = User(id=1, name='Owner', email='o@test', password_hash='x')
        clinic = Clinica(id=1, nome='Clinica', owner_id=owner.id)
        vet_user = User(id=2, name='Vet', email='vet@test', password_hash='x', worker='veterinario')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123')
        db.session.add_all([owner, clinic, vet_user, vet])
        db.session.commit()

        invite = VetClinicInvite(clinica_id=clinic.id, veterinario_id=vet.id)
        db.session.add(invite)
        db.session.commit()

        client = app.test_client()
        login(client, vet_user.id)
        client.post(f'/convites/{invite.id}/accept')

        assert vet.clinica_id == clinic.id
        assert invite.status == 'accepted'

        db.session.remove()
        db.drop_all()


def test_creating_invite_sends_email(app, monkeypatch):
    with app.app_context():
        db.drop_all()
        db.create_all()

        owner = User(id=1, name='Owner', email='owner@test', password_hash='x')
        clinic = Clinica(id=1, nome='Clinica', owner_id=owner.id)
        owner.clinica_id = clinic.id
        vet_user = User(
            id=2,
            name='Vet',
            email='vet@example.com',
            password_hash='x',
            worker='veterinario',
        )
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123')
        db.session.add_all([owner, clinic, vet_user, vet])
        db.session.commit()

        mocked_send = MagicMock()
        monkeypatch.setattr('app.mail.send', mocked_send)
        monkeypatch.setattr('app.ClinicAddStaffForm.validate_on_submit', lambda self: False)

        client = app.test_client()
        login(client, owner.id)
        response = client.post(
            f'/clinica/{clinic.id}',
            data={'email': vet_user.email, 'submit': 'Convidar', 'nome': ''},
        )

        assert response.status_code == 302
        invite = VetClinicInvite.query.filter_by(
            clinica_id=clinic.id,
            veterinario_id=vet.id,
            status='pending',
        ).first()
        assert invite is not None
        mocked_send.assert_called_once()
        sent_message = mocked_send.call_args[0][0]
        assert vet_user.email in sent_message.recipients

        db.session.remove()
        db.drop_all()
