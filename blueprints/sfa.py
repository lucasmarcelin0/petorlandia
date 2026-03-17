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

import hmac
import hashlib
import os

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

bp = Blueprint("sfa_routes", __name__, url_prefix="/sfa",
               template_folder="../templates/sfa")


def get_blueprint():
    return bp


# ---------------------------------------------------------------------------
# Autenticação simples por token de admin
# ---------------------------------------------------------------------------

def _verificar_token_admin() -> bool:
    """Verifica se a requisição tem o token de admin do SFA."""
    token_esperado = os.getenv("SFA_ADMIN_TOKEN", "")
    if not token_esperado:
        return True  # sem token configurado → acesso livre (dev)
    token = request.headers.get("X-SFA-Token") or request.args.get("token", "")
    return hmac.compare_digest(token, token_esperado)


def _verificar_webhook_secret() -> bool:
    """Verifica o segredo compartilhado nos webhooks do Google Apps Script."""
    secret_esperado = os.getenv("SFA_WEBHOOK_SECRET", "")
    if not secret_esperado:
        return True  # sem segredo configurado → aceita tudo (dev)
    secret = request.headers.get("X-SFA-Secret") or request.args.get("secret", "")
    return hmac.compare_digest(secret, secret_esperado)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@bp.route("/")
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
                    msg = msg_lembrete_t10(p.nome, p.id_estudo)
                elif "T30" in acao:
                    msg = msg_lembrete_t30(p.nome, p.id_estudo)
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

@bp.route("/pacientes")
def pacientes():
    from models.sfa import SfaPaciente

    grupo = request.args.get("grupo", "")
    status = request.args.get("status", "")
    busca = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)

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

    q = q.order_by(SfaPaciente.timestamp_cadastro.desc())
    paginacao = q.paginate(page=page, per_page=50, error_out=False)

    return render_template("sfa/pacientes.html",
                           pacientes=paginacao.items,
                           paginacao=paginacao,
                           filtros={"grupo": grupo, "status": status, "q": busca})


# ---------------------------------------------------------------------------
# Detalhe do paciente
# ---------------------------------------------------------------------------

@bp.route("/paciente/<id_estudo>")
def paciente_detail(id_estudo: str):
    from models.sfa import SfaPaciente, SfaAuditoria
    from services.sfa_service import (
        link_whatsapp, normalizar_telefone,
        msg_convite_t0, msg_lembrete_t10, msg_lembrete_t30,
        gerar_url_t0,
    )

    p = SfaPaciente.query.filter_by(id_estudo=id_estudo).first_or_404()
    auditoria = (SfaAuditoria.query
                 .filter_by(id_estudo=id_estudo)
                 .order_by(SfaAuditoria.timestamp.desc())
                 .limit(20).all())

    tel = normalizar_telefone(p.telefone or "")
    links_whatsapp = {}
    if tel:
        links_whatsapp["T0"] = link_whatsapp(tel, msg_convite_t0(p.nome, p.id_estudo, p.token_acesso or ""))
        links_whatsapp["T10"] = link_whatsapp(tel, msg_lembrete_t10(p.nome, p.id_estudo))
        links_whatsapp["T30"] = link_whatsapp(tel, msg_lembrete_t30(p.nome, p.id_estudo))

    url_t0 = gerar_url_t0(p.id_estudo, p.token_acesso or "")
    url_t0_debug = gerar_url_t0(p.id_estudo, p.token_acesso or "", debug=True)

    return render_template("sfa/paciente_detail.html",
                           p=p,
                           auditoria=auditoria,
                           links_whatsapp=links_whatsapp,
                           url_t0=url_t0,
                           url_t0_debug=url_t0_debug)


# ---------------------------------------------------------------------------
# Marcar status WhatsApp
# ---------------------------------------------------------------------------

@bp.route("/paciente/<id_estudo>/whatsapp", methods=["POST"])
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

@bp.route("/p/<token>")
def redirect_t0(token: str):
    """
    Recebe o token de acesso ou id_estudo, busca o paciente e redireciona
    para o Google Form com os campos pré-preenchidos.

    Modo debug: adicione ?debug=1 à URL.
    """
    from models.sfa import SfaPaciente
    from services.sfa_service import (
        registrar_auditoria, parse_data,
        FORM_T0_ID, ENTRY_T0_ID_ESTUDO, ENTRY_T0_NOME, ENTRY_T0_DATA_NASC_BASE,
    )
    from urllib.parse import urlencode

    debug = request.args.get("debug") == "1"

    # Busca por token_acesso primeiro, depois por id_estudo
    paciente = (SfaPaciente.query.filter_by(token_acesso=token).first()
                or SfaPaciente.query.filter_by(id_estudo=token).first())

    if not paciente:
        registrar_auditoria("WARN", "PACIENTE_NAO_ENCONTRADO", "redirect_t0",
                             f"Token/id não encontrado: {token}")
        return render_template("sfa/erro.html",
                               mensagem="Participante não encontrado. Verifique o link ou entre em contato com o pesquisador."), 404

    # Monta URL pré-preenchida do Google Forms
    params = {}
    if ENTRY_T0_ID_ESTUDO and paciente.id_estudo:
        params[ENTRY_T0_ID_ESTUDO] = paciente.id_estudo
    if ENTRY_T0_NOME and paciente.nome:
        params[ENTRY_T0_NOME] = paciente.nome
    if ENTRY_T0_DATA_NASC_BASE and paciente.data_nascimento:
        d = parse_data(paciente.data_nascimento)
        if d:
            base_id = ENTRY_T0_DATA_NASC_BASE.replace("entry.", "")
            params[f"entry.{base_id}_year"] = d.year
            params[f"entry.{base_id}_month"] = d.month
            params[f"entry.{base_id}_day"] = d.day

    if params and FORM_T0_ID:
        base_url = f"https://docs.google.com/forms/d/{FORM_T0_ID}/viewform?usp=pp_url"
        form_url = f"{base_url}&{urlencode(params)}"
    else:
        form_url = f"https://docs.google.com/forms/d/{FORM_T0_ID}/viewform" if FORM_T0_ID else "#"

    if debug:
        return render_template("sfa/redirect_debug.html",
                               paciente=paciente,
                               form_url=form_url,
                               params=params,
                               entry_id_estudo=ENTRY_T0_ID_ESTUDO,
                               form_t0_id=FORM_T0_ID)

    return render_template("sfa/redirect.html", form_url=form_url)


# ---------------------------------------------------------------------------
# Webhooks do Google Forms (via Google Apps Script onSubmit)
# ---------------------------------------------------------------------------

@bp.route("/webhook/t0", methods=["POST"])
def webhook_t0():
    if not _verificar_webhook_secret():
        abort(403)
    from services.sfa_service import on_submit_t0
    dados = request.get_json(force=True) or {}
    resultado = on_submit_t0(dados)
    return jsonify(resultado), 200 if resultado.get("ok") else 400


@bp.route("/webhook/t10", methods=["POST"])
def webhook_t10():
    if not _verificar_webhook_secret():
        abort(403)
    from services.sfa_service import on_submit_t10
    dados = request.get_json(force=True) or {}
    resultado = on_submit_t10(dados)
    return jsonify(resultado), 200 if resultado.get("ok") else 400


@bp.route("/webhook/t30", methods=["POST"])
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
def sync_sinan():
    """Dispara sincronização SINAN manualmente."""
    if not _verificar_token_admin():
        abort(403)
    from services.sfa_service import sincronizar_sinan
    resultado = sincronizar_sinan()
    flash(f"SINAN sync: {resultado['novos']} novo(s), {resultado['erros']} erro(s).", "info")
    return redirect(url_for("sfa_routes.dashboard"))


@bp.route("/rotina", methods=["POST"])
def rodar_rotina():
    """Roda verificação de seguimento e atualiza operacional."""
    if not _verificar_token_admin():
        abort(403)
    from services.sfa_service import verificar_seguimento
    from models.sfa import SfaPaciente
    from extensions import db
    from services.sfa_service import atualizar_operacional_paciente

    resultado = verificar_seguimento()
    # Atualiza campos operacionais de todos os pacientes
    for p in SfaPaciente.query.all():
        atualizar_operacional_paciente(p)
    db.session.commit()

    flash(
        f"Rotina concluída: {len(resultado['atrasados_t10'])} T10 atrasados, "
        f"{len(resultado['atrasados_t30'])} T30 atrasados.",
        "info"
    )
    return redirect(url_for("sfa_routes.dashboard"))
