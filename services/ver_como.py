"""Ver como: o administrador vê o site como outra conta, sem gravar nada em nome dela.

A sessão continua sendo do administrador. Enquanto o modo está ativo, o
carregador de usuário do login (``app.load_user``) devolve a conta vista, e as
restrições dela valem como para ela. Envios que gravam (POST, PUT, PATCH,
DELETE) são recusados em ``request_hooks``, que também mostra a faixa de aviso
em toda página. Cada início e fim fica na auditoria.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from flask import g, has_request_context, session

CHAVE_SESSAO = "ver_como"
DURACAO = timedelta(minutes=30)
METODOS_DE_LEITURA = frozenset({"GET", "HEAD", "OPTIONS"})
MENSAGEM_SOMENTE_LEITURA = "Modo Ver como: somente leitura. Nada foi gravado."


def _eh_admin(user) -> bool:
    return user is not None and (getattr(user, "role", "") or "").lower() == "admin"


def motivo_para_nao_ver(admin, alvo) -> str:
    """Vazio quando ``admin`` pode ver o site como ``alvo``; senão o motivo, para mostrar na tela."""
    if not _eh_admin(admin):
        return "Somente o administrador pode ver o site como outra conta."
    if alvo is None:
        return "Conta não encontrada."
    if alvo.id == admin.id:
        return "Esta já é a sua conta."
    if _eh_admin(alvo):
        return "Não é possível ver o site como outro administrador."
    return ""


def ensure_conta_para_ver_como(admin, user_id: int):
    """A conta pedida, se quem pede é administrador; senão 404, sem revelar se a conta existe."""
    from flask import abort
    from extensions import db
    from models import User

    if not getattr(admin, "is_authenticated", False) or not _eh_admin(admin):
        abort(404)
    return db.session.get(User, user_id) or abort(404)


def _auditar(funcao: str, mensagem: str, admin_id, alvo_id) -> None:
    from extensions import db
    from models.sfa import SfaAuditoria

    db.session.add(SfaAuditoria(nivel="INFO", categoria="VER_COMO", funcao=funcao, mensagem=mensagem,
                                detalhes_json=json.dumps({"admin_id": admin_id, "alvo_id": alvo_id})))


def iniciar(admin, alvo, voltar: str = "") -> None:
    """Liga o modo. Quem chama confirma antes com ``motivo_para_nao_ver`` e grava a auditoria (commit)."""
    from time_utils import utcnow

    session[CHAVE_SESSAO] = {"admin_id": admin.id, "alvo_id": alvo.id, "voltar": voltar,
                             "ate": (utcnow() + DURACAO).isoformat()}
    _auditar("ver_como_iniciar", f"Administrador #{admin.id} passou a ver o site como a conta #{alvo.id}.",
             admin.id, alvo.id)


def encerrar() -> dict | None:
    """Desliga o modo e devolve o que estava na sessão; quem chama grava a auditoria (commit)."""
    dados = session.pop(CHAVE_SESSAO, None)
    if has_request_context():
        g.pop("ver_como", None)
    if isinstance(dados, dict):
        _auditar("ver_como_encerrar", f"Administrador #{dados.get('admin_id')} voltou à própria conta.",
                 dados.get("admin_id"), dados.get("alvo_id"))
        return dados
    return None


def _expirou(ate) -> bool:
    from time_utils import utcnow

    try:
        return datetime.fromisoformat(str(ate)) <= utcnow()
    except (TypeError, ValueError):
        return True


def conta_vista(usuario):
    """A conta que o administrador ``usuario`` está vendo, ou ``None`` fora do modo Ver como.

    Sessão de outra pessoa, prazo vencido ou conta que deixou de existir (ou virou
    administradora) desligam o modo em silêncio: a pessoa volta a ser ela mesma.
    """
    if not has_request_context() or CHAVE_SESSAO not in session:
        return None
    from extensions import db
    from models import User

    dados = session.get(CHAVE_SESSAO)
    alvo = None
    if (isinstance(dados, dict) and _eh_admin(usuario) and dados.get("admin_id") == usuario.id
            and not _expirou(dados.get("ate"))):
        alvo = db.session.get(User, dados.get("alvo_id")) if isinstance(dados.get("alvo_id"), int) else None
    if alvo is None or motivo_para_nao_ver(usuario, alvo):
        session.pop(CHAVE_SESSAO, None)
        return None
    from time_utils import BR_TZ

    g.ver_como = {"admin": usuario, "alvo": alvo, "voltar": dados.get("voltar") or "",
                  "ate": datetime.fromisoformat(dados["ate"]).astimezone(BR_TZ).strftime("%H:%M")}
    return alvo


def ativo() -> dict | None:
    """Dados do modo na requisição atual (depois de a conta ter sido carregada)."""
    return g.get("ver_como") if has_request_context() else None
