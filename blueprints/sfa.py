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

from datetime import date
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
    from services.sfa_service import stats_painel, link_whatsapp, normalizar_telefone
    from services.sfa_service import (
        msg_convite_t0, msg_lembrete_t10, msg_lembrete_t30, ACOES_QUE_GERAM_CONTATO
    )

    stats = stats_painel()

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

    return render_template("sfa/dashboard.html", stats=stats)


# ---------------------------------------------------------------------------
# Lista de pacientes
# ---------------------------------------------------------------------------

def _coletar_filtros_pacientes() -> dict[str, str]:
    return {
        "grupo": request.args.get("grupo", ""),
        "status": request.args.get("status", ""),
        "q": request.args.get("q", "").strip(),
    }


def _consulta_pacientes_filtrada(filtros: dict[str, str] | None = None):
    from models.sfa import SfaPaciente

    filtros = filtros or _coletar_filtros_pacientes()
    grupo = filtros.get("grupo", "")
    status = filtros.get("status", "")
    busca = filtros.get("q", "").strip()

    q = SfaPaciente.query

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

    return q.order_by(SfaPaciente.timestamp_cadastro.desc())

@bp.route("/pacientes")
@require_sfa_internal_access
def pacientes():
    filtros = _coletar_filtros_pacientes()
    page = request.args.get("page", 1, type=int)

    q = _consulta_pacientes_filtrada(filtros)
    paginacao = q.paginate(page=page, per_page=50, error_out=False)

    return render_template("sfa/pacientes.html",
                           pacientes=paginacao.items,
                           paginacao=paginacao,
                           filtros=filtros)


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
                    ("Retorno atividades", payload.get("retorno_atividades_normais")),
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
    flash(
        f"SINAN sync: {resultado['novos']} novo(s), {resultado['erros']} erro(s). "
        f"T0: {resultado_t0['importados']} importada(s), {resultado_t0['ignorados']} ignorada(s), "
        f"{resultado_t0['erros']} erro(s).",
        "info",
    )
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
    return redirect(url_for("sfa_routes.dashboard"))
