"""Navigation ordering for users who operate on behalf of the platform."""

from extensions import db
from models import User, Veterinario


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _navbar_markup(response):
    page = response.get_data(as_text=True)
    start = page.index('<div class="collapse navbar-collapse justify-content-end" id="navbarNav">')
    end = page.index('</nav>', start)
    return page[start:end]


def test_veterinarian_work_area_precedes_personal_navigation(client, app):
    with app.app_context():
        user = User(name='Veterinário', email='vet-nav-priority@example.test', password_hash='x')
        db.session.add_all([user, Veterinario(user=user, crmv='CRMV-SP 100')])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    navbar = _navbar_markup(client.get('/'))

    assert navbar.index('fa-calendar-alt') < navbar.index('fa-home')
    assert navbar.index('fa-briefcase-medical') < navbar.index('fa-home')


def test_partner_area_precedes_personal_navigation(client, app):
    with app.app_context():
        user = User(
            name='Parceiro',
            email='partner-nav-priority@example.test',
            password_hash='x',
            role='parceiro',
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    navbar = _navbar_markup(client.get('/'))

    assert navbar.index('fa-handshake') < navbar.index('fa-home')


def test_delivery_area_precedes_personal_navigation(client, app):
    with app.app_context():
        user = User(
            name='Entregador',
            email='delivery-nav-priority@example.test',
            password_hash='x',
            worker='delivery',
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    navbar = _navbar_markup(client.get('/'))

    assert navbar.index('fa-truck') < navbar.index('fa-home')
