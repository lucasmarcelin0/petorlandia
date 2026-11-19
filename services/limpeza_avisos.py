"""Prefeitura integrada: avisa os responsáveis quando surge tarefa e quando ela é concluída.

Quem recebe:

* **tarefa nova** (comunicação da população ou vinda do Casa a Casa): quem tem
  papel vigente que comprova e enxerga aquele tipo de problema;
* **tarefa concluída** (comprovação com foto): a mesma equipe e a fiscalização
  (quem recusa) daquele tipo, para conferir;
* **tarefa de volta à fila** (comprovação recusada ou comunicação reaberta):
  a equipe do tipo e, na recusa, quem fez a comprovação recusada.

Quem fez a ação não recebe o próprio aviso. Administrador não entra na lista:
ele vê tudo e não é equipe; quem precisa receber ganha um papel. Papel "só as
próprias" também fica de fora, porque não atende comunicação de outras pessoas.

O aviso sai pelo celular (Web Push, para quem ativou as notificações no
aparelho) e por e-mail. Os destinatários são calculados na transação da ação;
o envio só acontece depois do commit (rollback descarta), numa thread, para a
pessoa que comunicou ou comprovou não esperar o servidor de e-mail.
"""
from __future__ import annotations

import threading

from flask import current_app, has_request_context, url_for
from sqlalchemy import event

_PENDENTES = "limpeza_avisos_pendentes"
TITULO_APP = "Prefeitura integrada"
SITE = "https://www.petorlandia.com.br"
EVENTOS = ("comunicada", "reaberta", "comprovada", "comprovacao_recusada")


def _endereco(solicitacao_id: int) -> tuple[str, str]:
    """(caminho para o push, endereço completo para o e-mail)."""
    caminho = f"/limpeza-urbana/solicitacao/{solicitacao_id}"
    if has_request_context():
        try:
            caminho = url_for("limpeza_urbana.solicitacao", solicitacao_id=solicitacao_id)
            return caminho, url_for("limpeza_urbana.solicitacao", solicitacao_id=solicitacao_id, _external=True)
        except Exception:  # noqa: BLE001 - blueprint ausente em algum contexto: usa o caminho fixo
            pass
    return caminho, SITE + caminho


def responsaveis(solicitacao, permissoes) -> list:
    """Contas com papel vigente que tenha alguma das ``permissoes`` e enxergue o tipo da comunicação."""
    from extensions import db
    from models import User
    from models.limpeza import LimpezaAcesso
    from services import limpeza_urbana as servico

    tipos_da_comunicacao = set(solicitacao.lista_categorias)
    ids = {a.user_id for a in LimpezaAcesso.query.filter_by(revogado_em=None).all()}
    contas = []
    for user in (db.session.get(User, uid) for uid in sorted(ids)):
        if user is None or servico.eh_admin(user):
            continue
        _papeis, perms, tipos, so_proprias = servico._vinculos(user)
        if not perms & set(permissoes) or "mapa" not in perms or so_proprias:
            continue
        if tipos is not None and not tipos & tipos_da_comunicacao:
            continue
        contas.append(user)
    return contas


def _ultima_comprovacao(solicitacao_id, status):
    from models.limpeza import LimpezaComprovacao
    return (LimpezaComprovacao.query.filter_by(solicitacao_id=solicitacao_id, status=status)
            .order_by(LimpezaComprovacao.id.desc()).first())


def _montar(tipo, solicitacao, autor_id, detalhe):
    """(ids dos destinatários, título, texto) do aviso, ou ``None`` se o evento não avisa ninguém."""
    from services import limpeza_urbana as servico

    numero = solicitacao.num
    rotulo = servico.rotulo_categorias(solicitacao.categorias)
    local = " — ".join(x for x in (solicitacao.referencia, solicitacao.descricao) if x)
    if tipo == "comunicada":
        destino = responsaveis(solicitacao, ("comprovar",))
        titulo = f"Nova tarefa nº {numero}: {rotulo}"
        texto = (local + ". " if local else "") + "Abra para ver a foto e o ponto no mapa."
        extras = set()
    elif tipo == "comprovada":
        destino = responsaveis(solicitacao, ("comprovar", "recusar"))
        comprovacao = _ultima_comprovacao(solicitacao.id, "valida")
        quem = servico.nome_da_conta(comprovacao.autor) if comprovacao and comprovacao.autor else ""
        titulo = f"Tarefa nº {numero} concluída: {rotulo}"
        texto = "Atendimento comprovado com foto" + (f" por {quem}" if quem else "")
        if comprovacao and comprovacao.distancia_m is not None:
            texto += f", a {comprovacao.distancia_m:.0f} m do ponto"
            if comprovacao.distancia_m > servico.DISTANCIA_ALERTA_M:
                texto += ". Foto longe do ponto comunicado: confira"
        texto += "."
        extras = set()
    elif tipo == "comprovacao_recusada":
        destino = responsaveis(solicitacao, ("comprovar",))
        recusada = _ultima_comprovacao(solicitacao.id, "recusada")
        extras = {recusada.autor_id} if recusada else set()
        titulo = f"Tarefa nº {numero} voltou para a fila: {rotulo}"
        texto = "A comprovação foi recusada" + (f": {detalhe}" if detalhe else "") + ". É preciso refazer."
    elif tipo == "reaberta":
        destino = responsaveis(solicitacao, ("comprovar",))
        titulo = f"Tarefa nº {numero} voltou para a fila: {rotulo}"
        texto = (detalhe or "A comunicação foi reaberta.") + " Abra para ver a foto e o ponto no mapa."
        extras = set()
    else:
        return None
    ids = ({u.id for u in destino} | extras) - {autor_id, None}
    if not ids:
        return None
    return sorted(ids), titulo, texto[:400]


def ao_registrar(tipo, solicitacao_id, user, detalhe=""):
    """Chamado por ``registrar_evento``: calcula quem avisar e guarda até o commit. Nunca derruba a ação."""
    if tipo not in EVENTOS or not solicitacao_id:
        return
    from extensions import db
    from models.limpeza import LimpezaSolicitacao

    try:
        with db.session.begin_nested():
            solicitacao = db.session.get(LimpezaSolicitacao, solicitacao_id)
            montado = _montar(tipo, solicitacao, getattr(user, "id", None), detalhe) if solicitacao else None
    except Exception:  # noqa: BLE001 - aviso é acessório: a comunicação/comprovação vale sem ele
        current_app.logger.exception("Prefeitura integrada: aviso de %s não calculado", tipo)
        return
    if montado is None:
        return
    ids, titulo, texto = montado
    caminho, endereco = _endereco(solicitacao_id)
    db.session.info.setdefault(_PENDENTES, []).append(dict(
        ids=ids, titulo=titulo, texto=texto, caminho=caminho, endereco=endereco,
        tag=f"limpeza-{solicitacao_id}-{tipo}"))


def _entregar(app, pendentes):
    """E-mail e push, numa sessão própria (a global acabou de commitar). Best-effort."""
    from sqlalchemy.orm import Session

    from extensions import db
    from models import User
    from services.notifications import _send_email
    from services.push import push_to_user

    from contextlib import nullcontext

    from flask import has_app_context

    # Na thread não há contexto; no envio síncrono (testes) reaproveita o da requisição.
    with (nullcontext() if has_app_context() else app.app_context()):
        sessao = Session(bind=db.engine)
        try:
            for aviso in pendentes:
                for uid in aviso["ids"]:
                    try:
                        user = sessao.get(User, uid)
                        if user is None:
                            continue
                        email = (user.email or "").strip()
                        # Convites internos usam e-mail sintético; mandar para lá só gera bounce.
                        if email and not email.endswith("@convite.petorlandia.local"):
                            _send_email([email], f"[{TITULO_APP}] {aviso['titulo']}"[:120],
                                        f"{aviso['texto']}\n\nAbrir: {aviso['endereco']}")
                        push_to_user(uid, aviso["titulo"], aviso["texto"], url=aviso["caminho"],
                                     tag=aviso["tag"], session=sessao)
                    except Exception:  # noqa: BLE001 - um destinatário com problema não para os outros
                        sessao.rollback()
                        app.logger.exception("Prefeitura integrada: aviso para a conta %s não entregue", uid)
        finally:
            sessao.close()


def _depois_do_commit(session):
    # O SQLAlchemy também chama after_commit ao liberar um savepoint (begin_nested): ali a
    # transação de verdade continua aberta e ainda pode dar rollback. Espera o commit final.
    if session.in_nested_transaction():
        return
    pendentes = session.info.pop(_PENDENTES, None)
    if not pendentes:
        return
    app = current_app._get_current_object()
    if app.config.get("TESTING") or app.config.get("LIMPEZA_AVISOS_SINCRONOS"):
        _entregar(app, pendentes)
        return
    threading.Thread(target=_entregar, args=(app, pendentes), name="limpeza-avisos", daemon=True).start()


def _depois_do_rollback(session, previous_transaction=None):
    # Só o rollback da transação inteira descarta; o de um savepoint (begin_nested) não.
    if previous_transaction is not None and getattr(previous_transaction, "nested", False):
        return
    session.info.pop(_PENDENTES, None)


def registrar(db):
    """Liga os ganchos na sessão do SQLAlchemy. Idempotente."""
    if getattr(registrar, "_feito", False):
        return
    event.listen(db.session, "after_commit", _depois_do_commit)
    event.listen(db.session, "after_soft_rollback", _depois_do_rollback)
    registrar._feito = True
