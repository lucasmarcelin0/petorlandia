"""Liga o que foi prescrito ao que a loja tem para vender.

É o cruzamento de maior intenção de compra do site: o tutor acabou de sair da
consulta com uma receita na mão. Até aqui esse caminho terminava em papel — a
pessoa lia o nome do medicamento e ia procurar em outro lugar.

O texto da prescrição é livre ("Prednisona — 5 mg comprimido"), então o
casamento é por princípio ativo, não por nome exato. Duas decisões de segurança
governam este módulo:

1. **Concentração errada é dano, não inconveniência.** "Prednisona 5mg" e
   "Prednisona 20mg" casam no mesmo princípio ativo. Quando a apresentação da
   loja não confere com a prescrita, a sugestão vem marcada como tal e nunca é
   incluída na compra em lote.
2. **A loja sugere, o veterinário prescreve.** Nada aqui afirma equivalência
   terapêutica; a rotulagem diz o que é — um produto com o mesmo princípio
   ativo disponível para compra.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

#: Palavras que descrevem forma farmacêutica, embalagem ou público-alvo. Não
#: identificam o medicamento e, se contassem como acerto, fariam "comprimido"
#: casar tudo com tudo.
_STOPWORDS = {
    'comprimido', 'comprimidos', 'capsula', 'capsulas', 'drageas', 'dragea',
    'frasco', 'frascos', 'caixa', 'caixas', 'ampola', 'ampolas', 'sache',
    'saches', 'bisnaga', 'pote', 'embalagem', 'contendo', 'unidade',
    'unidades', 'solucao', 'suspensao', 'injetavel', 'oral', 'topico',
    'topica', 'gotas', 'pomada', 'creme', 'spray', 'aerossol', 'xarope',
    'pasta', 'coleira', 'pipeta', 'transdermica',
    'cada', 'para', 'com', 'sem', 'uso', 'via', 'dose', 'doses',
    'caes', 'cao', 'gatos', 'gato', 'animal', 'animais', 'peso',
    'adulto', 'adultos', 'filhote', 'filhotes',
}

#: Um único acerto só conta quando a palavra é longa o bastante para ser um
#: princípio ativo. "sulfato" sozinho não pode arrastar uma sugestão.
_MIN_TOKEN_LEN = 5
_WEAK_TOKENS = {'sulfato', 'cloridrato', 'acido', 'oleo', 'extrato', 'sodio'}

_STRENGTH_RE = re.compile(r'(\d+(?:[.,]\d+)?)\s*(mg/g|mg/ml|mcg|mg|ml|g|%)', re.I)


@dataclass
class ProductMatch:
    """Um produto da loja sugerido para um item da receita."""

    product: object
    score: int
    same_strength: bool
    prescribed_strengths: list[str] = field(default_factory=list)

    @property
    def in_stock(self) -> bool:
        return (self.product.stock or 0) > 0

    @property
    def confidence(self) -> str:
        """``exata`` quando a apresentação confere; ``verificar`` caso contrário."""
        return 'exata' if self.same_strength else 'verificar'

    @property
    def buyable_in_bulk(self) -> bool:
        """Entra no 'adicionar todos'? Só o que confere e tem estoque."""
        return self.same_strength and self.in_stock


@dataclass
class PrescriptionLine:
    """Um item da receita com o que a loja encontrou para ele."""

    prescricao: object
    matches: list[ProductMatch] = field(default_factory=list)

    @property
    def has_offer(self) -> bool:
        return bool(self.matches)

    @property
    def best(self) -> ProductMatch | None:
        return self.matches[0] if self.matches else None


def build_prescription_offers(prescricoes, limit_per_item: int = 2) -> list[PrescriptionLine]:
    """Para cada item prescrito, os produtos da loja que servem.

    Devolve sempre uma linha por prescrição — inclusive as sem oferta, porque a
    tela precisa dizer "não temos" em vez de omitir o item e dar a impressão de
    que a receita está incompleta.
    """
    produtos = _sellable_products()
    linhas: list[PrescriptionLine] = []

    for prescricao in prescricoes:
        texto = getattr(prescricao, 'medicamento', '') or ''
        tokens = _tokens(texto)
        strengths = _strengths(texto)

        candidatos: list[ProductMatch] = []
        for produto in produtos:
            comuns = tokens & _tokens(produto.name or '')
            if not _is_real_match(comuns):
                continue
            produto_strengths = _strengths(produto.name or '')
            same = bool(strengths) and bool(produto_strengths) and bool(
                strengths & produto_strengths
            )
            # Sem concentração declarada em nenhum dos lados não há o que
            # conferir: trata-se como apresentação compatível.
            if not strengths or not produto_strengths:
                same = True
            candidatos.append(ProductMatch(
                product=produto,
                score=len(comuns),
                same_strength=same,
                prescribed_strengths=sorted(strengths),
            ))

        candidatos.sort(
            key=lambda m: (m.same_strength, m.in_stock, m.score, -float(m.product.price or 0)),
            reverse=True,
        )
        linhas.append(PrescriptionLine(
            prescricao=prescricao,
            matches=candidatos[:limit_per_item],
        ))

    return linhas


def bulk_buyable_products(linhas) -> list:
    """Produtos que o botão 'adicionar todos' pode incluir, sem repetir."""
    vistos: set[int] = set()
    produtos = []
    for linha in linhas:
        melhor = linha.best
        if melhor is None or not melhor.buyable_in_bulk:
            continue
        if melhor.product.id in vistos:
            continue
        vistos.add(melhor.product.id)
        produtos.append(melhor.product)
    return produtos


# --------------------------------------------------------------------- internos


def _sellable_products() -> list:
    from sqlalchemy import or_

    from models import CasaDeRacao, Product

    return (
        Product.query
        .outerjoin(CasaDeRacao, Product.casa_de_racao_id == CasaDeRacao.id)
        .filter(Product.status == 'active')
        .filter(Product.is_demo.is_(False))
        .filter(
            or_(
                Product.casa_de_racao_id.is_(None),
                CasaDeRacao.status == 'ativa',
            )
        )
        .all()
    )


def _normalize(text: str) -> str:
    sem_acento = unicodedata.normalize('NFKD', text or '')
    sem_acento = sem_acento.encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', ' ', sem_acento.lower()).strip()


def _tokens(text: str) -> set[str]:
    return {
        palavra
        for palavra in _normalize(text).split()
        if len(palavra) >= _MIN_TOKEN_LEN
        and palavra not in _STOPWORDS
        and not palavra.isdigit()
    }


def _strengths(text: str) -> set[str]:
    """Concentrações declaradas no texto, normalizadas ("5 mg" -> ``5mg``)."""
    achados = set()
    for numero, unidade in _STRENGTH_RE.findall(text or ''):
        numero = numero.replace(',', '.').rstrip('0').rstrip('.') or '0'
        achados.add(f'{numero}{unidade.lower()}')
    return achados


def _is_real_match(comuns: set[str]) -> bool:
    """Um acerto isolado em palavra genérica não sustenta uma sugestão."""
    if not comuns:
        return False
    if len(comuns) >= 2:
        return True
    unica = next(iter(comuns))
    return unica not in _WEAK_TOKENS and len(unica) >= 6
