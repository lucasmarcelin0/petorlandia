"""Elementos visuais compartilhados com o PDF da prescrição."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from document_utils import format_cnpj
from services.receita_pdf import _carregar_logo, _compativel, _texto

LARGURA = A4[0] - 3.2 * cm - 12
BORDA = colors.HexColor('#d9e2ec')
PRIMARIA = colors.HexColor('#1f3a56')
SUAVE = colors.HexColor('#687385')
BASE = ParagraphStyle('documento-base', fontName='Helvetica', fontSize=9.5, leading=13, textColor=colors.HexColor('#2b2d33'))
TITULO = ParagraphStyle('documento-titulo', parent=BASE, fontName='Helvetica-Bold', fontSize=15, leading=19, textColor=PRIMARIA, spaceAfter=7)
SECAO = ParagraphStyle('documento-secao', parent=BASE, fontName='Helvetica-Bold', fontSize=10.5, leading=14, textColor=PRIMARIA, spaceBefore=12, spaceAfter=6)
CENTRO = ParagraphStyle('documento-centro', parent=BASE, alignment=TA_CENTER)


def fichas(grupos):
    """Fichas de identificação no mesmo formato da prescrição."""
    cabecalho_ficha = ParagraphStyle('ficha-titulo', parent=BASE, fontName='Helvetica-Bold', fontSize=8.5, leading=11, textColor=PRIMARIA)
    rotulo_ficha = ParagraphStyle('ficha-rotulo', parent=BASE, fontSize=7.5, leading=9.5, textColor=SUAVE)
    valor_ficha = ParagraphStyle('ficha-valor', parent=BASE, fontSize=9, leading=11.5)
    colunas = []
    for titulo, linhas in grupos:
        conteudo = [Paragraph(_texto(titulo).upper(), cabecalho_ficha), Spacer(1, 3)]
        for rotulo, valor in linhas:
            if valor is None or not str(valor).strip():
                continue
            conteudo.extend([Paragraph(_texto(rotulo), rotulo_ficha), Paragraph(_texto(valor), valor_ficha), Spacer(1, 2)])
        colunas.append(conteudo)
    tabela = Table([colunas], colWidths=[LARGURA / len(colunas)] * len(colunas), splitInRow=1)
    estilos = [('VALIGN', (0, 0), (-1, -1), 'TOP'),
               ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
               ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]
    estilos.extend(('BOX', (i, 0), (i, 0), .75, BORDA) for i in range(len(colunas)))
    tabela.setStyle(TableStyle(estilos))
    return tabela


def cabecalho(clinica):
    if not clinica:
        return []
    nome = ParagraphStyle('documento-clinica', parent=BASE, fontName='Helvetica-Bold', fontSize=14, leading=17, textColor=PRIMARIA)
    contato = ParagraphStyle('documento-contato', parent=BASE, fontSize=8.5, leading=11, textColor=SUAVE)
    partes = [getattr(clinica, 'endereco', None),
              f"Tel.: {clinica.telefone}" if getattr(clinica, 'telefone', None) else None,
              getattr(clinica, 'email', None),
              f"CNPJ {format_cnpj(clinica.cnpj)}" if getattr(clinica, 'cnpj', None) else None]
    texto = [Paragraph(_texto(clinica.nome), nome)]
    if any(partes):
        texto.append(Paragraph(' · '.join(_texto(p) for p in partes if p), contato))
    logo = _carregar_logo(clinica)
    if logo:
        dados, largura, altura = logo
        escala = 1.9 * cm / max(largura, altura)
        imagens = [Image(BytesIO(dados), width=largura * escala, height=altura * escala, hAlign=align) for align in ('LEFT', 'RIGHT')]
        coluna = 2.3 * cm
        tabela = Table([[imagens[0], texto, imagens[1]]], colWidths=[coluna, LARGURA - 2 * coluna, coluna])
    else:
        tabela = Table([[texto]], colWidths=[LARGURA])
    tabela.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('ALIGN', (-1, 0), (-1, 0), 'RIGHT')]))
    return [tabela, Spacer(1, 6), HRFlowable(width='100%', thickness=1, color=BORDA), Spacer(1, 8)]


def montar(output, historia, clinica, titulo):
    partes = [getattr(clinica, 'nome', None), getattr(clinica, 'endereco', None),
              f"Tel.: {clinica.telefone}" if getattr(clinica, 'telefone', None) else None,
              getattr(clinica, 'email', None),
              f"CNPJ {format_cnpj(clinica.cnpj)}" if getattr(clinica, 'cnpj', None) else None]
    rodape = _compativel(' · '.join(str(p) for p in partes if p))

    def desenhar(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(SUAVE)
        canvas.setStrokeColor(BORDA)
        canvas.line(doc.leftMargin, 1.25 * cm, doc.leftMargin + doc.width, 1.25 * cm)
        pagina = f'pág. {doc.page}'
        canvas.drawRightString(doc.leftMargin + doc.width, .85 * cm, pagina)
        espaco = doc.width - canvas.stringWidth(pagina, 'Helvetica', 7.5) - 12
        texto = rodape
        while texto and canvas.stringWidth(texto, 'Helvetica', 7.5) > espaco:
            texto = texto[:-2].rstrip() + '…'
        canvas.drawString(doc.leftMargin, .85 * cm, texto)
        canvas.restoreState()

    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                            topMargin=1.4 * cm, bottomMargin=1.8 * cm, title=titulo,
                            author=getattr(clinica, 'nome', None) or 'PetOrlândia', creator='PetOrlândia')
    doc.build(historia, onFirstPage=desenhar, onLaterPages=desenhar)
