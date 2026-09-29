"""Rotas das simulações com voluntários (grupos de teste dos formulários).

Painel da equipe (acesso interno do SFA):
  /sfa/simulacoes                     → grupos, criação e links de convite
  /sfa/simulacoes/<id>                → participantes e andamento de um grupo
  /sfa/simulacoes/analise?g=1&g=2     → análise por grupo e consolidada
  /sfa/simulacoes/exportar.csv        → dados longos ou largos

Páginas públicas, protegidas pelo token do link:
  /sfa/simulacao/<convite>            → entrada no grupo
  /sfa/simulacao/p/<token>            → painel pessoal do voluntário
  /sfa/simulacao/p/<token>/<etapa>    → ficha SINAN, T0, T7 ou T30
"""
import io
import uuid
from datetime import date
from types import SimpleNamespace

from flask import abort, current_app, flash, make_response, redirect, render_template, request, send_file, url_for
from sqlalchemy.orm import selectinload
from werkzeug.datastructures import MultiDict

COOKIE_PREFIXO = "sfa_sim_"
COOKIE_DIAS = 180


def register(bp, require_access):
    from extensions import csrf, db
    from models.sfa import SfaSimulacaoGrupo, SfaSimulacaoParticipante
    from services import sfa_simulacao as service

    def privado(corpo, status=200):
        resposta = make_response(corpo, status)
        resposta.headers["Cache-Control"] = "no-store, private"
        resposta.headers["Referrer-Policy"] = "no-referrer"
        resposta.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resposta

    def contexto_base():
        return {
            "sim": service,
            "ETAPA_ROTULOS": service.ETAPA_ROTULOS,
            "fmt_dt": service.formatar_data_hora,
            "fmt_num": service.formatar_numero,
            "fmt_pct": service.formatar_pct,
            "fmt_dur": service.formatar_duracao,
        }

    def grupos_com_dados(ids=None):
        consulta = SfaSimulacaoGrupo.query.options(
            selectinload(SfaSimulacaoGrupo.participantes).selectinload(SfaSimulacaoParticipante.respostas))
        if ids:
            consulta = consulta.filter(SfaSimulacaoGrupo.id.in_(ids))
        return consulta.order_by(SfaSimulacaoGrupo.id).all()

    def dados_formulario_grupo():
        return dict(
            nome=request.form.get("nome", ""),
            descricao=request.form.get("descricao", ""),
            etapas=request.form.getlist("etapas"),
            agenda=request.form.get("agenda", "imediata"),
            cenarios={chave: request.form.get(f"cenario_{chave}", "") for chave in ("geral", *service.ETAPAS)},
        )

    def participante_por_token(token):
        return SfaSimulacaoParticipante.query.filter_by(token=token).first_or_404()

    # ------------------------------------------------------------------
    # Painel da equipe
    # ------------------------------------------------------------------

    @bp.route("/simulacoes", methods=["GET", "POST"])
    @require_access
    def simulacoes():
        if request.method == "POST":
            try:
                grupo = service.criar_grupo(creation_key=request.form.get("creation_key", ""), **dados_formulario_grupo())
            except ValueError as exc:
                flash(str(exc), "danger")
            else:
                flash(f"Grupo “{grupo.nome}” criado. Envie o link de convite aos participantes.", "success")
                return redirect(url_for("sfa_routes.simulacao_grupo", grupo_id=grupo.id))
        grupos = grupos_com_dados()
        resumo = []
        for grupo in grupos:
            calendarios = [service.calendario_participante(p) for p in grupo.participantes]
            por_etapa = {e: sum(1 for p in grupo.participantes if e in service.respostas_por_etapa(p))
                         for e in service.etapas_grupo(grupo)}
            resumo.append({"grupo": grupo, "participantes": len(grupo.participantes), "por_etapa": por_etapa,
                           "concluidos": sum(c["concluido"] for c in calendarios),
                           "convite_url": url_for("sfa_routes.simulacao_convite", token=grupo.token_convite, _external=True)})
        return render_template("sfa/simulacoes.html", resumo=resumo, creation_key=uuid.uuid4().hex,
                               form=request.form if request.method == "POST" else MultiDict(), **contexto_base())

    @bp.route("/simulacoes/<int:grupo_id>")
    @require_access
    def simulacao_grupo(grupo_id):
        grupo = (grupos_com_dados([grupo_id]) or [None])[0]
        if grupo is None:
            abort(404)
        linhas = [{"participante": p, "calendario": service.calendario_participante(p),
                   "link": url_for("sfa_routes.simulacao_painel", token=p.token, _external=True)}
                  for p in grupo.participantes]
        return render_template("sfa/simulacao_grupo.html", grupo=grupo, linhas=linhas,
                               etapas=service.etapas_grupo(grupo), cenarios=service.cenarios_grupo(grupo),
                               convite_url=url_for("sfa_routes.simulacao_convite", token=grupo.token_convite, _external=True),
                               **contexto_base())

    @bp.route("/simulacoes/<int:grupo_id>/editar", methods=["POST"])
    @require_access
    def simulacao_grupo_editar(grupo_id):
        grupo = db.get_or_404(SfaSimulacaoGrupo, grupo_id)
        try:
            service.atualizar_grupo(grupo, **dados_formulario_grupo())
            flash("Configurações do grupo atualizadas.", "success")
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        return redirect(url_for("sfa_routes.simulacao_grupo", grupo_id=grupo.id))

    @bp.route("/simulacoes/<int:grupo_id>/status", methods=["POST"])
    @require_access
    def simulacao_grupo_status(grupo_id):
        grupo = db.get_or_404(SfaSimulacaoGrupo, grupo_id)
        aberto = request.form.get("status") == "aberto"
        service.definir_status_grupo(grupo, aberto)
        flash("Grupo reaberto para novas respostas." if aberto else
              "Grupo encerrado. Os dados continuam disponíveis para análise.", "success")
        return redirect(url_for("sfa_routes.simulacao_grupo", grupo_id=grupo.id))

    @bp.route("/simulacoes/<int:grupo_id>/excluir", methods=["POST"])
    @require_access
    def simulacao_grupo_excluir(grupo_id):
        grupo = db.get_or_404(SfaSimulacaoGrupo, grupo_id)
        try:
            service.remover_grupo_vazio(grupo)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("sfa_routes.simulacao_grupo", grupo_id=grupo.id))
        flash("Grupo excluído.", "success")
        return redirect(url_for("sfa_routes.simulacoes"))

    @bp.route("/simulacoes/participante/<int:participante_id>")
    @require_access
    def simulacao_participante(participante_id):
        participante = db.get_or_404(SfaSimulacaoParticipante, participante_id)
        respostas = service.respostas_por_etapa(participante)
        etapas = []
        for etapa in service.ETAPAS:
            resposta = respostas.get(etapa)
            if resposta:
                variaveis = service.variaveis_etapa(etapa)
                rotulos = {var["id"]: var["rotulo"] for var in variaveis}
                etapas.append({"etapa": etapa, "resposta": resposta,
                               "avaliacao": service.carregar_avaliacao(resposta),
                               "erros": [[rotulos.get(item, item) for item in tentativa]
                                         for tentativa in service.carregar_erros(resposta)],
                               "linhas": service.respostas_legiveis(etapa, resposta, respostas, variaveis)})
        return privado(render_template("sfa/simulacao_participante.html", participante=participante,
                                       grupo=participante.grupo, etapas=etapas,
                                       calendario=service.calendario_participante(participante),
                                       link=url_for("sfa_routes.simulacao_painel", token=participante.token, _external=True),
                                       **contexto_base()))

    @bp.route("/simulacoes/participante/<int:participante_id>/excluir", methods=["POST"])
    @require_access
    def simulacao_participante_excluir(participante_id):
        participante = db.get_or_404(SfaSimulacaoParticipante, participante_id)
        grupo_id, codigo = participante.grupo_id, participante.codigo
        service.remover_participante(participante)
        flash(f"Participante {codigo} e as respostas dele foram excluídos.", "success")
        return redirect(url_for("sfa_routes.simulacao_grupo", grupo_id=grupo_id))

    @bp.route("/simulacoes/<int:grupo_id>/qrcode.png")
    @require_access
    def simulacao_qrcode(grupo_id):
        grupo = db.get_or_404(SfaSimulacaoGrupo, grupo_id)
        return qrcode_png(url_for("sfa_routes.simulacao_convite", token=grupo.token_convite, _external=True),
                          f"convite_simulacao_{grupo.id}.png")

    @bp.route("/simulacoes/analise")
    @require_access
    def simulacao_analise():
        todos = SfaSimulacaoGrupo.query.order_by(SfaSimulacaoGrupo.id).all()
        ids = [i for i in request.args.getlist("g", type=int) if i]
        grupos = grupos_com_dados(ids or [g.id for g in todos]) if todos else []
        analise = service.montar_analise(grupos) if grupos else {"vazio": True}
        etapa = request.args.get("etapa", "")
        disponiveis = analise.get("etapas_com_resposta", [])
        if etapa not in disponiveis:
            etapa = disponiveis[0] if disponiveis else ""
        visao = "consolidado" if request.args.get("visao") == "consolidado" else "comparar"
        selecionados = {g.id for g in grupos}
        # A cor segue o grupo (posição entre todos), nunca a ordem do filtro.
        cores = {g.id: service.COR_GRUPOS[i] if i < len(service.COR_GRUPOS) else service.COR_EXCEDENTE
                 for i, g in enumerate(todos)}
        cores_coluna = {"todos": service.COR_CONSOLIDADO, **{str(i): cor for i, cor in cores.items()}}
        return render_template("sfa/simulacao_analise.html", analise=analise, todos=todos, selecionados=selecionados,
                               etapa=etapa, visao=visao, ids=sorted(selecionados), cores=cores,
                               cores_coluna=cores_coluna, **contexto_base())

    @bp.route("/simulacoes/exportar.csv")
    @require_access
    def simulacao_exportar():
        ids = [i for i in request.args.getlist("g", type=int) if i]
        grupos = grupos_com_dados(ids or None)
        formato = "largo" if request.args.get("formato") == "largo" else "longo"
        texto = service.exportar_csv_largo(grupos) if formato == "largo" else service.exportar_csv_longo(grupos)
        resposta = current_app.response_class("﻿" + texto, mimetype="text/csv; charset=utf-8")
        resposta.headers["Content-Disposition"] = (
            f'attachment; filename="simulacao_sfa_{formato}_{date.today().isoformat()}.csv"')
        resposta.headers["Cache-Control"] = "no-store, private"
        return resposta

    # ------------------------------------------------------------------
    # Páginas do voluntário
    # ------------------------------------------------------------------

    def qrcode_png(alvo, nome):
        import qrcode

        imagem = qrcode.make(alvo)
        buffer = io.BytesIO()
        imagem.save(buffer, format="PNG")
        buffer.seek(0)
        resposta = send_file(buffer, mimetype="image/png", download_name=nome)
        resposta.headers["Cache-Control"] = "no-store, private"
        return resposta

    def aviso(titulo, mensagem, participante=None, status=200, tom="info"):
        return privado(render_template("sfa/simulacao_aviso.html", titulo=titulo, mensagem=mensagem,
                                       participante=participante, tom=tom, **contexto_base()), status)

    # Formulários públicos: o token do link é a credencial e não há sessão
    # autenticada, como em /sfa/p/<token>. Sem CSRF para que uma ficha longa
    # não se perca quando o token de sessão expira no meio do preenchimento.
    @bp.route("/simulacao/<token>", methods=["GET", "POST"])
    @csrf.exempt
    def simulacao_convite(token):
        grupo = SfaSimulacaoGrupo.query.filter_by(token_convite=token).first_or_404()
        cookie = request.cookies.get(f"{COOKIE_PREFIXO}{grupo.id}", "")
        existente = (SfaSimulacaoParticipante.query.filter_by(token=cookie, grupo_id=grupo.id).first()
                     if cookie else None)
        erro = ""
        if request.method == "POST":
            if str(request.form.get("website") or "").strip():
                return redirect(url_for("sfa_routes.simulacao_convite", token=token))
            if request.form.get("ciente") != "sim":
                erro = "Confirme que entendeu que é uma simulação e que vai usar apenas dados fictícios."
            else:
                try:
                    participante = service.inscrever_participante(
                        grupo, request.form.get("apelido", ""), request.form.get("perfil", ""),
                        request.form.get("experiencia", ""))
                except ValueError as exc:
                    erro = str(exc)
                else:
                    resposta = redirect(url_for("sfa_routes.simulacao_painel", token=participante.token, novo=1))
                    resposta.set_cookie(f"{COOKIE_PREFIXO}{grupo.id}", participante.token,
                                        max_age=COOKIE_DIAS * 86400, httponly=True, samesite="Lax",
                                        secure=request.is_secure, path="/sfa/simulacao")
                    resposta.headers["Cache-Control"] = "no-store, private"
                    return resposta
        return privado(render_template("sfa/simulacao_convite.html", grupo=grupo, existente=existente, erro=erro,
                                       etapas=service.etapas_grupo(grupo), cenarios=service.cenarios_grupo(grupo),
                                       form=request.form, **contexto_base()), 400 if erro else 200)

    @bp.route("/simulacao/p/<token>")
    def simulacao_painel(token):
        participante = participante_por_token(token)
        feito = request.args.get("feito", "")
        return privado(render_template(
            "sfa/simulacao_painel.html", participante=participante, grupo=participante.grupo,
            calendario=service.calendario_participante(participante), cenarios=service.cenarios_grupo(participante.grupo),
            link=url_for("sfa_routes.simulacao_painel", token=token, _external=True),
            novo=request.args.get("novo") == "1", feito=feito if feito in service.ETAPAS else "", **contexto_base()))

    @bp.route("/simulacao/p/<token>/qrcode.png")
    def simulacao_painel_qrcode(token):
        participante = participante_por_token(token)
        return qrcode_png(url_for("sfa_routes.simulacao_painel", token=participante.token, _external=True),
                          "meu_link_simulacao.png")

    def renderizar_etapa(participante, etapa, schema, *, valores=None, erros=None, submetido=None,
                         inicio="", erros_json="[]", status=200):
        grupo = participante.grupo
        cenarios = service.cenarios_grupo(grupo)
        simulacao = {
            "grupo": grupo, "participante": participante, "etapa": etapa,
            "etapa_rotulo": service.ETAPA_ROTULOS[etapa],
            "cenario_geral": cenarios.get("geral", ""), "cenario_etapa": cenarios.get(etapa, ""),
            "inicio": inicio or service.assinar_inicio(participante, etapa), "erros_json": erros_json,
            "painel_url": url_for("sfa_routes.simulacao_painel", token=participante.token),
        }
        acao = url_for("sfa_routes.simulacao_etapa", token=participante.token, etapa=etapa)
        if etapa == "sinan":
            corpo = render_template("sfa/pre_t0_form.html", schema=schema, error=(erros or {}).get("__all__", ""),
                                    submitted=submetido if submetido is not None else MultiDict(),
                                    form_action=acao, simulacao=simulacao)
        else:
            corpo = render_template(
                "sfa/t0_form.html", schema=schema, values=valores or {}, errors=erros or {},
                paciente=SimpleNamespace(nome=participante.apelido or participante.codigo),
                form_name=f"{service.ETAPA_ROTULOS[etapa]} · simulação", form_stage=etapa, simulacao=simulacao)
        return privado(corpo, status)

    @bp.route("/simulacao/p/<token>/<etapa>", methods=["GET", "POST"])
    @csrf.exempt
    def simulacao_etapa(token, etapa):
        from services.sfa_service import iterar_campos_form

        if etapa not in service.ETAPAS:
            abort(404)
        participante = participante_por_token(token)
        calendario = service.calendario_participante(participante)
        item = next((i for i in calendario["etapas"] if i["etapa"] == etapa), None)
        if item is None:
            abort(404)
        if item["status"] == "respondida":
            return aviso(f"{item['rotulo']} já respondid{'a' if etapa == 'sinan' else 'o'}",
                         "Esta etapa já foi registrada. Cada etapa é respondida uma única vez.", participante)
        if item["status"] != "disponivel":
            return aviso(f"{item['rotulo']} ainda não está disponível", item["motivo"], participante, 409, "espera")

        schema = service.schema_etapa(etapa, participante)
        if request.method == "GET":
            valores = service.valores_iniciais(etapa, schema, participante) if etapa != "sinan" else None
            return renderizar_etapa(participante, etapa, schema, valores=valores)

        if etapa == "sinan" and str(request.form.get("website") or "").strip():
            return redirect(url_for("sfa_routes.simulacao_painel", token=token))
        if request.content_length and request.content_length > 262144:
            abort(413)
        inicio = service.inicio_valido_ou_novo(request.form.get("sim_inicio", ""), participante, etapa)
        dados, erros = service.coletar_etapa(etapa, schema, request.form, participante)
        if erros:
            erros_json = service.acumular_erros(request.form.get("sim_erros", ""), erros)
            valores = None
            if etapa != "sinan":
                valores = {}
                for campo in iterar_campos_form(schema):
                    chave = campo["key"]
                    valores[chave] = (request.form.getlist(chave) if campo.get("type") == "checkboxes"
                                      else str(request.form.get(chave) or "").strip())
            return renderizar_etapa(participante, etapa, schema, valores=valores, erros=erros,
                                    submetido=request.form, inicio=inicio, erros_json=erros_json, status=400)
        service.salvar_resposta(participante, etapa, dados, schema, inicio, request.form.get("sim_erros", ""))
        return redirect(url_for("sfa_routes.simulacao_avaliacao", token=token, etapa=etapa))

    @bp.route("/simulacao/p/<token>/<etapa>/avaliacao", methods=["GET", "POST"])
    @csrf.exempt
    def simulacao_avaliacao(token, etapa):
        if etapa not in service.ETAPAS:
            abort(404)
        participante = participante_por_token(token)
        resposta = service.respostas_por_etapa(participante).get(etapa)
        if resposta is None:
            return redirect(url_for("sfa_routes.simulacao_etapa", token=token, etapa=etapa))
        erro = ""
        if request.method == "POST":
            if request.form.get("acao") == "pular":
                return redirect(url_for("sfa_routes.simulacao_painel", token=token, feito=etapa))
            try:
                service.registrar_avaliacao(resposta, request.form)
            except ValueError as exc:
                erro = str(exc)
            else:
                return redirect(url_for("sfa_routes.simulacao_painel", token=token, feito=etapa))
        return privado(render_template(
            "sfa/simulacao_avaliacao.html", participante=participante, grupo=participante.grupo, etapa=etapa,
            resposta=resposta, avaliacao=service.carregar_avaliacao(resposta), erro=erro,
            form=request.form if request.method == "POST" else None,
            calendario=service.calendario_participante(participante), **contexto_base()), 400 if erro else 200)
