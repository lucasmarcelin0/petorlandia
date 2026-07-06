from pathlib import Path

from extensions import db
from models import User


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_activity_pages_expose_shared_ajax_panel(app, client):
    with app.app_context():
        user = User(
            name='Tutor Atividades',
            email='tutor-atividades@test',
            password_hash='x',
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)

    paths = (
        '/minhas-solicitacoes',
        '/petsitter/minhas',
        '/planos/tosa/minhas-assinaturas',
        '/minhas-compras',
    )
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.data.count(b'data-activities-navigation') == 1, path
        assert response.data.count(b'data-activities-content') == 1, path
        assert b'data-activities-tab' in response.data, path
        assert b'js/minhas_atividades.js' in response.data, path


def test_activity_ajax_script_supports_history_and_safe_fallback():
    script = (PROJECT_ROOT / 'static' / 'js' / 'minhas_atividades.js').read_text(encoding='utf-8')

    assert 'history.pushState' in script
    assert "addEventListener('popstate'" in script
    assert 'window.location.assign(url)' in script
    assert 'X-Requested-With' in script
