"""Catálogo do prescritor do VetSmart: leitura comedida e formato compacto.

O prescritor do VetSmart lê, para cada item, a lista de apresentações e as
dosagens estruturadas num endereço próprio. É dali que saem as apresentações
dos princípios ativos genéricos ("Dipirona 500 mg, comprimido"), que a página
pública de bula não traz.

Esse endereço tem limite de ritmo imposto pelo próprio VetSmart: algo como
quinze leituras seguidas rendem um bloqueio de alguns minutos. Por isso este
módulo lê um item por vez, com pausa, obedece ao ``Retry-After`` e desiste em
vez de insistir. Não é para baixar o catálogo inteiro: é para trazer o que a
clínica prescreve.

O que se guarda é só o que o prescritor precisa (rótulos, concentração,
quantidade, medida e as dosagens numéricas), em
``Medicamento.conteudo_estruturado['catalogo_prescritor'][<id do VetSmart>]``.
Quem consome é ``services/bulario_escopo.py``.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from services import bulario_escopo as escopo

URL_ITEM = "https://api.vetsmart.com.br/v2/item/{pid}/dc?with=dosageForms,dosages"
CABECALHOS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; petorlandia-bulario)",
    "Origin": "https://widget.vetsmart.com.br",
    "Referer": "https://widget.vetsmart.com.br/",
}
#: Pausa entre leituras. Dez itens a cada 25 s passaram sem bloqueio.
INTERVALO_PADRAO = 25.0
#: Espera máxima aceita num ``Retry-After``; acima disso, para e retoma depois.
ESPERA_MAXIMA = 600


class LimiteDeRitmo(Exception):
    """O VetSmart pediu para parar. Carrega os segundos de espera."""

    def __init__(self, espera: int):
        super().__init__(f"limite de ritmo; esperar {espera}s")
        self.espera = espera


class ItemIndisponivel(Exception):
    """O item não existe (mais) no catálogo ou a leitura foi recusada."""


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def _decimal(valor: Any) -> Optional[float]:
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _inteiro(valor: Any) -> Optional[int]:
    try:
        return int(str(valor))
    except (TypeError, ValueError):
        return None


def _verdadeiro(valor: Any) -> bool:
    return str(valor).strip() in {"1", "true", "True"}


def compactar_item(bruto: Dict[str, Any], hoje: Optional[date] = None) -> Dict[str, Any]:
    """O item como o bulário guarda: só o necessário para prescrever."""
    medidas = ((bruto.get("suggestions") or {}).get("dosageForms") or {})
    apresentacoes = []
    for forma in bruto.get("dosageForms") or []:
        if not isinstance(forma, dict):
            continue
        rotulo = _texto(forma.get("formattedDrugDosageFormForPrescription"))
        if not rotulo:
            continue
        identificador = _texto(forma.get("dosageFormId"))
        apresentacoes.append({
            "id": identificador,
            "rotulo": rotulo,
            "completo": _texto(forma.get("formattedDrugDosageFormFull")),
            "concentracao": _texto(forma.get("concentration")),
            "quantidade": _texto(forma.get("quantity")),
            "forma": _texto(forma.get("type")),
            "info": _texto(forma.get("info")),
            "medida": _texto((medidas.get(identificador) or {}).get("type")),
            "ordem": _inteiro(forma.get("sortSequence")) or len(apresentacoes) + 1,
        })
    dosagens = []
    for dose in bruto.get("dosages") or []:
        if not isinstance(dose, dict):
            continue
        minimo = _decimal(dose.get("minDosage"))
        if minimo is None:
            continue
        maximo = _decimal(dose.get("maxDosage"))
        dosagens.append({
            "grupo": _texto(dose.get("dosageGroup")),
            "subgrupo": _texto(dose.get("dosageSubGroup")),
            "min": minimo,
            "max": maximo if maximo is not None else minimo,
            "unidade": _texto(dose.get("dosageUnitOfMeasure")),
            "por": _decimal(dose.get("referenceValue")) or 1.0,
            "por_unidade": _texto(dose.get("referenceUnitOfMeasure")) or "animal",
            "caes": _verdadeiro(dose.get("animalType1Dosage")),
            "gatos": _verdadeiro(dose.get("animalType2Dosage")),
            "ordem": _inteiro(dose.get("sortSequence")) or len(dosagens) + 1,
        })
    return {
        "nome": _texto(bruto.get("itemName")),
        "via": _texto((bruto.get("suggestions") or {}).get("usage")),
        "alimento": _verdadeiro(bruto.get("isFood")),
        "indisponivel": _verdadeiro(bruto.get("unavailable")),
        "atualizado_em": (hoje or date.today()).isoformat(),
        "apresentacoes": apresentacoes,
        "dosagens": dosagens,
    }


def buscar_item(pid: int, abrir: Callable[..., Any] = urllib.request.urlopen) -> Dict[str, Any]:
    """Lê um item do catálogo. Não tenta de novo: quem chama decide."""
    requisicao = urllib.request.Request(URL_ITEM.format(pid=int(pid)), headers=CABECALHOS)
    try:
        with abrir(requisicao, timeout=40) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        if erro.code == 429:
            raise LimiteDeRitmo(_inteiro(erro.headers.get("Retry-After")) or 300) from erro
        raise ItemIndisponivel(f"HTTP {erro.code}") from erro
    except (urllib.error.URLError, TimeoutError, ValueError) as erro:
        raise ItemIndisponivel(repr(erro)) from erro


# ───────────────────────── o que importar ──────────────────────────────────


def indice_de_nomes(medicamentos: Iterable[Tuple[int, str, Optional[str], Optional[int], Any]]):
    """Índices para casar um nome prescrito com os itens do VetSmart.

    Recebe tuplas ``(id, nome, principio_ativo, vetsmart_produto_id, conteudo)``
    e devolve ``(nomes -> ids do VetSmart, id do VetSmart -> ids de medicamento)``.
    Um nome de princípio ativo aponta para o item genérico dele.
    """
    por_nome: Dict[str, Set[int]] = {}
    donos: Dict[int, Set[int]] = {}
    for med_id, nome, _principio, vetsmart_id, conteudo in medicamentos:
        produtos = escopo.produtos(SimpleNamespace(conteudo_estruturado=conteudo))
        do_medicamento: Set[int] = set()
        for produto in produtos:
            pid = escopo.pid_do_produto(produto)
            if pid is None:
                continue
            donos.setdefault(pid, set()).add(med_id)
            por_nome.setdefault(escopo.norm(produto.get("nome")), set()).add(pid)
            if (produto.get("tipo") or "") == "principio_ativo":
                do_medicamento.add(pid)
        if not produtos and vetsmart_id is not None:
            donos.setdefault(int(vetsmart_id), set()).add(med_id)
            do_medicamento.add(int(vetsmart_id))
        if do_medicamento:
            por_nome.setdefault(escopo.norm(nome), set()).update(do_medicamento)
    por_nome.pop("", None)
    return por_nome, donos


def ids_dos_nomes(nomes_prescritos: Iterable[str], por_nome: Dict[str, Set[int]]) -> List[int]:
    """Ids do VetSmart dos itens que os nomes prescritos citam.

    Casa pelo nome mais longo que abre o texto da receita, em fronteira de
    palavra: "Vermivet Plus — 660 mg, comprimido" é o Vermivet Plus, não um
    "Vermivet" qualquer.
    """
    candidatos = sorted((nome for nome in por_nome if len(nome) >= 4), key=len, reverse=True)
    achados: List[int] = []
    vistos: Set[int] = set()
    for prescrito in nomes_prescritos:
        alvo = escopo.norm(prescrito)
        if not alvo:
            continue
        for nome in candidatos:
            if alvo.startswith(nome) and (len(alvo) == len(nome) or not alvo[len(nome)].isalnum()):
                for pid in sorted(por_nome[nome]):
                    if pid not in vistos:
                        vistos.add(pid)
                        achados.append(pid)
                break
    return achados


def gravar_no_conteudo(conteudo: Any, pid: int, item: Dict[str, Any]) -> Dict[str, Any]:
    """Novo ``conteudo_estruturado`` com o item do catálogo. Não altera o original."""
    novo = dict(conteudo) if isinstance(conteudo, dict) else {}
    catalogo = dict(novo.get(escopo.CHAVE_CATALOGO) or {})
    catalogo[str(int(pid))] = item
    novo[escopo.CHAVE_CATALOGO] = catalogo
    return novo


def ja_importado(conteudo: Any, pid: int) -> bool:
    catalogo = conteudo.get(escopo.CHAVE_CATALOGO) if isinstance(conteudo, dict) else None
    return isinstance(catalogo, dict) and isinstance(catalogo.get(str(int(pid))), dict)


def importar(
    ids: Iterable[int],
    gravar: Callable[[int, Dict[str, Any]], int],
    *,
    intervalo: float = INTERVALO_PADRAO,
    buscar: Callable[[int], Dict[str, Any]] = buscar_item,
    dormir: Callable[[float], None] = time.sleep,
    avisar: Callable[[str], None] = print,
) -> Dict[str, int]:
    """Lê os itens um a um e entrega cada um a ``gravar(pid, item)``.

    Para no segundo bloqueio seguido, ou num bloqueio que peça espera longa:
    o que faltou fica para a próxima execução.
    """
    resumo = {"lidos": 0, "gravados": 0, "indisponiveis": 0, "pendentes": 0}
    fila = list(ids)
    for posicao, pid in enumerate(fila):
        bruto = None
        for tentativa in (1, 2):
            try:
                bruto = buscar(pid)
                break
            except LimiteDeRitmo as limite:
                if tentativa == 2 or limite.espera > ESPERA_MAXIMA:
                    resumo["pendentes"] = len(fila) - posicao
                    avisar(f"limite de ritmo do VetSmart: parando com {resumo['pendentes']} item(ns) por ler")
                    return resumo
                avisar(f"limite de ritmo do VetSmart: aguardando {limite.espera}s")
                dormir(limite.espera + 5)
            except ItemIndisponivel as erro:
                resumo["indisponiveis"] += 1
                avisar(f"item {pid} indisponível ({erro})")
                break
        if bruto is not None:
            item = compactar_item(bruto)
            resumo["lidos"] += 1
            resumo["gravados"] += gravar(pid, item)
            avisar(
                f"item {pid} · {item['nome']} · {len(item['apresentacoes'])} apresentação(ões)"
                f" · {len(item['dosagens'])} dosagem(ns)"
            )
        if posicao + 1 < len(fila):
            dormir(intervalo)
    return resumo
