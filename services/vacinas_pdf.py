"""Carteira de vacinação em PDF."""
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, Spacer
from services.receita_pdf import _texto, _valor_crmv
from services.documento_pdf import BASE, TITULO, SECAO, cabecalho, fichas, montar


def gerar_pdf_carteira(animal, clinica, veterinario):
    corpo, titulo, secao = BASE, TITULO, SECAO
    story = []

    def linha(rotulo, valor):
        if valor is not None and str(valor).strip():
            story.append(Paragraph(f'<b>{_texto(rotulo)}:</b> {_texto(valor)}', corpo))

    def data(valor):
        return valor.strftime('%d/%m/%Y') if valor else '—'

    story.extend(cabecalho(clinica))
    story.append(Paragraph('Carteira de Vacinação', titulo))
    story.append(Paragraph('Histórico de imunizações', corpo))
    tutor = animal.owner
    story.append(fichas([
        ('Clínica e profissional', [('Clínica', clinica.nome), ('Veterinário', getattr(veterinario, 'name', None)), ('CRMV', _valor_crmv(veterinario))]),
        ('Paciente', [(label, getattr(animal, attr, None)) for label, attr in [('Nome', 'name'), ('Espécie', 'species'), ('Raça', 'breed'), ('Sexo', 'sex'), ('Microchip', 'microchip_number')]] + [('Nascimento', data(animal.date_of_birth) if animal.date_of_birth else None)]),
        ('Responsável', [(label, getattr(tutor, attr, None)) for label, attr in [('Nome', 'name'), ('CPF', 'cpf'), ('Contato', 'phone'), ('Endereço', 'address')]]),
    ]))
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
    montar(output, story, clinica, 'Carteira de Vacinação')
    return output.getvalue()
