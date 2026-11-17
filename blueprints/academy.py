"""Marcelino Academy: curso de inglês como mini app do PetOrlândia.

Telas (todas exigem login):

* ``/academy/`` — matérias de quem acessa; o administrador cria matérias;
* ``/academy/materia/<id>`` — lições, link da aula ao vivo; o professor edita,
  matricula alunos e vê o desempenho da turma;
* ``/academy/licao/<id>`` — texto da lição, testes e comentários;
* ``/academy/licao/<id>/editar`` — o professor monta testes e questões;
* ``/academy/correcoes`` — respostas abertas aguardando a nota do professor.
"""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from services import academy as servico
from services.academy import AcademyErro
from time_utils import utcnow

bp = Blueprint("academy", __name__, url_prefix="/academy")


def get_blueprint():
    return bp


def _exigir(condicao):
    if not condicao:
        abort(403)


def _obter(modelo, ident):
    obj = db.session.get(modelo, ident)
    if obj is None:
        abort(404)
    return obj


def _int(valor, padrao=0):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def _salvar(destino, mensagem=None):
    """Commit e volta; erro de preenchimento vira aviso sem gravar nada."""
    db.session.commit()
    servico.limpar_cache()
    if mensagem:
        flash(mensagem, "success")
    return redirect(destino)


def _erro(exc, destino):
    db.session.rollback()
    flash(str(exc), "warning")
    return redirect(destino)


@bp.context_processor
def _contexto():
    from models.academy import TIPOS_QUESTAO
    return dict(TIPOS_QUESTAO=TIPOS_QUESTAO, PAPEIS=servico.PAPEIS,
                academy_admin=servico.eh_admin(current_user),
                academy_professor=servico.eh_professor_de_alguma(current_user)
                if getattr(current_user, "is_authenticated", False) else False)


# ---------------------------------------------------------------- aluno

@bp.route("/")
@login_required
def inicio():
    _exigir(servico.tem_acesso(current_user))
    return render_template("academy/inicio.html", materias=servico.materias_visiveis(current_user))


@bp.route("/materia/<int:materia_id>")
@login_required
def materia(materia_id):
    from models.academy import AcademyLicao, AcademyMateria
    m = _obter(AcademyMateria, materia_id)
    _exigir(servico.pode_ver(current_user, m))
    professor = servico.eh_professor(current_user, m)
    licoes = m.licoes if professor else m.licoes.filter(AcademyLicao.publicada.is_(True))
    return render_template("academy/materia.html", materia=m, licoes=licoes.all(), professor=professor,
                           vinculos=servico.vinculos_da_materia(m) if professor else [],
                           turma=servico.desempenho_da_turma(m) if professor else [])


@bp.route("/licao/<int:licao_id>", methods=["GET", "POST"])
@login_required
def licao(licao_id):
    from models.academy import AcademyComentario, AcademyLicao
    item = _obter(AcademyLicao, licao_id)
    _exigir(servico.pode_ver(current_user, item.materia))
    professor = servico.eh_professor(current_user, item.materia)
    if not item.publicada and not professor:
        abort(404)
    destino = url_for(".licao", licao_id=item.id)
    if request.method == "POST":
        try:
            texto = servico.texto_obrigatorio(request.form.get("comentario"), "o comentário", 2000)
        except AcademyErro as exc:
            return _erro(exc, destino + "#comentarios")
        db.session.add(AcademyComentario(licao_id=item.id, user_id=current_user.id, texto=texto))
        return _salvar(destino + "#comentarios", "Comentário publicado.")
    testes = item.testes.all()
    questoes = [q for t in testes for q in t.questoes if q.ativa]
    comentarios = (AcademyComentario.query.filter_by(licao_id=item.id)
                   .order_by(AcademyComentario.id.desc()).limit(100).all())
    return render_template("academy/licao.html", licao=item, testes=testes, professor=professor,
                           respostas=servico.respostas_do_aluno(current_user, questoes),
                           comentarios=comentarios)


@bp.route("/questao/<int:questao_id>/responder", methods=["POST"])
@login_required
def responder(questao_id):
    from models.academy import AcademyQuestao
    q = _obter(AcademyQuestao, questao_id)
    licao_obj = q.teste.licao
    _exigir(servico.pode_ver(current_user, licao_obj.materia))
    destino = url_for(".licao", licao_id=licao_obj.id) + f"#questao-{q.id}"
    if not q.ativa or not licao_obj.publicada:
        return _erro(AcademyErro("Esta questão não está mais disponível."), destino)
    try:
        resposta = servico.responder(q, current_user, request.form)
    except AcademyErro as exc:
        return _erro(exc, destino)
    if resposta.nota is None:
        mensagem = "Resposta enviada. O professor vai corrigir."
    else:
        mensagem = "Resposta certa!" if resposta.nota == 1 else "Resposta errada. Veja o gabarito abaixo da questão."
    return _salvar(destino, mensagem)


@bp.route("/teste/<int:teste_id>/resultado")
@login_required
def resultado(teste_id):
    from models import User
    from models.academy import AcademyTeste
    teste = _obter(AcademyTeste, teste_id)
    m = teste.licao.materia
    _exigir(servico.pode_ver(current_user, m))
    aluno = current_user
    aluno_id = request.args.get("aluno", type=int)
    if aluno_id and aluno_id != current_user.id:
        _exigir(servico.eh_professor(current_user, m))
        aluno = _obter(User, aluno_id)
    questoes = [q for q in teste.questoes if q.ativa]
    respostas = servico.respostas_do_aluno(aluno, questoes)
    return render_template("academy/resultado.html", teste=teste, aluno=aluno, questoes=questoes,
                           respostas=respostas, certas=sum(1 for r in respostas.values() if r.nota == 1))


# ---------------------------------------------------------------- administração e professor

@bp.route("/materias", methods=["POST"])
@login_required
def criar_materia():
    from models.academy import AcademyMateria
    _exigir(servico.eh_admin(current_user))
    try:
        m = AcademyMateria(nome=servico.texto_obrigatorio(request.form.get("nome"), "o nome", 150),
                           criado_por=servico.assinatura(current_user))
    except AcademyErro as exc:
        return _erro(exc, url_for(".inicio"))
    db.session.add(m)
    db.session.flush()
    return _salvar(url_for(".materia", materia_id=m.id) + "#editar", "Matéria criada. Agora adicione professores e lições.")


@bp.route("/materia/<int:materia_id>", methods=["POST"])
@login_required
def editar_materia(materia_id):
    from models.academy import AcademyMateria
    m = _obter(AcademyMateria, materia_id)
    _exigir(servico.eh_professor(current_user, m))
    destino = url_for(".materia", materia_id=m.id)
    form = request.form
    try:
        m.nome = servico.texto_obrigatorio(form.get("nome"), "o nome", 150)
        m.descricao = (form.get("descricao") or "").strip()[:5000] or None
        m.horario = (form.get("horario") or "").strip()[:60] or None
        m.link_aula = servico.url_valida(form.get("link_aula"))
    except AcademyErro as exc:
        return _erro(exc, destino + "#editar")
    if servico.eh_admin(current_user) and "ativo" in form:
        m.ativo = form.get("ativo") == "1"
    return _salvar(destino, "Matéria atualizada.")


@bp.route("/materia/<int:materia_id>/pessoas", methods=["POST"])
@login_required
def adicionar_pessoa(materia_id):
    from models.academy import AcademyMateria
    m = _obter(AcademyMateria, materia_id)
    _exigir(servico.eh_professor(current_user, m))
    papel = request.form.get("papel") or "aluno"
    # Professor matricula alunos; só o administrador nomeia professores.
    _exigir(papel == "aluno" or servico.eh_admin(current_user))
    destino = url_for(".materia", materia_id=m.id) + "#pessoas"
    try:
        v = servico.vincular(m, request.form.get("email"), papel, current_user)
    except AcademyErro as exc:
        return _erro(exc, destino)
    db.session.flush()
    return _salvar(destino, f"{v.user.name or v.user.email} agora é {servico.PAPEIS[papel].lower()} de {m.nome}.")


@bp.route("/vinculo/<int:vinculo_id>/revogar", methods=["POST"])
@login_required
def revogar(vinculo_id):
    from models.academy import AcademyVinculo
    v = _obter(AcademyVinculo, vinculo_id)
    _exigir(servico.eh_professor(current_user, v.materia))
    _exigir(v.papel == "aluno" or servico.eh_admin(current_user))
    if v.revogado_em is None:
        servico.revogar(v, current_user)
    return _salvar(url_for(".materia", materia_id=v.materia_id) + "#pessoas", "Acesso encerrado.")


@bp.route("/materia/<int:materia_id>/licoes", methods=["POST"])
@login_required
def criar_licao(materia_id):
    from models.academy import AcademyLicao, AcademyMateria
    m = _obter(AcademyMateria, materia_id)
    _exigir(servico.eh_professor(current_user, m))
    try:
        titulo = servico.texto_obrigatorio(request.form.get("titulo"), "o título", 150)
    except AcademyErro as exc:
        return _erro(exc, url_for(".materia", materia_id=m.id))
    ultima = m.licoes.order_by(AcademyLicao.ordem.desc()).first()
    item = AcademyLicao(materia_id=m.id, titulo=titulo, ordem=(ultima.ordem + 1) if ultima else 1, publicada=False)
    db.session.add(item)
    db.session.flush()
    return _salvar(url_for(".editar_licao", licao_id=item.id),
                   "Lição criada como rascunho. Escreva o conteúdo e publique quando estiver pronta.")


@bp.route("/licao/<int:licao_id>/editar", methods=["GET", "POST"])
@login_required
def editar_licao(licao_id):
    from models.academy import AcademyLicao
    item = _obter(AcademyLicao, licao_id)
    _exigir(servico.eh_professor(current_user, item.materia))
    destino = url_for(".editar_licao", licao_id=item.id)
    if request.method == "POST":
        form = request.form
        try:
            item.titulo = servico.texto_obrigatorio(form.get("titulo"), "o título", 150)
            item.conteudo = (form.get("conteudo") or "").strip()[:50000] or None
            item.link_video = servico.url_valida(form.get("link_video"))
        except AcademyErro as exc:
            return _erro(exc, destino)
        item.ordem = _int(form.get("ordem"), item.ordem)
        item.publicada = form.get("publicada") == "1"
        return _salvar(destino, "Lição salva.")
    return render_template("academy/licao_editar.html", licao=item, testes=item.testes.all())


@bp.route("/licao/<int:licao_id>/testes", methods=["POST"])
@login_required
def criar_teste(licao_id):
    from models.academy import AcademyLicao, AcademyTeste
    item = _obter(AcademyLicao, licao_id)
    _exigir(servico.eh_professor(current_user, item.materia))
    destino = url_for(".editar_licao", licao_id=item.id)
    try:
        nome = servico.texto_obrigatorio(request.form.get("nome"), "o nome do teste", 150)
    except AcademyErro as exc:
        return _erro(exc, destino)
    teste = AcademyTeste(licao_id=item.id, nome=nome)
    db.session.add(teste)
    db.session.flush()
    return _salvar(destino + f"#teste-{teste.id}", "Teste criado. Adicione as questões.")


@bp.route("/teste/<int:teste_id>", methods=["POST"])
@login_required
def renomear_teste(teste_id):
    from models.academy import AcademyTeste
    teste = _obter(AcademyTeste, teste_id)
    _exigir(servico.eh_professor(current_user, teste.licao.materia))
    destino = url_for(".editar_licao", licao_id=teste.licao_id) + f"#teste-{teste.id}"
    try:
        teste.nome = servico.texto_obrigatorio(request.form.get("nome"), "o nome do teste", 150)
    except AcademyErro as exc:
        return _erro(exc, destino)
    return _salvar(destino, "Teste renomeado.")


@bp.route("/teste/<int:teste_id>/questoes", methods=["POST"])
@login_required
def criar_questao(teste_id):
    from models.academy import AcademyQuestao, AcademyTeste
    teste = _obter(AcademyTeste, teste_id)
    _exigir(servico.eh_professor(current_user, teste.licao.materia))
    destino = url_for(".editar_licao", licao_id=teste.licao_id) + f"#teste-{teste.id}"
    form = request.form
    ultima = teste.questoes.order_by(None).order_by(AcademyQuestao.ordem.desc()).first()
    q = AcademyQuestao(teste_id=teste.id, ordem=(ultima.ordem + 1) if ultima else 1)
    try:
        servico.aplicar_questao(q, form.get("enunciado"), form.get("tipo"), form.get("opcoes"))
    except AcademyErro as exc:
        return _erro(exc, destino)
    db.session.add(q)
    return _salvar(destino, "Questão adicionada.")


@bp.route("/questao/<int:questao_id>/editar", methods=["GET", "POST"])
@login_required
def editar_questao(questao_id):
    from models.academy import AcademyQuestao, AcademyResposta
    q = _obter(AcademyQuestao, questao_id)
    _exigir(servico.eh_professor(current_user, q.teste.licao.materia))
    voltar = url_for(".editar_licao", licao_id=q.teste.licao_id) + f"#teste-{q.teste_id}"
    respondida = AcademyResposta.query.filter_by(questao_id=q.id).count()
    if request.method == "POST":
        form = request.form
        if form.get("acao") in {"desativar", "reativar"}:
            q.ativa = form.get("acao") == "reativar"
            return _salvar(voltar, "Questão reativada." if q.ativa else "Questão retirada do teste. As respostas já dadas ficam no histórico.")
        try:
            servico.aplicar_questao(q, form.get("enunciado"), form.get("tipo"), form.get("opcoes"))
        except AcademyErro as exc:
            return _erro(exc, url_for(".editar_questao", questao_id=q.id))
        q.ordem = _int(form.get("ordem"), q.ordem)
        return _salvar(voltar, "Questão salva.")
    return render_template("academy/questao_editar.html", questao=q, respondida=respondida,
                           opcoes_texto=servico.opcoes_como_texto(q))


@bp.route("/correcoes")
@login_required
def correcoes():
    _exigir(servico.eh_professor_de_alguma(current_user))
    return render_template("academy/correcoes.html", pendentes=servico.pendentes_de_correcao(current_user))


@bp.route("/resposta/<int:resposta_id>/corrigir", methods=["POST"])
@login_required
def corrigir(resposta_id):
    from models.academy import AcademyResposta
    r = _obter(AcademyResposta, resposta_id)
    _exigir(servico.eh_professor(current_user, r.questao.teste.licao.materia))
    nota = request.form.get("nota")
    if nota not in {"0", "1"}:
        return _erro(AcademyErro("Escolha certa ou errada."), url_for(".correcoes"))
    r.nota = int(nota)
    r.observacao = (request.form.get("observacao") or "").strip()[:2000] or None
    r.corrigida_por = servico.assinatura(current_user)
    r.corrigida_em = utcnow()
    if request.form.get("voltar") == "resultado":
        destino = url_for(".resultado", teste_id=r.questao.teste_id, aluno=r.user_id)
    else:
        destino = url_for(".correcoes")
    return _salvar(destino, "Correção registrada.")
