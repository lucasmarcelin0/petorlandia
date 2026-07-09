"""
blueprints/petsitter.py
=======================
Módulo Petsitter + Carreiras + Indicações.

Rotas públicas:
  GET  /petsitter                      → página do serviço (compartilhável)
  GET/POST /carreiras                  → cadastro de parceiros e cuidadores

Rotas do tutor (login):
  GET/POST /petsitter/solicitar        → solicitação de cuidado
  GET  /petsitter/minhas               → minhas solicitações
  POST /petsitter/solicitacao/<id>/cancelar
  GET  /indicacao                      → meu link de indicação

Rotas do admin:
  GET  /petsitter/admin                → painel (candidaturas + solicitações)
  POST /petsitter/admin/candidatura/<id>/<acao>   (aprovar | rejeitar)
  POST /petsitter/admin/solicitacao/<id>/atribuir
  POST /petsitter/admin/solicitacao/<id>/concluir
"""
from __future__ import annotations

from datetime import date, datetime
from functools import wraps
from urllib.parse import quote

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from extensions import db

bp = Blueprint("petsitter_routes", __name__)


def get_blueprint():
    return bp


CATEGORIAS_CARREIRAS = {
    "petsitter": "Petsitter (cuidador de animais)",
    "clinica": "Clínica veterinária",
    "petshop": "Petshop / Casa de ração",
    "laboratorio": "Laboratório",
    "especialista": "Profissional especialista",
}

LOCAIS_ATENDIMENTO = {
    "domicilio_tutor": "Na minha casa (o cuidador vai até o pet)",
    "casa_sitter": "Na casa do cuidador (hospedagem)",
}


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if (getattr(current_user, "role", "") or "").lower() != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _whatsapp_share_url(texto: str) -> str:
    return f"https://wa.me/?text={quote(texto)}"


# ---------------------------------------------------------------------------
# Página pública do serviço
# ---------------------------------------------------------------------------

@bp.route("/petsitter")
def petsitter_home():
    from models import PetsitterProfile

    sitters_aprovados = PetsitterProfile.query.filter_by(status="aprovado").count()
    page_url = url_for("petsitter_routes.petsitter_home", _external=True)
    ref_code = None
    if current_user.is_authenticated:
        from models import ReferralCode

        existing = ReferralCode.query.filter_by(user_id=current_user.id).first()
        ref_code = existing.code if existing else None
    share_url = page_url + (f"?ref={ref_code}" if ref_code else "")
    share_texto = (
        "Vai viajar? A PetOrlândia tem petsitters de confiança para cuidar do seu pet. "
        f"Veja como funciona: {share_url}"
    )
    return render_template(
        "petsitter/index.html",
        sitters_aprovados=sitters_aprovados,
        share_whatsapp=_whatsapp_share_url(share_texto),
        page_url=page_url,
    )


# ---------------------------------------------------------------------------
# Solicitação do tutor
# ---------------------------------------------------------------------------

@bp.route("/petsitter/solicitar", methods=["GET", "POST"])
@login_required
def petsitter_solicitar():
    from models import Animal, PetsitterRequest

    animais = (
        Animal.query.filter(
            Animal.user_id == current_user.id,
            Animal.removido_em.is_(None),
        )
        .order_by(Animal.name.asc())
        .all()
    )

    if request.method == "POST":
        erros = []
        data_inicio = _parse_date(request.form.get("data_inicio"))
        data_fim = _parse_date(request.form.get("data_fim"))
        local = (request.form.get("local_atendimento") or "").strip()
        animal_ids = request.form.getlist("animal_ids", type=int)
        observacoes = (request.form.get("observacoes") or "").strip() or None
        endereco = (request.form.get("endereco") or "").strip() or None

        if not data_inicio or not data_fim:
            erros.append("Informe as datas de início e fim da viagem.")
        elif data_fim < data_inicio:
            erros.append("A data final não pode ser anterior à inicial.")
        elif data_inicio < date.today():
            erros.append("A data de início não pode estar no passado.")
        if local not in LOCAIS_ATENDIMENTO:
            erros.append("Escolha onde o pet será cuidado.")
        animais_escolhidos = [a for a in animais if a.id in animal_ids]
        if not animais_escolhidos:
            erros.append("Selecione pelo menos um pet.")
        if local == "domicilio_tutor" and not endereco:
            endereco_user = getattr(current_user, "endereco", None)
            endereco = str(endereco_user) if endereco_user else None
            if not endereco:
                erros.append("Informe o endereço onde o pet ficará.")

        if erros:
            for erro in erros:
                flash(erro, "warning")
        else:
            solicitacao = PetsitterRequest(
                tutor_id=current_user.id,
                data_inicio=data_inicio,
                data_fim=data_fim,
                local_atendimento=local,
                endereco=endereco,
                observacoes=observacoes,
            )
            solicitacao.animais.extend(animais_escolhidos)
            db.session.add(solicitacao)
            db.session.commit()
            from services.notifications import notify_admin_action

            pets = ", ".join(a.name for a in animais_escolhidos)
            notify_admin_action(
                title=f"Nova solicitacao de petsitter: {current_user.name}",
                body=(
                    f"Tutor: {current_user.name} ({current_user.email or 'sem email'})\n"
                    f"Pets: {pets}\n"
                    f"Periodo: {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}\n"
                    f"Local: {LOCAIS_ATENDIMENTO.get(local, local)}"
                    + (f"\nObservacoes: {observacoes}" if observacoes else "")
                ),
                event_type="petsitter_request.created",
                entity_type="petsitter_request",
                entity_id=solicitacao.id,
                priority="high",
                url=url_for("petsitter_routes.petsitter_admin", _external=True),
                idempotency_key=f"petsitter-request:{solicitacao.id}",
            )
            flash(
                "Solicitação enviada! Vamos encontrar um cuidador e te avisar.",
                "success",
            )
            return redirect(url_for("petsitter_routes.petsitter_minhas"))

    return render_template(
        "petsitter/solicitar.html",
        animais=animais,
        locais=LOCAIS_ATENDIMENTO,
    )


@bp.route("/petsitter/minhas")
@login_required
def petsitter_minhas():
    from models import PetsitterRequest

    solicitacoes = (
        PetsitterRequest.query.filter_by(tutor_id=current_user.id)
        .order_by(PetsitterRequest.created_at.desc())
        .all()
    )
    return render_template("petsitter/minhas.html", solicitacoes=solicitacoes)


@bp.route("/petsitter/solicitacao/<int:solicitacao_id>/cancelar", methods=["POST"])
@login_required
def petsitter_cancelar(solicitacao_id: int):
    from models import PetsitterRequest

    solicitacao = PetsitterRequest.query.get_or_404(solicitacao_id)
    if solicitacao.tutor_id != current_user.id:
        abort(403)
    if solicitacao.status in ("aberta", "atribuida"):
        solicitacao.status = "cancelada"
        db.session.commit()
        flash("Solicitação cancelada.", "info")
    return redirect(url_for("petsitter_routes.petsitter_minhas"))


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_preco(value):
    """Converte '350,00' / '350.00' em Decimal ou None."""
    from decimal import Decimal, InvalidOperation

    raw = (value or "").strip().replace("R$", "").replace(" ", "")
    if not raw:
        return None
    raw = raw.replace(".", "").replace(",", ".") if "," in raw else raw
    try:
        preco = Decimal(raw)
    except InvalidOperation:
        return None
    return preco if preco > 0 else None


@bp.route("/petsitter/solicitacao/<int:solicitacao_id>/pagar", methods=["POST"])
@login_required
def petsitter_pagar(solicitacao_id: int):
    """Gera (ou reaproveita) a cobrança Mercado Pago e redireciona ao checkout.

    O pagamento via Checkout Pro aceita cartão de crédito/débito, Pix e
    boleto, e permite estorno integral pela API caso algo dê errado.
    """
    from blueprints.utils import _load_app_module
    from models import PaymentMethod, PaymentStatus, Payment, PetsitterRequest

    solicitacao = PetsitterRequest.query.get_or_404(solicitacao_id)
    if solicitacao.tutor_id != current_user.id:
        abort(403)
    if solicitacao.status != "atribuida" or not solicitacao.preco_total:
        flash("Esta solicitação ainda não tem cobrança definida.", "warning")
        return redirect(url_for("petsitter_routes.petsitter_minhas"))

    payment = solicitacao.payment
    if payment is not None and payment.status == PaymentStatus.COMPLETED:
        flash("Esta solicitação já está paga.", "info")
        return redirect(url_for("petsitter_routes.petsitter_minhas"))

    app_module = _load_app_module()
    back_url = url_for("petsitter_routes.petsitter_minhas", _external=True)
    pets = ", ".join(a.name for a in solicitacao.animais) or "pets"
    items = [{
        "id": f"petsitter-{solicitacao.id}",
        "title": f"Petsitter para {pets} ({solicitacao.dias} diária(s))",
        "quantity": 1,
        "unit_price": float(solicitacao.preco_total),
    }]

    try:
        resultado = app_module._criar_preferencia_pagamento(
            items,
            external_reference=f"petsitter-{solicitacao.id}",
            back_url=back_url,
        )
    except app_module.PaymentPreferenceError as exc:
        flash(str(exc) or "Erro ao iniciar pagamento. Tente novamente.", "danger")
        return redirect(url_for("petsitter_routes.petsitter_minhas"))

    if payment is None:
        payment = Payment(
            user_id=current_user.id,
            method=PaymentMethod.CREDIT_CARD,
            status=PaymentStatus.PENDING,
            external_reference=f"petsitter-{solicitacao.id}",
        )
        db.session.add(payment)
        db.session.flush()
        solicitacao.payment_id = payment.id
    else:
        payment.status = PaymentStatus.PENDING
    payment.init_point = resultado["payment_url"]
    db.session.commit()

    return redirect(resultado["payment_url"])


# ---------------------------------------------------------------------------
# Carreiras
# ---------------------------------------------------------------------------

@bp.route("/carreiras", methods=["GET", "POST"])
def carreiras():
    from models import CareerApplication

    if request.method == "POST":
        categoria = (request.form.get("categoria") or "").strip()
        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        telefone = (request.form.get("telefone") or "").strip() or None
        cidade = (request.form.get("cidade") or "").strip() or None
        especialidade = (request.form.get("especialidade") or "").strip() or None
        mensagem = (request.form.get("mensagem") or "").strip() or None

        erros = []
        if categoria not in CATEGORIAS_CARREIRAS:
            erros.append("Escolha uma categoria válida.")
        if not nome:
            erros.append("Informe seu nome ou o nome do estabelecimento.")
        if not email or "@" not in email:
            erros.append("Informe um e-mail válido.")
        if categoria == "especialista" and not especialidade:
            erros.append("Informe sua especialidade (ex.: ultrassonografia).")

        pendente_existente = None
        if not erros:
            pendente_existente = CareerApplication.query.filter_by(
                email=email, categoria=categoria, status="pendente"
            ).first()

        if erros:
            for erro in erros:
                flash(erro, "warning")
        elif pendente_existente:
            flash(
                "Já recebemos uma candidatura sua nesta categoria. "
                "Ela está em análise — em breve entraremos em contato.",
                "info",
            )
            return redirect(url_for("petsitter_routes.carreiras"))
        else:
            candidatura = CareerApplication(
                user_id=current_user.id if current_user.is_authenticated else None,
                categoria=categoria,
                nome=nome,
                email=email,
                telefone=telefone,
                cidade=cidade,
                especialidade=especialidade,
                mensagem=mensagem,
            )
            db.session.add(candidatura)
            db.session.commit()
            from services.notifications import notify_admins

            notify_admins(
                f"Nova candidatura de {CATEGORIAS_CARREIRAS.get(categoria, categoria).lower()}: "
                f"{nome} ({email}).",
                kind="candidatura_carreiras",
                url=url_for(
                    "petsitter_routes.petsitter_admin"
                    if categoria == "petsitter"
                    else "admin_parcerias",
                    _external=True,
                ),
            )
            flash(
                "Candidatura recebida! Vamos analisar e entrar em contato. Obrigado por querer fazer parte. 🐾",
                "success",
            )
            return redirect(url_for("petsitter_routes.carreiras"))

    return render_template(
        "carreiras.html",
        categorias=CATEGORIAS_CARREIRAS,
        categoria_selecionada=request.values.get("categoria", ""),
    )


# ---------------------------------------------------------------------------
# Indicação
# ---------------------------------------------------------------------------

@bp.route("/indicacao")
@login_required
def indicacao():
    from models import ReferralCode

    referral = ReferralCode.get_or_create(current_user.id)
    db.session.commit()

    link = url_for("register", ref=referral.code, _external=True)
    texto = (
        "Eu uso a PetOrlândia para cuidar do meu pet: consultas, loja, petsitter e mais, "
        f"tudo em um lugar. Crie sua conta pelo meu link: {link}"
    )
    return render_template(
        "indicacao.html",
        referral=referral,
        link=link,
        share_whatsapp=_whatsapp_share_url(texto),
        total_indicados=len(referral.signups),
    )


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@bp.route("/petsitter/admin")
@admin_required
def petsitter_admin():
    from models import CareerApplication, PetsitterProfile, PetsitterRequest

    candidaturas = (
        CareerApplication.query.filter_by(status="pendente")
        .order_by(CareerApplication.created_at.asc())
        .all()
    )
    solicitacoes = (
        PetsitterRequest.query.filter(
            PetsitterRequest.status.in_(["aberta", "atribuida"])
        )
        .order_by(PetsitterRequest.data_inicio.asc())
        .all()
    )
    sitters = (
        PetsitterProfile.query.filter_by(status="aprovado")
        .order_by(PetsitterProfile.created_at.asc())
        .all()
    )
    return render_template(
        "petsitter/admin.html",
        candidaturas=candidaturas,
        solicitacoes=solicitacoes,
        sitters=sitters,
        categorias=CATEGORIAS_CARREIRAS,
    )


@bp.route(
    "/petsitter/admin/candidatura/<int:candidatura_id>/<acao>", methods=["POST"]
)
@admin_required
def petsitter_admin_candidatura(candidatura_id: int, acao: str):
    from models import CareerApplication, PetsitterProfile, User
    from time_utils import utcnow

    if acao not in ("aprovar", "rejeitar"):
        abort(404)

    candidatura = CareerApplication.query.get_or_404(candidatura_id)
    if candidatura.status != "pendente":
        flash("Esta candidatura já foi analisada.", "info")
        return redirect(url_for("petsitter_routes.petsitter_admin"))

    import uuid as _uuid

    from blueprints.utils import _load_app_module
    from services.notifications import notify_user

    candidatura.status = "aprovada" if acao == "aprovar" else "rejeitada"
    candidatura.reviewed_at = utcnow()
    candidatura.reviewed_by_id = current_user.id

    if acao == "aprovar":
        app_module = _load_app_module()

        usuario = candidatura.user
        if usuario is None:
            usuario = User.query.filter(
                db.func.lower(User.email) == candidatura.email
            ).first()
        usuario_novo = usuario is None
        if usuario_novo:
            usuario = User(
                name=candidatura.nome,
                email=candidatura.email,
                phone=candidatura.telefone or None,
                added_by=current_user,
            )
            usuario.set_password(_uuid.uuid4().hex)
            db.session.add(usuario)
            db.session.flush()
        candidatura.user_id = usuario.id

        if candidatura.categoria == "petsitter":
            perfil = PetsitterProfile.query.filter_by(user_id=usuario.id).first()
            if perfil is None:
                perfil = PetsitterProfile(
                    user_id=usuario.id,
                    cidade=candidatura.cidade,
                    bio=candidatura.mensagem,
                )
                db.session.add(perfil)
            perfil.status = "aprovado"
            db.session.commit()
            proximo_passo = (
                app_module._first_access_url_for_user(usuario, _external=True)
                if usuario_novo
                else url_for("petsitter_routes.petsitter_home", _external=True)
            )
            corpo = (
                f"Olá, {candidatura.nome.split()[0]}!\n\n"
                "Sua candidatura como petsitter no PetOrlândia foi aprovada. 🎉\n"
                + (
                    f"Crie sua senha de acesso neste link:\n{proximo_passo}\n\n"
                    if usuario_novo
                    else f"Acesse a plataforma: {proximo_passo}\n\n"
                )
                + "Abraços,\nEquipe PetOrlândia"
            )
        else:
            # Demais categorias (clínica, petshop, laboratório, especialista):
            # aprova gerando um convite de onboarding do tipo correspondente.
            import hashlib
            import secrets
            from datetime import datetime, timedelta, timezone

            from models import PartnerInvite

            tipo_convite = {
                "clinica": "clinica",
                "petshop": "casa_de_racao",
                "laboratorio": "clinica",
                "especialista": "veterinario",
            }.get(candidatura.categoria, "usuario")
            token = secrets.token_urlsafe(24)
            db.session.add(PartnerInvite(
                tipo=tipo_convite,
                nome=candidatura.nome,
                email=candidatura.email,
                telefone=candidatura.telefone,
                cidade=candidatura.cidade,
                token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                created_by_id=current_user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            ))
            db.session.commit()
            link = url_for("partner_invite_onboarding", token=token, _external=True)
            corpo = (
                f"Olá, {candidatura.nome.split()[0]}!\n\n"
                "Sua candidatura ao PetOrlândia foi aprovada. 🎉\n"
                f"Conclua seu cadastro neste link (válido por 30 dias):\n{link}\n\n"
                "Abraços,\nEquipe PetOrlândia"
            )

        notify_user(usuario, "Candidatura aprovada no PetOrlândia 🎉", corpo, kind="candidatura_aprovada")
        flash("Candidatura aprovada. O candidato foi avisado por e-mail com o próximo passo.", "success")
    else:
        db.session.commit()
        if candidatura.user is not None:
            notify_user(
                candidatura.user,
                "Sobre sua candidatura no PetOrlândia",
                (
                    f"Olá, {candidatura.nome.split()[0]}.\n\n"
                    "Agradecemos seu interesse, mas sua candidatura não foi aprovada neste momento.\n"
                    "Você pode se candidatar novamente no futuro.\n\n"
                    "Equipe PetOrlândia"
                ),
                kind="candidatura_rejeitada",
            )
        flash("Candidatura rejeitada.", "info")
    return redirect(url_for("petsitter_routes.petsitter_admin"))


@bp.route(
    "/petsitter/admin/solicitacao/<int:solicitacao_id>/atribuir", methods=["POST"]
)
@admin_required
def petsitter_admin_atribuir(solicitacao_id: int):
    from models import PetsitterProfile, PetsitterRequest

    solicitacao = PetsitterRequest.query.get_or_404(solicitacao_id)
    sitter_id = request.form.get("sitter_id", type=int)
    sitter = db.session.get(PetsitterProfile, sitter_id) if sitter_id else None
    if sitter is None or sitter.status != "aprovado":
        flash("Escolha um cuidador aprovado.", "warning")
        return redirect(url_for("petsitter_routes.petsitter_admin"))

    preco_total = _parse_preco(request.form.get("preco_total"))
    if preco_total is None:
        flash("Informe o valor total da cobrança (ex.: 350,00).", "warning")
        return redirect(url_for("petsitter_routes.petsitter_admin"))

    solicitacao.sitter_id = sitter.id
    solicitacao.preco_total = preco_total
    solicitacao.status = "atribuida"
    db.session.commit()
    flash(
        "Cuidador atribuído. O tutor verá o botão de pagamento em Minhas Solicitações.",
        "success",
    )
    return redirect(url_for("petsitter_routes.petsitter_admin"))


@bp.route(
    "/petsitter/admin/solicitacao/<int:solicitacao_id>/estornar", methods=["POST"]
)
@admin_required
def petsitter_admin_estornar(solicitacao_id: int):
    """Estorna integralmente o pagamento via API do Mercado Pago."""
    from blueprints.utils import _load_app_module
    from models import PaymentStatus, PetsitterRequest

    solicitacao = PetsitterRequest.query.get_or_404(solicitacao_id)
    payment = solicitacao.payment
    if payment is None or payment.status != PaymentStatus.COMPLETED:
        flash("Não há pagamento aprovado para estornar.", "warning")
        return redirect(url_for("petsitter_routes.petsitter_admin"))
    if not payment.mercado_pago_id:
        flash(
            "Pagamento sem identificador do Mercado Pago — estorne manualmente no painel MP.",
            "danger",
        )
        return redirect(url_for("petsitter_routes.petsitter_admin"))

    app_module = _load_app_module()
    try:
        resp = app_module.mp_sdk().refund().create(payment.mercado_pago_id)
    except Exception:  # noqa: BLE001
        flash("Falha ao conectar com o Mercado Pago. Tente novamente.", "danger")
        return redirect(url_for("petsitter_routes.petsitter_admin"))

    if resp.get("status") not in (200, 201):
        flash(
            f"Mercado Pago recusou o estorno (HTTP {resp.get('status')}). "
            "Verifique no painel do MP.",
            "danger",
        )
        return redirect(url_for("petsitter_routes.petsitter_admin"))

    payment.status = PaymentStatus.FAILED  # padrão do projeto para 'refunded'
    solicitacao.status = "cancelada"
    db.session.commit()
    flash("Estorno solicitado com sucesso. O valor voltará ao tutor.", "success")
    return redirect(url_for("petsitter_routes.petsitter_admin"))


@bp.route(
    "/petsitter/admin/solicitacao/<int:solicitacao_id>/concluir", methods=["POST"]
)
@admin_required
def petsitter_admin_concluir(solicitacao_id: int):
    from models import PetsitterRequest

    solicitacao = PetsitterRequest.query.get_or_404(solicitacao_id)
    solicitacao.status = "concluida"
    db.session.commit()
    flash("Solicitação concluída.", "success")
    return redirect(url_for("petsitter_routes.petsitter_admin"))
