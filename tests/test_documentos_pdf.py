"""A identidade da receita deve aparecer nos demais documentos sem perder dados."""
import base64
from datetime import date
from io import BytesIO
import re
from types import SimpleNamespace as Obj
import zlib

from PIL import Image
import pytest
from flask import Flask

from services.consulta_pdf import gerar_pdf_consulta
from services.exames_pdf import gerar_pdf_exames
from services.orcamento_pdf import gerar_pdf_orcamento
from services.vacinas_pdf import gerar_pdf_carteira


def conteudo(pdf):
    partes = []
    for fluxo in re.findall(rb'stream\r?\n(.*?)endstream', pdf, re.S):
        dados = fluxo.strip()
        try:
            if dados.endswith(b'~>'):
                dados = base64.a85decode(dados[:-2])
            partes.append(zlib.decompress(dados))
        except (ValueError, zlib.error):
            pass
    return b'\n'.join(partes)


@pytest.fixture
def documentos():
    tutor = Obj(name='Tutor Silva', cpf='123', phone='555', address='Rua Norte')
    vacina = Obj(nome='Antirrabica', aplicada_em=date(2026, 1, 1), tipo='Campanha', lote='LOTE123', veterinario='Dra Ana', proxima_dose=date(2027, 1, 1))
    animal = Obj(owner=tutor, name='Rex', species='cao', breed='SRD', sex='M', peso=10, microchip_number='CHIP123', date_of_birth=date(2020, 1, 1), vacinas_ordenadas=[vacina])
    clinica = Obj(nome='Clinica Exemplo', endereco='Rua Sul', telefone='555', email=None, cnpj=None)
    exame = Obj(nome='Hemograma', status='pendente', performed_at=None, justificativa='Avaliacao clinica', resultado=None, laudo_filename=None, laudo_url=None)
    bloco = Obj(data_criacao=None, exames=[exame], observacoes_gerais='Jejum')
    consulta = Obj(created_at=None, queixa_principal='Queixa importante', historico_clinico='Historico', exame_fisico='Exame', conduta='Retorno')
    itens = [Obj(descricao='Consulta clinica', valor=100)]
    return [
        (lambda: gerar_pdf_exames(bloco, animal, tutor, clinica, None), b'Hemograma'),
        (lambda: gerar_pdf_consulta(consulta=consulta, animal=animal, tutor=tutor, clinica=clinica, veterinario=None, printing_user=None, printed_at=None), b'Queixa importante'),
        (lambda: gerar_pdf_carteira(animal, clinica, None), b'LOTE123'),
        (lambda: gerar_pdf_orcamento(itens=itens, total=100, clinica=clinica, veterinario=None, printing_user=None, printed_at=None, animal=animal, tutor=tutor), b'Consulta clinica'),
    ]


@pytest.mark.parametrize('tem_logo', [False, True])
def test_identidade_e_dados_dos_documentos(documentos, tem_logo, monkeypatch):
    imagem = BytesIO()
    Image.new('RGB', (100, 50), 'red').save(imagem, 'JPEG')
    logo = (imagem.getvalue(), 100, 50) if tem_logo else None
    monkeypatch.setattr('services.documento_pdf._carregar_logo', lambda _: logo)
    for gerar, dado in documentos:
        pdf = gerar()
        texto = conteudo(pdf)
        assert pdf.startswith(b'%PDF-')
        assert b'Clinica Exemplo' in texto and b'Rex' in texto and b'Tutor Silva' in texto
        assert dado in texto
        assert len(re.findall(rb'/FormXob\.\w+ Do', texto)) == (2 if tem_logo else 0)
        assert b'p\\341g. 1' in texto


def test_fichas_longas_quebram_de_pagina_sem_perder_conteudo():
    tutor = Obj(name='Tutor', cpf=None, phone=None, address=('Endereco longo ' * 700) + 'FIMENDERECO')
    animal = Obj(owner=tutor, name='Rex', species='cao', breed='SRD', sex='M', microchip_number=None, date_of_birth=None, vacinas_ordenadas=[])
    clinica = Obj(nome='Clinica', endereco=None, telefone=None, email=None, cnpj=None)
    texto = conteudo(gerar_pdf_carteira(animal, clinica, None))
    assert b'FIMENDERECO' in texto
    assert b'p\\341g. 2' in texto


def test_carrega_logo_real_da_clinica(tmp_path):
    pasta = tmp_path / 'uploads' / 'clinicas'
    pasta.mkdir(parents=True)
    Image.new('RGBA', (100, 50), (255, 0, 0, 128)).save(pasta / 'logo.png')
    clinica = Obj(nome='Clinica', endereco=None, telefone=None, email=None, cnpj=None, logotipo='logo.png')
    animal = Obj(owner=None, name='Rex', species='cao', breed='SRD', sex='M', microchip_number=None, date_of_birth=None, vacinas_ordenadas=[])
    app = Flask(__name__, static_folder=str(tmp_path))
    with app.app_context():
        texto = conteudo(gerar_pdf_carteira(animal, clinica, None))
    assert len(re.findall(rb'/FormXob\.\w+ Do', texto)) == 2
