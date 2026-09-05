"""Navigation ordering for users who operate on behalf of the platform.

As asserções ancoram no rótulo visível, não no nome do glifo: o ícone é
detalhe de apresentação e já mudou uma vez (fa-home -> fa-house) sem que a
ordem da navegação — o que estes testes garantem — fosse alterada.
"""

from pathlib import Path

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

    assert navbar.index('Agenda') < navbar.index('Início')
    assert navbar.index('Trabalho') < navbar.index('Início')


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

    assert navbar.index('Parceiro') < navbar.index('Início')


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

    assert navbar.index('Solicitações') < navbar.index('Início')


def test_admin_nav_uses_wide_breakpoint_and_flexible_shell(client, app):
    with app.app_context():
        user = User(
            name='Administrador',
            email='admin-nav@example.test',
            password_hash='x',
            role='admin',
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    page = client.get('/').get_data(as_text=True)

    assert 'navbar-expand-xxl navbar--admin' in page
    assert 'clinic.css?v=20260802-mobile-navbar2' in page


def test_authenticated_navbar_keeps_mobile_logout_at_top_of_account_menu(client, app):
    with app.app_context():
        user = User(
            name='Pessoa no celular',
            email='mobile-logout@example.test',
            password_hash='x',
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    page = client.get('/').get_data(as_text=True)

    account_start = page.index('nav-item dropdown nav-account')
    account_end = page.index('</ul>', account_start)
    account_menu = page[account_start:account_end]

    assert 'nav-account__logout-mobile' in account_menu
    assert 'nav-account__logout-desktop' in account_menu
    assert account_menu.index('nav-account__logout-mobile') < account_menu.index('Meu perfil')
    assert account_menu.count('href="/logout"') == 2


def test_mobile_navbar_css_limits_menu_to_visible_viewport():
    css = (Path(__file__).parents[1] / 'static' / 'css' / 'clinic.css').read_text(encoding='utf-8')

    assert 'max-height: calc(100dvh - var(--topbar-height) - env(safe-area-inset-top));' in css
    assert 'overflow-y: auto;' in css
    assert 'overscroll-behavior: contain;' in css
    assert 'calc(1rem + env(safe-area-inset-bottom))' in css
    assert '.nav-account__logout-mobile' in css
    assert 'flex: 0 0 100%;' in css
    assert 'width: 100%;' in css


def test_navbar_renders_user_profile_photo_avatar_when_present(client, app):
    with app.app_context():
        user = User(
            name='Juliana Ferreira',
            email='juliana-nav-avatar@example.test',
            password_hash='x',
            profile_photo='https://images.example.test/juliana.jpg',
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    page = client.get('/').get_data(as_text=True)

    assert 'nav-account__avatar-wrap' in page
    assert 'nav-account__avatar' in page
    assert 'https://images.example.test/juliana.jpg' in page
    assert 'Foto de perfil de Juliana' in page
    assert 'Juliana' in page


def test_navbar_falls_back_to_icon_when_user_has_no_photo(client, app):
    with app.app_context():
        user = User(
            name='Carlos Santos',
            email='carlos-nav-no-photo@example.test',
            password_hash='x',
            profile_photo=None,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    page = client.get('/').get_data(as_text=True)

    assert 'nav-account__avatar-wrap' not in page
    assert 'nav-account__avatar' not in page
    assert 'fa-circle-user' in page
    assert 'Carlos' in page


def test_navbar_avatar_css_rules_present():
    css = (Path(__file__).parents[1] / 'static' / 'css' / 'tutor-experience.css').read_text(encoding='utf-8')

    assert '.nav-account__avatar-wrap' in css
    assert '.nav-account__avatar' in css
    assert 'border-radius: 50%;' in css
    assert 'object-fit: cover;' in css

