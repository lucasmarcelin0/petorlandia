"""Regras do acompanhamento de tratamento.

Interpreta a posologia em texto livre da receita (frequência/duração) para
pré-gerar a agenda de administrações. A ativação pelo veterinário é um clique:
o que não for interpretável com confiança vira item de registro livre, nunca
bloqueia com formulário.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

from time_utils import now_in_brazil

from models import (
    AdministracaoRegistro,
    ItemTratamento,
    TratamentoAcompanhamento,
    db,
)

# Doses geradas no máximo por item: evita agendas absurdas quando a duração
# vem exagerada ("por 90 dias" TID = 270 doses ainda cabe; acima disso trunca).
MAX_DOSES_POR_ITEM = 300

# Tratamento contínuo com intervalo conhecido: gera 30 dias de agenda.
DIAS_AGENDA_USO_CONTINUO = 30


def _normalizar(texto: str | None) -> str:
    if not texto:
        return ''
    # Fast path: pure ASCII strings do not contain combining characters, so unicodedata NFKD decomposition can be bypassed.
    if texto.isascii():
        return texto.lower().strip()
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(ch for ch in texto if not unicodedata.combining(ch))
    return texto.lower().strip()


# Siglas veterinárias usuais e suas variantes por extenso.
_FREQ_SIGLAS = {
    'sid': 24,
    'qd': 24,
    'bid': 12,
    'tid': 8,
    'qid': 6,
}

# Performance optimization: pre-compile regexes at module load time to prevent repeated compilation on hot paths.
_RE_SIGLAS = {sigla: re.compile(rf'\b{sigla}\b') for sigla in _FREQ_SIGLAS}
_RE_A_CADA_HORAS = re.compile(r'(?:a\s+)?cada\s+(\d{1,3})\s*(hora|h\b|hrs?)')
_RE_DE_X_EM_X_HORAS = re.compile(r'de\s+(\d{1,3})\s+em\s+\d{1,3}\s*(?:hora|h\b|hrs?)?')
_RE_X_SLASH_X_HORAS = re.compile(r'\b(\d{1,3})\s*/\s*(\d{1,3})\s*(?:hora|h\b|hrs?)?')
_RE_A_CADA_DIAS = re.compile(r'(?:a\s+)?cada\s+(\d{1,2})\s*dias?')
_RE_VEZES_DIA = re.compile(r'\b(\d{1,2})\s*(?:x|vez(?:es)?)\s*(?:ao|por|/|no)?\s*dia')
_RE_VEZES_SEMANA = re.compile(r'\b(\d{1,2})\s*(?:x|vez(?:es)?)\s*(?:ao|por|/|na)?\s*semana')
_RE_SEMANAL = re.compile(r'\bsemanal(?:mente)?\b')
_RE_UMA_VEZ_DIA = re.compile(r'\buma\s+vez\s+(?:ao|por)\s+dia\b|\bdiariamente\b|\btodos\s+os\s+dias\b|\b1\s+vez\s+(?:ao|por)\s+dia\b')

_RE_DURACAO_DIAS = re.compile(r'\b(\d{1,3})\s*dias?\b')
_RE_DURACAO_SEMANAS = re.compile(r'\b(\d{1,2})\s*semanas?\b')
_RE_DURACAO_MESES = re.compile(r'\b(\d{1,2})\s*m(?:e|ê)s(?:es)?\b')
_RE_UMA_SEMANA = re.compile(r'\buma\s+semana\b')
_RE_DOSE_UNICA = re.compile(r'\bdose\s+unica\b|\bunica\s+dose\b|\baplicacao\s+unica\b')

_RE_USO_CONTINUO = re.compile(r'\bcontinuo\b|\buso\s+continuo\b|\bcontinuamente\b')


def parse_intervalo_horas(frequencia: str | None) -> int | None:
    """Extrai o intervalo entre doses (em horas) do texto de frequência.

    Retorna None quando não há interpretação confiável.
    """
    texto = _normalizar(frequencia)
    if not texto:
        return None

    for sigla, pattern in _RE_SIGLAS.items():
        if pattern.search(texto):
            return _FREQ_SIGLAS[sigla]

    # "a cada 12 horas", "cada 8h", "de 8 em 8 horas", "12/12h", "12-12h"
    m = _RE_A_CADA_HORAS.search(texto)
    if m:
        return int(m.group(1))
    m = _RE_DE_X_EM_X_HORAS.search(texto)
    if m:
        return int(m.group(1))
    m = _RE_X_SLASH_X_HORAS.search(texto)
    if m and m.group(1) == m.group(2):
        return int(m.group(1))

    # "a cada 2 dias", "cada 3 dias"
    m = _RE_A_CADA_DIAS.search(texto)
    if m:
        return int(m.group(1)) * 24

    # "2x ao dia", "3 vezes por dia", "1x/dia"
    m = _RE_VEZES_DIA.search(texto)
    if m:
        vezes = int(m.group(1))
        if 1 <= vezes <= 24:
            return round(24 / vezes)

    # "1x por semana", "semanal", "2 vezes por semana"
    m = _RE_VEZES_SEMANA.search(texto)
    if m:
        vezes = int(m.group(1))
        if 1 <= vezes <= 7:
            return round(168 / vezes)
    if _RE_SEMANAL.search(texto):
        return 168

    # "uma vez ao dia", "diariamente", "todos os dias"
    if _RE_UMA_VEZ_DIA.search(texto):
        return 24

    return None


def parse_duracao_dias(duracao: str | None) -> int | None:
    """Extrai a duração do tratamento em dias. None = não interpretável/contínuo."""
    texto = _normalizar(duracao)
    if not texto:
        return None

    m = _RE_DURACAO_DIAS.search(texto)
    if m:
        return int(m.group(1))
    m = _RE_DURACAO_SEMANAS.search(texto)
    if m:
        return int(m.group(1)) * 7
    m = _RE_DURACAO_MESES.search(texto)
    if m:
        return int(m.group(1)) * 30
    if _RE_UMA_SEMANA.search(texto):
        return 7
    if _RE_DOSE_UNICA.search(texto):
        return 1
    return None


def eh_uso_continuo(duracao: str | None) -> bool:
    texto = _normalizar(duracao)
    return bool(_RE_USO_CONTINUO.search(texto))


def gerar_agenda(inicio: datetime, intervalo_horas: int, duracao_dias: int) -> list[datetime]:
    """Horários previstos a partir de ``inicio``, limitados a MAX_DOSES_POR_ITEM."""
    if intervalo_horas <= 0 or duracao_dias <= 0:
        return []
    fim = inicio + timedelta(days=duracao_dias)
    horarios = []
    atual = inicio
    while atual < fim and len(horarios) < MAX_DOSES_POR_ITEM:
        horarios.append(atual)
        atual = atual + timedelta(hours=intervalo_horas)
    return horarios


def criar_acompanhamento(bloco, usuario, inicio: datetime) -> TratamentoAcompanhamento:
    """Cria o acompanhamento de um bloco com itens e agenda pré-gerados.

    Não faz commit; o chamador decide a transação.
    """
    acompanhamento = TratamentoAcompanhamento(
        bloco_id=bloco.id,
        animal_id=bloco.animal_id,
        criado_por_id=getattr(usuario, 'id', None),
        data_inicio=inicio,
    )
    db.session.add(acompanhamento)
    db.session.flush()

    for prescricao in bloco.prescricoes:
        intervalo = parse_intervalo_horas(prescricao.frequencia)
        duracao = parse_duracao_dias(prescricao.duracao)
        if intervalo and not duracao and eh_uso_continuo(prescricao.duracao):
            duracao = DIAS_AGENDA_USO_CONTINUO

        item = ItemTratamento(
            acompanhamento_id=acompanhamento.id,
            prescricao_id=prescricao.id,
        )
        if intervalo and duracao:
            item.modo = 'agendado'
            item.intervalo_horas = intervalo
            item.duracao_dias = duracao
            db.session.add(item)
            db.session.flush()
            for horario in gerar_agenda(inicio, intervalo, duracao):
                db.session.add(AdministracaoRegistro(
                    item_id=item.id,
                    prevista_para=horario,
                    status='pendente',
                ))
        else:
            item.modo = 'livre'
            item.intervalo_horas = intervalo
            item.duracao_dias = duracao
            db.session.add(item)

    return acompanhamento


def resumo_progresso(acompanhamento) -> dict:
    """Progresso agregado dos itens agendados (para barra geral e visão do vet)."""
    previstas = feitas = puladas = atrasadas = 0
    agora = None
    for item in acompanhamento.itens:
        for registro in item.registros:
            if registro.prevista_para is None:
                continue
            previstas += 1
            if registro.status == 'feita':
                feitas += 1
            elif registro.status == 'pulada':
                puladas += 1
            elif registro.status == 'pendente':
                if agora is None:
                    agora = now_in_brazil()
                prevista = registro.prevista_para
                if prevista.tzinfo is None:
                    prevista = prevista.replace(tzinfo=agora.tzinfo)
                if prevista < agora:
                    atrasadas += 1
    percentual = round(100 * feitas / previstas) if previstas else None
    return {
        'previstas': previstas,
        'feitas': feitas,
        'puladas': puladas,
        'atrasadas': atrasadas,
        'percentual': percentual,
    }
