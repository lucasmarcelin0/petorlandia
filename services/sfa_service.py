"""
services/sfa_service.py
=======================
Lógica de negócio do módulo SFA — Síndromes Febris Agudas de Orlândia.

Porta a automação do GAS (SFA_Automacao.gs v3.8) para Python/Flask,
substituindo Google Sheets por PostgreSQL e o Web App por Flask.

Funções públicas principais (equivalentes ao GAS):
  - sincronizar_sinan()          ← sincronizarSINAN()
  - atualizar_contatos_do_dia()  ← atualizarContatosDoDia()
  - verificar_seguimento()       ← verificarSeguimento()
  - consolidar_banco()           ← consolidarBanco()
  - on_submit_t0(dados)          ← onSubmitT0(e)
  - on_submit_t10(dados)         ← onSubmitT10(e)
  - on_submit_t30(dados)         ← onSubmitT30(e)
  - gerar_url_t0(paciente)       ← gerarUrlT0Participante()
  - link_whatsapp(tel, msg)      ← linkWhatsApp()
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote, urlparse

from extensions import db
from flask import current_app, url_for
from sqlalchemy.exc import InternalError, NoSuchTableError, OperationalError, ProgrammingError

log = logging.getLogger("sfa_service")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORM_SCHEMA_FILES = {
    "t0": "config/sfa_t0_form.json",
    "t10": "config/sfa_t10_form.json",
    "t30": "config/sfa_t30_form.json",
}
DEFAULT_T0_FORM_SCHEMA_FILE = DEFAULT_FORM_SCHEMA_FILES["t0"]
SUPPORTED_T0_FIELD_TYPES = {
    "text",
    "date",
    "textarea",
    "select",
    "radio",
    "checkboxes",
    "number",
}
T0_CONSENT_ACCEPTED = "Confirmo que li o TCLE e aceito participar voluntariamente do estudo."
T0_CONSENT_DECLINED = "Nao aceito participar."
LEGACY_T0_CONSENT_ACCEPTED = "Aceito participar voluntariamente deste estudo."

# ---------------------------------------------------------------------------
# Configuração (lida de variáveis de ambiente ou fallback)
# ---------------------------------------------------------------------------

DIAS_T10 = int(os.getenv("SFA_DIAS_T10", "10"))
DIAS_T30 = int(os.getenv("SFA_DIAS_T30", "30"))
DIAS_LEMBRETE = int(os.getenv("SFA_DIAS_LEMBRETE", "2"))
DIAS_SEM_T0_ALERTA = int(os.getenv("SFA_DIAS_SEM_T0_ALERTA", "5"))
TOLERANCIA_ALERTA_DIAS = int(os.getenv("SFA_TOLERANCIA_ALERTA_DIAS", "1"))
NOME_PESQUISADOR = os.getenv("SFA_NOME_PESQUISADOR", "Lucas")
EMAIL_PESQUISADOR = os.getenv("SFA_EMAIL_PESQUISADOR", "lucas.marcbh.lm@gmail.com")
DDD_PADRAO = os.getenv("SFA_DDD_PADRAO", "16")
PREFIXO_PAIS = os.getenv("SFA_PREFIXO_PAIS", "55")
GRUPO_PENDENTE = "PENDENTE_REVISAO"

# Planilha SINAN no Google Sheets
SHEET_ID_SINAN = os.getenv(
    "SFA_SHEET_ID_SINAN",
    "15UdUxNhuL3VUNpJr_iEiiWTVM-rlKtVcGPeY9jSFJ_E",
)
SHEET_RANGE_SINAN = os.getenv("SFA_SHEET_RANGE_SINAN", "A:T")
SHEET_TITLE_SINAN = os.getenv("SFA_SHEET_TITLE_SINAN", "")
SHEET_GID_SINAN = os.getenv("SFA_SHEET_GID_SINAN", "")

# IDs dos Google Forms
FORM_T0_ID = os.getenv(
    "SFA_FORM_T0_ID",
    "1PbQj5rF4OkeNOYN44rCoVbbDYE-GftwHn-BNGC3-kmg",
)
FORM_T10_ID = os.getenv(
    "SFA_FORM_T10_ID",
    "1v8WL_3ecBUDU2N3CDDQeCULvwYI3UHCjA950aFwQj3g",
)
FORM_T30_ID = os.getenv(
    "SFA_FORM_T30_ID",
    "1VFrH7aFkjetu0Xu7lA6ch9ffqArExLNpt8933rsWyjw",
)
T0_RESPONSE_SHEET = os.getenv("SFA_T0_RESPONSE_SHEET", "")
T0_RESPONSE_RANGE = os.getenv("SFA_T0_RESPONSE_RANGE", "A:ZZ")
T0_RESPONSE_TITLE = os.getenv("SFA_T0_RESPONSE_TITLE", "")
T0_RESPONSE_GID = os.getenv("SFA_T0_RESPONSE_GID", "")
T0_FORM_SCHEMA_FILE = os.getenv("SFA_T0_FORM_SCHEMA_FILE", DEFAULT_FORM_SCHEMA_FILES["t0"])
T10_FORM_SCHEMA_FILE = os.getenv("SFA_T10_FORM_SCHEMA_FILE", DEFAULT_FORM_SCHEMA_FILES["t10"])
T30_FORM_SCHEMA_FILE = os.getenv("SFA_T30_FORM_SCHEMA_FILE", DEFAULT_FORM_SCHEMA_FILES["t30"])

LINK_FORM_T10 = os.getenv(
    "SFA_LINK_FORM_T10",
    f"https://docs.google.com/forms/d/{FORM_T10_ID}/viewform",
)
LINK_FORM_T30 = os.getenv(
    "SFA_LINK_FORM_T30",
    f"https://docs.google.com/forms/d/{FORM_T30_ID}/viewform",
)

# Entry IDs para pré-preenchimento dos formulários
# (extraídos via forceCorrectIds() / inspeção do Forms)
ENTRY_T0_ID_ESTUDO = os.getenv("SFA_ENTRY_T0_ID_ESTUDO", "entry.1447355807")
ENTRY_T0_FICHA_SINAN = os.getenv("SFA_ENTRY_T0_FICHA_SINAN", "")
ENTRY_T0_NOME = os.getenv("SFA_ENTRY_T0_NOME", "entry.2001573769")
ENTRY_T0_DATA_NASC_BASE = os.getenv("SFA_ENTRY_T0_DATA_NASC_BASE", "entry.1487617078")
ENTRY_T0_TOKEN = os.getenv("SFA_ENTRY_T0_TOKEN", "")
ENTRY_T10_NOME = os.getenv("SFA_ENTRY_T10_NOME", "entry.1342379317")
# Pendente: rodar salvarEntryIdsAcompanhamentos() no GAS para descobrir entry de id_estudo no T10/T30
ENTRY_T10_ID_ESTUDO = os.getenv("SFA_ENTRY_T10_ID_ESTUDO", "")
ENTRY_T30_NOME = os.getenv("SFA_ENTRY_T30_NOME", "entry.937246935")
ENTRY_T30_ID_ESTUDO = os.getenv("SFA_ENTRY_T30_ID_ESTUDO", "")

FORM_T0_HEADER_ALIASES = {
    "timestamp": [
        "timestamp",
        "carimbo de data/hora",
        "carimbo de data hora",
        "data/hora",
        "data e hora",
    ],
    "id_estudo": [
        "id_estudo",
        "id estudo",
        "codigo do participante",
        "codigo participante",
        "codigo do estudo",
        "codigo estudo",
    ],
    "ficha_sinan": [
        "ficha_sinan",
        "ficha sinan",
        "numero da ficha sinan",
        "numero ficha sinan",
    ],
    "token_acesso": [
        "token",
        "token acesso",
        "token de acesso",
        "codigo de acesso",
        "codigo unico",
        "chave de acesso",
    ],
    "nome": [
        "nome",
        "nome completo",
        "nome do participante",
    ],
    "data_nascimento": [
        "data nascimento",
        "data de nascimento",
        "nascimento",
    ],
    "tipo_residencia": [
        "tipo residencia",
        "tipo de residencia",
    ],
    "data_inicio_sintomas": [
        "data inicio sintomas",
        "data de inicio dos sintomas",
        "data inicio dos sintomas",
    ],
    "dias_incap": [
        "dias incap",
        "dias de incapacitacao",
        "dias incapacitado",
        "quantos dias ficou incapacitado",
    ],
    "internacao": [
        "internacao",
        "houve internacao",
        "precisou de internacao",
        "foi internado",
    ],
    "custo_total": [
        "custo total",
        "gasto total",
        "valor total gasto",
        "custo total aproximado",
    ],
    "ausencia_familiar": [
        "ausencia familiar",
        "alguem da familia precisou faltar",
        "familiar precisou faltar",
    ],
}

# Mapeamento de colunas da planilha SINAN (0-indexado)
COLS_SINAN = {
    "TIMESTAMP": 0,
    "AGRAVO": 1,
    "N": 2,
    "FICHA_SINAN": 3,
    "UNIDADE_NOTIFICANTE": 4,
    "DATA_NOTIFICACAO": 5,
    "DATA_INICIO_SINTOMAS": 6,
    "NOME": 7,
    "DATA_NASCIMENTO": 8,
    "ENDERECO": 9,
    "BAIRRO": 10,
    "TELEFONE": 11,
    "LOCAL_TRABALHO": 12,
    "DESLOCAMENTO": 13,
    "INFO_COMPLEMENTAR": 14,
    "TIPO_EXAME": 15,
    "RESULTADO": 16,
    "RESULTADO_FINAL": 17,
    "CLASSIFICACAO": 18,
    "RESPONSAVEL": 19,
}


# ---------------------------------------------------------------------------
# Utilitários gerais
# ---------------------------------------------------------------------------

def normalizar_telefone(tel: str) -> str:
    """Normaliza telefone para formato E.164 sem '+' (ex: 5516991234567)."""
    s = re.sub(r"\D", "", str(tel or ""))
    if not s:
        return ""
    if len(s) == 8:
        return PREFIXO_PAIS + DDD_PADRAO + s
    if len(s) == 9:
        return PREFIXO_PAIS + DDD_PADRAO + s
    if len(s) == 10:
        return PREFIXO_PAIS + s
    if len(s) == 11:
        return PREFIXO_PAIS + s
    if len(s) >= 12:
        return s
    return ""


def link_whatsapp(telefone_normalizado: str, mensagem: str) -> str:
    """Gera URL click-to-chat WhatsApp com mensagem pré-preenchida."""
    return f"https://wa.me/{telefone_normalizado}?text={quote(mensagem)}"


def _safe_query_all(model):
    """Retorna model.query.all() ou [] se a tabela não existir."""
    try:
        return model.query.all()
    except (ProgrammingError, OperationalError, NoSuchTableError, InternalError):
        db.session.rollback()
        log.warning("SFA: tabela não encontrada ao consultar %s", getattr(model, "__tablename__", str(model)), exc_info=False)
        return []


def _safe_query_limit(query_fn, limit=10):
    try:
        return query_fn().limit(limit).all()
    except (ProgrammingError, OperationalError, NoSuchTableError, InternalError):
        db.session.rollback()
        log.warning("SFA: tabela não encontrada ao consultar auditoria", exc_info=False)
        return []


def primeiro_nome(nome_completo: str) -> str:
    return (nome_completo or "Participante").split()[0]


def formatar_data(d) -> str:
    if not d:
        return ""
    if isinstance(d, (date, datetime)):
        return d.strftime("%d/%m/%Y")
    return str(d)


def parse_data(valor) -> Optional[date]:
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()
    if not s:
        return None
    try:
        if "/" in s:
            d, m, y = s.split("/")
            return date(int(y), int(m), int(d))
        return datetime.fromisoformat(s).date()
    except Exception:
        return None


def normalizar_nome_chave(valor: str) -> str:
    """Normaliza nome para comparação: minúsculas, sem acentos, sem espaços duplos."""
    s = str(valor or "").strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def _normalize_form_stage(form_stage: str) -> str:
    stage = str(form_stage or "").strip().lower()
    if stage not in DEFAULT_FORM_SCHEMA_FILES:
        raise ValueError(f"Etapa de formulario invalida: {form_stage}")
    return stage


def _schema_file_for_stage(form_stage: str) -> str:
    stage = _normalize_form_stage(form_stage)
    mapping = {
        "t0": T0_FORM_SCHEMA_FILE,
        "t10": T10_FORM_SCHEMA_FILE,
        "t30": T30_FORM_SCHEMA_FILE,
    }
    return mapping[stage] or DEFAULT_FORM_SCHEMA_FILES[stage]


def _resolve_form_schema_path(form_stage: str) -> Path:
    path = Path(_schema_file_for_stage(form_stage))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def carregar_form_schema(form_stage: str) -> dict:
    path = _resolve_form_schema_path(form_stage)
    with path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise ValueError("Schema do formulario T0 invalido.")
    schema["_path"] = str(path)
    schema["_stage"] = _normalize_form_stage(form_stage)
    return schema


def carregar_t0_form_schema() -> dict:
    return carregar_form_schema("t0")


def carregar_t10_form_schema() -> dict:
    return carregar_form_schema("t10")


def carregar_t30_form_schema() -> dict:
    return carregar_form_schema("t30")


def _schema_t0_sem_metadados(schema: dict) -> dict:
    return {
        key: value
        for key, value in dict(schema or {}).items()
        if not str(key).startswith("_")
    }


def validar_t0_form_schema(schema: dict) -> list[str]:
    schema = _schema_t0_sem_metadados(schema)
    errors: list[str] = []

    if not isinstance(schema, dict):
        return ["O schema do formulario T0 deve ser um objeto JSON."]

    if not str(schema.get("title") or "").strip():
        errors.append("Informe um titulo para o formulario.")

    sections = schema.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("Informe ao menos uma secao com campos.")
        return errors

    seen_keys: set[str] = set()
    for section_index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            errors.append(f"Secao {section_index}: formato invalido.")
            continue

        if not str(section.get("title") or "").strip():
            errors.append(f"Secao {section_index}: informe um titulo.")

        fields = section.get("fields")
        if not isinstance(fields, list) or not fields:
            errors.append(f"Secao {section_index}: informe ao menos um campo.")
            continue

        for field_index, field in enumerate(fields, start=1):
            if not isinstance(field, dict):
                errors.append(f"Secao {section_index}, campo {field_index}: formato invalido.")
                continue

            key = str(field.get("key") or "").strip()
            label = str(field.get("label") or "").strip()
            field_type = str(field.get("type") or "text").strip()

            if not key:
                errors.append(f"Secao {section_index}, campo {field_index}: informe a chave.")
            elif key in seen_keys:
                errors.append(f"Campo duplicado no schema: {key}.")
            else:
                seen_keys.add(key)

            if not label:
                errors.append(
                    f"Secao {section_index}, campo {key or field_index}: informe o rotulo."
                )

            if field_type not in SUPPORTED_T0_FIELD_TYPES:
                errors.append(
                    f"Secao {section_index}, campo {key or field_index}: "
                    f"tipo invalido ({field_type})."
                )

            if field_type in {"select", "radio", "checkboxes"}:
                options = field.get("options")
                if not isinstance(options, list) or not [
                    str(option).strip() for option in options if str(option).strip()
                ]:
                    errors.append(
                        f"Secao {section_index}, campo {key or field_index}: "
                        "informe opcoes validas."
                    )

    return errors


def serializar_t0_form_schema(schema: dict) -> str:
    return json.dumps(
        _schema_t0_sem_metadados(schema),
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def salvar_form_schema(form_stage: str, schema: dict) -> Path:
    errors = validar_t0_form_schema(schema)
    if errors:
        raise ValueError("Schema do formulario T0 invalido: " + " ".join(errors))

    path = _resolve_form_schema_path(form_stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serializar_t0_form_schema(schema), encoding="utf-8")
    return path


def salvar_t0_form_schema(schema: dict) -> Path:
    return salvar_form_schema("t0", schema)


def salvar_t10_form_schema(schema: dict) -> Path:
    return salvar_form_schema("t10", schema)


def salvar_t30_form_schema(schema: dict) -> Path:
    return salvar_form_schema("t30", schema)


def iterar_campos_form(schema: dict):
    for section in schema.get("sections", []):
        for field in section.get("fields", []):
            if isinstance(field, dict) and field.get("key"):
                yield field


def iterar_campos_t0(schema: dict):
    yield from iterar_campos_form(schema)


def _valor_html_data(valor: object) -> str:
    data = parse_data(valor)
    return data.isoformat() if data else ""


def _carregar_payload_resposta(resposta) -> dict[str, object]:
    if not resposta:
        return {}

    raw = getattr(resposta, "dados_json", None)
    if not raw:
        return {}

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _buscar_valor_respostas_anteriores(paciente, key: str) -> object:
    if not paciente or not key:
        return ""

    staged_responses: list[object] = []

    respostas_t30 = list(getattr(paciente, "respostas_t30", []) or [])
    respostas_t10 = list(getattr(paciente, "respostas_t10", []) or [])

    if respostas_t30:
        staged_responses.extend(reversed(respostas_t30))
    if respostas_t10:
        staged_responses.extend(reversed(respostas_t10))

    resposta_t0 = getattr(paciente, "resposta_t0", None)
    if resposta_t0:
        staged_responses.append(resposta_t0)

    for resposta in staged_responses:
        payload = _carregar_payload_resposta(resposta)
        value = payload.get(key)
        if value not in (None, "", []):
            return value

    return ""


def obter_resposta_formulario(paciente, form_stage: str):
    stage = _normalize_form_stage(form_stage)
    if stage == "t0":
        return getattr(paciente, "resposta_t0", None)

    attr_name = "respostas_t10" if stage == "t10" else "respostas_t30"
    respostas = list(getattr(paciente, attr_name, []) or [])
    return respostas[-1] if respostas else None


def obter_payload_formulario(paciente, form_stage: str) -> tuple[object, dict[str, object]]:
    resposta = obter_resposta_formulario(paciente, form_stage)
    return resposta, _carregar_payload_resposta(resposta)


def _tem_valor_resposta(value: object) -> bool:
    return value not in (None, "", [])


def formatar_valor_resposta(value: object) -> str:
    if isinstance(value, list):
        itens = [str(item).strip() for item in value if str(item or "").strip()]
        return " | ".join(itens) if itens else "Nao informado"
    if value is None:
        return "Nao informado"
    text = str(value).strip()
    return text or "Nao informado"


def t0_consentimento_aceito(decisao: object) -> bool:
    accepted_values = {T0_CONSENT_ACCEPTED, LEGACY_T0_CONSENT_ACCEPTED}
    if isinstance(decisao, list):
        valores = {str(item or "").strip() for item in decisao}
        return bool(valores & accepted_values)
    return str(decisao or "").strip() in accepted_values


def _nome_assinatura_tcle(payload: dict[str, object]) -> str:
    return str(
        payload.get("tcle_assinado_por")
        or payload.get("assinatura_tcle_nome")
        or payload.get("nome")
        or ""
    ).strip()


def _formatar_timestamp_consentimento(value: object) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return text


def montar_registro_assinatura_tcle(resposta) -> Optional[dict[str, str]]:
    payload = _carregar_payload_resposta(resposta)
    aceite = payload.get("aceite_tcle")
    if aceite in (None, "", []):
        aceite = payload.get("decisao_tcle")
    if not t0_consentimento_aceito(aceite):
        return None

    assinado_em_raw = (
        payload.get("consentimento_registrado_em")
        or getattr(resposta, "timestamp", None)
    )
    return {
        "id_estudo": str(getattr(resposta, "id_estudo", "") or ""),
        "ficha_sinan": str(payload.get("ficha_sinan") or ""),
        "participante": str(payload.get("nome") or getattr(resposta, "nome", "") or "").strip(),
        "nome_assinatura": _nome_assinatura_tcle(payload) or str(getattr(resposta, "nome", "") or "").strip(),
        "data_nascimento": str(
            payload.get("data_nascimento") or getattr(resposta, "data_nascimento", "") or ""
        ).strip(),
        "assinado_em": _formatar_timestamp_consentimento(assinado_em_raw),
        "assinado_em_raw": _serializar_valor_csv(assinado_em_raw),
        "ip": str(payload.get("consentimento_ip") or "").strip(),
        "user_agent": str(payload.get("consentimento_user_agent") or "").strip(),
    }


def montar_visao_resposta_formulario(
    form_stage: str,
    resposta,
    schema: Optional[dict] = None,
) -> dict:
    stage = _normalize_form_stage(form_stage)
    schema = schema or carregar_form_schema(stage)
    payload = _carregar_payload_resposta(resposta)

    sections: list[dict[str, object]] = []
    answered_total = 0
    total_fields = 0

    for section in schema.get("sections", []):
        fields_view: list[dict[str, object]] = []
        answered_section = 0
        section_fields = [
            field for field in section.get("fields", [])
            if isinstance(field, dict) and field.get("key")
        ]
        total_section = len(section_fields)
        total_fields += total_section

        for field in section_fields:
            raw_value = payload.get(field["key"])
            has_value = _tem_valor_resposta(raw_value)
            if has_value:
                answered_section += 1
                answered_total += 1

            fields_view.append(
                {
                    "key": field["key"],
                    "label": field.get("label") or field["key"],
                    "value": formatar_valor_resposta(raw_value),
                    "has_value": has_value,
                }
            )

        sections.append(
            {
                "title": section.get("title") or "Secao",
                "description": section.get("description") or "",
                "fields": fields_view,
                "answered": answered_section,
                "total": total_section,
            }
        )

    submitted_at = getattr(resposta, "timestamp", None)
    if isinstance(submitted_at, datetime):
        submitted_at = submitted_at.strftime("%d/%m/%Y %H:%M")

    return {
        "stage": stage,
        "title": schema.get("title") or stage.upper(),
        "submitted_at": submitted_at or "Nao informado",
        "sections": sections,
        "answered": answered_total,
        "total": total_fields,
        "payload": payload,
    }


def _serializar_valor_csv(value: object) -> str:
    if isinstance(value, list):
        return " | ".join(str(item).strip() for item in value if str(item or "").strip())
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return ""
    return str(value)


def _colunas_fixas_exportacao() -> list[str]:
    return [
        "id_estudo",
        "ficha_sinan",
        "nome",
        "data_nascimento",
        "telefone",
        "bairro",
        "endereco",
        "grupo",
        "status_t0",
        "status_t10",
        "status_t30",
        "status_geral",
        "data_t0",
        "data_t10",
        "data_t30",
        "fase_atual",
        "proxima_fase",
        "proxima_acao",
        "prioridade_operacional",
        "dias_para_acao",
        "data_proxima_acao",
        "status_whatsapp",
        "retorno_contato",
        "timestamp_cadastro",
        "updated_at",
    ]


def _colunas_formulario_exportacao(form_stage: str, schema: Optional[dict] = None) -> list[str]:
    stage = _normalize_form_stage(form_stage)
    schema = schema or carregar_form_schema(stage)
    return [f"{stage}__{field['key']}" for field in iterar_campos_form(schema)]


def montar_linha_exportacao_analitica(paciente, schemas: Optional[dict[str, dict]] = None) -> dict[str, str]:
    schemas = schemas or {
        "t0": carregar_t0_form_schema(),
        "t10": carregar_t10_form_schema(),
        "t30": carregar_t30_form_schema(),
    }

    row = {
        column: _serializar_valor_csv(getattr(paciente, column, ""))
        for column in _colunas_fixas_exportacao()
    }

    for stage in ("t0", "t10", "t30"):
        resposta, payload = obter_payload_formulario(paciente, stage)
        row[f"{stage}__respondido_em"] = _serializar_valor_csv(getattr(resposta, "timestamp", ""))
        for field in iterar_campos_form(schemas[stage]):
            row[f"{stage}__{field['key']}"] = _serializar_valor_csv(payload.get(field["key"]))

    return row


def listar_assinaturas_tcle() -> list[dict[str, str]]:
    from models.sfa import SfaRespostaT0

    assinaturas: list[dict[str, str]] = []
    for resposta in SfaRespostaT0.query.order_by(SfaRespostaT0.timestamp.desc()).all():
        registro = montar_registro_assinatura_tcle(resposta)
        if registro:
            assinaturas.append(registro)
    return assinaturas


def gerar_csv_assinaturas_tcle(assinaturas: Optional[list[dict[str, str]]] = None) -> str:
    registros = assinaturas if assinaturas is not None else listar_assinaturas_tcle()
    fieldnames = [
        "assinado_em",
        "id_estudo",
        "ficha_sinan",
        "participante",
        "nome_assinatura",
        "data_nascimento",
        "ip",
        "user_agent",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for registro in registros:
        writer.writerow({field: _serializar_valor_csv(registro.get(field, "")) for field in fieldnames})
    return output.getvalue()


def gerar_csv_exportacao_cadastro(pacientes) -> str:
    output = io.StringIO(newline="")
    fieldnames = _colunas_fixas_exportacao()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for paciente in pacientes:
        writer.writerow(
            {
                column: _serializar_valor_csv(getattr(paciente, column, ""))
                for column in fieldnames
            }
        )
    return output.getvalue()


def gerar_csv_exportacao_analitica(pacientes) -> str:
    schemas = {
        "t0": carregar_t0_form_schema(),
        "t10": carregar_t10_form_schema(),
        "t30": carregar_t30_form_schema(),
    }
    fieldnames = (
        _colunas_fixas_exportacao()
        + [f"{stage}__respondido_em" for stage in ("t0", "t10", "t30")]
        + _colunas_formulario_exportacao("t0", schemas["t0"])
        + _colunas_formulario_exportacao("t10", schemas["t10"])
        + _colunas_formulario_exportacao("t30", schemas["t30"])
    )

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for paciente in pacientes:
        writer.writerow(montar_linha_exportacao_analitica(paciente, schemas=schemas))
    return output.getvalue()


def construir_valores_iniciais_form(paciente, schema: dict) -> dict[str, object]:
    values: dict[str, object] = {}
    for field in iterar_campos_form(schema):
        key = field["key"]
        source = field.get("prefill")
        value = field.get("default", "")
        if source:
            value = _buscar_valor_respostas_anteriores(paciente, str(source))
            if value in (None, "", []):
                value = getattr(paciente, source, "") or ""
        if field.get("type") == "date":
            value = _valor_html_data(value)
        values[key] = value
    return values


def construir_valores_iniciais_t0(paciente, schema: dict) -> dict[str, object]:
    return construir_valores_iniciais_form(paciente, schema)


def construir_valores_iniciais_t10(paciente, schema: dict) -> dict[str, object]:
    return construir_valores_iniciais_form(paciente, schema)


def construir_valores_iniciais_t30(paciente, schema: dict) -> dict[str, object]:
    return construir_valores_iniciais_form(paciente, schema)


def coletar_resposta_nativa(
    form_stage: str,
    schema: dict,
    form_data,
    paciente,
) -> tuple[dict, dict[str, str]]:
    stage = _normalize_form_stage(form_stage)
    dados: dict[str, object] = {}
    errors: dict[str, str] = {}

    for field in iterar_campos_form(schema):
        key = field["key"]
        field_type = field.get("type", "text")
        if field_type == "checkboxes":
            value = [item.strip() for item in form_data.getlist(key) if str(item or "").strip()]
        else:
            value = str(form_data.get(key) or "").strip()
            if field_type == "date" and value:
                value = formatar_data(parse_data(value))

        if field.get("required") and not value:
            errors[key] = "Campo obrigatorio."

        dados[key] = value

    dados["token_acesso"] = paciente.token_acesso or ""
    dados["id_estudo"] = paciente.id_estudo or ""
    if not dados.get("ficha_sinan"):
        dados["ficha_sinan"] = paciente.ficha_sinan or ""
    if not dados.get("nome"):
        dados["nome"] = paciente.nome or ""
    if not dados.get("data_nascimento"):
        dados["data_nascimento"] = paciente.data_nascimento or ""
    dados["_origem"] = f"native_{stage}_form"
    return dados, errors


def coletar_resposta_t0_nativa(schema: dict, form_data, paciente) -> tuple[dict, dict[str, str]]:
    dados, errors = coletar_resposta_nativa("t0", schema, form_data, paciente)
    aceite_tcle = dados.get("aceite_tcle")

    if not t0_consentimento_aceito(aceite_tcle):
        errors["aceite_tcle"] = "Voce precisa aceitar o TCLE para enviar o formulario."

    return dados, errors


def coletar_resposta_t10_nativa(schema: dict, form_data, paciente) -> tuple[dict, dict[str, str]]:
    return coletar_resposta_nativa("t10", schema, form_data, paciente)


def coletar_resposta_t30_nativa(schema: dict, form_data, paciente) -> tuple[dict, dict[str, str]]:
    return coletar_resposta_nativa("t30", schema, form_data, paciente)


def _sanitize_limited_text(
    value: object,
    max_length: int,
    field_name: str,
    ajustes: Optional[list[dict]] = None,
) -> str:
    original = "" if value is None else str(value)
    cleaned = original.replace("\u00a0", " ")
    cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    acao = None
    if cleaned != original.strip():
        acao = "normalizado"

    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
        acao = "normalizado_e_truncado" if acao else "truncado"

    if acao and ajustes is not None:
        ajustes.append(
            {
                "campo": field_name,
                "acao": acao,
                "tamanho_original": len(original),
                "tamanho_final": len(cleaned),
            }
        )

    return cleaned


def calcular_idade(data_nasc: date, data_ref: date) -> Optional[int]:
    if not data_nasc or not data_ref:
        return None
    idade = data_ref.year - data_nasc.year
    if (data_ref.month, data_ref.day) < (data_nasc.month, data_nasc.day):
        idade -= 1
    return idade


def chave_dedup_sinan(row: list) -> Optional[str]:
    ficha = re.sub(r"\D", "", str(row[COLS_SINAN["FICHA_SINAN"]] or ""))
    if len(ficha) >= 5:
        return f"FICHA-{ficha}"
    n = re.sub(r"\D", "", str(row[COLS_SINAN["N"]] or ""))
    if n:
        return f"N-{n.zfill(3)}"
    return None


def registrar_auditoria(nivel: str, categoria: str, funcao: str,
                         mensagem: str, detalhes: Optional[dict] = None,
                         id_estudo: str = "") -> None:
    """Salva um registro na tabela SfaAuditoria."""
    try:
        from extensions import db
        from models.sfa import SfaAuditoria
        entrada = SfaAuditoria(
            nivel=nivel,
            categoria=categoria,
            funcao=funcao,
            id_estudo=id_estudo or "",
            mensagem=mensagem,
            detalhes_json=json.dumps(detalhes or {}, ensure_ascii=False),
        )
        db.session.add(entrada)
        db.session.commit()
    except Exception as exc:
        log.error("Falha ao registrar auditoria: %s", exc)


# ---------------------------------------------------------------------------
# Geração de id_estudo
# ---------------------------------------------------------------------------

def proximo_id_estudo() -> str:
    """Gera o próximo id_estudo sequencial (ex: SFA-042)."""
    from models.sfa import SfaPaciente
    total = SfaPaciente.query.count()
    return f"SFA-{(total + 1):03d}"


# ---------------------------------------------------------------------------
# Geração de URL do Web App Flask (substitui doGet do GAS)
# ---------------------------------------------------------------------------

def gerar_url_t0(id_estudo: str, token_acesso: str = "", debug: bool = False) -> str:
    """Gera a URL personalizada para o participante acessar o formulário T0."""
    try:
        if token_acesso:
            url = url_for("sfa_routes.redirect_t0", token=token_acesso, _external=True)
        else:
            url = url_for("sfa_routes.redirect_t0", token=id_estudo, _external=True)
        if debug:
            url += "?debug=1"
        return url
    except RuntimeError:
        # Fora do contexto Flask (ex: job agendado)
        base = os.getenv("SFA_WEBAPP_URL", "")
        if not base:
            return ""
        chave = f"tk={quote(token_acesso)}" if token_acesso else f"id={quote(id_estudo)}"
        return f"{base}/sfa/p?{chave}" + ("&debug=1" if debug else "")


# URLs nativas por etapa. Mantemos as configuracoes legadas acima apenas para
# compatibilidade, mas os links operacionais devem usar as funcoes abaixo.
def _gerar_url_etapa(
    form_stage: str,
    id_estudo: str,
    token_acesso: str = "",
    debug: bool = False,
) -> str:
    stage = _normalize_form_stage(form_stage)
    route_map = {
        "t0": "sfa_routes.redirect_t0",
        "t10": "sfa_routes.redirect_t10",
        "t30": "sfa_routes.redirect_t30",
    }
    suffix_map = {
        "t0": "",
        "t10": "/t10",
        "t30": "/t30",
    }

    try:
        token = token_acesso or id_estudo
        if not token:
            return ""
        url = url_for(route_map[stage], token=token, _external=True)
        if debug:
            url += "?debug=1"
        return url
    except RuntimeError:
        base = os.getenv("SFA_WEBAPP_URL", "").rstrip("/")
        token = token_acesso or id_estudo
        if not base or not token:
            return ""
        url = f"{base}/sfa/p/{quote(token)}{suffix_map[stage]}"
        if debug:
            url += "?debug=1"
        return url


def gerar_url_t0(id_estudo: str, token_acesso: str = "", debug: bool = False) -> str:
    return _gerar_url_etapa("t0", id_estudo, token_acesso, debug)


def gerar_url_t10(id_estudo: str, token_acesso: str = "", debug: bool = False) -> str:
    return _gerar_url_etapa("t10", id_estudo, token_acesso, debug)


def gerar_url_t30(id_estudo: str, token_acesso: str = "", debug: bool = False) -> str:
    return _gerar_url_etapa("t30", id_estudo, token_acesso, debug)


# ---------------------------------------------------------------------------
# Mensagens WhatsApp
# ---------------------------------------------------------------------------

def msg_convite_t0(nome: str, id_estudo: str, token_acesso: str = "") -> str:
    n = primeiro_nome(nome)
    link = gerar_url_t0(id_estudo, token_acesso)
    return (
        f"Ola, {n}. Tudo bem?\n\n"
        f"Aqui e {NOME_PESQUISADOR}, pesquisador da Secretaria de Saude de Orlandia.\n\n"
        "Voce foi registrado(a) recentemente com suspeita de dengue. "
        "Gostariamos de convida-lo(a) a participar de uma pesquisa cientifica "
        "sobre diagnostico de arboviroses no municipio.\n\n"
        "Informacoes importantes:\n"
        "- Participacao voluntaria\n"
        "- Apenas 3 entrevistas rapidas (hoje, em 10 e em 30 dias)\n"
        "- A pesquisa ajuda a melhorar o diagnostico de dengue em Orlandia\n\n"
        f"Codigo do participante: {id_estudo}\n\n"
        "Se topar participar, acesse o link abaixo. Seus dados ja estao preenchidos:\n"
        f"{link}\n\n"
        "Se tiver qualquer duvida, pode me chamar por aqui."
    )


def _link_prefilled(base_url: str, nome: str, id_estudo: str,
                    entry_nome: str, entry_id: str) -> str:
    """Monta URL de formulário Google com campos pré-preenchidos."""
    from urllib.parse import urlencode
    params = {}
    if entry_nome and nome:
        params[entry_nome] = nome
    if entry_id and id_estudo:
        params[entry_id] = id_estudo
    if not params:
        return base_url
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}usp=pp_url&{urlencode(params)}"


def msg_lembrete_t10(nome: str, id_estudo: str, token_acesso: str = "") -> str:
    n = primeiro_nome(nome)
    link = gerar_url_t10(id_estudo, token_acesso)
    return (
        f"Ola, {n}.\n\n"
        f"Aqui e {NOME_PESQUISADOR}, da pesquisa de arboviroses de Orlandia.\n\n"
        "Ja se passaram cerca de 10 dias e chegou o momento do acompanhamento T10.\n\n"
        f"Codigo do participante: {id_estudo}\n"
        f"Acesse e responda:\n{link}\n\n"
        "Obrigado pela sua participacao."
    )


def msg_lembrete_t30(nome: str, id_estudo: str, token_acesso: str = "") -> str:
    n = primeiro_nome(nome)
    link = gerar_url_t30(id_estudo, token_acesso)
    return (
        f"Ola, {n}.\n\n"
        f"Aqui e {NOME_PESQUISADOR}, da pesquisa de arboviroses de Orlandia.\n\n"
        "Chegamos ao final do seu acompanhamento de 30 dias.\n\n"
        f"Codigo do participante: {id_estudo}\n"
        "Seus dados ja estao preenchidos. Acesse e responda:\n"
        f"{link}\n\n"
        "Sua participacao foi muito importante para a pesquisa. Muito obrigado."
    )


def msg_revisao_pendente(nome: str, id_estudo: str) -> str:
    n = primeiro_nome(nome)
    return (
        f"Ola, {n}.\n\n"
        f"Aqui e {NOME_PESQUISADOR}, da pesquisa de arboviroses de Orlandia.\n\n"
        "Precisamos confirmar alguns dados do seu cadastro para concluir sua inclusao no estudo.\n"
        f"Codigo do participante: {id_estudo or '(sem codigo)'}\n\n"
        "Se puder, me responda por aqui para alinharmos rapidamente. Obrigado."
    )


# ---------------------------------------------------------------------------
# Cálculo de ação operacional (equivale a calcularAcaoOperacional do GAS)
# ---------------------------------------------------------------------------

ACOES_QUE_GERAM_CONTATO = {
    "Convidar T0", "Lembrar T10", "Cobrar T10",
    "Lembrar T30", "Cobrar T30", "Revisar cadastro",
}


def calcular_acao_operacional(paciente) -> dict:
    """
    Dado um SfaPaciente, retorna um dicionário com prioridade, fase, ação e
    data alvo — idêntico à lógica calcularAcaoOperacional() do GAS.
    """
    hoje = date.today()
    grupo = paciente.grupo or ""
    st_t0 = paciente.status_t0 or ""
    st_t10 = paciente.status_t10 or ""
    st_t30 = paciente.status_t30 or ""
    st_geral = paciente.status_geral or ""
    dt_t10 = parse_data(paciente.data_t10)
    dt_t30 = parse_data(paciente.data_t30)

    prioridade = "Baixa"
    acao = "Sem acao"
    data_alvo = None
    fase_atual = "Triagem"
    proxima_fase = "A definir"

    if grupo == GRUPO_PENDENTE:
        prioridade, acao, data_alvo = "Alta", "Revisar cadastro", hoje
        fase_atual, proxima_fase = "Revisao", "Definir inclusao"

    elif "PERDA" in st_geral:
        prioridade, acao, data_alvo = "Alta", "Revisar perda", hoje
        fase_atual, proxima_fase = "Perda de seguimento", "Encerrar ou recuperar"

    elif st_geral == "SINAN_Notificado" or st_t0 == "SINAN_Aguardando_T0":
        prioridade, acao, data_alvo = "Alta", "Convidar T0", hoje
        fase_atual, proxima_fase = "Aguardando T0", "T0"

    elif st_t10 == "ATRASADO":
        prioridade, acao, data_alvo = "Alta", "Cobrar T10", dt_t10 or hoje
        fase_atual, proxima_fase = "T10 atrasado", "T10"

    elif st_t30 == "ATRASADO":
        prioridade, acao, data_alvo = "Alta", "Cobrar T30", dt_t30 or hoje
        fase_atual, proxima_fase = "T30 atrasado", "T30"

    elif st_t10 == "Aguardando" and dt_t10:
        dias = (dt_t10 - hoje).days
        if dias <= 0:
            prioridade, acao = "Alta", "Cobrar T10"
        elif dias <= DIAS_LEMBRETE:
            prioridade, acao = "Media", "Lembrar T10"
        else:
            prioridade, acao = "Baixa", "Aguardar T10"
        data_alvo = dt_t10
        fase_atual, proxima_fase = "Entre T0 e T10", "T10"

    elif st_t30 == "Aguardando" and dt_t30:
        dias = (dt_t30 - hoje).days
        if dias <= 0:
            prioridade, acao = "Alta", "Cobrar T30"
        elif dias <= DIAS_LEMBRETE:
            prioridade, acao = "Media", "Lembrar T30"
        else:
            prioridade, acao = "Baixa", "Aguardar T30"
        data_alvo = dt_t30
        fase_atual, proxima_fase = "Entre T10 e T30", "T30"

    elif "COMPLETO" in st_geral:
        fase_atual, proxima_fase, acao = "Completo", "Encerrado", "Sem acao"

    elif st_geral == "Em_Andamento":
        prioridade, acao = "Media", "Monitorar"
        fase_atual, proxima_fase = "Em andamento", "Acompanhar"

    dias_para_acao = (data_alvo - hoje).days if data_alvo else None

    return {
        "prioridade": prioridade,
        "fase_atual": fase_atual,
        "proxima_fase": proxima_fase,
        "acao": acao,
        "data_alvo": formatar_data(data_alvo) if data_alvo else "",
        "dias_para_acao": dias_para_acao,
    }


def atualizar_operacional_paciente(paciente) -> None:
    """Recalcula e salva colunas operacionais para um único paciente."""
    resumo = calcular_acao_operacional(paciente)
    acao = resumo["acao"]

    # Detecta mudança de etapa para resetar status WhatsApp
    etapa_nova = _etapa_de_acao(acao)
    etapa_anterior = _etapa_de_acao(paciente.proxima_acao or "")
    if etapa_nova != etapa_anterior:
        if acao in ACOES_QUE_GERAM_CONTATO:
            paciente.status_whatsapp = "NAO_ENVIADO"
            paciente.retorno_contato = "PENDENTE"
            paciente.data_ultimo_whatsapp = ""

    paciente.fase_atual = resumo["fase_atual"]
    paciente.proxima_fase = resumo["proxima_fase"]
    paciente.proxima_acao = acao
    paciente.prioridade_operacional = resumo["prioridade"]
    paciente.data_proxima_acao = resumo["data_alvo"]
    paciente.dias_para_acao = resumo["dias_para_acao"]


def _etapa_de_acao(acao: str) -> str:
    a = acao or ""
    if "T0" in a:
        return "T0"
    if "T10" in a:
        return "T10"
    if "T30" in a:
        return "T30"
    if "Revisar" in a:
        return "REVISAO"
    return ""


# ---------------------------------------------------------------------------
# Sincronização SINAN (lê Google Sheets e importa para o banco)
# ---------------------------------------------------------------------------

def _is_service_account_payload(payload: object) -> bool:
    required = {"client_email", "private_key", "token_uri"}
    return (
        isinstance(payload, dict)
        and payload.get("type") == "service_account"
        and required.issubset(payload)
    )


def _try_load_service_account_info_from_file(path: Path) -> Optional[dict]:
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not _is_service_account_payload(payload):
        return None
    return payload


def _discover_local_google_credentials_file(project_root: Optional[Path] = None) -> Optional[Path]:
    root = project_root or PROJECT_ROOT
    matches: list[Path] = []

    for candidate in sorted(root.glob("*.json")):
        if _try_load_service_account_info_from_file(candidate):
            matches.append(candidate)

    if not matches:
        return None

    if len(matches) > 1:
        arquivos = ", ".join(path.name for path in matches[:5])
        if len(matches) > 5:
            arquivos += ", ..."
        raise RuntimeError(
            "Multiplos arquivos de credenciais Google encontrados na raiz do projeto "
            f"({arquivos}). Defina SFA_GOOGLE_CREDENTIALS_FILE para escolher qual usar."
        )

    return matches[0]


def _load_google_credentials_info(project_root: Optional[Path] = None) -> dict:
    root = project_root or PROJECT_ROOT
    creds_json = os.getenv("SFA_GOOGLE_CREDENTIALS_JSON", "").strip()
    if creds_json:
        try:
            payload = json.loads(creds_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "SFA_GOOGLE_CREDENTIALS_JSON nao contem um JSON valido."
            ) from exc
        if not _is_service_account_payload(payload):
            raise RuntimeError(
                "SFA_GOOGLE_CREDENTIALS_JSON nao contem um JSON valido de service account."
            )
        return payload

    for env_name in ("SFA_GOOGLE_CREDENTIALS_FILE", "GOOGLE_APPLICATION_CREDENTIALS"):
        creds_file = os.getenv(env_name, "").strip()
        if not creds_file:
            continue
        candidate = Path(creds_file).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve()
        payload = _try_load_service_account_info_from_file(candidate)
        if not payload:
            raise RuntimeError(
                f"{env_name} aponta para um arquivo invalido ou inexistente: {candidate}"
            )
        return payload

    discovered = _discover_local_google_credentials_file(root)
    if discovered is not None:
        log.info("Usando credenciais Google detectadas automaticamente em %s", discovered.name)
        payload = _try_load_service_account_info_from_file(discovered)
        if payload:
            return payload

    raise RuntimeError(
        "Credenciais Google nao configuradas. "
        "Defina SFA_GOOGLE_CREDENTIALS_JSON, SFA_GOOGLE_CREDENTIALS_FILE, "
        "GOOGLE_APPLICATION_CREDENTIALS ou mantenha um unico JSON de service account "
        "na raiz do projeto."
    )


def _extract_google_sheet_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", raw)
    if match:
        return match.group(1)
    return raw


def _extract_google_sheet_gid(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.isdigit():
        return raw

    parsed = urlparse(raw)
    for source in (parsed.query, parsed.fragment):
        params = parse_qs(source)
        gids = params.get("gid")
        if gids and gids[0].isdigit():
            return gids[0]

    match = re.search(r"(?:[?#&]gid=)(\d+)", raw)
    if match:
        return match.group(1)
    return ""


def _quote_a1_sheet_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _resolve_sheet_title_by_gid(service, spreadsheet_id: str, sheet_gid: str) -> str:
    try:
        target_gid = int(sheet_gid)
    except ValueError as exc:
        raise RuntimeError(f"SFA_SHEET_GID_SINAN invalido: {sheet_gid}") from exc

    metadata = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(sheetId,title))",
        )
        .execute()
    )
    for sheet in metadata.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("sheetId") == target_gid and props.get("title"):
            return props["title"]

    raise RuntimeError(
        f"Nenhuma aba com gid {sheet_gid} foi encontrada na planilha configurada."
    )


def _resolve_sheet_target(
    service,
    spreadsheet_source: str,
    range_value: str,
    sheet_title: str = "",
    sheet_gid: str = "",
) -> tuple[str, str]:
    spreadsheet_id = _extract_google_sheet_id(spreadsheet_source)
    if not spreadsheet_id:
        return "", ""

    range_value = (range_value or "A:T").strip() or "A:T"
    if "!" in range_value:
        return spreadsheet_id, range_value

    sheet_title = (sheet_title or "").strip()
    sheet_gid = (sheet_gid or "").strip()
    if not sheet_gid:
        sheet_gid = _extract_google_sheet_gid(spreadsheet_source)

    if sheet_title:
        return spreadsheet_id, f"{_quote_a1_sheet_title(sheet_title)}!{range_value}"

    if sheet_gid:
        resolved_title = _resolve_sheet_title_by_gid(service, spreadsheet_id, sheet_gid)
        return spreadsheet_id, f"{_quote_a1_sheet_title(resolved_title)}!{range_value}"

    return spreadsheet_id, range_value


def _resolve_sinan_sheet_target(service) -> tuple[str, str]:
    return _resolve_sheet_target(
        service,
        spreadsheet_source=SHEET_ID_SINAN,
        range_value=SHEET_RANGE_SINAN,
        sheet_title=SHEET_TITLE_SINAN,
        sheet_gid=SHEET_GID_SINAN,
    )


def _normalize_form_header(value: object) -> str:
    normalized = normalizar_nome_chave(value or "")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return re.sub(r"^\d+\s+", "", normalized).strip()


def _build_header_lookup(headers: list) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for index, header in enumerate(headers):
        key = _normalize_form_header(header)
        if key and key not in lookup:
            lookup[key] = index
    return lookup


def _lookup_form_value(row: list, header_lookup: dict[str, int], aliases: list[str]) -> str:
    for alias in aliases:
        idx = header_lookup.get(_normalize_form_header(alias))
        if idx is not None and idx < len(row):
            return str(row[idx] or "").strip()
    return ""


def _safe_int(value: object) -> int:
    digits = re.sub(r"[^\d-]", "", str(value or ""))
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def _safe_decimal_text(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "0"
    cleaned = raw.replace(".", "").replace(",", ".")
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    if cleaned.count(".") > 1:
        first, *rest = cleaned.split(".")
        cleaned = first + "." + "".join(rest)
    return cleaned or "0"


def _t0_response_keys(
    token_acesso: str,
    id_estudo: str,
    ficha_sinan: str,
    nome: str,
    data_nascimento: str,
) -> set[str]:
    keys = set()
    token_norm = str(token_acesso or "").strip()
    if token_norm:
        keys.add(f"tk:{token_norm}")

    id_norm = str(id_estudo or "").strip().upper()
    if id_norm:
        keys.add(f"id:{id_norm}")

    ficha_norm = str(ficha_sinan or "").strip()
    if ficha_norm:
        keys.add(f"fs:{ficha_norm}")

    nome_norm = normalizar_nome_chave(nome or "")
    data_norm = formatar_data(parse_data(data_nascimento)) if data_nascimento else ""
    if nome_norm and data_norm:
        keys.add(f"nd:{nome_norm}|{data_norm}")
    return keys


def _build_existing_t0_response_keys() -> set[str]:
    from models.sfa import SfaRespostaT0

    existing_keys = set()
    for resposta in SfaRespostaT0.query.with_entities(
        SfaRespostaT0.id_estudo,
        SfaRespostaT0.nome,
        SfaRespostaT0.data_nascimento,
        SfaRespostaT0.dados_json,
    ).all():
        token_acesso = ""
        ficha_sinan = ""
        if resposta.dados_json:
            try:
                payload = json.loads(resposta.dados_json)
            except json.JSONDecodeError:
                payload = {}
            token_acesso = str(payload.get("token_acesso") or payload.get("token") or "").strip()
            ficha_sinan = str(payload.get("ficha_sinan") or payload.get("numero_ficha_sinan") or "").strip()
        existing_keys.update(
            _t0_response_keys(
                token_acesso,
                resposta.id_estudo,
                ficha_sinan,
                resposta.nome,
                resposta.data_nascimento,
            )
        )
    return existing_keys


def _resolve_t0_response_sheet_target(service) -> tuple[str, str]:
    return _resolve_sheet_target(
        service,
        spreadsheet_source=T0_RESPONSE_SHEET,
        range_value=T0_RESPONSE_RANGE,
        sheet_title=T0_RESPONSE_TITLE,
        sheet_gid=T0_RESPONSE_GID,
    )


def _get_sheets_service():
    """Retorna cliente autenticado da Google Sheets API usando conta de serviço."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            "google-api-python-client não instalado. "
            "Execute: pip install google-api-python-client google-auth"
        )

    info = _load_google_credentials_info()
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    return build("sheets", "v4", credentials=creds)


def sincronizar_sinan() -> dict:
    """
    Lê a planilha SINAN no Google Sheets e importa casos novos para o banco.
    Equivale a sincronizarSINAN() do GAS.

    Retorna: {"novos": int, "erros": int}
    """
    spreadsheet_id = _extract_google_sheet_id(SHEET_ID_SINAN)
    if not spreadsheet_id:
        log.warning("SFA_SHEET_ID_SINAN não configurado — sincronização SINAN ignorada.")
        return {"novos": 0, "erros": 0}

    from extensions import db
    from models.sfa import SfaPaciente, SfaSinanLog

    try:
        service = _get_sheets_service()
        spreadsheet_id, sheet_range = _resolve_sinan_sheet_target(service)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=sheet_range)
            .execute()
        )
        rows = result.get("values", [])
    except Exception as exc:
        log.error("Erro ao ler planilha SINAN: %s", exc)
        registrar_auditoria("ERROR", "SINAN_SYNC", "sincronizar_sinan",
                             f"Falha ao ler Google Sheets: {exc}")
        return {"novos": 0, "erros": 1}

    if len(rows) < 2:
        log.info("Planilha SINAN vazia ou sem linhas de dados.")
        return {"novos": 0, "erros": 0}

    chaves_importadas = {
        r.chave_dedup for r in SfaSinanLog.query.with_entities(SfaSinanLog.chave_dedup).all()
    }

    novos = 0
    erros = 0
    linhas_ajustadas = []

    for row in rows[1:]:  # pula cabeçalho
        # Garante que a linha tenha colunas suficientes
        while len(row) < 20:
            row.append("")

        chave = chave_dedup_sinan(row)
        if not chave or chave in chaves_importadas:
            continue

        nome = str(row[COLS_SINAN["NOME"]] or "").strip()
        if not nome:
            continue

        ajustes_linha = []
        tel_bruto = str(row[COLS_SINAN["TELEFONE"]] or "")
        telefone = _sanitize_limited_text(
            normalizar_telefone(tel_bruto) or tel_bruto,
            25,
            "telefone",
            ajustes_linha,
        )
        nome = _sanitize_limited_text(nome, 200, "nome", ajustes_linha)
        bairro = _sanitize_limited_text(row[COLS_SINAN["BAIRRO"]], 120, "bairro", ajustes_linha)
        endereco = _sanitize_limited_text(row[COLS_SINAN["ENDERECO"]], 300, "endereco", ajustes_linha)
        ficha_sinan = _sanitize_limited_text(row[COLS_SINAN["FICHA_SINAN"]], 50, "ficha_sinan", ajustes_linha)
        n_caso = _sanitize_limited_text(row[COLS_SINAN["N"]], 20, "n_caso", ajustes_linha)
        resultado = _sanitize_limited_text(
            str(row[COLS_SINAN["RESULTADO"]] or "").lower(),
            120,
            "resultado",
            ajustes_linha,
        )
        tipo_exame = _sanitize_limited_text(row[COLS_SINAN["TIPO_EXAME"]], 120, "tipo_exame", ajustes_linha)
        data_not = _sanitize_limited_text(row[COLS_SINAN["DATA_NOTIFICACAO"]], 20, "data_notificacao", ajustes_linha)
        data_ini = _sanitize_limited_text(
            row[COLS_SINAN["DATA_INICIO_SINTOMAS"]],
            20,
            "data_inicio_sintomas",
            ajustes_linha,
        )
        data_nasc_raw = row[COLS_SINAN["DATA_NASCIMENTO"]]

        # Parseia data de nascimento
        data_nasc = ""
        if data_nasc_raw:
            d = parse_data(data_nasc_raw)
            data_nasc = formatar_data(d) if d else str(data_nasc_raw)
        data_nasc = _sanitize_limited_text(data_nasc, 20, "data_nascimento", ajustes_linha)

        is_positivo = ("positiv" in resultado and "não positiv" not in resultado
                       and "nao positiv" not in resultado)
        is_reagente = ("reagente" in resultado and "não reagente" not in resultado
                       and "nao reagente" not in resultado)
        grupo = "A" if (is_positivo or is_reagente) else "B"

        try:
            id_estudo = proximo_id_estudo()
            paciente = SfaPaciente(
                id_estudo=id_estudo,
                ficha_sinan=ficha_sinan,
                nome=nome,
                telefone=telefone,
                bairro=bairro,
                endereco=endereco,
                data_nascimento=data_nasc,
                grupo=grupo,
                status_t0="SINAN_Aguardando_T0",
                status_geral="SINAN_Notificado",
            )
            paciente.gerar_token()
            atualizar_operacional_paciente(paciente)
            db.session.add(paciente)

            log_entry = SfaSinanLog(
                chave_dedup=chave,
                ficha_sinan=ficha_sinan,
                n_caso=n_caso,
                nome=nome,
                telefone=telefone,
                bairro=bairro,
                data_notificacao=data_not,
                data_inicio_sintomas=data_ini,
                tipo_exame=tipo_exame,
                resultado=resultado,
                grupo=grupo,
                id_estudo_vinculado=id_estudo,
            )
            db.session.add(log_entry)
            db.session.flush()
            chaves_importadas.add(chave)
            if ajustes_linha:
                linhas_ajustadas.append({"chave": chave, "campos": ajustes_linha})
            novos += 1
        except Exception as exc:
            db.session.rollback()
            log.error("Erro ao importar caso SINAN %s: %s", chave, exc)
            erros += 1

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        log.error("Erro ao commit sincronização SINAN: %s", exc)
        erros += novos
        novos = 0

    if linhas_ajustadas:
        registrar_auditoria(
            "WARN",
            "SINAN_DADOS_AJUSTADOS",
            "sincronizar_sinan",
            f"{len(linhas_ajustadas)} linha(s) ajustada(s) antes da importacao.",
            detalhes={
                "total_linhas_ajustadas": len(linhas_ajustadas),
                "linhas": linhas_ajustadas[:20],
            },
        )

    log.info("SINAN sync: %d novos, %d erros, %d ajustes", novos, erros, len(linhas_ajustadas))
    return {"novos": novos, "erros": erros, "ajustes": len(linhas_ajustadas)}


# ---------------------------------------------------------------------------
# Submissão dos formulários (webhooks vindos do Google Forms via Apps Script)
# ---------------------------------------------------------------------------

def on_submit_t0(dados: dict) -> dict:
    """
    Processa submissão do formulário T0.
    `dados` deve conter os campos mapeados do Forms.
    Retorna {"ok": bool, "id_estudo": str, "acao": str}
    """
    from extensions import db
    from models.sfa import SfaPaciente, SfaRespostaT0

    token_acesso = str(dados.get("token_acesso") or dados.get("token") or "").strip()
    id_estudo = str(dados.get("id_estudo") or "").strip()
    ficha_sinan = str(dados.get("ficha_sinan") or dados.get("numero_ficha_sinan") or "").strip()
    nome = str(dados.get("nome") or "").strip()
    data_nasc = str(dados.get("data_nascimento") or "").strip()
    aceite_tcle = dados.get("aceite_tcle")
    if aceite_tcle in (None, "", []):
        aceite_tcle = dados.get("decisao_tcle")

    dados["aceite_tcle"] = (
        aceite_tcle if isinstance(aceite_tcle, list) else [str(aceite_tcle or "").strip()]
    )
    dados["tcle_assinado_por"] = nome
    dados["assinatura_tcle_nome"] = nome
    dados["consentimento_registrado_em"] = (
        str(dados.get("consentimento_registrado_em") or "").strip()
        or datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    )

    if not t0_consentimento_aceito(dados.get("aceite_tcle")):
        return {"ok": False, "erro": "Aceite do TCLE ausente"}
    if not nome:
        return {"ok": False, "erro": "Nome completo ausente para registrar a assinatura do TCLE"}

    if not token_acesso and not id_estudo and not ficha_sinan and not (nome and data_nasc):
        registrar_auditoria("WARN", "T0_SEM_IDENTIFICACAO", "on_submit_t0",
                             "T0 recebido sem token_acesso, id_estudo, ficha_sinan e sem nome/data de nascimento.")
        return {"ok": False, "erro": "Identificação insuficiente"}

    hoje = date.today()
    dt_t10 = hoje + timedelta(days=DIAS_T10)
    dt_t30 = hoje + timedelta(days=DIAS_T30)

    paciente = None

    # 1ª tentativa: id_estudo
    if token_acesso:
        paciente = SfaPaciente.query.filter_by(token_acesso=token_acesso).first()
        if not paciente:
            registrar_auditoria("WARN", "TOKEN_T0_NAO_ENCONTRADO", "on_submit_t0",
                                 f"T0 recebido com token_acesso nao encontrado: {token_acesso}")

    if id_estudo:
        paciente = paciente or SfaPaciente.query.filter_by(id_estudo=id_estudo).first()

    if ficha_sinan:
        paciente = paciente or SfaPaciente.query.filter_by(ficha_sinan=ficha_sinan).first()

    # 2ª tentativa: nome + data nascimento
    if not paciente and nome and data_nasc:
        nome_norm = normalizar_nome_chave(nome)
        nasc_norm = str(parse_data(data_nasc) or "")
        for p in SfaPaciente.query.all():
            if (normalizar_nome_chave(p.nome or "") == nome_norm
                    and str(parse_data(p.data_nascimento) or "") == nasc_norm):
                paciente = p
                log.warning("T0 vinculado por nome+data (sem id_estudo): linha %s", p.id_estudo)
                break

    acao = "atualizado"

    if paciente:
        if ficha_sinan and not paciente.ficha_sinan:
            paciente.ficha_sinan = ficha_sinan
        paciente.data_t0 = formatar_data(hoje)
        paciente.data_t10 = formatar_data(dt_t10)
        paciente.data_t30 = formatar_data(dt_t30)
        paciente.status_t0 = "T0_Completo"
        paciente.status_t10 = "Aguardando"
        paciente.status_t30 = "Aguardando"
        paciente.status_geral = "Em_Andamento"
        atualizar_operacional_paciente(paciente)
    else:
        # Cria novo registro (participante sem pré-cadastro SINAN)
        id_novo = id_estudo or proximo_id_estudo()
        paciente = SfaPaciente(
            id_estudo=id_novo,
            ficha_sinan=ficha_sinan,
            nome=nome,
            data_nascimento=data_nasc,
            grupo=GRUPO_PENDENTE,
            data_t0=formatar_data(hoje),
            data_t10=formatar_data(dt_t10),
            data_t30=formatar_data(dt_t30),
            status_t0="T0_Completo",
            status_t10="Aguardando",
            status_t30="Aguardando",
            status_geral="Em_Andamento",
        )
        paciente.gerar_token()
        atualizar_operacional_paciente(paciente)
        db.session.add(paciente)
        acao = "criado"
        registrar_auditoria("WARN", "PENDENTE_REVISAO", "on_submit_t0",
                             "T0 criado sem pré-cadastro SINAN; caso enviado para revisão.",
                             {"nome": nome, "data_nascimento": data_nasc},
                             id_estudo=id_novo)

    # Salva resposta T0
    resposta = SfaRespostaT0(
        id_estudo=paciente.id_estudo,
        nome=nome,
        data_nascimento=data_nasc,
        tipo_residencia=dados.get("tipo_residencia", ""),
        data_inicio_sintomas=dados.get("data_inicio_sintomas", ""),
        dias_incap=int(dados.get("dias_incap") or 0),
        internacao=dados.get("internacao", ""),
        custo_total=Decimal(str(dados.get("custo_total") or 0).replace(",", ".")),
        ausencia_familiar=dados.get("ausencia_familiar", ""),
        dados_json=json.dumps(dados, ensure_ascii=False),
    )
    db.session.add(resposta)
    db.session.commit()

    return {"ok": True, "id_estudo": paciente.id_estudo, "acao": acao}


def on_submit_t10(dados: dict) -> dict:
    """Processa submissão do formulário T10."""
    from extensions import db
    from models.sfa import SfaPaciente, SfaRespostaT10

    id_estudo = str(dados.get("id_estudo") or "").strip()
    if not id_estudo:
        registrar_auditoria("WARN", "T10_SEM_IDENTIFICADOR", "on_submit_t10",
                             "T10 recebido sem id_estudo.")
        return {"ok": False, "erro": "id_estudo ausente"}

    paciente = SfaPaciente.query.filter_by(id_estudo=id_estudo).first()
    if not paciente:
        registrar_auditoria("ERROR", "STATUS_NAO_ATUALIZADO", "on_submit_t10",
                             f"T10 recebido mas paciente não encontrado: {id_estudo}",
                             id_estudo=id_estudo)
        return {"ok": False, "erro": "Paciente não encontrado"}

    paciente.status_t10 = "T10_Completo"
    atualizar_operacional_paciente(paciente)

    resposta = SfaRespostaT10(
        id_estudo=id_estudo,
        dias_incap_novos=int(dados.get("dias_incap_novos") or 0),
        custo_remedios=Decimal(str(dados.get("custo_remedios") or 0).replace(",", ".")),
        custo_consultas=Decimal(str(dados.get("custo_consultas") or 0).replace(",", ".")),
        custo_transporte=Decimal(str(dados.get("custo_transporte") or 0).replace(",", ".")),
        custo_outros=Decimal(str(dados.get("custo_outros") or 0).replace(",", ".")),
        dados_json=json.dumps(dados, ensure_ascii=False),
    )
    db.session.add(resposta)
    db.session.commit()
    return {"ok": True, "id_estudo": id_estudo}


def on_submit_t30(dados: dict) -> dict:
    """Processa submissão do formulário T30."""
    from extensions import db
    from models.sfa import SfaPaciente, SfaRespostaT30

    id_estudo = str(dados.get("id_estudo") or "").strip()
    if not id_estudo:
        registrar_auditoria("WARN", "T30_SEM_IDENTIFICADOR", "on_submit_t30",
                             "T30 recebido sem id_estudo.")
        return {"ok": False, "erro": "id_estudo ausente"}

    paciente = SfaPaciente.query.filter_by(id_estudo=id_estudo).first()
    if not paciente:
        registrar_auditoria("ERROR", "STATUS_NAO_ATUALIZADO", "on_submit_t30",
                             f"T30 recebido mas paciente não encontrado: {id_estudo}",
                             id_estudo=id_estudo)
        return {"ok": False, "erro": "Paciente não encontrado"}

    paciente.status_t10 = "T10_Completo"  # garante consistência
    paciente.status_t30 = "T30_Completo"
    paciente.status_geral = "COMPLETO"
    atualizar_operacional_paciente(paciente)

    resposta = SfaRespostaT30(
        id_estudo=id_estudo,
        dias_incap_novos=int(dados.get("dias_incap_novos") or 0),
        custo_remedios=Decimal(str(dados.get("custo_remedios") or 0).replace(",", ".")),
        custo_consultas=Decimal(str(dados.get("custo_consultas") or 0).replace(",", ".")),
        custo_transporte=Decimal(str(dados.get("custo_transporte") or 0).replace(",", ".")),
        custo_outros=Decimal(str(dados.get("custo_outros") or 0).replace(",", ".")),
        dados_json=json.dumps(dados, ensure_ascii=False),
    )
    db.session.add(resposta)
    db.session.commit()
    return {"ok": True, "id_estudo": id_estudo}


# ---------------------------------------------------------------------------
# Verificação diária de alertas (equivale a verificarSeguimento do GAS)
# ---------------------------------------------------------------------------

def sincronizar_respostas_t0() -> dict:
    """Importa respostas T0 a partir da planilha vinculada ao Google Forms."""
    if not T0_RESPONSE_SHEET:
        log.info("SFA_T0_RESPONSE_SHEET nao configurado — sincronizacao T0 ignorada.")
        return {"importados": 0, "ignorados": 0, "erros": 0}

    try:
        service = _get_sheets_service()
        spreadsheet_id, sheet_range = _resolve_t0_response_sheet_target(service)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=sheet_range)
            .execute()
        )
        rows = result.get("values", [])
    except Exception as exc:
        log.error("Erro ao ler respostas T0: %s", exc)
        registrar_auditoria(
            "ERROR",
            "T0_SHEET_SYNC",
            "sincronizar_respostas_t0",
            f"Falha ao ler planilha de respostas T0: {exc}",
        )
        return {"importados": 0, "ignorados": 0, "erros": 1}

    if len(rows) < 2:
        return {"importados": 0, "ignorados": 0, "erros": 0}

    header_lookup = _build_header_lookup(rows[0])
    existing_keys = _build_existing_t0_response_keys()
    importados = 0
    ignorados = 0
    erros = 0

    for row in rows[1:]:
        if not any(str(cell or "").strip() for cell in row):
            continue

        dados = {
            "token_acesso": _lookup_form_value(row, header_lookup, FORM_T0_HEADER_ALIASES["token_acesso"]),
            "id_estudo": _lookup_form_value(row, header_lookup, FORM_T0_HEADER_ALIASES["id_estudo"]),
            "ficha_sinan": _lookup_form_value(row, header_lookup, FORM_T0_HEADER_ALIASES["ficha_sinan"]),
            "nome": _lookup_form_value(row, header_lookup, FORM_T0_HEADER_ALIASES["nome"]),
            "data_nascimento": _lookup_form_value(row, header_lookup, FORM_T0_HEADER_ALIASES["data_nascimento"]),
            "tipo_residencia": _lookup_form_value(row, header_lookup, FORM_T0_HEADER_ALIASES["tipo_residencia"]),
            "data_inicio_sintomas": _lookup_form_value(row, header_lookup, FORM_T0_HEADER_ALIASES["data_inicio_sintomas"]),
            "dias_incap": _safe_int(_lookup_form_value(row, header_lookup, FORM_T0_HEADER_ALIASES["dias_incap"])),
            "internacao": _lookup_form_value(row, header_lookup, FORM_T0_HEADER_ALIASES["internacao"]),
            "custo_total": _safe_decimal_text(_lookup_form_value(row, header_lookup, FORM_T0_HEADER_ALIASES["custo_total"])),
            "ausencia_familiar": _lookup_form_value(row, header_lookup, FORM_T0_HEADER_ALIASES["ausencia_familiar"]),
            "_origem": "google_sheets_t0_response",
            "_timestamp_form": _lookup_form_value(row, header_lookup, FORM_T0_HEADER_ALIASES["timestamp"]),
        }

        row_keys = _t0_response_keys(
            dados["token_acesso"],
            dados["id_estudo"],
            dados["ficha_sinan"],
            dados["nome"],
            dados["data_nascimento"],
        )
        if not row_keys:
            ignorados += 1
            continue

        if row_keys & existing_keys:
            ignorados += 1
            continue

        try:
            resultado = on_submit_t0(dados)
            if resultado.get("ok"):
                importados += 1
                existing_keys.update(row_keys)
                existing_keys.update(
                    _t0_response_keys(
                        dados["token_acesso"],
                        resultado.get("id_estudo", ""),
                        dados["ficha_sinan"],
                        dados["nome"],
                        dados["data_nascimento"],
                    )
                )
            else:
                ignorados += 1
        except Exception as exc:
            erros += 1
            log.error(
                "Erro ao importar resposta T0 (%s/%s): %s",
                dados.get("id_estudo") or "-",
                dados.get("nome") or "-",
                exc,
            )

    log.info("T0 response sync: %d importadas, %d ignoradas, %d erros", importados, ignorados, erros)
    return {"importados": importados, "ignorados": ignorados, "erros": erros}


def verificar_seguimento() -> dict:
    """
    Verifica prazos de T10 e T30 e atualiza status de atraso.
    Retorna contagens de atrasados.
    """
    from extensions import db
    from models.sfa import SfaPaciente

    hoje = date.today()
    sem_t0 = []
    atras_t10 = []
    atras_t30 = []

    pacientes = SfaPaciente.query.filter(
        SfaPaciente.status_geral != "COMPLETO"
    ).all()

    for p in pacientes:
        # Sem T0 há muito tempo
        if p.status_geral == "SINAN_Notificado" and p.timestamp_cadastro:
            ts = p.timestamp_cadastro
            if hasattr(ts, "date"):
                ts = ts.date()
            dias_sem = (hoje - ts).days
            if dias_sem >= DIAS_SEM_T0_ALERTA:
                sem_t0.append(p.id_estudo)

        # T10 atrasado
        dt10 = parse_data(p.data_t10)
        if p.status_t10 == "Aguardando" and dt10:
            dias = (dt10 - hoje).days
            if dias < -TOLERANCIA_ALERTA_DIAS:
                p.status_t10 = "ATRASADO"
                atras_t10.append(p.id_estudo)

        # T30 atrasado → perda de seguimento
        dt30 = parse_data(p.data_t30)
        if p.status_t30 == "Aguardando" and dt30:
            dias = (dt30 - hoje).days
            if dias < -TOLERANCIA_ALERTA_DIAS:
                p.status_t30 = "ATRASADO"
                p.status_geral = "PERDA_SEGUIMENTO"
                atras_t30.append(p.id_estudo)

        atualizar_operacional_paciente(p)

    db.session.commit()
    log.info("verificar_seguimento: %d T10 atrasados, %d T30 atrasados", len(atras_t10), len(atras_t30))
    return {"sem_t0": sem_t0, "atrasados_t10": atras_t10, "atrasados_t30": atras_t30}


# ---------------------------------------------------------------------------
# Contatos do dia (fila de WhatsApp para hoje)
# ---------------------------------------------------------------------------

def contatos_do_dia() -> dict:
    """
    Retorna as listas de contatos para hoje agrupadas por ação.
    Equivale a atualizarContatosDoDia() do GAS.
    """
    from models.sfa import SfaPaciente

    hoje = date.today()

    try:
        novos = SfaPaciente.query.filter_by(status_geral="SINAN_Notificado").all()
    except (ProgrammingError, OperationalError, NoSuchTableError, InternalError):
        db.session.rollback()
        log.warning("SFA: tabela 'sfa_paciente' não encontrada em contatos_do_dia", exc_info=False)
        return {"data": hoje.strftime("%d/%m/%Y"), "novos": [], "t10": [], "t30": []}

    def vencendo_em(paciente, campo_data: str, status: str) -> bool:
        if getattr(paciente, f"status_{campo_data}") != "Aguardando":
            return False
        dt = parse_data(getattr(paciente, f"data_{campo_data}"))
        if not dt:
            return False
        return 0 <= (dt - hoje).days <= DIAS_LEMBRETE

    todos = _safe_query_all(SfaPaciente)
    pend_t10 = [p for p in todos if vencendo_em(p, "t10", "Aguardando")]
    pend_t30 = [p for p in todos if vencendo_em(p, "t30", "Aguardando")]

    return {
        "data": hoje.strftime("%d/%m/%Y"),
        "novos": novos,
        "t10": pend_t10,
        "t30": pend_t30,
    }


# ---------------------------------------------------------------------------
# Estatísticas do painel (equivale a atualizarPainelOperacional)
# ---------------------------------------------------------------------------

def stats_painel() -> dict:
    """Retorna KPIs e fila do dia para o dashboard Flask."""
    from models.sfa import SfaAuditoria, SfaPaciente

    todos = _safe_query_all(SfaPaciente)
    total = len(todos)

    def cnt(fn):
        return sum(1 for p in todos if fn(p))

    fila = sorted(
        [p for p in todos if p.prioridade_operacional in ("Alta", "Media")
         or p.proxima_acao == "Convidar T0"],
        key=lambda p: (
            {"Alta": 0, "Media": 1, "Baixa": 2}.get(p.prioridade_operacional or "", 9),
            p.dias_para_acao if p.dias_para_acao is not None else 9999,
        )
    )[:25]

    try:
        alertas_recentes = (
            SfaAuditoria.query
            .order_by(SfaAuditoria.timestamp.desc())
            .limit(10)
            .all()
        )
    except (ProgrammingError, OperationalError, NoSuchTableError, InternalError):
        db.session.rollback()
        log.warning("SFA: tabela 'sfa_auditoria' não encontrada em stats_painel", exc_info=False)
        alertas_recentes = []

    pendentes_revisao = [p for p in todos if p.grupo == GRUPO_PENDENTE]

    return {
        "total": total,
        "aguardando_t0": cnt(lambda p: p.status_geral == "SINAN_Notificado"),
        "grupo_a": cnt(lambda p: p.grupo == "A"),
        "grupo_b": cnt(lambda p: p.grupo == "B"),
        "pendentes_revisao": cnt(lambda p: p.grupo == GRUPO_PENDENTE),
        "completos": cnt(lambda p: "COMPLETO" in (p.status_geral or "")),
        "perdas": cnt(lambda p: "PERDA" in (p.status_geral or "")),
        "fila": fila,
        "alertas_recentes": alertas_recentes,
        "pacientes_revisao": pendentes_revisao,
    }


# ---------------------------------------------------------------------------
# Job agendado: roda todas as rotinas diárias
# ---------------------------------------------------------------------------

def rodar_rotina_diaria(app) -> dict:
    """
    Executa sincronizar_sinan + sincronizar_respostas_t0 + verificar_seguimento dentro do app context.
    Chamado pelo APScheduler.
    """
    with app.app_context():
        resultado_sinan = sincronizar_sinan()
        resultado_t0 = sincronizar_respostas_t0()
        resultado_seg = verificar_seguimento()
        log.info("Rotina diária SFA concluída: %s", {**resultado_sinan, **resultado_seg})
        return {**resultado_sinan, **resultado_t0, **resultado_seg}
