"""PDF da receita gerado no servidor (botão "Baixar PDF").

Existe porque o "Salvar como PDF" de alguns celulares grava um arquivo de 0 B,
que não abre e que o assinador do gov.br recusa ("Arquivo não encontrado").
"""
import base64
import os
import re
import sys
import zlib
from io import BytesIO
from types import SimpleNamespace

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

from app import app as flask_app, db
from models import Animal, BlocoPrescricao, Clinica, Prescricao, User, Veterinario
from services.receita_pdf import nome_arquivo_receita


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.drop_all()


def _texto_do_pdf(pdf: bytes) -> str:
    """Junta o conteúdo decodificado dos streams do PDF para buscar texto.

    O ReportLab grava os streams em ASCII85 + Flate por padrão.
    """
    partes = []
    for bruto in re.findall(rb'stream\r?\n(.*?)endstream', pdf, re.S):
        dados = bruto.strip()
        if dados.endswith(b'~>'):
            try:
                dados = base64.a85decode(dados[:-2])
            except ValueError:
                continue
        try:
            dados = zlib.decompress(dados)
        except zlib.error:
            pass
        partes.append(dados.decode('latin-1', 'ignore'))
    return '\n'.join(partes)


def _criar_receita(observacoes='Dar com alimento & agua <depois> do almoco'):
    clinica = Clinica(nome='Clinica Prescricao', telefone='(16) 3333-0000', cnpj='12345678000190')
    db.session.add(clinica)
    db.session.flush()

    vet = User(name='Dra Paula', email='vet@example.com', worker='veterinario', role='admin')
    vet.set_password('pw-vet')
    db.session.add(vet)
    db.session.flush()
    db.session.add(Veterinario(user=vet, crmv='SP-123', clinica=clinica))

    tutor = User(name='Paulo Antonio', email='tutor@example.com')
    tutor.set_password('pw-tutor')
    animal = Animal(name='Mãezinha', owner=tutor, clinica=clinica)
    db.session.add_all([tutor, animal])
    db.session.flush()

    bloco = BlocoPrescricao(
        animal=animal,
        saved_by=vet,
        clinica=clinica,
        instrucoes_gerais='Repouso por 7 dias.\nRetorno em 10 dias.',
    )
    db.session.add(bloco)
    db.session.flush()
    db.session.add(Prescricao(
        animal_id=animal.id,
        bloco_id=bloco.id,
        medicamento='Amoxicilina 250mg',
        dosagem='1 comprimido',
        frequencia='12/12h',
        duracao='7 dias',
        observacoes=observacoes,
    ))
    db.session.commit()
    return bloco.id


def _login(client, email, password):
    resp = client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)
    assert resp.status_code == 200


def test_veterinario_baixa_pdf_valido_da_receita(app):
    with app.app_context():
        bloco_id = _criar_receita()

    client = app.test_client()
    with client:
        _login(client, 'vet@example.com', 'pw-vet')
        resp = client.get(f'/bloco_prescricao/{bloco_id}/pdf')

    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    disposicao = resp.headers['Content-Disposition']
    assert disposicao.startswith('attachment;')
    # Nome só com ASCII: sem acento nem "|", que o título da página levava.
    assert f'receita-{bloco_id}-maezinha.pdf' in disposicao
    assert 'no-store' in resp.headers['Cache-Control']

    pdf = resp.get_data()
    assert pdf.startswith(b'%PDF-')
    assert pdf.rstrip().endswith(b'%%EOF')
    assert int(resp.headers['Content-Length']) == len(pdf)

    texto = _texto_do_pdf(pdf)
    assert 'Amoxicilina 250mg' in texto
    assert '12/12h' in texto
    assert 'Paulo Antonio' in texto
    assert 'SP-123' in texto
    assert 'Clinica Prescricao' in texto
    assert 'Repouso por 7 dias.' in texto
    # O texto livre do veterinário é escapado, não interpretado como marcação.
    assert 'depois' in texto


def test_tela_da_receita_mostra_botao_baixar_pdf(app):
    with app.app_context():
        bloco_id = _criar_receita()

    client = app.test_client()
    with client:
        _login(client, 'vet@example.com', 'pw-vet')
        html = client.get(f'/bloco_prescricao/{bloco_id}/imprimir').get_data(as_text=True)

    assert 'Baixar PDF' in html
    assert f'/bloco_prescricao/{bloco_id}/pdf' in html
    # O caminho antigo continua disponível.
    assert 'window.print()' in html


def test_tutor_pelo_link_com_token_baixa_o_pdf(app):
    with app.app_context():
        bloco_id = _criar_receita()
        from app import _first_access_token_for_user

        tutor = User.query.filter_by(email='tutor@example.com').one()
        token = _first_access_token_for_user(tutor)

    client = app.test_client()
    resp = client.get(f'/bloco_prescricao/{bloco_id}/pdf?token={token}')
    assert resp.status_code == 200
    assert resp.get_data().startswith(b'%PDF-')


def test_visitante_sem_token_nao_recebe_o_pdf(app):
    with app.app_context():
        bloco_id = _criar_receita()

    resp = app.test_client().get(f'/bloco_prescricao/{bloco_id}/pdf')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    assert not resp.get_data().startswith(b'%PDF-')


def test_usuario_de_outra_clinica_nao_recebe_o_pdf(app):
    with app.app_context():
        bloco_id = _criar_receita()
        outro = User(name='Curioso', email='curioso@example.com')
        outro.set_password('pw-curioso')
        db.session.add(outro)
        db.session.commit()

    client = app.test_client()
    with client:
        _login(client, 'curioso@example.com', 'pw-curioso')
        resp = client.get(f'/bloco_prescricao/{bloco_id}/pdf')
    assert resp.status_code == 404


def test_receita_assinada_vazia_e_recusada(app, monkeypatch):
    with app.app_context():
        bloco_id = _criar_receita()

    enviados = []
    monkeypatch.setattr(
        'blueprints.consulta.upload_to_s3',
        lambda *args, **kwargs: enviados.append(args) or 'https://exemplo/receita.pdf',
        raising=False,
    )

    client = app.test_client()
    with client:
        _login(client, 'vet@example.com', 'pw-vet')
        resp = client.post(
            f'/bloco_prescricao/{bloco_id}/assinatura',
            data={'documento': (BytesIO(b''), 'Receita de Mãezinha _ Prefeitura.pdf')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )

    assert resp.status_code == 200
    assert 'vazio (0 B)' in resp.get_data(as_text=True)
    assert enviados == []
    with app.app_context():
        assert db.session.get(BlocoPrescricao, bloco_id).assinatura_arquivo_url is None


def test_nome_arquivo_receita_sem_acentos():
    bloco = SimpleNamespace(id=7, animal=SimpleNamespace(name='Mãezinha | Prefeitura'))
    assert nome_arquivo_receita(bloco) == 'receita-7-maezinha-prefeitura.pdf'
    assert nome_arquivo_receita(SimpleNamespace(id=8, animal=None)) == 'receita-8.pdf'


def test_pdf_com_logotipo_da_clinica(app, monkeypatch, tmp_path):
    """O logotipo entra no PDF; antes desta cobertura, ele derrubava a rota."""
    from PIL import Image as PILImage

    pasta = tmp_path / 'uploads' / 'clinicas'
    pasta.mkdir(parents=True)
    PILImage.new('RGBA', (300, 120), (31, 58, 86, 255)).save(pasta / 'logo.png')
    monkeypatch.setattr(app, 'static_folder', str(tmp_path))

    with app.app_context():
        bloco_id = _criar_receita()
        clinica = db.session.get(BlocoPrescricao, bloco_id).clinica
        clinica.logotipo = 'logo.png'
        db.session.commit()

    client = app.test_client()
    with client:
        _login(client, 'vet@example.com', 'pw-vet')
        resp = client.get(f'/bloco_prescricao/{bloco_id}/pdf')

    assert resp.status_code == 200
    assert b'/Subtype /Image' in resp.get_data()


def test_pdf_sai_mesmo_sem_conseguir_baixar_o_logotipo(app, monkeypatch):
    import requests

    def falha(*args, **kwargs):
        raise requests.ConnectionError('sem rede')

    monkeypatch.setattr(requests, 'get', falha)
    with app.app_context():
        bloco_id = _criar_receita()
        clinica = db.session.get(BlocoPrescricao, bloco_id).clinica
        clinica.logotipo = 'https://bucket.exemplo/logo.png'
        db.session.commit()

    client = app.test_client()
    with client:
        _login(client, 'vet@example.com', 'pw-vet')
        resp = client.get(f'/bloco_prescricao/{bloco_id}/pdf')

    assert resp.status_code == 200
    assert b'/Subtype /Image' not in resp.get_data()


def test_texto_fora_da_fonte_vira_equivalente_ou_some():
    from services.receita_pdf import _texto

    assert _texto('Peso ≥ 10kg 🐶 ½ comp. & <1x>') == 'Peso &gt;= 10kg  ½ comp. &amp; &lt;1x&gt;'
    assert _texto('Linha 1\nLinha 2') == 'Linha 1<br/>Linha 2'
