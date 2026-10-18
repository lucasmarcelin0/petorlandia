"""PDF da receita gerado no servidor, para baixar e assinar no gov.br.

A tela de impressão da receita depende do "Salvar como PDF" do próprio
aparelho. Em alguns celulares (visto num Xiaomi Redmi Note 13) esse recurso
grava um arquivo de 0 B: o PDF não abre e o assinador do gov.br responde
"Arquivo não encontrado". Aqui o arquivo sai pronto do servidor, igual em
qualquer aparelho.

O conteúdo espelha ``templates/orcamentos/imprimir_bloco.html``: o que mudar
lá (campos, rótulos, quem assina) deve mudar aqui também.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from io import BytesIO
from xml.sax.saxutils import escape

from document_utils import format_cnpj
from template_filters import format_datetime_brazil

logger = logging.getLogger(__name__)

COR_PRIMARIA = '#1f3a56'
COR_SECUNDARIA = '#556b83'
COR_BORDA = '#d9e2ec'
COR_TEXTO = '#2b2d33'
COR_SUAVE = '#687385'
COR_DESTAQUE = '#1f7a8c'
COR_FUNDO_NOTA = '#eef3f9'

# Limite do download do logotipo: o PDF não pode travar nem inchar por causa
# dele (o assinador do gov.br aceita no máximo 10 MB).
_LOGO_TIMEOUT_S = 4
_LOGO_MAX_BYTES = 5 * 1024 * 1024
_LOGO_MAX_PX = 600


def nome_arquivo_receita(bloco) -> str:
    """Nome do arquivo só com letras simples, números e hífen.

    O título da página ("Receita de X | Clínica") virava o nome do PDF salvo
    pelo celular, com acento e barra vertical; alguns gerenciadores de
    arquivos e o assinador do gov.br lidam mal com isso.
    """
    nome_animal = getattr(getattr(bloco, 'animal', None), 'name', None) or ''
    slug = unicodedata.normalize('NFKD', nome_animal).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', slug).strip('-').lower()[:40]
    return f"receita-{bloco.id}-{slug}.pdf" if slug else f"receita-{bloco.id}.pdf"


def _assinatura(user):
    """Mesma resolução de ``assinatura_de`` (app.py) para um ``User``."""
    vet = getattr(user, 'veterinario', None) if user else None
    return vet.assinatura if vet else None


def _membership_ativa(user) -> bool:
    vet = getattr(user, 'veterinario', None) if user else None
    membership = getattr(vet, 'membership', None) if vet else None
    return bool(membership and membership.is_active())


def _valor_crmv(user, vazio='—') -> str:
    """Equivalente ao macro ``valor_crmv`` de components/assinatura.html."""
    a = _assinatura(user)
    if not a or not a.crmv_formatado:
        return vazio
    valor = a.crmv_formatado.replace('CRMV ', '')
    if not a.pode_assinar:
        valor += f" (resp. técnico: {a.responsavel_tecnico})"
    return valor


# A Helvetica (fonte embutida em todo leitor de PDF) só cobre o Windows-1252:
# o resto sai como quadradinho preto. Símbolos que mudam o sentido da receita
# ganham equivalente; emoji e demais caracteres fora da fonte são omitidos.
_SUBSTITUICOES = str.maketrans({
    '≥': '>=', '≤': '<=', '≈': '~', '→': '->', '←': '<-', '−': '-',
    '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
})


def _compativel(texto: str) -> str:
    texto = unicodedata.normalize('NFC', texto).translate(_SUBSTITUICOES)
    saida = []
    for caractere in texto:
        try:
            caractere.encode('cp1252')
        except UnicodeEncodeError:
            continue
        saida.append(caractere)
    return ''.join(saida)


def _texto(valor) -> str:
    """Texto seguro para ``Paragraph`` (que interpreta marcação XML)."""
    if valor is None:
        return ''
    texto = _compativel(str(valor)).strip()
    return escape(texto).replace('\r\n', '\n').replace('\n', '<br/>')


def _carregar_logo(clinica):
    """Logotipo da própria clínica, reduzido, em JPEG: ``(bytes, largura, altura)``.

    Nunca cai para o logo do site: clínica sem logotipo sai sem logo.

    Devolve ``None`` se não der para obter. Falhar aqui nunca impede o PDF:
    a receita sai sem o logotipo.
    """
    caminho = getattr(clinica, 'logotipo', None) if clinica else None
    if not caminho:
        return None
    try:
        from PIL import Image as PILImage

        if caminho.startswith(('http://', 'https://')):
            import requests

            with requests.get(caminho, timeout=_LOGO_TIMEOUT_S, stream=True) as resposta:
                resposta.raise_for_status()
                dados = resposta.raw.read(_LOGO_MAX_BYTES + 1, decode_content=True)
            if len(dados) > _LOGO_MAX_BYTES:
                return None
            origem = BytesIO(dados)
        else:
            from flask import current_app

            if caminho.startswith('/'):
                origem = os.path.join(current_app.root_path, caminho.lstrip('/'))
            else:
                origem = os.path.join(current_app.static_folder, 'uploads', 'clinicas', caminho)
            if not os.path.isfile(origem):
                return None

        with PILImage.open(origem) as img:
            img.load()
            img = img.convert('RGBA')
        img.thumbnail((_LOGO_MAX_PX, _LOGO_MAX_PX))
        # Fundo branco no lugar da transparência: alguns leitores de PDF de
        # celular desenham o canal alfa como preto.
        fundo = PILImage.new('RGB', img.size, (255, 255, 255))
        fundo.paste(img, mask=img.split()[-1])
        arquivo = BytesIO()
        fundo.save(arquivo, format='JPEG', quality=90)
        return arquivo.getvalue(), fundo.size[0], fundo.size[1]
    except Exception:  # noqa: BLE001 - logotipo é opcional
        logger.info('Logotipo da clínica indisponível para o PDF da receita', exc_info=True)
        return None


def gerar_pdf_receita(*, bloco, clinica, veterinario, salvo_por, printing_user, printed_at) -> bytes:
    """Monta o PDF (A4) da receita e devolve os bytes."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Image,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    animal = bloco.animal
    tutor = animal.owner if animal else None

    base = ParagraphStyle('base', fontName='Helvetica', fontSize=10, leading=13.5, textColor=colors.HexColor(COR_TEXTO))
    estilos = {
        'clinica': ParagraphStyle('clinica', parent=base, fontName='Helvetica-Bold', fontSize=14, leading=17,
                                  textColor=colors.HexColor(COR_PRIMARIA)),
        'contato': ParagraphStyle('contato', parent=base, fontSize=8.5, leading=11, textColor=colors.HexColor(COR_SUAVE)),
        'titulo': ParagraphStyle('titulo', parent=base, fontName='Helvetica-Bold', fontSize=15, leading=19,
                                 textColor=colors.HexColor(COR_PRIMARIA)),
        'tag': ParagraphStyle('tag', parent=base, fontName='Helvetica-Bold', fontSize=8.5, leading=11,
                              textColor=colors.HexColor(COR_DESTAQUE), alignment=TA_RIGHT),
        'meta': ParagraphStyle('meta', parent=base, fontSize=8.5, leading=11.5, textColor=colors.HexColor(COR_SECUNDARIA)),
        'card_titulo': ParagraphStyle('card_titulo', parent=base, fontName='Helvetica-Bold', fontSize=8.5, leading=11,
                                      textColor=colors.HexColor(COR_PRIMARIA)),
        'rotulo': ParagraphStyle('rotulo', parent=base, fontSize=7.5, leading=9.5, textColor=colors.HexColor(COR_SUAVE)),
        'valor': ParagraphStyle('valor', parent=base, fontSize=9, leading=11.5),
        'secao': ParagraphStyle('secao', parent=base, fontName='Helvetica-Bold', fontSize=10.5, leading=14,
                                textColor=colors.HexColor(COR_PRIMARIA), spaceBefore=12, spaceAfter=6),
        'medicamento': ParagraphStyle('medicamento', parent=base, fontName='Helvetica-Bold', fontSize=10.5, leading=14),
        'posologia': ParagraphStyle('posologia', parent=base, fontSize=9.5, leading=13,
                                    textColor=colors.HexColor(COR_SECUNDARIA)),
        'obs': ParagraphStyle('obs', parent=base, fontSize=9.5, leading=13),
        'obs_suave': ParagraphStyle('obs_suave', parent=base, fontSize=9.5, leading=13,
                                    textColor=colors.HexColor(COR_SUAVE)),
        'nota': ParagraphStyle('nota', parent=base, fontSize=9.5, leading=13, leftIndent=9, rightIndent=9,
                               backColor=colors.HexColor(COR_FUNDO_NOTA), borderPadding=(7, 9, 7, 9),
                               spaceBefore=6, spaceAfter=6),
        'assinatura': ParagraphStyle('assinatura', parent=base, fontSize=9.5, leading=12.5, alignment=TA_CENTER),
        'assinatura_nota': ParagraphStyle('assinatura_nota', parent=base, fontSize=8, leading=10.5, alignment=TA_CENTER,
                                          textColor=colors.HexColor(COR_SUAVE)),
    }

    # Largura da página menos as margens (1,6 cm) e o respiro de 6 pt que o
    # quadro do SimpleDocTemplate deixa de cada lado; tabelas mais largas que
    # isso saem centralizadas e desalinhadas do texto.
    largura_util = A4[0] - 3.2 * cm - 12
    historia = []

    # Cabeçalho da clínica.
    if clinica:
        contatos = [
            clinica.endereco,
            f"Tel.: {clinica.telefone}" if clinica.telefone else None,
            clinica.email,
            f"CNPJ {format_cnpj(clinica.cnpj)}" if clinica.cnpj else None,
        ]
        bloco_texto = [Paragraph(_texto(clinica.nome), estilos['clinica'])]
        contato_linha = ' · '.join(_texto(c) for c in contatos if c)
        if contato_linha:
            bloco_texto.append(Paragraph(contato_linha, estilos['contato']))

        logo = _carregar_logo(clinica)
        if logo is not None:
            # Logo da clínica dos dois lados, como na receita impressa.
            dados_logo, largura_px, altura_px = logo
            lado = 1.9 * cm
            proporcao = largura_px / float(altura_px or 1)
            largura_logo, altura_logo = (lado, lado / proporcao) if proporcao >= 1 else (lado * proporcao, lado)
            coluna_logo = lado + 0.4 * cm
            cabecalho = Table(
                [[
                    Image(BytesIO(dados_logo), width=largura_logo, height=altura_logo, hAlign='LEFT'),
                    bloco_texto,
                    Image(BytesIO(dados_logo), width=largura_logo, height=altura_logo, hAlign='RIGHT'),
                ]],
                colWidths=[coluna_logo, largura_util - 2 * coluna_logo, coluna_logo],
            )
        else:
            cabecalho = Table([[bloco_texto]], colWidths=[largura_util])
        cabecalho.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('ALIGN', (-1, 0), (-1, 0), 'RIGHT'),
        ]))
        historia.append(cabecalho)
        historia.append(Spacer(1, 6))
        historia.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor(COR_BORDA)))
        historia.append(Spacer(1, 8))

    titulo = Table(
        [[Paragraph('Receita Médico-Veterinária', estilos['titulo']),
          Paragraph('CONTROLE ESPECIAL', estilos['tag'])]],
        colWidths=[largura_util * 0.7, largura_util * 0.3],
    )
    titulo.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    historia.append(titulo)
    historia.append(Spacer(1, 4))

    signature_user = veterinario or printing_user
    membership_ativa = _membership_ativa(signature_user)

    meta = []
    if bloco.data_criacao:
        meta.append(f"Emitido em {format_datetime_brazil(bloco.data_criacao, '%d/%m/%Y %H:%M')}")
    meta.append(f"Identificador da prescrição: #{bloco.id}")
    if salvo_por:
        meta.append(f"Salvo por {salvo_por.name}")
    historia.append(Paragraph(' · '.join(_texto(m) for m in meta), estilos['meta']))

    impresso_por = _texto(printing_user.name if printing_user else '—')
    if (membership_ativa and printing_user and signature_user
            and printing_user.id == signature_user.id):
        impresso_por += f" · {_texto(_valor_crmv(signature_user, vazio='sem CRMV'))}"
    data_hora = format_datetime_brazil(printed_at, '%d/%m/%Y %H:%M') if printed_at else ''
    historia.append(Paragraph(
        f"<b>Impresso por:</b> {impresso_por} · <b>Data/Hora:</b> {_texto(data_hora)}",
        estilos['meta'],
    ))
    historia.append(Spacer(1, 10))

    # Fichas: profissional, paciente e responsável legal.
    def ficha(titulo_ficha, linhas):
        conteudo = [Paragraph(_texto(titulo_ficha).upper(), estilos['card_titulo']), Spacer(1, 3)]
        for rotulo, valor in linhas:
            if valor in (None, ''):
                continue
            conteudo.append(Paragraph(_texto(rotulo), estilos['rotulo']))
            conteudo.append(Paragraph(_texto(valor), estilos['valor']))
            conteudo.append(Spacer(1, 2))
        return conteudo

    fichas = Table(
        [[
            ficha('Profissional Responsável', [
                ('Nome', veterinario.name if veterinario else '—'),
                ('CRMV', _valor_crmv(veterinario)),
            ]),
            ficha('Paciente', [
                ('Nome', animal.name if animal else None),
                ('Espécie', animal.species if animal else None),
                ('Raça', animal.breed if animal else None),
                ('Sexo', animal.sex if animal else None),
                ('Idade', animal.age_display if animal else None),
                ('Microchip', animal.microchip_number if animal else None),
            ]),
            ficha('Responsável Legal', [
                ('Nome', tutor.name if tutor else None),
                ('CPF', tutor.cpf if tutor else None),
                ('Endereço', tutor.address if tutor else None),
                ('Contato', tutor.phone if tutor else None),
            ]),
        ]],
        colWidths=[largura_util / 3.0] * 3,
    )
    fichas.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (0, 0), 0.75, colors.HexColor(COR_BORDA)),
        ('BOX', (1, 0), (1, 0), 0.75, colors.HexColor(COR_BORDA)),
        ('BOX', (2, 0), (2, 0), 0.75, colors.HexColor(COR_BORDA)),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    historia.append(fichas)

    historia.append(Paragraph('Prescrição Médico-Veterinária', estilos['secao']))
    historia.append(HRFlowable(width='100%', thickness=0.75, color=colors.HexColor(COR_BORDA), spaceAfter=6))
    for item in bloco.prescricoes:
        partes = [Paragraph(_texto(item.medicamento), estilos['medicamento'])]
        posologia = [
            f"<b>{rotulo}:</b> {_texto(valor)}"
            for rotulo, valor in (
                ('Dosagem', item.dosagem),
                ('Frequência', item.frequencia),
                ('Duração', item.duracao),
            )
            if valor
        ]
        if posologia:
            partes.append(Paragraph('&nbsp;&nbsp;&nbsp;'.join(posologia), estilos['posologia']))
        if item.observacoes:
            partes.append(Paragraph(_texto(item.observacoes), estilos['obs']))
        elif not posologia:
            partes.append(Paragraph('Posologia informada em consulta.', estilos['obs_suave']))
        partes.append(Spacer(1, 8))
        historia.append(KeepTogether(partes))

    if bloco.instrucoes_gerais:
        historia.append(Paragraph('Orientações e Cuidados', estilos['secao']))
        # Parágrafo com fundo, não célula de tabela: orientações longas
        # precisam quebrar entre páginas, e a célula não se divide.
        historia.append(Paragraph(_texto(bloco.instrucoes_gerais), estilos['nota']))

    # Assinatura: espaço em branco acima da linha para a assinatura à mão ou
    # para o carimbo visual que o assinador do gov.br põe na página.
    assinatura = [
        Spacer(1, 1.6 * cm),
        HRFlowable(width='45%', thickness=0.75, color=colors.HexColor(COR_TEXTO), hAlign='CENTER', spaceAfter=4),
        Paragraph(_texto(signature_user.name if signature_user else '—'), estilos['assinatura']),
    ]
    if membership_ativa:
        a = _assinatura(signature_user)
        if a and a.crmv_formatado:
            assinatura.append(Paragraph(_texto(a.crmv_formatado), estilos['assinatura']))
            if not a.pode_assinar:
                assinatura.append(Paragraph(
                    _texto(f"Documento sob responsabilidade técnica de {a.responsavel_tecnico}"),
                    estilos['assinatura_nota'],
                ))
        else:
            assinatura.append(Paragraph('_____________________________', estilos['assinatura']))
    else:
        assinatura.append(Paragraph('—', estilos['assinatura']))
    historia.append(KeepTogether(assinatura))

    rodape_partes = []
    if clinica:
        rodape_partes = [
            clinica.nome,
            clinica.endereco,
            f"Tel.: {clinica.telefone}" if clinica.telefone else None,
            clinica.email,
            f"CNPJ {format_cnpj(clinica.cnpj)}" if clinica.cnpj else None,
        ]
    rodape = _compativel(' · '.join(str(p) for p in rodape_partes if p))

    def desenhar_rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(colors.HexColor(COR_SUAVE))
        canvas.setStrokeColor(colors.HexColor(COR_BORDA))
        canvas.line(doc.leftMargin, 1.25 * cm, doc.leftMargin + doc.width, 1.25 * cm)
        pagina = f"Receita #{bloco.id} · pág. {doc.page}"
        canvas.drawRightString(doc.leftMargin + doc.width, 0.85 * cm, pagina)
        if rodape:
            # Corta o rodapé da clínica antes de encostar no número da página.
            espaco = doc.width - canvas.stringWidth(pagina, 'Helvetica', 7.5) - 12
            texto = rodape
            while texto and canvas.stringWidth(texto, 'Helvetica', 7.5) > espaco:
                texto = texto[:-2].rstrip() + '…'
            canvas.drawString(doc.leftMargin, 0.85 * cm, texto)
        canvas.restoreState()

    buffer = BytesIO()
    titulo_pdf = f"Receita de {animal.name}" if animal and animal.name else 'Receita'
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.8 * cm,
        title=titulo_pdf,
        author=(clinica.nome if clinica and clinica.nome else 'PetOrlândia'),
        subject='Receita Médico-Veterinária',
        creator='PetOrlândia',
    )
    doc.build(historia, onFirstPage=desenhar_rodape, onLaterPages=desenhar_rodape)
    return buffer.getvalue()
