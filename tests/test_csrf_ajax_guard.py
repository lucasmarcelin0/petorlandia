"""Guarda do CSRF em requisicoes AJAX (fetch/XHR).

Contexto: o bug do formulário de exclusão tinha um irmão em JavaScript.
Dezenas de chamadas `fetch()` mutantes não mandavam token nenhum — por
exemplo `/chat/<id>` (POST), `/vacina/<id>` (PUT/DELETE) e `/racao/<id>`
(PUT/DELETE). Todas levavam 400 "CSRF token missing or invalid". Como boa
parte desse JS não checa a resposta, a ação falhava em silêncio: no chat, o
campo de texto era limpo e a mensagem nunca era enviada.

Corrigir call site por call site não escala (e o próximo a ser escrito
esqueceria de novo), então o token passa a ser anexado por um wrapper global
em `static/csrf_fetch.js`. Estes testes protegem esse arranjo em dois níveis:

1. o wrapper continua carregado, e antes de qualquer script que faça request;
2. o contrato do servidor não mudou — header `X-CSRFToken` é aceito, e a
   ausência dele continua sendo rejeitada.

O comportamento do JS em si é verificado em `tests/test_csrf_fetch_wrapper.js`
(executado por `test_wrapper_behaviour_suite_passes` quando há Node).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from extensions import db
from models import Animal, User

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAYOUT = PROJECT_ROOT / "templates" / "layout.html"
WRAPPER = PROJECT_ROOT / "static" / "csrf_fetch.js"

SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>", re.IGNORECASE)


# --- nivel 1: o wrapper esta carregado, e primeiro ---------------------------

def test_wrapper_file_exists():
    assert WRAPPER.is_file(), "static/csrf_fetch.js desapareceu"


def test_layout_loads_wrapper_before_any_other_script():
    """Se outro script rodar antes, as requisições dele saem sem token."""
    text = LAYOUT.read_text(encoding="utf-8", errors="replace")

    wrapper_pos = text.find("csrf_fetch.js")
    assert wrapper_pos != -1, "layout.html não carrega static/csrf_fetch.js"

    for match in SCRIPT_TAG_RE.finditer(text):
        tag = match.group(0)
        if "csrf_fetch.js" in tag:
            break
        # ld+json é dado, não código executável; não faz request.
        if "application/ld+json" in tag:
            continue
        pytest.fail(
            "script executado antes do wrapper de CSRF "
            f"(linha {text.count(chr(10), 0, match.start()) + 1}): {tag[:90]}\n"
            "Requisições feitas por ele sairiam sem token."
        )


def test_layout_still_exposes_csrf_meta_tag():
    """O wrapper lê o token do <meta>; sem ele o wrapper vira no-op."""
    text = LAYOUT.read_text(encoding="utf-8", errors="replace")
    assert 'name="csrf-token"' in text
    assert text.find('name="csrf-token"') < text.find("csrf_fetch.js"), (
        "a meta do token precisa existir antes do wrapper no documento"
    )


@pytest.mark.parametrize(
    "marker, porque",
    [
        ("POST|PUT|PATCH|DELETE", "só métodos mutantes devem receber token"),
        ("isSameOrigin", "não pode vazar token para outra origem"),
        ("headers.has(HEADER)", "não pode sobrescrever header já definido"),
        ("querySelector('meta[name=\"csrf-token\"]')", "token lido da meta"),
        ("XMLHttpRequest", "XHR também precisa ser coberto"),
    ],
)
def test_wrapper_keeps_its_safety_properties(marker, porque):
    source = WRAPPER.read_text(encoding="utf-8", errors="replace")
    assert marker in source, f"wrapper perdeu proteção: {porque}"


def test_rendered_page_ships_wrapper_and_meta(client, app):
    """Prova no HTML servido, não só no template."""
    response = client.get("/login")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "csrf_fetch.js" in body
    assert 'name="csrf-token"' in body


# --- nivel 2: contrato do servidor ------------------------------------------

CSRF_ENDPOINTS = [
    ("post", "/chat/{animal_id}", {"content": "oi", "sender_id": 1, "receiver_id": 1}),
    ("put", "/vacina/1", {"nome": "x"}),
    ("put", "/racao/1", {"preco_pago": 1}),
]


@pytest.fixture()
def csrf_client(app):
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["SESSION_COOKIE_SECURE"] = False
    user = User(name="T", email="ajax@example.com", role="adotante", worker="veterinario")
    user.set_password("x")
    db.session.add(user)
    db.session.commit()
    animal = Animal(name="Rex", user_id=user.id)
    db.session.add(animal)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
    return client, animal.id


@pytest.mark.parametrize("method, path, payload", CSRF_ENDPOINTS)
def test_ajax_route_rejects_request_without_token(csrf_client, method, path, payload):
    """Sem token continua barrado — a proteção não pode ter sido afrouxada."""
    client, animal_id = csrf_client
    response = getattr(client, method)(
        path.format(animal_id=animal_id),
        headers={"Content-Type": "application/json", "Referer": "https://localhost/x"},
        data=json.dumps(payload),
    )
    assert response.status_code == 400
    assert "CSRF" in response.get_data(as_text=True)


@pytest.mark.parametrize("method, path, payload", CSRF_ENDPOINTS)
def test_ajax_route_accepts_x_csrftoken_header(csrf_client, method, path, payload):
    """Com o header que o wrapper injeta, o CSRF deixa passar.

    Não afirmamos sucesso de negócio (o payload é sintético): o ponto é que a
    resposta não seja mais a rejeição de CSRF.
    """
    client, animal_id = csrf_client
    page = client.get("/login")
    token = re.search(
        r'name="csrf-token" content="([^"]+)"', page.get_data(as_text=True)
    ).group(1)

    response = getattr(client, method)(
        path.format(animal_id=animal_id),
        headers={
            "Content-Type": "application/json",
            "Referer": "https://localhost/x",
            "X-CSRFToken": token,
        },
        data=json.dumps(payload),
    )
    body = response.get_data(as_text=True)
    assert not (
        response.status_code == 400 and "CSRF token missing or invalid" in body
    ), f"header X-CSRFToken deixou de ser aceito em {method.upper()} {path}"


def test_chat_message_is_actually_persisted_with_header(csrf_client):
    """O pior caso do bug, provado ponta a ponta.

    Antes, o JS do chat dava await no fetch sem token, ignorava a resposta e
    limpava o campo: a mensagem sumia da tela sem nunca ter sido gravada. Aqui
    exigimos gravação de verdade, não só "não foi barrado por CSRF".
    """
    from models import Message

    client, animal_id = csrf_client
    page = client.get("/login")
    token = re.search(
        r'name="csrf-token" content="([^"]+)"', page.get_data(as_text=True)
    ).group(1)
    user_id = int(db.session.query(User.id).filter_by(email="ajax@example.com").scalar())

    antes = Message.query.filter_by(animal_id=animal_id).count()
    response = client.post(
        f"/chat/{animal_id}",
        headers={
            "Content-Type": "application/json",
            "Referer": "https://localhost/x",
            "X-CSRFToken": token,
        },
        data=json.dumps(
            {"sender_id": user_id, "receiver_id": user_id, "content": "mensagem de teste"}
        ),
    )

    assert response.status_code in (200, 201), response.get_data(as_text=True)[:200]
    assert Message.query.filter_by(animal_id=animal_id).count() == antes + 1
    gravada = Message.query.filter_by(animal_id=animal_id).order_by(Message.id.desc()).first()
    assert gravada.content == "mensagem de teste"


# --- comportamento real do wrapper, via Node --------------------------------

def test_wrapper_behaviour_suite_passes():
    """Executa o wrapper de verdade contra stubs de DOM.

    Sem isto os testes acima só provariam que o arquivo *existe* e tem certas
    palavras — não que ele anexa o header corretamente.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("Node não disponível para exercitar o wrapper JS")

    suite = PROJECT_ROOT / "tests" / "test_csrf_fetch_wrapper.js"
    assert suite.is_file(), "suite JS do wrapper não encontrada"

    result = subprocess.run(
        [node, str(suite)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=60,
    )
    assert result.returncode == 0, (
        f"suite JS do wrapper falhou:\n{result.stdout}\n{result.stderr}"
    )
