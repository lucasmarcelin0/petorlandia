# -*- coding: utf-8 -*-
"""Auditoria de navegação do tutor comum.

Navega como um tutor (sem pet e com pet) seguindo todos os links GET internos
que aparecem nas páginas e falha se algum levar a erro 500, 404 ou a uma tela
de "sem permissão" (ex.: o antigo 'Apenas veterinários ou colaboradores podem
cadastrar animais' que aparecia ao clicar em 'Cadastrar pet').
"""
import re
from collections import deque

import pytest

from app import app as flask_app, db
from models import User, Animal, Veterinario, Endereco


HREF_RE = re.compile(r'href="([^"#]+)"')

# Textos que indicam que o tutor foi barrado por permissão após clicar num
# link que estava visível para ele — sempre um bug de UX.
PERMISSION_PATTERNS = [
    'Apenas veterin',
    'Apenas colaborador',
    'Acesso restrito',
    'Acesso negado',
    'não tem permissão',
    'permissão negada',
    'Somente veterin',
]

SKIP_PREFIXES = (
    '/logout', '/static', 'http', 'mailto:', 'tel:', 'javascript:',
    'whatsapp', '//',
)

MAX_PAGES = 250


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
    )
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def seed(app):
    with app.app_context():
        tutor_sem_pet = User(
            name='Tutor Sem Pet', email='sempet@teste.com',
            endereco=Endereco(rua='Rua A', cidade='Orlândia', estado='SP'),
        )
        tutor_sem_pet.set_password('x')

        tutor_com_pet = User(
            name='Tutor Com Pet', email='compet@teste.com',
            endereco=Endereco(rua='Rua B', cidade='Orlândia', estado='SP'),
        )
        tutor_com_pet.set_password('x')

        vet_user = User(
            name='Vet Teste', email='vet@teste.com', worker='veterinario',
            endereco=Endereco(rua='Rua C', cidade='Orlândia', estado='SP'),
        )
        vet_user.set_password('x')
        db.session.add_all([tutor_sem_pet, tutor_com_pet, vet_user])
        db.session.flush()

        vet = Veterinario(user_id=vet_user.id, crmv='12345', crmv_estado='SP')
        animal = Animal(name='Rex', user_id=tutor_com_pet.id, modo='adotado')
        db.session.add_all([vet, animal])
        db.session.commit()

        return {
            'sem_pet': tutor_sem_pet.id,
            'com_pet': tutor_com_pet.id,
            'vet_id': vet.id,
        }


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def _crawl(client, seeds):
    queue = deque((url, '(seed)') for url in seeds)
    visited = set()
    problems = []

    while queue and len(visited) < MAX_PAGES:
        url, source = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        resp = client.get(url, follow_redirects=True)

        if resp.status_code >= 500:
            problems.append(f'{url} (linkado de {source}): HTTP {resp.status_code}')
            continue
        if resp.status_code == 404 and source != '(seed)':
            problems.append(f'{url} (linkado de {source}): HTTP 404')
            continue

        if 'text/html' not in resp.headers.get('Content-Type', ''):
            continue
        html = resp.get_data(as_text=True)

        for pattern in PERMISSION_PATTERNS:
            if pattern in html:
                problems.append(
                    f'{url} (linkado de {source}): tela de permissão negada ("{pattern}")'
                )
                break

        for href in HREF_RE.findall(html):
            href = href.strip().split('#')[0]
            if not href or not href.startswith('/') or href.startswith(SKIP_PREFIXES):
                continue
            if href not in visited:
                queue.append((href, url))

    return visited, problems


@pytest.mark.parametrize('profile', ['sem_pet', 'com_pet'])
def test_tutor_links_never_hit_permission_walls(app, seed, profile):
    client = app.test_client()
    _login(client, seed[profile])

    seeds = [
        '/', '/servicos', '/servicos/exames', '/loja', '/add-animal',
        '/animals', '/profile', '/carrinho', '/plano-saude',
        f"/veterinario/{seed['vet_id']}",
    ]
    visited, problems = _crawl(client, seeds)

    assert len(visited) > 10, 'crawl não navegou o suficiente — seeds quebrados?'
    assert not problems, 'Links de tutor com problema:\n' + '\n'.join(problems)


def test_tutor_on_professional_animal_route_is_redirected(app, seed):
    """Tutor que cair em /novo_animal (rota profissional) vai para /add-animal."""
    client = app.test_client()
    _login(client, seed['sem_pet'])

    resp = client.get('/novo_animal')
    assert resp.status_code == 302
    assert '/add-animal' in resp.headers['Location']

    resp = client.get('/novo_animal', follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert 'Apenas veterin' not in html
