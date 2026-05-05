"""Re-ranqueamento de buscas de catálogo (medicamentos, exames, vacinas, rações)
baseado na espécie do animal sob consulta.

Princípio: NUNCA filtra. Apenas reordena. Itens sem species_scope ou de espécies
diferentes da do animal continuam visíveis (mas mais abaixo no resultado), pois
veterinários frequentemente usam medicamentos extra-label.

Uso típico nos endpoints:

    from services.species_ranking import (
        resolver_species_scope_do_animal,
        ordenar_por_species_scope,
    )

    scope = resolver_species_scope_do_animal(animal_id)
    resultados = ordenar_por_species_scope(resultados, scope)

Quando `scope` é None (sem animal_id ou espécie desconhecida), a função retorna
a lista original sem alterações.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Vocabulário canônico de scope
# ---------------------------------------------------------------------------
SCOPE_CG = 'CG'        # cães, gatos, pets de pequeno porte
SCOPE_BE = 'BE'        # bovinos, equinos, grandes animais de produção
SCOPE_AMBOS = 'AMBOS'  # produto aplicável a ambos os grupos
SCOPE_OUTRO = 'OUTRO'  # aves, exóticos, peixes, etc.

VALID_SCOPES = {SCOPE_CG, SCOPE_BE, SCOPE_AMBOS, SCOPE_OUTRO}


# ---------------------------------------------------------------------------
# Heurísticas de mapeamento espécie → scope
# ---------------------------------------------------------------------------
_TOKENS_CG = (
    'cão', 'caes', 'cães', 'cao', 'cachorro', 'canino',
    'gato', 'felino', 'cat', 'dog',
    'pequenos animais', 'pequeno porte',
)

_TOKENS_BE = (
    'bovino', 'boi', 'vaca', 'gado', 'bezerro', 'novilho',
    'equino', 'cavalo', 'égua', 'egua', 'eqüino', 'potro',
    'búfalo', 'bufalo',
    'caprino', 'cabra', 'bode',
    'ovino', 'ovelha', 'carneiro',
    'suíno', 'suino', 'porco',
    'grandes animais', 'animais de produção', 'producao',
)

_TOKENS_OUTRO = (
    'ave', 'aves', 'galinha', 'frango', 'galo',
    'peixe', 'pisc',
    'réptil', 'reptil', 'iguana', 'tartaruga',
    'roedor', 'hamster', 'cobaia',
    'exóticos', 'exoticos',
    'apícola', 'apicola', 'abelha',
)


def _normalizar(texto: str) -> str:
    """Lowercase + colapsa espaços."""
    return re.sub(r'\s+', ' ', (texto or '').lower()).strip()


def especie_para_scope(especie_texto: Optional[str]) -> Optional[str]:
    """Mapeia o nome textual da espécie do animal para o scope canônico.

    Retorna None se não conseguir classificar — nesse caso, o re-ranqueamento
    é desligado (mantém ordem original).
    """
    if not especie_texto:
        return None
    alvo = _normalizar(especie_texto)
    if not alvo:
        return None
    if any(token in alvo for token in _TOKENS_CG):
        return SCOPE_CG
    if any(token in alvo for token in _TOKENS_BE):
        return SCOPE_BE
    if any(token in alvo for token in _TOKENS_OUTRO):
        return SCOPE_OUTRO
    return None


def resolver_species_scope_do_animal(animal_id) -> Optional[str]:
    """Carrega o Animal e devolve o scope canônico.

    Funciona mesmo sem app context ativo: retorna None silenciosamente caso a
    importação ou a query falhe (ex.: chamadas em testes).
    """
    if animal_id in (None, '', 0, '0'):
        return None
    try:
        animal_id_int = int(animal_id)
    except (TypeError, ValueError):
        return None
    try:
        from models.base import Animal  # import local para evitar ciclo
        animal = Animal.query.get(animal_id_int)
    except Exception:
        return None
    if not animal:
        return None
    species_name = getattr(getattr(animal, 'species', None), 'name', None)
    return especie_para_scope(species_name)


# ---------------------------------------------------------------------------
# Compatibilidade entre scope alvo (animal) e scope do item
# ---------------------------------------------------------------------------
def _item_scope_match_score(target: Optional[str], item_scope: Optional[str]) -> int:
    """Pontuação inteira (maior = mais relevante para a espécie alvo).

       3: scope idêntico ao alvo                       (forte priorização)
       2: item marcado como 'AMBOS'                    (cobertura ampla)
       1: item sem scope (não classificado)            (neutro)
       0: scope diferente / 'OUTRO' não solicitado     (rebaixa)
    """
    if not target:
        return 1  # sem alvo: tudo neutro
    if not item_scope:
        return 1
    item_scope = item_scope.upper()
    if item_scope == target:
        return 3
    if item_scope == SCOPE_AMBOS:
        return 2
    return 0


def _resolver_scope_de_item(item, especies_textos: Sequence[Optional[str]] = ()) -> Optional[str]:
    """Resolve o scope efetivo de um item de catálogo.

    1. Se ele tem species_scope direto, usa esse valor.
    2. Caso contrário, tenta inferir a partir dos textos passados (ex.: a coluna
       legada 'especies' do Medicamento ou o conteudo_estruturado).
    """
    direto = getattr(item, 'species_scope', None)
    if direto:
        valor = str(direto).upper().strip()
        if valor in VALID_SCOPES:
            return valor
    for texto in especies_textos:
        if not texto:
            continue
        inferido = especie_para_scope(texto)
        if inferido:
            return inferido
    return None


def ordenar_por_species_scope(
    itens: Iterable,
    scope_alvo: Optional[str],
    *,
    inferir_de: Sequence[str] = (),
) -> List:
    """Reordena (estável) os itens priorizando os que casam com `scope_alvo`.

    A ordenação é estável: empates entre itens com mesma compatibilidade
    preservam a ordem original de entrada (que normalmente já está ordenada
    por relevância textual, alfabética etc.).

    Parâmetros
    ----------
    itens : iterável de objetos com (opcional) atributo `species_scope`.
    scope_alvo : 'CG' / 'BE' / 'AMBOS' / 'OUTRO' / None.
    inferir_de : nomes de atributos de string que podem conter dicas de espécie
                 quando species_scope ainda é NULL (ex.: ('especies',)).

    Retorna
    -------
    Lista re-ordenada. Se `scope_alvo` for None, devolve uma cópia da lista
    original sem alteração.
    """
    lista = list(itens)
    if not scope_alvo or not lista:
        return lista

    scope_alvo_norm = scope_alvo.upper()
    if scope_alvo_norm not in VALID_SCOPES:
        return lista

    def _chave_estavel(idx_item):
        idx, item = idx_item
        textos = []
        for nome_attr in inferir_de:
            valor = getattr(item, nome_attr, None)
            if isinstance(valor, str):
                textos.append(valor)
        scope_item = _resolver_scope_de_item(item, textos)
        score = _item_scope_match_score(scope_alvo_norm, scope_item)
        # `-score` para ordem decrescente; `idx` mantém ordem de empate.
        return (-score, idx)

    indexados = list(enumerate(lista))
    indexados.sort(key=_chave_estavel)
    return [item for _, item in indexados]


# ---------------------------------------------------------------------------
# Helper para detectar o scope a partir de campos textuais ricos do Medicamento
# (especies legacy + nodes do conteudo_estruturado)
# ---------------------------------------------------------------------------
def inferir_scope_de_medicamento(medicamento) -> Optional[str]:
    """Infere o species_scope para um Medicamento já no banco.

    Útil em scripts de backfill: examina o campo legado 'especies' (string),
    o conteudo_estruturado JSON e as doses associadas para chegar a um veredito.
    """
    candidatos: list[str] = []

    especies_legacy = getattr(medicamento, 'especies', None)
    if isinstance(especies_legacy, str):
        candidatos.append(especies_legacy)

    conteudo = getattr(medicamento, 'conteudo_estruturado', None)
    if isinstance(conteudo, dict):
        especies_node = conteudo.get('especies')
        if isinstance(especies_node, str):
            candidatos.append(especies_node)
        elif isinstance(especies_node, dict):
            for v in especies_node.values():
                if isinstance(v, str):
                    candidatos.append(v)
                elif isinstance(v, list):
                    candidatos.extend(x for x in v if isinstance(x, str))

    for dose in (getattr(medicamento, 'doses', None) or []):
        especie = getattr(dose, 'especie', None)
        if isinstance(especie, str):
            candidatos.append(especie)

    encontrados = {especie_para_scope(c) for c in candidatos if c}
    encontrados.discard(None)
    if not encontrados:
        return None
    if encontrados == {SCOPE_CG}:
        return SCOPE_CG
    if encontrados == {SCOPE_BE}:
        return SCOPE_BE
    if encontrados == {SCOPE_OUTRO}:
        return SCOPE_OUTRO
    if SCOPE_CG in encontrados and SCOPE_BE in encontrados:
        return SCOPE_AMBOS
    # mistura inconclusiva → AMBOS para segurança (não rebaixa nem força)
    return SCOPE_AMBOS
