"""Relatório clínico em PDF: manter alinhado ao relatório HTML."""
from io import BytesIO

from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, Spacer

from services.receita_pdf import _assinatura, _membership_ativa, _texto, _valor_crmv
from services.documento_pdf import BASE, TITULO, SECAO, CENTRO, cabecalho, fichas, montar
from template_filters import format_datetime_brazil


def gerar_pdf_consulta(*, consulta, animal, tutor, clinica, veterinario, printing_user, printed_at):
    base, title, heading, centered = BASE, TITULO, SECAO, CENTRO
    story = []

    def line(label, value):
        story.append(Paragraph(f'<b>{_texto(label)}:</b> {_texto(value if value not in (None, "") else "—")}', base))
        story.append(Spacer(1, 3))

    story.extend(cabecalho(clinica))
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
    story.append(fichas([
        ('Profissional Responsável', [('Nome', getattr(veterinario, 'name', None) or '—'), ('CRMV', _valor_crmv(veterinario))]),
        ('Paciente', [(label, value if value not in (None, '') else '—') for label, attr in [('Espécie', 'species'), ('Raça', 'breed'), ('Sexo', 'sex'), ('Peso (kg)', 'peso')] for value in [getattr(animal, attr, None)]] + [('Microchip', getattr(animal, 'microchip_number', None))]),
        ('Responsável', [(label, getattr(tutor, attr, None) or '—') for label, attr in [('Nome', 'name'), ('CPF', 'cpf'), ('Contato', 'phone'), ('Endereço', 'address')]]),
    ]))
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
    montar(out, story, clinica, 'Relatório de Atendimento Clínico')
    return out.getvalue()
