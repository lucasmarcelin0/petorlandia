"""Planos de saúde e planos de banho/tosa — views do domínio.

``mp_sdk``/``is_veterinarian``/``_is_admin`` são resolvidos via módulo app em
tempo de request: testes fazem monkeypatch desses nomes no app (contrato do
antigo lazy_view).
"""
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

from extensions import db
from forms import ConsultaPlanAuthorizationForm, SubscribePlanForm
from models import Animal
from services.health_plan import evaluate_consulta_coverages
from time_utils import utcnow

from app import get_animal_or_404, get_consulta_or_404

bp = Blueprint("planos_routes", __name__)


def get_blueprint():
    return bp


def _is_admin():
    import app as app_module

    return app_module._is_admin()


def is_veterinarian(*args, **kwargs):
    import app as app_module

    return app_module.is_veterinarian(*args, **kwargs)


def mp_sdk(*args, **kwargs):
    import app as app_module

    return app_module.mp_sdk(*args, **kwargs)


def _grooming_clinic_access(clinica_id):
    """Retorna (clinica, is_owner). Aborta 403 se sem permissão."""
    from models import Clinica, ClinicStaff
    clinica = Clinica.query.get_or_404(clinica_id)
    is_owner = current_user.id == clinica.owner_id
    staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=current_user.id).first()
    if not (_is_admin() or is_owner or staff):
        abort(403)
    return clinica, is_owner



@bp.route("/plano-saude", methods=["GET", "POST"])
@login_required
def plano_saude_overview():
    from models import HealthPlan, HealthSubscription, Clinica
    from forms import HealthPlanForm

    is_admin = _is_admin()
    minha_clinica = Clinica.query.filter_by(owner_id=current_user.id).first()

    # --- gestão: planos de saúde (admin global ou dono de clínica) ---
    health_form = HealthPlanForm(prefix='hp')
    if (is_admin or minha_clinica) and health_form.validate_on_submit() and health_form.submit.data:
        plan = HealthPlan(
            name=health_form.name.data,
            description=health_form.description.data or None,
            price=float(health_form.price.data),
            clinica_id=minha_clinica.id if minha_clinica and not is_admin else None,
        )
        db.session.add(plan)
        db.session.commit()
        flash('Plano de saúde criado!', 'success')
        return redirect(url_for('plano_saude_overview'))

    if is_admin:
        all_health_plans = HealthPlan.query.order_by(HealthPlan.name).all()
    elif minha_clinica:
        all_health_plans = HealthPlan.query.filter_by(clinica_id=minha_clinica.id).order_by(HealthPlan.name).all()
    else:
        all_health_plans = []

    # --- área do tutor ---
    animais_do_usuario = (
        Animal.query
        .filter_by(user_id=current_user.id)
        .filter(Animal.removido_em.is_(None))
        .all()
    )
    subs = HealthSubscription.query.filter_by(user_id=current_user.id, active=True).all()
    subscriptions = {s.animal_id: s for s in subs}

    return render_template(
        "planos/plano_saude_overview.html",
        animais=animais_do_usuario,
        subscriptions=subscriptions,
        user=current_user,
        is_admin=is_admin,
        minha_clinica=minha_clinica,
        health_form=health_form,
        all_health_plans=all_health_plans,
    )


@bp.route("/animal/<int:animal_id>/planosaude", methods=["GET", "POST"])
@login_required
def planosaude_animal(animal_id):
    animal = get_animal_or_404(animal_id)

    if animal.owner != current_user:
        flash("Você não tem permissão para acessar esse animal.", "danger")
        return redirect(url_for("profile"))

    form = SubscribePlanForm()
    from models import HealthPlan, HealthPlanOnboarding, HealthSubscription
    plans = HealthPlan.query.options(selectinload(HealthPlan.coverages)).all()
    form.plan_id.choices = [
        (p.id, f"{p.name} - R$ {p.price:.2f}") for p in plans
    ]
    default_animal_document = animal.microchip_number or str(animal.id)
    if request.method == "GET":
        form.tutor_document.data = current_user.cpf
        form.animal_document.data = default_animal_document
    else:
        form.tutor_document.data = form.tutor_document.data or current_user.cpf
        form.animal_document.data = form.animal_document.data or default_animal_document
    plans_data = [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "price": p.price,
            "coverages": [
                {
                    "name": c.name,
                    "code": c.procedure_code,
                    "limit": float(c.monetary_limit or 0),
                    "waiting": c.waiting_period_days,
                    "deductible": float(c.deductible_amount or 0),
                }
                for c in p.coverages
            ],
        }
        for p in plans
    ]
    subscription = (
        HealthSubscription.query
        .filter_by(animal_id=animal.id, user_id=current_user.id, active=True)
        .first()
    )
    onboarding = (
        HealthPlanOnboarding.query
        .filter_by(animal_id=animal.id)
        .order_by(HealthPlanOnboarding.created_at.desc())
        .first()
    )

    if form.validate_on_submit():
        return contratar_plano(animal_id)

    from admin import _is_admin

    return render_template(
        "animais/planosaude_animal.html",
        animal=animal,
        form=form,        # {{ form.hidden_tag() }} agora existe
        subscription=subscription,
        plans=plans_data,
        onboarding=onboarding,
        user_cpf=current_user.cpf,
        animal_microchip=animal.microchip_number,
        tutor_document_value=form.tutor_document.data,
        animal_document_value=form.animal_document.data,
        show_schedule_button=_is_admin() or is_veterinarian(current_user),
    )


@bp.route("/plano-saude/<int:animal_id>/contratar", methods=["POST"])
def contratar_plano(animal_id):
    """Inicia a assinatura de um plano de saúde via Mercado Pago."""
    # Check authentication manually to handle JSON requests properly
    if not current_user.is_authenticated:
        is_json_request = request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html']
        if is_json_request:
            return jsonify({'success': False, 'message': 'Você precisa estar logado para contratar um plano.', 'redirect': url_for('login_view')}), 401
        return redirect(url_for('login_view'))
    
    animal = get_animal_or_404(animal_id)

    if animal.owner != current_user:
        flash("Você não tem permissão para contratar este plano.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    # Create form and populate with POST data
    form = SubscribePlanForm()
    from models import HealthPlan, HealthPlanOnboarding
    plans = HealthPlan.query.all()
    form.plan_id.choices = [
        (p.id, f"{p.name} - R$ {p.price:.2f}") for p in plans
    ]
    
    # Check if form validates on POST
    if not form.validate_on_submit():
        current_app.logger.warning(f"Form validation errors: {form.errors}")
        flash("Selecione um plano válido.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    plan = HealthPlan.query.get_or_404(form.plan_id.data)

    onboarding = HealthPlanOnboarding(
        plan_id=plan.id,
        animal_id=animal.id,
        user_id=current_user.id,
        guardian_document=form.tutor_document.data,
        animal_document=form.animal_document.data or None,
        contract_reference=form.contract_reference.data or None,
        extra_notes=form.extra_notes.data or None,
        consent_ip=request.remote_addr,
        attachments={'document_links': form.document_links.data} if form.document_links.data else None,
    )
    db.session.add(onboarding)
    db.session.commit()
    flash('Documentos enviados para análise da seguradora.', 'info')

    preapproval_data = {
        "reason": f"{plan.name} - {animal.name}",
        "back_url": url_for("planosaude_animal", animal_id=animal.id, _external=True),
        "payer_email": current_user.email,
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": float(plan.price),
            "currency_id": "BRL",
        },
    }

    preapproval_data["external_reference"] = f"health-onboarding-{onboarding.id}"

    try:
        current_app.logger.info(f"Creating Mercado Pago preapproval with data: {preapproval_data}")
        resp = mp_sdk().preapproval().create(preapproval_data)
        current_app.logger.info(f"Mercado Pago response: {resp}")
    except Exception as e:  # pragma: no cover - network failures
        current_app.logger.exception(f"Erro de conexão com Mercado Pago: {e}")
        flash("Falha ao conectar com Mercado Pago.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    if resp.get("status") not in {200, 201}:
        current_app.logger.error(f"MP error (HTTP {resp.get('status')}): {resp}")
        flash("Erro ao iniciar assinatura.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    init_point = (resp.get("response", {}).get("init_point") or
                  resp.get("response", {}).get("sandbox_init_point"))
    if not init_point:
        flash("Erro ao iniciar assinatura.", "danger")
        return redirect(url_for("planosaude_animal", animal_id=animal.id))

    return redirect(init_point)


@bp.route("/consulta/<int:consulta_id>/validar-plano", methods=["POST"])
@login_required
def validar_plano_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if not is_veterinarian(current_user):
        abort(403)
    form = ConsultaPlanAuthorizationForm()
    from models import HealthSubscription
    active_subs = (
        HealthSubscription.query
        .filter_by(animal_id=consulta.animal_id, active=True)
        .all()
    )
    form.subscription_id.choices = [
        (s.id, f"{s.plan.name} – vigente desde {s.start_date.date():%d/%m/%Y}")
        for s in active_subs
    ]
    if not active_subs:
        flash('O tutor não possui plano ativo para este animal.', 'warning')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id))
    if not form.validate_on_submit():
        flash('Selecione um plano válido para validar a cobertura.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id))

    subscription = HealthSubscription.query.get_or_404(form.subscription_id.data)
    if subscription.animal_id != consulta.animal_id:
        flash('Plano selecionado não pertence a este animal.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id))

    consulta.health_subscription_id = subscription.id
    consulta.health_plan_id = subscription.plan_id
    consulta.authorization_reference = f"PRG-{consulta.id}-{int(utcnow().timestamp())}"
    consulta.authorization_checked_at = utcnow()
    consulta.authorization_notes = form.notes.data or ''

    result = evaluate_consulta_coverages(consulta)
    consulta.authorization_status = result['status']
    if result.get('messages'):
        consulta.authorization_notes = '\n'.join(result['messages'])
    db.session.commit()

    category = 'success' if result['status'] == 'approved' else 'warning'
    flash(' '.join(result.get('messages', [])) or 'Cobertura analisada.', category)
    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id))


@bp.route("/clinica/<int:clinica_id>/planos/tosa", methods=["GET", "POST"])
@login_required
def clinic_grooming_planos(clinica_id):
    from models import GroomingPlan
    from forms import GroomingPlanForm
    clinica, _ = _grooming_clinic_access(clinica_id)

    form = GroomingPlanForm()
    if form.validate_on_submit():
        plan = GroomingPlan(
            clinica_id=clinica.id,
            name=form.name.data,
            description=form.description.data or None,
            service_type=form.service_type.data,
            price=form.price.data,
            sessions_per_month=form.sessions_per_month.data,
        )
        db.session.add(plan)
        db.session.commit()
        flash('Plano criado com sucesso!', 'success')
        return redirect(url_for('clinic_grooming_planos', clinica_id=clinica.id))

    planos = GroomingPlan.query.filter_by(clinica_id=clinica.id).order_by(GroomingPlan.name).all()
    return render_template(
        'clinica/clinic_grooming_planos.html',
        clinica=clinica,
        planos=planos,
        form=form,
    )


@bp.route("/clinica/<int:clinica_id>/planos/tosa/<int:plan_id>/editar", methods=["GET", "POST"])
@login_required
def clinic_grooming_plano_editar(clinica_id, plan_id):
    from models import GroomingPlan
    from forms import GroomingPlanForm
    clinica, _ = _grooming_clinic_access(clinica_id)
    plan = GroomingPlan.query.filter_by(id=plan_id, clinica_id=clinica.id).first_or_404()

    form = GroomingPlanForm(obj=plan)
    if form.validate_on_submit():
        plan.name = form.name.data
        plan.description = form.description.data or None
        plan.service_type = form.service_type.data
        plan.price = form.price.data
        plan.sessions_per_month = form.sessions_per_month.data
        db.session.commit()
        flash('Plano atualizado.', 'success')
        return redirect(url_for('clinic_grooming_planos', clinica_id=clinica.id))

    return render_template(
        'clinica/clinic_grooming_plano_editar.html',
        clinica=clinica,
        plan=plan,
        form=form,
    )


@bp.route("/clinica/<int:clinica_id>/planos/tosa/<int:plan_id>/toggle", methods=["POST"])
@login_required
def clinic_grooming_plano_toggle(clinica_id, plan_id):
    from models import GroomingPlan
    clinica, _ = _grooming_clinic_access(clinica_id)
    plan = GroomingPlan.query.filter_by(id=plan_id, clinica_id=clinica.id).first_or_404()
    plan.active = not plan.active
    db.session.commit()
    state = 'ativado' if plan.active else 'desativado'
    flash(f'Plano {state}.', 'success')
    return redirect(url_for('clinic_grooming_planos', clinica_id=clinica.id))


@bp.route("/clinica/<int:clinica_id>/planos/tosa/<int:plan_id>/assinantes", methods=["GET"])
@login_required
def clinic_grooming_assinantes(clinica_id, plan_id):
    from models import GroomingPlan, GroomingSubscription
    clinica, _ = _grooming_clinic_access(clinica_id)
    plan = GroomingPlan.query.filter_by(id=plan_id, clinica_id=clinica.id).first_or_404()
    assinantes = (
        GroomingSubscription.query
        .filter_by(plan_id=plan.id)
        .order_by(GroomingSubscription.created_at.desc())
        .all()
    )
    return render_template(
        'clinica/clinic_grooming_assinantes.html',
        clinica=clinica,
        plan=plan,
        assinantes=assinantes,
    )


@bp.route("/planos/tosa", methods=["GET", "POST"])
@login_required
def grooming_planos_publicos():
    from models import GroomingPlan, GroomingSubscription, Clinica, CasaDeRacao
    from forms import GroomingPlanForm

    minha_clinica = Clinica.query.filter_by(owner_id=current_user.id).first()
    minha_casa_de_racao = CasaDeRacao.query.filter_by(owner_id=current_user.id).first()

    grooming_form = GroomingPlanForm(prefix='gp')
    if (minha_clinica or minha_casa_de_racao) and grooming_form.validate_on_submit() and grooming_form.submit.data:
        plan = GroomingPlan(
            clinica_id=minha_clinica.id if minha_clinica else None,
            casa_de_racao_id=minha_casa_de_racao.id if not minha_clinica and minha_casa_de_racao else None,
            name=grooming_form.name.data,
            description=grooming_form.description.data or None,
            service_type=grooming_form.service_type.data,
            price=grooming_form.price.data,
            sessions_per_month=grooming_form.sessions_per_month.data,
        )
        db.session.add(plan)
        db.session.commit()
        flash('Plano de banho e tosa criado!', 'success')
        return redirect(url_for('grooming_planos_publicos'))

    planos = (
        GroomingPlan.query
        .filter_by(active=True)
        .order_by(GroomingPlan.price)
        .all()
    )
    minhas_ids = set(
        s.plan_id for s in
        GroomingSubscription.query
        .filter_by(user_id=current_user.id, active=True)
        .all()
    )
    grooming_planos = []
    if minha_clinica:
        grooming_planos = minha_clinica.grooming_plans.order_by(GroomingPlan.name).all()
    elif minha_casa_de_racao:
        grooming_planos = minha_casa_de_racao.grooming_plans.order_by(GroomingPlan.name).all()

    return render_template(
        'grooming/planos_publicos.html',
        planos=planos,
        minhas_ids=minhas_ids,
        minha_clinica=minha_clinica,
        minha_casa_de_racao=minha_casa_de_racao,
        grooming_form=grooming_form,
        grooming_planos=grooming_planos,
    )


@bp.route("/planos/tosa/<int:plan_id>/assinar", methods=["GET", "POST"])
@login_required
def grooming_assinar(plan_id):
    from models import GroomingPlan, GroomingSubscription, Animal
    from forms import GroomingSubscribeForm
    plan = GroomingPlan.query.filter_by(id=plan_id, active=True).first_or_404()

    # Verifica se já possui assinatura ativa neste plano
    if GroomingSubscription.query.filter_by(user_id=current_user.id, plan_id=plan.id, active=True).first():
        flash('Você já possui uma assinatura ativa neste plano.', 'info')
        return redirect(url_for('grooming_planos_publicos'))

    animais = Animal.query.filter_by(user_id=current_user.id).all()
    form = GroomingSubscribeForm()
    form.animal_id.choices = [(a.id, a.name) for a in animais]

    if form.validate_on_submit():
        animal = Animal.query.get_or_404(form.animal_id.data)
        if animal.user_id != current_user.id:
            abort(403)

        sub = GroomingSubscription(
            plan_id=plan.id,
            animal_id=animal.id,
            user_id=current_user.id,
            active=False,
        )
        db.session.add(sub)
        db.session.commit()

        preapproval_data = {
            "reason": f"{plan.name} — {animal.name} ({plan.clinica.nome})",
            "back_url": url_for('grooming_minhas_assinaturas', _external=True),
            "payer_email": current_user.email,
            "auto_recurring": {
                "frequency": 1,
                "frequency_type": "months",
                "transaction_amount": float(plan.price),
                "currency_id": "BRL",
            },
            "external_reference": f"grooming-{sub.id}",
        }

        try:
            resp = mp_sdk().preapproval().create(preapproval_data)
        except Exception:
            current_app.logger.exception("Erro ao criar preapproval grooming")
            flash("Falha ao conectar com Mercado Pago.", "danger")
            return redirect(url_for('grooming_planos_publicos'))

        if resp.get("status") not in {200, 201}:
            flash("Erro ao iniciar assinatura. Tente novamente.", "danger")
            return redirect(url_for('grooming_planos_publicos'))

        mp_id = resp.get("response", {}).get("id")
        init_point = (resp.get("response", {}).get("init_point") or
                      resp.get("response", {}).get("sandbox_init_point"))

        if mp_id:
            sub.mp_preapproval_id = mp_id
            db.session.commit()

        if not init_point:
            flash("Erro ao iniciar assinatura.", "danger")
            return redirect(url_for('grooming_planos_publicos'))

        return redirect(init_point)

    return render_template(
        'grooming/assinar.html',
        plan=plan,
        form=form,
        animais=animais,
    )


@bp.route("/planos/tosa/assinatura/<int:sub_id>/cancelar", methods=["POST"])
@login_required
def grooming_cancelar(sub_id):
    from models import GroomingSubscription
    sub = GroomingSubscription.query.filter_by(id=sub_id, user_id=current_user.id).first_or_404()
    if sub.mp_preapproval_id:
        try:
            mp_sdk().preapproval().update(sub.mp_preapproval_id, {"status": "cancelled"})
        except Exception:
            current_app.logger.exception("Erro ao cancelar preapproval MP %s", sub.mp_preapproval_id)
    sub.active = False
    db.session.commit()
    flash('Assinatura cancelada.', 'success')
    return redirect(url_for('grooming_minhas_assinaturas'))


@bp.route("/planos/tosa/minhas-assinaturas", methods=["GET"])
@login_required
def grooming_minhas_assinaturas():
    from models import GroomingSubscription
    assinaturas = (
        GroomingSubscription.query
        .filter_by(user_id=current_user.id)
        .order_by(GroomingSubscription.created_at.desc())
        .all()
    )
    return render_template('grooming/minhas_assinaturas.html', assinaturas=assinaturas)

