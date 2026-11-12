"""Limpeza urbana: a população comunica, a equipe comprova, a fiscalização audita.

Telas:

* ``/limpeza-urbana/comunicar`` — foto + localização de lixo, entulho, móveis, galhos;
* ``/limpeza-urbana/minhas`` — o que a própria pessoa comunicou e o andamento;
* ``/limpeza-urbana/mapa`` — todas as comunicações georreferenciadas (equipe e fiscalização);
* ``/limpeza-urbana/solicitacao/<id>`` — antes e depois, com hora, ponto e distância;
* ``/limpeza-urbana/acessos`` — o administrador atribui papéis e períodos.
"""
from __future__ import annotations

import csv
import io
from datetime import date

from flask import (Blueprint, Response, abort, flash, jsonify, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from extensions import db
from services import limpeza_urbana as servico
from services.limpeza_urbana import LimpezaErro
from time_utils import utcnow

bp = Blueprint("limpeza_urbana", __name__, url_prefix="/limpeza-urbana")


def get_blueprint():
    return bp


def upload_to_s3(*args, **kwargs):
    # Late-binding: os testes trocam app.upload_to_s3.
    import app as app_module
    return app_module.upload_to_s3(*args, **kwargs)


def _exigir(condicao):
    if not condicao:
        abort(403)


def _data(texto):
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise LimpezaErro("Data inválida.")


def _contexto_base():
    return dict(
        papeis=servico.papeis_de(current_user),
        pode_mapa=servico.pode_ver_mapa(current_user),
        pode_comunicar=servico.pode_comunicar(current_user),
        pode_comprovar=servico.pode_comprovar(current_user),
        pode_fiscalizar=servico.pode_fiscalizar(current_user),
        eh_admin=servico.eh_admin(current_user),
        CATEGORIAS=servico.CATEGORIAS, STATUS=servico.STATUS, hora_local=servico.hora_local,
        rotulo_categorias=servico.rotulo_categorias,
        DISTANCIA_ALERTA_M=servico.DISTANCIA_ALERTA_M,
    )


@bp.route("/")
@login_required
def inicio():
    if servico.pode_ver_mapa(current_user):
        return redirect(url_for(".mapa"))
    if servico.pode_comunicar(current_user):
        return redirect(url_for(".comunicar"))
    abort(403)


@bp.route("/comunicar", methods=["GET", "POST"])
@login_required
def comunicar():
    _exigir(servico.pode_comunicar(current_user))
    form = request.form
    if request.method == "POST":
        try:
            categorias = servico.normalizar_categorias(form.getlist("categoria"))
            if not categorias:
                raise LimpezaErro("Marque o que precisa ser limpo (pode marcar mais de um).")
            data, exif, nome = servico.ler_foto(request.files.getlist("foto"))
            lat, lon, precisao, origem = servico.escolher_local(form, exif)
            foto_url = servico.guardar_foto(data, nome, "limpeza/comunicacoes", upload_to_s3)
            from models.limpeza import LimpezaSolicitacao
            solicitacao = LimpezaSolicitacao(
                autor_id=current_user.id, categorias=categorias,
                descricao=(form.get("descricao") or "").strip()[:500] or None,
                referencia=(form.get("referencia") or "").strip()[:200] or None,
                latitude=lat, longitude=lon, precisao_m=precisao, origem_local=origem,
                foto_url=foto_url, foto_capturada_em=servico.capturada_utc(exif.capturada_em), status="aberta",
            )
            db.session.add(solicitacao)
            db.session.flush()
            servico.registrar_evento("comunicada", solicitacao.id, current_user,
                                     f"{servico.rotulo_categorias(categorias)} ({origem})")
            db.session.commit()
        except LimpezaErro as exc:
            db.session.rollback()
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(erro=str(exc)), 400
            flash(str(exc), "danger")
            return render_template("limpeza/comunicar.html", form=form, selecionadas=form.getlist("categoria"),
                                   **_contexto_base()), 400
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            flash(f"Comunicação nº {solicitacao.id} registrada. Obrigado por colaborar!", "success")
            return jsonify(destino=url_for(".minhas"))
        flash(f"Comunicação nº {solicitacao.id} registrada. Obrigado por colaborar!", "success")
        return redirect(url_for(".minhas"))
    return render_template("limpeza/comunicar.html", form={}, selecionadas=[], **_contexto_base())


@bp.route("/minhas")
@login_required
def minhas():
    _exigir(servico.pode_comunicar(current_user))
    itens = servico.consultar(autor_id=current_user.id)
    return render_template("limpeza/minhas.html", itens=itens, **_contexto_base())


def _filtros():
    try:
        desde, ate = _data(request.args.get("desde")), _data(request.args.get("ate"))
    except LimpezaErro:
        desde = ate = None
    return dict(status=request.args.get("status") or None, categoria=request.args.get("categoria") or None,
                desde=desde, ate=ate)


@bp.route("/mapa")
@login_required
def mapa():
    _exigir(servico.pode_ver_mapa(current_user))
    return render_template("limpeza/mapa.html", filtros=_filtros(), visao_lista=False, **_contexto_base())


@bp.route("/comunicacoes")
@login_required
def todas_comunicacoes():
    _exigir(servico.eh_admin(current_user))
    return render_template("limpeza/mapa.html", filtros=_filtros(), visao_lista=True, **_contexto_base())


@bp.route("/mapa/dados")
@login_required
def mapa_dados():
    _exigir(servico.pode_ver_mapa(current_user))
    filtros = _filtros()
    itens = servico.consultar(**filtros)
    ver_autor = servico.pode_fiscalizar(current_user)
    resposta = jsonify({
        "pontos": [servico.como_ponto(s, ver_autor=ver_autor) for s in itens],
        "indicadores": servico.indicadores(itens),
        "limite": len(itens) >= 2000,
    })
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


def _solicitacao_visivel(solicitacao_id):
    from models.limpeza import LimpezaSolicitacao
    solicitacao = db.session.get(LimpezaSolicitacao, solicitacao_id)
    if solicitacao is None:
        abort(404)
    if not (servico.pode_ver_mapa(current_user) or solicitacao.autor_id == current_user.id):
        abort(403)
    return solicitacao


@bp.route("/solicitacao/<int:solicitacao_id>")
@login_required
def solicitacao(solicitacao_id):
    item = _solicitacao_visivel(solicitacao_id)
    eventos = []
    if servico.pode_fiscalizar(current_user):
        from models.limpeza import LimpezaEvento
        eventos = (LimpezaEvento.query.filter_by(solicitacao_id=item.id)
                   .order_by(LimpezaEvento.criado_em).all())
    return render_template("limpeza/solicitacao.html", item=item, eventos=eventos, **_contexto_base())


@bp.route("/solicitacao/<int:solicitacao_id>/comprovar", methods=["POST"])
@login_required
def comprovar(solicitacao_id):
    _exigir(servico.pode_comprovar(current_user))
    item = _solicitacao_visivel(solicitacao_id)
    destino = url_for(".solicitacao", solicitacao_id=item.id)
    if item.status != "aberta":
        flash("Esta comunicação não está aguardando limpeza.", "warning")
        return redirect(destino)
    try:
        data, exif, nome = servico.ler_foto(request.files.getlist("foto"))
        if servico.foto_antiga(exif.capturada_em):
            raise LimpezaErro("A foto da comprovação é antiga. Tire a foto agora, no local, depois da limpeza.")
        lat, lon, precisao, origem = servico.escolher_local(request.form, exif)
        distancia = round(servico.distancia_m(item.latitude, item.longitude, lat, lon), 1)
        foto_url = servico.guardar_foto(data, nome, "limpeza/comprovacoes", upload_to_s3)
        from models.limpeza import LimpezaComprovacao
        comprovacao = LimpezaComprovacao(
            solicitacao_id=item.id, autor_id=current_user.id,
            observacao=(request.form.get("observacao") or "").strip()[:500] or None,
            latitude=lat, longitude=lon, precisao_m=precisao, origem_local=origem, distancia_m=distancia,
            foto_url=foto_url, foto_capturada_em=servico.capturada_utc(exif.capturada_em), status="valida",
        )
        db.session.add(comprovacao)
        item.status, item.concluida_em = "concluida", utcnow()
        servico.registrar_evento("comprovada", item.id, current_user,
                                 f"Foto a {distancia:.0f} m do ponto comunicado ({origem})")
        db.session.commit()
    except LimpezaErro as exc:
        db.session.rollback()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(erro=str(exc)), 400
        flash(str(exc), "danger")
        return redirect(destino)
    if distancia > servico.DISTANCIA_ALERTA_M:
        flash(f"Limpeza registrada, mas a foto foi tirada a {distancia:.0f} m do ponto comunicado. "
              "A fiscalização vai conferir.", "warning")
    else:
        flash("Limpeza comprovada. Obrigado!", "success")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(destino=destino)
    return redirect(destino)


@bp.route("/comprovacao/<int:comprovacao_id>/recusar", methods=["POST"])
@login_required
def recusar_comprovacao(comprovacao_id):
    _exigir(servico.pode_fiscalizar(current_user))
    from models.limpeza import LimpezaComprovacao
    comprovacao = db.session.get(LimpezaComprovacao, comprovacao_id)
    if comprovacao is None:
        abort(404)
    destino = url_for(".solicitacao", solicitacao_id=comprovacao.solicitacao_id)
    motivo = (request.form.get("motivo") or "").strip()
    if not motivo:
        flash("Diga por que a comprovação foi recusada: a equipe precisa saber o que refazer.", "danger")
        return redirect(destino)
    if comprovacao.status != "valida":
        flash("Essa comprovação já foi recusada.", "info")
        return redirect(destino)
    por = servico.nome_da_conta(current_user)
    comprovacao.status, comprovacao.recusada_em = "recusada", utcnow()
    comprovacao.recusada_por, comprovacao.motivo_recusa = por, motivo[:300]
    item = comprovacao.solicitacao
    if item.status == "concluida" and item.comprovacao_valida is None:
        item.status, item.concluida_em = "aberta", None
    servico.registrar_evento("comprovacao_recusada", item.id, current_user, motivo)
    db.session.commit()
    flash("Comprovação recusada. A comunicação voltou para a fila de limpeza.", "info")
    return redirect(destino)


@bp.route("/solicitacao/<int:solicitacao_id>/descartar", methods=["POST"])
@login_required
def descartar(solicitacao_id):
    _exigir(servico.pode_fiscalizar(current_user))
    item = _solicitacao_visivel(solicitacao_id)
    destino = url_for(".solicitacao", solicitacao_id=item.id)
    motivo = (request.form.get("motivo") or "").strip()
    if not motivo:
        flash("Informe o motivo do descarte (duplicada, fora da área, foto sem relação…).", "danger")
        return redirect(destino)
    if item.status != "aberta":
        flash("Só comunicações aguardando limpeza podem ser descartadas.", "warning")
        return redirect(destino)
    item.status, item.descartada_em = "descartada", utcnow()
    item.descartada_por, item.motivo_descarte = servico.nome_da_conta(current_user), motivo[:300]
    servico.registrar_evento("descartada", item.id, current_user, motivo)
    db.session.commit()
    flash("Comunicação descartada. Ela continua no histórico.", "info")
    return redirect(destino)


@bp.route("/relatorio.csv")
@login_required
def relatorio():
    _exigir(servico.pode_fiscalizar(current_user))
    itens = servico.consultar(**_filtros())
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";")
    escritor.writerow([
        "nº", "tipos", "situação", "comunicada em", "latitude", "longitude", "origem do ponto",
        "precisão (m)", "foto da comunicação", "referência", "descrição", "comunicada por",
        "limpeza comprovada em", "horas até a limpeza", "distância da comprovação (m)",
        "foto da comprovação", "comprovada por", "comprovações recusadas", "motivo do descarte",
    ])
    for s in itens:
        c = s.comprovacao_valida
        escritor.writerow([
            s.id, servico.rotulo_categorias(s.categorias), servico.STATUS.get(s.status, s.status),
            servico.hora_local(s.criado_em), s.latitude, s.longitude, s.origem_local,
            s.precisao_m if s.precisao_m is not None else "", s.foto_url, s.referencia or "", s.descricao or "",
            servico.nome_da_conta(s.autor),
            servico.hora_local(c.criado_em) if c else "",
            servico.horas_ate_limpeza(s) if c else "",
            c.distancia_m if c else "", c.foto_url if c else "",
            servico.nome_da_conta(c.autor) if c else "",
            sum(1 for x in s.comprovacoes if x.status == "recusada"), s.motivo_descarte or "",
        ])
    nome = f"limpeza-urbana-{servico.hoje():%Y-%m-%d}.csv"
    return Response("﻿" + saida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"', "Cache-Control": "no-store"})


@bp.route("/acessos", methods=["GET", "POST"])
@login_required
def acessos():
    _exigir(servico.eh_admin(current_user))
    if request.method == "POST":
        por = servico.nome_da_conta(current_user)
        try:
            conta = servico.buscar_conta(request.form.get("email"))
            inicio, fim = _data(request.form.get("inicio")), _data(request.form.get("fim"))
            gravados = servico.conceder(conta, request.form.getlist("papel"), inicio, fim, por)
            db.session.commit()
        except LimpezaErro as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        else:
            rotulos = ", ".join(servico.PAPEIS[g.papel][0] for g in gravados)
            flash(f"{conta.name or conta.email}: acesso de {rotulos} concedido.", "success")
        return redirect(url_for(".acessos"))
    from models.limpeza import LimpezaEvento
    ativos = servico.acessos_ativos()
    dia = servico.hoje()
    historico = (LimpezaEvento.query.filter(LimpezaEvento.tipo.in_(["acesso_concedido", "acesso_revogado"]))
                 .order_by(LimpezaEvento.criado_em.desc()).limit(30).all())
    return render_template("limpeza/acessos.html", ativos=ativos, dia=dia, historico=historico,
                           vigente=servico.acesso_vigente, PAPEIS=servico.PAPEIS,
                           comunicacao_aberta=servico.comunicacao_aberta(), **_contexto_base())


@bp.route("/acessos/<int:acesso_id>/revogar", methods=["POST"])
@login_required
def revogar_acesso(acesso_id):
    _exigir(servico.eh_admin(current_user))
    if servico.revogar(acesso_id, servico.nome_da_conta(current_user)) is None:
        abort(404)
    db.session.commit()
    flash("Acesso revogado. Os demais acessos da conta não mudaram.", "info")
    return redirect(url_for(".acessos"))


@bp.route("/acessos/comunicacao-aberta", methods=["POST"])
@login_required
def comunicacao_aberta():
    _exigir(servico.eh_admin(current_user))
    from models.base import SiteFlag
    ligar = request.form.get("aberta") == "1"
    servico.registrar_evento("comunicacao_aberta" if ligar else "comunicacao_restrita", None, current_user,
                             f"por {servico.nome_da_conta(current_user)}")
    SiteFlag.set(servico.FLAG_COMUNICACAO_ABERTA, ligar,
                 label="Limpeza urbana: qualquer conta pode comunicar pontos para limpeza")
    flash("Agora qualquer conta pode comunicar pontos para limpeza." if ligar
          else "Somente quem tem papel atribuído pode comunicar.", "info")
    return redirect(url_for(".acessos"))
