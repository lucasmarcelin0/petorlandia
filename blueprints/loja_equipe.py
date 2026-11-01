"""Equipe da loja: o dono cadastra quem opera o caixa e liga ou desliga o acesso.

O operador usa o dia a dia (caixa, vendas, NFC-e, estoque, entradas, produtos,
banho e tosa, clientes e entregas). Dados da loja, fiscal, recebimentos e a
própria equipe continuam só com o dono (ver ``app.ensure_loja_operacao``).
"""
from __future__ import annotations

import uuid

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_mail import Message as MailMessage
from sqlalchemy import func

from extensions import db, mail
from models import LojaMembro, User
from template_filters import normalize_phone
from time_utils import now_in_brazil


bp = Blueprint("loja_equipe_routes", __name__)


def get_blueprint():
    return bp


def ensure_loja_dono(casa_id: int):
    """Só o dono da loja (ou admin) mexe na equipe; os demais recebem 403."""
    import app as app_module

    return app_module._casa_loja_access(casa_id)


@bp.route("/casa-de-racao/<int:casa_id>/equipe", methods=["GET"])
@login_required
def loja_equipe(casa_id):
    casa = ensure_loja_dono(casa_id)
    membros = (
        LojaMembro.query.filter_by(casa_de_racao_id=casa.id)
        .order_by(LojaMembro.ativo.desc(), LojaMembro.created_at.desc())
        .all()
    )
    return render_template("loja_equipe/equipe.html", casa=casa, membros=membros)


def _atualizar_menu(user_id: int) -> None:
    """O menu da loja do operador aparece ou some já na próxima página."""
    from context_processors import _invalidate_cached_context

    _invalidate_cached_context(user_id, "loja_operada")


def _enviar_email(destinatario: str, assunto: str, corpo: str) -> bool:
    try:
        mail.send(MailMessage(subject=assunto, recipients=[destinatario], body=corpo))
        return True
    except Exception as exc:  # noqa: BLE001 - o acesso vale mesmo sem o e-mail
        current_app.logger.warning("Falha ao enviar e-mail da equipe da loja para %s: %s", destinatario, exc)
        return False


@bp.route("/casa-de-racao/<int:casa_id>/equipe", methods=["POST"])
@login_required
def loja_equipe_adicionar(casa_id):
    """Libera o operador: conta existente pelo e-mail, ou conta nova com link para criar a senha."""
    import app as app_module

    casa = ensure_loja_dono(casa_id)
    destino = redirect(url_for("loja_equipe", casa_id=casa.id))
    nome = " ".join((request.form.get("nome") or "").split())[:120]
    email = (request.form.get("email") or "").strip().lower()
    celular = normalize_phone(request.form.get("celular"))
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        flash("Informe um e-mail válido.", "danger")
        return destino

    usuario = User.query.filter(func.lower(User.email) == email).first()
    nova_conta = usuario is None
    if usuario is not None and usuario.id in (casa.owner_id, casa.registered_by_id):
        flash("Este e-mail é do dono da loja, que já tem acesso a tudo.", "info")
        return destino
    if nova_conta:
        if not nome or not celular:
            flash("Para quem ainda não tem conta no PetOrlândia, informe nome, e-mail e celular.", "danger")
            return destino
        if len(celular.lstrip("+")) < 12:
            flash("Informe o celular com DDD, por exemplo (16) 99123-4567.", "danger")
            return destino
        if app_module.find_users_by_phone(celular):
            flash("Este celular já está em outra conta. Use o e-mail dessa conta para liberar o acesso.", "danger")
            return destino
        usuario = User(name=nome, email=email, phone=celular, is_private=True, added_by=current_user)
        # Senha provisória inacessível: a pessoa cria a dela pelo link de primeiro acesso.
        usuario.set_password(uuid.uuid4().hex)
        db.session.add(usuario)
        db.session.flush()

    membro = LojaMembro.query.filter_by(casa_de_racao_id=casa.id, user_id=usuario.id).first()
    if membro is None:
        membro = LojaMembro(casa_de_racao_id=casa.id, user_id=usuario.id, created_by_id=current_user.id)
        db.session.add(membro)
    membro.ativo = True
    membro.desativado_em = None
    db.session.commit()
    _atualizar_menu(usuario.id)

    primeiro_nome = (usuario.name or "").split()[0] if usuario.name else ""
    caixa = url_for("loja_caixa", casa_id=casa.id, _external=True)
    if nova_conta:
        link = app_module._first_access_url_for_user(
            usuario, next_url=url_for("loja_caixa", casa_id=casa.id), _external=True
        )
        enviado = _enviar_email(
            email,
            f"Seu acesso à {casa.nome} no PetOrlândia",
            (
                f"Olá, {primeiro_nome}!\n\n"
                f"Você foi cadastrado(a) como operador(a) da loja {casa.nome} no PetOrlândia.\n"
                f"Para criar sua senha, use este link:\n{link}\n\n"
                f"Depois, o caixa da loja fica em:\n{caixa}\n\n"
                "Abraços,\nEquipe PetOrlândia"
            ),
        )
        if enviado:
            flash(f"{usuario.name} cadastrado(a). Enviamos por e-mail o link para criar a senha.", "success")
        else:
            flash(
                f"{usuario.name} cadastrado(a), mas o e-mail não pôde ser enviado. "
                f"Envie a ele(a) este link de primeiro acesso: {link}",
                "warning",
            )
    else:
        _enviar_email(
            email,
            f"Acesso liberado na {casa.nome}",
            (
                f"Olá, {primeiro_nome}!\n\n"
                f"Seu acesso de operador(a) da loja {casa.nome} foi liberado no PetOrlândia.\n"
                f"Entre com a sua conta e use o caixa em:\n{caixa}\n\n"
                "Abraços,\nEquipe PetOrlândia"
            ),
        )
        flash(f"Acesso liberado para {usuario.name or email}, que já tinha conta no PetOrlândia.", "success")
    return destino


@bp.route("/casa-de-racao/<int:casa_id>/equipe/<int:membro_id>/acesso", methods=["POST"])
@login_required
def loja_equipe_acesso(casa_id, membro_id):
    """Liga ou desliga o acesso. Desligar não apaga nada do que a pessoa fez."""
    casa = ensure_loja_dono(casa_id)
    membro = LojaMembro.query.filter_by(id=membro_id, casa_de_racao_id=casa.id).first_or_404()
    ligar = request.form.get("ativo") == "1"
    membro.ativo = ligar
    membro.desativado_em = None if ligar else now_in_brazil()
    db.session.commit()
    _atualizar_menu(membro.user_id)
    nome = membro.user.name if membro.user else "Operador"
    flash(f"Acesso de {nome} {'religado' if ligar else 'desligado'}.", "success")
    return redirect(url_for("loja_equipe", casa_id=casa.id))
