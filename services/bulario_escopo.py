"""Escopo por produto comercial dentro de um medicamento canônico.

O bulário agrupa os produtos do VetSmart pelo princípio ativo: "Vermivet
Filhote" (suspensão, 1 mL/kg) e "Vermivet Plus" (comprimidos de 330 mg, 660 mg
e 2 g) vivem no mesmo ``Medicamento``. O prescritor do VetSmart, ao contrário,
trabalha por produto: escolhido o produto, só existem as apresentações e as
doses dele.

Este módulo reconstrói essa visão. Dado o medicamento canônico e o produto
escolhido, devolve um ``MedicamentoEscopado`` que tem a mesma interface que o
resto de ``services.bulario`` já consome (``apresentacoes``, ``doses``,
``via_administracao``...), restrita ao produto.

Três regras sustentam o módulo:

1. Apresentação de um produto nunca aparece em outro, e nenhuma apresentação
   do próprio produto é escondida. O que o VetSmart lista, o prescritor lista.
2. Dose também é do produto. "1 comprimido / 10 kg" do comprimido de 660 mg
   não vale para o de 2 g; o vínculo dose → apresentação vem do cabeçalho que
   o próprio VetSmart publica ("Vermivet Plus 660 mg") e só é aceito quando
   casa sem ambiguidade com a concentração cadastrada.
3. Nada aqui grava no banco. Linhas reais de ``apresentacao_medicamento`` e
   ``dose_medicamento`` são reaproveitadas (mantêm o ``id``); o que só existe
   no retrato do produto recebe um id sintético estável.

Sem dependência de Flask ou do banco: ``services/bulario.py`` carrega este
arquivo pelo caminho, como já faz com ``posologia_normalizacao.py``.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

#: Ids de apresentações e doses que existem só no retrato do produto. Ficam
#: muito acima de qualquer id real e cabem em um inteiro de 32 bits.
ID_SINTETICO_BASE = 1_000_000_000

_SIMBOLOS_MARCA = "®™©"
_SEPARADORES = " ,;:-–—" + _SIMBOLOS_MARCA
SECAO_ADMINISTRACAO = "Administração e doses"


# ───────────────────────── texto ───────────────────────────────────────────


def norm(texto: Any) -> str:
    """Minúsculas, sem acento, sem ®/™ e com espaços colapsados."""
    if not texto:
        return ""
    decomposto = unicodedata.normalize("NFKD", str(texto))
    limpo = "".join(
        c for c in decomposto
        if not unicodedata.combining(c) and c not in _SIMBOLOS_MARCA
    )
    return re.sub(r"\s+", " ", limpo).strip().lower()


def _norm_com_indices(texto: str) -> Tuple[str, List[int]]:
    """``norm`` que lembra de qual posição do original veio cada caractere."""
    chars: List[str] = []
    indices: List[int] = []
    for i, original in enumerate(texto):
        for c in unicodedata.normalize("NFKD", original):
            if unicodedata.combining(c) or c in _SIMBOLOS_MARCA:
                continue
            c = c.lower()
            if c.isspace():
                if not chars or chars[-1] == " ":
                    continue
                c = " "
            chars.append(c)
            indices.append(i)
    return "".join(chars), indices


def remover_prefixo_nome(texto: Any, nome: Any) -> str:
    """Tira o nome do produto do começo do texto, preservando a grafia do resto.

    "Vermivet Plus 660 mg (4 un)" sem "Vermivet Plus" vira "660 mg (4 un)".
    "Vermivet" não é prefixo de "Vermivetplus": exige fronteira de palavra.
    """
    bruto = str(texto or "")
    alvo = norm(nome)
    if not bruto.strip():
        return ""
    if alvo:
        normalizado, indices = _norm_com_indices(bruto)
        fim = len(alvo)
        if normalizado.startswith(alvo) and (
            fim >= len(normalizado) or not normalizado[fim].isalnum()
        ):
            return bruto[indices[fim - 1] + 1:].lstrip(_SEPARADORES).strip()
    return bruto.lstrip(_SEPARADORES).strip()


def _ler(obj: Any, campo: str) -> Any:
    return obj.get(campo) if isinstance(obj, dict) else getattr(obj, campo, None)


# ───────────────────────── produtos ────────────────────────────────────────


def produtos(medicamento: Any) -> List[Dict[str, Any]]:
    conteudo = getattr(medicamento, "conteudo_estruturado", None)
    if not isinstance(conteudo, dict):
        return []
    lista = conteudo.get("produtos_vetsmart")
    if not isinstance(lista, list):
        return []
    return [p for p in lista if isinstance(p, dict) and (p.get("nome") or "").strip()]


def pid_do_produto(produto: Dict[str, Any]) -> Optional[int]:
    try:
        return int(produto.get("vetsmart_produto_id"))
    except (TypeError, ValueError):
        return None


def pids_do_produto(produto: Dict[str, Any]) -> Set[int]:
    """Ids do VetSmart que respondem pelo produto (mais de um se foi fundido)."""
    pids = {pid for pid in (produto.get("pids") or []) if pid is not None}
    pid = pid_do_produto(produto)
    if pid is not None:
        pids.add(pid)
    return pids


def _fundir_produtos(lista: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Um produto só a partir de cadastros homônimos do VetSmart.

    O prescritor escolhe o produto pelo nome; dois cadastros "UP Flora" (um
    com a caixa de 8 cápsulas, outro com a de 30) são, para quem prescreve, o
    mesmo produto com duas apresentações.
    """
    fundido = dict(lista[0])
    fundido["pids"] = [pid for pid in (pid_do_produto(p) for p in lista) if pid is not None]
    for campo in ("apresentacoes", "doses"):
        fundido[campo] = [
            item for p in lista
            for item in (p.get(campo) if isinstance(p.get(campo), list) else [])
        ]
    for campo in ("via_administracao", "frequencia", "duracao_tratamento", "dosagem_recomendada", "fabricante"):
        fundido[campo] = next((p.get(campo) for p in lista if p.get(campo)), None)
    fundido["secoes"] = next(
        (p.get("secoes") for p in lista if any(administracao_do_produto(p).values())),
        lista[0].get("secoes"),
    )
    return fundido


def resolver_produto(medicamento: Any, nome_comercial: Any) -> Optional[Dict[str, Any]]:
    alvo = norm(nome_comercial)
    if not alvo:
        return None
    achados = [p for p in produtos(medicamento) if norm(p.get("nome")) == alvo]
    if not achados:
        return None
    return achados[0] if len(achados) == 1 else _fundir_produtos(achados)


def produto_implicito(medicamento: Any) -> Optional[Dict[str, Any]]:
    """O produto, quando o medicamento inteiro é um produto só.

    Vale para os cadastros com exatamente um produto no retrato e para os
    importados no formato antigo (o ``Medicamento`` é o próprio produto).
    Linha de apresentação de outro produto desfaz a certeza.
    """
    lista = produtos(medicamento)
    pids_linhas = {
        pid for pid in (
            getattr(ap, "vetsmart_produto_id", None)
            for ap in (getattr(medicamento, "apresentacoes", None) or [])
        ) if pid is not None
    }
    if len(lista) == 1:
        pid = pid_do_produto(lista[0])
        if pids_linhas and pids_linhas != {pid}:
            return None
        return lista[0]
    if lista or len(pids_linhas) != 1:
        return None
    pid = next(iter(pids_linhas))
    proprio = getattr(medicamento, "vetsmart_produto_id", None)
    if proprio is not None and proprio != pid:
        return None
    return {
        "vetsmart_produto_id": pid,
        "nome": getattr(medicamento, "nome", None) or "",
        "tipo": "produto",
        "apresentacoes": [],
        "doses": [],
        "implicito": True,
    }


# ───────────────────────── seção "Administração e doses" ───────────────────

_TITULOS_ADMIN = {
    "via(s)": "via",
    "frequencia de utilizacao": "frequencia",
    "duracao do tratamento": "duracao",
    "periodo de tratamento": "duracao",
    "dosagem indicada": "dosagens",
    "modo de usar": "modo_de_usar",
    "observacoes": "observacoes",
}
_RUIDO_ADMIN = {"videos da(s) via(s)"}


def parse_administracao(texto: Any) -> Dict[str, List[str]]:
    """Separa a seção do VetSmart nos blocos que o prescritor dele mostra."""
    partes: Dict[str, List[str]] = {chave: [] for chave in set(_TITULOS_ADMIN.values())}
    atual = None
    for bruta in str(texto or "").split("\n"):
        linha = bruta.strip()
        if not linha:
            continue
        chave = norm(linha)
        if chave in _TITULOS_ADMIN:
            atual = _TITULOS_ADMIN[chave]
            continue
        if chave in _RUIDO_ADMIN:
            continue
        if atual:
            partes[atual].append(linha)
    return partes


def administracao_do_produto(produto: Dict[str, Any]) -> Dict[str, List[str]]:
    secoes = produto.get("secoes")
    secao = secoes.get(SECAO_ADMINISTRACAO) if isinstance(secoes, dict) else None
    texto = secao.get("texto") if isinstance(secao, dict) else None
    return parse_administracao(texto)


# "1 mL / kg", "5 - 10 mg / kg", "1 comprimido / 10 kg", "1 - 2 gota / olho".
# Não casa "2º dia e tratamentos subsequentes" nem "2,5 kg a 5,0kg".
_RE_LINHA_DOSE = re.compile(
    r"^\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?\s+[^\W\d_][^/]*/\s*\S"
)
_RE_ZERO = re.compile(r"^0(?:[.,]0+)?(?:\s+\S+)?$")
_ESPECIE = r"(?:c[ãa]es|c[ãa]o|gatos?|caninos?|felinos?)"
_RE_SUFIXO_ESPECIE = re.compile(
    rf"^(.*?)\s+[-–]\s+({_ESPECIE}(?:\s+e\s+{_ESPECIE})?)$", re.IGNORECASE
)
_GRUPOS_GENERICOS = {"doses", "dose", "dosagem", "dosagens"}
_ROTULOS_GENERICOS = {"recomendado"}


def linhas_de_dosagem(linhas: Sequence[str]) -> List[Dict[str, Optional[str]]]:
    """Lê o bloco "Dosagem indicada" em (grupo, espécie, rótulo, dose).

    O grupo é o cabeçalho que o VetSmart põe acima de um conjunto de doses.
    Pode ser a variante do produto ("Vermivet Plus 660 mg"), uma indicação
    ("Glaucoma"), uma via ("IV") ou nada ("Doses").
    """
    saida: List[Dict[str, Optional[str]]] = []
    grupo: Optional[str] = None
    especie: Optional[str] = None
    rotulo: Optional[str] = None
    total = len(linhas)
    i = 0
    while i < total:
        linha = linhas[i].strip()
        chave = norm(linha)
        if not chave or _RE_ZERO.match(linha):
            i += 1
            continue
        if chave in _GRUPOS_GENERICOS:
            grupo, rotulo = None, None
            i += 1
            continue
        if chave.startswith("dosagem para"):
            resto = linha[len("Dosagem para"):].strip()
            rotulo = None
            if resto:
                especie = resto
                i += 1
            elif i + 1 < total:
                especie = linhas[i + 1].strip()
                i += 2
            else:
                i += 1
            continue
        if chave.startswith("indicacao"):
            i += 1
            continue
        if _RE_LINHA_DOSE.match(linha):
            saida.append({
                "grupo": grupo,
                "especie": especie,
                "rotulo": None if norm(rotulo) in _ROTULOS_GENERICOS else rotulo,
                "dose": linha,
            })
            rotulo = None
            i += 1
            continue
        sufixo = _RE_SUFIXO_ESPECIE.match(linha)
        if sufixo:
            prefixo = sufixo.group(1).strip()
            grupo = None if norm(prefixo) in _GRUPOS_GENERICOS else prefixo
            especie = sufixo.group(2).strip()
            rotulo = None
            i += 1
            continue
        proxima = linhas[i + 1].strip() if i + 1 < total else ""
        if proxima and _RE_LINHA_DOSE.match(proxima):
            rotulo = linha
        else:
            grupo, rotulo = linha, None
        i += 1
    return saida


def especie_code(texto: Any) -> Optional[str]:
    t = norm(texto)
    cao = bool(re.search(r"\bcaes\b|\bcao\b|\bcanin|\bcachorr", t))
    gato = bool(re.search(r"\bgat[oa]s?\b|\bfelin", t))
    if cao and gato:
        return "AMBOS"
    if cao:
        return "CAES"
    if gato:
        return "GATOS"
    return None


# ───────────────────────── força da apresentação ───────────────────────────

_RE_FORCA = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mcg|mg|g|ui|ml|%)(\s*/\s*ml)?(?![a-z0-9])"
)


def _forca(valor: float, unidade: Any) -> Tuple[float, str]:
    u = norm(unidade).replace(" ", "")
    if u in {"g", "g/ml"}:
        return (round(valor * 1000, 4), "mg" + u[1:])
    if u in {"mcg", "ug", "mcg/ml", "ug/ml"}:
        return (round(valor / 1000, 6), "mg" + ("/ml" if u.endswith("/ml") else ""))
    return (round(valor, 4), u)


def forcas_do_texto(texto: Any) -> Set[Tuple[float, str]]:
    saida: Set[Tuple[float, str]] = set()
    for m in _RE_FORCA.finditer(norm(texto)):
        try:
            valor = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        saida.add(_forca(valor, m.group(2) + ("/ml" if m.group(3) else "")))
    return saida


def forcas_da_apresentacao(ap: Any) -> Set[Tuple[float, str]]:
    saida: Set[Tuple[float, str]] = set()
    valor = _ler(ap, "concentracao_valor")
    unidade = _ler(ap, "concentracao_unidade")
    if valor is not None and unidade:
        try:
            saida.add(_forca(float(valor), unidade))
        except (TypeError, ValueError):
            pass
    volume = _ler(ap, "volume_valor")
    if volume is not None and norm(_ler(ap, "volume_unidade")) == "ml":
        try:
            saida.add((round(float(volume), 4), "ml"))
        except (TypeError, ValueError):
            pass
    if not saida:
        texto = re.sub(r"\([^)]*\)", " ", str(_ler(ap, "concentracao") or ""))
        saida |= forcas_do_texto(texto)
    return saida


# ───────────────────────── apresentações do produto ────────────────────────

_FORMAS_VAZIAS = {"n/a", "na", "apresentacao", "-", "."}


def rotulo_vetsmart(ap: Any, produto_nome: Any) -> str:
    """Rótulo no formato do VetSmart, sem repetir o nome do produto.

    "Vermivet Filhote, frasco (20 mL), com seringa dosadora" vira
    "Frasco (20 mL), com seringa dosadora".
    """
    forma = str(_ler(ap, "forma") or "").strip()
    texto = str(_ler(ap, "concentracao") or "").strip() or str(_ler(ap, "nome_variante") or "").strip()
    resto = remover_prefixo_nome(texto, produto_nome)
    if norm(forma) in _FORMAS_VAZIAS:
        forma = ""
    antes, depois = resto, ""
    corte = resto.find("(")
    if corte >= 0:
        antes, depois = resto[:corte], resto[corte:]
    antes = antes.strip(_SEPARADORES)
    depois = depois.strip()
    if forma and norm(forma) in norm(antes):
        forma = ""
    cabeca = ", ".join(parte for parte in (antes, forma) if parte)
    rotulo = re.sub(r"\s+", " ", " ".join(parte for parte in (cabeca, depois) if parte)).strip()
    if not rotulo:
        rotulo = forma or texto
    return rotulo[:1].upper() + rotulo[1:]


def _chave_apresentacao(forma: Any, texto: Any, produto_nome: Any) -> Tuple[str, str]:
    resto = norm(remover_prefixo_nome(texto, produto_nome))
    return (norm(forma), re.sub(r"[\s,;]+", " ", resto).strip())


def _dono_por_nome(rotulo: str, nomes: Sequence[str]) -> Optional[str]:
    """Nome de produto mais longo que prefixa o rótulo (com fronteira)."""
    melhor = None
    for nome in nomes:
        if not nome or not rotulo.startswith(nome):
            continue
        if len(rotulo) > len(nome) and rotulo[len(nome)].isalnum():
            continue
        if melhor is None or len(nome) > len(melhor):
            melhor = nome
    return melhor


def separar_linhas(medicamento: Any, produto: Dict[str, Any]) -> Tuple[List[Any], List[Any]]:
    """(linhas do produto, linhas sem dono) entre as apresentações do medicamento.

    Linha de outro produto não entra em nenhuma das duas listas.
    """
    pids = pids_do_produto(produto)
    alvo = norm(produto.get("nome"))
    outros = [
        nome for nome in (norm(p.get("nome")) for p in produtos(medicamento))
        if nome != alvo
    ]
    proprias: List[Any] = []
    avulsas: List[Any] = []
    for ap in (getattr(medicamento, "apresentacoes", None) or []):
        ap_pid = getattr(ap, "vetsmart_produto_id", None)
        if ap_pid is not None:
            if ap_pid in pids:
                proprias.append(ap)
            continue
        comercial = norm(getattr(ap, "nome_comercial", None))
        if comercial:
            if comercial == alvo:
                proprias.append(ap)
            elif comercial not in outros:
                avulsas.append(ap)
            continue
        rotulo = norm(getattr(ap, "nome_variante", None) or getattr(ap, "concentracao", None))
        dono = _dono_por_nome(rotulo, [alvo] + outros)
        if dono == alvo:
            proprias.append(ap)
        elif dono is None:
            avulsas.append(ap)
    return proprias, avulsas


def apresentacoes_do_produto(medicamento: Any, produto: Dict[str, Any]) -> Tuple[List[Any], List[Any]]:
    """Apresentações do produto (linhas reais + retrato) e as linhas sem dono."""
    proprias, avulsas = separar_linhas(medicamento, produto)
    nome = produto.get("nome")
    pid = pid_do_produto(produto)
    vistos: Dict[Tuple[str, str], Any] = {}
    lista: List[Any] = []

    def _prioridade(ap: Any) -> Tuple[bool, int]:
        return (getattr(ap, "concentracao_valor", None) is None, getattr(ap, "id", 0) or 0)

    for ap in sorted(proprias, key=_prioridade):
        texto = getattr(ap, "concentracao", None) or getattr(ap, "nome_variante", None)
        chave = _chave_apresentacao(getattr(ap, "forma", None), texto, nome)
        if chave in vistos:
            continue
        vistos[chave] = ap
        lista.append(ap)

    brutas = produto.get("apresentacoes")
    for indice, bruta in enumerate(brutas if isinstance(brutas, list) else []):
        if not isinstance(bruta, dict):
            continue
        forma = str(bruta.get("forma") or "").strip()
        concentracao = str(bruta.get("concentracao") or "").strip()
        if not forma and not concentracao:
            continue
        chave = _chave_apresentacao(forma, concentracao or bruta.get("nome_variante"), nome)
        if chave in vistos:
            continue
        sintetica = SimpleNamespace(
            id=ID_SINTETICO_BASE + (pid or 0) * 100 + indice,
            medicamento_id=getattr(medicamento, "id", None),
            forma=forma[:50],
            concentracao=concentracao,
            nome_variante=bruta.get("nome_variante"),
            concentracao_valor=bruta.get("concentracao_valor"),
            concentracao_unidade=bruta.get("concentracao_unidade"),
            volume_valor=bruta.get("volume_valor"),
            volume_unidade=bruta.get("volume_unidade"),
            nome_comercial=nome,
            fabricante=produto.get("fabricante"),
            vetsmart_produto_id=pid,
            sintetica=True,
        )
        vistos[chave] = sintetica
        lista.append(sintetica)
    return lista, avulsas


# ───────────────────────── doses do produto ────────────────────────────────

_CAMPOS_DOSE = (
    "id", "medicamento_id", "especie", "faixa_peso", "via", "dose", "frequencia",
    "duracao", "observacao", "especie_code", "peso_min_kg", "peso_max_kg",
    "dose_min", "dose_max", "dose_unidade", "intervalo_horas",
    "intervalo_min_horas", "intervalo_max_horas", "duracao_min_dias",
    "duracao_max_dias", "dose_raw_text", "fonte", "confianca", "indicacao",
)


def _texto_dose(valor: Any) -> str:
    texto = norm(valor)
    texto = re.sub(r"\s*/\s*", "/", texto)
    return re.sub(r"\s*[-–]\s*", "-", texto)


def _chave_dose(dose: Any) -> Tuple[str, str, str, str, str]:
    return (
        _texto_dose(_ler(dose, "dose_raw_text") or _ler(dose, "dose")),
        norm(_ler(dose, "frequencia")),
        norm(_ler(dose, "duracao")),
        str(_ler(dose, "especie_code") or "").upper(),
        str(_ler(dose, "dose_unidade") or "").upper(),
    )


_RE_RAZAO_POR_KG = re.compile(
    r"^(\d+(?:[.,]\d+)?)(?:-(\d+(?:[.,]\d+)?))?\s*[^\d/]+/(\d+(?:[.,]\d+)?)\s*kg$"
)


def _restaurar_razao(copia: SimpleNamespace) -> None:
    """Devolve a precisão de "1 comprimido / 30 kg".

    A coluna guarda três casas: 1/30 vira 0,033 e um cão de 30 kg recebe
    0,99 comprimido. O texto da bula tem a razão exata.
    """
    if not str(copia.dose_unidade or "").upper().endswith("_KG"):
        return
    m = _RE_RAZAO_POR_KG.match(_texto_dose(copia.dose_raw_text or copia.dose))
    if not m:
        return
    try:
        denominador = float(m.group(3).replace(",", "."))
        minimo = float(m.group(1).replace(",", ".")) / denominador
        maximo = float(m.group(2).replace(",", ".")) / denominador if m.group(2) else minimo
        gravado_min = float(copia.dose_min)
        gravado_max = float(copia.dose_max) if copia.dose_max is not None else gravado_min
    except (TypeError, ValueError, ZeroDivisionError):
        return
    # Só afina o que já estava gravado; não corrige linha que diz outra coisa.
    if abs(gravado_min - minimo) < 0.001 and abs(gravado_max - maximo) < 0.001:
        copia.dose_min = minimo
        copia.dose_max = maximo


def _copiar_dose(origem: Any, id_sintetico: Optional[int] = None) -> SimpleNamespace:
    """Cópia solta da dose. Nunca altera a linha do banco."""
    copia = SimpleNamespace(**{campo: _ler(origem, campo) for campo in _CAMPOS_DOSE})
    if copia.id is None:
        copia.id = id_sintetico
    copia.apresentacao_ids = None
    copia.variante = None
    copia.variante_nao_resolvida = False
    _restaurar_razao(copia)
    return copia


def _texto_completo(curto: Any, completo: Any) -> Any:
    """O texto integral do VetSmart quando o campo gravado foi cortado no meio."""
    if not curto or not completo:
        return curto
    a, b = norm(curto), norm(completo)
    if len(str(curto)) >= 90 and len(b) > len(a) and b.startswith(a):
        return completo
    return curto


def _vincular_variantes(
    doses: List[SimpleNamespace],
    dosagens: List[Dict[str, Optional[str]]],
    apresentacoes: List[Any],
) -> None:
    """Marca em cada dose as apresentações a que o cabeçalho do VetSmart a prende.

    O cabeçalho só conta como variante quando cita uma concentração ou um
    volume ("Vermivet Plus 660 mg", "Banni 0,32 mL – até 5kg"). "Canino",
    "Glaucoma" e "Até 5 kg" agrupam doses, mas não escolhem apresentação.
    """
    def _variante(entrada: Dict[str, Optional[str]]) -> Optional[str]:
        for campo in ("grupo", "rotulo"):
            texto = entrada.get(campo)
            if texto and forcas_do_texto(texto):
                return texto
        return None

    cabecalhos: Dict[str, Tuple[int, ...]] = {}
    for entrada in dosagens:
        variante = _variante(entrada)
        if not variante or variante in cabecalhos:
            continue
        forcas = forcas_do_texto(variante)
        cabecalhos[variante] = tuple(sorted(
            ap.id for ap in apresentacoes if forcas & forcas_da_apresentacao(ap)
        ))
    disputa = Counter(ap_id for ids in cabecalhos.values() for ap_id in ids)
    if any(total > 1 for total in disputa.values()):
        # Dois cabeçalhos reivindicam a mesma apresentação: melhor não
        # vincular nada a arriscar a dose de uma concentração em outra.
        cabecalhos = {variante: () for variante in cabecalhos}

    for dose in doses:
        alvo = _texto_dose(dose.dose_raw_text or dose.dose)
        candidatas = [e for e in dosagens if _texto_dose(e["dose"]) == alvo]
        if not candidatas:
            continue
        for campo in ("faixa_peso", "indicacao"):
            valor = norm(getattr(dose, campo, None))
            if not valor:
                continue
            filtradas = [e for e in candidatas if norm(e["rotulo"]) == valor]
            if filtradas:
                candidatas = filtradas
        codigo = str(dose.especie_code or "").upper()
        if codigo in {"CAES", "GATOS"}:
            filtradas = [
                e for e in candidatas
                if especie_code(e["especie"]) in {None, "AMBOS", codigo}
            ]
            if filtradas:
                candidatas = filtradas
        variantes = {_variante(e) for e in candidatas}
        if len(variantes) != 1:
            continue
        variante = next(iter(variantes))
        if not variante:
            continue
        dose.variante = variante
        ids = cabecalhos.get(variante) or ()
        if ids:
            dose.apresentacao_ids = ids
        else:
            dose.variante_nao_resolvida = True


def doses_do_produto(
    medicamento: Any,
    produto: Dict[str, Any],
    apresentacoes: List[Any],
) -> List[SimpleNamespace]:
    """Doses que valem para o produto.

    A tabela ``dose_medicamento`` é a referência (é nela que a curadoria
    acontece); o retrato do produto diz quais linhas são dele e completa o que
    a tabela não tem.
    """
    alvo = norm(produto.get("nome"))
    outros = [p for p in produtos(medicamento) if norm(p.get("nome")) != alvo]
    linhas = list(getattr(medicamento, "doses", None) or [])
    brutas = [d for d in (produto.get("doses") or []) if isinstance(d, dict)]
    pid = pid_do_produto(produto) or 0
    admin = administracao_do_produto(produto)
    dosagens = linhas_de_dosagem(admin["dosagens"])

    def _sinteticas(itens: List[Dict[str, Any]]) -> List[SimpleNamespace]:
        return [
            _copiar_dose(item, ID_SINTETICO_BASE + pid * 100 + indice)
            for indice, item in enumerate(itens)
        ]

    if not outros:
        doses = [_copiar_dose(linha) for linha in linhas] if linhas else _sinteticas(brutas)
    elif brutas:
        chaves = {_chave_dose(d) for d in brutas}
        chaves_linhas = {_chave_dose(linha) for linha in linhas}
        doses = [_copiar_dose(linha) for linha in linhas if _chave_dose(linha) in chaves]
        doses += _sinteticas([d for d in brutas if _chave_dose(d) not in chaves_linhas])
    else:
        # Produto sem dose estruturada no retrato: aceita só a linha cujo texto
        # está publicado na "Dosagem indicada" dele e que não é de outro produto.
        de_outros = {
            _chave_dose(d)
            for outro in outros
            for d in (outro.get("doses") or []) if isinstance(d, dict)
        }
        publicadas = {_texto_dose(e["dose"]) for e in dosagens}
        doses = [
            _copiar_dose(linha) for linha in linhas
            if _chave_dose(linha) not in de_outros
            and _texto_dose(getattr(linha, "dose_raw_text", None) or getattr(linha, "dose", None)) in publicadas
        ]

    frequencia = " ".join(admin["frequencia"]).strip()
    duracao = " ".join(admin["duracao"]).strip()
    for dose in doses:
        dose.frequencia = _texto_completo(dose.frequencia, frequencia)
        dose.duracao = _texto_completo(dose.duracao, duracao)
    _vincular_variantes(doses, dosagens, apresentacoes)
    return doses


# ───────────────────────── o medicamento escopado ──────────────────────────


class MedicamentoEscopado:
    """O medicamento canônico visto pelo recorte de um produto."""

    escopo_produto = True

    def __init__(
        self,
        base: Any,
        produto: Dict[str, Any],
        apresentacoes: List[Any],
        avulsas: List[Any],
    ) -> None:
        self._base = base
        self.produto = produto
        self.produto_nome = (produto.get("nome") or "").strip()
        self.produto_implicito = bool(produto.get("implicito"))
        self.apresentacoes = apresentacoes
        self.apresentacoes_avulsas = avulsas
        admin = administracao_do_produto(produto)
        self.dosagens = linhas_de_dosagem(admin["dosagens"])
        self.doses = doses_do_produto(base, produto, apresentacoes)

        def _preferir(*valores: Any) -> Any:
            for valor in valores:
                if isinstance(valor, str):
                    valor = valor.strip()
                if valor:
                    return valor
            return None

        self.via_administracao = _preferir(
            " / ".join(admin["via"]),
            produto.get("via_administracao"),
            getattr(base, "via_administracao", None),
        )
        self.frequencia = _preferir(
            " ".join(admin["frequencia"]),
            produto.get("frequencia"),
            getattr(base, "frequencia", None),
        )
        self.duracao_tratamento = _preferir(
            " ".join(admin["duracao"]),
            produto.get("duracao_tratamento"),
            getattr(base, "duracao_tratamento", None),
        )
        self.dosagem_recomendada = _preferir(
            produto.get("dosagem_recomendada"),
            getattr(base, "dosagem_recomendada", None),
        )
        self.classificacao = _preferir(
            produto.get("classificacao"), getattr(base, "classificacao", None)
        )
        self.vetsmart_produto_id = pid_do_produto(produto) or getattr(base, "vetsmart_produto_id", None)
        conteudo = getattr(base, "conteudo_estruturado", None)
        if self.produto_implicito:
            self.conteudo_estruturado = conteudo
        else:
            self.conteudo_estruturado = {
                **(conteudo if isinstance(conteudo, dict) else {}),
                "produtos_vetsmart": [produto],
            }
        # O cache de produtos do medicamento base não vale para o recorte.
        self._produtos_vetsmart_cache = None

    def __getattr__(self, nome: str) -> Any:
        if nome.startswith("__") or nome == "_base":
            raise AttributeError(nome)
        return getattr(self._base, nome)


def escopo_de(medicamento: Any, nome_comercial: Any = None) -> Optional[MedicamentoEscopado]:
    """O recorte por produto, ou None quando o medicamento deve ser visto inteiro.

    Sem nome comercial, só há recorte se o medicamento for um produto único.
    Produto sem apresentação própria não tem recorte: não há o que mostrar
    que seja dele.
    """
    if medicamento is None:
        return None
    if isinstance(medicamento, MedicamentoEscopado):
        return medicamento
    if norm(nome_comercial):
        produto = resolver_produto(medicamento, nome_comercial)
    else:
        produto = produto_implicito(medicamento)
    if produto is None:
        return None
    apresentacoes, avulsas = apresentacoes_do_produto(medicamento, produto)
    if not apresentacoes:
        return None
    return MedicamentoEscopado(medicamento, produto, apresentacoes, avulsas)
