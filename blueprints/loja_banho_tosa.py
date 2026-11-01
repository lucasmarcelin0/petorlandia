"""Banho e tosa da loja: agenda do dia, pacote do mês e cobrança no caixa.

Rotas novas. Os planos públicos e as assinaturas pelo Mercado Pago
continuam nas rotas de sempre (``/planos/tosa``).
"""
from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import GroomingPlan, GroomingSessao
from models.loja_caixa import FORMAS_PAGAMENTO_CAIXA
from services import loja_banho_tosa as banho_tosa
from services.loja_banho_tosa import BanhoTosaError
from services.loja_caixa import pdv
from time_utils import BR_TZ, now_in_brazil


bp = Blueprint("loja_banho_tosa_routes", __name__)


def get_blueprint():
    return bp


def ensure_loja_access(casa_id: int):
    """Dono da loja, quem a cadastrou ou admin; os demais recebem 403."""
    import app as app_module

    return app_module._casa_loja_access(casa_id)


def ensure_loja_operacao(casa_id: int):
    """Dono/admin ou operador ativo da loja (dia a dia); os demais recebem 403."""
    import app as app_module

    return app_module.ensure_loja_operacao(casa_id)


def _dia(texto: str | None) -> date:
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date() if texto else now_in_brazil().date()
    except ValueError:
        return now_in_brazil().date()


def _sessao_da_loja(casa, sessao_id: int) -> GroomingSessao:
    sessao = GroomingSessao.query.filter_by(id=sessao_id, casa_de_racao_id=casa.id).first()
    if sessao is None:
        abort(404)
    return sessao


def _voltar(casa, sessao=None):
    dia = request.form.get("dia") or (
        sessao.agendado_para.astimezone(BR_TZ).date().isoformat() if sessao and sessao.agendado_para.tzinfo else None
    )
    return redirect(url_for("loja_banho_tosa_agenda", casa_id=casa.id, dia=dia))


@bp.route("/casa-de-racao/<int:casa_id>/banho-tosa", methods=["GET"])
@login_required
def loja_banho_tosa_agenda(casa_id):
    casa = ensure_loja_operacao(casa_id)
    dia = _dia(request.args.get("dia"))
    planos = banho_tosa.planos_da_loja(casa.id)
    sessoes = banho_tosa.agenda_do_dia(casa.id, dia)
    saldos = {}
    for sessao in sessoes:
        if sessao.subscription is not None and sessao.subscription_id not in saldos:
            usados = banho_tosa.sessoes_no_mes(sessao.subscription, sessao.agendado_para)
            saldos[sessao.subscription_id] = (usados, sessao.plan.sessions_per_month if sessao.plan else 0)
    return render_template(
        "loja_banho_tosa/agenda.html",
        casa=casa,
        dia=dia,
        planos=planos,
        animais=banho_tosa.animais_da_loja(casa.id),
        sessoes=sessoes,
        saldos=saldos,
        caixa=pdv.caixa_aberto(casa.id),
        formas=FORMAS_PAGAMENTO_CAIXA,
    )


@bp.route("/casa-de-racao/<int:casa_id>/banho-tosa/agendar", methods=["POST"])
@login_required
def loja_banho_tosa_agendar(casa_id):
    casa = ensure_loja_operacao(casa_id)
    try:
        quando = datetime.strptime(
            f"{request.form.get('data')} {request.form.get('hora') or '09:00'}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=BR_TZ)
        sessao = banho_tosa.agendar(
            casa,
            animal_id=int(request.form.get("animal_id") or 0),
            plan_id=int(request.form.get("plan_id") or 0),
            quando=quando,
            observacao=request.form.get("observacao"),
            usuario_id=getattr(current_user, "id", None),
        )
        flash(f"{sessao.animal.name} agendado para {quando:%d/%m às %H:%M}.", "success")
        return redirect(url_for("loja_banho_tosa_agenda", casa_id=casa.id, dia=quando.date().isoformat()))
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc) if isinstance(exc, BanhoTosaError) else "Informe data e hora válidas.", "warning")
    return redirect(url_for("loja_banho_tosa_agenda", casa_id=casa.id, dia=request.form.get("data")))


@bp.route("/casa-de-racao/<int:casa_id>/banho-tosa/<int:sessao_id>/status", methods=["POST"])
@login_required
def loja_banho_tosa_status(casa_id, sessao_id):
    casa = ensure_loja_operacao(casa_id)
    sessao = _sessao_da_loja(casa, sessao_id)
    try:
        banho_tosa.mudar_status(sessao, request.form.get("status") or "")
        flash(f"{sessao.animal.name}: {sessao.status_label.lower()}.", "success")
    except BanhoTosaError as exc:
        flash(str(exc), "warning")
    return _voltar(casa, sessao)


@bp.route("/casa-de-racao/<int:casa_id>/banho-tosa/<int:sessao_id>/cobrar", methods=["POST"])
@login_required
def loja_banho_tosa_cobrar(casa_id, sessao_id):
    casa = ensure_loja_operacao(casa_id)
    sessao = _sessao_da_loja(casa, sessao_id)
    try:
        venda = banho_tosa.cobrar_no_caixa(
            casa,
            sessao,
            caixa=pdv.caixa_aberto(casa.id),
            pagamentos=[{"t_pag": request.form.get("t_pag"), "valor": request.form.get("valor")}],
            usuario_id=getattr(current_user, "id", None),
        )
        troco = f"{venda.troco:.2f}".replace(".", ",")
        flash(f"Recebido no caixa (venda #{venda.id}). Troco: R$ {troco}.", "success")
    except BanhoTosaError as exc:
        flash(str(exc), "warning")
    return _voltar(casa, sessao)


@bp.route("/casa-de-racao/<int:casa_id>/planos/tosa/<int:plan_id>/editar", methods=["GET", "POST"])
@login_required
def loja_banho_tosa_plano_editar(casa_id, plan_id):
    from forms import GroomingPlanForm

    casa = ensure_loja_access(casa_id)
    plan = GroomingPlan.query.filter_by(id=plan_id, casa_de_racao_id=casa.id).first()
    if plan is None:
        abort(404)
    form = GroomingPlanForm(obj=plan)
    if form.validate_on_submit():
        cobranca = form.cobranca.data if form.cobranca.data in ("mensal", "avulso") else "mensal"
        plan.name = form.name.data
        plan.description = form.description.data or None
        plan.service_type = form.service_type.data
        plan.price = form.price.data
        plan.cobranca = cobranca
        plan.sessions_per_month = 1 if cobranca == "avulso" else form.sessions_per_month.data
        plan.peso_min_kg = form.peso_min_kg.data
        plan.peso_max_kg = form.peso_max_kg.data
        db.session.commit()
        flash("Serviço atualizado.", "success")
        return redirect(url_for("casa_de_racao_grooming_planos", casa_id=casa.id))
    return render_template("loja_banho_tosa/plano_editar.html", casa=casa, plan=plan, form=form)
