from io import BytesIO
from pathlib import Path

import admin as admin_module
from extensions import db
from models import CasaDeRacao, User


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _create_admin_and_store():
    admin = User(
        name='Admin de imagens',
        email='admin-imagens@test',
        password_hash='x',
        role='admin',
    )
    owner = User(
        name='Dono da loja',
        email='dono-imagens@test',
        password_hash='x',
    )
    db.session.add_all([admin, owner])
    db.session.flush()
    store = CasaDeRacao(nome='Loja das imagens', owner_id=owner.id, status='ativa')
    db.session.add(store)
    db.session.commit()
    return admin.id, store.id


def test_every_admin_image_field_uses_the_shared_paste_contract(app):
    fields = (
        (admin_module.UserAdminView, 'profile_photo_upload'),
        (admin_module.ClinicaAdmin, 'logotipo_upload'),
        (admin_module.AnimalAdminView, 'image_upload'),
        (admin_module.ProductAdmin, 'image_upload'),
        (admin_module.CasaDeRacaoAdminView, 'logotipo_upload'),
    )

    for view, field_name in fields:
        field = view.form_extra_fields[field_name]
        render_kw = field.kwargs['render_kw']
        assert render_kw['data-image-paste'] == 'true'
        assert render_kw['data-max-bytes'] == str(20 * 1024 * 1024)
        assert 'image/png' in render_kw['accept']
        assert 'image/webp' in render_kw['accept']
        assert field.kwargs['validators']


def test_admin_image_urls_are_stable_for_legacy_relative_paths(app):
    with app.test_request_context('/'):
        assert admin_module._admin_image_src('uploads/products/racao.png') == (
            '/static/uploads/products/racao.png'
        )
        assert admin_module._admin_image_src('static/uploads/products/racao.png') == (
            '/static/uploads/products/racao.png'
        )
        assert admin_module._admin_image_src('/static/uploads/products/racao.png') == (
            '/static/uploads/products/racao.png'
        )
        assert admin_module._admin_image_src('https://cdn.test/racao.png') == (
            'https://cdn.test/racao.png'
        )


def test_admin_create_pages_load_the_global_image_paste_experience(app, client):
    with app.app_context():
        admin_id, _ = _create_admin_and_store()
    _login(client, admin_id)

    for path in (
        '/painel/user/new/',
        '/painel/clinica/new/',
        '/painel/animal/new/',
        '/painel/product/new/',
        '/painel/casaderacao/new/',
    ):
        response = client.get(path)
        html = response.data.decode('utf-8')
        assert response.status_code == 200, path
        assert 'data-image-paste="true"' in html, path
        assert '/static/admin/image_paste.css?v=20260802' in html, path
        assert '/static/admin/image_paste.js?v=20260802' in html, path


def test_admin_image_paste_script_keeps_clipboard_upload_safe_and_observable(app):
    script = (Path(app.root_path) / 'static' / 'admin' / 'image_paste.js').read_text(encoding='utf-8')

    assert "document.addEventListener('paste', handlePaste)" in script
    assert 'new DataTransfer()' in script
    assert 'new File([file]' in script
    assert "input.dispatchEvent(new Event('change', { bubbles: true }))" in script
    assert "closest('input:not([type=\"file\"]), textarea, [contenteditable=\"true\"]')" in script
    assert "'image/svg+xml'" not in script
    assert 'Clique no campo desejado e pressione Ctrl+V novamente.' in script


def test_admin_rejects_a_non_image_file_in_product_upload(app, client):
    with app.app_context():
        admin_id, store_id = _create_admin_and_store()
    _login(client, admin_id)

    response = client.post(
        '/painel/product/new/',
        data={
            'name': 'Arquivo inválido',
            'description': 'Não deve ser criado',
            'price': '20.00',
            'stock': '1',
            'status': 'active',
            'category': '',
            'clinica': '',
            'casa_de_racao': str(store_id),
            'subscription_discount_percent': '0',
            'subscription_shipping_fee': '0',
            'mp_category_id': 'pet_supplies',
            'image_upload': (BytesIO(b'<svg><script>alert(1)</script></svg>'), 'imagem.svg'),
        },
        content_type='multipart/form-data',
    )

    assert response.status_code == 200
    assert 'Envie uma imagem JPG, PNG, GIF, WebP ou BMP.' in response.data.decode('utf-8')
