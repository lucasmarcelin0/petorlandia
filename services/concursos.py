"""Regras dos simulados de concurso: quem acessa, leitura do gabarito e correção."""
from __future__ import annotations

import re
import zlib

from models.concursos import ALTERNATIVAS, ANULADA, ConcursoProva, ConcursoTentativa

MAX_QUESTOES = 200
MAX_PDF_BYTES = 15 * 1024 * 1024


def _admin(user):
    return (getattr(user, "role", None) or "").lower() == "admin"


def pode_gerenciar(user):
    """Envia provas e acompanha o progresso: administrador ou dono de clínica."""
    if not getattr(user, "is_authenticated", False):
        return False
    return _admin(user) or bool(getattr(user, "clinicas", None))


def pode_estudar(user):
    """Resolve provas: estagiária (marcada na conta ou com estágio ativo) e quem gerencia."""
    if not getattr(user, "is_authenticated", False):
        return False
    from helpers import is_active_intern, is_intern_account

    return pode_gerenciar(user) or is_intern_account(user) or is_active_intern(user)


def alunos_ids_visiveis(gestor):
    """Contas cujo progresso o gestor acompanha. ``None`` = todas (administrador)."""
    if _admin(gestor):
        return None
    from models import ClinicStaff

    clinicas = [c.id for c in getattr(gestor, "clinicas", None) or []]
    if not clinicas:
        return set()
    return {s.user_id for s in ClinicStaff.query.filter(ClinicStaff.clinic_id.in_(clinicas))}


def pode_ver_tentativa(user, tentativa):
    if tentativa.user_id == getattr(user, "id", None):
        return True
    if not pode_gerenciar(user):
        return False
    visiveis = alunos_ids_visiveis(user)
    return visiveis is None or tentativa.user_id in visiveis


# --- Gabarito ---------------------------------------------------------------

_PAR = re.compile(r"(?<!\d)(\d{1,3})\s*[-–—.:)]?\s*(ANULADA|[A-Ea-e*Xx])(?![A-Za-z])")


def ler_gabarito(texto, total=None):
    """``"1 - C 2 - D ..."`` → ``"CD..."``; questão sem resposta vira ``-``.

    Aceita também só a sequência de letras (``"CDBEB..."``). ``*``, ``X`` e
    ``ANULADA`` marcam questão anulada.
    """
    texto = (texto or "").strip()
    respostas = {}
    for numero, letra in _PAR.findall(texto):
        numero = int(numero)
        if 1 <= numero <= MAX_QUESTOES:
            letra = letra.upper()
            respostas[numero] = ANULADA if letra in {"*", "X", "ANULADA"} else letra
    if not respostas:
        seq = re.sub(r"[^A-Ea-eXx*]", "", texto).upper().replace("*", ANULADA)
        respostas = {i + 1: letra for i, letra in enumerate(seq[:MAX_QUESTOES])}
    total = int(total or 0) or (max(respostas) if respostas else 0)
    total = min(total, MAX_QUESTOES)
    return "".join(respostas.get(i, "-") for i in range(1, total + 1))


def texto_do_pdf(dados):
    """Texto simples de um PDF (operadores ``Tj``/``TJ`` em streams Flate).

    Leve e sem dependência: serve para gabaritos de uma página. O que não sair
    daqui a pessoa completa na tela "Conferir gabarito".
    """
    partes = []
    for bloco in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", dados or b"", re.S):
        try:
            conteudo = zlib.decompress(bloco.group(1))
        except zlib.error:
            continue
        for texto in re.finditer(rb"BT(.*?)ET", conteudo, re.S):
            linha = []
            for s in re.finditer(rb"\(((?:\\.|[^\\)])*)\)\s*Tj|\[((?:\\.|[^\]])*)\]\s*TJ", texto.group(1), re.S):
                if s.group(1) is not None:
                    linha.append(s.group(1))
                else:
                    linha.extend(re.findall(rb"\(((?:\\.|[^\\)])*)\)", s.group(2)))
            partes.append(b"".join(linha).decode("latin-1"))
    return "\n".join(partes)


def eh_pdf(dados):
    return bool(dados) and dados[:5] == b"%PDF-"


# --- Correção ---------------------------------------------------------------

def corrigir(prova, marcacoes):
    """Acertos: letra igual ao gabarito; anulada vale para todos."""
    acertos = 0
    for numero in range(1, prova.total_questoes + 1):
        certa = prova.resposta_certa(numero)
        if certa == ANULADA or (certa in ALTERNATIVAS and marcacoes.get(numero) == certa):
            acertos += 1
    return acertos


def folha(prova, tentativa, revelar=False):
    """Linhas da folha de respostas: número, marcada, certa e situação."""
    marcacoes = tentativa.marcacoes if tentativa else {}
    linhas = []
    for numero in range(1, prova.total_questoes + 1):
        marcada = marcacoes.get(numero)
        certa = prova.resposta_certa(numero) if revelar else None
        if not revelar:
            situacao = None
        elif certa == ANULADA:
            situacao = "anulada"
        elif not marcada:
            situacao = "branco"
        else:
            situacao = "certa" if marcada == certa else "errada"
        linhas.append({"numero": numero, "marcada": marcada, "certa": certa, "situacao": situacao})
    return linhas


def percentual(acertos, total):
    return round(100 * (acertos or 0) / total) if total else 0


def tentativa_aberta(prova, user):
    return (ConcursoTentativa.query.filter_by(prova_id=prova.id, user_id=user.id, entregue_em=None)
            .order_by(ConcursoTentativa.id.desc()).first())


def resumo_por_prova(user):
    """``{prova_id: {"melhor": %, "entregas": n, "aberta": tentativa}}`` da conta."""
    resumo = {}
    for t in ConcursoTentativa.query.filter_by(user_id=user.id).order_by(ConcursoTentativa.id):
        item = resumo.setdefault(t.prova_id, {"melhor": None, "entregas": 0, "aberta": None, "ultima": None})
        if t.entregue_em:
            pct = percentual(t.acertos, t.prova.total_questoes)
            item["entregas"] += 1
            item["ultima"] = t
            item["melhor"] = pct if item["melhor"] is None else max(item["melhor"], pct)
        else:
            item["aberta"] = t
    return resumo


def provas_ativas():
    return ConcursoProva.query.filter_by(ativo=True).order_by(ConcursoProva.criado_em.desc()).all()
