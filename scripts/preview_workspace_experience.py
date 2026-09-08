"""Local-only demo server and visual checks backed by an isolated memory DB."""
import argparse
import os
from pathlib import Path
import sys
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'


def build_app():
    from app_factory import create_app
    from extensions import db, limiter
    from flask import abort, redirect
    from flask_login import login_user, logout_user
    from models import Animal, CasaDeRacao, Clinica, Product, User, Veterinario
    from models import Order, OrderItem, Payment, PaymentMethod, PaymentStatus

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, MAIL_SUPPRESS_SEND=True,
                      RATELIMIT_ENABLED=False, SESSION_COOKIE_SECURE=False)
    limiter.enabled = False
    with app.app_context():
        assert str(db.engine.url) == 'sqlite:///:memory:'
        db.create_all()
        personas = {}
        for key, role, worker in [
            ('tutor', 'tutor', None), ('vet', 'tutor', 'veterinario'),
            ('store', 'tutor', None), ('partner', 'parceiro', None),
            ('delivery', 'tutor', 'delivery'), ('student', 'tutor', 'estudante'),
            ('admin', 'admin', None), ('staff', 'tutor', 'colaborador'),
            ('vaccinator', 'vacinador', None), ('manager', 'gestor', None),
            ('active_store', 'tutor', None),
        ]:
            user = User(name='Marina Demo', email=f'{key}@example.test', role=role, worker=worker)
            user.set_password('local-preview-only')
            db.session.add(user)
            db.session.flush()
            personas[key] = user.id
        clinic = Clinica(nome='Clínica Demonstração', owner_id=personas['vet'])
        db.session.add(clinic)
        db.session.flush()
        db.session.add(Veterinario(user_id=personas['vet'], crmv='DEMO', clinica_id=clinic.id))
        db.session.get(User, personas['staff']).clinica_id = clinic.id
        store = CasaDeRacao(nome='Loja Demonstração', owner_id=personas['store'],
                           registered_by_id=personas['partner'], status='pendente')
        db.session.add(store)
        db.session.add(Animal(name='Mel', user_id=personas['tutor'], is_alive=True))
        active_store = CasaDeRacao(nome='Loja Ativa Demonstração', owner_id=personas['active_store'],
                                  registered_by_id=personas['partner'], status='ativa')
        db.session.add(active_store)
        db.session.flush()
        product = Product(name='Produto de demonstração', price=30, stock=10, status='active',
                          casa_de_racao_id=active_store.id, image_url='/static/img/produtos/cefalexina_500mg.png')
        db.session.add(product)
        db.session.flush()
        order = Order(user_id=personas['tutor'])
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(order_id=order.id, product_id=product.id, item_name=product.name, quantity=1, unit_price=33.33))
        db.session.add(Payment(order_id=order.id, user_id=personas['tutor'], method=PaymentMethod.PIX, status=PaymentStatus.COMPLETED, amount=33.33))
        db.session.commit()
        app.config['PREVIEW_PAGES'] = [
            ('store', f'/casa-de-racao/{store.id}', 'store-dashboard'),
            ('store', f'/casa-de-racao/{store.id}/produtos', 'store-products'),
            ('active_store', f'/casa-de-racao/{active_store.id}/vendas', 'store-sales'),
            ('partner', '/parceiro', 'partner-dashboard'),
            ('delivery', '/delivery_requests', 'delivery-queue'),
            ('tutor', '/minhas-compras', 'purchases'),
            ('tutor', f'/pedidos/{order.id}/comprar-novamente', 'repurchase'),
            ('tutor', f'/produto/{product.id}', 'product-detail'),
        ]

    @app.route('/__preview__/as/<persona>')
    def preview_as(persona):
        logout_user()
        if persona != 'public':
            if persona not in personas:
                abort(404)
            login_user(db.session.get(User, personas[persona]))
        return redirect('/')

    return app


def capture(server, port, app):
    import json
    from PIL import Image
    from playwright.sync_api import sync_playwright

    output = ROOT / 'output' / 'workspace-experience'
    output.mkdir(parents=True, exist_ok=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    results = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge' if sys.platform == 'win32' else None)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            base = f'http://127.0.0.1:{port}'
            page.goto(base + '/__preview__/as/vet', wait_until='networkidle')
            page.evaluate('document.fonts.ready')
            assert page.evaluate('document.fonts.check(\'900 16px "Font Awesome 6 Free"\')')
            screenshot = ROOT / 'static' / 'img' / 'landing-agenda.png'
            page.screenshot(path=str(screenshot))
            with Image.open(screenshot) as image:
                image.save(screenshot.with_suffix('.webp'), 'WEBP', quality=88, method=6)
            for width, height in [(1440, 1000), (1024, 768), (390, 844)]:
                page.set_viewport_size({'width': width, 'height': height})
                for persona in ['public', 'tutor', 'vet', 'store', 'partner', 'delivery', 'student', 'admin', 'staff', 'vaccinator', 'manager']:
                    response = page.goto(base + '/__preview__/as/' + persona, wait_until='networkidle')
                    overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
                    assert response.status == 200, (persona, response.status)
                    assert not overflow, (persona, width, 'horizontal overflow')
                    assert page.locator('main').count() == 1
                    if persona != 'public':
                        toggler = page.locator('.navbar-toggler')
                        if toggler.is_visible():
                            toggler.click()
                            page.wait_for_selector('#navbarNav.show')
                        links = page.locator('.navbar .nav-item > .nav-link')
                        assert links.evaluate_all('links => links.filter(link => link.getClientRects().length).every(link => { const rect = link.getBoundingClientRect(); return rect.left >= 0 && rect.right <= innerWidth + 1; })'), (persona, width, 'clipped navigation')
                        account = page.locator('.nav-account__toggle')
                        account.click()
                        logout = page.locator('.nav-account .dropdown-menu.show a[href$="/logout"]:visible').first
                        logout.scroll_into_view_if_needed()
                        assert logout.is_visible(), (persona, width, 'logout unavailable')
                        account.click()
                        if toggler.is_visible():
                            toggler.click()
                            page.wait_for_selector('#navbarNav:not(.show):not(.collapsing)', state='attached')
                        page.evaluate('window.scrollTo(0, 0)')
                    page.screenshot(path=str(output / f'{persona}-{width}.png'), full_page=True)
                    results.append({'persona': persona, 'width': width, 'status': response.status, 'overflow': overflow})
                page.goto(base + '/__preview__/as/public', wait_until='networkidle')
                tab = page.locator('[data-profile="clinica"]')
                tab.click()
                page.wait_for_selector('[data-profile-panel="clinica"]')
                assert '/minha-clinica' in page.locator('[data-profile-primary]').first.get_attribute('href')
                tab.focus()
                page.keyboard.press('ArrowRight')
                page.wait_for_selector('[data-profile-panel="veterinario"]')
                assert page.locator('[data-profile="veterinario"]').get_attribute('aria-selected') == 'true'
                for persona, path, name in app.config['PREVIEW_PAGES']:
                    page.goto(base + '/__preview__/as/' + persona, wait_until='networkidle')
                    response = page.goto(base + path, wait_until='networkidle')
                    assert response.status == 200, (path, response.status)
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'), (path, width)
                    page.screenshot(path=str(output / f'{name}-{width}.png'), full_page=True)
                    if name == 'store-dashboard':
                        page.locator('#produtos-tab').click()
                        page.locator('a[href="#recebimentos"]').click()
                        assert page.locator('#loja').is_visible()
                        assert page.locator('#recebimentos').is_visible()
                    if name in ['product-detail', 'repurchase']:
                        media = page.locator('.product-media__image').first
                        assert media.evaluate('image => image.complete && image.naturalWidth > 0')
                        assert '.webp' in media.evaluate('image => image.currentSrc')
                    results.append({'page': name, 'width': width, 'status': response.status, 'overflow': False})
            browser.close()
            print(json.dumps({'screens': results, 'javascript_errors': errors}, ensure_ascii=True))
            assert not errors, errors
    finally:
        server.shutdown()
        thread.join(timeout=5)


def main():
    from werkzeug.serving import make_server

    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5057)
    parser.add_argument('--capture', action='store_true')
    args = parser.parse_args()
    app = build_app()
    server = make_server('127.0.0.1', args.port, app, threaded=True)
    if args.capture:
        capture(server, args.port, app)
    else:
        print(f'Local demo: http://127.0.0.1:{args.port}', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
