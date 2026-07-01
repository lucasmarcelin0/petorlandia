def test_chatgpt_onboarding_page_is_public(client):
    response = client.get('/chatgpt')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Comece a usar no ChatGPT' in html
    assert '/mcp' in html
    assert '/oauth/authorize' in html
    assert '/oauth/token' in html
