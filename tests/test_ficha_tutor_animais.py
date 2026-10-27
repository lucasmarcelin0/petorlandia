"""Ficha do tutor: cadastro e edição de animais à prova de erros bobos.

Cobre os problemas encontrados ao cadastrar vários animais pela ficha:
envio cortado que chegava como formulário vazio, segundo animal herdando a
data do primeiro (lado do servidor: cada envio é independente), reenvio
duplicando cadastro, peso com vírgula, foto que sumia quando o S3 falhava,
"Não sei" virando "Não", e os atalhos de WhatsApp/ligação/mapa.
"""

import os
import sys
from io import BytesIO

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

import app as app_module  # noqa: E402
from app import app as flask_app, db  # noqa: E402
from models import Animal, Breed, Endereco, Species, User  # noqa: E402
from test_intern_start_consulta import _build_clinic, client, login  # noqa: E402,F401

JSON = {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
HTML = {'Accept': 'text/html,application/xhtml+xml'}


def _jpeg(largura=40, altura=60, cor=(200, 120, 80)):
    buffer = BytesIO()
    Image.new('RGB', (largura, altura), cor).save(buffer, format='JPEG')
    buffer.seek(0)
    return buffer


@pytest.fixture
def uploads(monkeypatch):
    """Troca o envio ao S3 por uma lista em memória."""
    enviados = []

    def fake_upload(file, filename, folder='uploads', **kwargs):
        stream = getattr(file, 'stream', file)
        dados = stream.read()
        enviados.append({'filename': filename, 'folder': folder, 'bytes': dados})
        return f'https://bucket.test/{folder}/{filename}'

    monkeypatch.setattr(app_module, 'upload_to_s3', fake_upload)
    return enviados


def _preparar(monkeypatch, *, telefone='+5516991234567', com_endereco=True):
    """Clínica do teste + tutor visível para o veterinário (id 2)."""
    _build_clinic()
    tutor = db.session.get(User, 1)
    tutor.clinica_id = 1
    tutor.phone = telefone
    if com_endereco:
        tutor.endereco = Endereco(
            cep='14620-000', rua='Rua Sete de Setembro', numero='245',
            bairro='Centro', cidade='Orlândia', estado='SP',
        )
    cao = Species(id=1, name='Cachorro')
    db.session.add(cao)
    db.session.flush()
    db.session.add(Breed(id=1, name='SRD', species_id=1))
    rex = db.session.get(Animal, 1)
    rex.species_id = 1
    rex.sex = 'Macho'
    rex.peso = 12.5
    db.session.commit()
    login(monkeypatch, db.session.get(User, 2))


def _animal(animal_id=1):
    db.session.expire_all()
    return db.session.get(Animal, animal_id)


# ------------------------------------------------------ envio cortado (global)

CORPO_CORTADO = (
    '--XyZ\r\nContent-Disposition: form-data; name="name"\r\n\r\nRex\r\n'
    '--XyZ\r\nContent-Disposition: form-data; name="image"; filename="f.jpg"\r\n'
    'Content-Type: image/jpeg\r\n\r\n'
).encode() + b'\xff' * 4000


def test_envio_cortado_volta_para_o_formulario_quando_nao_e_json(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = client.post(
            '/update_animal/1', data=CORPO_CORTADO,
            content_type='multipart/form-data; boundary=XyZ',
            headers={**HTML, 'Referer': 'http://localhost/ficha_tutor/1'},
        )
        assert resp.status_code == 303
        assert resp.headers['Location'].endswith('/ficha_tutor/1')
        assert _animal().peso == 12.5


def test_envio_cortado_e_barrado_antes_do_csrf(client, monkeypatch):
    """Com CSRF ligado (produção), a primeira leitura do formulário já barra."""
    with flask_app.app_context():
        _preparar(monkeypatch)
        monkeypatch.setitem(flask_app.config, 'WTF_CSRF_ENABLED', True)
        resp = client.post(
            '/update_animal/1', data=CORPO_CORTADO,
            content_type='multipart/form-data; boundary=XyZ', headers=JSON,
        )
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'incomplete_body'
        assert _animal().sex == 'Macho'


def test_corpo_valido_continua_passando(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = client.post('/update_animal/1', data={'name': 'Rex', 'sex': 'Macho', 'peso': '11'}, headers=JSON)
        assert resp.status_code == 200
        assert _animal().peso == 11.0


# ------------------------------------------------------------- update_animal

def test_edicao_aceita_peso_com_virgula_e_devolve_o_animal(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = client.post('/update_animal/1', data={'name': 'Rex', 'peso': '13,2', 'sex': 'Macho'}, headers=JSON)
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['animal']['peso'] == 13.2
        assert payload['animal']['species'] == 'Cachorro'
        assert _animal().peso == 13.2


def test_edicao_com_peso_invalido_mantem_o_anterior_e_avisa(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = client.post('/update_animal/1', data={'name': 'Rex', 'peso': 'doze'}, headers=JSON)
        assert resp.status_code == 200
        assert any('Peso inválido' in m['message'] for m in resp.get_json().get('messages', []))
        assert _animal().peso == 12.5


@pytest.mark.parametrize('enviado, esperado', [('1', True), ('0', False), ('', None)])
def test_castrado_nao_sei_fica_sem_resposta(client, monkeypatch, enviado, esperado):
    with flask_app.app_context():
        _preparar(monkeypatch)
        client.post('/update_animal/1', data={'name': 'Rex', 'neutered': enviado}, headers=JSON)
        assert _animal().neutered is esperado


def test_castrado_fora_do_formulario_nao_muda(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        rex = _animal()
        rex.neutered = True
        db.session.commit()
        client.post('/update_animal/1', data={'name': 'Rex'}, headers=JSON)
        assert _animal().neutered is True


def test_apagar_data_e_idade_limpa_o_nascimento(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        client.post('/update_animal/1', data={'name': 'Rex', 'date_of_birth': '2020-05-01', 'age': ''}, headers=JSON)
        assert _animal().date_of_birth is not None
        client.post('/update_animal/1', data={'name': 'Rex', 'date_of_birth': '', 'age': ''}, headers=JSON)
        rex = _animal()
        assert rex.date_of_birth is None
        assert rex.age is None


def test_data_futura_e_recusada(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = client.post('/update_animal/1', data={'name': 'Rex', 'date_of_birth': '2999-01-01'}, headers=JSON)
        assert any('Data de nascimento' in m['message'] for m in resp.get_json().get('messages', []))
        assert _animal().date_of_birth is None


def test_falha_no_armazenamento_nao_apaga_a_foto_nem_o_cadastro(client, monkeypatch):
    """Antes: upload falhava -> animal.image = None e a foto anterior sumia."""
    with flask_app.app_context():
        _preparar(monkeypatch)
        rex = _animal()
        rex.image = 'https://bucket.test/animals/antiga.jpg'
        db.session.commit()

        def upload_quebrado(*args, **kwargs):
            raise ConnectionError('S3 fora do ar')

        monkeypatch.setattr(app_module, 'upload_to_s3', upload_quebrado)
        resp = client.post(
            '/update_animal/1',
            data={'name': 'Outro nome', 'sex': 'Fêmea', 'image': (_jpeg(), 'nova.jpg')},
            content_type='multipart/form-data', headers=JSON,
        )
        assert resp.status_code == 502
        assert resp.get_json()['field'] == 'image'
        rex = _animal()
        assert rex.image == 'https://bucket.test/animals/antiga.jpg'
        assert rex.name == 'Rex'
        assert rex.sex == 'Macho'


def test_foto_em_producao_passa_pelo_armazenamento_duravel(client, monkeypatch, uploads):
    with flask_app.app_context():
        _preparar(monkeypatch)
        monkeypatch.setitem(flask_app.config, 'TESTING', False)
        monkeypatch.setitem(flask_app.config, 'ALLOW_LOCAL_UPLOAD_FALLBACK', False)
        resp = client.post(
            '/update_animal/1',
            data={'name': 'Rex', 'image': (_jpeg(), 'nova.jpg'), 'photo_rotation': '0'},
            content_type='multipart/form-data', headers=JSON,
        )
        assert resp.status_code == 200
        assert _animal().image.startswith('https://bucket.test/animals/')


def test_foto_nova_grava_o_giro_nos_pixels(client, monkeypatch, uploads):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = client.post(
            '/update_animal/1',
            data={'name': 'Rex', 'image': (_jpeg(40, 60), 'retrato.jpg'), 'photo_rotation': '90', 'photo_zoom': '1.5'},
            content_type='multipart/form-data', headers=JSON,
        )
        assert resp.status_code == 200
        rex = _animal()
        assert rex.image.startswith('https://bucket.test/animals/')
        assert rex.photo_rotation == 0
        assert rex.photo_zoom == 1.5
        enviada = Image.open(BytesIO(uploads[-1]['bytes']))
        assert enviada.size[0] > enviada.size[1]  # retrato 40x60 virou paisagem


def test_rotacao_sem_foto_nova_continua_por_css(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        client.post('/update_animal/1', data={'name': 'Rex', 'photo_rotation': '180'}, headers=JSON)
        assert _animal().photo_rotation == 180


# --------------------------------------------------------------- novo_animal

def _novo(client, **campos):
    dados = {'tutor_id': '1', 'species_id': '1', 'sem_lista': '1'}
    dados.update(campos)
    return client.post('/novo_animal', data=dados, headers=JSON)


def test_cadastro_sem_nome_e_recusado(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        antes = Animal.query.count()
        resp = _novo(client, name='   ')
        assert resp.status_code == 400
        assert resp.get_json()['field'] == 'name'
        assert Animal.query.count() == antes


def test_cadastro_sem_tutor_e_recusado(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = client.post('/novo_animal', data={'name': 'Bob'}, headers=JSON)
        assert resp.status_code == 400
        assert resp.get_json()['field'] == 'tutor_id'


def test_idade_invalida_vira_erro_e_nao_sucesso(client, monkeypatch):
    """Antes: flash + redirect; o fetch recebia 200 e dizia "cadastrado"."""
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = _novo(client, name='Bob', age='dois')
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False
        assert Animal.query.filter_by(name='Bob').count() == 0


def test_cadastro_com_peso_virgula_e_castrado_nao_sei(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = _novo(client, name='Bob', peso='8,5', neutered='', sex='')
        assert resp.status_code == 200
        bob = Animal.query.filter_by(name='Bob').one()
        assert bob.peso == 8.5
        assert bob.neutered is None  # o default=False da coluna não pode vencer
        assert bob.sex is None


def test_cadastro_sem_foto_ignora_enquadramento_que_sobrou(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        _novo(client, name='Bob', photo_rotation='270', photo_zoom='2.5', photo_offset_x='40')
        bob = Animal.query.filter_by(name='Bob').one()
        assert (bob.photo_rotation, bob.photo_zoom, bob.photo_offset_x) == (0, 1.0, 0.0)


def test_cadastro_com_foto_guarda_enquadramento(client, monkeypatch, uploads):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = client.post(
            '/novo_animal',
            data={'tutor_id': '1', 'name': 'Bob', 'species_id': '1', 'sem_lista': '1',
                  'image': (_jpeg(), 'bob.jpg'), 'photo_rotation': '90',
                  'photo_zoom': '1.75', 'photo_offset_x': '-12', 'photo_offset_y': '8'},
            content_type='multipart/form-data', headers=JSON,
        )
        assert resp.status_code == 200
        bob = Animal.query.filter_by(name='Bob').one()
        assert bob.image.startswith('https://bucket.test/animals/')
        assert bob.photo_rotation == 0  # giro gravado nos pixels
        assert (bob.photo_zoom, bob.photo_offset_x, bob.photo_offset_y) == (1.75, -12.0, 8.0)


def test_reenvio_do_mesmo_envio_nao_duplica(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        primeiro = _novo(client, name='Thor', envio_id='envio-123')
        assert primeiro.status_code == 200
        segundo = _novo(client, name='Thor', envio_id='envio-123')
        assert segundo.status_code == 200
        payload = segundo.get_json()
        assert payload['already_existed'] is True
        assert payload['animal']['id'] == primeiro.get_json()['animal']['id']
        assert Animal.query.filter_by(name='Thor').count() == 1


def test_mesmo_nome_em_outro_envio_pede_confirmacao(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        _novo(client, name='Thor', date_of_birth='2020-02-01', envio_id='a')
        resp = _novo(client, name='thor', date_of_birth='2020-02-01', envio_id='b')
        assert resp.status_code == 409
        assert resp.get_json()['duplicate'] is True
        confirmado = _novo(client, name='Thor', date_of_birth='2020-02-01', envio_id='b', confirmar_duplicado='1')
        assert confirmado.status_code == 200
        assert Animal.query.filter(db.func.lower(Animal.name) == 'thor').count() == 2


def test_animal_removido_nao_bloqueia_novo_cadastro(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        _novo(client, name='Luna', date_of_birth='2021-01-01')
        luna = Animal.query.filter_by(name='Luna').one()
        luna.removido_em = db.func.now()
        db.session.commit()
        resp = _novo(client, name='Luna', date_of_birth='2021-01-01')
        assert resp.status_code == 200


def test_lista_de_adicionados_so_quando_pedida_e_falha_nao_derruba(client, monkeypatch):
    import blueprints.pacientes as pacientes

    with flask_app.app_context():
        _preparar(monkeypatch)
        sem = _novo(client, name='A1')
        assert 'html' not in sem.get_json()

        def quebra(*args, **kwargs):
            raise RuntimeError('lista indisponível')

        monkeypatch.setattr(pacientes, '_get_recent_animais', quebra)
        com = client.post('/novo_animal', data={'tutor_id': '1', 'name': 'A2', 'species_id': '1'}, headers=JSON)
        assert com.status_code == 200
        assert com.get_json()['success'] is True
        assert Animal.query.filter_by(name='A2').count() == 1


# ------------------------------------------------------------ ficha do tutor

def test_ficha_mostra_atalhos_de_contato(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        html = client.get('/ficha_tutor/1', headers=HTML).get_data(as_text=True)
        assert 'href="https://wa.me/5516991234567"' in html
        assert 'href="tel:+5516991234567"' in html
        assert 'https://www.google.com/maps/search/?api=1&amp;query=Rua%20Sete%20de%20Setembro%2C%20245' in html
        assert 'Centro · Orlândia/SP · 14620-000' in html


@pytest.mark.parametrize('telefone', ['(16) 99123-4567', '016991234567', '16991234567', '+55 16 99123-4567'])
def test_whatsapp_aceita_telefone_em_qualquer_formato(client, monkeypatch, telefone):
    with flask_app.app_context():
        _preparar(monkeypatch, telefone=telefone)
        html = client.get('/ficha_tutor/1', headers=HTML).get_data(as_text=True)
        assert 'href="https://wa.me/5516991234567"' in html


def test_ficha_sem_telefone_nem_endereco_leva_ao_campo(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch, telefone=None, com_endereco=False)
        html = client.get('/ficha_tutor/1', headers=HTML).get_data(as_text=True)
        assert 'href="https://wa.me' not in html
        assert 'href="https://www.google.com/maps' not in html
        assert 'data-ir-para-campo="tutor-phone"' in html
        assert 'data-ir-para-campo="cep"' in html


def test_telefone_estrangeiro_liga_mas_nao_inventa_whatsapp(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch, telefone='+1 555 123 4567')
        html = client.get('/ficha_tutor/1', headers=HTML).get_data(as_text=True)
        assert 'href="https://wa.me' not in html
        assert 'href="tel:+15551234567"' in html


def test_ficha_nunca_mostra_none(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        db.session.add(Animal(name='Temp', user_id=1, clinica_id=1))
        db.session.commit()
        db.session.execute(db.text("UPDATE animal SET name = NULL, species_id = NULL WHERE name = 'Temp'"))
        db.session.commit()
        html = client.get('/ficha_tutor/1', headers=HTML).get_data(as_text=True)
        lista = html[html.index('id="tutor-animais-lista"'):html.index('id="dados"')]
        assert '>None<' not in lista and ' None ' not in lista
        assert 'Sem nome' in lista
        assert 'Espécie não informada' in lista


def test_parametro_editar_abre_so_animal_do_tutor(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        html = client.get('/ficha_tutor/1?editar=1', headers=HTML).get_data(as_text=True)
        assert 'data-editar-animal="1"' in html
        html = client.get('/ficha_tutor/1?editar=999', headers=HTML).get_data(as_text=True)
        assert 'data-editar-animal=""' in html


def test_lista_parcial_da_ficha(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        resp = client.get('/ficha_tutor/1/animais', headers=JSON)
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['ativos'] == 1 and payload['removidos'] == 0
        assert 'id="animal-card-1"' in payload['html']
        assert 'no-store' in resp.headers['Cache-Control']


def test_lista_parcial_respeita_quem_pode_ver(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        visitante = User(id=50, name='Visitante', email='visitante@test', worker='adotante')
        visitante.set_password('x')
        db.session.add(visitante)
        db.session.commit()
        login(monkeypatch, visitante)  # sem clínica nem perfil profissional
        resp = client.get('/ficha_tutor/1/animais', headers=JSON)
        assert resp.status_code == 403


def test_restaurar_animal_removido(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        rex = _animal()
        rex.added_by_id = 2
        db.session.commit()
        assert client.post('/animal/1/deletar', headers=JSON).status_code == 200
        assert _animal().removido_em is not None
        resp = client.post('/animal/1/restaurar', headers=JSON)
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        assert _animal().removido_em is None


def test_restaurar_exige_a_mesma_permissao_de_remover(client, monkeypatch):
    with flask_app.app_context():
        _preparar(monkeypatch)
        rex = _animal()
        rex.removido_em = db.func.now()
        rex.added_by_id = None
        db.session.commit()
        resp = client.post('/animal/1/restaurar', headers=JSON)
        assert resp.status_code == 403
        assert _animal().removido_em is not None


# --------------------------------------------------------- funções auxiliares

@pytest.mark.parametrize('entrada, esperado', [
    ('12,5', 12.5), ('12.5', 12.5), (' 7 ', 7.0), ('', None), (None, None), ('0,035', 0.035),
])
def test_peso_do_formulario(entrada, esperado):
    from blueprints.pacientes import _peso_do_formulario
    assert _peso_do_formulario(entrada) == esperado


@pytest.mark.parametrize('entrada', ['doze', '-3', '0', '1,2,3', 'nan', '99999'])
def test_peso_do_formulario_recusa_invalidos(entrada):
    from blueprints.pacientes import _peso_do_formulario
    with pytest.raises(ValueError):
        _peso_do_formulario(entrada)


def test_rotate_photo_zero_devolve_a_mesma_foto():
    from services.photo_intake import normalize_photo_upload, rotate_photo
    foto = normalize_photo_upload(_jpeg().getvalue())
    assert rotate_photo(foto, 0) is foto
    assert rotate_photo(foto, '360') is foto
    girada = rotate_photo(foto, 270)
    assert girada is not foto
    assert Image.open(BytesIO(girada.stream.getvalue())).size == (60, 40)
