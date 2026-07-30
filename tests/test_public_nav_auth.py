def test_anonymous_navigation_balances_login_and_registration(client):
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "css/public_nav_auth.css" in html
    assert "nav-link--auth nav-link--login" in html
    assert "nav-link--auth nav-link--trial" in html
    assert "Entrar em uma conta existente" in html
    assert "Criar uma conta e testar grátis" in html
