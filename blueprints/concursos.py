"""Simulados de concurso: easter egg da área de estudo da estagiária.

* ``/estudos/concursos/`` — provas disponíveis e o meu progresso;
* ``/estudos/concursos/nova`` — gestor envia PDF da prova + gabarito;
* ``/estudos/concursos/prova/<id>/gabarito`` — gestor confere/completa o gabarito;
* ``/estudos/concursos/prova/<id>`` — folha de respostas ao lado do PDF;
* ``/estudos/concursos/tentativa/<id>`` — resultado corrigido;
* ``/estudos/concursos/acompanhamento`` — progresso de cada estagiária.
"""
from __future__ import annotations

from io import BytesIO

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from extensions import db
from models.concursos import ALTERNATIVAS, ANULADA, ConcursoProva, ConcursoTentativa
from services import concursos as servico
from time_utils import utcnow

bp = Blueprint("concursos", __name__, url_prefix="/estudos/concursos")


def get_blueprint():
    return bp


def _exigir(condicao):
    if not condicao:
        abort(403)


def _prova(prova_id, *, so_ativa=True):
    prova = db.session.get(ConcursoProva, prova_id)
    if prova is None or (so_ativa and not prova.ativo and not servico.pode_gerenciar(current_user)):
        abort(404)
    return prova


@bp.route("/")
@login_required
def inicio():
    _exigir(servico.pode_estudar(current_user))
    gestor = servico.pode_gerenciar(current_user)
    provas = (ConcursoProva.query.order_by(ConcursoProva.criado_em.desc()).all() if gestor
              else servico.provas_ativas())
    return render_template("concursos/inicio.html", provas=provas, gestor=gestor,
                           resumo=servico.resumo_por_prova(current_user))


@bp.route("/nova", methods=["GET", "POST"])
@login_required
def nova():
    _exigir(servico.pode_gerenciar(current_user))
    if request.method == "GET":
        return render_template("concursos/nova.html", gestor=True)

    titulo = (request.form.get("titulo") or "").strip()[:200]
    arquivo = request.files.get("pdf_prova")
    dados = arquivo.read(servico.MAX_PDF_BYTES + 1) if arquivo else b""
    if not titulo:
        flash("Dê um título para a prova.", "warning")
        return redirect(url_for("concursos.nova"))
    if not servico.eh_pdf(dados) or len(dados) > servico.MAX_PDF_BYTES:
        flash("Envie o PDF da prova (até 15 MB).", "warning")
        return redirect(url_for("concursos.nova"))

    texto = request.form.get("gabarito_texto") or ""
    arquivo_gab = request.files.get("pdf_gabarito")
    if arquivo_gab and arquivo_gab.filename:
        dados_gab = arquivo_gab.read(servico.MAX_PDF_BYTES + 1)
        if servico.eh_pdf(dados_gab):
            texto = f"{texto}\n{servico.texto_do_pdf(dados_gab)}"
    try:
        total = int(request.form.get("total_questoes") or 0)
    except ValueError:
        total = 0
    gabarito = servico.ler_gabarito(texto, total or None)
    if not gabarito:
        gabarito = "-" * max(1, min(total, servico.MAX_QUESTOES) or 50)

    try:
        ano = int(request.form.get("ano") or 0) or None
    except ValueError:
        ano = None
    prova = ConcursoProva(
        titulo=titulo,
        banca=(request.form.get("banca") or "").strip()[:80] or None,
        cargo=(request.form.get("cargo") or "").strip()[:120] or None,
        ano=ano,
        total_questoes=len(gabarito),
        gabarito=gabarito,
        pdf_nome=(arquivo.filename or "prova.pdf")[:200],
        pdf_prova=dados,
        ativo=False,
        criado_por_id=current_user.id,
    )
    db.session.add(prova)
    db.session.commit()
    faltam = gabarito.count("-")
    flash(f"Prova enviada. Confira o gabarito{f' — faltam {faltam} questões' if faltam else ''} e publique.",
          "info")
    return redirect(url_for("concursos.gabarito", prova_id=prova.id))


@bp.route("/prova/<int:prova_id>/gabarito", methods=["GET", "POST"])
@login_required
def gabarito(prova_id):
    _exigir(servico.pode_gerenciar(current_user))
    prova = _prova(prova_id, so_ativa=False)
    if request.method == "POST":
        try:
            total = max(1, min(int(request.form.get("total_questoes") or prova.total_questoes), servico.MAX_QUESTOES))
        except ValueError:
            total = prova.total_questoes
        letras = []
        for numero in range(1, total + 1):
            letra = (request.form.get(f"q{numero}") or "-").strip().upper()
            letras.append(letra if letra in (*ALTERNATIVAS, ANULADA) else "-")
        prova.total_questoes = total
        prova.gabarito = "".join(letras)
        prova.titulo = (request.form.get("titulo") or prova.titulo).strip()[:200] or prova.titulo
        quer_publicar = bool(request.form.get("ativo"))
        if quer_publicar and not prova.gabarito_completo:
            prova.ativo = False
            flash("Gabarito salvo, mas a prova só é publicada com todas as questões preenchidas.", "warning")
        else:
            prova.ativo = quer_publicar
            flash("Prova publicada para as estagiárias." if quer_publicar else "Gabarito salvo (prova oculta).",
                  "success")
        db.session.commit()
        return redirect(url_for("concursos.gabarito", prova_id=prova.id))
    return render_template("concursos/gabarito.html", prova=prova, gestor=True,
                           alternativas=(*ALTERNATIVAS, ANULADA))


@bp.route("/prova/<int:prova_id>/pdf")
@login_required
def pdf(prova_id):
    _exigir(servico.pode_estudar(current_user))
    prova = _prova(prova_id)
    if not prova.pdf_prova:
        abort(404)
    resposta = send_file(BytesIO(prova.pdf_prova), mimetype="application/pdf",
                         download_name=prova.pdf_nome or "prova.pdf", as_attachment=False)
    # A folha de respostas mostra o PDF num iframe da própria página.
    resposta.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    resposta.headers["X-Frame-Options"] = "SAMEORIGIN"
    resposta.headers["Cache-Control"] = "private, max-age=3600"
    return resposta


@bp.route("/prova/<int:prova_id>")
@login_required
def prova(prova_id):
    _exigir(servico.pode_estudar(current_user))
    prova = _prova(prova_id)
    tentativa = servico.tentativa_aberta(prova, current_user)
    if tentativa is None:
        tentativa = ConcursoTentativa(prova_id=prova.id, user_id=current_user.id, respostas="{}")
        db.session.add(tentativa)
        db.session.commit()
    return render_template("concursos/prova.html", prova=prova, tentativa=tentativa,
                           folha=servico.folha(prova, tentativa), alternativas=ALTERNATIVAS,
                           gestor=servico.pode_gerenciar(current_user))


def _minha_tentativa_aberta(tentativa_id):
    tentativa = db.session.get(ConcursoTentativa, tentativa_id)
    if tentativa is None or tentativa.user_id != current_user.id:
        abort(404)
    if tentativa.entregue_em:
        abort(409)
    return tentativa


@bp.route("/tentativa/<int:tentativa_id>/marcar", methods=["POST"])
@login_required
def marcar(tentativa_id):
    tentativa = _minha_tentativa_aberta(tentativa_id)
    dados = request.get_json(silent=True) or request.form
    try:
        numero = int(dados.get("questao"))
    except (TypeError, ValueError):
        abort(400)
    letra = (dados.get("letra") or "").strip().upper()
    if not 1 <= numero <= tentativa.prova.total_questoes or letra not in (*ALTERNATIVAS, ""):
        abort(400)
    marcacoes = tentativa.marcacoes
    if letra:
        marcacoes[numero] = letra
    else:
        marcacoes.pop(numero, None)
    tentativa.marcacoes = marcacoes
    tentativa.atualizada_em = utcnow()
    db.session.commit()
    return jsonify(ok=True, respondidas=len(marcacoes), total=tentativa.prova.total_questoes)


@bp.route("/tentativa/<int:tentativa_id>/entregar", methods=["POST"])
@login_required
def entregar(tentativa_id):
    tentativa = _minha_tentativa_aberta(tentativa_id)
    tentativa.acertos = servico.corrigir(tentativa.prova, tentativa.marcacoes)
    tentativa.entregue_em = utcnow()
    tentativa.atualizada_em = tentativa.entregue_em
    db.session.commit()
    return redirect(url_for("concursos.resultado", tentativa_id=tentativa.id))


@bp.route("/tentativa/<int:tentativa_id>")
@login_required
def resultado(tentativa_id):
    tentativa = db.session.get(ConcursoTentativa, tentativa_id)
    if tentativa is None or not servico.pode_ver_tentativa(current_user, tentativa):
        abort(404)
    if not tentativa.entregue_em:
        if tentativa.user_id == current_user.id:
            return redirect(url_for("concursos.prova", prova_id=tentativa.prova_id))
        abort(404)
    prova = tentativa.prova
    linhas = servico.folha(prova, tentativa, revelar=True)
    return render_template(
        "concursos/resultado.html", prova=prova, tentativa=tentativa, linhas=linhas,
        pct=servico.percentual(tentativa.acertos, prova.total_questoes),
        erradas=sum(1 for linha in linhas if linha["situacao"] == "errada"),
        brancos=sum(1 for linha in linhas if linha["situacao"] == "branco"),
        gestor=servico.pode_gerenciar(current_user),
    )


@bp.route("/acompanhamento")
@login_required
def acompanhamento():
    _exigir(servico.pode_gerenciar(current_user))
    visiveis = servico.alunos_ids_visiveis(current_user)
    consulta = ConcursoTentativa.query.order_by(ConcursoTentativa.atualizada_em.desc())
    if visiveis is not None:
        consulta = consulta.filter(ConcursoTentativa.user_id.in_(visiveis or {0}))
    tentativas = consulta.limit(500).all()
    pessoas = {}
    for t in tentativas:
        pessoa = pessoas.setdefault(t.user_id, {"user": t.user, "tentativas": []})
        pessoa["tentativas"].append(t)
    linhas = []
    for pessoa in pessoas.values():
        entregues = [t for t in pessoa["tentativas"] if t.entregue_em]
        pcts = [servico.percentual(t.acertos, t.prova.total_questoes) for t in entregues]
        linhas.append({
            "user": pessoa["user"],
            "tentativas": pessoa["tentativas"],
            "entregues": len(entregues),
            "media": round(sum(pcts) / len(pcts)) if pcts else None,
            "melhor": max(pcts) if pcts else None,
            "ultima_atividade": pessoa["tentativas"][0].atualizada_em,
        })
    linhas.sort(key=lambda linha: linha["ultima_atividade"], reverse=True)
    return render_template("concursos/acompanhamento.html", linhas=linhas, gestor=True,
                           percentual=servico.percentual)


@bp.app_context_processor
def _porta_secreta():
    """``pode_estudar_concursos()`` nos templates: a corujinha só aparece para quem entra."""
    return {"pode_estudar_concursos": lambda: servico.pode_estudar(current_user)}
