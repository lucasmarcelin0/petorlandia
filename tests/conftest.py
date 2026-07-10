import os
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

from app_factory import create_app
from extensions import db


@pytest.fixture(autouse=True, scope="module")
def _isolate_app_state():
    """Isola o estado global do app singleton entre ARQUIVOS de teste.

    create_app() devolve sempre a mesma instância; testes que mutam
    diretamente app.config (ex.: LOGIN_DISABLED=True), substituem itens de
    template_context_processors ou registram error handlers vazariam esse
    estado para os arquivos seguintes quando a suíte roda num único processo.
    Snapshot no início / restore no fim de cada módulo elimina a poluição
    entre arquivos sem interferir em fixtures de escopo módulo dos próprios
    arquivos.
    """
    application = create_app()
    saved_config = dict(application.config)
    saved_processors = {
        key: list(value)
        for key, value in application.template_context_processors.items()
    }
    # error_handler_spec fica de fora de propósito: a estrutura aninhada do
    # Flask não sobrevive a snapshot/restore raso e handlers custom de teste
    # são raros (usar monkeypatch nesses casos).
    yield
    application.config.clear()
    application.config.update(saved_config)
    application.template_context_processors.clear()
    application.template_context_processors.update(saved_processors)


@pytest.fixture(autouse=True)
def _clear_context_cache():
    """Zera o cache de badges (TTL 30s) entre testes.

    O cache é keyed por user_id; testes recriam usuários com os mesmos ids e
    herdariam contadores/flags do teste anterior (ex.: has_clinic_access).
    """
    from context_processors import _context_cache

    _context_cache.clear()
    yield
    _context_cache.clear()


@pytest.fixture()
def app():
    app = create_app()
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={},
        WTF_CSRF_ENABLED=False,
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()
