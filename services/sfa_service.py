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

import json
import logging
import os
import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional
from urllib.parse import quote

from flask import current_app, url_for

log = logging.getLogger("sfa_service")

# ---------------------------------------------------------------------------
# Configuração (lida de variáveis de ambiente ou fallback)
# ---------------------------------------------------------------------------

DIAS_T10 = int(os.getenv("SFA_DIAS_T10", "10"))
DIAS_T30 = int(os.getenv("SFA_DIAS_T30", "30"))
DIAS_LEMBRETE = int(os.getenv("SFA_DIAS_LEMBRETE", "2"))
DIAS_SEM_T0_ALERTA = int(os.getenv("SFA_DIAS_SEM_T0_ALERTA", "5"))
TOLERANCIA_ALERTA_DIAS = int(os.getenv("SFA_TOLERANCIA_ALERTA_DIAS", "1"))
NOME_PESQUISADOR = os.getenv("SFA_NOME_PESQUISADOR", "Lucas")
DDD_PADRAO = os.getenv("SFA_DDD_PADRAO", "16")
PREFIXO_PAIS = os.getenv("SFA_PREFIXO_PAIS", "55")
EMAIL_PESQUISADOR = os.getenv("SFA_EMAIL_PESQUISADOR", "")
GRUPO_PENDENTE = "PENDENTE_REVISAO"

# IDs da planilha SINAN no Google Sheets (usados por sincronizar_sinan)
SHEET_ID_SINAN = os.getenv("SFA_SHEET_ID_SINAN", "")

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


# ---------------------------------------------------------------------------
# Mensagens WhatsApp
# ---------------------------------------------------------------------------

def msg_convite_t0(nome: str, id_estudo: str, token_acesso: str = "") -> str:
    n = primeiro_nome(nome)
    link = gerar_url_t0(id_estudo, token_acesso)
    return (
        f"Olá, {n}! Tudo bem? Aqui é {NOME_PESQUISADOR}, "
        "pesquisador da Secretaria de Saúde de Orlândia. 👋\n\n"
        "Você foi registrado(a) recentemente com suspeita de dengue. "
        "Gostaríamos de convidá-lo(a) a participar de uma pesquisa científica "
        "sobre diagnóstico de arboviroses no município.\n\n"
        "✅ Participação voluntária\n"
        "✅ Apenas 3 entrevistas rápidas (hoje, em 10 e em 30 dias)\n"
        "✅ Contribui para melhorar o diagnóstico de dengue em Orlândia\n\n"
        f"Se topar participar, acesse o link abaixo — seus dados já estão preenchidos:\n{link}"
        "\n\nQualquer dúvida, é só chamar! 😊"
    )


def msg_lembrete_t10(nome: str, id_estudo: str) -> str:
    n = primeiro_nome(nome)
    link = os.getenv("SFA_LINK_FORM_T10", "#")
    return (
        f"Olá, {n}! Aqui é {NOME_PESQUISADOR} da pesquisa de arboviroses de Orlândia. 🔬\n\n"
        "Já se passaram cerca de 10 dias — está na hora do acompanhamento T10!\n\n"
        f"Código do participante: {id_estudo}\n"
        f"Acesse e responda:\n{link}"
        "\n\nObrigado pela sua participação! 🙏"
    )


def msg_lembrete_t30(nome: str, id_estudo: str) -> str:
    n = primeiro_nome(nome)
    link = os.getenv("SFA_LINK_FORM_T30", "#")
    return (
        f"Olá, {n}! Aqui é {NOME_PESQUISADOR} da pesquisa de arboviroses de Orlândia. 🔬\n\n"
        "Chegamos ao final do seu acompanhamento (30 dias).\n"
        f"Código do participante: {id_estudo}\n"
        f"Seus dados já estão preenchidos — acesse e responda:\n{link}"
        "\n\nSua participação foi fundamental para nossa pesquisa. Muito obrigado! 🙏"
    )


def msg_revisao_pendente(nome: str, id_estudo: str) -> str:
    n = primeiro_nome(nome)
    return (
        f"Olá, {n}! Aqui é {NOME_PESQUISADOR} da pesquisa de arboviroses de Orlândia.\n\n"
        "Precisamos confirmar alguns dados do seu cadastro para concluir sua inclusão no estudo.\n"
        f"Código do participante: {id_estudo or '(sem código)'}\n\n"
        "Se puder, me responda por aqui para alinharmos rapidinho. Obrigado!"
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

    creds_json = os.getenv("SFA_GOOGLE_CREDENTIALS_JSON", "")
    if not creds_json:
        creds_file = os.getenv("SFA_GOOGLE_CREDENTIALS_FILE", "")
        if creds_file:
            with open(creds_file) as f:
                creds_json = f.read()

    if not creds_json:
        raise RuntimeError(
            "Credenciais Google não configuradas. "
            "Defina SFA_GOOGLE_CREDENTIALS_JSON ou SFA_GOOGLE_CREDENTIALS_FILE."
        )

    info = json.loads(creds_json)
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
    if not SHEET_ID_SINAN:
        log.warning("SFA_SHEET_ID_SINAN não configurado — sincronização SINAN ignorada.")
        return {"novos": 0, "erros": 0}

    from extensions import db
    from models.sfa import SfaPaciente, SfaSinanLog

    try:
        service = _get_sheets_service()
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SHEET_ID_SINAN, range="A:T")
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

        tel_bruto = str(row[COLS_SINAN["TELEFONE"]] or "")
        telefone = normalizar_telefone(tel_bruto) or tel_bruto
        bairro = str(row[COLS_SINAN["BAIRRO"]] or "").strip()
        endereco = str(row[COLS_SINAN["ENDERECO"]] or "").strip()
        ficha_sinan = str(row[COLS_SINAN["FICHA_SINAN"]] or "").strip()
        n_caso = str(row[COLS_SINAN["N"]] or "").strip()
        resultado = str(row[COLS_SINAN["RESULTADO"]] or "").lower()
        tipo_exame = str(row[COLS_SINAN["TIPO_EXAME"]] or "")
        data_not = str(row[COLS_SINAN["DATA_NOTIFICACAO"]] or "")
        data_ini = str(row[COLS_SINAN["DATA_INICIO_SINTOMAS"]] or "")
        data_nasc_raw = row[COLS_SINAN["DATA_NASCIMENTO"]]

        # Parseia data de nascimento
        data_nasc = ""
        if data_nasc_raw:
            d = parse_data(data_nasc_raw)
            data_nasc = formatar_data(d) if d else str(data_nasc_raw)

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

    log.info("SINAN sync: %d novos, %d erros", novos, erros)
    return {"novos": novos, "erros": erros}


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

    id_estudo = str(dados.get("id_estudo") or "").strip()
    nome = str(dados.get("nome") or "").strip()
    data_nasc = str(dados.get("data_nascimento") or "").strip()

    if not id_estudo and not (nome and data_nasc):
        registrar_auditoria("WARN", "T0_SEM_IDENTIFICACAO", "on_submit_t0",
                             "T0 recebido sem id_estudo e sem nome/data de nascimento.")
        return {"ok": False, "erro": "Identificação insuficiente"}

    hoje = date.today()
    dt_t10 = hoje + timedelta(days=DIAS_T10)
    dt_t30 = hoje + timedelta(days=DIAS_T30)

    paciente = None

    # 1ª tentativa: id_estudo
    if id_estudo:
        paciente = SfaPaciente.query.filter_by(id_estudo=id_estudo).first()

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

    novos = SfaPaciente.query.filter_by(status_geral="SINAN_Notificado").all()

    def vencendo_em(paciente, campo_data: str, status: str) -> bool:
        if getattr(paciente, f"status_{campo_data}") != "Aguardando":
            return False
        dt = parse_data(getattr(paciente, f"data_{campo_data}"))
        if not dt:
            return False
        return 0 <= (dt - hoje).days <= DIAS_LEMBRETE

    pend_t10 = [p for p in SfaPaciente.query.all() if vencendo_em(p, "t10", "Aguardando")]
    pend_t30 = [p for p in SfaPaciente.query.all() if vencendo_em(p, "t30", "Aguardando")]

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

    todos = SfaPaciente.query.all()
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

    alertas_recentes = (
        SfaAuditoria.query
        .order_by(SfaAuditoria.timestamp.desc())
        .limit(10)
        .all()
    )

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
    Executa sincronizar_sinan + verificar_seguimento dentro do app context.
    Chamado pelo APScheduler.
    """
    with app.app_context():
        resultado_sinan = sincronizar_sinan()
        resultado_seg = verificar_seguimento()
        log.info("Rotina diária SFA concluída: %s", {**resultado_sinan, **resultado_seg})
        return {**resultado_sinan, **resultado_seg}
