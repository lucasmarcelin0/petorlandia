"""Relatório clínico em PDF: manter alinhado ao relatório HTML."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from document_utils import format_cnpj
from services.receita_pdf import _assinatura, _carregar_logo, _membership_ativa, _texto, _valor_crmv
from template_filters import format_datetime_brazil


def gerar_pdf_consulta(*, consulta, animal, tutor, clinica, veterinario, printing_user, printed_at):
    base = ParagraphStyle('consulta-base', fontName='Helvetica', fontSize=9.5, leading=13)
    title = ParagraphStyle('consulta-titulo', parent=base, fontName='Helvetica-Bold', fontSize=15, leading=19, textColor=colors.HexColor('#1f3a56'), spaceAfter=7)
    heading = ParagraphStyle('consulta-secao', parent=base, fontName='Helvetica-Bold', fontSize=11, leading=15, textColor=colors.HexColor('#1f3a56'), spaceBefore=10, spaceAfter=4)
    centered = ParagraphStyle('consulta-assinatura', parent=base, alignment=TA_CENTER)
    story = []

    def line(label, value):
        story.append(Paragraph(f'<b>{_texto(label)}:</b> {_texto(value if value not in (None, "") else "—")}', base))
        story.append(Spacer(1, 3))

    if clinica:
        logo = _carregar_logo(clinica)
        nome = Paragraph(_texto(clinica.nome), title)
        if logo:
            dados, width, height = logo
            scale = min(1.7 * cm / max(width, 1), 1.7 * cm / max(height, 1))
            table = Table([[Image(BytesIO(dados), width=width * scale, height=height * scale), nome]], colWidths=[2.2 * cm, 13.5 * cm])
            table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
            story.append(table)
        else:
            story.append(nome)
        for label, value in [('Endereço', clinica.endereco), ('Telefone', clinica.telefone),
                             ('E-mail', clinica.email), ('CNPJ', format_cnpj(clinica.cnpj) if clinica.cnpj else None)]:
            if value:
                line(label, value)
        story.append(HRFlowable(width='100%', thickness=.6, color=colors.HexColor('#d9e2ec'), spaceAfter=7))
    story.append(Paragraph('Relatório de Atendimento Clínico', title))
    if consulta.created_at:
        line('Consulta realizada em', format_datetime_brazil(consulta.created_at, '%d/%m/%Y %H:%M'))
    line('Paciente', animal.name)
    line('Responsável', getattr(tutor, 'name', None))
    signature_user = printing_user or veterinario
    line('Impresso por', getattr(signature_user, 'name', None))
    if _membership_ativa(signature_user):
        line('CRMV de quem imprimiu', _valor_crmv(signature_user, vazio='sem CRMV'))
    if printed_at:
        line('Data/Hora', format_datetime_brazil(printed_at, '%d/%m/%Y %H:%M'))
    story.append(Paragraph('Profissional Responsável', heading))
    line('Nome', getattr(veterinario, 'name', None))
    line('CRMV', _valor_crmv(veterinario))
    story.append(Paragraph('Paciente', heading))
    for label, attr in [('Espécie', 'species'), ('Raça', 'breed'), ('Sexo', 'sex'), ('Peso (kg)', 'peso'), ('Microchip', 'microchip_number')]:
        value = getattr(animal, attr, None)
        if attr != 'microchip_number' or value:
            line(label, value)
    story.append(Paragraph('Responsável', heading))
    for label, attr in [('Nome', 'name'), ('CPF', 'cpf'), ('Contato', 'phone'), ('Endereço', 'address')]:
        line(label, getattr(tutor, attr, None))
    for label, attr in [('Motivo da Consulta', 'queixa_principal'), ('Histórico Clínico', 'historico_clinico'), ('Exame Físico', 'exame_fisico'), ('Conduta Médica', 'conduta')]:
        story.append(Paragraph(label, heading))
        story.append(Paragraph(_texto(getattr(consulta, attr, None) or '—'), base))
    story.extend([Spacer(1, 1.6 * cm), HRFlowable(width='45%', hAlign='CENTER', spaceAfter=4),
                  Paragraph(_texto(getattr(signature_user, 'name', None) or '—'), centered)])
    if _membership_ativa(signature_user):
        assinatura = _assinatura(signature_user)
        story.append(Paragraph(_texto(assinatura.crmv_formatado if assinatura and assinatura.crmv_formatado else '—'), centered))
        if assinatura and not assinatura.pode_assinar and assinatura.responsavel_tecnico:
            story.append(Paragraph(_texto(f'Documento sob responsabilidade técnica de {assinatura.responsavel_tecnico}'), centered))
    else:
        story.append(Paragraph('—', centered))
    if veterinario and printing_user and veterinario.id != printing_user.id:
        story.append(Spacer(1, 8))
        line('Profissional responsável registrado', f'{veterinario.name} · {_valor_crmv(veterinario)}')
    out = BytesIO()
    SimpleDocTemplate(out, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.8 * cm,
                      title='Relatório de Atendimento Clínico').build(story)
    return out.getvalue()
