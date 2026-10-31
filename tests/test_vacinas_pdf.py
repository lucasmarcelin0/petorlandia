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
                             microchip_number='1234', birth_date=date(2020, 1, 1),
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
