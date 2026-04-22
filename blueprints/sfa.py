"""
blueprints/sfa.py
=================
Blueprint Flask para o módulo SFA — Síndromes Febris Agudas de Orlândia.

Rotas:
  GET  /sfa/                    → Dashboard operacional
  GET  /sfa/pacientes           → Lista de pacientes com filtros
  GET  /sfa/paciente/<id>       → Detalhe do paciente
  POST /sfa/paciente/<id>/whatsapp → Marca status WhatsApp
  GET  /sfa/p/<token>           → Redirect para formulário T0 (substitui doGet do GAS)
  POST /sfa/webhook/t0          → Recebe submissão T0 do Google Forms
  POST /sfa/webhook/t10         → Recebe submissão T10
  POST /sfa/webhook/t30         → Recebe submissão T30
  POST /sfa/sync                → Dispara sincronização SINAN manualmente
  POST /sfa/rotina              → Roda todas as rotinas (verificar_seguimento etc.)
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import hmac
import hashlib
import json
import os
from functools import wraps

from extensions import csrf
from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    current_app,
)
from flask_login import current_user

bp = Blueprint("sfa_routes", __name__, url_prefix="/sfa",
               template_folder="../templates/sfa")


def get_blueprint():
    return bp


# ---------------------------------------------------------------------------
# Helpers de segurança
# ---------------------------------------------------------------------------

def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _usuario_admin_autenticado() -> bool:
    return bool(
        current_user.is_authenticated
        and (getattr(current_user, "role", "") or "").lower() == "admin"
    )


def _token_admin_informado() -> str:
    return (request.headers.get("X-SFA-Token") or request.args.get("token", "")).strip()


def _acesso_interno_sfa_liberado() -> bool:
    """
    Libera acesso às rotas internas do SFA para:
      - usuário admin autenticado; ou
      - token administrativo válido.

    Em produção, o módulo fica fechado por padrão. Para desenvolvimento local,
    o comportamento antigo pode ser reabilitado com SFA_ALLOW_OPEN_ACCESS=1.
    """
    if current_app.testing:
        return True
    if _usuario_admin_autenticado():
        return True
    token_esperado = os.getenv("SFA_ADMIN_TOKEN", "").strip()
    token_recebido = _token_admin_informado()
    if token_esperado and token_recebido:
        return hmac.compare_digest(token_recebido, token_esperado)
    return _env_flag("SFA_ALLOW_OPEN_ACCESS", default=False)


def _bloquear_acesso_interno():
    if current_user.is_authenticated:
        abort(403)
    login_endpoint = "login_view"
    if login_endpoint in current_app.view_functions:
        return redirect(url_for(login_endpoint, next=request.url))
    abort(401)


def require_sfa_internal_access(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if _acesso_interno_sfa_liberado():
            return view(*args, **kwargs)
        return _bloquear_acesso_interno()

    return wrapper


# ---------------------------------------------------------------------------
# Autenticação simples por token de admin
# ---------------------------------------------------------------------------

def _verificar_token_admin() -> bool:
    """Verifica se a requisição tem o token de admin do SFA."""
    return _acesso_interno_sfa_liberado()


def _verificar_webhook_secret() -> bool:
    """Verifica o segredo compartilhado nos webhooks do Google Apps Script."""
    if current_app.testing:
        return True
    secret_esperado = os.getenv("SFA_WEBHOOK_SECRET", "").strip()
    if not secret_esperado:
        current_app.logger.warning(
            "SFA webhook rejeitado porque SFA_WEBHOOK_SECRET não está configurado."
        )
        return False
    secret = request.headers.get("X-SFA-Secret") or request.args.get("secret", "")
    return hmac.compare_digest(secret, secret_esperado)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@bp.route("/")
@require_sfa_internal_access
def dashboard():
    from services.sfa_service import (
        stats_painel, link_whatsapp, normalizar_telefone, diagnostico_configuracao, resumo_dados_teste_sfa
    )
    from services.sfa_service import (
        msg_convite_t0, msg_lembrete_t10, msg_lembrete_t30, ACOES_QUE_GERAM_CONTATO
    )

    stats = stats_painel()
    diagnostico = diagnostico_configuracao()
    resumo_testes = resumo_dados_teste_sfa()

    # Enriquece a fila com links WhatsApp prontos
    for p in stats["fila"]:
        tel = normalizar_telefone(p.telefone or "")
        acao = p.proxima_acao or ""
        p._link_whatsapp = ""
        if tel and acao in ACOES_QUE_GERAM_CONTATO:
            try:
                if acao == "Convidar T0":
                    msg = msg_convite_t0(p.nome, p.id_estudo, p.token_acesso or "")
                elif "T10" in acao:
                    msg = msg_lembrete_t10(p.nome, p.id_estudo, p.token_acesso or "")
                elif "T30" in acao:
                    msg = msg_lembrete_t30(p.nome, p.id_estudo, p.token_acesso or "")
                else:
                    msg = ""
                if msg:
                    p._link_whatsapp = link_whatsapp(tel, msg)
            except Exception:
                pass

    return render_template("sfa/dashboard.html", stats=stats, diagnostico=diagnostico, resumo_testes=resumo_testes)


# ---------------------------------------------------------------------------
# Lista de pacientes
# ---------------------------------------------------------------------------

def _coletar_filtros_pacientes() -> dict[str, str]:
    return {
        "visao": request.args.get("visao", "reais").strip() or "reais",
        "grupo": request.args.get("grupo", ""),
        "status": request.args.get("status", ""),
        "q": request.args.get("q", "").strip(),
        "mes_inicio_sintomas": request.args.get("mes_inicio_sintomas", "").strip(),
        "data_inicio_sintomas": request.args.get("data_inicio_sintomas", "").strip(),
        "data_inicio_sintomas_de": request.args.get("data_inicio_sintomas_de", "").strip(),
        "data_inicio_sintomas_ate": request.args.get("data_inicio_sintomas_ate", "").strip(),
        "data_notificacao_de": request.args.get("data_notificacao_de", "").strip(),
        "data_notificacao_ate": request.args.get("data_notificacao_ate", "").strip(),
        "respondido_t0_de": request.args.get("respondido_t0_de", "").strip(),
        "respondido_t0_ate": request.args.get("respondido_t0_ate", "").strip(),
        "respondido_t10_de": request.args.get("respondido_t10_de", "").strip(),
        "respondido_t10_ate": request.args.get("respondido_t10_ate", "").strip(),
        "respondido_t30_de": request.args.get("respondido_t30_de", "").strip(),
        "respondido_t30_ate": request.args.get("respondido_t30_ate", "").strip(),
        "proxima_acao_ate": request.args.get("proxima_acao_ate", "").strip(),
        "situacao_data": request.args.get("situacao_data", "").strip(),
    }


def _parse_month_filter(value: str) -> tuple[int, int] | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m")
    except ValueError:
        return None
    return parsed.year, parsed.month


def _date_field_to_iso_expr(field):
    from sqlalchemy import func

    return (
        func.substr(field, 7, 4)
        + "-"
        + func.substr(field, 4, 2)
        + "-"
        + func.substr(field, 1, 2)
    )


def _parse_date_filter(value: str):
    from services.sfa_service import parse_data

    return parse_data(value)


def _apply_string_date_range(query, field, start_value: str, end_value: str):
    parsed_start = _parse_date_filter(start_value)
    parsed_end = _parse_date_filter(end_value)
    iso_expr = _date_field_to_iso_expr(field)

    if parsed_start:
        query = query.filter(iso_expr >= parsed_start.isoformat())
    if parsed_end:
        query = query.filter(iso_expr <= parsed_end.isoformat())
    return query


def _apply_timestamp_range(query, field, start_value: str, end_value: str):
    parsed_start = _parse_date_filter(start_value)
    parsed_end = _parse_date_filter(end_value)

    if parsed_start:
        query = query.filter(field >= datetime.combine(parsed_start, time.min))
    if parsed_end:
        query = query.filter(field < datetime.combine(parsed_end + timedelta(days=1), time.min))
    return query


def _string_date_conditions(field, start_value: str, end_value: str):
    parsed_start = _parse_date_filter(start_value)
    parsed_end = _parse_date_filter(end_value)
    iso_expr = _date_field_to_iso_expr(field)
    conditions = []

    if parsed_start:
        conditions.append(iso_expr >= parsed_start.isoformat())
    if parsed_end:
        conditions.append(iso_expr <= parsed_end.isoformat())
    return conditions


def _timestamp_conditions(field, start_value: str, end_value: str):
    parsed_start = _parse_date_filter(start_value)
    parsed_end = _parse_date_filter(end_value)
    conditions = []

    if parsed_start:
        conditions.append(field >= datetime.combine(parsed_start, time.min))
    if parsed_end:
        conditions.append(field < datetime.combine(parsed_end + timedelta(days=1), time.min))
    return conditions


def _consulta_pacientes_filtrada(filtros: dict[str, str] | None = None):
    from models.sfa import SfaPaciente, SfaRespostaT0, SfaRespostaT10, SfaRespostaT30, SfaSinanLog
    from services.sfa_service import SFA_TEST_MARKER, SFA_TEST_NAME_PREFIX, formatar_data, parse_data
    from extensions import db
    from sqlalchemy import exists, func
    from sqlalchemy.orm import joinedload

    filtros = filtros or _coletar_filtros_pacientes()
    visao = filtros.get("visao", "reais").strip().lower() or "reais"
    grupo = filtros.get("grupo", "")
    status = filtros.get("status", "")
    busca = filtros.get("q", "").strip()
    mes_inicio_sintomas = filtros.get("mes_inicio_sintomas", "").strip()
    data_inicio_sintomas = filtros.get("data_inicio_sintomas", "").strip()
    data_inicio_sintomas_de = filtros.get("data_inicio_sintomas_de", "").strip()
    data_inicio_sintomas_ate = filtros.get("data_inicio_sintomas_ate", "").strip()
    data_notificacao_de = filtros.get("data_notificacao_de", "").strip()
    data_notificacao_ate = filtros.get("data_notificacao_ate", "").strip()
    respondido_t0_de = filtros.get("respondido_t0_de", "").strip()
    respondido_t0_ate = filtros.get("respondido_t0_ate", "").strip()
    respondido_t10_de = filtros.get("respondido_t10_de", "").strip()
    respondido_t10_ate = filtros.get("respondido_t10_ate", "").strip()
    respondido_t30_de = filtros.get("respondido_t30_de", "").strip()
    respondido_t30_ate = filtros.get("respondido_t30_ate", "").strip()
    proxima_acao_ate = filtros.get("proxima_acao_ate", "").strip()
    situacao_data = filtros.get("situacao_data", "").strip()

    q = SfaPaciente.query.options(joinedload(SfaPaciente.resposta_t0))

    teste_expr = (
        SfaPaciente.observacao_operacional.ilike(f"%{SFA_TEST_MARKER}%")
        | SfaPaciente.nome.ilike(f"{SFA_TEST_NAME_PREFIX}%")
    )
    if visao == "testes":
        q = q.filter(teste_expr)
    elif visao != "todos":
        q = q.filter((SfaPaciente.observacao_operacional.is_(None)) | (~teste_expr))

    if grupo:
        q = q.filter(SfaPaciente.grupo == grupo)
    if status:
        q = q.filter(SfaPaciente.status_geral == status)
    if busca:
        like = f"%{busca}%"
        q = q.filter(
            SfaPaciente.nome.ilike(like)
            | SfaPaciente.id_estudo.ilike(like)
            | SfaPaciente.bairro.ilike(like)
            | SfaPaciente.ficha_sinan.ilike(like)
        )
    filtros_t0 = []
    if mes_inicio_sintomas:
        parsed_month = _parse_month_filter(mes_inicio_sintomas)
        if parsed_month:
            year, month = parsed_month
            filtros_t0.append(SfaRespostaT0.data_inicio_sintomas.like(f"__/{month:02d}/{year:04d}"))
    if data_inicio_sintomas:
        parsed_date = parse_data(data_inicio_sintomas)
        if parsed_date:
            filtros_t0.append(SfaRespostaT0.data_inicio_sintomas == formatar_data(parsed_date))
    if data_inicio_sintomas_de or data_inicio_sintomas_ate:
        filtros_t0.extend(_string_date_conditions(SfaRespostaT0.data_inicio_sintomas, data_inicio_sintomas_de, data_inicio_sintomas_ate))
    if respondido_t0_de or respondido_t0_ate:
        filtros_t0.extend(_timestamp_conditions(SfaRespostaT0.timestamp, respondido_t0_de, respondido_t0_ate))
    if filtros_t0:
        q = q.filter(
            exists()
            .where(SfaRespostaT0.id_estudo == SfaPaciente.id_estudo)
            .where(*filtros_t0)
        )

    if data_notificacao_de or data_notificacao_ate:
        filtros_sinan = _string_date_conditions(SfaSinanLog.data_notificacao, data_notificacao_de, data_notificacao_ate)
        if filtros_sinan:
            q = q.filter(
                exists()
                .where(SfaSinanLog.id_estudo_vinculado == SfaPaciente.id_estudo)
                .where(*filtros_sinan)
            )

    if respondido_t10_de or respondido_t10_ate:
        filtros_t10 = _timestamp_conditions(SfaRespostaT10.timestamp, respondido_t10_de, respondido_t10_ate)
        if filtros_t10:
            q = q.filter(
                exists()
                .where(SfaRespostaT10.id_estudo == SfaPaciente.id_estudo)
                .where(*filtros_t10)
            )

    if respondido_t30_de or respondido_t30_ate:
        filtros_t30 = _timestamp_conditions(SfaRespostaT30.timestamp, respondido_t30_de, respondido_t30_ate)
        if filtros_t30:
            q = q.filter(
                exists()
                .where(SfaRespostaT30.id_estudo == SfaPaciente.id_estudo)
                .where(*filtros_t30)
            )
    if proxima_acao_ate:
        q = _apply_string_date_range(q, SfaPaciente.data_proxima_acao, "", proxima_acao_ate)
        q = q.filter((SfaPaciente.proxima_acao.isnot(None)) & (SfaPaciente.proxima_acao != "") & (SfaPaciente.proxima_acao != "Sem acao"))
    if situacao_data:
        hoje = date.today()
        if situacao_data == "atrasados":
            q = _apply_string_date_range(q, SfaPaciente.data_proxima_acao, "", hoje.isoformat())
            q = q.filter((SfaPaciente.proxima_acao.isnot(None)) & (SfaPaciente.proxima_acao != "") & (SfaPaciente.proxima_acao != "Sem acao"))
        elif situacao_data == "vence_7_dias":
            q = _apply_string_date_range(
                q,
                SfaPaciente.data_proxima_acao,
                hoje.isoformat(),
                (hoje + timedelta(days=7)).isoformat(),
            )
            q = q.filter((SfaPaciente.proxima_acao.isnot(None)) & (SfaPaciente.proxima_acao != "") & (SfaPaciente.proxima_acao != "Sem acao"))

    data_notificacao_order_sq = (
        db.session.query(
            SfaSinanLog.id_estudo_vinculado.label("id_estudo"),
            func.max(_date_field_to_iso_expr(SfaSinanLog.data_notificacao)).label("data_notificacao_iso"),
        )
        .group_by(SfaSinanLog.id_estudo_vinculado)
        .subquery()
    )
    q = q.outerjoin(
        data_notificacao_order_sq,
        data_notificacao_order_sq.c.id_estudo == SfaPaciente.id_estudo,
    )

    return q.order_by(
        data_notificacao_order_sq.c.data_notificacao_iso.desc().nullslast(),
        SfaPaciente.timestamp_cadastro.desc(),
    )


def _anexar_datas_notificacao_sinan(pacientes) -> None:
    from models.sfa import SfaSinanLog

    ids_estudo = [getattr(paciente, "id_estudo", "") for paciente in pacientes if getattr(paciente, "id_estudo", "")]
    if not ids_estudo:
        return

    logs = (
        SfaSinanLog.query
        .filter(SfaSinanLog.id_estudo_vinculado.in_(ids_estudo))
        .order_by(SfaSinanLog.id.desc())
        .all()
    )

    datas_por_estudo = {}
    for log in logs:
        id_estudo = getattr(log, "id_estudo_vinculado", "")
        if id_estudo and id_estudo not in datas_por_estudo:
            datas_por_estudo[id_estudo] = getattr(log, "data_notificacao", "") or ""

    for paciente in pacientes:
        paciente._data_notificacao_sinan = datas_por_estudo.get(getattr(paciente, "id_estudo", ""), "")


def _resposta_recente(respostas):
    itens = list(respostas or [])
    if not itens:
        return None
    return sorted(itens, key=lambda item: getattr(item, "timestamp", None) or datetime.min)[-1]


def _dashboard_distribution(title: str, data: dict[str, int]) -> dict[str, object]:
    total = sum(data.values())
    items = []
    for label, count in sorted(data.items(), key=lambda item: (-item[1], item[0])):
        pct = round((count / total) * 100, 1) if total else 0
        items.append({"label": label, "count": count, "pct": pct})
    return {"title": title, "total": total, "items": items}


def _dashboard_grouped_distribution(
    title: str,
    data: dict[str, dict[str, int]],
    denominators: dict[str, int] | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    denominators = denominators or {}
    total_denominator = denominators.get("total") or sum(data.get("total", {}).values())
    a_denominator = denominators.get("A") or sum(data.get("A", {}).values())
    b_denominator = denominators.get("B") or sum(data.get("B", {}).values())
    labels = set(data.get("total", {})) | set(data.get("A", {})) | set(data.get("B", {}))
    items = []

    for label in labels:
        total_count = data.get("total", {}).get(label, 0)
        a_count = data.get("A", {}).get(label, 0)
        b_count = data.get("B", {}).get(label, 0)
        a_pct = _safe_ratio(a_count, a_denominator)
        b_pct = _safe_ratio(b_count, b_denominator)
        gap = round(abs(a_pct - b_pct), 1)
        if a_pct > b_pct:
            leader = "A"
        elif b_pct > a_pct:
            leader = "B"
        else:
            leader = "Empate"
        items.append(
            {
                "label": label,
                "count": total_count,
                "pct": _safe_ratio(total_count, total_denominator),
                "a_count": a_count,
                "a_pct": a_pct,
                "b_count": b_count,
                "b_pct": b_pct,
                "leader": leader,
                "gap": gap,
            }
        )

    items.sort(key=lambda item: (-item["count"], -item["gap"], item["label"]))
    if limit:
        items = items[:limit]
    return {
        "title": title,
        "total": total_denominator,
        "a_total": a_denominator,
        "b_total": b_denominator,
        "items": items,
    }


def _faixa_etaria_sfa(data_nascimento: str, referencia: date) -> str:
    from services.sfa_service import calcular_idade, parse_data

    nascimento = parse_data(data_nascimento)
    idade = calcular_idade(nascimento, referencia) if nascimento else None
    if idade is None:
        return "Nao informado"
    if idade < 18:
        return "<18"
    if idade < 30:
        return "18-29"
    if idade < 45:
        return "30-44"
    if idade < 60:
        return "45-59"
    return "60+"


def _safe_ratio(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _recuperacao_alta_sfa(estado) -> bool:
    estado_texto = str(estado or "")
    return estado_texto.startswith(
        (
            "Totalmente recuperado",
            "Quase recuperado",
            "100% recuperado",
            "90-99% recuperado",
        )
    )


def _retorno_atividades_rapido_sfa(retorno) -> bool:
    retorno_texto = str(retorno or "")
    return retorno_texto.startswith(
        (
            "No mesmo dia",
            "Em 2 a 3 dias",
            "Em 4 a 7 dias",
        )
    )


def _retorno_atividades_lento_sfa(retorno) -> bool:
    retorno_texto = str(retorno or "")
    return retorno_texto.startswith(
        (
            "Em 15 a 30 dias",
            "Depois de 30 dias",
            "Voltei parcialmente",
            "Ainda nao voltei",
        )
    )


def _retorno_atividades_temporal_sfa(retorno) -> str:
    retorno_texto = str(retorno or "")
    opcoes_temporais = {
        "No mesmo dia ou em 1 dia",
        "Em 2 a 3 dias",
        "Em 4 a 7 dias",
        "Em 8 a 14 dias",
        "Em 15 a 30 dias",
        "Depois de 30 dias",
        "Voltei parcialmente, mas ainda nao totalmente",
        "Ainda nao voltei",
    }
    return retorno_texto if retorno_texto in opcoes_temporais else ""


def _montar_dashboard_testes_sfa(pacientes) -> dict[str, object]:
    from services.sfa_service import parse_data

    pacientes = list(pacientes or [])
    total = len(pacientes)
    if not total:
        return {
            "cards": [],
            "distributions": [],
            "cost_breakdown": [],
            "timeline_cards": [],
            "research_cards": [],
            "group_comparison": [],
            "symptom_prevalence": [],
            "demographic_distributions": [],
            "research_alerts": [],
            "symptom_group_matrix": [],
            "recovery_segments": [],
            "return_cost_segments": [],
            "hypothesis_cards": [],
            "cluster_summary": [],
            "top_differentiators": [],
        }

    def _avg(values):
        nums = [float(value) for value in values if value is not None]
        return round(sum(nums) / len(nums), 1) if nums else 0.0

    def _days_between(start_value, end_value):
        start = parse_data(start_value)
        end = parse_data(end_value)
        if not start or not end:
            return None
        return max((end - start).days, 0)

    def _new_grouped_counts():
        return {"total": {}, "A": {}, "B": {}}

    def _increment_grouped(store, label, grupo):
        label = label or "Nao informado"
        store["total"][label] = store["total"].get(label, 0) + 1
        if grupo in ("A", "B"):
            store[grupo][label] = store[grupo].get(label, 0) + 1

    grupo_a = sum(1 for paciente in pacientes if getattr(paciente, "grupo", "") == "A")
    grupo_b = sum(1 for paciente in pacientes if getattr(paciente, "grupo", "") == "B")
    t0s = [getattr(paciente, "resposta_t0", None) for paciente in pacientes if getattr(paciente, "resposta_t0", None)]
    t10s = [_resposta_recente(getattr(paciente, "respostas_t10", [])) for paciente in pacientes]
    t10s = [resposta for resposta in t10s if resposta]
    t30s = [_resposta_recente(getattr(paciente, "respostas_t30", [])) for paciente in pacientes]
    t30s = [resposta for resposta in t30s if resposta]

    total_custos_t30 = [
        float(
            (getattr(resposta, "custo_remedios", 0) or 0)
            + (getattr(resposta, "custo_consultas", 0) or 0)
            + (getattr(resposta, "custo_transporte", 0) or 0)
            + (getattr(resposta, "custo_outros", 0) or 0)
        )
        for resposta in t30s
    ]
    recuperacao_alta = 0
    for resposta in t30s:
        payload = json.loads(getattr(resposta, "dados_json", "{}") or "{}")
        estado = str(payload.get("estado_saude_final") or "")
        if _recuperacao_alta_sfa(estado):
            recuperacao_alta += 1

    cards = [
        {"label": "Pacientes avaliados", "value": total, "tone": "var(--sfa-teal)"},
        {"label": "Grupo A", "value": f"{grupo_a} ({round((grupo_a / total) * 100) if total else 0}%)", "tone": "#dc3545"},
        {"label": "Grupo B", "value": f"{grupo_b} ({round((grupo_b / total) * 100) if total else 0}%)", "tone": "#6c757d"},
        {"label": "Dias incapacitantes T0", "value": _avg([getattr(resposta, "dias_incap", None) for resposta in t0s]), "tone": "#fd7e14"},
        {"label": "Dias incapacitantes T30", "value": _avg([getattr(resposta, "dias_incap_novos", None) for resposta in t30s]), "tone": "#198754"},
        {"label": "Custo médio final", "value": f"R$ {_avg(total_custos_t30):.1f}", "tone": "#0d6efd"},
        {"label": "Recuperação alta no T30", "value": f"{recuperacao_alta}/{len(t30s) or total}", "tone": "#20c997"},
    ]

    melhorias = {}
    retornos = {}
    estados_finais = {}
    residencias = {}
    bairros = {}
    sexo_dist = {}
    ocupacao_dist = {}
    faixa_etaria_dist = {}
    sintomas_dist = {}
    symptom_group_matrix = {}
    melhorias_grouped = _new_grouped_counts()
    estados_finais_grouped = _new_grouped_counts()
    retornos_grouped = _new_grouped_counts()
    residencias_grouped = _new_grouped_counts()
    bairros_grouped = _new_grouped_counts()
    sexo_grouped = _new_grouped_counts()
    ocupacao_grouped = _new_grouped_counts()
    faixa_etaria_grouped = _new_grouped_counts()
    sintomas_grouped = _new_grouped_counts()
    return_cost_buckets = {
        "No mesmo dia ou em 1 dia": [],
        "Em 2 a 3 dias": [],
        "Em 4 a 7 dias": [],
        "Em 8 a 14 dias": [],
        "Em 15 a 30 dias": [],
        "Depois de 30 dias": [],
        "Voltei parcialmente, mas ainda nao totalmente": [],
        "Ainda nao voltei": [],
    }
    recovery_segments = {
        "Masculino": {"total": 0, "alta": 0},
        "Feminino": {"total": 0, "alta": 0},
        "<18": {"total": 0, "alta": 0},
        "18-29": {"total": 0, "alta": 0},
        "30-44": {"total": 0, "alta": 0},
        "45-59": {"total": 0, "alta": 0},
        "60+": {"total": 0, "alta": 0},
    }
    grupo_metrics = {
        "A": {"pacientes": 0, "custos": [], "dias_t30": [], "recuperacao_alta": 0},
        "B": {"pacientes": 0, "custos": [], "dias_t30": [], "recuperacao_alta": 0},
    }
    for paciente in pacientes:
        grupo = getattr(paciente, "grupo", "") or "Nao informado"
        if grupo in grupo_metrics:
            grupo_metrics[grupo]["pacientes"] += 1
        bairro = paciente.bairro or "Nao informado"
        bairros[bairro] = bairros.get(bairro, 0) + 1
        _increment_grouped(bairros_grouped, bairro, grupo)
        faixa = _faixa_etaria_sfa(getattr(paciente, "data_nascimento", ""), date.today())
        faixa_etaria_dist[faixa] = faixa_etaria_dist.get(faixa, 0) + 1
        _increment_grouped(faixa_etaria_grouped, faixa, grupo)
        if paciente.resposta_t0:
            payload_t0 = json.loads(getattr(paciente.resposta_t0, "dados_json", "{}") or "{}")
            residencia = payload_t0.get("tipo_residencia") or getattr(paciente.resposta_t0, "tipo_residencia", "") or "Nao informado"
            residencias[residencia] = residencias.get(residencia, 0) + 1
            _increment_grouped(residencias_grouped, residencia, grupo)
            sexo = payload_t0.get("sexo_biologico") or "Nao informado"
            ocupacao = payload_t0.get("ocupacao_principal") or "Nao informado"
            sexo_dist[sexo] = sexo_dist.get(sexo, 0) + 1
            ocupacao_dist[ocupacao] = ocupacao_dist.get(ocupacao, 0) + 1
            _increment_grouped(sexo_grouped, sexo, grupo)
            _increment_grouped(ocupacao_grouped, ocupacao, grupo)
            for sintoma in payload_t0.get("sintomas_principais") or []:
                sintomas_dist[sintoma] = sintomas_dist.get(sintoma, 0) + 1
                _increment_grouped(sintomas_grouped, sintoma, grupo)
                symptom_group_matrix.setdefault(sintoma, {"A": 0, "B": 0, "total": 0})
                if grupo in ("A", "B"):
                    symptom_group_matrix[sintoma][grupo] += 1
                symptom_group_matrix[sintoma]["total"] += 1
        resposta_t10 = _resposta_recente(getattr(paciente, "respostas_t10", []))
        if resposta_t10:
            payload_t10 = json.loads(getattr(resposta_t10, "dados_json", "{}") or "{}")
            melhora = payload_t10.get("classificacao_melhora") or "Nao informado"
            melhorias[melhora] = melhorias.get(melhora, 0) + 1
            _increment_grouped(melhorias_grouped, melhora, grupo)
        resposta_t30 = _resposta_recente(getattr(paciente, "respostas_t30", []))
        if resposta_t30:
            payload_t30 = json.loads(getattr(resposta_t30, "dados_json", "{}") or "{}")
            estado = payload_t30.get("estado_saude_final") or "Nao informado"
            retorno = payload_t30.get("retorno_atividades_normais") or "Nao informado"
            retorno_temporal = _retorno_atividades_temporal_sfa(retorno)
            estados_finais[estado] = estados_finais.get(estado, 0) + 1
            _increment_grouped(estados_finais_grouped, estado, grupo)
            if retorno_temporal:
                retornos[retorno_temporal] = retornos.get(retorno_temporal, 0) + 1
                _increment_grouped(retornos_grouped, retorno_temporal, grupo)
            custo_total = float(
                (getattr(resposta_t30, "custo_remedios", 0) or 0)
                + (getattr(resposta_t30, "custo_consultas", 0) or 0)
                + (getattr(resposta_t30, "custo_transporte", 0) or 0)
                + (getattr(resposta_t30, "custo_outros", 0) or 0)
            )
            if grupo in grupo_metrics:
                grupo_metrics[grupo]["custos"].append(custo_total)
                grupo_metrics[grupo]["dias_t30"].append(getattr(resposta_t30, "dias_incap_novos", 0) or 0)
                if _recuperacao_alta_sfa(estado):
                    grupo_metrics[grupo]["recuperacao_alta"] += 1
            if retorno_temporal in return_cost_buckets:
                return_cost_buckets[retorno_temporal].append(custo_total)
            if sexo in recovery_segments:
                recovery_segments[sexo]["total"] += 1
            if faixa in recovery_segments:
                recovery_segments[faixa]["total"] += 1
            alta = _recuperacao_alta_sfa(estado)
            if alta:
                if sexo in recovery_segments:
                    recovery_segments[sexo]["alta"] += 1
                if faixa in recovery_segments:
                    recovery_segments[faixa]["alta"] += 1

    distributions = [
        _dashboard_grouped_distribution("Evolução percebida no T10", melhorias_grouped),
        _dashboard_grouped_distribution("Estado final no T30", estados_finais_grouped),
        _dashboard_grouped_distribution("Retorno às atividades", retornos_grouped),
        _dashboard_grouped_distribution("Tipo de residência", residencias_grouped),
        _dashboard_grouped_distribution("Bairros do lote", bairros_grouped),
    ]

    cost_labels = [
        ("Medicamentos", "custo_remedios"),
        ("Consultas/exames", "custo_consultas"),
        ("Transporte", "custo_transporte"),
        ("Outros", "custo_outros"),
    ]
    cost_breakdown = []
    max_cost = 0.0
    for label, attr in cost_labels:
        avg_value = _avg([getattr(resposta, attr, None) for resposta in t30s])
        max_cost = max(max_cost, avg_value)
        cost_breakdown.append({"label": label, "value": avg_value})
    for item in cost_breakdown:
        item["pct"] = round((item["value"] / max_cost) * 100, 1) if max_cost else 0

    dias_t0 = []
    dias_t10 = []
    dias_t30 = []
    for paciente in pacientes:
        inicio = parse_data(getattr(getattr(paciente, "resposta_t0", None), "data_inicio_sintomas", ""))
        if not inicio:
            continue
        if paciente.data_t0 and parse_data(paciente.data_t0):
            dias_t0.append((parse_data(paciente.data_t0) - inicio).days)
        if paciente.data_t10 and parse_data(paciente.data_t10):
            dias_t10.append((parse_data(paciente.data_t10) - inicio).days)
        if paciente.data_t30 and parse_data(paciente.data_t30):
            dias_t30.append((parse_data(paciente.data_t30) - inicio).days)

    timeline_cards = [
        {"label": "Dias médios até T0", "value": _avg(dias_t0)},
        {"label": "Dias médios até T10", "value": _avg(dias_t10)},
        {"label": "Dias médios até T30", "value": _avg(dias_t30)},
    ]

    research_cards = [
        {"label": "Sexo mais frequente", "value": max(sexo_dist, key=sexo_dist.get) if sexo_dist else "N/D"},
        {"label": "Faixa etária mais frequente", "value": max(faixa_etaria_dist, key=faixa_etaria_dist.get) if faixa_etaria_dist else "N/D"},
        {"label": "Ocupação mais frequente", "value": max(ocupacao_dist, key=ocupacao_dist.get) if ocupacao_dist else "N/D"},
        {"label": "Sintoma mais frequente", "value": max(sintomas_dist, key=sintomas_dist.get) if sintomas_dist else "N/D"},
    ]

    group_comparison = [
        {
            "metric": "Pacientes",
            "a": grupo_metrics["A"]["pacientes"],
            "b": grupo_metrics["B"]["pacientes"],
        },
        {
            "metric": "Custo final médio",
            "a": f"R$ {_avg(grupo_metrics['A']['custos']):.1f}",
            "b": f"R$ {_avg(grupo_metrics['B']['custos']):.1f}",
        },
        {
            "metric": "Dias incapacitantes T30",
            "a": _avg(grupo_metrics["A"]["dias_t30"]),
            "b": _avg(grupo_metrics["B"]["dias_t30"]),
        },
        {
            "metric": "Recuperação alta",
            "a": f"{grupo_metrics['A']['recuperacao_alta']}/{grupo_metrics['A']['pacientes'] or 0}",
            "b": f"{grupo_metrics['B']['recuperacao_alta']}/{grupo_metrics['B']['pacientes'] or 0}",
        },
    ]

    symptom_prevalence = _dashboard_grouped_distribution(
        "Sintomas principais no T0",
        sintomas_grouped,
        {"total": total, "A": grupo_metrics["A"]["pacientes"], "B": grupo_metrics["B"]["pacientes"]},
        limit=8,
    )["items"]
    demographic_distributions = [
        _dashboard_grouped_distribution("Sexo biológico", sexo_grouped),
        _dashboard_grouped_distribution("Faixa etária", faixa_etaria_grouped),
        _dashboard_grouped_distribution("Ocupação principal", ocupacao_grouped),
    ]

    symptom_group_rows = []
    for sintoma, values in sorted(symptom_group_matrix.items(), key=lambda item: (-item[1]["total"], item[0])):
        symptom_group_rows.append(
            {
                "symptom": sintoma,
                "a": values["A"],
                "b": values["B"],
                "a_pct": _safe_ratio(values["A"], grupo_metrics["A"]["pacientes"]),
                "b_pct": _safe_ratio(values["B"], grupo_metrics["B"]["pacientes"]),
            }
        )

    recovery_segment_rows = []
    for label, values in recovery_segments.items():
        if not values["total"]:
            continue
        recovery_segment_rows.append(
            {
                "segment": label,
                "alta": values["alta"],
                "total": values["total"],
                "pct": _safe_ratio(values["alta"], values["total"]),
            }
        )
    recovery_segment_rows.sort(key=lambda item: (-item["pct"], item["segment"]))

    return_cost_rows = []
    for label, values in return_cost_buckets.items():
        if not values:
            continue
        return_cost_rows.append(
            {
                "segment": label,
                "avg_cost": _avg(values),
                "count": len(values),
            }
        )
    return_cost_rows.sort(key=lambda item: -item["avg_cost"])

    top_differentiators = []
    for row in symptom_group_rows:
        gap = round(abs(row["a_pct"] - row["b_pct"]), 1)
        top_differentiators.append(
            {
                "label": row["symptom"],
                "group": "A" if row["a_pct"] >= row["b_pct"] else "B",
                "gap": gap,
                "a_pct": row["a_pct"],
                "b_pct": row["b_pct"],
            }
        )
    top_differentiators.sort(key=lambda item: (-item["gap"], item["label"]))

    clusters = {
        "Recuperação rápida e baixo custo": {"count": 0, "days": []},
        "Recuperação clínica com custo alto": {"count": 0, "days": []},
        "Recuperação lenta com limitação funcional": {"count": 0, "days": []},
        "Persistência de impacto": {"count": 0, "days": []},
    }
    for paciente in pacientes:
        resposta_t0 = getattr(paciente, "resposta_t0", None)
        resposta_t10 = _resposta_recente(getattr(paciente, "respostas_t10", []))
        resposta_t30 = _resposta_recente(getattr(paciente, "respostas_t30", []))
        if not resposta_t30:
            continue

        payload_t0 = json.loads(getattr(resposta_t0, "dados_json", "{}") or "{}") if resposta_t0 else {}
        payload_t10 = json.loads(getattr(resposta_t10, "dados_json", "{}") or "{}") if resposta_t10 else {}
        payload_t30 = json.loads(getattr(resposta_t30, "dados_json", "{}") or "{}")
        inicio_sintomas = payload_t0.get("data_inicio_sintomas") or getattr(resposta_t0, "data_inicio_sintomas", "")
        estado = str(payload_t30.get("estado_saude_final") or "")
        retorno = _retorno_atividades_temporal_sfa(payload_t30.get("retorno_atividades_normais"))
        if not retorno:
            continue
        melhora_t10 = str(payload_t10.get("classificacao_melhora") or "").startswith("Melhorando")
        dias_ate_t10 = _days_between(inicio_sintomas, getattr(paciente, "data_t10", ""))
        dias_ate_t30 = _days_between(inicio_sintomas, getattr(paciente, "data_t30", ""))
        dias_ate_melhora = dias_ate_t10 if melhora_t10 and dias_ate_t10 is not None else dias_ate_t30
        custo_total = float(
            (getattr(resposta_t30, "custo_remedios", 0) or 0)
            + (getattr(resposta_t30, "custo_consultas", 0) or 0)
            + (getattr(resposta_t30, "custo_transporte", 0) or 0)
            + (getattr(resposta_t30, "custo_outros", 0) or 0)
        )
        if (
            _recuperacao_alta_sfa(estado)
            and _retorno_atividades_rapido_sfa(retorno)
            and custo_total <= 30
            and (dias_ate_melhora is None or dias_ate_melhora <= 14)
        ):
            cluster_label = "Recuperação rápida e baixo custo"
        elif _recuperacao_alta_sfa(estado):
            cluster_label = "Recuperação clínica com custo alto"
        elif _retorno_atividades_lento_sfa(retorno) or (dias_ate_melhora is not None and dias_ate_melhora > 21):
            cluster_label = "Recuperação lenta com limitação funcional"
        else:
            cluster_label = "Persistência de impacto"

        clusters[cluster_label]["count"] += 1
        if dias_ate_melhora is not None:
            clusters[cluster_label]["days"].append(dias_ate_melhora)

    cluster_summary = [
        {
            "label": label,
            "count": values["count"],
            "pct": _safe_ratio(values["count"], len(t30s)),
            "avg_days": _avg(values["days"]),
            "time_label": "dias desde início dos sintomas até melhora/fechamento",
        }
        for label, values in clusters.items()
        if values["count"]
    ]
    cluster_summary.sort(key=lambda item: (-item["count"], item["label"]))

    research_alerts = []
    if grupo_metrics["A"]["custos"] and grupo_metrics["B"]["custos"]:
        avg_a = _avg(grupo_metrics["A"]["custos"])
        avg_b = _avg(grupo_metrics["B"]["custos"])
        if avg_a > avg_b:
            research_alerts.append(f"Grupo A com custo final médio maior: R$ {avg_a:.1f} vs R$ {avg_b:.1f}.")
        elif avg_b > avg_a:
            research_alerts.append(f"Grupo B com custo final médio maior: R$ {avg_b:.1f} vs R$ {avg_a:.1f}.")
    if recovery_segment_rows:
        top_segment = recovery_segment_rows[0]
        research_alerts.append(
            f"Melhor recuperação alta no segmento {top_segment['segment']}: {top_segment['pct']}%."
        )
    if symptom_group_rows:
        top_symptom = symptom_group_rows[0]
        if top_symptom["a_pct"] != top_symptom["b_pct"]:
            grupo_lider = "A" if top_symptom["a_pct"] > top_symptom["b_pct"] else "B"
            lider_pct = top_symptom["a_pct"] if grupo_lider == "A" else top_symptom["b_pct"]
            research_alerts.append(
                f"Sintoma '{top_symptom['symptom']}' mais concentrado no grupo {grupo_lider}: {lider_pct}%."
            )
    if return_cost_rows:
        top_return = return_cost_rows[0]
        research_alerts.append(
            f"Maior custo médio aparece em '{top_return['segment']}': R$ {top_return['avg_cost']:.1f}."
        )

    lowest_recovery = recovery_segment_rows[-1] if recovery_segment_rows else None
    strongest_diff = top_differentiators[0] if top_differentiators else None
    highest_cost_return = return_cost_rows[0] if return_cost_rows else None
    hypothesis_cards = []
    if strongest_diff:
        hypothesis_cards.append(
            {
                "title": "Sintoma discriminante",
                "body": f"{strongest_diff['label']} diferencia mais os grupos, favorecendo o grupo {strongest_diff['group']} ({strongest_diff['gap']} p.p.).",
            }
        )
    if highest_cost_return:
        hypothesis_cards.append(
            {
                "title": "Custo e funcionalidade",
                "body": f"O maior custo médio aparece em '{highest_cost_return['segment']}'.",
            }
        )
    if lowest_recovery:
        hypothesis_cards.append(
            {
                "title": "Recuperação mais lenta",
                "body": f"O segmento {lowest_recovery['segment']} teve a menor taxa de recuperação alta ({lowest_recovery['pct']}%).",
            }
        )
    if cluster_summary:
        hypothesis_cards.append(
            {
                "title": "Cluster predominante",
                "body": f"O cluster mais frequente foi '{cluster_summary[0]['label']}' com {cluster_summary[0]['count']} caso(s).",
            }
        )

    return {
        "cards": cards,
        "distributions": distributions,
        "cost_breakdown": cost_breakdown,
        "timeline_cards": timeline_cards,
        "research_cards": research_cards,
        "group_comparison": group_comparison,
        "symptom_prevalence": symptom_prevalence,
        "demographic_distributions": demographic_distributions,
        "research_alerts": research_alerts,
        "symptom_group_matrix": symptom_group_rows[:8],
        "recovery_segments": recovery_segment_rows[:8],
        "return_cost_segments": return_cost_rows[:6],
        "hypothesis_cards": hypothesis_cards,
        "cluster_summary": cluster_summary[:6],
        "top_differentiators": top_differentiators[:6],
    }

@bp.route("/pacientes")
@require_sfa_internal_access
def pacientes():
    filtros = _coletar_filtros_pacientes()
    page = request.args.get("page", 1, type=int)

    q = _consulta_pacientes_filtrada(filtros)
    dashboard_testes = None
    if filtros.get("visao") == "testes":
        dashboard_testes = _montar_dashboard_testes_sfa(q.all())
    paginacao = q.paginate(page=page, per_page=50, error_out=False)
    _anexar_datas_notificacao_sinan(paginacao.items)

    return render_template("sfa/pacientes.html",
                           pacientes=paginacao.items,
                           paginacao=paginacao,
                           filtros=filtros,
                           dashboard_testes=dashboard_testes)


def _csv_download_response(csv_text: str, filename: str):
    response = current_app.response_class(
        "\ufeff" + csv_text,
        mimetype="text/csv; charset=utf-8",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@bp.route("/export/cadastro.csv")
@require_sfa_internal_access
def export_cadastro_csv():
    from services.sfa_service import gerar_csv_exportacao_cadastro

    filtros = _coletar_filtros_pacientes()
    pacientes = _consulta_pacientes_filtrada(filtros).all()
    csv_text = gerar_csv_exportacao_cadastro(pacientes)
    return _csv_download_response(csv_text, f"sfa_cadastro_{date.today().isoformat()}.csv")


@bp.route("/export/analitico.csv")
@require_sfa_internal_access
def export_analitico_csv():
    from services.sfa_service import gerar_csv_exportacao_analitica

    filtros = _coletar_filtros_pacientes()
    pacientes = _consulta_pacientes_filtrada(filtros).all()
    csv_text = gerar_csv_exportacao_analitica(pacientes)
    return _csv_download_response(csv_text, f"sfa_analitico_{date.today().isoformat()}.csv")


@bp.route("/tcle/assinaturas")
@require_sfa_internal_access
def tcle_signatures():
    from services.sfa_service import listar_assinaturas_tcle

    assinaturas = listar_assinaturas_tcle()
    return render_template(
        "sfa/tcle_signatures.html",
        assinaturas=assinaturas,
        total_assinaturas=len(assinaturas),
    )


@bp.route("/tcle/assinaturas.csv")
@require_sfa_internal_access
def export_tcle_signatures_csv():
    from services.sfa_service import gerar_csv_assinaturas_tcle, listar_assinaturas_tcle

    assinaturas = listar_assinaturas_tcle()
    csv_text = gerar_csv_assinaturas_tcle(assinaturas)
    return _csv_download_response(csv_text, f"sfa_tcle_assinaturas_{date.today().isoformat()}.csv")


# ---------------------------------------------------------------------------
# Detalhe do paciente
# ---------------------------------------------------------------------------

@bp.route("/paciente/<id_estudo>")
@require_sfa_internal_access
def paciente_detail(id_estudo: str):
    from models.sfa import SfaPaciente, SfaAuditoria
    from services.sfa_service import (
        link_whatsapp, normalizar_telefone,
        msg_convite_t0, msg_lembrete_t10, msg_lembrete_t30,
        gerar_url_t0, gerar_url_t10, gerar_url_t30,
        carregar_t0_form_schema, carregar_t10_form_schema, carregar_t30_form_schema,
        montar_visao_resposta_formulario, obter_resposta_formulario,
    )

    def _format_currency(value) -> str:
        if value in (None, ""):
            return "Nao informado"
        return f"R$ {float(value):.2f}"

    def _format_timestamp(value) -> str:
        text = str(value or "").strip()
        if not text:
            return "Nao informado"
        try:
            return date.fromisoformat(text).strftime("%d/%m/%Y")
        except ValueError:
            pass
        try:
            from datetime import datetime

            return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return text

    def _compact_summary(items):
        return [
            {"label": label, "value": value}
            for label, value in items
            if value not in (None, "", "Nao informado")
        ]

    p = SfaPaciente.query.filter_by(id_estudo=id_estudo).first_or_404()
    auditoria = (SfaAuditoria.query
                 .filter_by(id_estudo=id_estudo)
                 .order_by(SfaAuditoria.timestamp.desc())
                 .limit(20).all())

    tel = normalizar_telefone(p.telefone or "")
    links_whatsapp = {}
    if tel:
        links_whatsapp["T0"] = link_whatsapp(tel, msg_convite_t0(p.nome, p.id_estudo, p.token_acesso or ""))
        links_whatsapp["T10"] = link_whatsapp(tel, msg_lembrete_t10(p.nome, p.id_estudo, p.token_acesso or ""))
        links_whatsapp["T30"] = link_whatsapp(tel, msg_lembrete_t30(p.nome, p.id_estudo, p.token_acesso or ""))

    url_t0 = gerar_url_t0(p.id_estudo, p.token_acesso or "")
    url_t0_debug = gerar_url_t0(p.id_estudo, p.token_acesso or "", debug=True)
    url_t10 = gerar_url_t10(p.id_estudo, p.token_acesso or "")
    url_t10_debug = gerar_url_t10(p.id_estudo, p.token_acesso or "", debug=True)
    url_t30 = gerar_url_t30(p.id_estudo, p.token_acesso or "")
    url_t30_debug = gerar_url_t30(p.id_estudo, p.token_acesso or "", debug=True)

    schemas = {
        "t0": carregar_t0_form_schema(),
        "t10": carregar_t10_form_schema(),
        "t30": carregar_t30_form_schema(),
    }
    response_views = []

    for stage, stage_label, icon, badge_class in [
        ("t0", "T0", "fas fa-clipboard-list", "success"),
        ("t10", "T10", "fas fa-clipboard-check", "warning"),
        ("t30", "T30", "fas fa-flag-checkered", "primary"),
    ]:
        resposta = obter_resposta_formulario(p, stage)
        if not resposta:
            continue

        view = montar_visao_resposta_formulario(stage, resposta, schema=schemas[stage])
        payload = view["payload"]

        if stage == "t0":
            summary = _compact_summary(
                [
                    ("Inicio sintomas", payload.get("data_inicio_sintomas") or getattr(resposta, "data_inicio_sintomas", "")),
                    ("Tipo de moradia", payload.get("tipo_residencia") or getattr(resposta, "tipo_residencia", "")),
                    ("Dias incapacitado", payload.get("dias_incap") or getattr(resposta, "dias_incap", "")),
                    ("Custo total", _format_currency(getattr(resposta, "custo_total", ""))),
                    ("TCLE assinado por", payload.get("tcle_assinado_por")),
                    ("TCLE registrado em", _format_timestamp(payload.get("consentimento_registrado_em"))),
                ]
            )
        elif stage == "t10":
            summary = _compact_summary(
                [
                    ("Evolucao", payload.get("classificacao_melhora")),
                    ("Dias incapacitado", payload.get("dias_incap_novos") or getattr(resposta, "dias_incap_novos", "")),
                    ("Custo total", _format_currency(getattr(resposta, "custo_total", ""))),
                    ("Previsao retorno", payload.get("retorno_atividades_previsao")),
                ]
            )
        else:
            summary = _compact_summary(
                [
                    ("Estado final", payload.get("estado_saude_final")),
                    ("Dias incapacitado", payload.get("dias_incap_novos") or getattr(resposta, "dias_incap_novos", "")),
                    ("Custo total", _format_currency(getattr(resposta, "custo_total", ""))),
                    ("Quando voltou as atividades", payload.get("retorno_atividades_normais")),
                ]
            )

        response_views.append(
            {
                **view,
                "stage_label": stage_label,
                "icon": icon,
                "badge_class": badge_class,
                "summary": summary,
            }
        )

    return render_template("sfa/paciente_detail.html",
                           p=p,
                           auditoria=auditoria,
                           links_whatsapp=links_whatsapp,
                           response_views=response_views,
                           url_t0=url_t0,
                           url_t0_debug=url_t0_debug,
                           url_t10=url_t10,
                           url_t10_debug=url_t10_debug,
                           url_t30=url_t30,
                           url_t30_debug=url_t30_debug)


# ---------------------------------------------------------------------------
# Marcar status WhatsApp
# ---------------------------------------------------------------------------

@bp.route("/paciente/<id_estudo>/whatsapp", methods=["POST"])
@require_sfa_internal_access
def marcar_whatsapp(id_estudo: str):
    from extensions import db
    from models.sfa import SfaPaciente
    from services.sfa_service import formatar_data
    from datetime import date

    p = SfaPaciente.query.filter_by(id_estudo=id_estudo).first_or_404()
    novo_status = request.form.get("status", "ENVIADO")
    if novo_status not in ("ENVIADO", "RESPONDIDO", "SEM_WHATSAPP"):
        abort(400)

    p.status_whatsapp = novo_status
    p.data_ultimo_whatsapp = formatar_data(date.today())
    if novo_status == "RESPONDIDO":
        p.retorno_contato = "ACEITOU"
    db.session.commit()
    flash(f"WhatsApp marcado como {novo_status}.", "success")
    return redirect(url_for("sfa_routes.paciente_detail", id_estudo=id_estudo))


@bp.route("/paciente/manual", methods=["POST"])
@require_sfa_internal_access
def criar_paciente_manual():
    from services.sfa_service import criar_paciente_manual as criar_manual_service

    ok, resultado, paciente = criar_manual_service(request.form)
    if not ok:
        flash(resultado, "warning")
        if paciente is not None:
            return redirect(url_for("sfa_routes.paciente_detail", id_estudo=paciente.id_estudo))
        return redirect(url_for("sfa_routes.dashboard"))

    flash(f"Participante {resultado} criado com sucesso.", "success")
    return redirect(url_for("sfa_routes.paciente_detail", id_estudo=resultado))


@bp.route("/teste-dados/gerar", methods=["POST"])
@require_sfa_internal_access
def gerar_teste_dados():
    from services.sfa_service import gerar_lote_pacientes_teste_sfa

    quantidade = request.form.get("quantidade", 10, type=int) or 10
    resumo = gerar_lote_pacientes_teste_sfa(quantidade)
    flash(
        f"Lote de teste {resumo['batch_id']} criado com {resumo['total']} pacientes. "
        "Os registros ficam ocultos do fluxo real por padrão.",
        "success",
    )
    return redirect(url_for("sfa_routes.pacientes", visao="testes"))


@bp.route("/teste-dados/apagar", methods=["POST"])
@require_sfa_internal_access
def apagar_teste_dados():
    from services.sfa_service import apagar_lote_pacientes_teste_sfa

    resumo = apagar_lote_pacientes_teste_sfa()
    flash(f"{resumo['removidos']} paciente(s) de teste removido(s).", "success")
    return redirect(url_for("sfa_routes.dashboard"))


# ---------------------------------------------------------------------------
# Redirect T0 — substitui o doGet() do Web App GAS
# ---------------------------------------------------------------------------

def _buscar_paciente_publico_t0(token: str):
    from models.sfa import SfaPaciente

    return (
        SfaPaciente.query.filter_by(token_acesso=token).first()
        or SfaPaciente.query.filter_by(id_estudo=token).first()
    )


def _resposta_publica_existente(paciente, form_stage: str) -> bool:
    stage = str(form_stage or "").strip().lower()
    if stage == "t0":
        return bool(getattr(paciente, "resposta_t0", None))
    if stage == "t10":
        return bool(getattr(paciente, "respostas_t10", []))
    if stage == "t30":
        return bool(getattr(paciente, "respostas_t30", []))
    return False


def _render_public_native_form(
    token: str,
    form_stage: str,
    form_name: str,
    schema_loader,
    initial_builder,
    collector,
    submitter,
):
    from services.sfa_service import iterar_campos_form, registrar_auditoria

    debug = request.args.get("debug") == "1"
    paciente = _buscar_paciente_publico_t0(token)

    if not paciente:
        registrar_auditoria(
            "WARN",
            "PACIENTE_NAO_ENCONTRADO",
            f"redirect_{form_stage}",
            f"Token/id nao encontrado: {token}",
        )
        return render_template(
            "sfa/erro.html",
            mensagem=(
                "Participante nao encontrado. Verifique o link ou entre em contato "
                "com o pesquisador."
            ),
        ), 404

    schema = schema_loader()
    values = initial_builder(paciente, schema)
    errors: dict[str, str] = {}

    if request.method == "POST":
        if _resposta_publica_existente(paciente, form_stage):
            return render_template(
                "sfa/t0_submitted.html",
                paciente=paciente,
                already_submitted=True,
                form_name=form_name,
                form_stage=form_stage,
            )

        for field in iterar_campos_form(schema):
            key = field["key"]
            if field.get("type") == "checkboxes":
                values[key] = request.form.getlist(key)
            else:
                values[key] = str(request.form.get(key) or "").strip()

        dados, errors = collector(schema, request.form, paciente)
        if not errors:
            if form_stage == "t0":
                forwarded_for = str(request.headers.get("X-Forwarded-For") or "").strip()
                dados["consentimento_ip"] = (
                    forwarded_for.split(",")[0].strip()
                    if forwarded_for
                    else str(request.remote_addr or "").strip()
                )
                dados["consentimento_user_agent"] = str(
                    request.headers.get("User-Agent") or ""
                ).strip()
            resultado = submitter(dados)
            if resultado.get("ok"):
                return render_template(
                    "sfa/t0_submitted.html",
                    paciente=paciente,
                    already_submitted=False,
                    form_name=form_name,
                    form_stage=form_stage,
                )
            errors["__all__"] = (
                resultado.get("erro")
                or "Nao foi possivel registrar sua resposta agora. Tente novamente em alguns minutos."
            )

    if debug:
        return render_template(
            "sfa/t0_debug.html",
            paciente=paciente,
            schema=schema,
            values=values,
            field_count=sum(1 for _ in iterar_campos_form(schema)),
            form_name=form_name,
            form_stage=form_stage,
        )

    if request.method == "GET" and _resposta_publica_existente(paciente, form_stage):
        return render_template(
            "sfa/t0_submitted.html",
            paciente=paciente,
            already_submitted=True,
            form_name=form_name,
            form_stage=form_stage,
        )

    return render_template(
        "sfa/t0_form.html",
        paciente=paciente,
        schema=schema,
        values=values,
        errors=errors,
        form_name=form_name,
        form_stage=form_stage,
    )


def _render_form_config(form_name: str, form_stage: str, schema_loader, schema_saver):
    from services.sfa_service import (
        iterar_campos_form,
        serializar_t0_form_schema,
        validar_t0_form_schema,
    )

    schema = schema_loader()
    schema_text = serializar_t0_form_schema(schema)
    errors: list[str] = []

    if request.method == "POST":
        schema_text = request.form.get("schema_json", "").strip()
        try:
            schema_enviado = json.loads(schema_text or "{}")
            errors = validar_t0_form_schema(schema_enviado)
            if errors:
                flash(
                    f"Nao foi possivel salvar o {form_name.lower()}. Revise os erros abaixo.",
                    "error",
                )
            else:
                schema_saver(schema_enviado)
                flash(f"{form_name} atualizado com sucesso.", "success")
                return redirect(url_for(f"sfa_routes.{form_stage}_form_config"))
        except json.JSONDecodeError as exc:
            errors = [f"JSON invalido na linha {exc.lineno}, coluna {exc.colno}."]
            flash(
                f"Nao foi possivel salvar o {form_name.lower()}. O JSON esta invalido.",
                "error",
            )

    return render_template(
        "sfa/t0_form_config.html",
        schema=schema,
        schema_text=schema_text,
        errors=errors,
        field_count=sum(1 for _ in iterar_campos_form(schema)),
        form_name=form_name,
        form_stage=form_stage,
    )


@bp.route("/p/<token>", methods=["GET", "POST"])
@csrf.exempt
def redirect_t0(token: str):
    from services.sfa_service import (
        carregar_t0_form_schema,
        coletar_resposta_t0_nativa,
        construir_valores_iniciais_t0,
        on_submit_t0,
    )
    return _render_public_native_form(
        token=token,
        form_stage="t0",
        form_name="Formulario T0",
        schema_loader=carregar_t0_form_schema,
        initial_builder=construir_valores_iniciais_t0,
        collector=coletar_resposta_t0_nativa,
        submitter=on_submit_t0,
    )


@bp.route("/p/<token>/t10", methods=["GET", "POST"])
@csrf.exempt
def redirect_t10(token: str):
    from services.sfa_service import (
        carregar_t10_form_schema,
        coletar_resposta_t10_nativa,
        construir_valores_iniciais_t10,
        on_submit_t10,
    )
    return _render_public_native_form(
        token=token,
        form_stage="t10",
        form_name="Formulario T10",
        schema_loader=carregar_t10_form_schema,
        initial_builder=construir_valores_iniciais_t10,
        collector=coletar_resposta_t10_nativa,
        submitter=on_submit_t10,
    )


@bp.route("/p/<token>/t30", methods=["GET", "POST"])
@csrf.exempt
def redirect_t30(token: str):
    from services.sfa_service import (
        carregar_t30_form_schema,
        coletar_resposta_t30_nativa,
        construir_valores_iniciais_t30,
        on_submit_t30,
    )
    return _render_public_native_form(
        token=token,
        form_stage="t30",
        form_name="Formulario T30",
        schema_loader=carregar_t30_form_schema,
        initial_builder=construir_valores_iniciais_t30,
        collector=coletar_resposta_t30_nativa,
        submitter=on_submit_t30,
    )


@bp.route("/config/t0", methods=["GET", "POST"])
@require_sfa_internal_access
def t0_form_config():
    from services.sfa_service import carregar_t0_form_schema, salvar_t0_form_schema

    return _render_form_config(
        form_name="Formulario T0",
        form_stage="t0",
        schema_loader=carregar_t0_form_schema,
        schema_saver=salvar_t0_form_schema,
    )


@bp.route("/config/t10", methods=["GET", "POST"])
@require_sfa_internal_access
def t10_form_config():
    from services.sfa_service import carregar_t10_form_schema, salvar_t10_form_schema

    return _render_form_config(
        form_name="Formulario T10",
        form_stage="t10",
        schema_loader=carregar_t10_form_schema,
        schema_saver=salvar_t10_form_schema,
    )


@bp.route("/config/t30", methods=["GET", "POST"])
@require_sfa_internal_access
def t30_form_config():
    from services.sfa_service import carregar_t30_form_schema, salvar_t30_form_schema

    return _render_form_config(
        form_name="Formulario T30",
        form_stage="t30",
        schema_loader=carregar_t30_form_schema,
        schema_saver=salvar_t30_form_schema,
    )


# ---------------------------------------------------------------------------
# Webhooks do Google Forms (via Google Apps Script onSubmit)
# ---------------------------------------------------------------------------

@bp.route("/webhook/t0", methods=["POST"])
@csrf.exempt
def webhook_t0():
    if not _verificar_webhook_secret():
        abort(403)
    from services.sfa_service import on_submit_t0
    dados = request.get_json(force=True) or {}
    resultado = on_submit_t0(dados)
    return jsonify(resultado), 200 if resultado.get("ok") else 400


@bp.route("/webhook/t10", methods=["POST"])
@csrf.exempt
def webhook_t10():
    if not _verificar_webhook_secret():
        abort(403)
    from services.sfa_service import on_submit_t10
    dados = request.get_json(force=True) or {}
    resultado = on_submit_t10(dados)
    return jsonify(resultado), 200 if resultado.get("ok") else 400


@bp.route("/webhook/t30", methods=["POST"])
@csrf.exempt
def webhook_t30():
    if not _verificar_webhook_secret():
        abort(403)
    from services.sfa_service import on_submit_t30
    dados = request.get_json(force=True) or {}
    resultado = on_submit_t30(dados)
    return jsonify(resultado), 200 if resultado.get("ok") else 400


# ---------------------------------------------------------------------------
# Ações manuais (disparadas pelo pesquisador via dashboard)
# ---------------------------------------------------------------------------

@bp.route("/sync", methods=["POST"])
@require_sfa_internal_access
def sync_sinan():
    """Dispara sincronização SINAN manualmente."""
    if not _verificar_token_admin():
        abort(403)
    from services.sfa_service import sincronizar_respostas_t0, sincronizar_sinan
    resultado = sincronizar_sinan()
    resultado_t0 = sincronizar_respostas_t0()
    detalhes = [
        detalhe
        for detalhe in [resultado.get("mensagem"), resultado_t0.get("mensagem")]
        if detalhe
    ]
    flash(
        f"SINAN sync: {resultado['novos']} novo(s), {resultado['erros']} erro(s). "
        f"T0: {resultado_t0['importados']} importada(s), {resultado_t0['ignorados']} ignorada(s), "
        f"{resultado_t0['erros']} erro(s).",
        "info",
    )
    if detalhes:
        flash(" | ".join(detalhes), "warning")
    return redirect(url_for("sfa_routes.dashboard"))


@bp.route("/rotina", methods=["POST"])
@require_sfa_internal_access
def rodar_rotina():
    """Roda verificação de seguimento e atualiza operacional."""
    if not _verificar_token_admin():
        abort(403)
    from services.sfa_service import sincronizar_respostas_t0, verificar_seguimento
    from models.sfa import SfaPaciente
    from extensions import db
    from services.sfa_service import atualizar_operacional_paciente

    resultado_t0 = sincronizar_respostas_t0()
    resultado = verificar_seguimento()
    # Atualiza campos operacionais de todos os pacientes
    for p in SfaPaciente.query.all():
        atualizar_operacional_paciente(p)
    db.session.commit()

    flash(
        f"Rotina concluída: {len(resultado['atrasados_t10'])} T10 atrasados, "
        f"{len(resultado['atrasados_t30'])} T30 atrasados, "
        f"{resultado_t0['importados']} T0 importada(s).",
        "info"
    )
    if resultado_t0.get("mensagem"):
        flash(resultado_t0["mensagem"], "warning")
    return redirect(url_for("sfa_routes.dashboard"))
