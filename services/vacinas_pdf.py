"""Carteira de vacinação em PDF."""
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer
from services.receita_pdf import _texto, _valor_crmv


def gerar_pdf_carteira(animal, clinica, veterinario):
    styles = getSampleStyleSheet()
    corpo = ParagraphStyle('carteira-corpo', parent=styles['Normal'], fontSize=10, leading=14, spaceAfter=4)
    titulo = ParagraphStyle('carteira-titulo', parent=styles['Heading1'], fontSize=15, leading=19, textColor=colors.HexColor('#1f3a56'))
    secao = ParagraphStyle('carteira-secao', parent=styles['Heading2'], fontSize=11, leading=15, spaceBefore=10)
    story = []

    def linha(rotulo, valor):
        if valor is not None and str(valor).strip():
            story.append(Paragraph(f'<b>{_texto(rotulo)}:</b> {_texto(valor)}', corpo))

    def data(valor):
        return valor.strftime('%d/%m/%Y') if valor else '—'

    story.append(Paragraph(_texto(clinica.nome), titulo))
    for label, attr in [('Endereço', 'endereco'), ('Telefone', 'telefone'), ('E-mail', 'email'), ('CNPJ', 'cnpj')]:
        linha(label, getattr(clinica, attr, None))
    story.append(Spacer(1, 8))
    story.append(Paragraph('Carteira de Vacinação', titulo))
    story.append(Paragraph('Histórico de imunizações', corpo))
    story.append(Paragraph('Paciente', secao))
    for label, attr in [('Nome', 'name'), ('Espécie', 'species'), ('Raça', 'breed'), ('Sexo', 'sex'), ('Microchip', 'microchip_number')]:
        linha(label, getattr(animal, attr, None))
    if animal.birth_date:
        linha('Nascimento', data(animal.birth_date))
    tutor = animal.owner
    story.append(Paragraph('Responsável', secao))
    for label, attr in [('Nome', 'name'), ('CPF', 'cpf'), ('Contato', 'phone'), ('Endereço', 'address')]:
        linha(label, getattr(tutor, attr, None))
    story.append(Paragraph('Clínica e profissional', secao))
    linha('Clínica', clinica.nome)
    linha('Veterinário', getattr(veterinario, 'name', None))
    linha('CRMV', _valor_crmv(veterinario))
    story.append(Paragraph('Vacinas aplicadas', secao))
    for vacina in animal.vacinas_ordenadas:
        story.append(HRFlowable(width='100%', thickness=.5, color=colors.HexColor('#d9e2ec'), spaceAfter=5))
        for label, value in [('Data', data(vacina.aplicada_em)), ('Vacina', vacina.nome), ('Tipo/Doença', vacina.tipo or '—'),
                             ('Lote', vacina.lote or '—'), ('Veterinário', vacina.veterinario or '—'),
                             ('Próxima dose', data(vacina.proxima_dose))]:
            linha(label, value)
    story.extend([Spacer(1, 1.5 * cm), Paragraph('____________________________________', corpo),
                  Paragraph(_texto(getattr(veterinario, 'name', None) or 'Responsável pela Aplicação'), corpo),
                  Paragraph(_texto(_valor_crmv(veterinario)), corpo),
                  Spacer(1, 1 * cm), Paragraph('____________________________________', corpo),
                  Paragraph('Responsável pelo Animal', corpo),
                  Spacer(1, .5 * cm), Paragraph('Documento válido apenas com carimbo e assinatura do médico veterinário responsável.', corpo)])
    output = BytesIO()
    SimpleDocTemplate(output, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.8 * cm,
                      title='Carteira de Vacinação').build(story)
    return output.getvalue()
