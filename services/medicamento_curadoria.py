"""Curadoria offline de medicamentos priorizados por prescrições reais.

Esta camada não chama IA nem pesquisa web. Ela prepara a fila segura para uma
curadoria posterior: ranqueia o que é mais usado, resolve aliases sem gravar
cache novo e aponta lacunas objetivas no bulário.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import selectinload

from models import (
    ApresentacaoMedicamento,
    BlocoPrescricao,
    CuradoriaMedicamentoReview,
    DoseMedicamento,
    Medicamento,
    Prescricao,
    PrescricaoAliasMedicamento,
)


_DASH_RE = re.compile(r"[\u2010-\u2015\u2212]+")
_SPACE_RE = re.compile(r"\s+")


def normalizar_nome_prescrito(nome: str | None) -> str:
    """Chave estável para agrupar nomes prescritos com variações superficiais."""
    texto = str(nome or "").strip()
    texto = _DASH_RE.sub(" - ", texto)
    nfkd = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    texto = re.sub(r"[^\w%/.,+\- ]+", " ", texto)
    texto = re.sub(r"\s*-\s*", " - ", texto)
    texto = _SPACE_RE.sub(" ", texto).strip()
    return texto[:180]


def _prefixo_prescricao(nome: str) -> str:
    chave = normalizar_nome_prescrito(nome)
    return chave.split(" - ", 1)[0].strip()


def _vazio(valor: Any) -> bool:
    return not str(valor or "").strip()


def _parece_texto_livre(valor: Any) -> bool:
    texto = str(valor or "").strip().lower()
    if not texto:
        return True
    return any(t in texto for t in ("conforme", "orienta", "criterio", "critério", "bula"))


@dataclass
class RankingCuradoriaItem:
    nome_normalizado: str
    nome_prescrito_principal: str
    variantes: list[str]
    total_prescricoes: int
    ultima_prescricao_em: Optional[datetime]
    medicamento_id: Optional[int]
    medicamento_nome: Optional[str]
    confianca_alias: str
    score_lacunas: int
    prioridade: int
    resumo_historico: dict[str, Any]
    diagnostico: dict[str, Any]
    proposta: dict[str, Any]
    fontes: list[dict[str, Any]]


def _resolver_alias_offline(nome_prescrito: str, session) -> tuple[Optional[int], str]:
    """Resolve sem persistir em `prescricao_alias_medicamento`.

    Evita efeitos colaterais no dry-run e funciona no SQLite de testes.
    """
    nome = str(nome_prescrito or "").strip()
    if not nome:
        return None, "sem_match"

    alias = (
        session.query(PrescricaoAliasMedicamento)
        .filter(PrescricaoAliasMedicamento.nome_prescrito == nome)
        .first()
    )
    if alias is not None:
        return alias.medicamento_id, alias.confianca or "cache"

    chave = normalizar_nome_prescrito(nome)
    prefixo = _prefixo_prescricao(nome)
    meds = session.query(Medicamento.id, Medicamento.nome).all()

    for med_id, med_nome in meds:
        if normalizar_nome_prescrito(med_nome) == chave:
            return med_id, "exato"

    if prefixo and prefixo != chave:
        candidatos = []
        for med_id, med_nome in meds:
            med_norm = normalizar_nome_prescrito(med_nome)
            if med_norm == prefixo or med_norm.startswith(prefixo):
                candidatos.append((len(med_norm), med_id))
        if candidatos:
            candidatos.sort()
            return candidatos[0][1], "prefixo"

    busca = prefixo or chave
    if len(busca) >= 4:
        ap = (
            session.query(ApresentacaoMedicamento)
            .filter(func.lower(ApresentacaoMedicamento.nome_variante).like(f"{busca}%"))
            .first()
        )
        if ap:
            return ap.medicamento_id, "variante"

    candidatos = []
    for med_id, med_nome in meds:
        med_norm = normalizar_nome_prescrito(med_nome)
        if len(med_norm) >= 6 and chave.startswith(med_norm):
            candidatos.append((len(med_norm), med_id))
    if candidatos:
        candidatos.sort(reverse=True)
        return candidatos[0][1], "substring"

    return None, "sem_match"


def _medicamento_snapshot(medicamento: Medicamento | None) -> dict[str, Any]:
    if not medicamento:
        return {
            "tem_cadastro": False,
            "tem_apresentacoes": False,
            "tem_apresentacao_calculavel": False,
            "tem_doses": False,
            "tem_bula_ou_fonte": False,
        }
    apresentacoes = list(medicamento.apresentacoes or [])
    doses = list(medicamento.doses or [])
    return {
        "tem_cadastro": True,
        "medicamento_id": medicamento.id,
        "nome": medicamento.nome,
        "principio_ativo": medicamento.principio_ativo,
        "classificacao": medicamento.classificacao,
        "tem_apresentacoes": bool(apresentacoes),
        "total_apresentacoes": len(apresentacoes),
        "tem_apresentacao_calculavel": any(ap.concentracao_valor is not None for ap in apresentacoes),
        "apresentacoes_sem_concentracao": sum(1 for ap in apresentacoes if ap.concentracao_valor is None),
        "tem_doses": bool(doses),
        "total_doses": len(doses),
        "tem_bula_ou_fonte": bool(medicamento.bula or medicamento.vetsmart_produto_id),
    }


def _montar_diagnostico(
    *,
    historico: dict[str, Any],
    medicamento: Medicamento | None,
    confianca_alias: str,
) -> tuple[int, dict[str, Any]]:
    snapshot = _medicamento_snapshot(medicamento)
    problemas: list[dict[str, str]] = []
    score = 0

    def add(codigo: str, nivel: str, titulo: str, detalhe: str, peso: int) -> None:
        nonlocal score
        problemas.append({
            "codigo": codigo,
            "nivel": nivel,
            "titulo": titulo,
            "detalhe": detalhe,
        })
        score += peso

    if not snapshot["tem_cadastro"]:
        add("SEM_MEDICAMENTO_CANONICO", "critico", "Sem medicamento canônico", "Nome prescrito ainda não foi ligado ao bulário.", 30)
    elif confianca_alias in {"substring", "variante", "sem_match"}:
        add("ALIAS_INCERTO", "atencao", "Alias precisa de revisão", f"Resolução atual: {confianca_alias}.", 12)

    if snapshot["tem_cadastro"] and not snapshot["tem_apresentacoes"]:
        add("SEM_APRESENTACOES", "atencao", "Sem apresentações", "O medicamento não tem apresentação estruturada para seleção na prescrição.", 18)
    elif snapshot["tem_cadastro"] and not snapshot["tem_apresentacao_calculavel"]:
        add("APRESENTACOES_SEM_CONCENTRACAO", "informativo", "Apresentações sem concentração", "Pode ser correto para doses por unidade, mas precisa ser classificado.", 8)

    if snapshot["tem_cadastro"] and not snapshot["tem_doses"]:
        add("SEM_DOSE_ESTRUTURADA", "atencao", "Sem dose estruturada", "Não há protocolo de dose estruturado no bulário.", 20)

    if not snapshot["tem_bula_ou_fonte"]:
        add("SEM_FONTE_TECNICA", "atencao", "Sem fonte técnica", "Não há bula/link VetSmart associado no cadastro atual.", 12)

    if historico["proporcao_campos_incompletos"] >= 0.5:
        add("HISTORICO_INCOMPLETO", "atencao", "Histórico incompleto", "Metade ou mais das prescrições tem dose, frequência ou duração ausente.", 10)

    if historico["proporcao_texto_livre"] >= 0.5:
        add("USO_COMO_TEXTO_LIVRE", "informativo", "Uso frequente como texto livre", "Prescrições usam termos como conforme bula/orientação/critério.", 5)

    return score, {
        "snapshot_bulario": snapshot,
        "problemas": problemas,
        "requer_revisao": bool(problemas),
        "modo_analise": "offline_sem_ia",
    }


def _proposta_offline(item: dict[str, Any], medicamento: Medicamento | None) -> dict[str, Any]:
    acoes = ["pesquisar_fontes_confiaveis", "revisar_historico_prescricoes"]
    if medicamento is None:
        acoes.insert(0, "resolver_medicamento_canonico")
    else:
        if not (medicamento.apresentacoes or []):
            acoes.append("estruturar_apresentacoes")
        if not (medicamento.doses or []):
            acoes.append("estruturar_posologia")
    return {
        "origem": "OFFLINE",
        "confianca": "BAIXA",
        "resumo": "Priorizado por uso real. Aguardando pesquisa com fontes externas e/ou revisão humana.",
        "acoes_sugeridas": acoes,
        "aplicar_automaticamente": False,
        "observacao_segura": "Nenhum dado clínico oficial foi alterado por esta etapa.",
    }


def gerar_ranking_curadoria(session, limite: int = 25) -> list[RankingCuradoriaItem]:
    rows = (
        session.query(Prescricao)
        .outerjoin(BlocoPrescricao, BlocoPrescricao.id == Prescricao.bloco_id)
        .all()
    )
    grupos: dict[str, list[Prescricao]] = defaultdict(list)
    for prescricao in rows:
        chave = normalizar_nome_prescrito(prescricao.medicamento)
        if chave:
            grupos[chave].append(prescricao)

    resultado: list[RankingCuradoriaItem] = []
    med_cache: dict[int, Medicamento] = {}

    for chave, prescricoes in grupos.items():
        nomes = Counter((p.medicamento or "").strip() for p in prescricoes if (p.medicamento or "").strip())
        nome_principal = nomes.most_common(1)[0][0]
        med_id, confianca = _resolver_alias_offline(nome_principal, session)
        medicamento = None
        if med_id:
            if med_id not in med_cache:
                med_cache[med_id] = session.get(
                    Medicamento,
                    med_id,
                    options=[
                        selectinload(Medicamento.apresentacoes),
                        selectinload(Medicamento.doses),
                    ],
                )
            medicamento = med_cache.get(med_id)

        total = len(prescricoes)
        datas = [p.data_prescricao for p in prescricoes if p.data_prescricao]
        ultima = max(datas) if datas else None
        incompletos = [
            p for p in prescricoes
            if _vazio(p.dosagem) or _vazio(p.frequencia) or _vazio(p.duracao)
        ]
        texto_livre = [
            p for p in prescricoes
            if _parece_texto_livre(p.dosagem) or _parece_texto_livre(p.frequencia) or _parece_texto_livre(p.duracao)
        ]
        doses = Counter(str(p.dosagem or "").strip() for p in prescricoes if str(p.dosagem or "").strip())
        frequencias = Counter(str(p.frequencia or "").strip() for p in prescricoes if str(p.frequencia or "").strip())
        duracoes = Counter(str(p.duracao or "").strip() for p in prescricoes if str(p.duracao or "").strip())
        historico = {
            "variantes_nome": nomes.most_common(8),
            "amostras_dosagem": doses.most_common(8),
            "amostras_frequencia": frequencias.most_common(8),
            "amostras_duracao": duracoes.most_common(8),
            "total_prescricoes": total,
            "prescricoes_incompletas": len(incompletos),
            "proporcao_campos_incompletos": round(len(incompletos) / total, 3) if total else 0,
            "prescricoes_texto_livre": len(texto_livre),
            "proporcao_texto_livre": round(len(texto_livre) / total, 3) if total else 0,
        }
        score_lacunas, diagnostico = _montar_diagnostico(
            historico=historico,
            medicamento=medicamento,
            confianca_alias=confianca,
        )
        prioridade = (total * 1000) + score_lacunas
        proposta = _proposta_offline({"nome": nome_principal}, medicamento)
        fontes = [{
            "tipo": "historico_interno",
            "rotulo": "Histórico de prescrições do PetOrlândia",
            "status": "coletado",
        }]
        if medicamento and medicamento.vetsmart_produto_id:
            fontes.append({
                "tipo": "fonte_tecnica_existente",
                "rotulo": "VetSmart associado no cadastro",
                "status": "existente",
            })

        resultado.append(RankingCuradoriaItem(
            nome_normalizado=chave,
            nome_prescrito_principal=nome_principal,
            variantes=[nome for nome, _ in nomes.most_common(8)],
            total_prescricoes=total,
            ultima_prescricao_em=ultima,
            medicamento_id=med_id,
            medicamento_nome=getattr(medicamento, "nome", None),
            confianca_alias=confianca,
            score_lacunas=score_lacunas,
            prioridade=prioridade,
            resumo_historico=historico,
            diagnostico=diagnostico,
            proposta=proposta,
            fontes=fontes,
        ))

    def _data_ordem(item: RankingCuradoriaItem) -> float:
        if not item.ultima_prescricao_em:
            return 0.0
        try:
            return item.ultima_prescricao_em.timestamp()
        except Exception:
            return 0.0

    resultado.sort(key=lambda item: (item.total_prescricoes, _data_ordem(item), item.score_lacunas), reverse=True)
    return resultado[:limite]


def sincronizar_fila_curadoria(session, limite: int = 25, dry_run: bool = True) -> dict[str, Any]:
    ranking = gerar_ranking_curadoria(session, limite=limite)
    criados = atualizados = 0
    preview: list[dict[str, Any]] = []

    for pos, item in enumerate(ranking, start=1):
        row = (
            session.query(CuradoriaMedicamentoReview)
            .filter(CuradoriaMedicamentoReview.nome_normalizado == item.nome_normalizado)
            .first()
        )
        payload = {
            "nome_prescrito_principal": item.nome_prescrito_principal,
            "medicamento_id": item.medicamento_id,
            "prioridade": pos,
            "total_prescricoes": item.total_prescricoes,
            "ultima_prescricao_em": item.ultima_prescricao_em,
            "confianca_alias": item.confianca_alias,
            "resumo_historico": item.resumo_historico,
            "diagnostico": item.diagnostico,
            "proposta": item.proposta,
            "fontes": item.fontes,
        }
        if row is None:
            criados += 1
        else:
            atualizados += 1
        preview.append({
            "posicao": pos,
            "nome": item.nome_prescrito_principal,
            "medicamento_id": item.medicamento_id,
            "medicamento_nome": item.medicamento_nome,
            "total_prescricoes": item.total_prescricoes,
            "confianca_alias": item.confianca_alias,
            "problemas": [p["codigo"] for p in item.diagnostico.get("problemas", [])],
        })
        if dry_run:
            continue
        if row is None:
            row = CuradoriaMedicamentoReview(
                nome_normalizado=item.nome_normalizado,
                status="pendente",
            )
            session.add(row)
        for key, value in payload.items():
            setattr(row, key, value)

    if not dry_run:
        session.commit()

    return {
        "dry_run": dry_run,
        "limite": limite,
        "total_candidatos": len(ranking),
        "criados": criados,
        "atualizados": atualizados,
        "preview": preview,
    }


def listar_reviews(session, status: str | None = None, limite: int = 100) -> list[CuradoriaMedicamentoReview]:
    query = session.query(CuradoriaMedicamentoReview).order_by(
        CuradoriaMedicamentoReview.prioridade.asc(),
        CuradoriaMedicamentoReview.total_prescricoes.desc(),
    )
    if status:
        query = query.filter(CuradoriaMedicamentoReview.status == status)
    return query.limit(limite).all()
