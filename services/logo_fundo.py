"""Remove o fundo liso de um logotipo, deixando-o transparente.

Existe porque todo upload de imagem virava JPEG: um logo enviado em PNG sem
fundo ganhava um quadrado branco atrás, que aparece em todo lugar que não é
branco (cabeçalhos, cartões, modo escuro). O upload de logo já preserva a
transparência; isto conserta os logos que foram salvos antes.

O fundo é a cor que domina a borda da imagem, e só sai a região dessa cor
ligada à borda: um branco no meio do desenho (olho de um bicho, miolo de uma
letra) fica. Fundo que não é liso (foto, degradê forte) é recusado em vez de
estragar o logo.
"""
from __future__ import annotations

import os
from collections import Counter
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFilter

_LOGO_TIMEOUT_S = 8
_LOGO_MAX_BYTES = 10 * 1024 * 1024


class FundoNaoRemovivel(ValueError):
    """O logo não tem um fundo liso que dê para tirar com segurança."""


def remover_fundo(imagem: Image.Image, tolerancia: int = 32, minimo_borda: float = 0.6) -> Image.Image:
    """Devolve uma cópia RGBA do logo com o fundo transparente.

    ``tolerancia`` é a diferença máxima (0-255, por canal) para um pixel contar
    como fundo; pixels um pouco acima disso na divisa ficam semitransparentes,
    para a borda do desenho não sair serrilhada. ``minimo_borda`` é a fração da
    borda que precisa ser da cor de fundo para o fundo ser considerado liso.
    """
    original = imagem.convert("RGBA")
    largura, altura = original.size
    if largura < 3 or altura < 3:
        raise FundoNaoRemovivel("A imagem é pequena demais.")

    alfa_original = original.getchannel("A")
    rgb = original.convert("RGB")
    borda = _pixels_da_borda(largura, altura)

    opacos = [rgb.getpixel(p) for p in borda if alfa_original.getpixel(p) > 200]
    if len(opacos) < len(borda) * 0.5:
        raise FundoNaoRemovivel("O logo já está sem fundo.")

    # Cor de fundo: a mais comum na borda (agrupada para ignorar ruído do JPEG).
    grupos = Counter((r // 8, g // 8, b // 8) for r, g, b in opacos)
    grupo = grupos.most_common(1)[0][0]
    membros = [c for c in opacos if (c[0] // 8, c[1] // 8, c[2] // 8) == grupo]
    fundo = tuple(sum(canal) // len(membros) for canal in zip(*membros))

    # Distância de cada pixel até a cor de fundo (maior diferença entre canais).
    diferencas = ImageChops.difference(rgb, Image.new("RGB", rgb.size, fundo)).split()
    distancia = ImageChops.lighter(ImageChops.lighter(diferencas[0], diferencas[1]), diferencas[2])

    parecidos_na_borda = sum(1 for p in borda if distancia.getpixel(p) <= tolerancia)
    if parecidos_na_borda < len(borda) * minimo_borda:
        raise FundoNaoRemovivel(
            "O fundo do logo não é de uma cor só (foto ou degradê); não dá para tirar sem estragar o desenho."
        )

    # Candidatos a fundo = 255; o preenchimento a partir da borda marca com 128
    # só o que está ligado a ela.
    candidatos = distancia.point(lambda v: 255 if v <= tolerancia else 0)
    for ponto in borda:
        if candidatos.getpixel(ponto) == 255:
            ImageDraw.floodfill(candidatos, ponto, 128)
    removido = candidatos.point(lambda v: 255 if v == 128 else 0)

    total = largura * altura
    fracao_removida = removido.histogram()[255] / total
    if fracao_removida > 0.97:
        raise FundoNaoRemovivel("O logo parece ser todo da cor do fundo; nada foi alterado.")
    if fracao_removida < 0.005:
        raise FundoNaoRemovivel("Não há fundo para tirar neste logo.")

    # Divisa suave: logo ao lado do que saiu, quem é quase da cor do fundo fica
    # semitransparente.
    vizinhanca = ImageChops.subtract(removido.filter(ImageFilter.MaxFilter(3)), removido)
    parcial = distancia.point(
        lambda v: 0 if v <= tolerancia else 255 if v >= 2 * tolerancia else int((v - tolerancia) * 255 / tolerancia)
    )
    alfa = ImageChops.composite(parcial, ImageChops.invert(removido), vizinhanca)
    alfa = ImageChops.darker(alfa, alfa_original)

    resultado = original.copy()
    resultado.putalpha(alfa)

    # Corta a margem que ficou vazia, com um respiro, para o logo ocupar o
    # espaço reservado a ele nas telas e na receita.
    caixa = alfa.point(lambda v: 255 if v > 8 else 0).getbbox()
    if caixa:
        respiro = max(2, int(max(largura, altura) * 0.02))
        caixa = (
            max(0, caixa[0] - respiro),
            max(0, caixa[1] - respiro),
            min(largura, caixa[2] + respiro),
            min(altura, caixa[3] + respiro),
        )
        resultado = resultado.crop(caixa)
    return resultado


def _pixels_da_borda(largura: int, altura: int) -> list[tuple[int, int]]:
    passo = max(1, max(largura, altura) // 400)
    pontos = set()
    for x in range(0, largura, passo):
        pontos.add((x, 0))
        pontos.add((x, altura - 1))
    for y in range(0, altura, passo):
        pontos.add((0, y))
        pontos.add((largura - 1, y))
    for canto in ((0, 0), (largura - 1, 0), (0, altura - 1), (largura - 1, altura - 1)):
        pontos.add(canto)
    return sorted(pontos)


def abrir_logo(logotipo: str) -> Image.Image:
    """Abre o logotipo gravado (URL do S3 ou arquivo em static/uploads)."""
    if not logotipo:
        raise FundoNaoRemovivel("A clínica não tem logo.")
    if logotipo.startswith(("http://", "https://")):
        import requests

        with requests.get(logotipo, timeout=_LOGO_TIMEOUT_S, stream=True) as resposta:
            resposta.raise_for_status()
            dados = resposta.raw.read(_LOGO_MAX_BYTES + 1, decode_content=True)
        if len(dados) > _LOGO_MAX_BYTES:
            raise FundoNaoRemovivel("O arquivo do logo é grande demais.")
        origem = BytesIO(dados)
    else:
        from flask import current_app

        if logotipo.startswith("/"):
            origem = os.path.join(current_app.root_path, logotipo.lstrip("/"))
        else:
            origem = os.path.join(current_app.static_folder, "uploads", "clinicas", logotipo)
        if not os.path.isfile(origem):
            raise FundoNaoRemovivel("Não encontrei o arquivo do logo.")
    with Image.open(origem) as imagem:
        imagem.load()
        return imagem.copy()


def png_em_memoria(imagem: Image.Image) -> BytesIO:
    arquivo = BytesIO()
    imagem.save(arquivo, format="PNG", optimize=True)
    arquivo.seek(0)
    return arquivo
