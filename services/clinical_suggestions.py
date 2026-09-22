"""Serviços de sugestão clínica baseada em protocolos curados."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from datetime import date, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from extensions import db
from models import AuditoriaSugestaoClinica, ProtocoloClinico


# Pre-compiled regex patterns for token normalization
_RE_NON_ALPHANUMERIC_SPACES = re.compile(r"[^a-z0-9\s]+")
_RE_SPACES = re.compile(r"\s+")


_STOP_WORDS = {
    "de", "da", "do", "das", "dos",
    "em", "na", "no", "nas", "nos",
    "para", "por", "com", "sem", "sob", "sobre",
    "que", "uma", "umas", "um", "uns",
    "como", "mais", "menos",
    "protocolo", "protocolos",
    "inicial", "iniciais",
    "essencial", "essenciais",
    "caso", "casos",
    "quadro", "quadros",
    "grau", "tipo",
}


def _strip_accents(value: str | None) -> str:
    if not value:
        return ""
    # Fast-path for pure ASCII strings to avoid unicodedata normalization overhead
    if value.isascii():
        return value
    normalized = unicodedata.normalize("NFKD", value)
    return "".join([char for char in normalized if not unicodedata.combining(char)])


def _normalize_token(value: str | None) -> str:
    if not value:
        return ""
    text = _strip_accents(value).lower().strip()
    text = _RE_NON_ALPHANUMERIC_SPACES.sub(" ", text)
    return _RE_SPACES.sub(" ", text).strip()


def _tokenize(value: str | None) -> list[str]:
    normalized = _normalize_token(value)
    if not normalized:
        return []
    return [token for token in normalized.split(" ") if len(token) >= 3 and token not in _STOP_WORDS]


def _species_matches(protocol_species: str | None, animal_species: str | None) -> bool:
    if not protocol_species:
        return True
    protocol_value = _normalize_token(protocol_species)
    animal_value = _normalize_token(animal_species)
    if not animal_value:
        return True

    aliases = {
        "cao": {"cao", "caes", "canino", "cachorro", "cadela"},
        "gato": {"gato", "gatos", "felino", "gata"},
    }

    protocol_aliases = aliases.get(protocol_value, {protocol_value})
    animal_aliases = aliases.get(animal_value, {animal_value})
    return not protocol_aliases.isdisjoint(animal_aliases)


def _score_protocol(protocol: ProtocoloClinico, context: dict[str, Any]) -> tuple[int, list[str]]:
    # 1. Espécie: filtro eliminatório imediato
    animal_species = context.get("especie")
    if not _species_matches(protocol.especie, animal_species):
        return (-1, ["Espécie incompatível com o protocolo."])

    reasons: list[str] = []
    suspicion = _normalize_token(context.get("suspeita_clinica"))
    protocol_suspicion = _normalize_token(protocol.suspeita_principal)
    protocol_name = _normalize_token(protocol.nome)
    protocol_triggers = _normalize_token(protocol.sinais_gatilho)

    suspicion_score = 0
    search_matched = False

    if suspicion:
        if protocol_suspicion and suspicion == protocol_suspicion:
            search_matched = True
            suspicion_score += 80
            reasons.append("Suspeita clínica coincide com o protocolo.")
        elif protocol_name and suspicion == protocol_name:
            search_matched = True
            suspicion_score += 80
            reasons.append("Nome do protocolo coincide com o termo pesquisado.")
        elif protocol_suspicion and (suspicion in protocol_suspicion or protocol_suspicion in suspicion):
            search_matched = True
            suspicion_score += 55
            reasons.append("Suspeita clínica muito próxima da hipótese principal do protocolo.")
        elif protocol_name and (suspicion in protocol_name or protocol_name in suspicion):
            search_matched = True
            suspicion_score += 50
            reasons.append("Termo pesquisado coincide com o nome do protocolo.")
        elif protocol_triggers and suspicion in protocol_triggers:
            search_matched = True
            suspicion_score += 45
            reasons.append("Termo pesquisado coincide com sinais gatilho do protocolo.")
        else:
            suspicion_tokens = set(_tokenize(suspicion))
            protocol_all_tokens = set(
                _tokenize(" ".join(filter(None, [protocol.nome, protocol.suspeita_principal, protocol.sinais_gatilho])))
            )
            overlap_search = [t for t in suspicion_tokens if t in protocol_all_tokens]
            if overlap_search:
                search_matched = True
                suspicion_score += min(40, len(overlap_search) * 10)
                reasons.append("Encontrados termos pesquisados no protocolo: " + ", ".join(sorted(overlap_search)[:5]) + ".")

        # Quando uma busca/suspeita for informada, apenas protocolos que correspondam à busca devem aparecer
        if not search_matched:
            return (0, [])

    clinical_text = " ".join(
        filter(
            None,
            [
                context.get("queixa_principal"),
                context.get("historico_clinico"),
                context.get("exame_fisico"),
            ],
        )
    )
    clinical_tokens = Counter(_tokenize(clinical_text))
    protocol_tokens = set(
        _tokenize(" ".join(filter(None, [protocol.nome, protocol.suspeita_principal, protocol.sinais_gatilho])))
    )
    overlap = [token for token in protocol_tokens if clinical_tokens.get(token)]
    overlap_score = 0
    if overlap:
        overlap_score += min(30, len(overlap) * 6)
        reasons.append("Encontrados sinais/termos relacionados: " + ", ".join(sorted(overlap)[:5]) + ".")

    # Se não houve correspondência com a busca nem sobreposição clínica, o protocolo não tem indicação clínica
    if not search_matched and not overlap:
        return (0, [])

    score = suspicion_score + overlap_score

    # Bonificação por espécie (somente se já houver correspondência clínica)
    if _species_matches(protocol.especie, animal_species):
        score += 20
        if protocol.especie:
            reasons.append(f"Compatível com a espécie registrada ({animal_species}).")

    # Bonificação por prioridade clínica
    if protocol.prioridade:
        score += max(0, 20 - min(protocol.prioridade, 20))

    return (score, reasons)


def _followup_label(item) -> str:
    if item.prazo_min_dias and item.prazo_max_dias and item.prazo_min_dias != item.prazo_max_dias:
        prazo = f"{item.prazo_min_dias} a {item.prazo_max_dias} dias"
    elif item.prazo_min_dias:
        prazo = f"{item.prazo_min_dias} dia(s)"
    elif item.prazo_max_dias:
        prazo = f"até {item.prazo_max_dias} dia(s)"
    else:
        prazo = "prazo a definir"
    return f"{item.tipo_retorno or 'retorno'} em {prazo}"


def build_followup_prefill(item, reference_date: date | None = None) -> dict[str, Any]:
    reference = reference_date or date.today()
    days = item.prazo_min_dias or item.prazo_max_dias or 7
    suggested_date = reference + timedelta(days=days)
    objective = (item.objetivo or "").strip()
    triggers = (item.gatilhos_antecipacao or "").strip()
    reason_parts = []
    if objective:
        reason_parts.append(objective)
    if triggers:
        reason_parts.append(f"Antecipar se: {triggers}")
    return {
        "id": item.id,
        "tipo_retorno": item.tipo_retorno or "retorno",
        "prazo_min_dias": item.prazo_min_dias,
        "prazo_max_dias": item.prazo_max_dias,
        "objetivo": objective or None,
        "gatilhos_antecipacao": triggers or None,
        "label": _followup_label(item),
        "suggested_date": suggested_date.isoformat(),
        "reason": "\n".join(reason_parts).strip() or objective or "Reavaliação clínica sugerida por protocolo.",
    }


def serialize_protocol(protocol: ProtocoloClinico, context: dict[str, Any], reasons: list[str], score: int) -> dict[str, Any]:
    clinic_id = context.get('clinica_id')
    return {
        "id": protocol.id,
        "nome": protocol.nome,
        "suspeita_principal": protocol.suspeita_principal,
        "especie": protocol.especie,
        "score": score,
        "editable": bool(protocol.clinica_id and clinic_id and protocol.clinica_id == clinic_id),
        "motivos": reasons,
        "alertas": (protocol.alertas or "").strip() or None,
        "orientacoes_tutor": (protocol.orientacoes_tutor or "").strip() or None,
        "conduta_sugerida": (protocol.conduta_sugerida or "").strip() or None,
        "exames": [
            {
                "id": item.id,
                "nome": item.nome,
                "justificativa": item.justificativa,
            }
            for item in (protocol.exames_sugeridos or [])
        ],
        "medicamentos": [
            {
                "id": item.id,
                "medicamento_id": item.medicamento_id,
                "nome": item.nome_exibicao,
                "justificativa": item.justificativa,
                "dosagem": item.dosagem_texto,
                "frequencia": item.frequencia_texto,
                "duracao": item.duracao_texto,
                "observacoes": item.observacoes,
                "indicacao": item.indicacao,
            }
            for item in (protocol.medicamentos_sugeridos or [])
            if item.nome_exibicao
        ],
        "retornos": [
            build_followup_prefill(item, reference_date=context.get("data_base"))
            for item in (protocol.retornos_sugeridos or [])
        ],
    }


def recommend_protocols(context: dict[str, Any], clinic_id: int | None = None, limit: int = 5) -> list[dict[str, Any]]:
    query = (
        ProtocoloClinico.query
        .options(
            selectinload(ProtocoloClinico.exames_sugeridos),
            selectinload(ProtocoloClinico.medicamentos_sugeridos),
            selectinload(ProtocoloClinico.retornos_sugeridos),
        )
        .filter_by(ativo=True)
    )
    if clinic_id:
        query = query.filter(
            or_(ProtocoloClinico.clinica_id.is_(None), ProtocoloClinico.clinica_id == clinic_id)
        )
    else:
        query = query.filter(ProtocoloClinico.clinica_id.is_(None))

    ranked: list[tuple[int, ProtocoloClinico, list[str]]] = []
    for protocol in query.order_by(ProtocoloClinico.prioridade.asc(), ProtocoloClinico.nome.asc()).all():
        score, reasons = _score_protocol(protocol, context)
        if score <= 0:
            continue
        ranked.append((score, protocol, reasons))

    ranked.sort(key=lambda entry: entry[0], reverse=True)
    if context.get("suspeita_clinica"):
        strong_matches = [entry for entry in ranked if entry[0] >= 50]
        if strong_matches:
            ranked = strong_matches
    return [serialize_protocol(protocol, context, reasons, score) for score, protocol, reasons in ranked[:limit]]


def log_suggestion_event(
    *,
    consulta_id: int,
    protocolo_id: int | None,
    actor_user_id: int | None,
    tipo_item: str,
    acao: str,
    titulo_item: str | None = None,
    justificativa: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditoriaSugestaoClinica:
    audit = AuditoriaSugestaoClinica(
        consulta_id=consulta_id,
        protocolo_id=protocolo_id,
        actor_user_id=actor_user_id,
        tipo_item=tipo_item,
        acao=acao,
        titulo_item=titulo_item,
        justificativa=justificativa,
        payload=payload or None,
    )
    db.session.add(audit)
    return audit
