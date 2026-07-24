"""Blueprint do Portal SIM (Servico de Inspecao Municipal de Orlandia).

Porta o prototipo local `portal-sim` (Documents/SIM - Orlandia) para dentro do
PetOrlandia, montado em /sim. Mantem usuarios e tabelas proprios (prefixo sim_),
sem misturar com as contas publicas do PetOrlandia. Anexos ficam no banco
principal (LargeBinary) para sobreviver ao filesystem efemero do Heroku.

Base legal: LC 84/2024, LC 104/2026 e Decretos 5.368, 5.373 e 5.374/2024.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import secrets
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from flask import Blueprint, abort, jsonify, redirect, request, send_file, send_from_directory

from extensions import csrf, db

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTAL_STATIC_DIR = PROJECT_ROOT / "static" / "sim_portal"

PROCESS_ID = "SIM-ORL-2026-0001"
REGISTRY_PROCESS_ID = "SIM-REGISTRO-GERAL"

# Prazo de defesa do autuado: art. 145 do Decreto municipal 5.368/2024.
DEFENSE_DEADLINE_DAYS = 10

ACT_PREFIXES = {
    "Auto de infracao": "AI",
    "Termo de advertencia": "TA",
    "Auto de apreensao": "AA",
    "Termo de suspensao de atividades": "TS",
    "Termo de interdicao": "TI",
    "Notificacao": "NT",
    "Termo de coleta de amostras": "TC",
}

# Prefixo de docId usado para anexar o rotulo direto na tela de cada produto,
# em vez do documento generico "rotulos-produtos" do checklist.
PRODUCT_LABEL_PREFIX = "rotulo-produto-"


# ---------------------------------------------------------------------------
# Modelos (todas as tabelas prefixadas com sim_)
# ---------------------------------------------------------------------------

class SimUser(db.Model):
    __tablename__ = "sim_users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False)  # sim | establishment
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.String(40), nullable=False)


class SimSession(db.Model):
    __tablename__ = "sim_sessions"
    token = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("sim_users.id"), nullable=False)
    created_at = db.Column(db.String(40), nullable=False)
    last_seen_at = db.Column(db.String(40), nullable=False)


class SimProcessState(db.Model):
    __tablename__ = "sim_process_state"
    process_id = db.Column(db.String(60), primary_key=True)
    state_json = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.String(40), nullable=False)
    updated_by = db.Column(db.Integer)


class SimStateRevision(db.Model):
    __tablename__ = "sim_state_revisions"
    id = db.Column(db.Integer, primary_key=True)
    process_id = db.Column(db.String(60), nullable=False)
    state_json = db.Column(db.Text, nullable=False)
    changed_by = db.Column(db.Integer)
    changed_by_name = db.Column(db.String(255), nullable=False)
    changed_at = db.Column(db.String(40), nullable=False)
    reason = db.Column(db.String(255), nullable=False)


class SimAuditEvent(db.Model):
    __tablename__ = "sim_audit_events"
    id = db.Column(db.Integer, primary_key=True)
    process_id = db.Column(db.String(60), nullable=False)
    actor_user_id = db.Column(db.Integer)
    actor_name = db.Column(db.String(255), nullable=False)
    action = db.Column(db.Text, nullable=False)
    version = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.String(40), nullable=False)


class SimNotification(db.Model):
    __tablename__ = "sim_notifications"
    id = db.Column(db.Integer, primary_key=True)
    process_id = db.Column(db.String(60), nullable=False)
    to_role = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    upload_id = db.Column(db.String(40))
    document_id = db.Column(db.String(80))
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.String(40), nullable=False)
    read_at = db.Column(db.String(40))


class SimUpload(db.Model):
    __tablename__ = "sim_uploads"
    id = db.Column(db.String(40), primary_key=True)
    process_id = db.Column(db.String(60), nullable=False)
    document_id = db.Column(db.String(80), nullable=False)
    version_no = db.Column(db.Integer, nullable=False, default=1)
    original_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(120))
    size_bytes = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    content = db.Column(db.LargeBinary, nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("sim_users.id"), nullable=False)
    uploaded_by_role = db.Column(db.String(30), nullable=False, default="establishment")
    visibility = db.Column(db.String(20), nullable=False, default="all")
    note = db.Column(db.Text)
    uploaded_at = db.Column(db.String(40), nullable=False)


class SimEstablishment(db.Model):
    __tablename__ = "sim_establishments"
    id = db.Column(db.Integer, primary_key=True)
    legal_name = db.Column(db.String(255), nullable=False)
    trade_name = db.Column(db.String(255))
    cnpj_cpf = db.Column(db.String(40))
    sim_number = db.Column(db.String(40))
    registration_date = db.Column(db.String(20))
    address = db.Column(db.String(255))
    district = db.Column(db.String(120))
    city = db.Column(db.String(120), default="Orlandia")
    state = db.Column(db.String(5), default="SP")
    zip = db.Column(db.String(20))
    phone = db.Column(db.String(40))
    email = db.Column(db.String(255))
    legal_responsible = db.Column(db.String(255))
    technical_responsible = db.Column(db.String(255))
    last_project_protocol = db.Column(db.String(120))
    situation = db.Column(db.String(60), nullable=False, default="Em registro")
    classification = db.Column(db.String(255))
    species_capacity = db.Column(db.Text)
    risk_level = db.Column(db.String(20), default="Medio")
    inspection_frequency_days = db.Column(db.Integer, default=90)
    notes = db.Column(db.Text)
    created_at = db.Column(db.String(40), nullable=False)
    updated_at = db.Column(db.String(40), nullable=False)


class SimFiscalAct(db.Model):
    __tablename__ = "sim_fiscal_acts"
    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey("sim_establishments.id"))
    act_type = db.Column(db.String(60), nullable=False)
    act_number = db.Column(db.String(30), nullable=False)
    act_date = db.Column(db.String(20))
    place = db.Column(db.String(255))
    legal_basis = db.Column(db.Text)
    facts = db.Column(db.Text)
    seized_material = db.Column(db.Text)
    attenuating_aggravating = db.Column(db.Text)
    notification = db.Column(db.Text)
    witnesses = db.Column(db.Text)
    other_info = db.Column(db.Text)
    status = db.Column(db.String(40), nullable=False, default="Lavrado")
    science_date = db.Column(db.String(20))
    defense_deadline = db.Column(db.String(20))
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.String(40), nullable=False)
    updated_at = db.Column(db.String(40), nullable=False)


class SimInspection(db.Model):
    __tablename__ = "sim_inspections"
    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey("sim_establishments.id"))
    inspection_date = db.Column(db.String(20))
    kind = db.Column(db.String(80))
    inspector = db.Column(db.String(255))
    findings = db.Column(db.Text)
    decision = db.Column(db.String(120))
    next_due = db.Column(db.String(20))
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.String(40), nullable=False)
    updated_at = db.Column(db.String(40), nullable=False)


class SimSample(db.Model):
    __tablename__ = "sim_samples"
    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey("sim_establishments.id"))
    collection_date = db.Column(db.String(20))
    product = db.Column(db.String(255))
    analysis_type = db.Column(db.String(120))
    lab = db.Column(db.String(255))
    result = db.Column(db.Text)
    status = db.Column(db.String(60), default="Coletada")
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.String(40), nullable=False)
    updated_at = db.Column(db.String(40), nullable=False)


SIM_TABLES = [
    SimUser.__table__,
    SimSession.__table__,
    SimProcessState.__table__,
    SimStateRevision.__table__,
    SimAuditEvent.__table__,
    SimNotification.__table__,
    SimUpload.__table__,
    SimEstablishment.__table__,
    SimFiscalAct.__table__,
    SimInspection.__table__,
    SimSample.__table__,
]


# ---------------------------------------------------------------------------
# Semente do processo piloto GUERRA MILK
# ---------------------------------------------------------------------------

SEED_STATE = {
    "role": "establishment",
    "view": "dashboard",
    "printForm": "anexoI",
    "protocol": {
        "id": PROCESS_ID,
        "status": "corrections",
        "version": 2,
        "submittedAt": "2026-07-23T09:14:00-03:00",
        "updatedAt": "2026-07-23T09:32:00-03:00",
        "assignedTo": "Lucas Marcelino Campos Ferreira",
    },
    "establishment": {
        "legalName": "LF-GUERRA MILK ORLANDIA - ME",
        "tradeName": "GUERRA MILK",
        "cnpj": "12.934.929/0001-77",
        "cnae": "1052-0/00 - Fabricacao de laticinios",
        "classification": "Unidade de beneficiamento de leite e derivados",
        "address": "Avenida F, 464-A",
        "district": "Jardim Boa Vista",
        "city": "Orlandia",
        "state": "SP",
        "zip": "14620-000",
        "simNumber": "Pendente",
    },
    "legalResponsible": {"name": "Jose Francisco Guerra"},
    "documents": [
        {"id": "requerimento-assinado", "item": "01", "group": "art11", "name": "Requerimento ao SIM solicitando o registro", "hint": "Preencha a ficha no portal, imprima o Anexo I, assine no gov.br e envie aqui.", "required": True, "status": "Pendente", "file": "", "internal": False, "formView": "establishment", "printForm": "anexoI"},
        {"id": "plantas-baixas", "item": "02", "group": "art11", "name": "Planta baixa ou croqui das construcoes/reformas + memorial descritivo da construcao", "hint": "Elaborados por profissional habilitado; o Anexo III do portal ajuda no memorial descritivo.", "required": True, "status": "Pendente", "file": "", "internal": False},
        {"id": "contrato-social-cnpj", "item": "03", "group": "art11", "name": "Contrato ou estatuto social registrado, quando houver firma constituida", "hint": "Junta Comercial (empresas) ou cartorio; MEI usa o Certificado CCMEI.", "required": True, "status": "Pendente", "file": "", "internal": False},
        {"id": "cpf-cnpj", "item": "04", "group": "art11", "name": "CPF ou CNPJ, conforme o caso", "hint": "Cartao CNPJ: emissao gratuita no site da Receita Federal.", "link": "https://solucoes.receita.fazenda.gov.br/servicos/cnpjreva/cnpjreva_solicitacao.asp", "required": True, "status": "Pendente", "file": "", "internal": False},
        {"id": "inscricao-estadual", "item": "05", "group": "art11", "name": "Inscricao estadual/ICMS ou inscricao de Produtor Rural", "hint": "Consulte de graca no Cadesp/Sefaz-SP e anexe a tela; produtor rural usa a inscricao de produtor.", "link": "https://www.cadesp.fazenda.sp.gov.br/Pages/Cadastro/Consultas/ConsultaPublica/ConsultaPublica.aspx?idServicoCarta=BDAB67E2-FE2D-44D7-8D19-2CDF9015E3A9", "required": True, "status": "Pendente", "file": "", "internal": False},
        {"id": "alvara-prefeitura", "item": "06", "group": "art11", "name": "Alvara de construcao e/ou localizacao e funcionamento", "hint": "Emitido pela Prefeitura de Orlandia (setor de obras/tributos), ou documento equivalente.", "required": True, "status": "Pendente", "file": "", "internal": False},
        {"id": "certidoes-ambientais", "item": "07", "group": "art11", "name": "Licenca ambiental ou dispensa emitida pelo orgao ambiental", "hint": "CETESB: licenca de operacao ou certidao de dispensa, conforme a atividade.", "required": True, "status": "Pendente", "file": "", "internal": False},
        {"id": "exames-agua", "item": "08", "group": "art11", "name": "Exames fisico-quimico e microbiologico da agua de abastecimento", "hint": "Laboratorio credenciado; colete conforme orientacao do laboratorio.", "required": True, "status": "Pendente", "file": "", "internal": False},
        {"id": "memorial-economico-sanitario", "item": "09", "group": "art11", "name": "Memorial descritivo economico e sanitario do estabelecimento", "hint": "Preencha o Anexo II (MTSE) no portal: ele atende este item. Imprima, assine e envie.", "required": True, "status": "Pendente", "file": "", "internal": False, "formView": "establishment", "printForm": "mtse"},
        {"id": "manual-bpf", "item": "10", "group": "art11", "name": "Manual de Boas Praticas de Fabricacao de Alimentos - BPF", "hint": "Elaborado com o responsavel tecnico; descreve higiene, processos e controles do estabelecimento.", "required": True, "status": "Pendente", "file": "", "internal": False},
        {"id": "registro-crmv", "item": "11", "group": "art11", "name": "Registro do estabelecimento no CRMV-SP, se aplicavel", "hint": "Confirme com o responsavel tecnico se a atividade exige registro no conselho.", "required": False, "status": "Pendente", "file": "", "internal": False},
        {"id": "comprovante-taxa", "item": "12", "group": "art11", "name": "Comprovante da Taxa de Inspecao Sanitaria", "hint": "DISPENSADO em 2026: os servicos do art. 175-C sao prestados sem cobranca neste ano (LC 104/2026, art. 3, par. unico).", "required": False, "status": "Dispensado em 2026", "file": "", "internal": False},
        {"id": "mtse", "group": "anexos", "name": "Anexo II - Memorial Tecnico-Sanitario (rascunho de trabalho)", "hint": "Versao de trabalho do MTSE; a versao final assinada vai no item 09.", "required": False, "status": "Em correcao", "file": "MTSE_rascunho.pdf", "internal": False},
        {"id": "rotulos-produtos", "group": "anexos", "name": "Anexo IV - Rotulos e memoriais por produto", "hint": "Envie o rotulo de cada produto direto na tela Produtos (um anexo por produto); aqui e so um resumo.", "required": False, "status": "Pendente", "file": "", "internal": False},
        {"id": "doc-responsavel-legal", "group": "anexos", "name": "Documento do responsavel legal (RG/CPF ou CNH)", "hint": "Copia simples e legivel.", "required": True, "status": "Pendente", "file": "", "internal": False},
        {"id": "art-responsavel-tecnico", "group": "anexos", "name": "ART ou contrato do responsavel tecnico", "hint": "Anotacao de responsabilidade tecnica emitida no conselho do RT.", "required": True, "status": "Pendente", "file": "", "internal": False},
        {"id": "planta-fluxo", "group": "anexos", "name": "Croqui de fluxo (apoio)", "hint": "Opcional; ajuda a analise do fluxo de producao.", "required": False, "status": "Pendente", "file": "", "internal": False},
        {"id": "parecer-tecnico-sim", "name": "Parecer tecnico do SIM", "required": False, "status": "Interno", "file": "", "internal": True},
        {"id": "checklist-inspecao-sim", "name": "Checklist de inspecao do SIM", "required": False, "status": "Interno", "file": "", "internal": True},
        {"id": "despachos-internos-sim", "name": "Despachos internos / instrucoes", "required": False, "status": "Interno", "file": "", "internal": True},
    ],
    "products": [
        {
            "id": "guerra-milk-produto-1",
            "name": "Queijo / derivado lacteo a confirmar",
            "brand": "Guerra Milk",
            "status": "Rascunho",
            "version": 1,
            "previousVersionId": None,
            "supersededBy": None,
            "supersededAt": None,
            "approvedAt": None,
            "approvedBy": None,
            "simNote": "",
            "submittedAt": None,
            "conservation": "Refrigerado",
            "notes": "Denominacao e RTIQ precisam ser confirmados.",
            "requestNature": "Registro de produto e rotulo",
            "packageType": "",
            "labelFeatures": "",
            "composition": "",
            "nutrition": "",
            "manufacturingProcess": "",
            "packagingProcess": "",
            "storageConditions": "",
            "marketTransport": "",
        },
    ],
    "audit": [
        {"at": "2026-07-23T08:58:00-03:00", "who": "SIM Orlandia", "action": "Processo criado a partir do historico SIVISA.", "version": 1},
        {"at": "2026-07-23T09:32:00-03:00", "who": "Lucas Marcelino Campos Ferreira", "action": "Correcoes solicitadas pelo SIM.", "version": 2},
    ],
}

REGISTRY_FIELDS = {
    "establishments": [
        "legal_name", "trade_name", "cnpj_cpf", "sim_number", "registration_date", "address", "district",
        "city", "state", "zip", "phone", "email", "legal_responsible", "technical_responsible",
        "last_project_protocol", "situation", "classification", "species_capacity", "risk_level",
        "inspection_frequency_days", "notes",
    ],
    "fiscal_acts": [
        "establishment_id", "act_type", "act_date", "place", "legal_basis", "facts", "seized_material",
        "attenuating_aggravating", "notification", "witnesses", "other_info", "status", "science_date",
    ],
    "inspections": [
        "establishment_id", "inspection_date", "kind", "inspector", "findings", "decision",
    ],
    "samples": [
        "establishment_id", "collection_date", "product", "analysis_type", "lab", "result", "status", "notes",
    ],
}

REGISTRY_MODELS = {
    "establishments": SimEstablishment,
    "fiscal_acts": SimFiscalAct,
    "inspections": SimInspection,
    "samples": SimSample,
}

REGISTRY_LABELS = {
    "establishments": "Estabelecimento",
    "fiscal_acts": "Ato fiscal",
    "inspections": "Inspecao",
    "samples": "Coleta de amostra",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180_000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    salt_hex, digest_hex = encoded.split(":", 1)
    expected = password_hash(password, bytes.fromhex(salt_hex)).split(":", 1)[1]
    return hmac.compare_digest(expected, digest_hex)


def add_days(date_str: str | None, days: int) -> str:
    try:
        base = datetime.fromisoformat((date_str or "")[:10])
    except ValueError:
        base = datetime.now()
    return (base + timedelta(days=days)).date().isoformat()


_ready = False


def ensure_ready() -> None:
    """Cria as tabelas sim_* que faltarem e aplica as sementes uma unica vez."""
    global _ready
    if _ready:
        return
    engine = db.engine
    db.metadata.create_all(bind=engine, tables=SIM_TABLES, checkfirst=True)
    if not SimUser.query.filter_by(email="lucas.sim@orlandia.sp.gov.br").first():
        db.session.add(SimUser(
            email="lucas.sim@orlandia.sp.gov.br",
            name="Lucas Marcelino Campos Ferreira",
            role="sim",
            password_hash=password_hash(os.environ.get("SIM_SEED_ADMIN_PASSWORD", "sim2026")),
            created_at=now_iso(),
        ))
    if not SimUser.query.filter_by(email="guerra.milk@empresa.local").first():
        db.session.add(SimUser(
            email="guerra.milk@empresa.local",
            name="GUERRA MILK",
            role="establishment",
            password_hash=password_hash(os.environ.get("SIM_SEED_ESTABLISHMENT_PASSWORD", "guerra2026")),
            created_at=now_iso(),
        ))
    if not db.session.get(SimProcessState, PROCESS_ID):
        db.session.add(SimProcessState(
            process_id=PROCESS_ID,
            state_json=json.dumps(SEED_STATE, ensure_ascii=False),
            updated_at=now_iso(),
        ))
        for item in SEED_STATE["audit"]:
            db.session.add(SimAuditEvent(
                process_id=PROCESS_ID,
                actor_name=item["who"],
                action=item["action"],
                version=item["version"],
                created_at=item["at"],
            ))
    if not SimEstablishment.query.first():
        db.session.add(SimEstablishment(
            legal_name="LF-GUERRA MILK ORLANDIA - ME",
            trade_name="GUERRA MILK",
            cnpj_cpf="12.934.929/0001-77",
            sim_number="Pendente",
            address="Avenida F, 464-A",
            district="Jardim Boa Vista",
            zip="14620-000",
            legal_responsible="Jose Francisco Guerra",
            situation="Em registro",
            classification="Unidade de beneficiamento de leite e derivados",
            risk_level="Alto",
            inspection_frequency_days=30,
            notes="Historico SIVISA 2012-2016 (licencas vencidas/canceladas). Processo piloto SIM-ORL-2026-0001.",
            created_at=now_iso(),
            updated_at=now_iso(),
        ))
    db.session.commit()
    _ready = True


def current_user() -> SimUser | None:
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    if not token:
        token = request.args.get("token", "")
    if not token:
        return None
    session = db.session.get(SimSession, token)
    if not session:
        return None
    user = db.session.get(SimUser, session.user_id)
    if not user or not user.active:
        return None
    session.last_seen_at = now_iso()
    db.session.commit()
    return user


def public_user(user: SimUser | None) -> dict | None:
    if not user:
        return None
    return {"email": user.email, "name": user.name, "role": user.role}


def get_state() -> dict:
    row = db.session.get(SimProcessState, PROCESS_ID)
    state = json.loads(row.state_json)
    existing = {doc.get("id") for doc in state.get("documents", [])}
    for doc in SEED_STATE["documents"]:
        if doc["id"] not in existing:
            state.setdefault("documents", []).append(dict(doc))
        else:
            for item in state["documents"]:
                if item.get("id") == doc["id"]:
                    # Metadados legais vem sempre da semente (checklist do art. 11
                    # da LC 84/2024); status/arquivo/versoes ficam como estao.
                    for key in ("name", "hint", "item", "group", "link", "internal", "required", "formView", "printForm"):
                        if key in doc:
                            item[key] = doc[key]
                    # Dispensa legal de 2026 (LC 104/2026) vale mesmo para
                    # processos criados antes da atualizacao do checklist.
                    if doc["id"] == "comprovante-taxa" and item.get("status") == "Pendente":
                        item["status"] = "Dispensado em 2026"
                    break
    order = {doc["id"]: index for index, doc in enumerate(SEED_STATE["documents"])}
    state["documents"].sort(key=lambda doc: order.get(doc.get("id"), 99))
    # Processos criados antes da adicao de "products" ao seed server-side
    # (o campo so existia no estado inicial do navegador) ficam sem produto
    # nenhum ate o estabelecimento salvar algo; evita GET /state com lista vazia.
    if not state.get("products"):
        state["products"] = [dict(product) for product in SEED_STATE["products"]]
    return state


def save_state(state: dict, user_id: int | None) -> None:
    row = db.session.get(SimProcessState, PROCESS_ID)
    row.state_json = json.dumps(state, ensure_ascii=False)
    row.updated_at = now_iso()
    row.updated_by = user_id


def upload_payload(row: SimUpload, name_by_id: dict[int, str]) -> dict:
    return {
        "id": row.id,
        "documentId": row.document_id,
        "versionNo": row.version_no,
        "file": row.original_name,
        "mimeType": row.mime_type,
        "sizeBytes": row.size_bytes,
        "sha256": row.sha256,
        "uploadedBy": name_by_id.get(row.uploaded_by, "?"),
        "uploadedByRole": row.uploaded_by_role,
        "visibility": row.visibility,
        "uploadedAt": row.uploaded_at,
    }


def hydrate_state(role: str) -> dict:
    state = get_state()
    name_by_id = {u.id: u.name for u in SimUser.query.all()}
    uploads_by_doc: dict[str, list[dict]] = {}
    rows = (
        SimUpload.query.filter_by(process_id=PROCESS_ID)
        .order_by(SimUpload.document_id, SimUpload.version_no.desc(), SimUpload.uploaded_at.desc())
        .all()
    )
    for row in rows:
        if role != "sim" and row.visibility == "sim":
            continue
        uploads_by_doc.setdefault(row.document_id, []).append(upload_payload(row, name_by_id))
    visible_docs = []
    for doc in state.get("documents", []):
        if role != "sim" and doc.get("internal"):
            continue
        versions = uploads_by_doc.get(doc.get("id"), [])
        enriched = dict(doc)
        enriched["versions"] = versions
        if versions:
            latest = versions[0]
            enriched.update({
                "file": latest["file"],
                "uploadId": latest["id"],
                "sha256": latest["sha256"],
                "sizeBytes": latest["sizeBytes"],
                "uploadedAt": latest["uploadedAt"],
                "uploadedBy": latest["uploadedBy"],
                "versionNo": latest["versionNo"],
            })
        visible_docs.append(enriched)
    state["documents"] = visible_docs
    for product in state.get("products", []):
        label_versions = uploads_by_doc.get(f"{PRODUCT_LABEL_PREFIX}{product.get('id')}", [])
        product["labelVersions"] = label_versions
        if label_versions:
            latest = label_versions[0]
            product.update({
                "labelFile": latest["file"],
                "labelUploadId": latest["id"],
                "labelSha256": latest["sha256"],
                "labelSizeBytes": latest["sizeBytes"],
                "labelUploadedAt": latest["uploadedAt"],
                "labelUploadedBy": latest["uploadedBy"],
                "labelVersionNo": latest["versionNo"],
            })
    return state


def audit(user: SimUser, action: str, version: int, process_id: str = PROCESS_ID) -> None:
    db.session.add(SimAuditEvent(
        process_id=process_id,
        actor_user_id=user.id,
        actor_name=user.name,
        action=action,
        version=version,
        created_at=now_iso(),
    ))


def notify(to_role: str, title: str, message: str, created_by: int, upload_id: str | None = None, document_id: str | None = None) -> None:
    db.session.add(SimNotification(
        process_id=PROCESS_ID,
        to_role=to_role,
        title=title,
        message=message,
        upload_id=upload_id,
        document_id=document_id,
        created_by=created_by,
        created_at=now_iso(),
    ))


def model_dict(obj) -> dict:
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns if column.name != "content"}


def registry_payload() -> dict:
    est_names = {est.id: (est.trade_name or est.legal_name) for est in SimEstablishment.query.all()}

    def with_name(obj):
        data = model_dict(obj)
        data["establishment_name"] = est_names.get(obj.establishment_id)
        return data

    return {
        "establishments": [model_dict(est) for est in SimEstablishment.query.order_by(SimEstablishment.legal_name).all()],
        "fiscalActs": [with_name(act) for act in SimFiscalAct.query.order_by(SimFiscalAct.id.desc()).all()],
        "inspections": [with_name(item) for item in SimInspection.query.order_by(SimInspection.inspection_date.desc(), SimInspection.id.desc()).all()],
        "samples": [with_name(item) for item in SimSample.query.order_by(SimSample.collection_date.desc(), SimSample.id.desc()).all()],
        "audit": [
            {"actor_name": event.actor_name, "action": event.action, "created_at": event.created_at}
            for event in SimAuditEvent.query.filter_by(process_id=REGISTRY_PROCESS_ID).order_by(SimAuditEvent.id.desc()).limit(60)
        ],
    }


def next_act_number(act_type: str, act_date: str | None) -> str:
    prefix = ACT_PREFIXES.get(act_type, "AT")
    year = (act_date or now_iso())[:4]
    total = SimFiscalAct.query.filter(SimFiscalAct.act_number.like(f"{prefix}-{year}-%")).count()
    return f"{prefix}-{year}-{total + 1:03d}"


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

def get_blueprint():
    bp = Blueprint("sim_portal", __name__, url_prefix="/sim")
    csrf.exempt(bp)

    @bp.before_request
    def _prepare():
        ensure_ready()

    # ---- front estatico -------------------------------------------------
    # no-cache (revalidacao por ETag a cada visita): o portal e atualizado com
    # frequencia e o max-age padrao de 7 dias do app fazia navegadores exibirem
    # versoes antigas por ate uma semana apos cada deploy.
    @bp.route("/")
    def sim_index():
        if not PORTAL_STATIC_DIR.exists():
            abort(404)
        response = send_from_directory(str(PORTAL_STATIC_DIR), "index.html")
        response.headers["Cache-Control"] = "no-cache"
        return response

    @bp.route("/<path:filename>")
    def sim_static(filename: str):
        response = send_from_directory(str(PORTAL_STATIC_DIR), filename)
        response.headers["Cache-Control"] = "no-cache"
        return response

    # ---- autenticacao ---------------------------------------------------
    @bp.route("/api/login", methods=["POST"])
    def sim_login():
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        user = SimUser.query.filter_by(email=email, active=True).first()
        if not user or not verify_password(password, user.password_hash):
            return jsonify({"error": "E-mail ou senha invalidos."}), 401
        token = secrets.token_urlsafe(32)
        db.session.add(SimSession(token=token, user_id=user.id, created_at=now_iso(), last_seen_at=now_iso()))
        db.session.commit()
        return jsonify({"token": token, "user": public_user(user)})

    @bp.route("/api/logout", methods=["POST"])
    def sim_logout():
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
        if token:
            session = db.session.get(SimSession, token)
            if session:
                db.session.delete(session)
                db.session.commit()
        return jsonify({"ok": True})

    @bp.route("/api/session")
    def sim_session():
        return jsonify({"user": public_user(current_user())})

    # ---- processo piloto ------------------------------------------------
    @bp.route("/api/state")
    def sim_state():
        user = current_user()
        if not user:
            return jsonify({"error": "Sessao expirada ou inexistente."}), 401
        state = hydrate_state(user.role)
        state["audit"] = [
            {"at": event.created_at, "who": event.actor_name, "action": event.action, "version": event.version}
            for event in SimAuditEvent.query.filter_by(process_id=PROCESS_ID).order_by(SimAuditEvent.id.desc()).limit(100)
        ]
        state["stateHistory"] = [
            {"id": item.id, "changed_by_name": item.changed_by_name, "changed_at": item.changed_at, "reason": item.reason}
            for item in SimStateRevision.query.filter_by(process_id=PROCESS_ID).order_by(SimStateRevision.id.desc()).limit(30)
        ]
        notifications = [
            {
                "id": item.id, "to_role": item.to_role, "title": item.title, "message": item.message,
                "upload_id": item.upload_id, "document_id": item.document_id,
                "created_at": item.created_at, "read_at": item.read_at,
            }
            for item in SimNotification.query.filter(
                SimNotification.process_id == PROCESS_ID,
                SimNotification.to_role.in_([user.role, "all"]),
            ).order_by(SimNotification.id.desc()).limit(50)
        ]
        state["role"] = user.role
        return jsonify({"state": state, "notifications": notifications, "user": public_user(user)})

    @bp.route("/api/state", methods=["POST"])
    def sim_state_update():
        user = current_user()
        if not user:
            return jsonify({"error": "Sessao expirada ou inexistente."}), 401
        data = request.get_json(silent=True) or {}
        state = data.get("state")
        if not isinstance(state, dict):
            return jsonify({"error": "Estado invalido."}), 400
        state["role"] = user.role
        state.setdefault("protocol", {})["updatedAt"] = now_iso()
        current = get_state()
        if user.role != "sim":
            internal_docs = [doc for doc in current.get("documents", []) if doc.get("internal")]
            external_docs = [doc for doc in state.get("documents", []) if not doc.get("internal")]
            state["documents"] = external_docs + internal_docs
        save_state(state, user.id)
        db.session.add(SimStateRevision(
            process_id=PROCESS_ID,
            state_json=json.dumps(state, ensure_ascii=False),
            changed_by=user.id,
            changed_by_name=user.name,
            changed_at=now_iso(),
            reason="Alteracao de campos do processo",
        ))
        db.session.commit()
        return jsonify({"ok": True, "state": hydrate_state(user.role)})

    # ---- uploads --------------------------------------------------------
    @bp.route("/api/uploads", methods=["POST"])
    def sim_upload():
        user = current_user()
        if not user:
            return jsonify({"error": "Sessao expirada ou inexistente."}), 401
        doc_id = request.form.get("docId", "")
        file = request.files.get("file")
        if not doc_id or file is None or not file.filename:
            return jsonify({"error": "Documento ou arquivo ausente."}), 400
        state = get_state()
        is_label = doc_id.startswith(PRODUCT_LABEL_PREFIX)
        product = None
        doc = None
        if is_label:
            product_id = doc_id[len(PRODUCT_LABEL_PREFIX):]
            product = next((p for p in state.get("products", []) if p.get("id") == product_id), None)
            if not product:
                return jsonify({"error": "Produto nao encontrado."}), 404
            if product.get("status") == "Aprovado" or product.get("supersededBy"):
                return jsonify({"error": "Produto aprovado; abra uma nova versao para trocar o rotulo."}), 403
            if user.role != "establishment":
                return jsonify({"error": "Apenas o estabelecimento envia o rotulo do produto."}), 403
            visibility = "all"
        else:
            doc = next((d for d in state.get("documents", []) if d.get("id") == doc_id), None)
            if not doc:
                return jsonify({"error": "Documento nao encontrado."}), 404
            if doc.get("internal") and user.role != "sim":
                return jsonify({"error": "Documento interno do SIM."}), 403
            visibility = "sim" if doc.get("internal") else "all"
        payload = file.read()
        original = Path(file.filename).name
        digest = hashlib.sha256(payload).hexdigest()
        upload_id = secrets.token_hex(12)
        uploaded_at = now_iso()
        last = (
            SimUpload.query.filter_by(process_id=PROCESS_ID, document_id=doc_id)
            .order_by(SimUpload.version_no.desc()).first()
        )
        version_no = (last.version_no if last else 0) + 1
        db.session.add(SimUpload(
            id=upload_id,
            process_id=PROCESS_ID,
            document_id=doc_id,
            version_no=version_no,
            original_name=original,
            mime_type=mimetypes.guess_type(original)[0] or "application/octet-stream",
            size_bytes=len(payload),
            sha256=digest,
            content=payload,
            uploaded_by=user.id,
            uploaded_by_role=user.role,
            visibility=visibility,
            uploaded_at=uploaded_at,
        ))
        if not is_label:
            for item in state.get("documents", []):
                if item.get("id") == doc_id:
                    item.update({
                        "status": "Recebido",
                        "file": original,
                        "uploadId": upload_id,
                        "sha256": digest,
                        "sizeBytes": len(payload),
                        "uploadedAt": uploaded_at,
                        "uploadedBy": user.name,
                        "versionNo": version_no,
                    })
        version = int(state.get("protocol", {}).get("version", 1))
        state.setdefault("protocol", {})["updatedAt"] = uploaded_at
        save_state(state, user.id)
        if is_label:
            audit(user, f"Rotulo enviado: {product.get('name') or 'produto sem nome'} v{version_no} - {original} (SHA-256 {digest[:12]}...).", version)
            notify(
                "sim",
                f"Novo rotulo: {product.get('name') or 'produto'}",
                f"{user.name} enviou o rotulo {original} com SHA-256 {digest[:16]}...",
                user.id, upload_id, doc_id,
            )
        else:
            audit(user, f"Upload recebido: {doc.get('name', doc_id)} v{version_no} - {original} (SHA-256 {digest[:12]}...).", version)
            notify(
                "sim" if user.role == "establishment" else "all",
                f"Novo anexo: {doc.get('name', doc_id)} v{version_no}",
                f"{user.name} enviou {original} com SHA-256 {digest[:16]}...",
                user.id,
                upload_id,
                doc_id,
            )
        db.session.commit()
        return jsonify({
            "ok": True,
            "state": hydrate_state(user.role),
            "upload": {"id": upload_id, "sha256": digest, "sizeBytes": len(payload), "versionNo": version_no},
        })

    @bp.route("/api/uploads/<upload_id>")
    def sim_download(upload_id: str):
        user = current_user()
        if not user:
            return jsonify({"error": "Sessao expirada ou inexistente."}), 401
        row = db.session.get(SimUpload, upload_id)
        if not row:
            abort(404)
        if user.role != "sim" and row.visibility == "sim":
            return jsonify({"error": "Anexo interno do SIM."}), 403
        # "inline" (padrao) permite pre-visualizar PDF/imagem no iframe do modal
        # sem forcar download; o botao de baixar usa o atributo HTML "download"
        # para salvar o arquivo mesmo com essa disposicao.
        return send_file(
            BytesIO(row.content),
            mimetype=row.mime_type or "application/octet-stream",
            as_attachment=bool(request.args.get("download")),
            download_name=row.original_name,
        )

    # ---- modulos do servico (exclusivos do SIM) -------------------------
    def require_sim() -> SimUser | None:
        user = current_user()
        if not user or user.role != "sim":
            return None
        return user

    @bp.route("/api/registry")
    def sim_registry():
        user = require_sim()
        if not user:
            return jsonify({"error": "Area exclusiva do SIM."}), 403
        return jsonify({"registry": registry_payload()})

    def registry_save(table: str):
        user = require_sim()
        if not user:
            return jsonify({"error": "Area exclusiva do SIM."}), 403
        data = request.get_json(silent=True) or {}
        fields = REGISTRY_FIELDS[table]
        model = REGISTRY_MODELS[table]
        record_id = data.get("id")
        values = {key: data.get(key) for key in fields if key in data}
        if table == "establishments" and not (values.get("legal_name") or record_id):
            return jsonify({"error": "Razao social obrigatoria."}), 400
        if table != "establishments" and not record_id and not values.get("establishment_id"):
            return jsonify({"error": "Selecione o estabelecimento."}), 400
        if table == "fiscal_acts" and values.get("science_date"):
            values["defense_deadline"] = add_days(values["science_date"], DEFENSE_DEADLINE_DAYS)
        if table == "inspections" and values.get("establishment_id") and values.get("inspection_date"):
            est = db.session.get(SimEstablishment, int(values["establishment_id"]))
            frequency = int(est.inspection_frequency_days or 90) if est else 90
            values["next_due"] = add_days(values["inspection_date"], frequency)
        if record_id:
            obj = db.session.get(model, int(record_id))
            if not obj:
                return jsonify({"error": "Registro nao encontrado."}), 404
            for key, value in values.items():
                setattr(obj, key, value)
            obj.updated_at = now_iso()
            label = f"{REGISTRY_LABELS[table]} atualizado(a) (id {record_id})."
        else:
            if table == "fiscal_acts":
                values["act_number"] = next_act_number(values.get("act_type", ""), values.get("act_date"))
            obj = model(**values, created_by=user.id, created_at=now_iso(), updated_at=now_iso())
            db.session.add(obj)
            db.session.flush()
            record_id = obj.id
            label = f"{REGISTRY_LABELS[table]} criado(a) (id {record_id})."
            if table == "fiscal_acts":
                label = f"Ato fiscal lavrado: {values['act_number']} ({values.get('act_type', '')})."
        audit(user, label, 0, process_id=REGISTRY_PROCESS_ID)
        db.session.commit()
        return jsonify({"ok": True, "id": record_id, "registry": registry_payload()})

    @bp.route("/api/establishments", methods=["POST"])
    def sim_establishments():
        return registry_save("establishments")

    @bp.route("/api/fiscal-acts", methods=["POST"])
    def sim_fiscal_acts():
        return registry_save("fiscal_acts")

    @bp.route("/api/inspections", methods=["POST"])
    def sim_inspections():
        return registry_save("inspections")

    @bp.route("/api/samples", methods=["POST"])
    def sim_samples():
        return registry_save("samples")

    return bp
