"""Tirar o fundo do logo da clínica (services/logo_fundo.py e rotas).

O upload antigo achatava todo logo em JPEG, e o transparente virava um
quadrado branco atrás do desenho.
"""
import os
import sys
from io import BytesIO

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from PIL import Image, ImageDraw

import app as app_module
from app import app as flask_app, db
from models import Clinica, User
from services.logo_fundo import FundoNaoRemovivel, remover_fundo


def _jpeg(imagem):
    arquivo = BytesIO()
    imagem.save(arquivo, format='JPEG', quality=85)
    arquivo.seek(0)
    return Image.open(arquivo)


def _logo_em_fundo_branco():
    imagem = Image.new('RGB', (400, 300), 'white')
    desenho = ImageDraw.Draw(imagem)
    desenho.ellipse((100, 50, 300, 250), fill=(20, 60, 140))
    desenho.ellipse((175, 125, 225, 175), fill='white')  # branco DENTRO do desenho
    return _jpeg(imagem)


def test_remove_fundo_branco_e_preserva_branco_interno():
    resultado = remover_fundo(_logo_em_fundo_branco())

    assert resultado.mode == 'RGBA'
    assert resultado.getpixel((0, 0))[3] == 0
    centro = (resultado.size[0] // 2, resultado.size[1] // 2)
    assert resultado.getpixel(centro)[3] == 255
    assert resultado.getpixel(centro)[:3] >= (240, 240, 240)
    # Margem vazia cortada: o logo ocupa quase toda a imagem.
    assert resultado.size[0] < 260 and resultado.size[1] < 260


def test_recusa_fundo_que_nao_e_liso():
    degrade = Image.linear_gradient('L').resize((300, 300)).convert('RGB')
    with pytest.raises(FundoNaoRemovivel, match='não é de uma cor só'):
        remover_fundo(degrade)


def test_recusa_logo_que_ja_esta_sem_fundo():
    transparente = Image.new('RGBA', (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(transparente).ellipse((40, 40, 160, 160), fill=(0, 120, 0, 255))
    with pytest.raises(FundoNaoRemovivel, match='já está sem fundo'):
        remover_fundo(transparente)


@pytest.fixture
def app(monkeypatch):
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    _zerar_limite_de_login()
    yield flask_app
    _zerar_limite_de_login()
    with flask_app.app_context():
        db.drop_all()


def _zerar_limite_de_login():
    from extensions import limiter

    try:
        limiter.reset()
    except Exception:  # noqa: BLE001
        pass


def _criar_clinica_com_dono():
    dono = User(name='Paulo', email='dono@example.com')
    dono.set_password('pw-dono')
    outro = User(name='Outro', email='outro@example.com')
    outro.set_password('pw-outro')
    db.session.add_all([dono, outro])
    db.session.flush()
    clinica = Clinica(nome='Clínica do Paulo', owner_id=dono.id, logotipo='https://bucket.exemplo/logo.jpg')
    db.session.add(clinica)
    db.session.commit()
    return clinica.id


def _login(client, email, senha):
    resposta = client.post('/login', data={'email': email, 'password': senha}, follow_redirects=True)
    assert resposta.status_code == 200


def test_dono_remove_fundo_e_pode_desfazer(app, monkeypatch):
    enviados = []

    def upload_falso(arquivo, nome, folder='uploads', **kwargs):
        enviados.append((nome, folder, kwargs.get('keep_transparency'), Image.open(arquivo).mode))
        return 'https://bucket.exemplo/logo_sem_fundo.png'

    monkeypatch.setattr('services.logo_fundo.abrir_logo', lambda url: _logo_em_fundo_branco())
    monkeypatch.setattr(app_module, 'upload_to_s3', upload_falso)

    with app.app_context():
        clinica_id = _criar_clinica_com_dono()

    client = app.test_client()
    with client:
        _login(client, 'dono@example.com', 'pw-dono')
        resposta = client.post(f'/clinica/{clinica_id}/logo/remover-fundo')
        assert resposta.status_code == 302
        with app.app_context():
            assert db.session.get(Clinica, clinica_id).logotipo == 'https://bucket.exemplo/logo_sem_fundo.png'
        assert enviados and enviados[0][1:] == ('clinicas', True, 'RGBA')
        assert enviados[0][0].endswith('.png')

        pagina = client.get(f'/clinica/{clinica_id}').get_data(as_text=True)
        assert 'Remover fundo do logo' in pagina
        assert 'Desfazer' in pagina

        client.post(f'/clinica/{clinica_id}/logo/desfazer-fundo')
        with app.app_context():
            assert db.session.get(Clinica, clinica_id).logotipo == 'https://bucket.exemplo/logo.jpg'


def test_fundo_que_nao_da_para_tirar_nao_altera_o_logo(app, monkeypatch):
    degrade = Image.linear_gradient('L').resize((300, 300)).convert('RGB')
    monkeypatch.setattr('services.logo_fundo.abrir_logo', lambda url: degrade)
    monkeypatch.setattr(app_module, 'upload_to_s3', lambda *a, **k: pytest.fail('não deveria enviar'))

    with app.app_context():
        clinica_id = _criar_clinica_com_dono()

    client = app.test_client()
    with client:
        _login(client, 'dono@example.com', 'pw-dono')
        resposta = client.post(f'/clinica/{clinica_id}/logo/remover-fundo', follow_redirects=True)
    assert 'não é de uma cor só' in resposta.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Clinica, clinica_id).logotipo == 'https://bucket.exemplo/logo.jpg'


def test_quem_nao_gerencia_a_clinica_nao_mexe_no_logo(app, monkeypatch):
    monkeypatch.setattr('services.logo_fundo.abrir_logo', lambda url: pytest.fail('não deveria abrir'))

    with app.app_context():
        clinica_id = _criar_clinica_com_dono()

    client = app.test_client()
    with client:
        _login(client, 'outro@example.com', 'pw-outro')
        # 404 vem da guarda global de escopo de clínica; 403 da própria rota.
        assert client.post(f'/clinica/{clinica_id}/logo/remover-fundo').status_code in (403, 404)
        assert client.post(f'/clinica/{clinica_id}/logo/desfazer-fundo').status_code in (403, 404)
    with app.app_context():
        assert db.session.get(Clinica, clinica_id).logotipo == 'https://bucket.exemplo/logo.jpg'
