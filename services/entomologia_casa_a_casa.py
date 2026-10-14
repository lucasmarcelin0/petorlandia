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

# Quarteirão dividido entre duas pessoas: cada uma faz um L, os dois lados em torno de um canto.
# Os Ls de uma divisão são sempre opostos (NE + SO ou NO + SE).
PARTES = {"NE": "SO", "SO": "NE", "NO": "SE", "SE": "NO"}
NOME_PARTE = {"NE": "L Nordeste", "NO": "L Noroeste", "SE": "L Sudeste", "SO": "L Sudoeste"}
# O que a equipe faz no quarteirão, escolhido no escritório ao planejar.
ATIVIDADES = {
    "ADL": "Avaliação de densidade larvária",
    "VI_ROTINA": "Visita a imóveis · rotina",
    "VI_PENDENCIA": "Visita a imóveis · pendência",
    "CC_ROTINA": "Controle de criadouro · rotina",
    "CC_PENDENCIA": "Controle de criadouro · pendência",
}
# Controle feito em cada recipiente e larvicida do tratamento focal.
CONTROLES = {"M": "Mecânico", "A": "Alternativo", "F": "Focal"}
PRODUTOS_FOCAL = {"NATULAR": "Natular", "VECTOBAC": "Vectobac"}

# Tipo de recipiente, com os grupos e a numeração da ficha de campo do SISAWEB (1 a 40).
GRUPOS_RECIPIENTE = (
    ("A", "Depósito elevado", ((1, "Ligado à rede"), (2, "Não ligado à rede"))),
    ("B", "Depósito não elevado", ((3, "Ligado à rede"), (4, "Não ligado à rede"))),
    ("C", "Móveis", ((5, "Vaso de planta na água"), (6, "Vasos de planta (diversos)"), (7, "Prato / pingadeira"),
                     (8, "Consumo animal"), (9, "Depósito p/ construção"), (10, "Depósito p/ horticultura"),
                     (11, "Piscina desmontável"), (12, "Lata, frasco, plástico utilizáveis"),
                     (13, "Garrafas retornáveis"), (14, "Balde / regador"), (15, "Bandeja geladeira / ar cond."),
                     (16, "Material de construção"), (17, "Outros"))),
    ("D", "Fixos", ((18, "Ralo interno"), (19, "Ralo externo"), (20, "Laje"), (21, "Calha"),
                    (22, "Vaso sanitário / cx. descarga"), (23, "Piscina"), (24, "Depósito p/ construção"),
                    (25, "Depósito p/ horticultura"), (26, "Consumo animal"), (27, "Outros"))),
    ("E", "Pneus", ((28, "Pneu"), (29, "Outros correlatos"))),
    ("F", "Passíveis remoção / alteração", ((30, "Lata, frasco, plástico"), (31, "Garrafa descartável"),
                                            (32, "Lona, encerado, plástico"), (33, "Entulho de construção"),
                                            (34, "Peças / sucatas"), (35, "Masseira"), (36, "Barco"),
                                            (37, "Outros"))),
    ("G", "Naturais", ((38, "Oco de árvore e bambu"), (39, "Bromélias"), (40, "Outros"))),
)
TIPOS_RECIPIENTE = {numero: (grupo, nome) for grupo, _titulo, tipos in GRUPOS_RECIPIENTE for numero, nome in tipos}


def grupos_recipiente() -> list[dict]:
    """Os tipos de recipiente no formato da tela (vai na página, então vale sem internet)."""
    return [{"g": grupo, "nome": titulo, "tipos": [[numero, nome] for numero, nome in tipos]}
            for grupo, titulo, tipos in GRUPOS_RECIPIENTE]

_UUID = re.compile(r"[A-Za-z0-9-]{8,64}")
_IMOVEL = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_CELULA = 0.003          # ~300 m: grade para achar o quarteirão de um ponto sem testar os 946
_PASSO_NOME_M = 70.0     # um ponto para o nome da rua a cada tanto, ao longo do eixo
_PASSO_RODOVIA_M = 240.0  # rodovia é comprida e vista de longe: basta um nome a cada quadra grande
# Vias principais primeiro: quando os nomes disputam espaço na tela, elas ganham.
_ORDEM_DAS_VIAS = ("motorway", "trunk", "primary", "secondary", "tertiary")
_TOLERANCIA_M = 30.0     # ponto na calçada, logo fora do polígono, ainda é do quarteirão ao lado

_lock = threading.Lock()
_memo: dict = {}
_VALIDADE_S = 600
_CONFERIR_S = 30         # de quanto em quanto tempo olhar se o atlas mudou


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


def _assinatura_campo():
    """Muda quando um imóvel é acrescentado (ou retirado) em campo: a base é refeita."""
    from services.entomologia_service import consultar_sem_interromper

    def consulta():
        from sqlalchemy import func
        from extensions import db
        from models.entomologia import EntomologiaImovelCampo as C
        total, maior, retirados = db.session.query(func.count(C.id), func.max(C.id),
                                                   func.count(C.removido_em)).one()
        return f"{total}-{maior or 0}-{retirados}"

    return consultar_sem_interromper(consulta, "")


def _imoveis_campo() -> list:
    from services.entomologia_service import consultar_sem_interromper

    def consulta():
        from models.entomologia import EntomologiaImovelCampo as C
        return [(c.imovel, c.bloco, c.logradouro, c.numero, c.complemento or "", c.longitude, c.latitude)
                for c in C.query.filter(C.removido_em.is_(None)).order_by(C.id).all()]

    return consultar_sem_interromper(consulta, []) or []


def esquecer_base() -> None:
    with _lock:
        _memo.clear()


def base() -> dict:
    """Quarteirões e imóveis prontos para o aparelho; refeita quando o atlas muda."""
    agora = time.monotonic()
    with _lock:
        pronto = _memo.get("base")
        if pronto and agora - pronto["conferido"] < _CONFERIR_S:
            return pronto["dados"]
    atlas = _assinatura()
    chave = (atlas, _assinatura_campo())
    with _lock:
        pronto = _memo.get("base")
        if pronto and pronto["chave"] == chave and (atlas is not None or agora - pronto["em"] < _VALIDADE_S):
            pronto["conferido"] = agora
            return pronto["dados"]
    dados = _montar_base()
    with _lock:
        _memo["base"] = {"chave": chave, "em": agora, "conferido": agora, "dados": dados}
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


def nome_de_rua(nome: object) -> str:
    """O nome como aparece na lista de casas: "Rua Vinte e Seis" vira "Rua 26"."""
    from services.entomologia_cnefe import street_number

    nome = " ".join(str(nome or "").split())
    tipo, _, resto = nome.partition(" ")
    if resto:
        numero = street_number(resto)
        if numero != resto:
            return f"{tipo} {numero}"
    return nome


def _vias() -> dict:
    """Onde escrever o nome de cada rua no mapa em branco.

    Sai dos eixos de rua do atlas (OpenStreetMap, ``atlas-referencias/lugares.json``),
    que fazem parte do projeto: vale também sem internet. Cada ponto leva o
    ângulo do trecho, já pronto para girar o texto na tela e sempre legível
    (nunca de cabeça para baixo).
    """
    from services import entomologia_atlas_editor as editor
    from services.entomologia_atlas_malha import NOT_BUILT

    nomes, pontos, linhas = {}, [], []
    ruas = []
    for feature in editor.references().get("features", []):
        p, g = feature.get("properties") or {}, feature.get("geometry") or {}
        categoria = str(p.get("category") or "").lower()
        nome = nome_de_rua(p.get("name") or p.get("label"))
        if g.get("type") != "LineString" or not nome or categoria in NOT_BUILT:
            continue
        ordem = _ORDEM_DAS_VIAS.index(categoria) if categoria in _ORDEM_DAS_VIAS else len(_ORDEM_DAS_VIAS)
        ruas.append((ordem, nome, g["coordinates"]))
    for ordem, nome, linha in sorted(ruas, key=lambda rua: rua[0]):
        indice_nome = nomes.setdefault(nome, len(nomes))
        # Os eixos completos permitem identificar também uma lateral sem casas.
        linhas.append([indice_nome, [[round(x, 6), round(y, 6)] for x, y in linha]])
        passo = _PASSO_RODOVIA_M if ordem < 3 else _PASSO_NOME_M
        trechos, total = [], 0.0
        for (ax, ay), (bx, by) in zip(linha, linha[1:]):
            dx = (bx - ax) * 111_320.0 * math.cos(math.radians((ay + by) / 2))
            dy = (by - ay) * 110_540.0
            comprimento = math.hypot(dx, dy)
            if comprimento:
                trechos.append((total, comprimento, ax, ay, bx, by, dx, dy))
                total += comprimento
        if total < 25:
            continue
        alvo = min(passo / 2, total / 2)
        for inicio, comprimento, ax, ay, bx, by, dx, dy in trechos:
            while alvo <= inicio + comprimento:
                t = (alvo - inicio) / comprimento
                # Na tela o eixo y cresce para baixo: o giro em CSS é o ângulo do trecho com o sinal trocado.
                giro = -math.degrees(math.atan2(dy, dx))
                giro = giro - 180 if giro > 90 else (giro + 180 if giro < -90 else giro)
                pontos.append([round(ax + (bx - ax) * t, 6), round(ay + (by - ay) * t, 6), round(giro),
                               indice_nome])
                alvo += passo
    return {"nomes": list(nomes), "pontos": pontos, "linhas": linhas}


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

    # Imóveis que faltavam na base oficial e a equipe acrescentou em campo: fazem parte do mapa daí em diante.
    posicao_do_bloco = {bloco["id"]: posicao for posicao, bloco in enumerate(blocos)}
    for identificador, bloco_id, rua, numero, complemento, x, y in _imoveis_campo():
        posicao = posicao_do_bloco.get(bloco_id)
        if posicao is None or identificador in usados:
            continue
        usados.add(identificador)
        por_bloco[posicao].append([identificador, round(x, 6), round(y, 6), ruas.setdefault(rua, len(ruas)),
                                   str(numero)[:20], complemento[:60], posicao])

    # Na ordem da volta no quarteirão: o ângulo em torno do centro dá a sequência de quem caminha.
    imoveis = []
    for posicao in sorted(por_bloco):
        cx, cy = blocos[posicao]["c"]
        escala = math.cos(math.radians(cy))
        imoveis.extend(sorted(por_bloco[posicao],
                              key=lambda casa: (-math.atan2(casa[2] - cy, (casa[1] - cx) * escala), casa[4])))

    dados = {"blocos": blocos, "ruas": list(ruas), "imoveis": imoveis, "sem_quarteirao": fora,
             "janela_dias": JANELA_DIAS, "vias": _vias()}
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
            "r": plano.responsavel or "", "c": _iso(plano.concluido_em), "cp": plano.concluido_por or "",
            "v": _iso(plano.atualizado_em), "pt": plano.parte or "", "at": plano.atividade or ""}


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
        "rt": recipientes_da_visita(visita), "fp": visita.focal_produto or "", "at": visita.atividade or "",
    }


def recipientes_da_visita(visita) -> list[dict]:
    try:
        lista = json.loads(getattr(visita, "recipientes_json", None) or "[]")
    except ValueError:
        return []
    return lista if isinstance(lista, list) else []


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


class ConflitoPlano(ValueError):
    pass


def _linhas_do_dia(bloco_id: str, dia: date, travar: bool = False) -> list:
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q
    consulta = Q.query.filter_by(bloco=bloco_id, data=dia).order_by(Q.id)
    return (consulta.with_for_update() if travar else consulta).all()


def _atividade(valor):
    """Atividade escolhida no escritório; vazio ou desconhecido vira ``None``."""
    valor = str(valor or "").strip().upper()
    return valor if valor in ATIVIDADES else None


def conferir_plano(blocos, dia, esperado):
    """Valida a fotografia apresentada na tela antes de alterar o lote inteiro.

    A fotografia traz uma entrada por linha do plano (duas quando o quarteirão está
    dividido em L) e uma entrada só com ``b`` para quarteirão livre no dia.
    """
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q
    ids = {b['id'] for b in _blocos_validos(blocos)}
    if not isinstance(esperado, list) or any(not isinstance(p, dict) or not isinstance(p.get('b'), str) for p in esperado):
        raise ValueError('Conferência do plano inválida.')
    if {p.get('b') for p in esperado} != ids:
        raise ValueError('Conferência incompleta do plano.')
    atuais = defaultdict(set)
    for linha in Q.query.filter(Q.bloco.in_(ids), Q.data == dia).with_for_update().all():
        p = plano_dict(linha)
        atuais[linha.bloco].add((p['pt'], p['id'], p['ri'], p['c'], p['v']))
    vistos = defaultdict(set)
    for previa in esperado:
        if previa.get('id') is not None:
            vistos[previa['b']].add((previa.get('pt') or '', previa.get('id'), previa.get('ri'), previa.get('c'),
                                     previa.get('v')))
    if any(vistos.get(b, set()) != atuais.get(b, set()) for b in ids):
        raise ConflitoPlano('O plano mudou em outro aparelho. Confira a agenda atualizada e aplique novamente.')


def reagendar(blocos, origem, destino, hoje, responsavel):
    """Move o lote sem apagar serviço realizado nem sobrescrever o destino.

    Quarteirão dividido em L muda de dia com as duas metades e os mesmos responsáveis.
    """
    from models.entomologia import EntomologiaVisitaDomiciliar as V
    if destino < hoje or destino > hoje + timedelta(days=60) or origem == destino:
        raise ValueError('Escolha uma nova data entre hoje e 60 dias à frente.')
    grupos = []
    for bloco in _blocos_validos(blocos):
        linhas = _linhas_do_dia(bloco['id'], origem, travar=True)
        if (not linhas or any(linha.concluido_em for linha in linhas)
                or V.query.filter(V.bloco == bloco['id'], V.data_visita >= origem).first()):
            raise ValueError('Só é possível reagendar quarteirões que ainda não começaram.')
        if _linhas_do_dia(bloco['id'], destino):
            raise ConflitoPlano('Já existe um plano para esse quarteirão na data de destino. Confira a agenda.')
        grupos.append(linhas)
    for linhas in grupos:
        for linha in linhas:
            linha.data = destino
            if len(linhas) == 1:
                linha.responsavel_id = getattr(responsavel, 'id', None)
                linha.responsavel = nome_da_conta(responsavel) or None
    return len(grupos)


def planejar(blocos, dia: date, hoje: date, responsavel, por: str, atividade=None) -> int:
    """Põe os quarteirões no plano do dia (ou troca o responsável dos que já estão).

    Quarteirão dividido em L volta a ser inteiro, do responsável escolhido.
    """
    from extensions import db
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q

    if dia < hoje or dia > hoje + timedelta(days=60):
        raise ValueError("O plano vale de hoje até 60 dias à frente.")
    atividade = _atividade(atividade)
    feitos = 0
    for bloco in _blocos_validos(blocos):
        linhas = _linhas_do_dia(bloco["id"], dia)
        if any(linha.concluido_em is not None for linha in linhas):
            continue
        if not linhas:
            linha = Q(bloco=bloco["id"], setor=bloco["s"], quarteirao=bloco["n"], data=dia, criado_por=por, parte="")
            db.session.add(linha)
        else:
            linha = linhas[0]
            for sobra in linhas[1:]:
                db.session.delete(sobra)
            linha.parte = ""
        linha.responsavel_id = getattr(responsavel, "id", None)
        linha.responsavel = nome_da_conta(responsavel) or None
        if atividade:
            linha.atividade = atividade
        feitos += 1
    return feitos


def dividir(bloco_id, dia: date, hoje: date, divisao, por: str) -> int:
    """Divide o quarteirão do dia em dois Ls opostos, um para cada pessoa.

    ``divisao``: ``[(parte, responsavel), (parte_oposta, responsavel)]``. Reaproveita
    as linhas que já existem (a atividade escolhida continua) e não mexe em parte concluída.
    """
    from extensions import db
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q

    if dia < hoje or dia > hoje + timedelta(days=60):
        raise ValueError("O plano vale de hoje até 60 dias à frente.")
    if (not isinstance(divisao, list) or len(divisao) != 2
            or divisao[0][0] not in PARTES or PARTES[divisao[0][0]] != divisao[1][0]):
        raise ValueError("Divida o quarteirão em dois Ls opostos (NE e SO, ou NO e SE).")
    (bloco,) = _blocos_validos([bloco_id])
    linhas = _linhas_do_dia(bloco["id"], dia)
    if any(linha.concluido_em is not None for linha in linhas):
        raise ValueError("Parte deste quarteirão já foi concluída. Reabra antes de dividir de novo.")
    atividade = next((linha.atividade for linha in linhas if linha.atividade), None)
    por_parte = {linha.parte: linha for linha in linhas}
    livres = [linha for linha in linhas if linha.parte not in {parte for parte, _r in divisao}]
    for parte, responsavel in divisao:
        linha = por_parte.get(parte) or (livres.pop(0) if livres else None)
        if linha is None:
            linha = Q(bloco=bloco["id"], setor=bloco["s"], quarteirao=bloco["n"], data=dia, criado_por=por,
                      atividade=atividade)
            db.session.add(linha)
        linha.parte = parte
        linha.responsavel_id = getattr(responsavel, "id", None)
        linha.responsavel = nome_da_conta(responsavel) or None
    for sobra in livres:
        db.session.delete(sobra)
    return 1


def unir(bloco_id, dia: date, responsavel) -> int:
    """Desfaz a divisão em L: o quarteirão volta a ser inteiro, do responsável escolhido."""
    from extensions import db

    (bloco,) = _blocos_validos([bloco_id])
    linhas = _linhas_do_dia(bloco["id"], dia)
    if len(linhas) < 2 and not any(linha.parte for linha in linhas):
        return 0
    if any(linha.concluido_em is not None for linha in linhas):
        raise ValueError("Parte deste quarteirão já foi concluída. Reabra antes de juntar as partes.")
    escolhida = next((linha for linha in linhas if linha.responsavel_id == getattr(responsavel, "id", None)), linhas[0])
    for sobra in linhas:
        if sobra is not escolhida:
            db.session.delete(sobra)
    escolhida.parte = ""
    escolhida.responsavel_id = getattr(responsavel, "id", None)
    escolhida.responsavel = nome_da_conta(responsavel) or None
    return 1


def desplanejar(blocos, dia: date) -> int:
    """Tira do plano o que ainda não começou; quarteirão com visita registrada fica."""
    from extensions import db
    from models.entomologia import EntomologiaVisitaDomiciliar as V

    feitos = 0
    for bloco in _blocos_validos(blocos):
        linhas = _linhas_do_dia(bloco["id"], dia)
        if not linhas or any(linha.concluido_em is not None for linha in linhas):
            continue
        if V.query.filter(V.bloco == bloco["id"], V.data_visita >= dia).first() is not None:
            continue
        for linha in linhas:
            db.session.delete(linha)
        feitos += 1
    return feitos


def _abertos(bloco_id: str, ate: date) -> list:
    """Linhas em aberto do plano mais recente do quarteirão (duas quando dividido em L)."""
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q
    linhas = (Q.query.filter(Q.bloco == bloco_id, Q.concluido_em.is_(None), Q.data <= ate)
              .order_by(Q.data.desc(), Q.id).all())
    return [linha for linha in linhas if linha.data == linhas[0].data] if linhas else []


def _plano_aberto(bloco_id: str, ate: date, usuario_id=None):
    abertos = _abertos(bloco_id, ate)
    return next((linha for linha in abertos if usuario_id and linha.responsavel_id == usuario_id),
                abertos[0] if abertos else None)


def concluir(blocos, hoje: date, usuario) -> int:
    """Conclui o quarteirão; dividido em L, quem tem um L conclui só o seu."""
    from extensions import db
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q
    from time_utils import utcnow

    feitos, nome = 0, nome_da_conta(usuario)
    for bloco in _blocos_validos(blocos):
        abertos = _abertos(bloco["id"], hoje)
        if not abertos:
            if _linhas_do_dia(bloco["id"], hoje):
                continue            # já concluído hoje
            linha = Q(bloco=bloco["id"], setor=bloco["s"], quarteirao=bloco["n"], data=hoje, criado_por=nome,
                      responsavel_id=usuario.id, responsavel=nome, parte="")
            db.session.add(linha)
            abertos = [linha]
        meus = [linha for linha in abertos if linha.responsavel_id == usuario.id]
        for linha in (meus if meus and len(abertos) > 1 else abertos):
            linha.concluido_em, linha.concluido_por, linha.concluido_por_id = utcnow(), nome, usuario.id
        feitos += 1
    return feitos


def reabrir(blocos, hoje: date) -> int:
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q

    feitos = 0
    for bloco in _blocos_validos(blocos):
        ultima = (Q.query.filter(Q.bloco == bloco["id"], Q.concluido_em.isnot(None),
                                 Q.data >= hoje - timedelta(days=RECENTE_DIAS))
                  .order_by(Q.data.desc(), Q.id.desc()).first())
        if ultima is None or _abertos(bloco["id"], hoje):
            continue
        for linha in _linhas_do_dia(bloco["id"], ultima.data):
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


def _produtos(valor) -> list[str]:
    """Larvicidas do focal informados (lista ou texto separado por vírgula), sem repetição."""
    itens = valor if isinstance(valor, list) else str(valor or "").split(",")
    produtos = set()
    for item in itens:
        produto = str(item or "").strip().upper()
        if not produto:
            continue
        if produto not in PRODUTOS_FOCAL:
            raise ValueError("Produto do tratamento focal inválido.")
        produtos.add(produto)
    return sorted(produtos)


def _recipientes_por_tipo(valor) -> list[dict]:
    """Recipientes anotados linha a linha: ``[{"t": 12, "e": 3, "a": 2, "l": 1, "c": "F", "p": "NATULAR"}]``.

    Cada linha tem um tipo (1 a 40) e, opcionalmente, o controle feito nela (``c``:
    M, A ou F) e, no focal, o larvicida (``p``). Linhas iguais em tipo e controle somam.
    """
    if valor in (None, ""):
        return []
    if not isinstance(valor, list) or len(valor) > 3 * len(TIPOS_RECIPIENTE):
        raise ValueError("Lista de tipos de recipiente inválida.")
    por_linha: dict = {}
    for linha in valor:
        if not isinstance(linha, dict):
            raise ValueError("Lista de tipos de recipiente inválida.")
        try:
            tipo = int(linha.get("t"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Tipo de recipiente inválido.") from exc
        if tipo not in TIPOS_RECIPIENTE:
            raise ValueError("Tipo de recipiente inválido.")
        controle = str(linha.get("c") or "").strip().upper()
        if controle and controle not in CONTROLES:
            raise ValueError("Controle do recipiente inválido.")
        produto = str(linha.get("p") or "").strip().upper() if controle == "F" else ""
        if produto and produto not in PRODUTOS_FOCAL:
            raise ValueError("Produto do tratamento focal inválido.")
        larva = _inteiro(linha.get("l"), "recipientes com larva")
        agua = max(_inteiro(linha.get("a"), "recipientes com água"), larva)
        existentes = max(_inteiro(linha.get("e"), "recipientes existentes"), agua)
        soma = por_linha.setdefault((tipo, controle, produto), {"t": tipo, "e": 0, "a": 0, "l": 0})
        if controle:
            soma["c"] = controle
        if produto:
            soma["p"] = produto
        soma["e"], soma["a"], soma["l"] = (min(999, soma["e"] + existentes), min(999, soma["a"] + agua),
                                           min(999, soma["l"] + larva))
    return [por_linha[chave] for chave in sorted(por_linha) if por_linha[chave]["e"]]


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
    por_tipo = _recipientes_por_tipo(item.get("recipientes")) if inspecionado else []
    # O controle anotado em cada recipiente vale também para o imóvel.
    controles = {linha.get("c") for linha in por_tipo}
    mecanico = inspecionado and (bool(item.get("controle_mecanico")) or "M" in controles)
    alternativo = inspecionado and (bool(item.get("controle_alternativo")) or "A" in controles)
    focal = inspecionado and (bool(item.get("tratamento_focal")) or "F" in controles)
    produtos = sorted(set(_produtos(item.get("focal_produto")) if focal else [])
                      | {linha["p"] for linha in por_tipo if linha.get("p")})
    existentes = _inteiro(item.get("recipientes_existentes"), "recipientes existentes") if inspecionado else 0
    com_agua = _inteiro(item.get("recipientes_agua"), "recipientes com água") if inspecionado else 0
    com_larva = _inteiro(item.get("recipientes_larva"), "recipientes com larva") if inspecionado else 0
    if por_tipo:
        # Anotados por tipo, os totais do boletim são a soma dos tipos.
        existentes = min(999, sum(linha["e"] for linha in por_tipo))
        com_agua = min(999, sum(linha["a"] for linha in por_tipo))
        com_larva = min(999, sum(linha["l"] for linha in por_tipo))
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
        "recipientes_json": json.dumps(por_tipo, separators=(",", ":")) if por_tipo else None,
        "larvas_encontradas": inspecionado and (bool(item.get("larvas")) or com_larva > 0),
        "tubitos": _inteiro(item.get("tubitos"), "tubitos") if inspecionado else 0,
        "controle_mecanico": mecanico, "controle_alternativo": alternativo, "tratamento_focal": focal,
        "focal_produto": ",".join(produtos) if focal and produtos else None,
        "atividade": _atividade(item.get("atividade")),
        "observacao": str(item.get("observacao") or "").strip()[:1000] or None,
    }


def registrar_visitas(itens, usuario, hoje: date) -> dict:
    """Grava o lote vindo do aparelho. Reenviar a mesma visita não duplica."""
    from extensions import db
    from models.entomologia import (EntomologiaImovelCampo as C, EntomologiaQuarteiraoTrabalho as Q,
                                    EntomologiaVisitaDomiciliar as V)

    if not isinstance(itens, list) or not itens:
        raise ValueError("Nenhuma visita informada.")
    if len(itens) > LIMITE_LOTE:
        raise ValueError(f"Envie até {LIMITE_LOTE} visitas por vez.")
    blocos = indice()["blocos"]
    nome = nome_da_conta(usuario)
    enviados = [str(item.get("uuid") or "") for item in itens if isinstance(item, dict)]
    existentes = {uuid for (uuid,) in V.query.with_entities(V.uuid_local).filter(V.uuid_local.in_(enviados)).all()}
    aceitas, recusadas, novas, imoveis_novos = [], [], 0, 0
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
        if not dados["atividade"]:
            plano = _plano_aberto(dados["bloco"], dados["data_visita"], usuario.id)
            dados["atividade"] = plano.atividade if plano else None
        db.session.add(V(**dados, recuperacao=recuperacao, agente_id=usuario.id, agente=nome))
        novas += 1
        # Imóvel que faltava na base: entra no mapa da equipe a partir de agora.
        if (dados["imovel"].startswith("novo-") and dados["logradouro"] and dados["numero"]
                and C.query.filter_by(imovel=dados["imovel"]).first() is None):
            bloco = blocos[dados["bloco"]]
            db.session.add(C(imovel=dados["imovel"], bloco=dados["bloco"], setor=dados["setor"],
                             quarteirao=dados["quarteirao"], logradouro=dados["logradouro"],
                             numero=dados["numero"], complemento=dados["complemento"],
                             latitude=dados["latitude"] if dados["latitude"] is not None else bloco["c"][1],
                             longitude=dados["longitude"] if dados["longitude"] is not None else bloco["c"][0],
                             criado_por_id=usuario.id, criado_por=nome))
            imoveis_novos += 1
        # Todo quarteirão trabalhado tem a sua linha no plano, mesmo quando não foi planejado.
        if (_plano_aberto(dados["bloco"], dados["data_visita"]) is None
                and Q.query.filter_by(bloco=dados["bloco"], data=dados["data_visita"]).first() is None):
            db.session.add(Q(bloco=dados["bloco"], setor=dados["setor"], quarteirao=dados["quarteirao"],
                             data=dados["data_visita"], responsavel_id=usuario.id, responsavel=nome,
                             criado_por=nome))
            db.session.flush()
    return {"aceitas": aceitas, "recusadas": recusadas, "novas": novas, "imoveis_novos": imoveis_novos}


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


def _texto_de_planilha(valor) -> str:
    texto = " ".join(str(valor or "").split())
    return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto


def _tipos_em_texto(visita) -> str:
    """"12 (3 exist., 2 água, 1 larva) | 30 (1 exist.)": os tipos anotados, legíveis na planilha."""
    partes = []
    for linha in recipientes_da_visita(visita):
        conta = [f'{linha.get("e", 0)} exist.']
        if linha.get("a"):
            conta.append(f'{linha["a"]} água')
        if linha.get("l"):
            conta.append(f'{linha["l"]} larva')
        if linha.get("c"):
            controle = CONTROLES.get(linha["c"], linha["c"]).lower()
            conta.append(controle + (" " + PRODUTOS_FOCAL.get(linha.get("p"), "") if linha.get("p") else ""))
        partes.append(f'{TIPOS_RECIPIENTE.get(linha.get("t"), ("?",))[0]}{linha.get("t")} ({", ".join(conta)})')
    return " | ".join(partes)


def _nomes_produtos(valor) -> str:
    return " + ".join(PRODUTOS_FOCAL.get(p, p) for p in str(valor or "").split(",") if p)


def visitas_csv(inicio: date, fim: date) -> str:
    """Uma linha por visita, com todos os campos registrados na rua."""
    sim = lambda valor: "SIM" if valor else "NAO"
    return _csv(
        ["DATA", "HORA", "SETOR", "QUARTEIRAO", "LOGRADOURO", "NUMERO", "COMPLEMENTO", "SITUACAO",
         "REC. EXIST.", "REC. AGUA", "REC. LARVA", "IM. LARVA", "TUBITOS", "IM MECANICO", "IM ALTERNATIVO",
         "IM FOCAL", "RECUPERACAO", "AGENTE", "OBSERVACAO", "PRODUTO FOCAL", "ATIVIDADE", "TIPOS DE RECIPIENTE"],
        ([v.data_visita.isoformat(), (_iso(v.horario_visita) or "")[11:16], v.setor, v.quarteirao,
          _texto_de_planilha(v.logradouro), v.numero or "", _texto_de_planilha(v.complemento),
          SITUACOES.get(v.situacao, v.situacao),
          v.recipientes_existentes, v.recipientes_agua, v.recipientes_larva, sim(v.larvas_encontradas), v.tubitos,
          sim(v.controle_mecanico), sim(v.controle_alternativo), sim(v.tratamento_focal), sim(v.recuperacao),
          _texto_de_planilha(v.agente), _texto_de_planilha(v.observacao), _nomes_produtos(v.focal_produto),
          ATIVIDADES.get(v.atividade or "", ""), _tipos_em_texto(v)]
         for v in _visitas_do_periodo(inicio, fim)))


def recipientes_csv(inicio: date, fim: date) -> str:
    """Recipientes por tipo, somados por dia e quarteirão (vale a última visita do imóvel no dia)."""
    ultimas = {}
    for visita in _visitas_do_periodo(inicio, fim):
        ultimas[(visita.data_visita, visita.bloco, visita.imovel)] = visita
    somas: dict = {}
    for (dia, bloco, _imovel), v in ultimas.items():
        for linha in recipientes_da_visita(v):
            tipo = linha.get("t")
            if tipo not in TIPOS_RECIPIENTE:
                continue
            conta = somas.setdefault((dia, v.setor, v.quarteirao, bloco, tipo),
                                     {"imoveis": set(), "e": 0, "a": 0, "l": 0, "M": 0, "A": 0, "NATULAR": 0, "VECTOBAC": 0})
            conta["imoveis"].add(v.imovel)
            for chave in ("e", "a", "l"):
                conta[chave] += linha.get(chave, 0)
            # Recipientes (existentes) por controle feito na linha; focal pelo larvicida usado.
            controle = linha.get("p") if linha.get("c") == "F" else linha.get("c")
            if controle in conta:
                conta[controle] += linha.get("e", 0)
    colunas = ("e", "a", "l", "M", "A", "NATULAR", "VECTOBAC")
    return _csv(
        ["DATA", "SETOR", "QUARTEIRAO", "GRUPO", "TIPO", "RECIPIENTE", "IMOVEIS", "REC. EXIST.", "REC. AGUA",
         "REC. LARVA", "MECANICO", "ALTERNATIVO", "FOCAL NATULAR", "FOCAL VECTOBAC"],
        ([dia.isoformat(), setor, quarteirao, TIPOS_RECIPIENTE[tipo][0], tipo, TIPOS_RECIPIENTE[tipo][1],
          len(conta["imoveis"]), *(conta[c] for c in colunas)]
         for (dia, setor, quarteirao, _bloco, tipo), conta in sorted(somas.items(), key=lambda item: (
             item[0][0], item[0][1], item[0][2], item[0][3], item[0][4]))))


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


# ---------------------------------------------------------------------------
# Relatório do escritório: tudo por dia e por quarteirão
# ---------------------------------------------------------------------------

_CONTAS_RELATORIO = ("imoveis", "trabalhados", "fechados", "desocupados", "temporada", "parciais", "recusas",
                     "com_larva", "tubitos", "rec_existentes", "rec_agua", "rec_larva", "mecanico", "alternativo",
                     "focal", "natular", "vectobac", "recuperados")
_CONTA_SITUACAO = {"TRABALHADO": "trabalhados", "FECHADO": "fechados", "DESOCUPADO": "desocupados",
                   "TEMPORADA": "temporada", "PARCIAL": "parciais", "RECUSA": "recusas"}


def relatorio(inicio: date, fim: date) -> dict:
    """Dias do período, cada um com totais e uma linha por quarteirão trabalhado ou planejado.

    Vale a última visita de cada imóvel no dia, como no boletim. Cada quarteirão traz
    também o plano (responsáveis, Ls, atividade, se foi concluído), os agentes que
    registraram e os recipientes por grupo (A a G).
    """
    from models.entomologia import EntomologiaQuarteiraoTrabalho as Q

    casas_por_bloco = indice()["casas"]
    ultimas = {}
    for visita in _visitas_do_periodo(inicio, fim):
        ultimas[(visita.data_visita, visita.bloco, visita.imovel)] = visita

    def nova_linha(dia, bloco, setor, quarteirao):
        return {"data": dia.isoformat(), "bloco": bloco, "setor": setor, "quarteirao": quarteirao,
                "previstos": casas_por_bloco.get(bloco, 0), "planos": [], "agentes": [], "atividades": [],
                "concluido": False, "grupos": {grupo: 0 for grupo, _t, _ in GRUPOS_RECIPIENTE},
                **{conta: 0 for conta in _CONTAS_RELATORIO}}

    linhas: dict = {}
    for (dia, bloco, _imovel), v in ultimas.items():
        linha = linhas.setdefault((dia, bloco), nova_linha(dia, bloco, v.setor, v.quarteirao))
        linha["imoveis"] += 1
        linha[_CONTA_SITUACAO.get(v.situacao, "trabalhados")] += 1
        linha["com_larva"] += bool(v.larvas_encontradas)
        linha["tubitos"] += v.tubitos or 0
        linha["rec_existentes"] += v.recipientes_existentes or 0
        linha["rec_agua"] += v.recipientes_agua or 0
        linha["rec_larva"] += v.recipientes_larva or 0
        linha["mecanico"] += bool(v.controle_mecanico)
        linha["alternativo"] += bool(v.controle_alternativo)
        linha["focal"] += bool(v.tratamento_focal)
        produtos = str(v.focal_produto or "").split(",")
        linha["natular"] += "NATULAR" in produtos
        linha["vectobac"] += "VECTOBAC" in produtos
        linha["recuperados"] += bool(v.recuperacao)
        for tipo in recipientes_da_visita(v):
            grupo = TIPOS_RECIPIENTE.get(tipo.get("t"), (None,))[0]
            if grupo:
                linha["grupos"][grupo] += tipo.get("e", 0)
        if v.agente and v.agente not in linha["agentes"]:
            linha["agentes"].append(v.agente)
        if v.atividade and v.atividade not in linha["atividades"]:
            linha["atividades"].append(v.atividade)

    for plano in Q.query.filter(Q.data >= inicio, Q.data <= fim).order_by(Q.id).all():
        linha = linhas.setdefault((plano.data, plano.bloco), nova_linha(plano.data, plano.bloco, plano.setor,
                                                                        plano.quarteirao))
        linha["planos"].append({"responsavel": plano.responsavel or "", "parte": plano.parte or "",
                                "concluido": plano.concluido_em is not None})
        if plano.atividade and plano.atividade not in linha["atividades"]:
            linha["atividades"].append(plano.atividade)
    for linha in linhas.values():
        linha["concluido"] = bool(linha["planos"]) and all(p["concluido"] for p in linha["planos"])

    dias = []
    for dia in sorted({chave[0] for chave in linhas}, reverse=True):
        do_dia = sorted((linha for (d, _b), linha in linhas.items() if d == dia),
                        key=lambda linha: (_ordem_natural(linha["setor"]), _ordem_natural(linha["quarteirao"])))
        totais = {conta: sum(linha[conta] for linha in do_dia) for conta in _CONTAS_RELATORIO}
        totais.update(quarteiroes=len(do_dia), concluidos=sum(linha["concluido"] for linha in do_dia),
                      agentes=sorted({agente for linha in do_dia for agente in linha["agentes"]}))
        dias.append({"data": dia.isoformat(), "totais": totais, "quarteiroes": do_dia})
    return {"inicio": inicio.isoformat(), "fim": fim.isoformat(), "dias": dias, "atividades": ATIVIDADES,
            "grupos": {grupo: titulo for grupo, titulo, _ in GRUPOS_RECIPIENTE}}


def _ordem_natural(texto) -> tuple:
    return tuple(int(parte) if parte.isdigit() else parte for parte in re.split(r"(\d+)", str(texto or "")))


def relatorio_csv(inicio: date, fim: date) -> str:
    """O relatório do escritório numa planilha: uma linha por dia e quarteirão."""
    grupos = [grupo for grupo, _t, _ in GRUPOS_RECIPIENTE]
    cabecalho = ["DATA", "SETOR", "QUARTEIRAO", "ATIVIDADE", "RESPONSAVEIS", "AGENTES", "CONCLUIDO",
                 "IMOVEIS PREVISTOS", "IMOVEIS VISITADOS", "TRABALHADOS", "FECHADOS", "DESOCUPADOS", "RECUSAS",
                 "TEMPORADA", "PARCIAIS", "RECUPERADOS", "COM LARVA", "TUBITOS", "REC. EXIST.", "REC. AGUA",
                 "REC. LARVA", "MECANICO", "ALTERNATIVO", "FOCAL", "NATULAR", "VECTOBAC",
                 *[f"RECIPIENTES {grupo}" for grupo in grupos]]
    linhas = []
    for dia in reversed(relatorio(inicio, fim)["dias"]):
        for q in dia["quarteiroes"]:
            responsaveis = " + ".join(p["responsavel"] + (f" ({NOME_PARTE[p['parte']]})" if p["parte"] else "")
                                      for p in q["planos"] if p["responsavel"])
            linhas.append([q["data"], q["setor"], q["quarteirao"],
                           " / ".join(ATIVIDADES.get(a, a) for a in q["atividades"]),
                           _texto_de_planilha(responsaveis), _texto_de_planilha(" + ".join(q["agentes"])),
                           "SIM" if q["concluido"] else "NAO", q["previstos"], q["imoveis"], q["trabalhados"],
                           q["fechados"], q["desocupados"], q["recusas"], q["temporada"], q["parciais"],
                           q["recuperados"], q["com_larva"], q["tubitos"], q["rec_existentes"], q["rec_agua"],
                           q["rec_larva"], q["mecanico"], q["alternativo"], q["focal"], q["natular"], q["vectobac"],
                           *[q["grupos"][grupo] for grupo in grupos]])
    return _csv(cabecalho, linhas)
