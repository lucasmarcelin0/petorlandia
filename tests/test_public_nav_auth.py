from bs4 import BeautifulSoup

from extensions import db
from models import User


def test_anonymous_navigation_balances_login_and_registration(client):
    """Entrar e criar conta continuam lado a lado, com o mesmo peso visual.

    O rótulo da ação de cadastro segue a área: na home o visitante é tratado
    como tutor, então a oferta é a conta gratuita — não o teste do sistema de
    gestão, que só faz sentido para quem chegou pela porta da clínica.
    """
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "css/public_nav_auth.css" in html
    assert "nav-link--auth nav-link--login" in html
    assert "nav-link--auth nav-link--trial" in html
    assert "Entrar em uma conta existente" in html
    assert "Criar uma conta gratuita de tutor" in html


def test_business_area_keeps_the_clinic_trial_offer(client):
    """Na porta da clínica a oferta volta a ser o teste do sistema."""
    html = client.get("/parceiros/clinica").get_data(as_text=True)

    assert "Criar uma conta de clínica e testar grátis" in html
    assert "cta_nav_trial" in html
    assert "Criar uma conta gratuita de tutor" not in html


def test_auth_actions_stay_outside_the_collapsed_menu(client):
    """No celular as ações de acesso não podem depender de abrir a sanfona.

    O grupo compacto precisa ficar FORA de `#navbarNav`; se alguém movê-lo para
    dentro do menu recolhido, o visitante volta a ter que descobrir o hambúrguer
    para entrar ou testar a plataforma.
    """
    soup = BeautifulSoup(client.get("/").get_data(as_text=True), "html.parser")

    quick = soup.select_one(".public-auth-quick")
    assert quick is not None, "grupo de acesso rápido ausente na barra pública"
    assert quick.find_parent(id="navbarNav") is None
    assert "d-lg-none" in quick.get("class", [])

    hrefs = [a["href"] for a in quick.select("a.public-auth-quick__link")]
    assert len(hrefs) == 2, "esperado exatamente Entrar e Testar grátis"
    assert any("/login" in href for href in hrefs)
    assert any("/register" in href for href in hrefs)

    labels = [a["aria-label"] for a in quick.select("a.public-auth-quick__link")]
    assert all(labels), "cada ação precisa de rótulo acessível"


def test_logged_in_navbar_has_no_public_auth_actions(client, app):
    """Quem já entrou não deve ver Entrar/Testar grátis ocupando a barra."""
    with app.app_context():
        user = User(name="Tutor Teste", email="tutor-navbar@test.com")
        user.set_password("senha123")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True

    soup = BeautifulSoup(client.get("/").get_data(as_text=True), "html.parser")

    assert soup.select_one(".public-auth-quick") is None
    assert soup.select_one(".navbar.navbar--public") is None
