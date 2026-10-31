"""PDF de orçamento gerado a partir dos mesmos dados autorizados da impressão."""
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from services.receita_pdf import _texto, _valor_crmv, _membership_ativa, _carregar_logo
from template_filters import format_datetime_brazil
from document_utils import format_cnpj


def gerar_pdf_orcamento(*, itens, total, clinica, veterinario, printing_user, printed_at, animal=None, tutor=None, padrao=False):
    estilos = getSampleStyleSheet()
    normal = estilos['BodyText']
    title = estilos['Title']
    conteudo = []
    def linha(label, value):
        if value is not None and value != '':
            conteudo.append(Paragraph(f'<b>{_texto(label)}:</b> {_texto(value)}', normal))
            conteudo.append(Spacer(1, 3))
    if clinica:
        logo = _carregar_logo(clinica)
        if logo:
            dados, largura, altura = logo
            dimensao = 1.9 * cm / max(largura, altura)
            conteudo.append(Image(BytesIO(dados), width=largura * dimensao, height=altura * dimensao))
        conteudo.append(Paragraph(_texto(clinica.nome), title))
        for label, value in [('Endereço', clinica.endereco), ('Telefone', clinica.telefone),
                             ('E-mail', clinica.email), ('CNPJ', format_cnpj(clinica.cnpj) if clinica.cnpj else None)]:
            linha(label, value)
    conteudo.append(Spacer(1, 8))
    conteudo.append(Paragraph('Orçamento' if padrao else 'Orçamento da Consulta', estilos['Heading1']))
    assinatura = (printing_user or veterinario) if padrao else (veterinario or printing_user)
    linha('Impresso por', getattr(printing_user, 'name', '—') if printing_user else '—')
    linha('Data/Hora', format_datetime_brazil(printed_at, '%d/%m/%Y %H:%M'))
    linha('Profissional responsável', getattr(veterinario, 'name', '—') if veterinario else '—')
    linha('CRMV', _valor_crmv(veterinario))
    if animal:
        for label, value in [('Paciente', animal.name), ('Espécie', animal.species), ('Raça', animal.breed),
                             ('Sexo', animal.sex), ('Peso (kg)', animal.peso), ('Microchip', animal.microchip_number)]:
            linha(label, value)
    if tutor:
        for label, value in [('Responsável', tutor.name), ('CPF', tutor.cpf),
                             ('Contato', tutor.phone), ('Endereço', tutor.address)]:
            linha(label, value)
    conteudo.append(Spacer(1, 10))
    dados = [[Paragraph('<b>Descrição</b>', normal), Paragraph('<b>Valor (R$)</b>', normal)]]
    for item in itens:
        dados.append([Paragraph(_texto(item.descricao), normal), Paragraph(f'{float(item.valor):.2f}', normal)])
    dados.append([Paragraph('<b>Total</b>', normal), Paragraph(f'<b>{float(total):.2f}</b>', normal)])
    tabela = Table(dados, colWidths=[12.4 * cm, 3.2 * cm], repeatRows=1)
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
    SimpleDocTemplate(output, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm).build(conteudo)
    return output.getvalue()
