"""Requisição de exames em PDF para impressão e download."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

from services.receita_pdf import _texto, _valor_crmv
from template_filters import format_datetime_brazil


def gerar_pdf_exames(bloco, animal, tutor, clinica, veterinario):
    styles = getSampleStyleSheet()
    body = ParagraphStyle('exame-corpo', parent=styles['Normal'], fontSize=9.5, leading=14, spaceAfter=4)
    title = ParagraphStyle('exame-titulo', parent=styles['Heading1'], fontSize=15, leading=19, textColor=colors.HexColor('#1f3a56'))
    heading = ParagraphStyle('exame-secao', parent=styles['Heading2'], fontSize=11, leading=15, textColor=colors.HexColor('#1f3a56'), spaceBefore=12)
    centered = ParagraphStyle('exame-assinatura', parent=body, alignment=TA_CENTER)
    story = []

    def line(label, value):
        if value is not None and str(value).strip():
            story.append(Paragraph(f'<b>{_texto(label)}:</b> {_texto(value)}', body))

    def section(label):
        story.append(Paragraph(_texto(label), heading))
        story.append(HRFlowable(width='100%', thickness=.5, color=colors.HexColor('#d9e2ec'), spaceAfter=5))

    story.append(Paragraph(_texto(clinica.nome), title))
    for label, value in [('Endereço', clinica.endereco), ('Telefone', clinica.telefone), ('Email', clinica.email), ('CNPJ', clinica.cnpj)]:
        line(label, value)
    story.append(Spacer(1, 10))
    story.append(Paragraph('Requisição de Exames Complementares', title))
    if bloco.data_criacao:
        line('Solicitado em', format_datetime_brazil(bloco.data_criacao, '%d/%m/%Y %H:%M'))
    section('Profissional Responsável')
    line('Nome', getattr(veterinario, 'name', None))
    line('CRMV', _valor_crmv(veterinario))
    section('Paciente')
    for label, attr in [('Nome', 'name'), ('Espécie', 'species'), ('Raça', 'breed'), ('Sexo', 'sex'), ('Microchip', 'microchip_number')]:
        line(label, getattr(animal, attr, None))
    if tutor:
        section('Responsável')
        for label, attr in [('Nome', 'name'), ('CPF', 'cpf'), ('Contato', 'phone'), ('Endereço', 'address')]:
            line(label, getattr(tutor, attr, None))
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
    SimpleDocTemplate(output, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.8 * cm,
                      title='Requisição de Exames Complementares').build(story)
    return output.getvalue()
