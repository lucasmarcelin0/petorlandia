"""Papéis adicionais (role/worker múltiplos) e simulados de concurso da estagiária."""
import io
import zlib

from flask import g

from extensions import db
from helpers import is_intern_account, user_has_role, user_has_worker
from models import ClinicStaff, Clinica, User
from models.concursos import ConcursoProva, ConcursoTentativa
from services import concursos as servico

PDF_FALSO = b"%PDF-1.4\n%fake\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def conta(email, role='adotante', worker=None, **extra):
    user = User(name=email.split('@')[0].title(), email=email, password_hash='x', role=role, worker=worker, **extra)
    db.session.add(user)
    db.session.commit()
    return user


def entrar(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    for chave in ('_login_user', 'user_experience', '_site_flag_cache'):
        g.pop(chave, None)


# --- Papéis adicionais --------------------------------------------------------

def test_papeis_adicionais_somam_ao_principal(app):
    with app.app_context():
        user = conta('yasmin@example.test', role='vacinador', worker='estudante',
                     roles_extras='estagiario, parceiro', workers_extras='colaborador')
        assert user.all_roles == {'vacinador', 'estagiario', 'parceiro'}
        assert user.has_role('estagiario') and user.has_worker('colaborador', 'delivery')
        assert not user.has_role('admin')
        assert user_has_role(user, 'parceiro') and user_has_worker(user, 'estudante')
        assert not user_has_role(None, 'parceiro')


def test_role_extra_estagiario_marca_a_conta_como_estagiaria(app):
    with app.app_context():
        user = conta('v@example.test', role='vacinador', roles_extras='estagiario')
        assert is_intern_account(user)


def test_area_do_vacinador_e_de_estudo_aparecem_pelos_extras(app):
    from services.workspaces import resolve_experience

    with app.test_request_context():
        user = conta('dupla@example.test', role='tutor', roles_extras='vacinador',
                     workers_extras='estudante')
        experiencia = resolve_experience(user)
        assert {'vaccinator', 'student'} <= set(experiencia.capabilities)


def test_vacina_pmo_aceita_vacinador_como_papel_adicional(client, app):
    with app.app_context():
        com_extra = conta('extra@example.test', role='tutor', roles_extras='vacinador')
        sem = conta('sem@example.test', role='tutor')
        entrar(client, sem)
        negado = client.get('/vacina-pmo')
        entrar(client, com_extra)
        liberado = client.get('/vacina-pmo')
        assert negado.status_code in (403, 404)
        assert liberado.status_code not in (403, 404), liberado.status_code


def test_painel_admin_grava_papeis_adicionais_sem_repetir_o_principal(app):
    from werkzeug.datastructures import MultiDict

    from admin import UserAdminView

    class Campo:
        def __init__(self, name, data):
            self.name, self.data = name, data

    class Form:
        roles_extras_escolha = Campo('roles_extras_escolha', ['vacinador', 'estagiario', 'estagiario'])
        workers_extras_escolha = Campo('workers_extras_escolha', [])

    with app.test_request_context(method='POST', data=MultiDict([
        ('roles_extras_escolha', 'vacinador'), ('roles_extras_escolha', 'estagiario'),
        ('workers_extras_escolha__enviado', '1'),
    ])):
        user = conta('form@example.test', role='vacinador', workers_extras='delivery')
        UserAdminView._gravar_papeis_extras(Form(), user)
        assert user.roles_extras == 'estagiario'
        assert user.workers_extras is None  # tudo desmarcado retira


def test_painel_admin_nao_mexe_nos_extras_quando_o_campo_nao_veio(app):
    from admin import UserAdminView

    class Campo:
        def __init__(self, name):
            self.name, self.data = name, []

    class Form:
        roles_extras_escolha = Campo('roles_extras_escolha')
        workers_extras_escolha = Campo('workers_extras_escolha')

    with app.test_request_context(method='POST', data={'name': 'x'}):
        user = conta('outra@example.test', roles_extras='vacinador')
        UserAdminView._gravar_papeis_extras(Form(), user)
        assert user.roles_extras == 'vacinador'


def test_admin_nao_pode_ser_papel_adicional():
    from admin import EXTRA_ROLE_CHOICES, EXTRA_WORKER_CHOICES

    assert 'admin' not in {v for v, _ in EXTRA_ROLE_CHOICES}
    assert not {'master', 'unidade_saude', 'master_notificacao', ''} & {v for v, _ in EXTRA_WORKER_CHOICES}


# --- Gabarito -----------------------------------------------------------------

def test_ler_gabarito_formatos():
    assert servico.ler_gabarito('1 - C\n2 - D\n3  -  B') == 'CDB'
    assert servico.ler_gabarito('1-A 3-ANULADA', total=4) == 'A-X-'
    assert servico.ler_gabarito('cdb*e') == 'CDBXE'
    texto_vunesp = 'Pág. 1 de 1 PMJD2501 CONCURSO PÚBLICO 30.08.2026 051. PROVA OBJETIVA\n1  -  C\n2  -  D\n50  -  E'
    gabarito = servico.ler_gabarito(texto_vunesp)
    assert len(gabarito) == 50 and gabarito[:2] == 'CD' and gabarito[-1] == 'E'
    assert gabarito.count('-') == 47


def test_texto_do_pdf_le_operadores_de_texto():
    stream = zlib.compress(b'BT /F1 12 Tf (1  -  C)Tj ET BT [(2)-250( - D)]TJ ET')
    pdf = b'%PDF-1.4\n1 0 obj<</Length 9>>stream\n' + stream + b'\nendstream\nendobj\n%%EOF'
    assert servico.ler_gabarito(servico.texto_do_pdf(pdf)) == 'CD'


# --- Simulado -----------------------------------------------------------------

def _prova_publicada(client, admin):
    entrar(client, admin)
    resp = client.post('/estudos/concursos/nova', data={
        'titulo': 'Jardinópolis 2026', 'banca': 'VUNESP', 'ano': '2026',
        'pdf_prova': (io.BytesIO(PDF_FALSO), 'prova.pdf'),
        'gabarito_texto': '1-C 2-D 3-B 4-X',
    }, content_type='multipart/form-data')
    assert resp.status_code == 302
    prova = ConcursoProva.query.one()
    assert prova.gabarito == 'CDBX' and not prova.ativo
    resp = client.post(f'/estudos/concursos/prova/{prova.id}/gabarito', data={
        'titulo': prova.titulo, 'total_questoes': '5',
        'q1': 'C', 'q2': 'D', 'q3': 'B', 'q4': 'X', 'q5': 'A', 'ativo': '1'})
    assert resp.status_code == 302
    db.session.refresh(prova)
    assert prova.ativo and prova.gabarito == 'CDBXA'
    return prova


def test_fluxo_da_estagiaria_marca_entrega_e_gestor_acompanha(client, app):
    with app.app_context():
        admin = conta('admin@example.test', role='admin')
        estagiaria = conta('yasmin@example.test', role='vacinador', worker='estudante')
        prova = _prova_publicada(client, admin)

        entrar(client, estagiaria)
        assert 'Jardinópolis 2026' in client.get('/estudos/concursos/').get_data(as_text=True)
        pagina = client.get(f'/estudos/concursos/prova/{prova.id}')
        assert pagina.status_code == 200
        tentativa = ConcursoTentativa.query.filter_by(user_id=estagiaria.id).one()
        url = f'/estudos/concursos/tentativa/{tentativa.id}/marcar'
        for numero, letra in ((1, 'C'), (2, 'A'), (3, 'B'), (5, 'E')):
            assert client.post(url, json={'questao': numero, 'letra': letra}).get_json()['ok']
        assert client.post(url, json={'questao': 5, 'letra': ''}).get_json()['respondidas'] == 3
        assert client.post(url, json={'questao': 9, 'letra': 'A'}).status_code == 400

        pdf = client.get(f'/estudos/concursos/prova/{prova.id}/pdf')
        assert pdf.data.startswith(b'%PDF') and "frame-ancestors 'self'" in pdf.headers['Content-Security-Policy']

        resp = client.post(f'/estudos/concursos/tentativa/{tentativa.id}/entregar')
        assert resp.status_code == 302
        db.session.refresh(tentativa)
        assert tentativa.acertos == 3  # 1 C, 3 B e a anulada 4
        assert client.post(url, json={'questao': 1, 'letra': 'A'}).status_code == 409
        resultado = client.get(f'/estudos/concursos/tentativa/{tentativa.id}').get_data(as_text=True)
        assert '60%' in resultado

        # Refazer abre uma tentativa nova; a entregue fica no histórico.
        client.get(f'/estudos/concursos/prova/{prova.id}')
        assert ConcursoTentativa.query.filter_by(user_id=estagiaria.id).count() == 2

        entrar(client, admin)
        painel = client.get('/estudos/concursos/acompanhamento').get_data(as_text=True)
        assert estagiaria.name in painel and '60%' in painel


def test_quem_nao_e_estagiaria_nao_entra_e_nao_ve_resultado_alheio(client, app):
    with app.app_context():
        admin = conta('admin@example.test', role='admin')
        estagiaria = conta('e1@example.test', worker='estudante')
        tutor = conta('tutor@example.test')
        outra = conta('e2@example.test', roles_extras='estagiario')
        prova = _prova_publicada(client, admin)

        entrar(client, tutor)
        assert client.get('/estudos/concursos/').status_code in (403, 404)
        assert client.get(f'/estudos/concursos/prova/{prova.id}/pdf').status_code in (403, 404)

        entrar(client, estagiaria)
        assert client.get('/estudos/concursos/nova').status_code in (403, 404)
        client.get(f'/estudos/concursos/prova/{prova.id}')
        tentativa = ConcursoTentativa.query.filter_by(user_id=estagiaria.id).one()
        client.post(f'/estudos/concursos/tentativa/{tentativa.id}/entregar')

        entrar(client, outra)
        assert client.get(f'/estudos/concursos/tentativa/{tentativa.id}').status_code == 404
        assert client.post(f'/estudos/concursos/tentativa/{tentativa.id}/marcar',
                           json={'questao': 1, 'letra': 'A'}).status_code == 404


def test_dono_de_clinica_acompanha_so_a_propria_equipe(client, app):
    with app.app_context():
        admin = conta('admin@example.test', role='admin')
        dono = conta('dono@example.test')
        clinica = Clinica(nome='Clínica', owner_id=dono.id)
        db.session.add(clinica)
        db.session.commit()
        da_equipe = conta('equipe@example.test', worker='estudante')
        de_fora = conta('fora@example.test', worker='estudante')
        db.session.add(ClinicStaff(clinic_id=clinica.id, user_id=da_equipe.id, is_intern=True))
        db.session.commit()
        prova = _prova_publicada(client, admin)
        for pessoa in (da_equipe, de_fora):
            entrar(client, pessoa)
            client.get(f'/estudos/concursos/prova/{prova.id}')

        entrar(client, dono)
        painel = client.get('/estudos/concursos/acompanhamento').get_data(as_text=True)
        assert da_equipe.name in painel and de_fora.name not in painel


def test_prova_oculta_nao_aparece_e_corujinha_so_para_quem_entra(client, app):
    with app.app_context():
        admin = conta('admin@example.test', role='admin')
        estagiaria = conta('e1@example.test', worker='estudante')
        tutor = conta('tutor@example.test')
        entrar(client, admin)
        client.post('/estudos/concursos/nova', data={
            'titulo': 'Rascunho', 'pdf_prova': (io.BytesIO(PDF_FALSO), 'p.pdf'), 'gabarito_texto': '1-A 2-'},
            content_type='multipart/form-data')
        prova = ConcursoProva.query.one()

        entrar(client, estagiaria)
        assert 'Rascunho' not in client.get('/estudos/concursos/').get_data(as_text=True)
        assert client.get(f'/estudos/concursos/prova/{prova.id}').status_code == 404
        assert 'cz-coruja' in client.get('/estudantes').get_data(as_text=True)

        entrar(client, tutor)
        assert 'cz-coruja' not in client.get('/estudantes').get_data(as_text=True)


def test_publicar_exige_gabarito_completo(client, app):
    with app.app_context():
        admin = conta('admin@example.test', role='admin')
        entrar(client, admin)
        client.post('/estudos/concursos/nova', data={
            'titulo': 'Incompleta', 'pdf_prova': (io.BytesIO(PDF_FALSO), 'p.pdf'), 'gabarito_texto': '1-A 3-C'},
            content_type='multipart/form-data')
        prova = ConcursoProva.query.one()
        assert prova.gabarito == 'A-C'
        client.post(f'/estudos/concursos/prova/{prova.id}/gabarito', data={
            'total_questoes': '3', 'q1': 'A', 'q2': '-', 'q3': 'C', 'ativo': '1'})
        db.session.refresh(prova)
        assert not prova.ativo

        assert client.post('/estudos/concursos/nova', data={
            'titulo': 'Sem PDF', 'pdf_prova': (io.BytesIO(b'nao e pdf'), 'p.pdf')},
            content_type='multipart/form-data').status_code == 302
        assert ConcursoProva.query.count() == 1
