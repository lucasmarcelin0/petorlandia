from datetime import date
from types import SimpleNamespace
import base64
import re
import zlib
from unittest.mock import patch
from services.vacinas_pdf import gerar_pdf_carteira


def test_carteira_pdf_preserva_as_informacoes():
    tutor = SimpleNamespace(name='Tutor', cpf='123', phone='555', address='Rua Norte')
    vacina = SimpleNamespace(nome='Antirrabica', aplicada_em=date(2026, 1, 1),
                             tipo='Campanha', lote='LOTE123', veterinario='Dra Ana',
                             proxima_dose=date(2027, 1, 1))
    animal = SimpleNamespace(owner=tutor, name='Rex', species='cao', breed='SRD', sex='M',
                             microchip_number='1234', date_of_birth=date(2020, 1, 1),
                             vacinas_ordenadas=[vacina])
    clinica = SimpleNamespace(nome='Clinica', endereco='Rua', telefone='555', email=None, cnpj=None)
    with patch('services.vacinas_pdf._valor_crmv', return_value='SP-123'):
        pdf = gerar_pdf_carteira(animal, clinica, SimpleNamespace(name='Dra Ana'))
    assert pdf.startswith(b'%PDF-')
    texto = ''
    for bruto in re.findall(rb'stream\r?\n(.*?)endstream', pdf, re.S):
        dados = bruto.strip()
        try:
            if dados.endswith(b'~>'):
                dados = base64.a85decode(dados[:-2])
            texto += zlib.decompress(dados).decode('latin-1', 'ignore')
        except (ValueError, zlib.error):
            continue
    for item in ('Rex', 'Tutor', 'Antirrabica', 'Campanha', 'LOTE123', 'Dra Ana', '01/01/2027', 'SP-123'):
        assert item in texto


def test_rota_pdf_usa_data_do_modelo_e_preserva_acesso(app, client):
    from extensions import db
    from models import Animal, Clinica, User, Vacina

    tutor = User(name='Tutor', email='tutor-pdf@example.com', password_hash='x')
    terceiro = User(name='Outro', email='outro-pdf@example.com', password_hash='x')
    clinica = Clinica(nome='Clinica')
    com_data = Animal(name='Rex', owner=tutor, clinica=clinica, date_of_birth=date(2020, 1, 2))
    sem_data = Animal(name='Mel', owner=tutor, clinica=clinica)
    vacina = Vacina(animal=com_data, nome='Antirrabica', aplicada=True, aplicada_em=date(2026, 1, 1))
    db.session.add_all([tutor, terceiro, clinica, com_data, sem_data, vacina])
    db.session.commit()

    with client.session_transaction() as session:
        session['_user_id'] = str(tutor.id)
        session['_fresh'] = True
    for animal in (com_data, sem_data):
        for modo, disposition in (('inline', 'inline'), ('download', 'attachment')):
            resp = client.get(f'/animal/{animal.id}/vacinas/imprimir?pdf={modo}')
            assert resp.status_code == 200
            assert resp.mimetype == 'application/pdf'
            assert resp.headers['Content-Disposition'].startswith(disposition)
            assert resp.data.startswith(b'%PDF-')
            if animal is com_data:
                texto = ''
                for bruto in re.findall(rb'stream\r?\n(.*?)endstream', resp.data, re.S):
                    dados = bruto.strip()
                    try:
                        if dados.endswith(b'~>'):
                            dados = base64.a85decode(dados[:-2])
                        texto += zlib.decompress(dados).decode('latin-1', 'ignore')
                    except (ValueError, zlib.error):
                        continue
                assert '02/01/2020' in texto
                assert 'Antirrabica' in texto

    with client.session_transaction() as session:
        session['_user_id'] = str(terceiro.id)
        session['_fresh'] = True
    # A fixture mantém o app context aberto entre requisições; descarte o
    # usuário que o Flask-Login guardou nesse contexto ao trocar de sessão.
    from flask import g
    g.pop('_login_user', None)
    assert client.get(f'/animal/{com_data.id}/vacinas/imprimir?pdf=inline').status_code in (403, 404)
