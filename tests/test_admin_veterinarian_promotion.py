"""Regression coverage for the admin veterinarian-promotion flow."""

from extensions import db
from models import User, Veterinario, VeterinarianMembership


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_admin_promotes_user_to_veterinarian_with_one_membership(client, app):
    """A new veterinarian must receive one profile and one trial membership."""

    with app.app_context():
        admin = User(
            name='Admin da Plataforma',
            email='admin-promocao-vet@example.test',
            password_hash='not-used-in-this-test',
            role='admin',
        )
        target = User(
            name='Profissional a Promover',
            email='profissional-promocao-vet@example.test',
            password_hash='not-used-in-this-test',
        )
        db.session.add_all([admin, target])
        db.session.commit()
        admin_id = admin.id
        target_id = target.id

    _login(client, admin_id)
    response = client.post(
        f'/admin/users/{target_id}/promover_veterinario',
        data={'crmv': 'CRMV-SP 12345', 'phone': '16999990000'},
    )

    assert response.status_code == 302

    with app.app_context():
        target = db.session.get(User, target_id)
        assert target.worker == 'veterinario'
        assert target.phone == '16999990000'
        assert target.veterinario is not None
        assert target.veterinario.crmv == 'CRMV-SP 12345'
        assert (
            VeterinarianMembership.query.filter_by(
                veterinario_id=target.veterinario.id
            ).count()
            == 1
        )

    # Repeating the action must update the existing profile, never create a
    # second membership or fail with the same uniqueness constraint.
    response = client.post(
        f'/admin/users/{target_id}/promover_veterinario',
        data={'crmv': 'CRMV-SP 54321'},
    )

    assert response.status_code == 302

    with app.app_context():
        target = db.session.get(User, target_id)
        assert target.veterinario.crmv == 'CRMV-SP 54321'
        assert (
            VeterinarianMembership.query.filter_by(
                veterinario_id=target.veterinario.id
            ).count()
            == 1
        )


def test_direct_veterinarian_creation_still_starts_one_trial_membership(app):
    """The model fallback remains safe for veterinarian profiles created elsewhere."""

    with app.app_context():
        user = User(
            name='Veterinário criado diretamente',
            email='vet-criacao-direta@example.test',
            password_hash='not-used-in-this-test',
            worker='veterinario',
        )
        vet = Veterinario(user=user, crmv='CRMV-SP 67890')
        db.session.add_all([user, vet])
        db.session.commit()

        memberships = VeterinarianMembership.query.filter_by(
            veterinario_id=vet.id
        ).all()
        assert len(memberships) == 1
        assert memberships[0].trial_ends_at is not None
