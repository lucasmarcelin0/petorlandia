"""Bulário de Medicamentos (somente admin) — views reais do domínio.

Primeiro domínio migrado do app.py monolítico: as views vivem aqui e o
blueprint é registrado por blueprint_utils.register_domain_blueprints, que
também cria aliases de endpoint sem prefixo (url_for('bulario') continua
funcionando).
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
from sqlalchemy import Text, cast, or_

from extensions import db
from time_utils import now_in_brazil

bp = Blueprint("bulario_routes", __name__)


def _is_admin():
    """Resolve via módulo app em tempo de request.

    Testes fazem monkeypatch de ``app._is_admin``; a indireção mantém esse
    contrato (o lazy_view antigo também resolvia tarde).
    """
    import app as app_module

    return app_module._is_admin()


@bp.route("/bulario/curadoria", methods=["GET"])
@login_required
def bulario_curadoria():
    """Fila de curadoria offline dos medicamentos mais prescritos."""
    if not _is_admin():
        abort(403)

    from services.medicamento_curadoria import gerar_ranking_curadoria, listar_reviews

    status = request.args.get("status", "").strip() or None
    limite = request.args.get("limite", 25, type=int) or 25
    limite = max(1, min(limite, 200))
    reviews = listar_reviews(db.session, status=status, limite=200)
    ranking_preview = gerar_ranking_curadoria(db.session, limite=limite)

    return render_template(
        "bulario/curadoria.html",
        reviews=reviews,
        ranking_preview=ranking_preview,
        status=status,
        limite=limite,
    )


@bp.route("/bulario/curadoria/sincronizar", methods=["POST"])
@login_required
def bulario_curadoria_sincronizar():
    """Gera/sincroniza a fila, sem alterar dados clínicos do bulário."""
    if not _is_admin():
        abort(403)

    from services.medicamento_curadoria import sincronizar_fila_curadoria

    limite = request.form.get("limite", 25, type=int) or 25
    limite = max(1, min(limite, 200))
    dry_run = request.form.get("dry_run") == "1"

    try:
        resultado = sincronizar_fila_curadoria(db.session, limite=limite, dry_run=dry_run)
        if dry_run:
            flash(
                f"Dry-run concluído: {resultado['total_candidatos']} candidato(s) avaliados; nada foi gravado.",
                "info",
            )
        else:
            flash(
                f"Fila sincronizada: {resultado['criados']} criado(s), {resultado['atualizados']} atualizado(s).",
                "success",
            )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Falha ao sincronizar curadoria de medicamentos")
        flash(f"Falha ao sincronizar curadoria: {exc}", "danger")

    return redirect(url_for("bulario_curadoria", limite=limite))


@bp.route("/bulario/curadoria/<int:review_id>/status", methods=["POST"])
@login_required
def bulario_curadoria_status(review_id):
    """Atualiza apenas o status da revisão de curadoria."""
    if not _is_admin():
        abort(403)

    from models.base import CuradoriaMedicamentoReview

    review = CuradoriaMedicamentoReview.query.get_or_404(review_id)
    novo_status = (request.form.get("status") or "").strip()
    permitidos = {"pendente", "pesquisado", "revisar", "aprovado", "rejeitado"}
    if novo_status not in permitidos:
        flash("Status de curadoria inválido.", "warning")
        return redirect(url_for("bulario_curadoria"))

    review.status = novo_status
    if novo_status == "aprovado":
        review.aprovado_em = now_in_brazil()
        review.aprovado_por_id = current_user.id
    db.session.commit()
    flash("Status da curadoria atualizado.", "success")
    return redirect(url_for("bulario_curadoria"))


@bp.route("/bulario", methods=["GET"])
@login_required
def bulario():
    """Lista paginada de medicamentos com busca — somente admin."""
    if not _is_admin():
        abort(403)

    from models.base import Medicamento

    q = request.args.get("q", "").strip()
    classificacao = request.args.get("classe", "").strip()
    especie = request.args.get("especie", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 24

    query = Medicamento.query.order_by(Medicamento.nome)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Medicamento.nome.ilike(like),
                Medicamento.principio_ativo.ilike(like),
                Medicamento.classificacao.ilike(like),
            )
        )

    if classificacao:
        query = query.filter(Medicamento.classificacao.ilike(f"%{classificacao}%"))

    if especie in ("caes", "gatos"):
        from models.base import DoseMedicamento
        codes = ["CAES", "AMBOS"] if especie == "caes" else ["GATOS", "AMBOS"]
        sub = db.session.query(DoseMedicamento.medicamento_id).filter(
            DoseMedicamento.especie_code.in_(codes)
        ).subquery()
        query = query.filter(Medicamento.id.in_(sub))

    classes = [
        r[0] for r in
        db.session.query(Medicamento.classificacao)
        .filter(Medicamento.classificacao.isnot(None))
        .distinct()
        .order_by(Medicamento.classificacao)
        .all()
        if r[0]
    ]

    total = query.count()
    paginacao = query.paginate(page=page, per_page=per_page, error_out=False)

    # Agrupamento clínico: 176 classes cruas viram 10 macro-grupos
    # (Antimicrobiano, Antiparasitário, Vacina, etc.) com drill-down.
    from services.bulario import construir_macro_grupos
    macro_grupos, macro_ativo = construir_macro_grupos(classes, classificacao)

    # Batch-load de espécies por med para evitar N+1 nos cards
    from models.base import DoseMedicamento
    med_ids = [m.id for m in paginacao.items]
    especies_por_med = {}
    if med_ids:
        rows = db.session.query(
            DoseMedicamento.medicamento_id,
            DoseMedicamento.especie_code,
        ).filter(
            DoseMedicamento.medicamento_id.in_(med_ids)
        ).distinct().all()
        for mid, code in rows:
            especies_por_med.setdefault(mid, set()).add(code)

    return render_template(
        "bulario/lista.html",
        medicamentos=paginacao.items,
        paginacao=paginacao,
        q=q,
        classificacao=classificacao,
        especie=especie,
        classes=classes,
        total=total,
        macro_grupos=macro_grupos,
        macro_ativo=macro_ativo,
        especies_por_med=especies_por_med,
    )


@bp.route("/bulario/<int:medicamento_id>", methods=["GET"])
@login_required
def bulario_detalhe(medicamento_id):
    """Detalhe de um medicamento do bulário — somente admin."""
    if not _is_admin():
        abort(403)
    from models.base import Medicamento
    from services.bulario import montar_monografia_medicamento, extrair_secoes_vetsmart, vetsmart_url
    # Sem defer: precisamos do conteudo_estruturado para raw_sections e monografia
    med = Medicamento.query.get_or_404(medicamento_id)
    return render_template(
        "bulario/detalhe.html",
        med=med,
        monografia=montar_monografia_medicamento(med),
        secoes_vetsmart=extrair_secoes_vetsmart(med),
        vetsmart_produto_url=vetsmart_url(med),
    )


@bp.route("/bulario/novo", methods=["GET", "POST"])
@login_required
def bulario_novo():
    """Cria um novo medicamento — somente admin."""
    if not _is_admin():
        abort(403)
    from models.base import Medicamento, ApresentacaoMedicamento

    if request.method == "POST":
        med = Medicamento(
            nome                = request.form.get("nome", "").strip()[:100],
            classificacao       = request.form.get("classificacao", "").strip()[:100] or None,
            principio_ativo     = request.form.get("principio_ativo", "").strip()[:200] or None,
            via_administracao   = request.form.get("via_administracao", "").strip()[:80] or None,
            dosagem_recomendada = request.form.get("dosagem_recomendada", "").strip() or None,
            frequencia          = request.form.get("frequencia", "").strip()[:100] or None,
            duracao_tratamento  = request.form.get("duracao_tratamento", "").strip() or None,
            observacoes         = request.form.get("observacoes", "").strip() or None,
            bula                = request.form.get("bula", "").strip() or None,
            created_by          = current_user.id,
        )
        db.session.add(med)
        db.session.flush()

        formas = request.form.getlist("apres_forma[]")
        concs  = request.form.getlist("apres_conc[]")
        for forma, conc in zip(formas, concs):
            forma = forma.strip()[:50]
            conc  = conc.strip()[:100]
            if forma:
                db.session.add(ApresentacaoMedicamento(
                    medicamento_id=med.id, forma=forma, concentracao=conc
                ))

        _salvar_doses_do_form(med.id, request.form)

        db.session.commit()
        flash("Medicamento criado com sucesso.", "success")
        return redirect(url_for("bulario_detalhe", medicamento_id=med.id))

    return render_template("bulario/form.html", med=None, titulo="Novo medicamento")


def _salvar_doses_do_form(medicamento_id, form):
    """Lê os campos `dose_*[]` do form e substitui as doses do medicamento."""
    from models.base import DoseMedicamento
    # remove as existentes
    DoseMedicamento.query.filter_by(medicamento_id=medicamento_id).delete()
    db.session.flush()

    especies   = form.getlist("dose_especie[]")
    pesos      = form.getlist("dose_faixa_peso[]")
    vias       = form.getlist("dose_via[]")
    valores    = form.getlist("dose_valor[]")
    freqs      = form.getlist("dose_frequencia[]")
    duracoes   = form.getlist("dose_duracao[]")
    obs        = form.getlist("dose_observacao[]")

    linhas = zip(especies, pesos, vias, valores, freqs, duracoes, obs)
    for esp, peso, via, dose, freq, dur, o in linhas:
        # Ignora linha totalmente vazia
        if not any(v.strip() for v in (esp, peso, via, dose, freq, dur, o)):
            continue
        db.session.add(DoseMedicamento(
            medicamento_id = medicamento_id,
            especie        = (esp.strip()[:80] or None),
            faixa_peso     = (peso.strip()[:80] or None),
            via            = (via.strip()[:80] or None),
            dose           = (dose.strip()[:200] or None),
            frequencia     = (freq.strip()[:120] or None),
            duracao        = (dur.strip()[:120] or None),
            observacao     = (o.strip() or None),
        ))


@bp.route("/bulario/<int:medicamento_id>/editar", methods=["GET", "POST"])
@login_required
def bulario_editar(medicamento_id):
    """Edita um medicamento existente — somente admin."""
    if not _is_admin():
        abort(403)
    from models.base import Medicamento, ApresentacaoMedicamento

    med = Medicamento.query.get_or_404(medicamento_id)

    if request.method == "POST":
        med.nome                = request.form.get("nome", "").strip()[:100]
        med.classificacao       = request.form.get("classificacao", "").strip()[:100] or None
        med.principio_ativo     = request.form.get("principio_ativo", "").strip()[:200] or None
        med.via_administracao   = request.form.get("via_administracao", "").strip()[:80] or None
        med.dosagem_recomendada = request.form.get("dosagem_recomendada", "").strip() or None
        med.frequencia          = request.form.get("frequencia", "").strip()[:100] or None
        med.duracao_tratamento  = request.form.get("duracao_tratamento", "").strip() or None
        med.observacoes         = request.form.get("observacoes", "").strip() or None
        med.bula                = request.form.get("bula", "").strip() or None

        for apres in list(med.apresentacoes):
            db.session.delete(apres)
        db.session.flush()

        formas = request.form.getlist("apres_forma[]")
        concs  = request.form.getlist("apres_conc[]")
        for forma, conc in zip(formas, concs):
            forma = forma.strip()[:50]
            conc  = conc.strip()[:100]
            if forma:
                db.session.add(ApresentacaoMedicamento(
                    medicamento_id=med.id, forma=forma, concentracao=conc
                ))

        _salvar_doses_do_form(med.id, request.form)

        db.session.commit()
        flash("Medicamento atualizado com sucesso.", "success")
        return redirect(url_for("bulario_detalhe", medicamento_id=med.id))

    return render_template("bulario/form.html", med=med, titulo=f"Editar — {med.nome}")


@bp.route("/bulario/<int:medicamento_id>/excluir", methods=["POST"])
@login_required
def bulario_excluir(medicamento_id):
    """Exclui um medicamento — somente admin."""
    if not _is_admin():
        abort(403)
    from models.base import Medicamento

    med = Medicamento.query.get_or_404(medicamento_id)
    nome = med.nome
    db.session.delete(med)
    db.session.commit()
    flash(f'Medicamento "{nome}" excluído.', "info")
    return redirect(url_for("bulario"))


@bp.route("/api/bulario/buscar", methods=["GET"])
@login_required
def bulario_buscar_api():
    """API JSON para autocomplete de medicamentos (usado em prescrições).

    Busca por nome genérico (Medicamento.nome / principio_ativo) E por nome
    comercial (ApresentacaoMedicamento.nome_comercial).  Quando o termo bate
    num nome comercial, o resultado carrega `nome_exibicao_busca` com o nome
    comercial e `apresentacoes` filtradas para aquela marca — assim buscar
    "Sec Lac" mostra só as concentrações dessa marca.
    """
    from models.base import Medicamento, ApresentacaoMedicamento

    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return jsonify([])

    like = f"%{q}%"

    # 1. Busca genérica por nome do princípio ativo / medicamento
    genericos = (
        Medicamento.query
        .filter(
            or_(
                Medicamento.nome.ilike(like),
                Medicamento.principio_ativo.ilike(like),
                cast(Medicamento.conteudo_estruturado, Text).ilike(like),
            )
        )
        .order_by(Medicamento.nome)
        .limit(15)
        .all()
    )

    # 2. Busca por nome comercial das apresentações
    comerciais = (
        db.session.query(Medicamento, ApresentacaoMedicamento.nome_comercial)
        .join(
            ApresentacaoMedicamento,
            ApresentacaoMedicamento.medicamento_id == Medicamento.id,
        )
        .filter(
            ApresentacaoMedicamento.nome_comercial.isnot(None),
            ApresentacaoMedicamento.nome_comercial != '',
            ApresentacaoMedicamento.nome_comercial.ilike(like),
        )
        .group_by(Medicamento.id, ApresentacaoMedicamento.nome_comercial)
        .order_by(Medicamento.nome, ApresentacaoMedicamento.nome_comercial)
        .limit(10)
        .all()
    )

    from services.bulario import serializar_medicamento_busca

    # IDs que têm match comercial — o resultado comercial tem prioridade e
    # suprime o resultado genérico do mesmo medicamento.  Isso garante que
    # buscar "Sec Lac" mostre apenas a entrada filtrada por marca, e buscar
    # "metergolina" mostre todas as apresentações sem split por comercial.
    ids_com_match_comercial = {med.id for med, _ in comerciais}

    seen: set = set()
    output = []

    for med in genericos:
        if med.id in ids_com_match_comercial:
            continue  # resultado comercial tem prioridade
        key = (med.id, None)
        if key not in seen:
            seen.add(key)
            output.append(serializar_medicamento_busca(med))

    for med, nome_comercial in comerciais:
        key = (med.id, nome_comercial)
        if key not in seen:
            seen.add(key)
            output.append(
                serializar_medicamento_busca(
                    med,
                    nome_exibicao=nome_comercial,
                    nome_comercial_filtro=nome_comercial,
                )
            )

    return jsonify(output)


@bp.route("/api/bulario/sugerir-dose", methods=["GET"])
@login_required
def bulario_sugerir_dose_api():
    """API JSON: dado um medicamento + animal, devolve uma sugestão de dose
    pré-calculada (peso × mg/kg) ou indica que não há protocolo aplicável.

    Query params:
      - medicamento_id (int, obrigatório)
      - animal_id      (int, obrigatório)
      - indicacao      (str, opcional) — 'Alergia', 'Imunossupressão', etc.
        Quando há mais de uma indicação disponível e o cliente não passou
        nenhuma, a resposta vem em modo "multiplo" com a lista de opções.
    """
    from models.base import Medicamento, Animal
    from services.bulario import sugerir_dose

    med_id = request.args.get("medicamento_id", type=int)
    animal_id = request.args.get("animal_id", type=int)
    indicacao = (request.args.get("indicacao") or "").strip() or None
    nome_comercial_filtro = (request.args.get("nome_comercial_filtro") or "").strip() or None
    if not med_id or not animal_id:
        return jsonify({
            "disponivel": False,
            "motivo": "Parâmetros medicamento_id e animal_id são obrigatórios.",
        }), 400

    med = Medicamento.query.get(med_id)
    if med is None:
        return jsonify({"disponivel": False, "motivo": "Medicamento não encontrado."}), 404

    animal = Animal.query.get(animal_id)
    if animal is None:
        return jsonify({"disponivel": False, "motivo": "Animal não encontrado."}), 404

    # Diagnóstico antes de delegar para o serviço — para que o front consiga
    # explicar por que não há sugestão automática.
    peso = getattr(animal, "peso", None)
    try:
        peso_f = float(peso) if peso is not None else None
    except (TypeError, ValueError):
        peso_f = None
    if not peso_f or peso_f <= 0:
        return jsonify({
            "disponivel": False,
            "motivo": "Peso do animal não está cadastrado — preencha o peso para usar a dose pré-calculada.",
        })

    if not (med.doses or []):
        return jsonify({
            "disponivel": False,
            "motivo": "Este medicamento ainda não tem protocolo de dose cadastrado no bulário.",
        })

    sugestao = sugerir_dose(
        med, animal,
        indicacao=indicacao,
        nome_comercial_filtro=nome_comercial_filtro,
    )
    if not sugestao:
        return jsonify({
            "disponivel": False,
            "motivo": "Não há protocolo aplicável para a espécie/peso deste animal.",
        })

    # Converte Decimals → float para JSON
    def _safe(v):
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return v

    sugestao["peso_kg"]    = _safe(sugestao.get("peso_kg"))
    sugestao["dose_min"]   = _safe(sugestao.get("dose_min"))
    sugestao["dose_media"] = _safe(sugestao.get("dose_media"))
    sugestao["dose_max"]   = _safe(sugestao.get("dose_max"))

    # Modo "múltiplas indicações": front exibe dropdown e recompõe a chamada
    nome_exibir = nome_comercial_filtro or med.nome
    if sugestao.get("multiplo"):
        return jsonify({
            "disponivel": True,
            "multiplo": True,
            "medicamento": {
                "id": med.id,
                "nome": nome_exibir,
                "principio_ativo": med.principio_ativo or "",
            },
            "animal": {
                "id": animal.id,
                "nome": getattr(animal, "name", None) or getattr(animal, "nome", None) or "",
                "especie": (getattr(getattr(animal, "species", None), "name", None) or ""),
                "peso_kg": peso_f,
            },
            "indicacoes": sugestao.get("indicacoes", []),
        })

    return jsonify({
        "disponivel": True,
        "multiplo": False,
        "medicamento": {
            "id": med.id,
            "nome": nome_exibir,
            "principio_ativo": med.principio_ativo or "",
        },
        "animal": {
            "id": animal.id,
            "nome": getattr(animal, "name", None) or getattr(animal, "nome", None) or "",
            "especie": (getattr(getattr(animal, "species", None), "name", None) or ""),
            "peso_kg": peso_f,
        },
        "sugestao": sugestao,
    })


def get_blueprint():
    return bp
