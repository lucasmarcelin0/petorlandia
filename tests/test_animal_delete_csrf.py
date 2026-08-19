"""Exclusão de animal pelo caminho real do navegador, com CSRF ligado.

O resto da suíte roda com `WTF_CSRF_ENABLED=False`, então o submit de verdade
(token vindo do HTML renderizado) nunca era exercitado. Foi assim que passou o
bug em que o formulário de exclusão de `editar_animal.html` não tinha token e
o usuário só via "Sua sessão foi atualizada. Confira os dados e envie o
formulário novamente." sem o animal ser excluído.

Aqui o fluxo é ponta a ponta: renderiza a página, extrai o token do próprio
formulário de exclusão e envia — exatamente o que o navegador faz.

A varredura que cobre TODOS os formulários do site está em
`test_csrf_form_guard.py`; este arquivo prova o comportamento funcional.
"""
from __future__ import annotations

import re

import pytest

from extensions import db
from models import Animal, User

CSRF_WARNING = "Sua sessão foi atualizada"

# O test client não manda Accept por padrão, e os handlers de erro escolhem
# JSON quando `application/json >= text/html`. Sem estes headers testaríamos a
# API, não a tela que o usuário viu.
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

# PREFERRED_URL_SCHEME=https faz o test client falar https, então
# WTF_CSRF_SSL_STRICT (ligado) exige o header Referer no POST. Navegador manda
# isso sozinho num submit same-origin; o test client não manda nada.
def _browser_post_headers(referer_path):
    return {**BROWSER_HEADERS, "Referer": f"https://localhost{referer_path}"}


@pytest.fixture()
def csrf_app(app):
    """App das fixtures padrão, mas com CSRF ligado como em produção."""
    app.config["WTF_CSRF_ENABLED"] = True
    # SESSION_COOKIE_SECURE fica True por padrão (produção é HTTPS). O test
    # client fala http://localhost, então o cookie Secure não voltaria na
    # requisição seguinte e o token CSRF se perderia entre o GET e o POST —
    # falha de harness, não do app.
    app.config["SESSION_COOKIE_SECURE"] = False
    return app


@pytest.fixture()
def owner(csrf_app):
    user = User(
        name="Tutor",
        email="tutor@example.com",
        role="adotante",
        worker="veterinario",
    )
    user.set_password("x")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def animal(owner):
    pet = Animal(name="Rex", user_id=owner.id)
    db.session.add(pet)
    db.session.commit()
    return pet


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _extract_delete_form_token(html, animal_id):
    """Pega o token do formulário que aponta para a rota de exclusão.

    Procurar "o primeiro csrf_token da página" não serviria: a página tem o
    formulário de edição antes, e o bug era justamente o *segundo* formulário
    estar sem token.
    """
    forms = re.findall(r"<form\b[^>]*>.*?</form\s*>", html, re.IGNORECASE | re.DOTALL)
    for form in forms:
        if f"/animal/{animal_id}/deletar" not in form:
            continue
        match = re.search(
            r"name=[\"']csrf_token[\"'][^>]*value=[\"']([^\"']+)[\"']", form
        )
        return match.group(1) if match else None
    pytest.fail(f"formulário de exclusão do animal {animal_id} não encontrado na página")


def test_delete_form_is_rendered_with_csrf_token(csrf_app, client, owner, animal):
    """A página de edição precisa entregar o token no formulário de exclusão."""
    _login(client, owner.id)

    response = client.get(f"/editar_animal/{animal.id}", headers=BROWSER_HEADERS)

    assert response.status_code == 200
    token = _extract_delete_form_token(response.get_data(as_text=True), animal.id)
    assert token, (
        "o formulário de exclusão foi renderizado sem csrf_token; o submit vai "
        "falhar com a mensagem de sessão atualizada"
    )


def test_owner_can_delete_animal_through_rendered_form(csrf_app, client, owner, animal):
    """Regressão do bug relatado: excluir animal a partir de /editar_animal."""
    animal_id = animal.id
    _login(client, owner.id)

    page = client.get(f"/editar_animal/{animal_id}", headers=BROWSER_HEADERS)
    token = _extract_delete_form_token(page.get_data(as_text=True), animal_id)

    response = client.post(
        f"/animal/{animal_id}/deletar",
        data={"csrf_token": token},
        headers=_browser_post_headers(f"/editar_animal/{animal_id}"),
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert CSRF_WARNING not in body, "submit legítimo foi barrado pela proteção CSRF"
    assert db.session.get(Animal, animal_id).removido_em is not None


def test_delete_without_token_is_rejected_and_keeps_animal(csrf_app, client, owner, animal):
    """A proteção continua valendo: sem token, nada é excluído."""
    animal_id = animal.id
    _login(client, owner.id)

    response = client.post(
        f"/animal/{animal_id}/deletar",
        headers=_browser_post_headers(f"/editar_animal/{animal_id}"),
        follow_redirects=True,
    )

    assert db.session.get(Animal, animal_id).removido_em is None
    assert CSRF_WARNING in response.get_data(as_text=True)


def test_csrf_failure_on_post_only_route_does_not_return_405(csrf_app, client, owner, animal):
    """Sem referrer, a falha de CSRF não pode virar '405 Method Not Allowed'.

    A rota de exclusão só aceita POST. O handler redirecionava para
    `request.path`, então o navegador fazia um GET nessa mesma URL e recebia
    405 — o aviso de sessão atualizada nunca aparecia.
    """
    _login(client, animal.user_id)

    response = client.post(
        f"/animal/{animal.id}/deletar",
        headers=BROWSER_HEADERS,  # de propósito sem Referer
        follow_redirects=True,
    )

    assert response.status_code != 405, (
        "falha de CSRF em rota POST-only caiu em 405 em vez de mostrar o aviso"
    )
    assert response.status_code == 200
