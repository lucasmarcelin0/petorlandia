"""Casa a casa: quarteirões e imóveis para o mapa em branco, plano do dia e visitas.

Três peças, todas sem dado de pessoa:

- ``base``: quarteirões da malha de campo e imóveis numerados do atlas, numa
  forma compacta que o aparelho guarda para trabalhar sem internet;
- o **plano**: quais quarteirões serão trabalhados em cada dia e por quem;
- as **visitas**: o resultado de cada imóvel, com os campos do boletim oficial
  "Visita a Imóvel" (os mesmos que ``scripts/import_entomologia.METRICS`` lê).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# Depois deste prazo a visita deixa de colorir o imóvel: é hora de passar de novo.
JANELA_DIAS = 60
# Planos concluídos há até este prazo seguem para o aparelho ("trabalhado por último").
RECENTE_DIAS = 30
LIMITE_LOTE = 300
FUSO = ZoneInfo("America/Sao_Paulo")

# Situação do imóvel, na ordem e com os nomes do boletim oficial.
SITUACOES = {
    "TRABALHADO": "Trabalhado",
    "FECHADO": "Fechado",
    "DESOCUPADO": "Desocupado",
    "TEMPORADA": "Temporada",
    "PARCIAL": "Parcial",
    "RECUSA": "Recusa",
}
INSPECIONADO = {"TRABALHADO", "PARCIAL"}
PENDENCIA = {"FECHADO", "RECUSA", "TEMPORADA"}
# Coluna do arquivo oficial para cada situação.
COLUNA_SITUACAO = {"TRABALHADO": "IM TRAB", "FECHADO": "IM FECH", "DESOCUPADO": "IM DESOC",
                   "TEMPORADA": "IM TEMP", "PARCIAL": "IM PARC", "RECUSA": "IM RECUSA"}

_UUID = re.compile(r"[A-Za-z0-9-]{8,64}")
_IMOVEL = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_CELULA = 0.003          # ~300 m: grade para achar o quarteirão de um ponto sem testar os 946
_TOLERANCIA_M = 30.0     # ponto na calçada, logo fora do polígono, ainda é do quarteirão ao lado

_lock = threading.Lock()
_memo: dict = {}
_VALIDADE_S = 600


# ---------------------------------------------------------------------------
# Base: quarteirões e imóveis
# ---------------------------------------------------------------------------

def _enderecos() -> list:
    """Endereços com número do atlas (CNEFE com as correções da equipe). Sem banco, lista vazia."""
    from services.entomologia_service import consultar_sem_interromper

    def consulta():
        from services import entomologia_atlas_editor as editor
        return [feature for layer in editor.layers(False).values()
                if layer.get("origin", {}).get("type") == "cnefe" for feature in layer["features"]]

    return consultar_sem_interromper(consulta, []) or []


def _assinatura():
    try:
        from services import entomologia_atlas_artefatos as artefatos
        return artefatos.versao_atual()
    except Exception:  # noqa: BLE001 - sem artefatos, a base vale por tempo
        return None


def esquecer_base() -> None:
    with _lock:
        _memo.clear()


def base() -> dict:
    """Quarteirões e imóveis prontos para o aparelho; refeita quando o atlas muda."""
    chave, agora = _assinatura(), time.monotonic()
    with _lock:
        pronto = _memo.get("base")
        if pronto and pronto["chave"] == chave and (chave is not None or agora - pronto["em"] < _VALIDADE_S):
            return pronto["dados"]
    dados = _montar_base()
    with _lock:
        _memo["base"] = {"chave": chave, "em": agora, "dados": dados}
        _memo.pop("indice", None)
    return dados


def indice() -> dict:
    """Consulta rápida do servidor: quarteirão por id e quantos imóveis cada um tem."""
    dados = base()
    with _lock:
        pronto = _memo.get("indice")
        if pronto and pronto["versao"] == dados["versao"]:
            return pronto
    casas = Counter(imovel[6] for imovel in dados["imoveis"])
    pronto = {"versao": dados["versao"],
              "blocos": {bloco["id"]: bloco for bloco in dados["blocos"]},
              "casas": {bloco["id"]: casas.get(posicao, 0) for posicao, bloco in enumerate(dados["blocos"])}}
    with _lock:
        _memo["indice"] = pronto
    return pronto


def _complemento(propriedades: dict) -> str:
    # "Rua Um, 10 · Apartamento 2 · Centro": o meio é o complemento.
    partes = str(propriedades.get("address") or "").split(" · ")
    return " · ".join(partes[1:-1]).strip()[:60] if len(partes) > 2 else ""


def _distancia_m(x: float, y: float, anel: list) -> float:
    """Menor distância, em metros, do ponto às arestas do anel."""
    escala_x = 111_320.0 * math.cos(math.radians(y))
    menor = float("inf")
    for (ax, ay), (bx, by) in zip(anel, anel[1:]):
        px, py = (x - ax) * escala_x, (y - ay) * 110_540.0
        dx, dy = (bx - ax) * escala_x, (by - ay) * 110_540.0
        comprimento = dx * dx + dy * dy
        t = 0.0 if not comprimento else max(0.0, min(1.0, (px * dx + py * dy) / comprimento))
        menor = min(menor, math.hypot(px - t * dx, py - t * dy))
    return menor


def _montar_base() -> dict:
    from services.entomologia_cnefe import inside
    from services.entomologia_service import load_field_territory

    blocos, grade = [], defaultdict(list)
    for feature in load_field_territory()["features"]:
        p, g = feature["properties"], feature["geometry"]
        poligonos = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        poligonos = [[[[round(x, 6), round(y, 6)] for x, y in anel] for anel in poligono] for poligono in poligonos]
        xs = [x for poligono in poligonos for x, _y in poligono[0]]
        ys = [y for poligono in poligonos for _x, y in poligono[0]]
        if not xs:
            continue
        rotulo = p.get("label") or [sum(xs) / len(xs), sum(ys) / len(ys)]
        posicao = len(blocos)
        blocos.append({"id": str(p["source_id"]), "n": str(p["block"]), "s": str(p["sector"]),
                       "d": str(p.get("district") or ""), "c": [round(rotulo[0], 6), round(rotulo[1], 6)],
                       "g": poligonos})
        margem = _CELULA / 8
        for cx in range(int((min(xs) - margem) // _CELULA), int((max(xs) + margem) // _CELULA) + 1):
            for cy in range(int((min(ys) - margem) // _CELULA), int((max(ys) + margem) // _CELULA) + 1):
                grade[(cx, cy)].append(posicao)

    def bloco_do_ponto(x: float, y: float):
        candidatos = grade.get((int(x // _CELULA), int(y // _CELULA)), ())
        for posicao in candidatos:
            if inside([x, y], {"type": "MultiPolygon", "coordinates": blocos[posicao]["g"]}):
                return posicao
        perto = [(min(_distancia_m(x, y, poligono[0]) for poligono in blocos[posicao]["g"]), posicao)
                 for posicao in candidatos]
        distancia, posicao = min(perto, default=(float("inf"), None))
        return posicao if distancia <= _TOLERANCIA_M else None

    utilizaveis = []
    for feature in _enderecos():
        g, p = feature.get("geometry"), feature.get("properties") or {}
        numero = str(p.get("house_number") or "").strip()
        if not g or g.get("type") != "Point" or not numero:
            continue
        utilizaveis.append((feature, p, numero, float(g["coordinates"][0]), float(g["coordinates"][1])))
    repetidos = Counter(str(p.get("cnefe_id") or "") for _f, p, _n, _x, _y in utilizaveis)

    ruas, por_bloco, vistos, usados, fora = {}, defaultdict(list), set(), set(), 0
    for feature, p, numero, x, y in utilizaveis:
        rua = " ".join(str(p.get("street") or "").split()) or "Logradouro não informado"
        complemento = _complemento(p)
        chave = (rua, numero, complemento, round(x, 6), round(y, 6))
        if chave in vistos:
            continue
        vistos.add(chave)
        posicao = bloco_do_ponto(x, y)
        if posicao is None:
            fora += 1
            continue
        # O id precisa ser o mesmo a cada montagem: as visitas apontam para ele.
        cnefe = str(p.get("cnefe_id") or "")
        identificador = cnefe if cnefe and repetidos[cnefe] == 1 else str(feature.get("id") or "").removeprefix("cnefe-")
        if not identificador or not _IMOVEL.fullmatch(identificador):
            identificador = hashlib.sha1(repr(chave).encode()).hexdigest()[:16]
        if identificador in usados:
            identificador = identificador[:60] + "." + hashlib.sha1(repr(chave).encode()).hexdigest()[:8]
        usados.add(identificador)
        por_bloco[posicao].append([identificador, round(x, 6), round(y, 6),
                                   ruas.setdefault(rua, len(ruas)), numero[:20], complemento, posicao])

    # Na ordem da volta no quarteirão: o ângulo em torno do centro dá a sequência de quem caminha.
    imoveis = []
    for posicao in sorted(por_bloco):
        cx, cy = blocos[posicao]["c"]
        escala = math.cos(math.radians(cy))
        imoveis.extend(sorted(por_bloco[posicao],
                              key=lambda casa: (-math.atan2(casa[2] - cy, (casa[1] - cx) * escala), casa[4])))

    dados = {"blocos": blocos, "ruas": list(ruas), "imoveis": imoveis, "sem_quarteirao": fora,
             "janela_dias": JANELA_DIAS}
    dados["versao"] = hashlib.sha1(json.dumps(dados, ensure_ascii=False, sort_keys=True,
                                              separators=(",", ":")).encode()).hexdigest()[:16]
    return dados


# ---------------------------------------------------------------------------
# Estado: plano e visitas, para o mapa ao vivo
# ---------------------------------------------------------------------------

def _inicio_do_dia(dia: date) -> datetime:
    return datetime(dia.year, dia.month, dia.day, tzinfo=FUSO)


def _iso(momento) -> str | None:
    if momento is None:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ZoneInfo("UTC"))
    return momento.astimezone(FUSO).isoformat(timespec="seconds")


def plano_dict(plano) -> dict:
    return {"id": plano.id, "b": plano.bloco, "d": plano.data.isoformat(), "ri": plano.responsavel_id,
            "r": plano.responsavel or "", "c": _iso(plano.concluido_em), "cp": plano.concluido_por or ""}


def visita_dict(visita) -> dict:
    return {
        "i": visita.id, "u": visita.uuid_local, "b": visita.bloco, "m": visita.imovel, "s": visita.situacao,
        "l": int(bool(visita.larvas_encontradas)), "d": visita.data_visita.isoformat(),
        "h": _iso(visita.horario_visita or visita.recebido_em), "ai": visita.agente_id, "a": visita.agente or "",
        "re": visita.recipientes_existentes or 0, "ra": visita.recipientes_agua or 0,
        "rl": visita.recipientes_larva or 0, "t": visita.tubitos or 0,
        "cm": int(bool(visita.controle_mecanico)), "ca": int(bool(visita.controle_alternativo)),
        "tf": int(bool(visita.tratamento_focal)), "rc": int(bool(visita.recuperacao)),
        "o": visita.observacao or "", "lg": visita.logradouro or "", "n": visita.numero or "",
        "cp": visita.complemento or "", "la": visita.latitude, "lo": visita.longitude,
    }


def estado(hoje: date, desde: int = 0) -> dict:
    """Plano em aberto ou recente e as visitas da janela.

    Sem ``desde``, vai a visita mais recente de cada imóvel (o que colore o
    mapa). Com ``desde``, só o que chegou depois: é o que mantém as telas ao vivo.
    """
    from sqlalchemy import case, func, or_
    from extensions import db
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q, EntomologiaVisitaDomiciliar as V

    inicio = hoje - timedelta(days=JANELA_DIAS)
    planos = (Q.query.filter(or_(Q.concluido_em.is_(None), Q.data >= hoje - timedelta(days=RECENTE_DIAS)))
              .order_by(Q.data, Q.id).all())
    na_janela = V.query.filter(V.data_visita >= inicio)
    if desde:
        visitas = na_janela.filter(V.id > desde).order_by(V.id).limit(5000).all()
    else:
        ultimas = {}
        for visita in na_janela.order_by(V.id).all():
            ultimas[visita.imovel] = visita
        visitas = sorted(ultimas.values(), key=lambda visita: visita.id)
    cursor = db.session.query(func.max(V.id)).scalar() or 0

    hoje_sim = case((V.data_visita == hoje, 1), else_=0)
    agentes = {}
    for agente_id, nome, total, do_dia, recuperadas, ultima in (
            db.session.query(V.agente_id, func.max(V.agente), func.count(V.id), func.sum(hoje_sim),
                             func.sum(case((V.recuperacao.is_(True), 1), else_=0)), func.max(V.horario_visita))
            .group_by(V.agente_id).all()):
        agentes[agente_id] = {"id": agente_id, "nome": nome or "", "visitas": int(total or 0),
                              "hoje": int(do_dia or 0), "recuperadas": int(recuperadas or 0),
                              "ultima": _iso(ultima), "quarteiroes": 0, "quarteiroes_hoje": 0}
    concluido_hoje = case((Q.concluido_em >= _inicio_do_dia(hoje), 1), else_=0)
    for agente_id, nome, total, do_dia in (
            db.session.query(Q.concluido_por_id, func.max(Q.concluido_por), func.count(Q.id), func.sum(concluido_hoje))
            .filter(Q.concluido_em.isnot(None)).group_by(Q.concluido_por_id).all()):
        linha = agentes.setdefault(agente_id, {"id": agente_id, "nome": nome or "", "visitas": 0, "hoje": 0,
                                               "recuperadas": 0, "ultima": None})
        linha["quarteiroes"], linha["quarteiroes_hoje"] = int(total or 0), int(do_dia or 0)
    return {"hoje": hoje.isoformat(), "agora": _iso(datetime.now(FUSO)), "cursor": int(cursor),
            "parcial": bool(desde), "planos": [plano_dict(p) for p in planos],
            "visitas": [visita_dict(v) for v in visitas],
            "agentes": sorted(agentes.values(), key=lambda a: (-a["hoje"], -a["visitas"], a["nome"]))}


def equipe(usuario=None) -> list[dict]:
    """Quem pode receber quarteirões: a equipe "Combate à dengue" e quem está planejando."""
    from services.entomologia_acesso import membros_ativos
    from services.entomologia_service import consultar_sem_interromper

    pessoas = {}
    for membro in consultar_sem_interromper(membros_ativos, []) or []:
        pessoas[membro.user_id] = nome_da_conta(membro.user)
    if getattr(usuario, "is_authenticated", False):
        pessoas.setdefault(usuario.id, nome_da_conta(usuario))
    return sorted(({"id": chave, "nome": nome} for chave, nome in pessoas.items()), key=lambda p: p["nome"].lower())


def nome_da_conta(user) -> str:
    return str(getattr(user, "name", "") or getattr(user, "email", "") or "").strip()[:160]


# ---------------------------------------------------------------------------
# Plano do dia (escritório)
# ---------------------------------------------------------------------------

def _data(valor, hoje: date) -> date:
    try:
        return date.fromisoformat(str(valor)[:10]) if valor else hoje
    except ValueError as exc:
        raise ValueError("Data inválida.") from exc


def _blocos_validos(blocos) -> list[dict]:
    conhecidos = indice()["blocos"]
    if not isinstance(blocos, list) or not blocos:
        raise ValueError("Informe ao menos um quarteirão.")
    if len(blocos) > 400:
        raise ValueError("Quarteirões demais de uma vez.")
    validos = [conhecidos[str(bloco)] for bloco in dict.fromkeys(blocos) if str(bloco) in conhecidos]
    if not validos:
        raise ValueError("Quarteirão desconhecido.")
    return validos


def planejar(blocos, dia: date, hoje: date, responsavel, por: str) -> int:
    """Põe os quarteirões no plano do dia (ou troca o responsável dos que já estão)."""
    from extensions import db
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q

    if dia < hoje or dia > hoje + timedelta(days=60):
        raise ValueError("O plano vale de hoje até 60 dias à frente.")
    feitos = 0
    for bloco in _blocos_validos(blocos):
        linha = Q.query.filter_by(bloco=bloco["id"], data=dia).first()
        if linha is None:
            linha = Q(bloco=bloco["id"], setor=bloco["s"], quarteirao=bloco["n"], data=dia, criado_por=por)
            db.session.add(linha)
        elif linha.concluido_em is not None:
            continue
        linha.responsavel_id = getattr(responsavel, "id", None)
        linha.responsavel = nome_da_conta(responsavel) or None
        feitos += 1
    return feitos


def desplanejar(blocos, dia: date) -> int:
    """Tira do plano o que ainda não começou; quarteirão com visita registrada fica."""
    from extensions import db
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q, EntomologiaVisitaDomiciliar as V

    feitos = 0
    for bloco in _blocos_validos(blocos):
        linha = Q.query.filter_by(bloco=bloco["id"], data=dia).first()
        if linha is None or linha.concluido_em is not None:
            continue
        if V.query.filter(V.bloco == bloco["id"], V.data_visita >= dia).first() is not None:
            continue
        db.session.delete(linha)
        feitos += 1
    return feitos


def _plano_aberto(bloco_id: str, ate: date):
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q
    return (Q.query.filter(Q.bloco == bloco_id, Q.concluido_em.is_(None), Q.data <= ate)
            .order_by(Q.data.desc(), Q.id.desc()).first())


def concluir(blocos, hoje: date, usuario) -> int:
    from extensions import db
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q
    from time_utils import utcnow

    feitos, nome = 0, nome_da_conta(usuario)
    for bloco in _blocos_validos(blocos):
        linha = _plano_aberto(bloco["id"], hoje)
        if linha is None:
            linha = Q.query.filter_by(bloco=bloco["id"], data=hoje).first()
            if linha is not None:
                continue            # já concluído hoje
            linha = Q(bloco=bloco["id"], setor=bloco["s"], quarteirao=bloco["n"], data=hoje, criado_por=nome,
                      responsavel_id=usuario.id, responsavel=nome)
            db.session.add(linha)
        linha.concluido_em, linha.concluido_por, linha.concluido_por_id = utcnow(), nome, usuario.id
        feitos += 1
    return feitos


def reabrir(blocos, hoje: date) -> int:
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q

    feitos = 0
    for bloco in _blocos_validos(blocos):
        linha = (Q.query.filter(Q.bloco == bloco["id"], Q.concluido_em.isnot(None),
                                Q.data >= hoje - timedelta(days=RECENTE_DIAS))
                 .order_by(Q.data.desc(), Q.id.desc()).first())
        if linha is None or _plano_aberto(bloco["id"], hoje) is not None:
            continue
        linha.concluido_em = linha.concluido_por = linha.concluido_por_id = None
        feitos += 1
    return feitos


# ---------------------------------------------------------------------------
# Visitas (rua)
# ---------------------------------------------------------------------------

def _inteiro(valor, campo: str) -> int:
    try:
        numero = int(valor or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Número inválido em {campo}.") from exc
    if not 0 <= numero <= 999:
        raise ValueError(f"{campo}: use um número de 0 a 999.")
    return numero


def _coordenada(valor, minimo: float, maximo: float):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) and minimo <= numero <= maximo else None


def validar_visita(item, blocos: dict, hoje: date) -> dict:
    """Campos de uma visita prontos para gravar; ``ValueError`` diz o que recusar."""
    if not isinstance(item, dict):
        raise ValueError("Visita em formato inválido.")
    uuid_local = str(item.get("uuid") or "")
    if not _UUID.fullmatch(uuid_local):
        raise ValueError("Identificador da visita inválido.")
    bloco = blocos.get(str(item.get("bloco") or ""))
    if bloco is None:
        raise ValueError("Quarteirão desconhecido.")
    imovel = str(item.get("imovel") or "")
    if not _IMOVEL.fullmatch(imovel):
        raise ValueError("Imóvel inválido.")
    situacao = str(item.get("situacao") or "").upper()
    if situacao not in SITUACOES:
        raise ValueError("Situação do imóvel inválida.")
    dia = _data(item.get("data"), hoje)
    if dia > hoje + timedelta(days=1) or dia < hoje - timedelta(days=JANELA_DIAS):
        raise ValueError("Data da visita fora do período aceito.")
    horario = None
    try:
        horario = datetime.fromisoformat(str(item.get("horario") or "").replace("Z", "+00:00"))
        if horario.tzinfo is None:
            horario = horario.replace(tzinfo=FUSO)
    except ValueError:
        horario = None

    inspecionado = situacao in INSPECIONADO
    existentes = _inteiro(item.get("recipientes_existentes"), "recipientes existentes") if inspecionado else 0
    com_agua = _inteiro(item.get("recipientes_agua"), "recipientes com água") if inspecionado else 0
    com_larva = _inteiro(item.get("recipientes_larva"), "recipientes com larva") if inspecionado else 0
    # No boletim, existentes >= com água >= com larva.
    com_agua = max(com_agua, com_larva)
    existentes = max(existentes, com_agua)
    return {
        "uuid_local": uuid_local, "bloco": bloco["id"], "setor": bloco["s"], "quarteirao": bloco["n"],
        "imovel": imovel, "situacao": situacao, "data_visita": dia, "horario_visita": horario,
        "logradouro": " ".join(str(item.get("logradouro") or "").split())[:200] or None,
        "numero": str(item.get("numero") or "").strip()[:50] or None,
        "complemento": str(item.get("complemento") or "").strip()[:80] or None,
        "latitude": _coordenada(item.get("lat"), -90, 90), "longitude": _coordenada(item.get("lng"), -180, 180),
        "recipientes_existentes": existentes, "recipientes_agua": com_agua, "recipientes_larva": com_larva,
        "larvas_encontradas": inspecionado and (bool(item.get("larvas")) or com_larva > 0),
        "tubitos": _inteiro(item.get("tubitos"), "tubitos") if inspecionado else 0,
        "controle_mecanico": inspecionado and bool(item.get("controle_mecanico")),
        "controle_alternativo": inspecionado and bool(item.get("controle_alternativo")),
        "tratamento_focal": inspecionado and bool(item.get("tratamento_focal")),
        "observacao": str(item.get("observacao") or "").strip()[:1000] or None,
    }


def registrar_visitas(itens, usuario, hoje: date) -> dict:
    """Grava o lote vindo do aparelho. Reenviar a mesma visita não duplica."""
    from extensions import db
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q, EntomologiaVisitaDomiciliar as V

    if not isinstance(itens, list) or not itens:
        raise ValueError("Nenhuma visita informada.")
    if len(itens) > LIMITE_LOTE:
        raise ValueError(f"Envie até {LIMITE_LOTE} visitas por vez.")
    blocos = indice()["blocos"]
    nome = nome_da_conta(usuario)
    enviados = [str(item.get("uuid") or "") for item in itens if isinstance(item, dict)]
    existentes = {uuid for (uuid,) in V.query.with_entities(V.uuid_local).filter(V.uuid_local.in_(enviados)).all()}
    aceitas, recusadas, novas = [], [], 0
    for item in itens:
        try:
            dados = validar_visita(item, blocos, hoje)
        except ValueError as exc:
            recusadas.append({"uuid": str(item.get("uuid") or "") if isinstance(item, dict) else "",
                              "motivo": str(exc)})
            continue
        aceitas.append(dados["uuid_local"])
        if dados["uuid_local"] in existentes:
            continue
        existentes.add(dados["uuid_local"])
        anterior = (V.query.filter(V.imovel == dados["imovel"], V.bloco == dados["bloco"],
                                   V.data_visita >= hoje - timedelta(days=JANELA_DIAS))
                    .order_by(V.id.desc()).first())
        recuperacao = bool(anterior and anterior.situacao in PENDENCIA and dados["situacao"] in INSPECIONADO)
        db.session.add(V(**dados, recuperacao=recuperacao, agente_id=usuario.id, agente=nome))
        novas += 1
        # Todo quarteirão trabalhado tem a sua linha no plano, mesmo quando não foi planejado.
        if (_plano_aberto(dados["bloco"], dados["data_visita"]) is None
                and Q.query.filter_by(bloco=dados["bloco"], data=dados["data_visita"]).first() is None):
            db.session.add(Q(bloco=dados["bloco"], setor=dados["setor"], quarteirao=dados["quarteirao"],
                             data=dados["data_visita"], responsavel_id=usuario.id, responsavel=nome,
                             criado_por=nome))
            db.session.flush()
    return {"aceitas": aceitas, "recusadas": recusadas, "novas": novas}


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------

def _visitas_do_periodo(inicio: date, fim: date):
    from models.entomologia import EntomologiaVisitaDomiciliar as V
    return (V.query.filter(V.data_visita >= inicio, V.data_visita <= fim)
            .order_by(V.data_visita, V.setor, V.quarteirao, V.id).all())


def _csv(cabecalho: list[str], linhas) -> str:
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(cabecalho)
    escritor.writerows(linhas)
    return saida.getvalue()


def visitas_csv(inicio: date, fim: date) -> str:
    """Uma linha por visita, com todos os campos registrados na rua."""
    sim = lambda valor: "SIM" if valor else "NAO"
    return _csv(
        ["DATA", "HORA", "SETOR", "QUARTEIRAO", "LOGRADOURO", "NUMERO", "COMPLEMENTO", "SITUACAO",
         "REC. EXIST.", "REC. AGUA", "REC. LARVA", "IM. LARVA", "TUBITOS", "IM MECANICO", "IM ALTERNATIVO",
         "IM FOCAL", "RECUPERACAO", "AGENTE", "OBSERVACAO"],
        ([v.data_visita.isoformat(), (_iso(v.horario_visita) or "")[11:16], v.setor, v.quarteirao,
          v.logradouro or "", v.numero or "", v.complemento or "", SITUACOES.get(v.situacao, v.situacao),
          v.recipientes_existentes, v.recipientes_agua, v.recipientes_larva, sim(v.larvas_encontradas), v.tubitos,
          sim(v.controle_mecanico), sim(v.controle_alternativo), sim(v.tratamento_focal), sim(v.recuperacao),
          v.agente or "", " ".join((v.observacao or "").split())]
         for v in _visitas_do_periodo(inicio, fim)))


COLUNAS_BOLETIM = ["IM TRAB", "IM FECH", "IM DESOC", "IM TEMP", "IM PARC", "IM RECUSA", "IM. LARVA",
                   "IM MECANICO", "IM ALTERNATIVO", "IM FOCAL", "REC. EXIST.", "REC. AGUA", "REC. LARVA"]


def boletim(inicio: date, fim: date) -> list[dict]:
    """Totais por dia e quarteirão, nas colunas do arquivo oficial. Vale a última visita do imóvel no dia."""
    ultimas = {}
    for visita in _visitas_do_periodo(inicio, fim):
        ultimas[(visita.data_visita, visita.bloco, visita.imovel)] = visita
    linhas: dict = {}
    for (dia, bloco, _imovel), v in ultimas.items():
        linha = linhas.setdefault((dia, v.setor, v.quarteirao, bloco),
                                  {"DATA": dia.isoformat(), "SETOR": v.setor, "QUARTEIRAO": v.quarteirao,
                                   **{coluna: 0 for coluna in COLUNAS_BOLETIM}})
        linha[COLUNA_SITUACAO[v.situacao]] += 1
        linha["IM. LARVA"] += bool(v.larvas_encontradas)
        linha["IM MECANICO"] += bool(v.controle_mecanico)
        linha["IM ALTERNATIVO"] += bool(v.controle_alternativo)
        linha["IM FOCAL"] += bool(v.tratamento_focal)
        linha["REC. EXIST."] += v.recipientes_existentes or 0
        linha["REC. AGUA"] += v.recipientes_agua or 0
        linha["REC. LARVA"] += v.recipientes_larva or 0
    return [linhas[chave] for chave in sorted(linhas, key=lambda c: (c[0], c[1], c[2], c[3]))]


def boletim_csv(inicio: date, fim: date) -> str:
    cabecalho = ["DATA", "SETOR", "QUARTEIRAO", *COLUNAS_BOLETIM]
    return _csv(cabecalho, ([linha[coluna] for coluna in cabecalho] for linha in boletim(inicio, fim)))
