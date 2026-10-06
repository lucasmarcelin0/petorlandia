"""Mapa da fila de vacinação: onde fica cada casa da "Inscrição a agendar" e em que dia ela cairia.

Cada endereço da aba é procurado na base de endereços do atlas (CNEFE do IBGE, correções da
equipe e croquis dos condomínios), com o mesmo localizador da camada Dengue Automatizados:
nenhum endereço sai para um geocodificador externo e o que o atlas não tem aparece como
"sem posição", com o motivo.

A previsão de dia repete a regra do "Criar dia de vacinação" (``plan_pmo_day``) sobre a fila,
em duas ordens: a da planilha, que é a que vale hoje, e a proposta por zonas.

Zonas: Orlândia é uma malha métrica inclinada ~5°. Nas ruas o número da casa é a distância em
metros até o eixo entre a Avenida 1 e a Avenida A; nas avenidas, a distância até uma base ao
sul. As ruas pares ficam ao norte do eixo Rua 1/Rua 2 e as ímpares ao sul. Por isso os limites
das zonas são retas nessa malha (``u`` ao longo das ruas, ``v`` ao longo das avenidas, em metros
a partir da Vigilância) e correspondem a ruas e avenidas de verdade.
"""
from __future__ import annotations

import json
import math
import os
import threading
from collections import Counter
from typing import Any

ORIGEM = (-47.8838617, -20.7122478)          # Vigilância Sanitária (longitude, latitude)
_MX = 111320 * math.cos(math.radians(-20.72))
_MY = 111320
_INCLINACAO = math.atan(0.09)                 # as ruas sobem ~9 cm por metro para leste
_COS, _SIN = math.cos(_INCLINACAO), math.sin(_INCLINACAO)

# Ordem = sequência sugerida de visita (cada zona encosta na seguinte).
ZONAS = [
    {'id': 'A', 'nome': 'Vilinha', 'cor': '#e41a1c',
     'limites': 'Além da rodovia: Cidade Alta, Júlio Bucci, São João, São Francisco'},
    {'id': 'B', 'nome': 'Gruta / Nova Orlândia', 'cor': '#ff7f00',
     'limites': 'Sudoeste, da Avenida 13 em diante'},
    {'id': 'C', 'nome': 'Centro Sul', 'cor': '#377eb8',
     'limites': 'Avenidas 1 a 12, ruas ímpares (inclui Bandeirantes)'},
    {'id': 'D', 'nome': 'Centro Norte', 'cor': '#984ea3',
     'limites': 'Avenidas 1 a 12, ruas pares (inclui Teixeira, Prado, Comove, Marcussi)'},
    {'id': 'E', 'nome': 'Boa Vista Oeste', 'cor': '#4daf4a',
     'limites': 'Avenidas A a H, da Rua 1 até a Rua 10'},
    {'id': 'F', 'nome': 'Benini / das Flores', 'cor': '#00a6c8',
     'limites': 'Avenidas A a L, da Rua 12 até a Rua 18'},
    {'id': 'G', 'nome': 'Morada do Sol', 'cor': '#a65628',
     'limites': 'Rua 20 para cima, avenidas E a P'},
    {'id': 'H', 'nome': 'Siena / Max Define / José Luiz Simões', 'cor': '#f781bf',
     'limites': 'Avenidas M a T, da Rua 12 para cima'},
    {'id': 'I', 'nome': 'Brazão / Vista Linda', 'cor': '#6e6e6e',
     'limites': 'Avenidas U a Z e 100, da Rua 12 para cima'},
    {'id': 'J', 'nome': 'Santa Rita', 'cor': '#b89b00',
     'limites': 'Avenidas Q a Z, da Rua 1 até a Rua 10'},
    {'id': 'K', 'nome': 'Boa Vista Leste', 'cor': '#005a3c',
     'limites': 'Avenidas I a P, da Rua 1 até a Rua 10'},
    {'id': 'L', 'nome': 'Parisi / Jequitibá', 'cor': '#6400a0',
     'limites': 'Lado leste, ruas ímpares da 3 em diante e alamedas'},
]
ZONA_POR_ID = {zona['id']: zona for zona in ZONAS}

_lock = threading.Lock()
_indice: dict[str, Any] = {}                  # versão dos dados do atlas -> AddressIndex


def malha(lon: float, lat: float) -> tuple[float, float]:
    """Posição na malha da cidade, em metros a partir da Vigilância: ``u`` leste, ``v`` norte."""
    x, y = (lon - ORIGEM[0]) * _MX, (lat - ORIGEM[1]) * _MY
    return x * _COS + y * _SIN, -x * _SIN + y * _COS


def zona_da_malha(u: float, v: float) -> str:
    if u < 300:                                # lado das avenidas numeradas
        if u < -900 and v > -300:
            return 'A'
        if u < -1050:
            return 'B'
        return 'D' if v >= -1010 else 'C'      # eixo entre a Rua 1 e a Rua 2
    if v < -1140 and u >= 1300:
        return 'L'
    if v >= 90 and 790 <= u < 1960:            # Rua 20 para cima
        return 'G'
    if v >= -390:                              # Rua 12 para cima
        if u < 1570:
            return 'F'
        return 'H' if u < 2400 else 'I'
    if u < 1180:
        return 'E'
    return 'K' if u < 1960 else 'J'


def zona(lon: float, lat: float) -> str:
    return zona_da_malha(*malha(lon, lat))


# --------------------------------------------------------------------------
# Endereços do atlas
# --------------------------------------------------------------------------

def indice_enderecos():
    """Índice de endereços do atlas (``AddressIndex``) ou ``None`` enquanto o atlas prepara os dados.

    No site vem dos artefatos já gravados (sem remontar as camadas, que leva mais de 30 s);
    fica na memória só o índice compacto, por versão dos dados.
    """
    from services import entomologia_atlas_artefatos as artefatos
    from services import entomologia_atlas_editor as editor
    from services.entomologia_dengue_auto import AddressIndex

    versao = artefatos.versao_atual()
    if versao is None:                         # testes e máquina local: caminho direto
        return AddressIndex(editor.layers(False))
    with _lock:
        if versao in _indice:
            return _indice[versao]
        pronto, catalogo = artefatos.enderecos(False), artefatos.catalogo()
        if not pronto or catalogo is None:
            return None
        camadas = {layer['id']: {'origin': {'type': 'cnefe'}, 'features': layer['features']}
                   for layer in json.loads(artefatos.descomprimir(pronto[0]))['layers']}
        for item in catalogo['items']:
            tipo = (item.get('origin') or {}).get('type')
            if item.get('deleted') or item.get('clinical') or tipo not in ('condominium', 'local'):
                continue
            achada = artefatos.camada(item['id'])
            if achada:
                camadas[item['id']] = {**item, 'features': json.loads(artefatos.descomprimir(achada[0][0]))['features']}
        indice = AddressIndex(camadas)
        _indice.clear()
        _indice[versao] = indice
        return indice


# --------------------------------------------------------------------------
# Fila -> dias
# --------------------------------------------------------------------------

def dias_da_fila(casas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dias que o "Criar dia de vacinação" montaria, um após o outro, com a fila nesta ordem."""
    from services.vacina_pmo_service import plan_pmo_day

    restantes, dias = list(casas), []
    while restantes:
        plano = plan_pmo_day(restantes)
        manha, tarde = plano['Manha'], plano['Tarde']
        if not manha and not tarde:            # casa que sozinha passa do teto do dia
            manha = [restantes[0]]
        escolhidas = {id(casa) for casa in manha + tarde}
        dias.append({'Manha': manha, 'Tarde': tarde})
        restantes = [casa for casa in restantes if id(casa) not in escolhidas]
    return dias


def _passos(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])     # anda-se pelas quadras, não em linha reta


def _percurso(casas, inicio):
    """Ordem de visita curta dentro de uma zona: vizinho mais próximo a partir de ``inicio`` e 2-opt."""
    restantes, atual, ordem = list(casas), inicio, []
    while restantes:
        proxima = min(restantes, key=lambda casa: (_passos(atual, casa['_uv']), casa['linha']))
        restantes.remove(proxima)
        ordem.append(proxima)
        atual = proxima['_uv']
    total, melhorou, voltas = len(ordem), True, 0
    while melhorou and voltas < 30:
        melhorou, voltas = False, voltas + 1
        for i in range(total - 1):
            antes = ordem[i - 1]['_uv'] if i else inicio
            for j in range(i + 1, total):
                ganho = _passos(antes, ordem[j]['_uv']) - _passos(antes, ordem[i]['_uv'])
                if j + 1 < total:
                    ganho += _passos(ordem[i]['_uv'], ordem[j + 1]['_uv']) - _passos(ordem[j]['_uv'], ordem[j + 1]['_uv'])
                if ganho < -1e-6:
                    ordem[i:j + 1] = ordem[i:j + 1][::-1]
                    melhorou = True
    return ordem


def ordem_proposta(casas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Zona por zona, na ordem de ``ZONAS``; dentro da zona, pelo caminho mais curto. Sem posição vai ao fim."""
    ordem, atual = [], (0.0, 0.0)
    for item in ZONAS:
        da_zona = [casa for casa in casas if casa['zona'] == item['id']]
        if da_zona:
            trecho = _percurso(da_zona, atual)
            ordem += trecho
            atual = trecho[-1]['_uv']
    return ordem + [casa for casa in casas if not casa['zona']]


def _marcar(casas, dias, campo):
    for numero, dia in enumerate(dias, start=1):
        for turno in ('Manha', 'Tarde'):
            for posicao, casa in enumerate(dia[turno], start=1):
                casa[campo] = {'dia': numero, 'turno': turno, 'ordem': posicao}


# --------------------------------------------------------------------------
# Planilha -> mapa
# --------------------------------------------------------------------------

def montar(values: list[list[Any]], agendadas: set[int], indice) -> dict[str, Any]:
    """Casas da aba com posição, zona e dia previsto. ``agendadas``: linhas já pintadas (fora da fila)."""
    from services import vacina_pmo_service as pmo
    from services.entomologia_dengue_auto import METHOD_LABELS, locate, parse_address

    casas = []
    for indice_linha, bruta in enumerate(values):
        if pmo._is_summary_or_header(bruta):
            continue
        desvio = pmo._row_column_offset(bruta)
        celula = lambda coluna: pmo._cell(bruta, coluna + desvio)
        tutor, rua, numero, complemento, bairro = (celula(c) for c in range(5))
        caes, gatos = pmo._parse_count(celula(7)), pmo._parse_count(celula(8))
        if not tutor or not (rua or celula(5) or celula(6)) or not (caes or gatos or celula(9)):
            continue
        lido = parse_address(f'{rua}, {numero} {complemento}')
        achado = locate(lido, bairro, indice)
        ponto = (achado['geometry'] or {}).get('coordinates')
        casa = {
            'linha': indice_linha + 1, 'tutor': tutor,
            'endereco': ', '.join(p for p in (rua, numero, complemento) if p), 'bairro': bairro,
            'caes': caes, 'gatos': gatos, 'animais': caes + gatos,
            'cluster_planilha': celula(11) if len(celula(11)) <= 2 else '',
            'agendada': (indice_linha + 1) in agendadas,
            'lat': ponto[1] if ponto else None, 'lng': ponto[0] if ponto else None,
            'zona': '', 'metodo': METHOD_LABELS.get(achado['method'], achado['method']),
            'confianca': achado['confidence'], 'precisao': achado['precision'],
            'avisos': achado['issues'], 'bairro_atlas': achado['reference_neighborhood'],
            # para a regra do dia (condomínio fica junto) e para o percurso; não vão na resposta
            'dogs': caes, 'cats': gatos, 'cells': [pmo._cell(bruta, c + desvio) for c in range(pmo.PMO_SCHEDULE_SOURCE_COLUMNS)],
        }
        if ponto:
            casa['_uv'] = malha(ponto[0], ponto[1])
            casa['zona'] = zona_da_malha(*casa['_uv'])
        casas.append(casa)

    fila = [casa for casa in casas if not casa['agendada']]
    dias_planilha = dias_da_fila(fila)
    dias_proposta = dias_da_fila(ordem_proposta(fila))
    _marcar(fila, dias_planilha, 'previsao_planilha')
    _marcar(fila, dias_proposta, 'previsao_proposta')

    por_zona = Counter(casa['zona'] for casa in fila if casa['zona'])
    animais_zona = Counter()
    for casa in fila:
        if casa['zona']:
            animais_zona[casa['zona']] += casa['animais']
    no_mapa = sum(1 for casa in fila if casa['lat'] is not None)
    for casa in casas:
        for interno in ('dogs', 'cats', 'cells', '_uv'):
            casa.pop(interno, None)
    return {
        'casas': casas,
        'zonas': [{**item, 'casas': por_zona[item['id']], 'animais': animais_zona[item['id']]} for item in ZONAS],
        'resumo': {
            'casas': len(fila), 'animais': sum(casa['animais'] for casa in fila),
            'no_mapa': no_mapa, 'sem_posicao': len(fila) - no_mapa,
            'confianca_baixa': sum(1 for casa in fila if casa['confianca'] == 'baixa'),
            'ja_agendadas': len(casas) - len(fila),
            'dias_planilha': len(dias_planilha), 'dias_proposta': len(dias_proposta),
            'enderecos_no_atlas': indice.size,
        },
        'origem': {'lat': ORIGEM[1], 'lng': ORIGEM[0]},
    }


def dados_do_mapa() -> dict[str, Any]:
    """Lê a aba "Inscrição a agendar" agora e devolve o que a página do mapa desenha."""
    from services import vacina_pmo_service as pmo
    from time_utils import now_in_brazil

    indice = indice_enderecos()
    if indice is None:
        return {'success': False, 'preparando': True,
                'message': 'O atlas está preparando a base de endereços. Tente de novo em um minuto.'}
    planilha = pmo._extract_google_sheet_id(os.getenv('PMO_VACCINE_SHEET_URL', pmo.DEFAULT_SHEET_URL))
    if not planilha:
        raise RuntimeError('URL/ID da planilha PMO inválido.')
    servico = pmo._get_sheets_service_rw()
    aba = pmo._resolve_pmo_sheet_title(
        servico, planilha,
        os.getenv(pmo.PMO_SCHEDULE_SOURCE_SHEET_TITLE_ENV, pmo.PMO_SCHEDULE_SOURCE_SHEET_DEFAULT_TITLE))
    values = (servico.spreadsheets().values()
              .get(spreadsheetId=planilha, range=f'{pmo._quote_sheet_title(aba)}!A:R')
              .execute().get('values', []))
    agendadas = pmo._pmo_scheduled_source_rows(servico, planilha, aba, len(values))
    resultado = montar(values, agendadas, indice)
    resultado.update(success=True, aba=aba, lido_em=now_in_brazil().strftime('%d/%m/%Y %H:%M'),
                     animais_por_dia=pmo.PMO_DAY_TARGET_ANIMALS)
    return resultado
