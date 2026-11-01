"""Requisição de exames em PDF para impressão e download."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, Spacer

from services.receita_pdf import _texto, _valor_crmv
from services.documento_pdf import BASE, TITULO, SECAO, CENTRO, cabecalho, fichas, montar
from template_filters import format_datetime_brazil


def gerar_pdf_exames(bloco, animal, tutor, clinica, veterinario):
    body, title, heading, centered = BASE, TITULO, SECAO, CENTRO
    story = []

    def line(label, value):
        if value is not None and str(value).strip():
            story.append(Paragraph(f'<b>{_texto(label)}:</b> {_texto(value)}', body))

    def section(label):
        story.append(Paragraph(_texto(label), heading))
        story.append(HRFlowable(width='100%', thickness=.5, color=colors.HexColor('#d9e2ec'), spaceAfter=5))

    story.extend(cabecalho(clinica))
    story.append(Paragraph('Requisição de Exames Complementares', title))
    if bloco.data_criacao:
        line('Solicitado em', format_datetime_brazil(bloco.data_criacao, '%d/%m/%Y %H:%M'))
    story.append(fichas([
        ('Profissional Responsável', [('Nome', getattr(veterinario, 'name', None)), ('CRMV', _valor_crmv(veterinario))]),
        ('Paciente', [(label, getattr(animal, attr, None)) for label, attr in [('Nome', 'name'), ('Espécie', 'species'), ('Raça', 'breed'), ('Sexo', 'sex'), ('Microchip', 'microchip_number')]]),
        ('Responsável', [(label, getattr(tutor, attr, None)) for label, attr in [('Nome', 'name'), ('CPF', 'cpf'), ('Contato', 'phone'), ('Endereço', 'address')]]),
    ]))
    section('Exames Solicitados')
    for exame in bloco.exames:
        story.append(Paragraph(f'<b>{_texto(exame.nome)}</b>', body))
        line('Status', (exame.status or 'pendente').replace('_', ' ').capitalize())
        if exame.performed_at:
            line('Realizado em', format_datetime_brazil(exame.performed_at, '%d/%m/%Y'))
        line('Justificativa', exame.justificativa)
        line('Resultado', exame.resultado)
        line('Laudo', exame.laudo_filename or ('Abrir laudo' if exame.laudo_url else None))
        story.append(Spacer(1, 5))
    if bloco.observacoes_gerais:
        section('Observações')
        story.append(Paragraph(_texto(bloco.observacoes_gerais), body))
    story.extend([Spacer(1, 1.6 * cm), HRFlowable(width='45%', hAlign='CENTER'),
                  Paragraph(_texto(getattr(veterinario, 'name', None) or ' '), centered),
                  Paragraph(_texto(_valor_crmv(veterinario)), centered)])
    output = BytesIO()
    montar(output, story, clinica, 'Requisição de Exames Complementares')
    return output.getvalue()
