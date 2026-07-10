"""Loja, carrinho, pagamentos (Mercado Pago) e entregas — views do domínio.

``mp_sdk``, ``upload_to_s3``, ``verify_mp_signature``, ``CheckoutForm``,
``_run_whatsapp_batch_selenium`` e ``_is_admin`` são late-bound via módulo app
(testes fazem monkeypatch desses nomes — contrato do antigo lazy_view).
"""
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timedelta
from decimal import Decimal

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from extensions import csrf, db, mail
from flask_mail import Message as MailMessage
from forms import (
    AddToCartForm,
    CartAddressForm,
    DeliveryRequestForm,
    EditAddressForm,
    OrderItemForm,
    ProductPhotoForm,
    ProductUpdateForm,
)
from models import (
    BlocoOrcamento,
    CasaDeRacao,
    Clinica,
    ClinicInventoryItem,
    ClinicInventoryMovement,
    DataShareAccess,
    DataShareLog,
    DeliveryRequest,
    Endereco,
    Orcamento,
    Order,
    OrderItem,
    Payment,
    PaymentMethod,
    PaymentStatus,
    PendingWebhook,
    PickupLocation,
    Product,
    ProductPhoto,
    SavedAddress,
    TipoRacao,
    User,
    get_active_product_categories,
)
from security.crypto import MissingMasterKeyError
from template_filters import digits_only, format_datetime_brazil
from time_utils import now_in_brazil, utcnow

from app import (
    _build_delivery_research_contact_map,
    _build_delivery_research_contacts,
    _build_loja_query,
    _build_missing_tutor_geocodes,
    _build_tutor_map_data,
    _commit_delivery_research_contact_changes,
    _concluir_entrega_efeitos,
    _connected_mercadopago_account_for_order,
    _delivery_context_for_current_user,
    _delivery_error_response,
    _delivery_research_contact_table_available,
    _delivery_research_food_label_for_type,
    _delivery_sections_payload,
    _export_data_share_logs_csv,
    _export_data_share_logs_pdf,
    _get_or_create_delivery_research_contact,
    _get_vendedores_ativos,
    _mp_auto_return_enabled,
    _normalize_external_payment_status,
    _order_checkout_total,
    _order_vendor_shipping,
    _parse_mp_datetime,
    _reprice_order_items,
    _resolve_health_onboarding,
    _setup_checkout_form,
    _shipping_items_for_preference,
    _sync_delivery_research_answers_to_racoes,
    _sync_health_subscription_from_onboarding,
    _sync_orcamento_payment_classification,
    _sync_veterinarian_membership_payment,
    _wants_json_response,
    address_geocode_queue,
    avisar_admin_nova_solicitacao,
    formatar_telefone,
    list_rations,
    registrar_feedback_solicitacao,
)

bp = Blueprint("loja_routes", __name__)


def get_blueprint():
    return bp


def _is_admin():
    import app as app_module

    return app_module._is_admin()


def mp_sdk(*args, **kwargs):
    import app as app_module

    return app_module.mp_sdk(*args, **kwargs)


def upload_to_s3(*args, **kwargs):
    import app as app_module

    return app_module.upload_to_s3(*args, **kwargs)


def verify_mp_signature(*args, **kwargs):
    import app as app_module

    return app_module.verify_mp_signature(*args, **kwargs)


def _get_current_order(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app._get_current_order.
    import app as app_module
    return app_module._get_current_order(*args, **kwargs)


def _mercadopago_notification_url(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app._mercadopago_notification_url.
    import app as app_module
    return app_module._mercadopago_notification_url(*args, **kwargs)


def CheckoutForm(*args, **kwargs):
    import app as app_module

    return app_module.CheckoutForm(*args, **kwargs)


def _run_whatsapp_batch_selenium(*args, **kwargs):
    import app as app_module

    return app_module._run_whatsapp_batch_selenium(*args, **kwargs)


@bp.route("/relatorio/racoes/pesquisa", methods=["GET"])
@login_required
def pesquisa_racoes_tutores():
    if not _is_admin():
        abort(403)

    contatos = _build_delivery_research_contacts()
    racao_options = [
        {
            "id": tipo.id,
            "label": _delivery_research_food_label_for_type(tipo),
        }
        for tipo in list_rations()
        if _delivery_research_food_label_for_type(tipo)
    ]
    status_disponivel = contatos[0]["status_disponivel"] if contatos else _delivery_research_contact_table_available()
    stage_counts = {
        "pending": 0,
        "sent": 0,
        "replied": 0,
        "recorded": 0,
        "do_not_send": 0,
    }
    for item in contatos:
        stage_counts[item["stage"]] += 1
    if not status_disponivel:
        flash(
            "A pesquisa foi carregada, mas o controle de envio ainda depende da nova migração do banco.",
            "warning",
        )

    return render_template(
        "loja/pesquisa_racoes_tutores.html",
        contatos=contatos,
        racao_options=racao_options,
        status_disponivel=status_disponivel,
        stage_counts=stage_counts,
    )


@bp.route("/relatorio/racoes/pesquisa/<int:tutor_id>/toggle", methods=["POST"])
@login_required
def toggle_pesquisa_racoes_tutor(tutor_id):
    if not _is_admin():
        abort(403)

    if not _delivery_research_contact_table_available():
        flash(
            "O controle de envio ainda não está disponível porque a migração do banco não foi aplicada.",
            "warning",
        )
        return redirect(url_for("pesquisa_racoes_tutores"))

    tutor = User.query.get_or_404(tutor_id)
    status = _get_or_create_delivery_research_contact(tutor.id)

    if status.sent:
        status.sent = False
        status.sent_at = None
        status.sent_by_id = None
        status.do_not_send = False
        status.do_not_send_at = None
        status.do_not_send_by_id = None
        status.replied = False
        status.replied_at = None
        status.replied_by_id = None
        status.recorded = False
        status.recorded_at = None
        status.recorded_by_id = None
        flash(f"Envio para {tutor.name} desmarcado.", "info")
    else:
        status.do_not_send = False
        status.do_not_send_at = None
        status.do_not_send_by_id = None
        status.sent = True
        status.sent_at = utcnow()
        status.sent_by_id = current_user.id
        flash(f"Envio para {tutor.name} marcado como realizado.", "success")

    _commit_delivery_research_contact_changes(tutor.id)
    return redirect(url_for("pesquisa_racoes_tutores"))


@bp.route("/relatorio/racoes/pesquisa/<int:tutor_id>/status/<status_key>", methods=["POST"])
@login_required
def update_pesquisa_racoes_tutor_status(tutor_id, status_key):
    if not _is_admin():
        abort(403)

    if status_key not in {"sent", "replied", "recorded", "do_not_send"}:
        abort(400)

    if not _delivery_research_contact_table_available():
        flash(
            "O controle de status ainda não está disponível porque a migração do banco não foi aplicada.",
            "warning",
        )
        return redirect(url_for("pesquisa_racoes_tutores"))

    tutor = User.query.get_or_404(tutor_id)
    status = _get_or_create_delivery_research_contact(tutor.id)

    now = utcnow()

    if status_key == "do_not_send":
        if status.do_not_send:
            status.do_not_send = False
            status.do_not_send_at = None
            status.do_not_send_by_id = None
            flash(f"{tutor.name} voltou para a fila normal da pesquisa.", "info")
        else:
            status.do_not_send = True
            status.do_not_send_at = now
            status.do_not_send_by_id = current_user.id
            flash(f"{tutor.name} foi separado na lista de nao enviar agora.", "success")

    elif status_key == "sent":
        if status.sent:
            status.sent = False
            status.sent_at = None
            status.sent_by_id = None
            status.do_not_send = False
            status.do_not_send_at = None
            status.do_not_send_by_id = None
            status.replied = False
            status.replied_at = None
            status.replied_by_id = None
            status.recorded = False
            status.recorded_at = None
            status.recorded_by_id = None
            flash(f"Status de envio removido para {tutor.name}.", "info")
        else:
            status.do_not_send = False
            status.do_not_send_at = None
            status.do_not_send_by_id = None
            status.sent = True
            status.sent_at = now
            status.sent_by_id = current_user.id
            flash(f"{tutor.name} movido para a fila de enviados.", "success")

    elif status_key == "replied":
        if status.replied:
            status.replied = False
            status.replied_at = None
            status.replied_by_id = None
            status.recorded = False
            status.recorded_at = None
            status.recorded_by_id = None
            flash(f"Resposta de {tutor.name} desmarcada.", "info")
        else:
            status.do_not_send = False
            status.do_not_send_at = None
            status.do_not_send_by_id = None
            if not status.sent:
                status.sent = True
                status.sent_at = status.sent_at or now
                status.sent_by_id = status.sent_by_id or current_user.id
            status.replied = True
            status.replied_at = now
            status.replied_by_id = current_user.id
            flash(f"{tutor.name} movido para a fila de respostas recebidas.", "success")

    elif status_key == "recorded":
        if status.recorded:
            status.recorded = False
            status.recorded_at = None
            status.recorded_by_id = None
            flash(f"Cadastro das respostas de {tutor.name} desmarcado.", "info")
        else:
            status.do_not_send = False
            status.do_not_send_at = None
            status.do_not_send_by_id = None
            if not status.sent:
                status.sent = True
                status.sent_at = status.sent_at or now
                status.sent_by_id = status.sent_by_id or current_user.id
            if not status.replied:
                status.replied = True
                status.replied_at = status.replied_at or now
                status.replied_by_id = status.replied_by_id or current_user.id
            status.recorded = True
            status.recorded_at = now
            status.recorded_by_id = current_user.id
            flash(f"{tutor.name} movido para a fila de respostas cadastradas.", "success")

    _commit_delivery_research_contact_changes(tutor.id)
    return redirect(url_for("pesquisa_racoes_tutores"))


@bp.route("/relatorio/racoes/pesquisa/<int:tutor_id>/answers", methods=["POST"])
@login_required
def save_pesquisa_racoes_tutor_answers(tutor_id):
    if not _is_admin():
        abort(403)

    if not _delivery_research_contact_table_available():
        flash(
            "O registro estruturado ainda nao esta disponivel porque a migracao do banco nao foi aplicada.",
            "warning",
        )
        return redirect(url_for("pesquisa_racoes_tutores"))

    tutor = User.query.get_or_404(tutor_id)
    status = _get_or_create_delivery_research_contact(tutor.id)

    now = utcnow()
    selected_tipo_racao_id = request.form.get("current_food_tipo_racao_id")
    selected_tipo_racao = None
    if str(selected_tipo_racao_id or "").isdigit():
        selected_tipo_racao = TipoRacao.query.get(int(selected_tipo_racao_id))

    manual_current_food = (request.form.get("current_food") or "").strip()
    resolved_current_food = manual_current_food or None
    if selected_tipo_racao is not None:
        resolved_current_food = _delivery_research_food_label_for_type(selected_tipo_racao)

    status.response_collected_at = now
    status.do_not_send = False
    status.do_not_send_at = None
    status.do_not_send_by_id = None
    status.interest_answer = (request.form.get("interest_answer") or "").strip() or None
    status.current_food = resolved_current_food
    status.bag_size = (request.form.get("bag_size") or "").strip() or None
    status.price_paid = (request.form.get("price_paid") or "").strip() or None
    status.purchase_channel = (request.form.get("purchase_channel") or "").strip() or None
    status.duration_estimate = (request.form.get("duration_estimate") or "").strip() or None
    status.response_notes = (request.form.get("response_notes") or "").strip() or None

    if not status.sent:
        status.sent = True
        status.sent_at = status.sent_at or now
        status.sent_by_id = status.sent_by_id or current_user.id
    if not status.replied:
        status.replied = True
        status.replied_at = status.replied_at or now
        status.replied_by_id = status.replied_by_id or current_user.id
    if not status.recorded:
        status.recorded = True
        status.recorded_at = now
        status.recorded_by_id = current_user.id
    else:
        status.recorded_at = now
        status.recorded_by_id = current_user.id

    synced_count = _sync_delivery_research_answers_to_racoes(
        tutor,
        status,
        request.form.getlist("sync_animal_ids"),
    )

    db.session.commit()
    flash(
        f"Respostas estruturadas de {tutor.name} salvas com sucesso. {synced_count} pet(s) sincronizado(s) com o historico de racoes.",
        "success",
    )
    return redirect(url_for("pesquisa_racoes_tutores"))


@bp.route("/relatorio/racoes/pesquisa/send-selected", methods=["POST"])
@login_required
def send_selected_pesquisa_racoes_tutores():
    if not _is_admin():
        abort(403)

    selected_ids = []
    for raw in request.form.getlist("selected_tutor_ids"):
        if str(raw).isdigit():
            selected_ids.append(int(raw))

    if not selected_ids:
        flash("Selecione ao menos um tutor para envio em lote.", "warning")
        return redirect(url_for("pesquisa_racoes_tutores"))

    contact_map = _build_delivery_research_contact_map()
    batch_items = []
    skipped = 0
    excluded = 0
    for tutor_id in selected_ids:
        item = contact_map.get(tutor_id)
        if not item or not item.get("whatsapp_url"):
            skipped += 1
            continue
        status_envio = item.get("status_envio")
        if status_envio and getattr(status_envio, "do_not_send", False):
            excluded += 1
            continue

        tutor = item["tutor"]
        batch_items.append(
            {
                "tutor_id": tutor.id,
                "tutor_name": tutor.name,
                "phone": digits_only(formatar_telefone(tutor.phone or "")),
                "message": item["mensagem"],
            }
        )

    if not batch_items:
        if excluded and not skipped:
            flash("Os tutores selecionados estao marcados como nao enviar agora.", "warning")
        else:
            flash("Nenhum dos tutores selecionados possui WhatsApp valido para envio.", "warning")
        return redirect(url_for("pesquisa_racoes_tutores"))

    whatsapp_runner = getattr(sys.modules.get("app", sys.modules[__name__]), "_run_whatsapp_batch_selenium", _run_whatsapp_batch_selenium)

    try:
        result_payload = whatsapp_runner(batch_items)
    except subprocess.TimeoutExpired:
        flash("O envio em lote demorou mais que o esperado e foi interrompido.", "danger")
        return redirect(url_for("pesquisa_racoes_tutores"))
    except Exception as exc:
        current_app.logger.exception("Erro ao executar envio em lote via Selenium")
        message = str(exc)
        if "DevToolsActivePort" in message or "session not created" in message.lower():
            message = (
                "Nao foi possivel abrir o navegador da automacao. "
                "Feche janelas abertas do Chrome e do Edge que possam estar usando o perfil do WhatsApp "
                "e tente novamente."
            )
        flash(f"Falha ao executar envio em lote: {message}", "danger")
        return redirect(url_for("pesquisa_racoes_tutores"))

    success_count = 0
    failed_count = 0
    failed_examples = []
    for result in result_payload.get("results", []):
        tutor_id = result.get("tutor_id")
        if not tutor_id:
            continue
        if result.get("status") == "sent" and _delivery_research_contact_table_available():
            status = _get_or_create_delivery_research_contact(tutor_id)
            status.sent = True
            status.sent_at = utcnow()
            status.sent_by_id = current_user.id
            success_count += 1
        else:
            failed_count += 1
            if len(failed_examples) < 3:
                failed_examples.append(
                    {
                        "name": result.get("tutor_name") or f"Tutor {tutor_id}",
                        "error": (result.get("error") or "Falha nao detalhada.")[:180],
                    }
                )

    if success_count:
        db.session.commit()

    summary = f"Envio em lote concluido: {success_count} enviado(s)"
    if failed_count:
        summary += f", {failed_count} com falha"
    if skipped:
        summary += f", {skipped} sem WhatsApp valido"
    if excluded:
        summary += f", {excluded} em nao enviar agora"
    flash(summary + ".", "success" if success_count else "warning")

    for failure in failed_examples:
        flash(f"Falha em {failure['name']}: {failure['error']}", "warning")

    process_error = result_payload.get("process_error")
    if process_error:
        flash(
            "O lote foi interrompido no meio do processo, mas os envios ja confirmados foram preservados. "
            "Revise os que faltaram antes de reenviar.",
            "warning",
        )
    return redirect(url_for("pesquisa_racoes_tutores"))


@bp.route("/relatorio/racoes/pesquisa/warmup-whatsapp", methods=["POST"])
@login_required
def warmup_pesquisa_racoes_whatsapp():
    if not _is_admin():
        abort(403)

    try:
        result_payload = _run_whatsapp_batch_selenium([], warmup_only=True)
    except subprocess.TimeoutExpired:
        flash("O aquecimento do WhatsApp demorou mais que o esperado e foi interrompido.", "danger")
        return redirect(url_for("pesquisa_racoes_tutores"))
    except Exception as exc:
        current_app.logger.exception("Erro ao aquecer WhatsApp Web via Selenium")
        flash(f"Falha ao aquecer WhatsApp Web: {exc}", "danger")
        return redirect(url_for("pesquisa_racoes_tutores"))

    browser_used = result_payload.get("browser") or "navegador"
    flash(
        f"WhatsApp Web aquecido com sucesso no {browser_used}. Se a sessao pedir QR Code, conecte agora antes do envio em lote.",
        "success",
    )
    return redirect(url_for("pesquisa_racoes_tutores"))


@bp.route("/orders/new", methods=["GET", "POST"])
@login_required
def create_order():
    if current_user.worker != 'delivery':
        abort(403)

    order_id = session.get('current_order')
    if order_id:
        order = Order.query.get_or_404(order_id)
    else:
        order = Order(user_id=current_user.id)
        db.session.add(order)
        db.session.commit()
        session['current_order'] = order.id

    form = OrderItemForm()
    delivery_form = DeliveryRequestForm()

    if form.validate_on_submit():
        item = OrderItem(order_id=order.id,
                         item_name=form.item_name.data,
                         quantity=form.quantity.data)
        db.session.add(item)
        db.session.commit()
        flash('Item adicionado ao pedido.', 'success')
        return redirect(url_for('create_order'))

    total_quantity = sum(i.quantity for i in order.items)
    return render_template(
        'loja/create_order.html',
        form=form,
        delivery_form=delivery_form,
        order=order,
        total_quantity=total_quantity,
    )


@bp.route("/orders/<int:order_id>/request_delivery", methods=["POST"])
@login_required
def request_delivery(order_id):
    if current_user.worker != 'delivery':      # só entregadores podem solicitar
        abort(403)

    order = Order.query.get_or_404(order_id)

    # ─── 1. escolher um ponto de retirada ────────────────────────────────
    # Hoje: pega o primeiro ponto ATIVO
    pickup = (
        PickupLocation.query
        .filter_by(ativo=True)
        .first()
    )

    if pickup is None:
        default_addr = current_app.config.get("DEFAULT_PICKUP_ADDRESS")
        if default_addr:
            flash(f'Usando endereço de retirada padrão: {default_addr}', 'info')
        else:
            flash('Nenhum ponto de retirada cadastrado/ativo.', 'danger')
            return redirect(url_for('list_delivery_requests'))

    # ─── 2. criar a DeliveryRequest já com o pickup_id ───────────────────
    req = DeliveryRequest(
        order_id        = order.id,
        requested_by_id = current_user.id,
        status          = 'pendente',
        pickup          = pickup         # 🔑 chave aqui!
    )

    db.session.add(req)
    db.session.commit()

    session.pop('current_order', None)
    flash('Solicitação de entrega gerada.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Solicitação de entrega gerada.', category='success')
    return redirect(url_for('list_delivery_requests'))


@bp.route("/delivery_requests", methods=["GET"])
@login_required
def list_delivery_requests():
    """
    •  Entregador → até 3 pendentes (mais antigas primeiro) + as dele
    •  Cliente    → só pedidos que ele criou
    """
    context, counts = _delivery_context_for_current_user()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html, counts, _ = _delivery_sections_payload()
        return jsonify(html=html, counts=counts)

    return render_template("entregas/delivery_requests.html", **context)


@bp.route("/admin/delivery/<int:req_id>", methods=["GET"])
@login_required
def admin_delivery_detail(req_id):
    # se quiser, mantenha restrição de admin aqui
    if not _is_admin():
        abort(403)
    return redirect(url_for("delivery_detail", req_id=req_id))


@bp.route("/worker/delivery/<int:req_id>", methods=["GET"])
@login_required
def worker_delivery_detail(req_id):
    # garante que o usuário é entregador e dono da entrega
    if current_user.worker != "delivery":
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    if req.worker_id and req.worker_id != current_user.id:
        abort(403)
    return redirect(url_for("delivery_detail", req_id=req_id))


@bp.route("/delivery_requests/<int:req_id>/accept", methods=["POST"])
@login_required
def accept_delivery(req_id):
    try:
        if current_user.worker != 'delivery':
            return _delivery_error_response('Apenas entregadores podem realizar esta ação.', 'danger', 403)
        req = (
            DeliveryRequest.query
            .filter_by(id=req_id)
            .with_for_update()
            .first()
        )
        if not req:
            abort(404)
        if req.status != 'pendente':
            return _delivery_error_response('Solicitação não disponível.', 'warning', 400)
        if req.worker_id and req.worker_id != current_user.id:
            return _delivery_error_response('Entrega já aceita por outro entregador.', 'warning', 409)
        req.status = 'em_andamento'
        req.worker_id = current_user.id
        req.accepted_at = utcnow()
        db.session.commit()
        flash('Entrega aceita.', 'success')
        if _wants_json_response():
            html, counts, _ = _delivery_sections_payload()
            response_data = {
                'message': 'Entrega aceita.',
                'category': 'success',
                'redirect': url_for('worker_delivery_detail', req_id=req.id),
                'html': html,
                'counts': counts,
            }
            return jsonify(**response_data)
        # ⬇️ redireciona direto ao detalhe unificado
        return redirect(url_for('delivery_detail', req_id=req.id))
    except CSRFError:
        db.session.rollback()
        return _delivery_error_response('Falha de validação. Recarregue a página e tente novamente.', 'warning', 400)
    except Exception as exc:  # pragma: no cover - segurança extra
        db.session.rollback()
        current_app.logger.exception('Erro ao aceitar entrega', exc_info=exc)
        return _delivery_error_response('Erro interno ao processar a entrega.', 'danger', 500)


@bp.route("/delivery_requests/<int:req_id>/complete", methods=["POST"])
@login_required
def complete_delivery(req_id):
    try:
        if current_user.worker != 'delivery':
            return _delivery_error_response('Apenas entregadores podem realizar esta ação.', 'danger', 403)
        req = DeliveryRequest.query.get_or_404(req_id)
        if req.worker_id != current_user.id:
            return _delivery_error_response('Você não pode concluir esta entrega.', 'danger', 403)
        req.status = 'concluida'
        req.completed_at = utcnow()
        _concluir_entrega_efeitos(req)
        db.session.commit()
        flash('Entrega concluída.', 'success')
        if _wants_json_response():
            html, counts, _ = _delivery_sections_payload()
            response_data = {'message': 'Entrega concluída.', 'category': 'success', 'redirect': None, 'html': html, 'counts': counts}
            return jsonify(**response_data)
        return redirect(url_for('list_delivery_requests'))
    except CSRFError:
        db.session.rollback()
        return _delivery_error_response('Falha de validação. Recarregue a página e tente novamente.', 'warning', 400)
    except Exception as exc:  # pragma: no cover - segurança extra
        db.session.rollback()
        current_app.logger.exception('Erro ao concluir entrega', exc_info=exc)
        return _delivery_error_response('Erro interno ao processar a entrega.', 'danger', 500)


@bp.route("/delivery_requests/<int:req_id>/cancel", methods=["POST"])
@login_required
def cancel_delivery(req_id):
    try:
        if current_user.worker != 'delivery':
            return _delivery_error_response('Apenas entregadores podem realizar esta ação.', 'danger', 403)
        req = DeliveryRequest.query.get_or_404(req_id)
        if req.worker_id != current_user.id:
            return _delivery_error_response('Você não pode cancelar esta entrega.', 'danger', 403)
        req.status = 'cancelada'
        req.canceled_at = utcnow()
        req.canceled_by_id = current_user.id
        db.session.commit()
        flash('Entrega cancelada.', 'info')
        if _wants_json_response():
            html, counts, _ = _delivery_sections_payload()
            response_data = {'message': 'Entrega cancelada.', 'category': 'info', 'redirect': None, 'html': html, 'counts': counts}
            return jsonify(**response_data)
        return redirect(url_for('list_delivery_requests'))
    except CSRFError:
        db.session.rollback()
        return _delivery_error_response('Falha de validação. Recarregue a página e tente novamente.', 'warning', 400)
    except Exception as exc:  # pragma: no cover - segurança extra
        db.session.rollback()
        current_app.logger.exception('Erro ao cancelar entrega', exc_info=exc)
        return _delivery_error_response('Erro interno ao processar a entrega.', 'danger', 500)


@bp.route("/delivery_requests/<int:req_id>/buyer_cancel", methods=["POST"])
@login_required
def buyer_cancel_delivery(req_id):
    try:
        req = DeliveryRequest.query.get_or_404(req_id)
        if req.requested_by_id != current_user.id:
            return _delivery_error_response('Você não pode cancelar esta entrega.', 'danger', 403)
        if req.status in ['concluida', 'cancelada']:
            return _delivery_error_response('Não é possível cancelar.', 'warning', 400)
        req.status = 'cancelada'
        req.canceled_at = utcnow()
        req.canceled_by_id = current_user.id
        db.session.commit()
        flash('Solicitação cancelada.', 'info')
        if _wants_json_response():
            html, counts, _ = _delivery_sections_payload()
            return jsonify(message='Solicitação cancelada.', category='info', redirect=None, html=html, counts=counts)
        return redirect(url_for('loja'))
    except CSRFError:
        db.session.rollback()
        return _delivery_error_response('Falha de validação. Recarregue a página e tente novamente.', 'warning', 400)
    except Exception as exc:  # pragma: no cover - segurança extra
        db.session.rollback()
        current_app.logger.exception('Erro ao cancelar entrega pelo comprador', exc_info=exc)
        return _delivery_error_response('Erro interno ao processar a entrega.', 'danger', 500)


@bp.route("/delivery/<int:req_id>", methods=["GET"])
@login_required
def delivery_detail(req_id):
    """Detalhe da entrega para admin, entregador ou comprador."""
    req = (
        DeliveryRequest.query
        .options(
            joinedload(DeliveryRequest.pickup).joinedload(PickupLocation.endereco),
            joinedload(DeliveryRequest.order).joinedload(Order.user),
            joinedload(DeliveryRequest.worker),
        )
        .get_or_404(req_id)
    )

    order = req.order
    buyer = order.user
    items = order.items
    total = sum(i.quantity * i.product.price for i in items if i.product)

    if _is_admin():
        role = "admin"
    elif current_user.worker == "delivery":
        if req.worker_id and req.worker_id != current_user.id:
            abort(403)
        role = "worker"
    elif current_user.id == buyer.id:
        role = "buyer"
    else:
        abort(403)

    wants_json = 'application/json' in request.headers.get('Accept', '')

    def _status_label_and_class(status):
        mapping = {
            'pendente': ('Pendente', 'bg-warning text-dark'),
            'em_andamento': ('Em andamento', 'bg-info'),
            'concluida': ('Concluída', 'bg-success'),
            'cancelada': ('Cancelada', 'bg-danger'),
        }
        return mapping.get(status, (status.capitalize(), 'bg-secondary'))

    if wants_json:
        label, badge_class = _status_label_and_class(req.status or '')
        timeline = []
        if req.requested_at:
            timeline.append({
                'key': 'requested_at',
                'label': 'Solicitado',
                'timestamp': format_datetime_brazil(req.requested_at),
            })
        if req.accepted_at:
            timeline.append({
                'key': 'accepted_at',
                'label': 'Aceito',
                'timestamp': format_datetime_brazil(req.accepted_at),
            })
        if req.completed_at:
            timeline.append({
                'key': 'completed_at',
                'label': 'Concluído',
                'timestamp': format_datetime_brazil(req.completed_at),
            })
        if req.canceled_at:
            timeline.append({
                'key': 'canceled_at',
                'label': 'Cancelado',
                'timestamp': format_datetime_brazil(req.canceled_at),
                'is_cancel': True,
            })
        worker_data = None
        if req.worker:
            worker_data = {
                'id': req.worker.id,
                'name': req.worker.name,
                'email': req.worker.email,
            }
        return jsonify({
            'success': True,
            'status': req.status,
            'status_label': label,
            'badge_class': badge_class,
            'timeline': timeline,
            'worker': worker_data,
        })

    label, badge_class = _status_label_and_class(req.status or '')

    return render_template(
        "entregas/delivery_detail.html",
        req=req,
        order=order,
        items=items,
        buyer=buyer,
        delivery_worker=req.worker,
        total=total,
        role=role,
        status_label=label,
        status_badge_class=badge_class,
    )


@bp.route("/admin/mapa_tutores", methods=["GET"])
@login_required
def admin_tutor_map():
    if not _is_admin():
        abort(403)

    map_data = _build_tutor_map_data()

    return render_template('admin/tutor_map.html', **map_data)


@bp.route("/admin/api/tutor_markers", methods=["GET"])
@login_required
def admin_tutor_markers_api():
    if not _is_admin():
        abort(403)

    return jsonify(_build_tutor_map_data())


@bp.route("/admin/api/geocode_addresses", methods=["POST"])
@login_required
def admin_geocode_addresses():
    if not _is_admin():
        abort(403)

    started = address_geocode_queue.start()
    status = address_geocode_queue.status()
    status['missing_tutors'] = _build_missing_tutor_geocodes()
    return jsonify({'started': started, 'status': status}), (202 if started else 200)


@bp.route("/admin/api/geocode_addresses/status", methods=["GET"])
@login_required
def admin_geocode_status():
    if not _is_admin():
        abort(403)

    status = address_geocode_queue.status()
    status['missing_tutors'] = _build_missing_tutor_geocodes()

    return jsonify(status)


@bp.route("/admin/delivery_overview", methods=["GET"])
@login_required
def delivery_overview():
    if not _is_admin():
        abort(403)

    # eager‑loading: DeliveryRequest ➜ Order ➜ User + Items + Product
    base_q = (
        DeliveryRequest.query.filter_by(archived=False)
        .options(
            joinedload(DeliveryRequest.order)
                .joinedload(Order.user),                       # comprador
            joinedload(DeliveryRequest.order)
                .joinedload(Order.items)
                .joinedload(OrderItem.product)                 # itens + produtos
        )
        .order_by(DeliveryRequest.id.desc())
    )

    per_page = 10
    open_page = request.args.get('open_page', 1, type=int)
    progress_page = request.args.get('progress_page', 1, type=int)
    completed_page = request.args.get('completed_page', 1, type=int)
    canceled_page = request.args.get('canceled_page', 1, type=int)

    open_pagination = (
        base_q.filter_by(status="pendente")
              .paginate(page=open_page, per_page=per_page, error_out=False)
    )
    progress_pagination = (
        base_q.filter_by(status="em_andamento")
              .paginate(page=progress_page, per_page=per_page, error_out=False)
    )
    completed_pagination = (
        base_q.filter_by(status="concluida")
              .paginate(page=completed_page, per_page=per_page, error_out=False)
    )
    canceled_pagination = (
        base_q.filter_by(status="cancelada")
              .paginate(page=canceled_page, per_page=per_page, error_out=False)
    )

    open_requests = open_pagination.items
    in_progress   = progress_pagination.items
    completed     = completed_pagination.items
    canceled      = canceled_pagination.items

    # produtos para o bloco de estoque
    products = Product.query.order_by(Product.name).all()

    return render_template(
        "admin/delivery_overview.html",
        products      = products,
        open_requests = open_requests,
        in_progress   = in_progress,
        completed     = completed,
        canceled      = canceled,
        open_pagination = open_pagination,
        progress_pagination = progress_pagination,
        completed_pagination = completed_pagination,
        canceled_pagination = canceled_pagination,
        open_page = open_page,
        progress_page = progress_page,
        completed_page = completed_page,
        canceled_page = canceled_page,
    )


@bp.route("/admin/delivery_requests/<int:req_id>/status/<status>", methods=["POST"])
@login_required
def admin_set_delivery_status(req_id, status):
    if not _is_admin():
        abort(403)

    allowed = ['pendente', 'em_andamento', 'concluida', 'cancelada']
    if status not in allowed:
        abort(400)

    req = DeliveryRequest.query.get_or_404(req_id)
    now = utcnow()
    req.status = status

    if status == 'pendente':
        req.worker_id = None
        req.accepted_at = None
        req.canceled_at = None
        req.canceled_by_id = None
        req.completed_at = None
    elif status == 'em_andamento':
        if not req.accepted_at:
            req.accepted_at = now

        req.canceled_at = None
        req.canceled_by_id = None
        req.completed_at = None
    elif status == 'concluida':
        if not req.completed_at:
            req.completed_at = now
        if not req.accepted_at:
            req.accepted_at = now
        req.canceled_at = None
        req.canceled_by_id = None
        _concluir_entrega_efeitos(req)

    elif status == 'cancelada':
        req.canceled_at = now
        req.canceled_by_id = current_user.id
        req.completed_at = None

    db.session.commit()
    flash('Status atualizado.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Status atualizado.', category='success', status=status)
    return redirect(url_for('delivery_overview'))


@bp.route("/admin/delivery_requests/<int:req_id>/delete", methods=["POST"])
@login_required
def admin_delete_delivery(req_id):
    if not _is_admin():
        abort(403)

    req = DeliveryRequest.query.get_or_404(req_id)
    db.session.delete(req)
    db.session.commit()
    flash('Entrega excluída.', 'info')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega excluída.', category='info', deleted=True)
    return redirect(url_for('delivery_overview'))


@bp.route("/admin/delivery_requests/<int:req_id>/archive", methods=["POST"])
@login_required
def admin_archive_delivery(req_id):
    if not _is_admin():
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    req.archived = True
    db.session.commit()
    flash('Entrega arquivada.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega arquivada.', category='success', archived=True)
    return redirect(url_for('delivery_overview'))


@bp.route("/admin/delivery_requests/<int:req_id>/unarchive", methods=["POST"])
@login_required
def admin_unarchive_delivery(req_id):
    if not _is_admin():
        abort(403)
    req = DeliveryRequest.query.get_or_404(req_id)
    req.archived = False
    db.session.commit()
    flash('Entrega desarquivada.', 'success')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(message='Entrega desarquivada.', category='success', archived=False)
    return redirect(url_for('delivery_archive'))


@bp.route("/admin/delivery_archive", methods=["GET"])
@login_required
def delivery_archive():
    if not _is_admin():
        abort(403)

    reqs = (
        DeliveryRequest.query.filter_by(archived=True)
        .options(
            joinedload(DeliveryRequest.order)
                .joinedload(Order.user),
            joinedload(DeliveryRequest.order)
                .joinedload(Order.items)
                .joinedload(OrderItem.product)
        )
        .order_by(DeliveryRequest.id.desc())
        .all()
    )

    return render_template('admin/delivery_archive_admin.html', requests=reqs)


@bp.route("/admin/data-share-logs", methods=["GET"])
@login_required
def admin_data_share_logs():
    if not _is_admin():
        abort(403)

    query = (
        DataShareLog.query.options(
            joinedload(DataShareLog.access).joinedload(DataShareAccess.user),
            joinedload(DataShareLog.access).joinedload(DataShareAccess.source_clinic),
            joinedload(DataShareLog.actor),
        )
        .join(DataShareAccess)
    )

    clinic_id = request.args.get('clinic_id', type=int)
    tutor_id = request.args.get('tutor_id', type=int)
    actor_id = request.args.get('actor_id', type=int)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    if clinic_id:
        query = query.filter(DataShareAccess.source_clinic_id == clinic_id)
    if tutor_id:
        query = query.filter(DataShareAccess.user_id == tutor_id)
    if actor_id:
        query = query.filter(DataShareLog.actor_id == actor_id)

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(DataShareLog.occurred_at >= start_dt)
        except ValueError:
            start_dt = None
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(DataShareLog.occurred_at < end_dt)
        except ValueError:
            end_dt = None

    filters = {
        'clinic_id': clinic_id or '',
        'tutor_id': tutor_id or '',
        'actor_id': actor_id or '',
        'start_date': start_date or '',
        'end_date': end_date or '',
    }
    query_args = {k: v for k, v in filters.items() if v not in ('', None)}
    csv_args = dict(query_args, format='csv')
    pdf_args = dict(query_args, format='pdf')

    export_format = request.args.get('format')
    total = query.count()
    ordered = query.order_by(DataShareLog.occurred_at.desc())

    if export_format in {'csv', 'pdf'}:
        logs = ordered.all()
        if export_format == 'csv':
            return _export_data_share_logs_csv(logs)
        return _export_data_share_logs_pdf(logs)

    logs = ordered.limit(500).all()
    return render_template(
        'admin/data_share_logs.html',
        logs=logs,
        total=total,
        filters=filters,
        query_args=query_args,
        csv_args=csv_args,
        pdf_args=pdf_args,
    )


@bp.route("/delivery_archive", methods=["GET"])
@login_required
def delivery_archive_user():
    base = (
        DeliveryRequest.query.filter_by(archived=True)
        .options(
            joinedload(DeliveryRequest.order).joinedload(Order.user)
        )
        .order_by(DeliveryRequest.id.desc())
    )
    if current_user.worker == "delivery":
        reqs = base.filter_by(worker_id=current_user.id).all()
    else:
        reqs = base.filter_by(requested_by_id=current_user.id).all()
    return render_template('entregas/delivery_archive.html', requests=reqs)


@bp.route("/loja", methods=["GET"])
@login_required
def loja():
    pagamento_pendente = None
    payment_id = session.get("last_pending_payment")
    if payment_id:
        payment = Payment.query.get(payment_id)
        if payment and payment.status.name == "PENDING":
            pagamento_pendente = payment

    search_term = request.args.get("q", "").strip()
    filtro = request.args.get("filter", "all")
    vendedor = request.args.get("vendedor", "").strip()
    categoria = request.args.get("category", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 12

    query = _build_loja_query(search_term, filtro, vendedor, categoria)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    produtos = pagination.items
    form = AddToCartForm()

    has_orders = Order.query.filter_by(user_id=current_user.id).first() is not None
    minha_clinica = Clinica.query.filter_by(owner_id=current_user.id).first()
    vendedores = _get_vendedores_ativos()

    return render_template(
        "loja/loja.html",
        products=produtos,
        pagination=pagination,
        pagamento_pendente=pagamento_pendente,
        form=form,
        has_orders=has_orders,
        selected_filter=filtro,
        search_term=search_term,
        minha_clinica=minha_clinica,
        vendedores=vendedores,
        selected_vendedor=vendedor,
        categories=get_active_product_categories(),
        selected_category=categoria,
    )


@bp.route("/loja/data", methods=["GET"])
@login_required
def loja_data():
    search_term = request.args.get("q", "").strip()
    filtro = request.args.get("filter", "all")
    vendedor = request.args.get("vendedor", "").strip()
    categoria = request.args.get("category", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 12

    query = _build_loja_query(search_term, filtro, vendedor, categoria)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    produtos = pagination.items
    form = AddToCartForm()

    if request.args.get("format") == "json":
        products_data = [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price": p.price,
                "image_url": p.image_url,
            }
            for p in produtos
        ]
        return jsonify(
            products=products_data,
            page=pagination.page,
            total_pages=pagination.pages,
            has_next=pagination.has_next,
            has_prev=pagination.has_prev,
        )

    html = render_template(
        "partials/_product_grid.html",
        products=produtos,
        pagination=pagination,
        form=form,
        selected_filter=filtro,
        search_term=search_term,
        selected_vendedor=vendedor,
    )
    return html


@bp.route("/produto/<int:product_id>", methods=["GET", "POST"])
@login_required
def produto_detail(product_id):
    """Exibe detalhes do produto e permite edições para administradores."""
    product = Product.query.options(db.joinedload(Product.extra_photos)).get_or_404(product_id)

    update_form = ProductUpdateForm(obj=product, prefix='upd')
    photo_form = ProductPhotoForm(prefix='photo')
    form = AddToCartForm()

    if _is_admin():
        if update_form.validate_on_submit() and update_form.submit.data:
            product.name = update_form.name.data
            product.description = update_form.description.data
            product.price = float(update_form.price.data or 0)
            product.stock = update_form.stock.data
            product.category = update_form.category.data or None
            product.mp_category_id = (update_form.mp_category_id.data or "others").strip()
            product.ncm = (update_form.ncm.data or "").strip() or None
            product.cfop = (update_form.cfop.data or "").strip() or None
            product.cst = (update_form.cst.data or "").strip() or None
            product.csosn = (update_form.csosn.data or "").strip() or None
            product.origem = (update_form.origem.data or "").strip() or None
            product.unidade = (update_form.unidade.data or "").strip() or None
            product.aliquota_icms = update_form.aliquota_icms.data
            product.aliquota_pis = update_form.aliquota_pis.data
            product.aliquota_cofins = update_form.aliquota_cofins.data
            if update_form.image_upload.data:
                file = update_form.image_upload.data
                filename = secure_filename(file.filename)
                image_url = upload_to_s3(file, filename, folder='products')
                if image_url:
                    product.image_url = image_url
            db.session.commit()
            flash('Produto atualizado.', 'success')
            return redirect(url_for('produto_detail', product_id=product.id))

        if photo_form.validate_on_submit() and photo_form.submit.data:
            file = photo_form.image.data
            filename = secure_filename(file.filename)
            image_url = upload_to_s3(file, filename, folder='products')
            if image_url:
                db.session.add(ProductPhoto(product_id=product.id, image_url=image_url))
                db.session.commit()
                flash('Foto adicionada.', 'success')
            return redirect(url_for('produto_detail', product_id=product.id))

    return render_template(
        'loja/product_detail.html',
        product=product,
        update_form=update_form,
        photo_form=photo_form,
        form=form,
        is_admin=_is_admin(),
    )


@bp.route("/carrinho/adicionar/<int:product_id>", methods=["POST"])
@login_required
def adicionar_carrinho(product_id):
    product = Product.query.get(product_id)
    form = AddToCartForm()
    is_ajax = (request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
               'application/json' in request.headers.get('Accept', ''))

    if not product:
        if is_ajax:
            return jsonify(success=False, error='product not found'), 404
        flash("Produto não encontrado.", "warning")
        return redirect(url_for("loja"))

    qty = 1

    if not form.validate_on_submit():
        # Tenta identificar erros comuns do formulário e responder de forma útil
        if form.csrf_token.errors:
            message = "Sua sessão expirou. Recarregue a página e tente novamente."
            if is_ajax:
                return jsonify(success=False, error='invalid csrf', message=message, category="warning"), 400
            flash(message, "warning")
            return redirect(url_for("loja"))

        # Falha apenas na quantidade? Usa fallback seguro ao invés de retornar 400
        try:
            qty = max(1, int(request.form.get("quantity", 1)))
        except (TypeError, ValueError):
            qty = 1
    else:
        qty = form.quantity.data or 1

    order = _get_current_order()
    if not order:
        order = Order(user_id=current_user.id)
        db.session.add(order)
        db.session.commit()
        session["current_order"] = order.id

    # Verifica se o produto já está no carrinho para somar as quantidades
    item = OrderItem.query.filter_by(order_id=order.id, product_id=product.id).first()
    if item:
        item.quantity += qty
    else:
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            item_name=product.name,
            # Preço público (taxa embutida) — é o que o comprador paga.
            unit_price=product.preco_publico or Decimal("0"),
            quantity=qty,
        )
        db.session.add(item)

    db.session.commit()
    flash("Produto adicionado ao carrinho.", "success")
    
    if is_ajax:
        total_value = _order_checkout_total(order)
        total_qty = sum(i.quantity for i in order.items)
        return jsonify(
            success=True,
            message="Produto adicionado ao carrinho.",
            category="success",
            item_id=item.id,
            item_quantity=item.quantity,
            order_total=total_value,
            order_total_formatted=f"R$ {total_value:.2f}",
            order_quantity=total_qty,
        )
    return redirect(url_for("loja"))


@bp.route("/carrinho/increase/<int:item_id>", methods=["POST"])
@login_required
def aumentar_item_carrinho(item_id):
    """Incrementa a quantidade de um item no carrinho."""
    order = _get_current_order()
    item = OrderItem.query.get_or_404(item_id)
    if not order or item.order_id != order.id:
        abort(404)
    item.quantity += 1
    db.session.commit()
    
    wants_json = request.accept_mimetypes.accept_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if wants_json:
        total_value = _order_checkout_total(order)
        total_qty = sum(i.quantity for i in order.items)
        return jsonify(
            message="Quantidade atualizada",
            category="success",
            item_id=item.id,
            item_quantity=item.quantity,
            order_total=total_value,
            order_total_formatted=f"R$ {total_value:.2f}",
            order_quantity=total_qty,
        )
    
    flash("Quantidade atualizada", "success")
    return redirect(url_for("ver_carrinho"))


@bp.route("/carrinho/decrease/<int:item_id>", methods=["POST"])
@login_required
def diminuir_item_carrinho(item_id):
    """Diminui a quantidade de um item; remove se chegar a zero."""
    order = _get_current_order()
    item = OrderItem.query.get_or_404(item_id)
    if not order or item.order_id != order.id:
        abort(404)
    item.quantity -= 1
    if item.quantity <= 0:
        db.session.delete(item)
        db.session.commit()
        message = "Produto removido"
        category = "info"
        item_qty = 0
    else:
        db.session.commit()
        message = "Quantidade atualizada"
        category = "success"
        item_qty = item.quantity
    
    wants_json = request.accept_mimetypes.accept_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if wants_json:
        total_value = _order_checkout_total(order)
        total_qty = sum(i.quantity for i in order.items)
        payload = {
            "message": message,
            "category": category,
            "item_id": item.id,
            "item_quantity": item_qty,
            "order_total": total_value,
            "order_total_formatted": f"R$ {total_value:.2f}",
            "order_quantity": total_qty,
        }
        if total_qty == 0:
            payload["redirect"] = url_for("ver_carrinho")
        return jsonify(**payload)
    
    flash(message, category)
    return redirect(url_for("ver_carrinho"))


@bp.route("/carrinho", methods=["GET", "POST"])
@login_required
def ver_carrinho():
    # 1) Cria o form
    form = CheckoutForm()
    addr_form = CartAddressForm()
    default_address = _setup_checkout_form(form)

    # 2) Verifica se há um pagamento pendente
    pagamento_pendente = None
    payment_id = session.get('last_pending_payment')
    if payment_id:
        pagamento = Payment.query.get(payment_id)
        if pagamento and pagamento.status == PaymentStatus.PENDING:
            pagamento_pendente = pagamento

    # 3) Busca o pedido atual e garante preços vigentes (reprecifica
    #    carrinhos abertos antes de mudanças de precificação)
    order = _get_current_order()
    _reprice_order_items(order)

    # 4) Renderiza o carrinho passando o form
    return render_template(
        'loja/carrinho.html',
        form=form,
        order=order,
        shipping=_order_vendor_shipping(order),
        pagamento_pendente=pagamento_pendente,
        default_address=default_address,
        saved_addresses=current_user.saved_addresses,
        addr_form=addr_form
    )


@bp.route("/carrinho/retomar/<int:order_id>", methods=["GET"])
@login_required
def retomar_carrinho_chatgpt(order_id):
    """Retoma um pedido criado pelo ChatGPT/MCP na sessão web do comprador."""
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        abort(403)
    if order.payment and order.payment.status == PaymentStatus.COMPLETED:
        flash("Este pedido já foi pago.", "info")
        return redirect(url_for("pedido_detail", order_id=order.id))
    session["current_order"] = order.id
    flash("Pedido carregado no carrinho. Revise entrega e pagamento.", "success")
    return redirect(url_for("ver_carrinho"))


@bp.route("/carrinho/salvar_endereco", methods=["POST"])
@login_required
def carrinho_salvar_endereco():
    """Salva um novo endereço informado no carrinho."""
    form = CartAddressForm()
    if not form.validate_on_submit():
        flash('Preencha os campos obrigatórios do endereço.', 'warning')
        return redirect(url_for('ver_carrinho'))

    tmp_addr = Endereco(
        cep=form.cep.data,
        rua=form.rua.data,
        numero=form.numero.data,
        complemento=form.complemento.data,
        bairro=form.bairro.data,
        cidade=form.cidade.data,
        estado=form.estado.data,
    )
    address_text = tmp_addr.full
    sa = SavedAddress(user_id=current_user.id, address=address_text)
    db.session.add(sa)
    db.session.commit()
    session['last_address_id'] = sa.id
    flash('Endereço salvo com sucesso.', 'success')

    return redirect(url_for('ver_carrinho'))


@bp.route("/checkout/confirm", methods=["POST"])
@login_required
def checkout_confirm():
    """Mostra um resumo antes de redirecionar ao pagamento externo."""
    form = CheckoutForm()
    _setup_checkout_form(form, preserve_selected=True)
    if not form.validate_on_submit():
        return redirect(url_for("ver_carrinho"))

    order = _get_current_order()
    if not order or not order.items:
        flash("Seu carrinho está vazio.", "warning")
        return redirect(url_for("ver_carrinho"))
    _reprice_order_items(order)

    # Determine the address text based on the chosen option
    selected_address = None
    if form.address_id.data is not None and form.address_id.data >= 0:
        if form.address_id.data == 0 and current_user.endereco and current_user.endereco.full:
            selected_address = current_user.endereco.full
        else:
            sa = SavedAddress.query.filter_by(
                id=form.address_id.data,
                user_id=current_user.id
            ).first()
            if sa:
                selected_address = sa.address

    if not selected_address and form.shipping_address.data:
        selected_address = form.shipping_address.data

    if not selected_address and current_user.endereco and current_user.endereco.full:
        selected_address = current_user.endereco.full

    return render_template(
        "loja/checkout_confirm.html",
        form=form,
        order=order,
        shipping=_order_vendor_shipping(order),
        selected_address=selected_address,
    )


@bp.route("/checkout", methods=["POST"])
@login_required
def checkout():
    current_app.logger.setLevel(logging.DEBUG)

    form = CheckoutForm()
    _setup_checkout_form(form, preserve_selected=True)
    prefers_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or (
            request.accept_mimetypes['application/json'] > 0
            and request.accept_mimetypes['application/json'] >=
            request.accept_mimetypes['text/html']
        )
    )

    def respond_error(message, category="danger", status=400, errors=None):
        if prefers_json:
            payload = {"success": False, "message": message, "category": category}
            if errors:
                payload["errors"] = errors
            return jsonify(payload), status
        flash(message, category)
        return redirect(url_for("ver_carrinho"))

    if not form.validate_on_submit():
        return respond_error(
            "Preencha os campos obrigatórios.",
            "warning",
            errors=form.errors,
        )

    # 1️⃣ pedido atual do carrinho
    order = _get_current_order()
    if not order or not order.items:
        return respond_error("Seu carrinho está vazio.", "warning")
    # Nunca cobrar preço defasado: reprecifica com o preço público vigente.
    _reprice_order_items(order)

    address_text = None
    if form.address_id.data is not None and form.address_id.data >= 0:
        if form.address_id.data == 0 and current_user.endereco and current_user.endereco.full:
            address_text = current_user.endereco.full
        else:
            sa = SavedAddress.query.filter_by(id=form.address_id.data, user_id=current_user.id).first()
            if sa:
                address_text = sa.address
        session["last_address_id"] = form.address_id.data
    elif form.address_id.data == -1:
        cep = request.form.get('cep')
        rua = request.form.get('rua')
        numero = request.form.get('numero')
        complemento = request.form.get('complemento')
        bairro = request.form.get('bairro')
        cidade = request.form.get('cidade')
        estado = request.form.get('estado')
        required_address_labels = {
            'cep': 'CEP',
            'rua': 'Rua',
            'cidade': 'Cidade',
            'estado': 'Estado',
        }

        missing_required = [
            label for key, label in required_address_labels.items()
            if not ((request.form.get(key) or '').strip())
        ]

        if missing_required:
            message = 'Preencha os campos obrigatórios do endereço: ' + ', '.join(missing_required) + '.'
            return respond_error(message, 'warning', errors={"shipping_address": [message]})

        tmp_addr = Endereco(
            cep=cep,
            rua=rua,
            numero=numero,
            complemento=complemento,
            bairro=bairro,
            cidade=cidade,
            estado=estado
        )
        address_text = tmp_addr.full
        sa = SavedAddress(user_id=current_user.id, address=address_text)
        db.session.add(sa)
        db.session.flush()
        session["last_address_id"] = sa.id
    if not address_text and form.shipping_address.data:
        address_text = form.shipping_address.data
        sa = SavedAddress(user_id=current_user.id, address=address_text)
        db.session.add(sa)
        db.session.flush()
        session["last_address_id"] = sa.id
    if not address_text and current_user.endereco and current_user.endereco.full:
        address_text = current_user.endereco.full
        session["last_address_id"] = 0 if address_text else None

    order.shipping_address = address_text
    db.session.add(order)
    db.session.commit()

    # 2️⃣ grava Payment PENDING
    payment = Payment(
        user_id=current_user.id,
        order_id=order.id,
        method=PaymentMethod.PIX,          # ou outro enum que prefira
        status=PaymentStatus.PENDING,
    )
    shipping = _order_vendor_shipping(order)
    payment.amount = shipping["grand_total"]
    db.session.add(payment)
    db.session.flush()                     # gera payment.id sem fechar a transação
    payment.external_reference = str(payment.id)
    db.session.commit()

    # 3️⃣ itens do Preference
    # O Mercado Pago recomenda enviar um código no campo
    # ``items.id`` para agilizar a verificação antifraude.

    items = [
        {
            "id":          str(it.product.id),
            "title":       it.product.name,
            "description": it.product.description or it.product.name,
            "category_id": it.product.mp_category_id or "others",
            "quantity":    int(it.quantity),
            # Preço público congelado no carrinho (taxa embutida).
            "unit_price":  float(
                it.unit_price if it.unit_price is not None
                else (it.product.preco_publico or 0)
            ),
        }
        for it in order.items
    ]
    items.extend(_shipping_items_for_preference(order))


    # 4️⃣ payload Preference

    # Separa o nome em partes para extrair primeiro e último nome
    name = (current_user.name or "").strip()
    parts = name.split()
    if parts:
        first_name = parts[0]
        last_name = " ".join(parts[1:]) if len(parts) > 1 else first_name
    else:
        # Quando o usuário não tem um nome salvo, usa o prefixo do e‑mail
        first_name = current_user.email.split("@")[0]
        last_name = first_name
    payer_info = {
        "first_name": first_name,
        "last_name": last_name,

        "email": current_user.email,
    }
    if current_user.phone:
        digits = re.sub(r"\D", "", current_user.phone)
        if digits.startswith("55") and len(digits) > 11:
            digits = digits[2:]
        if len(digits) >= 10:
            payer_info["phone"] = {
                "area_code": digits[:2],
                "number": digits[2:],
            }
        else:
            payer_info["phone"] = {"number": digits}
    if current_user.cpf:
        payer_info["identification"] = {
            "type": "CPF",
            "number": re.sub(r"\D", "", current_user.cpf),
        }
    if order.shipping_address:
        payer_info["address"] = {"street_name": order.shipping_address}
        m = re.search(r"CEP\s*(\d{5}-?\d{3})", order.shipping_address)
        if m:
            payer_info["address"]["zip_code"] = m.group(1)

    back_urls = {
        s: url_for("payment_status", payment_id=payment.id, _external=True)
        for s in ("success", "failure", "pending")
    }
    preference_data = {
        "items": items,
        "external_reference": payment.external_reference,
        "notification_url":   _mercadopago_notification_url(),
        "payment_methods":    {"installments": 1},
        "statement_descriptor": current_app.config.get("MERCADOPAGO_STATEMENT_DESCRIPTOR"),
        "binary_mode": current_app.config.get("MERCADOPAGO_BINARY_MODE", False),
        "back_urls": back_urls,
        "payer": payer_info,
    }
    if _mp_auto_return_enabled(back_urls):
        preference_data["auto_return"] = "approved"
    seller_payment_account = _connected_mercadopago_account_for_order(order)
    sdk_access_token = None
    if seller_payment_account:
        try:
            sdk_access_token = seller_payment_account.access_token
        except MissingMasterKeyError:
            current_app.logger.exception(
                "Chave mestra ausente ao descriptografar token Mercado Pago da casa %s",
                seller_payment_account.casa_de_racao_id,
            )
            return respond_error("Pagamento da loja indisponivel no momento.")
        # Retenção da plataforma no split (invisível ao comprador, que vê
        # um preço único com a taxa embutida):
        #   1. margem dos produtos = preço público − preço do lojista;
        #   2. frete de entregas por parceiro PetOrlândia (retido para
        #      repasse ao entregador); frete de entrega própria ('propria')
        #      fica com o lojista.
        fee_produtos = max(
            Decimal("0.00"),
            shipping["products_total"] - shipping["seller_products_total"],
        )
        marketplace_fee = float(
            (fee_produtos + shipping["platform_freight_total"]).quantize(Decimal("0.01"))
        )
        if marketplace_fee > 0:
            preference_data["marketplace_fee"] = marketplace_fee
    current_app.logger.debug("MP Preference Payload:\n%s",
                             json.dumps(preference_data, indent=2, ensure_ascii=False))

    # 5️⃣ cria Preference no Mercado Pago
    try:
        sdk = mp_sdk(sdk_access_token) if sdk_access_token else mp_sdk()
        resp = sdk.preference().create(preference_data)
    except Exception:
        current_app.logger.exception("Erro de conexão com Mercado Pago")
        return respond_error("Falha ao conectar com Mercado Pago.")

    if resp.get("status") != 201:
        current_app.logger.error("MP error (HTTP %s): %s", resp["status"], resp)
        return respond_error("Erro ao iniciar pagamento.")

    pref = resp["response"]
    payment.transaction_id = str(pref["id"])       # preference_id
    payment.init_point     = pref["init_point"]
    db.session.commit()

    session["last_pending_payment"] = payment.id
    if prefers_json:
        return jsonify(success=True, redirect=pref["init_point"])
    return redirect(pref["init_point"])


@bp.route("/notificacoes", methods=["POST", "GET"])
@csrf.exempt
def notificacoes_mercado_pago():
    if request.method == "GET":
        return jsonify(status="pong"), 200

    secret = current_app.config.get("MERCADOPAGO_WEBHOOK_SECRET", "")
    if not verify_mp_signature(request, secret):
        return jsonify(error="invalid signature"), 400

    # Check notification type
    notification_type = request.args.get("type") or request.args.get("topic")
    if notification_type != "payment":
        current_app.logger.info("Ignoring non-payment notification: %s", notification_type)
        return jsonify(status="ignored"), 200

    # Extract mp_id
    data = request.get_json(silent=True) or {}
    mp_id = (data.get("data", {}).get("id") or  # v1
             data.get("resource", "").split("/")[-1])  # v2

    if not mp_id:
        return jsonify(status="ignored"), 200

    # Query payment
    resp = mp_sdk().payment().get(mp_id)
    if resp.get("status") == 404:
        with db.session.begin():
            p = PendingWebhook.query.filter_by(mp_id=mp_id).first()
            if not p:
                db.session.add(PendingWebhook(mp_id=mp_id))
        return jsonify(status="retry_later"), 202
    if resp.get("status") != 200:
        return jsonify(error="api error"), 500

    # Process payment info
    info = resp["response"]
    status = info["status"]
    extref = info.get("external_reference")
    if not extref:
        return jsonify(status="ignored"), 200

    # Update database
    status_map = {
        "approved": PaymentStatus.COMPLETED,
        "authorized": PaymentStatus.COMPLETED,
        "pending": PaymentStatus.PENDING,
        "in_process": PaymentStatus.PENDING,
        "in_mediation": PaymentStatus.PENDING,
        "rejected": PaymentStatus.FAILED,
        "cancelled": PaymentStatus.FAILED,
        "refunded": PaymentStatus.FAILED,
        "expired": PaymentStatus.FAILED,
    }

    bloco_id = None
    if extref and extref.startswith('bloco_orcamento-'):
        try:
            bloco_id = int(extref.split('-', 1)[1])
        except (ValueError, TypeError):
            bloco_id = None

    orcamento_id = None
    if extref and extref.startswith('orcamento-'):
        try:
            orcamento_id = int(extref.split('-', 1)[1])
        except (ValueError, TypeError):
            orcamento_id = None

    onboarding = _resolve_health_onboarding(extref) if extref else None
    payment_status = status_map.get(status, PaymentStatus.PENDING)

    grooming_sub = None
    if extref and extref.startswith('grooming-'):
        try:
            from models import GroomingSubscription
            grooming_sub = GroomingSubscription.query.get(int(extref.split('-', 1)[1]))
        except (ValueError, TypeError):
            pass

    racao_sub = None
    if extref and extref.startswith('racao-assinatura-'):
        try:
            from models import RacaoAssinatura
            racao_sub = RacaoAssinatura.query.get(int(extref.rsplit('-', 1)[1]))
        except (ValueError, TypeError):
            pass

    try:
        with db.session.begin():
            pay = Payment.query.filter_by(external_reference=extref).first()
            bloco = BlocoOrcamento.query.get(bloco_id) if bloco_id else None
            orcamento = Orcamento.query.get(orcamento_id) if orcamento_id else None
            if not pay and not bloco and not orcamento and not onboarding and not grooming_sub and not racao_sub:
                current_app.logger.warning("Payment %s not found for external_reference %s", mp_id, extref)
                return jsonify(error="payment not found"), 404

            if pay:
                pay.status = payment_status
                pay.mercado_pago_id = mp_id

                if pay.external_reference and pay.external_reference.startswith('vet-membership-'):
                    _sync_veterinarian_membership_payment(pay)

                if (
                    pay.status == PaymentStatus.COMPLETED
                    and pay.external_reference
                    and pay.external_reference.startswith('vacserv-')
                ):
                    from models import VaccineServiceRequest
                    from services.notifications import queue_admin_action_notification
                    from services.vaccine_service_paid import mark_request_paid
                    try:
                        vacserv_id = int(pay.external_reference.split('-', 1)[1])
                    except (ValueError, TypeError):
                        vacserv_id = None
                    if vacserv_id:
                        vacserv_req = VaccineServiceRequest.query.get(vacserv_id)
                        if vacserv_req:
                            mark_request_paid(vacserv_req)
                            tutor = vacserv_req.user
                            queue_admin_action_notification(
                                title=f'Pedido de vacina pago #{vacserv_req.id}',
                                body=(
                                    f'Tutor: {tutor.name if tutor else "?"}\n'
                                    f'Pet: {vacserv_req.animal.name if vacserv_req.animal else "?"}\n'
                                    f'Vacina(s): {vacserv_req.item_nome}\n'
                                    f'Valor: R$ {float(vacserv_req.valor or 0):.2f}'
                                ),
                                event_type='vaccine_service.paid',
                                entity_type='vaccine_service_request',
                                entity_id=vacserv_req.id,
                                priority='high',
                                url=url_for('servicos_vacinas_admin', _external=True),
                                idempotency_key=f'vacserv-paid:{vacserv_req.id}',
                            )

                if (
                    pay.status == PaymentStatus.COMPLETED
                    and pay.external_reference
                    and pay.external_reference.startswith('petsitter-')
                ):
                    from models import PetsitterRequest
                    from services.notifications import queue_admin_action_notification
                    try:
                        petsitter_id = int(pay.external_reference.split('-', 1)[1])
                    except (ValueError, TypeError):
                        petsitter_id = None
                    if petsitter_id:
                        petsitter_req = PetsitterRequest.query.get(petsitter_id)
                        if petsitter_req:
                            tutor = petsitter_req.tutor
                            queue_admin_action_notification(
                                title=f'Pagamento de petsitter confirmado #{petsitter_req.id}',
                                body=(
                                    f'Tutor: {tutor.name if tutor else "?"}\n'
                                    f'Periodo: {petsitter_req.data_inicio.strftime("%d/%m/%Y")} a '
                                    f'{petsitter_req.data_fim.strftime("%d/%m/%Y")}\n'
                                    f'Valor: R$ {float(petsitter_req.preco_total or 0):.2f}'
                                ),
                                event_type='petsitter_request.paid',
                                entity_type='petsitter_request',
                                entity_id=petsitter_req.id,
                                priority='high',
                                url=url_for('petsitter_routes.petsitter_admin', _external=True),
                                idempotency_key=f'petsitter-paid:{petsitter_req.id}',
                            )

                if pay.status == PaymentStatus.COMPLETED and pay.order_id:
                    order = Order.query.get(pay.order_id)
                    if order and not DeliveryRequest.query.filter_by(order_id=pay.order_id).first():
                        # Agrupa itens por vendedor (clinica_id, casa_de_racao_id)
                        seller_items: dict = {}
                        for oi in order.items:
                            prod = oi.product
                            if not prod:
                                continue
                            key = (prod.clinica_id, prod.casa_de_racao_id)
                            seller_items.setdefault(key, []).append(oi)

                        for (clinica_id, casa_id), _ in seller_items.items():
                            tipo = 'plataforma'
                            if casa_id:
                                casa = CasaDeRacao.query.get(casa_id)
                                if casa and casa.modo_entrega == 'propria':
                                    tipo = 'propria'
                            elif clinica_id:
                                clinica = Clinica.query.get(clinica_id)
                                if clinica and clinica.modo_entrega == 'propria':
                                    tipo = 'propria'
                            db.session.add(DeliveryRequest(
                                order_id=pay.order_id,
                                requested_by_id=pay.user_id,
                                status="pendente",
                                clinica_id=clinica_id,
                                casa_de_racao_id=casa_id,
                                tipo_entrega=tipo,
                            ))

                        # Feedback do pedido pago: confirma ao comprador e
                        # avisa o admin. Roda só na 1ª notificação (o guard de
                        # DeliveryRequest acima evita duplicar em retries).
                        comprador = order.user
                        if comprador:
                            registrar_feedback_solicitacao(
                                comprador,
                                (
                                    f"Pagamento confirmado! Seu pedido #{order.id} "
                                    f"(R$ {order.total_value():.2f}) já está em preparação "
                                    f"e você será avisado sobre a entrega."
                                ),
                                kind='order_paid',
                            )
                        avisar_admin_nova_solicitacao(
                            f'Pedido #{order.id} pago',
                            (
                                f'Cliente: {comprador.name if comprador else "?"} '
                                f'({comprador.email if comprador else "?"})\n'
                                f'Valor: R$ {order.total_value():.2f}\n'
                                f'Itens: ' + ', '.join(f'{i.item_name} x{i.quantity}' for i in order.items)
                            ),
                        )

                    # Decrementa estoque das clínicas para produtos vinculados
                    if order:
                        from services.notifications import queue_admin_action_notification

                        comprador = order.user
                        queue_admin_action_notification(
                            title=f'Pedido pago #{order.id}',
                            body=(
                                f'Cliente: {comprador.name if comprador else "?"} '
                                f'({comprador.email if comprador else "?"})\n'
                                f'Valor: R$ {order.total_value():.2f}\n'
                                f'Itens: ' + ', '.join(f'{i.item_name} x{i.quantity}' for i in order.items)
                            ),
                            event_type='order.paid',
                            entity_type='order',
                            entity_id=order.id,
                            priority='high',
                            url=url_for('delivery_overview', _external=True),
                            idempotency_key=f'order-paid:{order.id}',
                        )
                        for oi in order.items:
                            prod = oi.product
                            if prod and prod.clinic_inventory_item_id:
                                inv = ClinicInventoryItem.query.get(prod.clinic_inventory_item_id)
                                if inv:
                                    qty_sold = oi.quantity
                                    before = inv.quantity
                                    inv.quantity = max(0, before - qty_sold)
                                    prod.stock = inv.quantity
                                    db.session.add(ClinicInventoryMovement(
                                        clinica_id=inv.clinica_id,
                                        item=inv,
                                        quantity_change=-qty_sold,
                                        quantity_before=before,
                                        quantity_after=inv.quantity,
                                        tipo='saida',
                                        motivo=f'Venda — Pedido #{order.id}',
                                    ))
                            # Decrementa estoque simples de casas de ração
                            if prod and prod.casa_de_racao_id:
                                prod.stock = max(0, prod.stock - oi.quantity)

            normalized_status = _normalize_external_payment_status(status)

            if bloco:
                bloco.payment_status = normalized_status
                _sync_orcamento_payment_classification(bloco)

            if orcamento:
                new_payment_status = normalized_status
                orcamento.payment_status = new_payment_status
                if new_payment_status == 'paid':
                    paid_at = _parse_mp_datetime(info.get('date_approved')) or utcnow()
                    orcamento.paid_at = paid_at
                else:
                    orcamento.paid_at = None
                if status in {'pending', 'in_process', 'in_mediation'} and orcamento.status == 'draft':
                    orcamento.status = 'sent'
                elif status in {'approved', 'authorized'}:
                    orcamento.status = 'approved'
                elif status == 'rejected':
                    orcamento.status = 'rejected'
                elif status in {'cancelled', 'refunded', 'expired'}:
                    orcamento.status = 'canceled'
                _sync_orcamento_payment_classification(orcamento)

            if onboarding:
                _sync_health_subscription_from_onboarding(onboarding, payment_status, pay)

            if grooming_sub and payment_status == PaymentStatus.COMPLETED and not grooming_sub.active:
                grooming_sub.active = True
                grooming_sub.start_date = utcnow()
                if mp_id and not grooming_sub.mp_preapproval_id:
                    grooming_sub.mp_preapproval_id = mp_id

            if racao_sub and payment_status == PaymentStatus.COMPLETED:
                _process_racao_assinatura_ciclo(racao_sub, mp_id)

    except SQLAlchemyError as e:
        current_app.logger.exception("DB error: %s", e)
        return jsonify(error="db failure"), 500

    return jsonify(status="updated"), 200


@bp.route("/pagamento/<status>", methods=["GET"])
def legacy_pagamento(status):
    extref = request.args.get("external_reference")
    payment = None

    if extref and extref.isdigit():
        payment = Payment.query.get(int(extref))

    if not payment:
        mp_id = (request.args.get("collection_id") or
                 request.args.get("payment_id"))
        if mp_id:
            payment = Payment.query.filter(
                (Payment.mercado_pago_id == mp_id) |
                (Payment.transaction_id == mp_id)
            ).first()

    if not payment:
        pref_id = request.args.get("preference_id")
        if pref_id:
            payment = Payment.query.filter_by(transaction_id=pref_id).first()

    mp_status = (request.args.get("status") or
                 request.args.get("collection_status") or
                 status)

    if not payment:
        if mp_status in {"success", "completed", "approved", "sucesso"}:
            return render_template("auth/sucesso.html")
        abort(404)

    return redirect(url_for("payment_status", payment_id=payment.id, status=mp_status))


@bp.route("/order/<int:order_id>/edit_address", methods=["GET", "POST"])
@login_required
def edit_order_address(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        abort(403)

    form = EditAddressForm(obj=order)
    if form.validate_on_submit():
        order.shipping_address = form.shipping_address.data
        db.session.commit()
        flash("Endereço atualizado.", "success")
        if order.payment:
            return redirect(url_for("payment_status", payment_id=order.payment.id))
        return redirect(url_for("loja"))

    payment_id = order.payment.id if order.payment else None
    return render_template("loja/edit_address.html", form=form, payment_id=payment_id)


@bp.route("/payment_status/<int:payment_id>", methods=["GET"])
def payment_status(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    if current_user.is_authenticated and payment.user_id != current_user.id:
        abort(403)

    result  = request.args.get("status") or payment.status.name.lower()

    form = CheckoutForm()

    delivery_req = (DeliveryRequest.query
                    .filter_by(order_id=payment.order_id)
                    .first())

    # endpoint a usar
    endpoint = "delivery_detail"  # agora é um só

    # Limpa o pedido da sessão quando o pagamento foi concluído
    if result in {"success", "completed", "approved"}:
        session.pop("current_order", None)

    order = payment.order if (
        current_user.is_authenticated and payment.user_id == current_user.id
    ) else None

    delivery_estimate = None
    if order and order.created_at:
        delivery_estimate = order.created_at + timedelta(days=5)

    cancel_url = (
        url_for('buyer_cancel_delivery', req_id=delivery_req.id)
        if delivery_req and delivery_req.status not in ['cancelada', 'concluida']
        else None
    )
    edit_address_url = url_for('edit_order_address', order_id=payment.order_id) if order else None

    return render_template(
        "loja/payment_status.html",
        payment          = payment,
        result           = result,
        req_id           = delivery_req.id if delivery_req else None,
        req_endpoint     = endpoint,
        order            = order,
        form             = form,
        delivery_estimate= delivery_estimate,
        cancel_url       = cancel_url,
        edit_address_url = edit_address_url,
    )


@bp.route("/minhas-compras", methods=["GET"])
@login_required
def minhas_compras():
    page = request.args.get("page", 1, type=int)
    per_page = 20

    pagination = (Order.query
                  .join(Order.payment)
                  .options(joinedload(Order.payment))
                  .filter(Order.user_id == current_user.id,
                          Payment.status == PaymentStatus.COMPLETED)
                  .order_by(Order.created_at.desc())
                  .paginate(page=page, per_page=per_page, error_out=False))

    return render_template(
        "loja/minhas_compras.html",
        orders=pagination.items,
        pagination=pagination,
        PaymentStatus=PaymentStatus,
    )


@bp.route("/pedidos/<int:order_id>/confirmar-recebimento", methods=["POST"])
@login_required
def confirmar_recebimento_pedido(order_id):
    """Tutor confirma que o pedido chegou — base para liberar repasses."""
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        abort(403)
    if order.received_at is None:
        order.received_at = now_in_brazil()
        db.session.commit()
        flash('Recebimento confirmado. Obrigado!', 'success')
    else:
        flash('Este pedido já estava confirmado como recebido.', 'info')
    return redirect(url_for('minhas_compras'))


@bp.route("/pedido/<int:order_id>", methods=["GET"])
@login_required
def pedido_detail(order_id):
    order = (Order.query
             .options(
                 joinedload(Order.items).joinedload(OrderItem.product),
                 joinedload(Order.user),
                 joinedload(Order.payment),
                 joinedload(Order.delivery_requests).joinedload(DeliveryRequest.pickup).joinedload(PickupLocation.endereco),
                 joinedload(Order.delivery_requests).joinedload(DeliveryRequest.worker)
             )
             .get_or_404(order_id))

    req = order.delivery_requests[0] if order.delivery_requests else None
    is_admin_user = bool(
        current_user.is_authenticated
        and getattr(current_user, "role", None) == "admin"
    )
    is_buyer = order.user_id == current_user.id
    is_assigned_delivery = bool(
        getattr(current_user, "worker", None) == "delivery"
        and req
        and req.worker_id == current_user.id
    )
    if not (is_admin_user or is_buyer or is_assigned_delivery):
        abort(403)

    items = order.items
    buyer = order.user
    delivery_worker = req.worker if req else None
    total = sum(i.quantity * i.product.price for i in items if i.product)

    if is_admin_user:
        role = "admin"
    elif is_assigned_delivery:
        role = "worker"
    elif buyer and current_user.id == buyer.id:
        role = "buyer"
    else:
        abort(403)

    form = CheckoutForm()
    edit_address_url = url_for("edit_order_address", order_id=order.id)
    cancel_url = (
        url_for("buyer_cancel_delivery", req_id=req.id)
        if req and req.status not in ['cancelada', 'concluida']
        else None
    )

    return render_template(
        "entregas/delivery_detail.html",
        req=req,
        order=order,
        items=items,
        buyer=buyer,
        delivery_worker=delivery_worker,
        total=total,
        role=role,
        form=form,
        edit_address_url=edit_address_url,
        cancel_url=cancel_url,
    )



# ---------------------------------------------------------------------------
# Assinatura de ração (recorrência via preapproval Mercado Pago)
# ---------------------------------------------------------------------------

# frequência em dias -> (frequency, frequency_type) do preapproval
RACAO_ASSINATURA_FREQUENCIAS = {
    15: (15, 'days'),
    30: (1, 'months'),
    60: (2, 'months'),
    90: (3, 'months'),
}


def _process_racao_assinatura_ciclo(racao_sub, mp_id=None):
    """Registra um ciclo pago da assinatura e notifica tutor e lojista."""
    primeira_vez = racao_sub.status != 'active'
    if primeira_vez:
        racao_sub.status = 'active'
        racao_sub.activated_at = utcnow()
    if mp_id and not racao_sub.mp_preapproval_id:
        racao_sub.mp_preapproval_id = str(mp_id)
    racao_sub.ciclos_pagos = (racao_sub.ciclos_pagos or 0) + 1
    racao_sub.ultimo_ciclo_em = utcnow()

    produto = racao_sub.product
    nome_produto = racao_sub.variant.name if racao_sub.variant else (produto.name if produto else 'Assinatura')

    # Tutor: confirmação do ciclo
    try:
        from services.push import push_to_user
        push_to_user(
            racao_sub.user_id,
            'Assinatura confirmada 🐾' if primeira_vez else 'Ração a caminho 🐾',
            f'Pagamento confirmado: {nome_produto}. A entrega será preparada.',
            url='/minhas-assinaturas-racao',
            tag='racao-assinatura',
        )
    except Exception:  # noqa: BLE001
        current_app.logger.debug('push tutor assinatura falhou', exc_info=True)

    # Lojista: preparar entrega
    casa = produto.casa_de_racao if produto else None
    if casa and casa.owner_id:
        endereco = racao_sub.endereco_entrega or 'endereço cadastrado do cliente'
        cliente = racao_sub.user.name if racao_sub.user else 'cliente'
        texto = (
            f'Assinatura #{racao_sub.id}: preparar entrega de {racao_sub.quantidade}x '
            f'{nome_produto} para {cliente} ({endereco}).'
        )
        try:
            from services.push import push_to_user
            push_to_user(casa.owner_id, 'Nova entrega de assinatura 📦', texto,
                         url=f'/casa-de-racao/{casa.id}/entregas', tag='racao-assinatura')
        except Exception:  # noqa: BLE001
            current_app.logger.debug('push lojista assinatura falhou', exc_info=True)
        owner = getattr(casa, 'owner', None)
        email = getattr(owner, 'email', None)
        if email:
            try:
                mail.send(MailMessage(
                    subject='PetOrlândia — nova entrega de assinatura',
                    recipients=[email],
                    body=texto,
                ))
            except Exception:  # noqa: BLE001
                current_app.logger.warning('Falha ao avisar lojista por e-mail (assinatura %s)', racao_sub.id)


@bp.route('/produto/<int:product_id>/assinar', methods=['GET', 'POST'])
@login_required
def racao_assinar(product_id):
    """Cria uma assinatura recorrente do produto (ração e afins)."""
    from models import Animal, ProductVariant, RacaoAssinatura

    product = Product.query.get_or_404(product_id)
    if product.status != 'active':
        abort(404)

    variantes = [v for v in (product.variants or []) if v.status == 'active']
    animais = (
        Animal.query
        .filter_by(user_id=current_user.id)
        .filter(Animal.removido_em.is_(None))
        .all()
    )

    if request.method == 'POST':
        freq = request.form.get('frequencia_dias', type=int) or 30
        if freq not in RACAO_ASSINATURA_FREQUENCIAS:
            freq = 30
        quantidade = max(1, min(request.form.get('quantidade', type=int) or 1, 10))
        variant = None
        variant_id = request.form.get('variant_id', type=int)
        if variant_id:
            variant = ProductVariant.query.filter_by(id=variant_id, product_id=product.id).first()
        animal_id = request.form.get('animal_id', type=int) or None
        if animal_id and not any(a.id == animal_id for a in animais):
            animal_id = None
        endereco = (request.form.get('endereco_entrega') or '').strip()[:255] or None

        preco_unit = variant.preco_publico if variant else product.preco_publico
        preco_ciclo = float(preco_unit or 0) * quantidade
        if preco_ciclo <= 0:
            flash('Produto sem preço válido para assinatura.', 'danger')
            return redirect(url_for('produto_detail', product_id=product.id))

        sub = RacaoAssinatura(
            user_id=current_user.id,
            product_id=product.id,
            variant_id=variant.id if variant else None,
            animal_id=animal_id,
            quantidade=quantidade,
            frequencia_dias=freq,
            preco_ciclo=preco_ciclo,
            endereco_entrega=endereco,
            status='pending',
        )
        db.session.add(sub)
        db.session.commit()

        frequency, frequency_type = RACAO_ASSINATURA_FREQUENCIAS[freq]
        nome_item = variant.name if variant else product.name
        preapproval_data = {
            'reason': f'Assinatura {nome_item} — PetOrlândia',
            'back_url': url_for('racao_minhas_assinaturas', _external=True),
            'payer_email': current_user.email,
            'auto_recurring': {
                'frequency': frequency,
                'frequency_type': frequency_type,
                'transaction_amount': preco_ciclo,
                'currency_id': 'BRL',
            },
            'external_reference': f'racao-assinatura-{sub.id}',
        }
        try:
            resp = mp_sdk().preapproval().create(preapproval_data)
        except Exception:
            current_app.logger.exception('Erro ao criar preapproval de assinatura de ração')
            flash('Falha ao conectar com o Mercado Pago. Tente novamente.', 'danger')
            return redirect(url_for('produto_detail', product_id=product.id))

        if resp.get('status') not in {200, 201}:
            current_app.logger.warning('Preapproval de ração rejeitado: %s', resp)
            flash('Erro ao iniciar a assinatura. Tente novamente.', 'danger')
            return redirect(url_for('produto_detail', product_id=product.id))

        body = resp.get('response', {}) or {}
        mp_id = body.get('id')
        init_point = body.get('init_point') or body.get('sandbox_init_point')
        if mp_id:
            sub.mp_preapproval_id = str(mp_id)
            db.session.commit()
        if not init_point:
            flash('Erro ao iniciar a assinatura.', 'danger')
            return redirect(url_for('produto_detail', product_id=product.id))
        return redirect(init_point)

    return render_template(
        'loja/assinar_racao.html',
        product=product,
        variantes=variantes,
        animais=animais,
        frequencias=RACAO_ASSINATURA_FREQUENCIAS,
    )


@bp.route('/minhas-assinaturas-racao')
@login_required
def racao_minhas_assinaturas():
    from models import RacaoAssinatura

    assinaturas = (
        RacaoAssinatura.query
        .filter_by(user_id=current_user.id)
        .order_by(RacaoAssinatura.created_at.desc())
        .all()
    )
    return render_template('loja/minhas_assinaturas_racao.html', assinaturas=assinaturas)


@bp.route('/assinatura-racao/<int:sub_id>/cancelar', methods=['POST'])
@login_required
def racao_assinatura_cancelar(sub_id):
    from models import RacaoAssinatura

    sub = RacaoAssinatura.query.get_or_404(sub_id)
    if sub.user_id != current_user.id and not _is_admin():
        abort(403)
    if sub.mp_preapproval_id:
        try:
            mp_sdk().preapproval().update(sub.mp_preapproval_id, {'status': 'cancelled'})
        except Exception:
            current_app.logger.exception('Falha ao cancelar preapproval %s', sub.mp_preapproval_id)
    sub.status = 'cancelled'
    sub.cancelled_at = utcnow()
    db.session.commit()
    flash('Assinatura cancelada. Nenhuma nova cobrança será feita.', 'info')
    return redirect(url_for('racao_minhas_assinaturas'))
