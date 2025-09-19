import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
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


def test_owner_can_cancel_invite(app):
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
        login(client, owner.id)
        response = client.post(f'/clinica/{clinic.id}/convites/{invite.id}/cancel')

        assert response.status_code == 302
        db.session.refresh(invite)
        assert invite.status == 'cancelled'

        db.session.remove()
        db.drop_all()


def test_admin_can_resend_declined_invite(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        owner = User(id=1, name='Owner', email='o@test', password_hash='x')
        clinic = Clinica(id=1, nome='Clinica', owner_id=owner.id)
        admin = User(id=99, name='Admin', email='admin@test', password_hash='x', role='admin')
        vet_user = User(id=2, name='Vet', email='vet@test', password_hash='x', worker='veterinario')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123')
        db.session.add_all([owner, clinic, admin, vet_user, vet])
        db.session.commit()

        invite = VetClinicInvite(clinica_id=clinic.id, veterinario_id=vet.id, status='declined')
        db.session.add(invite)
        db.session.commit()

        client = app.test_client()
        login(client, admin.id)
        response = client.post(f'/clinica/{clinic.id}/convites/{invite.id}/resend')

        assert response.status_code == 302
        db.session.refresh(invite)
        assert invite.status == 'pending'

        db.session.remove()
        db.drop_all()


def test_non_owner_cannot_manage_invite(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        owner = User(id=1, name='Owner', email='o@test', password_hash='x')
        clinic = Clinica(id=1, nome='Clinica', owner_id=owner.id)
        other_user = User(id=2, name='User', email='user@test', password_hash='x')
        vet_user = User(id=3, name='Vet', email='vet@test', password_hash='x', worker='veterinario')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123')
        db.session.add_all([owner, clinic, other_user, vet_user, vet])
        db.session.commit()

        invite = VetClinicInvite(clinica_id=clinic.id, veterinario_id=vet.id)
        db.session.add(invite)
        db.session.commit()

        client = app.test_client()
        login(client, other_user.id)
        response = client.post(f'/clinica/{clinic.id}/convites/{invite.id}/cancel')

        assert response.status_code == 403
        db.session.refresh(invite)
        assert invite.status == 'pending'

        db.session.remove()
        db.drop_all()
