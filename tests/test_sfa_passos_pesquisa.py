"""Card "Passos da pesquisa" no painel do SFA."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from extensions import db
from models.sfa import SfaPassoPesquisa

MIGRACAO = Path('migrations/versions/f8b2c6d4e1a7_sfa_passos_pesquisa.py')


def _passos(app, *itens):
    with app.app_context():
        for ordem, (titulo, url) in enumerate(itens, start=1):
            db.session.add(SfaPassoPesquisa(titulo=titulo, url=url, ordem=ordem))
        db.session.commit()
        return [p.id for p in SfaPassoPesquisa.query.order_by(SfaPassoPesquisa.ordem)]


def test_painel_mostra_passos_como_botoes_no_lugar_dos_pilotos(app, client):
    _passos(app, ('Projeto de pesquisa', 'https://docs.google.com/document/d/projeto/edit'),
            ('TCLE', 'https://docs.google.com/document/d/tcle/edit'))

    html = client.get('/sfa/').get_data(as_text=True)

    assert 'Passos da pesquisa' in html
    assert 'href="https://docs.google.com/document/d/projeto/edit" target="_blank"' in html
    assert '1. Projeto de pesquisa' in html and '2. TCLE' in html
    assert '0 de 2 concluídos' in html
    assert 'Nenhum participante piloto cadastrado' not in html
    assert '/sfa/pilotos' in html  # o gerenciamento de pilotos continua acessível


def test_marcar_e_desmarcar_concluido(app, client):
    (pid,) = _passos(app, ('TCLE', 'https://exemplo.org/tcle'))

    resposta = client.post(f'/sfa/passos/{pid}/concluido', data={'concluido': '1'})
    assert resposta.status_code == 302 and resposta.headers['Location'].endswith('#passos-pesquisa')
    with app.app_context():
        passo = db.session.get(SfaPassoPesquisa, pid)
        assert passo.concluido is True and passo.concluido_em is not None
    html = client.get('/sfa/').get_data(as_text=True)
    assert '1 de 1 concluído' in html and 'btn-success' in html and 'Concluído em' in html

    client.post(f'/sfa/passos/{pid}/concluido', data={'concluido': '0'})
    with app.app_context():
        passo = db.session.get(SfaPassoPesquisa, pid)
        assert passo.concluido is False and passo.concluido_em is None


def test_editar_adicionar_e_remover_passo(app, client):
    (pid,) = _passos(app, ('Projeto', 'https://exemplo.org/projeto'))

    client.post(f'/sfa/passos/{pid}', data={'titulo': 'Projeto revisado', 'url': 'https://exemplo.org/v2', 'acao': 'salvar'})
    client.post('/sfa/passos', data={'titulo': 'Plataforma Brasil', 'url': ''})
    with app.app_context():
        passos = SfaPassoPesquisa.query.order_by(SfaPassoPesquisa.ordem).all()
        assert [(p.titulo, p.url) for p in passos] == [('Projeto revisado', 'https://exemplo.org/v2'), ('Plataforma Brasil', '')]
        novo_id = passos[1].id
    assert '(sem link)' in client.get('/sfa/').get_data(as_text=True)

    client.post(f'/sfa/passos/{novo_id}', data={'acao': 'remover'})
    with app.app_context():
        assert SfaPassoPesquisa.query.count() == 1


def test_link_que_nao_e_http_e_recusado(app, client):
    (pid,) = _passos(app, ('TCLE', 'https://exemplo.org/tcle'))

    client.post(f'/sfa/passos/{pid}', data={'titulo': 'TCLE', 'url': 'javascript:alert(1)', 'acao': 'salvar'})
    client.post('/sfa/passos', data={'titulo': 'Ruim', 'url': 'ftp://exemplo.org'})
    with app.app_context():
        assert db.session.get(SfaPassoPesquisa, pid).url == 'https://exemplo.org/tcle'
        assert SfaPassoPesquisa.query.count() == 1


def test_migracao_cria_os_tres_passos_iniciais():
    spec = importlib.util.spec_from_file_location('passos_migration', MIGRACAO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert modulo.down_revision == 'e7a3c9d5b1f4'
    engine = sa.create_engine('sqlite://')
    with engine.begin() as conn:
        modulo.op = Operations(MigrationContext.configure(conn))
        modulo.upgrade()
        linhas = conn.execute(sa.text('SELECT ordem, titulo, concluido FROM sfa_passo_pesquisa ORDER BY ordem')).fetchall()
        assert [(o, t) for o, t, _ in linhas] == [(1, 'Projeto de pesquisa'), (2, 'TCLE'), (3, 'Questionário T0, T7 e T30')]
        assert not any(c for _, _, c in linhas)
        modulo.upgrade()  # idempotente
        modulo.downgrade()
        assert 'sfa_passo_pesquisa' not in sa.inspect(conn).get_table_names()
