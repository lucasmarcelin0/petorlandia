"""PDF de orçamento gerado a partir dos mesmos dados autorizados da impressão."""
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from services.receita_pdf import _texto, _valor_crmv, _membership_ativa
from services.documento_pdf import BASE, TITULO, LARGURA, cabecalho, fichas, montar
from template_filters import format_datetime_brazil


def gerar_pdf_orcamento(*, itens, total, clinica, veterinario, printing_user, printed_at, animal=None, tutor=None, padrao=False):
    normal = BASE
    conteudo = []
    def linha(label, value):
        if value is not None and value != '':
            conteudo.append(Paragraph(f'<b>{_texto(label)}:</b> {_texto(value)}', normal))
            conteudo.append(Spacer(1, 3))
    conteudo.extend(cabecalho(clinica))
    conteudo.append(Paragraph('Orçamento' if padrao else 'Orçamento da Consulta', TITULO))
    assinatura = (printing_user or veterinario) if padrao else (veterinario or printing_user)
    linha('Impresso por', getattr(printing_user, 'name', '—') if printing_user else '—')
    linha('Data/Hora', format_datetime_brazil(printed_at, '%d/%m/%Y %H:%M'))
    grupos = [('Profissional responsável', [('Nome', getattr(veterinario, 'name', '—') if veterinario else '—'), ('CRMV', _valor_crmv(veterinario))])]
    if animal:
        grupos.append(('Paciente', [('Nome', animal.name), ('Espécie', animal.species), ('Raça', animal.breed),
                                   ('Sexo', animal.sex), ('Peso (kg)', animal.peso), ('Microchip', animal.microchip_number)]))
    if tutor:
        grupos.append(('Responsável', [('Nome', tutor.name), ('CPF', tutor.cpf), ('Contato', tutor.phone), ('Endereço', tutor.address)]))
    conteudo.append(fichas(grupos))
    conteudo.append(Spacer(1, 10))
    dados = [[Paragraph('<b>Descrição</b>', normal), Paragraph('<b>Valor (R$)</b>', normal)]]
    for item in itens:
        dados.append([Paragraph(_texto(item.descricao), normal), Paragraph(f'{float(item.valor):.2f}', normal)])
    dados.append([Paragraph('<b>Total</b>', normal), Paragraph(f'<b>{float(total):.2f}</b>', normal)])
    tabela = Table(dados, colWidths=[LARGURA * .8, LARGURA * .2], repeatRows=1)
    tabela.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .5, colors.HexColor('#d9e2ec')),
                                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef3f9'))]))
    conteudo.append(tabela)
    conteudo.append(Spacer(1, 12))
    nota = ('Valores válidos exclusivamente para os itens listados acima. Consulte a clínica para condições de pagamento e opções adicionais.'
            if padrao else 'Este orçamento tem validade de 30 dias a partir da data de emissão e poderá sofrer ajustes conforme a evolução clínica do paciente.')
    conteudo.append(Paragraph(_texto(nota), normal))
    conteudo.append(Spacer(1, 1.5 * cm))
    conteudo.append(Paragraph('________________________________', normal))
    linha('Assinatura', getattr(assinatura, 'name', '—') if assinatura else '—')
    if _membership_ativa(assinatura):
        linha('CRMV da assinatura', _valor_crmv(assinatura))
    output = BytesIO()
    montar(output, conteudo, clinica, 'Orçamento' if padrao else 'Orçamento da Consulta')
    return output.getvalue()
