"""Regras da área de limpeza urbana: quem acessa, onde a foto foi tirada e a auditoria.

Papéis (adicionais, concedidos por um administrador, com período opcional) são
criados, editados e excluídos pelo administrador na tabela ``limpeza_papel``.
Cada papel diz o que a pessoa pode fazer (``PERMISSOES``: comunicar, ver o
mapa, comprovar com foto, recusar, descartar, exportar) e quais tipos de
problema vê (vazio = todos). Com "só as próprias", o mapa do papel mostra só
o que a própria pessoa comunicou. Os papéis iniciais são Colaborador, Equipe de
limpeza e Fiscalização.

Os tipos de problema (lixo, entulho…) também são cadastrados pelo
administrador, na tabela ``limpeza_tipo``; ``CATEGORIAS`` é só o conjunto inicial.

Administrador tem tudo. Com a chave ``limpeza_comunicacao_aberta`` ligada,
qualquer conta pode comunicar, sem precisar de papel.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO

from flask import g, has_request_context

from time_utils import now_in_brazil, utcnow

# O que um papel pode permitir. Os três últimos formam a fiscalização.
PERMISSOES = {
    "comunicar": "Comunicar problemas",
    "mapa": "Ver o mapa",
    "proprias": "Só as próprias comunicações",
    "comprovar": "Comprovar com foto",
    "recusar": "Recusar comprovação",
    "descartar": "Descartar comunicação",
    "exportar": "Exportar relatório",
}
FISCALIZACAO = ("recusar", "descartar", "exportar")
# Quem comprova ou fiscaliza trabalha a partir do mapa.
EXIGEM_MAPA = ("proprias", "comprovar") + FISCALIZACAO

# Papéis iniciais (a migration grava estes na tabela). Valem enquanto a tabela estiver vazia.
PAPEIS = {
    "colaborador": ("Colaborador", ("comunicar",)),
    "equipe": ("Equipe de campo", ("comunicar", "mapa", "comprovar")),
    "fiscal": ("Fiscalização", ("comunicar", "mapa", "recusar", "descartar", "exportar")),
}


# Conjunto inicial (a migration grava estes na tabela). Vale enquanto a tabela estiver vazia.
CATEGORIAS = {
    "lixo": "Lixo acumulado",
    "entulho": "Entulho",
    "moveis": "Móveis e objetos grandes",
    "galhos": "Galhos e poda",
    "canteiro": "Canteiro ou praça sem limpeza",
    "outro": "Outro",
}

CHAVE_OUTRO = "outro"


def _linhas_tipos():
    """(chave, rótulo, ativo, id) na ordem de exibição; memorizado por requisição."""
    if has_request_context() and "_limpeza_tipos" in g:
        return g._limpeza_tipos
    from models.limpeza import LimpezaTipo
    try:
        linhas = [(t.chave, t.rotulo, bool(t.ativo), t.id)
                  for t in LimpezaTipo.query.order_by(LimpezaTipo.ordem, LimpezaTipo.id).all()]
    except Exception:  # tabela ausente antes da migration: vale o conjunto inicial
        from extensions import db
        db.session.rollback()
        linhas = []
    if has_request_context():
        g._limpeza_tipos = linhas
    return linhas


def catalogo(incluir_inativos: bool = False) -> dict:
    """{chave: rótulo} dos tipos de problema, na ordem da tela."""
    linhas = _linhas_tipos()
    if not linhas:
        return dict(CATEGORIAS)
    return {chave: rotulo for chave, rotulo, ativo, _ in linhas if ativo or incluir_inativos}


def em_ordem_alfabetica(tipos: dict) -> dict:
    """Mesmo {chave: rótulo} para exibir: A-Z sem diferenciar acento ou maiúscula, "Outro" por último.

    Só a tela usa esta ordem; a gravação continua na ordem do catálogo.
    """
    import unicodedata

    def chave_ordem(item):
        chave, rotulo = item
        texto = unicodedata.normalize("NFKD", rotulo or "").encode("ascii", "ignore").decode().casefold()
        return (chave == CHAVE_OUTRO, texto)
    return dict(sorted(tipos.items(), key=chave_ordem))


def normalizar_categorias(valores, *, incluir_inativos: bool = False) -> str:
    """Chaves válidas, sem repetição, na ordem do catálogo."""
    escolhidas = set(valores or [])
    return ",".join(c for c in catalogo(incluir_inativos) if c in escolhidas)


def rotulo_categorias(valor) -> str:
    chaves = valor.split(",") if isinstance(valor, str) else list(valor or [])
    nomes = catalogo(incluir_inativos=True)
    return ", ".join(nomes.get(c, c) for c in chaves if c)


def filtro_tipo(coluna, chave):
    """Lista separada por vírgula contém exatamente ``chave`` (sem confundir prefixos)."""
    from sqlalchemy import or_
    return or_(coluna == chave, coluna.like(f"{chave},%"), coluna.like(f"%,{chave}"),
               coluna.like(f"%,{chave},%"))


STATUS = {"aberta": "Aguardando atendimento", "concluida": "Atendimento comprovado", "descartada": "Descartada"}

FLAG_COMUNICACAO_ABERTA = "limpeza_comunicacao_aberta"

# Comprovação mais longe que isso do ponto comunicado fica marcada para a fiscalização.
DISTANCIA_ALERTA_M = 60.0
# A comprovação precisa ser a foto do momento: se a imagem diz que foi tirada
# há mais tempo que isso, é recusada (foto antiga da galeria).
IDADE_MAXIMA_COMPROVACAO = timedelta(hours=3)
FOTO_MAX_BYTES = 15 * 1024 * 1024


class LimpezaErro(ValueError):
    """Erro com mensagem pronta para a tela."""


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------

def eh_admin(user) -> bool:
    return bool(getattr(user, "is_authenticated", False)
                and (getattr(user, "role", "") or "").lower() == "admin")


def hoje() -> date:
    return now_in_brazil().date()


def acesso_vigente(acesso, dia: date | None = None) -> bool:
    dia = dia or hoje()
    if acesso.revogado_em is not None:
        return False
    if acesso.inicio and dia < acesso.inicio:
        return False
    if acesso.fim and dia > acesso.fim:
        return False
    return True


def _linhas_papeis():
    """{chave: dict(nome, permissoes, tipos, id, ativo)}; memorizado por requisição."""
    if has_request_context() and "_limpeza_papeis_cat" in g:
        return g._limpeza_papeis_cat
    from models.limpeza import LimpezaPapel
    try:
        linhas = {p.chave: dict(id=p.id, chave=p.chave, nome=p.nome, ativo=bool(p.ativo),
                                permissoes=frozenset(x for x in (p.permissoes or "").split(",") if x),
                                tipos=tuple(t for t in (p.tipos or "").split(",") if t) or None)
                  for p in LimpezaPapel.query.order_by(LimpezaPapel.id).all()}
    except Exception:  # tabela ausente antes da migration: valem os papéis iniciais
        from extensions import db
        db.session.rollback()
        linhas = {}
    if not linhas:
        linhas = {chave: dict(id=None, chave=chave, nome=nome, ativo=True, permissoes=frozenset(perms), tipos=None)
                  for chave, (nome, perms) in PAPEIS.items()}
    if has_request_context():
        g._limpeza_papeis_cat = linhas
    return linhas


def papeis_catalogo(incluir_inativos: bool = False) -> dict:
    return {c: p for c, p in _linhas_papeis().items() if p["ativo"] or incluir_inativos}


def nome_do_papel(chave) -> str:
    papel = _linhas_papeis().get(chave)
    return papel["nome"] if papel else str(chave or "")


def resumo_do_papel(papel) -> str:
    """"Comunicar problemas, ver o mapa · Galhos e poda" para a lista do administrador."""
    perms = [PERMISSOES[k] for k in PERMISSOES if k in papel["permissoes"] and k != "proprias"]
    texto = ", ".join(perms[:1] + [x[0].lower() + x[1:] for x in perms[1:]])
    if papel["permissoes"] & set(("mapa",) + EXIGEM_MAPA):
        texto += " · " + (rotulo_categorias(",".join(papel["tipos"])) if papel["tipos"] else "todos os tipos")
        if "proprias" in papel["permissoes"]:
            texto += " (só as próprias)"
    return texto


def _vinculos(user):
    """(chaves vigentes, permissões, tipos visíveis ou None = todos, só as próprias); memorizado por requisição."""
    cache = g.setdefault("_limpeza_papeis", {}) if has_request_context() else {}
    if user.id not in cache:
        from models.limpeza import LimpezaAcesso
        try:
            linhas = [a for a in LimpezaAcesso.query.filter_by(user_id=user.id, revogado_em=None).all()
                      if acesso_vigente(a)]
        except Exception:  # tabela ausente antes da migration: área some, site continua
            from extensions import db
            db.session.rollback()
            linhas = []
        catalogo_papeis = papeis_catalogo()
        papeis = [catalogo_papeis[a.papel] for a in linhas if a.papel in catalogo_papeis]
        permissoes = frozenset(p for papel in papeis for p in papel["permissoes"])
        do_mapa = [papel for papel in papeis if "mapa" in papel["permissoes"]]
        if any(papel["tipos"] is None for papel in do_mapa):
            tipos = None
        else:
            tipos = frozenset(t for papel in do_mapa for t in papel["tipos"])
        # Basta um papel com o mapa completo para ver tudo; o recorte vale só se todos o têm.
        so_proprias = bool(do_mapa) and all("proprias" in papel["permissoes"] for papel in do_mapa)
        cache[user.id] = (frozenset(papel["chave"] for papel in papeis), permissoes, tipos, so_proprias)
    return cache[user.id]


SESSAO_VER_COMO = "limpeza_ver_como"


def papel_simulado(user):
    """Papel que o administrador escolheu para "ver como"; ``None`` fora desse modo."""
    if not has_request_context() or not eh_admin(user):
        return None
    from flask import session
    chave = session.get(SESSAO_VER_COMO)
    return papeis_catalogo().get(chave) if chave else None


def papeis_de(user) -> frozenset[str]:
    """Chaves dos papéis vigentes hoje; memorizado por requisição (navegação + rota)."""
    if not getattr(user, "is_authenticated", False) or not getattr(user, "id", None):
        return frozenset()
    if eh_admin(user):
        simulado = papel_simulado(user)
        return frozenset([simulado["chave"]]) if simulado else frozenset(papeis_catalogo())
    return _vinculos(user)[0]


def permissoes_de(user) -> frozenset[str]:
    if not getattr(user, "is_authenticated", False) or not getattr(user, "id", None):
        return frozenset()
    if eh_admin(user):
        simulado = papel_simulado(user)
        return simulado["permissoes"] if simulado else frozenset(PERMISSOES)
    return _vinculos(user)[1]


def tipos_visiveis(user):
    """Tipos que a pessoa vê no mapa, comprova e fiscaliza. ``None`` = todos."""
    if not getattr(user, "id", None):
        return None
    if eh_admin(user):
        simulado = papel_simulado(user)
        if simulado and "mapa" in simulado["permissoes"] and simulado["tipos"]:
            return frozenset(simulado["tipos"])
        return None
    return _vinculos(user)[2]


def so_proprias(user) -> bool:
    """O mapa (e o que se comprova ou fiscaliza nele) mostra só o que a pessoa comunicou."""
    if not getattr(user, "id", None):
        return False
    if eh_admin(user):
        simulado = papel_simulado(user)
        return bool(simulado and "proprias" in simulado["permissoes"])
    return _vinculos(user)[3]


def autor_do_recorte(user):
    """``autor_id`` para ``consultar``: a própria conta com "só as próprias", senão ``None``."""
    return user.id if so_proprias(user) else None


def ve_solicitacao_do_mapa(user, solicitacao) -> bool:
    if not pode_ver_mapa(user):
        return False
    if so_proprias(user) and solicitacao.autor_id != user.id:
        return False
    tipos = tipos_visiveis(user)
    return tipos is None or bool(tipos & set(solicitacao.lista_categorias))


def comunicacao_aberta() -> bool:
    from models.base import SiteFlag
    return bool(SiteFlag.get(FLAG_COMUNICACAO_ABERTA, default=False))


def pode_comunicar(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return "comunicar" in permissoes_de(user) or comunicacao_aberta()


def pode_ver_mapa(user) -> bool:
    return "mapa" in permissoes_de(user)


def pode_comprovar(user) -> bool:
    return "comprovar" in permissoes_de(user)


def pode_recusar(user) -> bool:
    return "recusar" in permissoes_de(user)


def pode_descartar(user) -> bool:
    return "descartar" in permissoes_de(user)


def pode_exportar(user) -> bool:
    return "exportar" in permissoes_de(user)


def pode_fiscalizar(user) -> bool:
    """Alguma permissão de fiscalização: vê quem comunicou, quem comprovou e o histórico."""
    return bool(permissoes_de(user) & set(FISCALIZACAO))


def nome_da_conta(user) -> str:
    return str(getattr(user, "name", "") or getattr(user, "email", "") or "").strip()[:160]


def _limpar_cache():
    if has_request_context():
        g.pop("_limpeza_papeis", None)
        g.pop("_limpeza_papeis_cat", None)
        g.pop("_limpeza_tipos", None)
        g.pop("user_experience", None)


# Conquistas mostradas no "parabéns" depois de comunicar ou comprovar: só incentivo
# na tela, nada é gravado além das próprias comunicações e comprovações.
NIVEIS_COMUNICACAO = [
    (1, "🌱", "Olho vivo", "Sua primeira comunicação! A cidade agradece."),
    (3, "🔎", "Vizinho atento", "Você já ajudou em vários pontos da cidade."),
    (10, "🛡️", "Guardião do bairro", "Dez pontos comunicados: o bairro está em boas mãos."),
    (25, "🏅", "Cidadão exemplar", "Sua participação faz diferença de verdade."),
    (50, "🏆", "Herói da cidade", "Cinquenta comunicações! Orlândia agradece."),
]
NIVEIS_COMPROVACAO = [
    (1, "🙌", "Mão na massa", "Primeiro atendimento comprovado!"),
    (10, "⭐", "Equipe nota 10", "Dez atendimentos comprovados."),
    (50, "🚀", "Ritmo forte", "Cinquenta pontos resolvidos."),
    (100, "🏆", "Referência da cidade", "Cem atendimentos comprovados!"),
]
SESSAO_PARABENS = "limpeza_parabens"


def conquista(total: int, tipo: str = "comunicacao") -> dict:
    """Nível atual, se o total acabou de alcançá-lo e quanto falta para o próximo."""
    niveis = NIVEIS_COMPROVACAO if tipo == "comprovacao" else NIVEIS_COMUNICACAO
    atual = None
    proximo = None
    for nivel in niveis:
        if total >= nivel[0]:
            atual = nivel
        elif proximo is None:
            proximo = nivel
    dados = {"total": total, "novo_nivel": bool(atual and atual[0] == total)}
    if atual:
        dados.update(emoji=atual[1], nivel=atual[2], frase=atual[3])
    if proximo:
        dados.update(proximo_nivel=proximo[2], faltam=proximo[0] - total,
                     progresso=int(100 * (total - (atual[0] if atual else 0)) / (proximo[0] - (atual[0] if atual else 0))))
    else:
        dados["progresso"] = 100
    return dados


def total_comunicacoes(autor_id: int) -> int:
    from models.limpeza import LimpezaSolicitacao
    return LimpezaSolicitacao.query.filter_by(autor_id=autor_id).count()


def total_comprovacoes(autor_id: int) -> int:
    from models.limpeza import LimpezaComprovacao
    return LimpezaComprovacao.query.filter_by(autor_id=autor_id, status="valida").count()


def proximo_numero() -> int:
    """Próximo número de comunicação, sem saltos.

    No Postgres, uma trava da transação faz duas gravações simultâneas esperarem
    uma pela outra; ela some no commit ou no rollback, e um rollback não gasta número.
    """
    from extensions import db
    from models.limpeza import LimpezaSolicitacao
    if db.session.get_bind().dialect.name == "postgresql":
        db.session.execute(db.text("SELECT pg_advisory_xact_lock(724501)"))
    return (db.session.query(db.func.max(LimpezaSolicitacao.numero)).scalar() or 0) + 1


def separar_emails(texto) -> list[str]:
    """E-mails colados de uma lista (vírgula, ponto e vírgula, espaço ou linha), sem repetir."""
    vistos = []
    for parte in re.split(r"[\s,;]+", texto or ""):
        parte = parte.strip().strip("<>").lower()
        if parte and parte not in vistos:
            vistos.append(parte)
    return vistos


def buscar_conta(email):
    from sqlalchemy import func
    from models import User
    email = (email or "").strip().lower()
    if not email or "@" not in email or len(email) > 254:
        raise LimpezaErro("Informe um e-mail válido.")
    user = User.query.filter(func.lower(User.email) == email).first()
    if not user:
        raise LimpezaErro("Nenhuma conta com esse e-mail. Peça para a pessoa criar a conta no site "
                          "com esse endereço e conceda o acesso em seguida.")
    return user


def texto_tipos(tipos) -> str:
    return rotulo_categorias(tipos) if tipos else "todos os tipos"


def conceder(user, papeis, inicio: date | None, fim: date | None, por: str):
    """Concede (ou reabre com o novo período) cada papel. Devolve os vínculos gravados."""
    from extensions import db
    from models.limpeza import LimpezaAcesso
    disponiveis = papeis_catalogo()
    papeis = [c for c in disponiveis if c in set(papeis or [])]
    if not papeis:
        raise LimpezaErro("Marque pelo menos um papel.")
    if inicio and fim and fim < inicio:
        raise LimpezaErro("A data final do acesso é anterior à inicial.")
    gravados = []
    for papel in papeis:
        # Um vínculo ativo por papel: o novo período substitui o anterior.
        for antigo in LimpezaAcesso.query.filter_by(user_id=user.id, papel=papel, revogado_em=None):
            antigo.revogado_em, antigo.revogado_por = utcnow(), por
        vinculo = LimpezaAcesso(user_id=user.id, papel=papel, inicio=inicio, fim=fim, concedido_por=por)
        db.session.add(vinculo)
        gravados.append(vinculo)
    registrar_evento("acesso_concedido", None, None,
                     f"{', '.join(disponiveis[p]['nome'] for p in papeis)} para a conta #{user.id}"
                     f"{_periodo_texto(inicio, fim)} por {por}")
    _limpar_cache()
    return gravados


def alterar_acesso(acesso_id: int, inicio: date | None, fim: date | None, por: str):
    """Troca o período de um acesso. O vínculo antigo fica no histórico como revogado."""
    from extensions import db
    from models.limpeza import LimpezaAcesso
    antigo = db.session.get(LimpezaAcesso, acesso_id)
    if antigo is None or antigo.revogado_em is not None:
        return None
    if inicio and fim and fim < inicio:
        raise LimpezaErro("A data final do acesso é anterior à inicial.")
    if (inicio, fim) == (antigo.inicio, antigo.fim):
        return antigo
    antigo.revogado_em, antigo.revogado_por = utcnow(), por
    novo = LimpezaAcesso(user_id=antigo.user_id, papel=antigo.papel, inicio=inicio, fim=fim, concedido_por=por,
                         tipos=antigo.tipos, perfil=antigo.perfil)
    db.session.add(novo)
    registrar_evento("acesso_alterado", None, None,
                     f"{nome_do_papel(antigo.papel)} da conta #{antigo.user_id}: "
                     f"{(_periodo_texto(inicio, fim) or ' sem limite de data').strip()} por {por}")
    _limpar_cache()
    return novo


def revogar(acesso_id: int, por: str):
    from extensions import db
    from models.limpeza import LimpezaAcesso
    acesso = db.session.get(LimpezaAcesso, acesso_id)
    if acesso is None or acesso.revogado_em is not None:
        return None
    acesso.revogado_em, acesso.revogado_por = utcnow(), por
    registrar_evento("acesso_revogado", None, None,
                     f"{nome_do_papel(acesso.papel)} da conta #{acesso.user_id} por {por}")
    _limpar_cache()
    return acesso


def acessos_ativos():
    from models.limpeza import LimpezaAcesso
    return (LimpezaAcesso.query.filter_by(revogado_em=None)
            .order_by(LimpezaAcesso.concedido_em.desc()).all())


def _periodo_texto(inicio, fim):
    if inicio and fim:
        return f" de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}"
    if inicio:
        return f" a partir de {inicio:%d/%m/%Y}"
    if fim:
        return f" até {fim:%d/%m/%Y}"
    return ""


def registrar_evento(tipo, solicitacao_id, user, detalhe=""):
    from extensions import db
    from models.limpeza import LimpezaEvento
    db.session.add(LimpezaEvento(tipo=tipo, solicitacao_id=solicitacao_id,
                                 user_id=getattr(user, "id", None), detalhe=(detalhe or "")[:500]))


# ---------------------------------------------------------------------------
# Tipos de problema (cadastro do administrador)
# ---------------------------------------------------------------------------

def _texto_simples(texto) -> str:
    import unicodedata
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-z0-9]+", " ", texto.lower())
    return " ".join(texto.split())


def _semear_tipos():
    """Grava o conjunto inicial antes da primeira alteração (banco sem a carga da migration)."""
    from extensions import db
    from models.limpeza import LimpezaTipo
    if LimpezaTipo.query.first() is None:
        for i, (chave, rotulo) in enumerate(CATEGORIAS.items()):
            db.session.add(LimpezaTipo(chave=chave, rotulo=rotulo, ativo=True, criado_por="Sistema",
                                       ordem=999 if chave == CHAVE_OUTRO else (i + 1) * 10))
        db.session.flush()


def _rotulo_valido(rotulo) -> str:
    rotulo = " ".join(str(rotulo or "").split())[:80]
    if len(rotulo) < 2:
        raise LimpezaErro("Escreva o nome do tipo de problema.")
    return rotulo[0].upper() + rotulo[1:]


def criar_tipo(rotulo, por: str):
    """Novo tipo (antes de "Outro"). Nome repetido reativa o tipo existente."""
    from extensions import db
    from models.limpeza import LimpezaTipo
    rotulo = _rotulo_valido(rotulo)
    _semear_tipos()
    simples = _texto_simples(rotulo)
    for tipo in LimpezaTipo.query.all():
        if _texto_simples(tipo.rotulo) == simples:
            if tipo.ativo:
                raise LimpezaErro(f"Já existe o tipo “{tipo.rotulo}”.")
            tipo.ativo = True
            registrar_evento("tipo_reativado", None, None, f"{tipo.rotulo} por {por}")
            _limpar_cache()
            return tipo
    base = "-".join(simples.split())[:24].strip("-") or "tipo"
    chave, n = base, 2
    while LimpezaTipo.query.filter_by(chave=chave).first() is not None:
        chave, n = f"{base[:21]}-{n}", n + 1
    maior = (db.session.query(db.func.max(LimpezaTipo.ordem))
             .filter(LimpezaTipo.chave != CHAVE_OUTRO).scalar() or 0)
    tipo = LimpezaTipo(chave=chave, rotulo=rotulo, ordem=maior + 10, ativo=True, criado_por=por)
    db.session.add(tipo)
    db.session.flush()
    registrar_evento("tipo_criado", None, None, f"{rotulo} por {por}")
    _limpar_cache()
    return tipo


def _tipo(tipo_id):
    from extensions import db
    from models.limpeza import LimpezaTipo
    _semear_tipos()
    tipo = db.session.get(LimpezaTipo, tipo_id)
    if tipo is None:
        raise LimpezaErro("Tipo de problema não encontrado.")
    return tipo


def renomear_tipo(tipo_id, rotulo, por: str):
    tipo = _tipo(tipo_id)
    rotulo = _rotulo_valido(rotulo)
    if rotulo != tipo.rotulo:
        registrar_evento("tipo_renomeado", None, None, f"{tipo.rotulo} → {rotulo} por {por}")
        tipo.rotulo = rotulo
        _limpar_cache()
    return tipo


def ativar_tipo(tipo_id, ativo: bool, por: str):
    tipo = _tipo(tipo_id)
    if tipo.chave == CHAVE_OUTRO and not ativo:
        raise LimpezaErro("“Outro” fica sempre disponível: é por ele que chegam os tipos novos.")
    if bool(tipo.ativo) != bool(ativo):
        tipo.ativo = bool(ativo)
        registrar_evento("tipo_reativado" if ativo else "tipo_desativado", None, None, f"{tipo.rotulo} por {por}")
        _limpar_cache()
    return tipo


def tipos_cadastrados():
    """Linhas para a tela do administrador (inclui os desativados)."""
    from models.limpeza import LimpezaTipo
    _semear_tipos()
    linhas = LimpezaTipo.query.order_by(LimpezaTipo.ordem, LimpezaTipo.id).all()
    ordem = list(em_ordem_alfabetica({t.chave: t.rotulo for t in linhas}))
    return sorted(linhas, key=lambda t: ordem.index(t.chave))


def sugestoes_outro(limite: int = 12):
    """O que a população escreveu ao marcar "Outro", agrupado pelo texto, mais frequente primeiro."""
    from models.limpeza import LimpezaSolicitacao
    itens = (LimpezaSolicitacao.query
             .filter(filtro_tipo(LimpezaSolicitacao.categorias, CHAVE_OUTRO),
                     LimpezaSolicitacao.status != "descartada",
                     LimpezaSolicitacao.descricao.isnot(None))
             .order_by(LimpezaSolicitacao.criado_em.desc()).limit(1000).all())
    grupos = {}
    for s in itens:
        chave = _texto_simples(s.descricao)
        if not chave:
            continue
        grupo = grupos.setdefault(chave, {"texto": chave, "exemplo": " ".join(s.descricao.split())[:80],
                                          "total": 0, "ids": []})
        grupo["total"] += 1
        grupo["ids"].append(s.id)
    return sorted(grupos.values(), key=lambda g_: (-g_["total"], g_["exemplo"].lower()))[:limite]


def reclassificar_outro(texto, destino, por: str) -> int:
    """Troca "Outro" por ``destino`` nas comunicações cujo texto simplificado é ``texto``."""
    from models.limpeza import LimpezaSolicitacao
    texto = _texto_simples(texto)
    nomes = catalogo(incluir_inativos=True)
    if not texto or destino not in nomes or destino == CHAVE_OUTRO:
        raise LimpezaErro("Escolha para qual tipo levar essas comunicações.")
    total = 0
    for s in LimpezaSolicitacao.query.filter(filtro_tipo(LimpezaSolicitacao.categorias, CHAVE_OUTRO)).all():
        if _texto_simples(s.descricao) != texto:
            continue
        novas = [destino if c == CHAVE_OUTRO else c for c in s.lista_categorias]
        s.categorias = normalizar_categorias(novas, incluir_inativos=True)
        registrar_evento("reclassificada", s.id, None, f"Outro → {nomes[destino]} por {por}")
        total += 1
    return total


# ---------------------------------------------------------------------------
# Papéis (cadastro do administrador)
# ---------------------------------------------------------------------------

def _semear_papeis():
    from extensions import db
    from models.limpeza import LimpezaPapel
    if LimpezaPapel.query.first() is None:
        for chave, (nome, perms) in PAPEIS.items():
            db.session.add(LimpezaPapel(chave=chave, nome=nome, permissoes=",".join(perms), criado_por="Sistema"))
        db.session.flush()
        _limpar_cache()


def papeis_cadastrados():
    """Papéis ativos para a tela do administrador, com quantas pessoas têm cada um."""
    from sqlalchemy import func

    from extensions import db
    from models.limpeza import LimpezaAcesso
    _semear_papeis()
    uso = dict(db.session.query(LimpezaAcesso.papel, func.count(LimpezaAcesso.id))
               .filter(LimpezaAcesso.revogado_em.is_(None)).group_by(LimpezaAcesso.papel).all())
    return [dict(p, uso=uso.get(c, 0), resumo=resumo_do_papel(p)) for c, p in papeis_catalogo().items()]


def _dados_do_papel(nome, permissoes, tipos, ignorar_id=None):
    from models.limpeza import LimpezaPapel
    nome = " ".join(str(nome or "").split())[:80]
    if len(nome) < 2:
        raise LimpezaErro("Dê um nome ao papel.")
    simples = _texto_simples(nome)
    for outro in LimpezaPapel.query.filter_by(ativo=True).all():
        if outro.id != ignorar_id and _texto_simples(outro.nome) == simples:
            raise LimpezaErro(f"Já existe o papel “{outro.nome}”.")
    escolhidas = set(permissoes or [])
    if escolhidas & set(EXIGEM_MAPA):
        escolhidas.add("mapa")
    escolhidas = [p for p in PERMISSOES if p in escolhidas]
    if not escolhidas:
        raise LimpezaErro("Marque pelo menos uma coisa que o papel pode fazer.")
    tipos = normalizar_categorias(tipos or [], incluir_inativos=True) if "mapa" in escolhidas else ""
    return nome, ",".join(escolhidas), tipos or None


def criar_papel(nome, permissoes, tipos, por: str):
    from extensions import db
    from models.limpeza import LimpezaPapel
    _semear_papeis()
    nome, permissoes, tipos = _dados_do_papel(nome, permissoes, tipos)
    usadas = {c for (c,) in db.session.query(LimpezaPapel.chave).all()}
    base = "-".join(_texto_simples(nome).split())[:20].strip("-") or "papel"
    chave, n = base, 2
    while chave in usadas:
        chave, n = f"{base[:17]}-{n}", n + 1
    papel = LimpezaPapel(chave=chave, nome=nome, permissoes=permissoes, tipos=tipos, criado_por=por)
    db.session.add(papel)
    db.session.flush()
    registrar_evento("papel_criado", None, None, f"{nome}: {resumo_do_papel(_como_dict(papel))} por {por}")
    _limpar_cache()
    return papel


def _como_dict(papel):
    return dict(id=papel.id, chave=papel.chave, nome=papel.nome, ativo=bool(papel.ativo),
                permissoes=frozenset(x for x in (papel.permissoes or "").split(",") if x),
                tipos=tuple(t for t in (papel.tipos or "").split(",") if t) or None)


def _papel_ativo(papel_id):
    from extensions import db
    from models.limpeza import LimpezaPapel
    _semear_papeis()
    papel = db.session.get(LimpezaPapel, papel_id)
    if papel is None or not papel.ativo:
        raise LimpezaErro("Papel não encontrado.")
    return papel


def editar_papel(papel_id, nome, permissoes, tipos, por: str):
    """Muda nome, permissões e tipos. Vale na hora para todos que têm o papel."""
    papel = _papel_ativo(papel_id)
    papel.nome, papel.permissoes, papel.tipos = _dados_do_papel(nome, permissoes, tipos, ignorar_id=papel.id)
    registrar_evento("papel_editado", None, None, f"{papel.nome}: {resumo_do_papel(_como_dict(papel))} por {por}")
    _limpar_cache()
    return papel


def excluir_papel(papel_id, por: str) -> tuple[str, int]:
    """Desativa o papel e revoga os acessos dele. Devolve (nome, acessos revogados)."""
    from models.limpeza import LimpezaAcesso
    papel = _papel_ativo(papel_id)
    agora, revogados = utcnow(), 0
    for acesso in LimpezaAcesso.query.filter_by(papel=papel.chave, revogado_em=None):
        acesso.revogado_em, acesso.revogado_por = agora, por
        revogados += 1
    papel.ativo = False
    registrar_evento("papel_excluido", None, None,
                     f"{papel.nome} ({revogados} acesso(s) revogado(s)) por {por}")
    _limpar_cache()
    return papel.nome, revogados


# ---------------------------------------------------------------------------
# Localização e foto
# ---------------------------------------------------------------------------

@dataclass
class DadosFoto:
    latitude: float | None = None
    longitude: float | None = None
    capturada_em: datetime | None = None


def _racional(valor) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError, ZeroDivisionError):
        numerador, denominador = valor
        return float(numerador) / float(denominador)


def ler_exif(data: bytes) -> DadosFoto:
    """GPS e hora de captura gravados pela câmera, quando existem.

    A câmera aberta pelo navegador costuma remover o GPS da foto (Android) e o
    iPhone remove ao compartilhar; por isso a tela também envia a posição do
    aparelho. Foto escolhida da galeria normalmente mantém o GPS original.
    """
    from PIL import Image
    from services.photo_intake import ensure_heif_support

    ensure_heif_support()
    dados = DadosFoto()
    try:
        with Image.open(BytesIO(data)) as imagem:
            exif = imagem.getexif()
    except Exception:
        return dados
    if not exif:
        return dados
    try:
        sub = exif.get_ifd(0x8769)  # Exif IFD
        texto = sub.get(0x9003) or exif.get(0x0132)  # DateTimeOriginal / DateTime
        if texto:
            dados.capturada_em = datetime.strptime(str(texto).strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:
        dados.capturada_em = None
    try:
        gps = exif.get_ifd(0x8825)
        if gps and 2 in gps and 4 in gps:
            def graus(tripla):
                d, m, s = (_racional(v) for v in tripla)
                return d + m / 60 + s / 3600
            lat, lon = graus(gps[2]), graus(gps[4])
            if str(gps.get(1, "N")).upper().startswith("S"):
                lat = -lat
            if str(gps.get(3, "E")).upper().startswith("W"):
                lon = -lon
            if _coordenada_valida(lat, lon):
                dados.latitude, dados.longitude = round(lat, 7), round(lon, 7)
    except Exception:
        pass
    return dados


def _coordenada_valida(lat, lon) -> bool:
    return (lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180
            and not (abs(lat) < 1e-6 and abs(lon) < 1e-6))


def _numero(texto):
    try:
        valor = float(str(texto).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None
    return valor if math.isfinite(valor) else None


def escolher_local(form, exif: DadosFoto):
    """(lat, lon, precisão, origem). O GPS gravado na foto vale mais que o do aparelho.

    O GPS da foto diz onde ela foi tirada; o do aparelho diz onde a pessoa
    estava ao enviar — que pode ser em casa, se a foto veio da galeria.
    """
    if exif.latitude is not None:
        return exif.latitude, exif.longitude, None, "foto"
    lat, lon = _numero(form.get("latitude")), _numero(form.get("longitude"))
    if lat is not None and lon is not None and _coordenada_valida(lat, lon):
        precisao = _numero(form.get("precisao"))
        return round(lat, 7), round(lon, 7), (round(precisao, 1) if precisao is not None else None), "aparelho"
    raise LimpezaErro("Não recebemos a localização. Permita o acesso à localização no navegador "
                      "e tire a foto no local, ou use uma foto que tenha a localização gravada.")


def distancia_m(lat1, lon1, lat2, lon2) -> float:
    raio = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * raio * math.asin(math.sqrt(a))


def ler_foto(arquivos) -> tuple[bytes, DadosFoto, str]:
    """(conteúdo, EXIF, nome) do primeiro arquivo com conteúdo.

    A tela tem dois campos "foto" (câmera e galeria) e o navegador envia os dois,
    um deles vazio; o iPhone às vezes manda o nome em branco, então vale o conteúdo.
    """
    for arquivo in arquivos or []:
        if arquivo is None:
            continue
        data = arquivo.read(FOTO_MAX_BYTES + 1)
        if not data:
            continue
        if len(data) > FOTO_MAX_BYTES:
            raise LimpezaErro("A foto é muito grande. Use uma imagem de até 15 MB.")
        return data, ler_exif(data), arquivo.filename or "foto"
    raise LimpezaErro("Tire a foto do local antes de enviar.")


def guardar_foto(data: bytes, nome_original: str, pasta: str, uploader) -> str:
    import uuid

    from werkzeug.utils import secure_filename

    from services.photo_intake import PhotoIntakeError, normalize_photo_upload, normalized_filename
    from services.photo_storage import PhotoStorageError, store_photo

    try:
        foto = normalize_photo_upload(data)
    except PhotoIntakeError as exc:
        raise LimpezaErro(exc.user_message) from exc
    nome = f"{uuid.uuid4().hex}_{secure_filename(normalized_filename(nome_original or 'foto', foto))}"
    try:
        return store_photo(foto.stream, nome, folder=pasta, uploader=uploader)
    except PhotoStorageError as exc:
        raise LimpezaErro(exc.user_message) from exc


def capturada_utc(capturada_em: datetime | None):
    """A câmera grava a hora local sem fuso; o aparelho está em Orlândia (horário de Brasília)."""
    if capturada_em is None:
        return None
    from datetime import timezone

    from time_utils import BR_TZ
    return capturada_em.replace(tzinfo=BR_TZ).astimezone(timezone.utc)


def foto_antiga(capturada_em: datetime | None) -> bool:
    if capturada_em is None:
        return False
    agora_local = now_in_brazil().replace(tzinfo=None)
    return agora_local - capturada_em > IDADE_MAXIMA_COMPROVACAO


# ---------------------------------------------------------------------------
# Leitura para o mapa e o relatório
# ---------------------------------------------------------------------------

def _iso(valor):
    return valor.isoformat() if valor else None


def _local(valor):
    """Hora de Brasília. As colunas guardam UTC (SQLite devolve sem fuso)."""
    if not valor:
        return ""
    from datetime import timezone

    from time_utils import BR_TZ
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M")


def hora_local(valor):
    return _local(valor)


def horas_ate_limpeza(solicitacao):
    comprovacao = solicitacao.comprovacao_valida
    if solicitacao.status != "concluida" or comprovacao is None:
        return None
    inicio, fim = solicitacao.criado_em, comprovacao.criado_em
    if inicio.tzinfo is None:
        from datetime import timezone
        inicio = inicio.replace(tzinfo=timezone.utc)
    if fim.tzinfo is None:
        from datetime import timezone
        fim = fim.replace(tzinfo=timezone.utc)
    return round((fim - inicio).total_seconds() / 3600, 1)


def consultar(status=None, categoria=None, desde: date | None = None, ate: date | None = None, autor_id=None,
              tipos=None):
    """``tipos``: recorte do acesso (``None`` = todos; conjunto vazio = nada)."""
    from datetime import time, timezone

    from sqlalchemy.orm import selectinload

    from models.limpeza import LimpezaSolicitacao
    from time_utils import BR_TZ

    q = LimpezaSolicitacao.query.options(selectinload(LimpezaSolicitacao.comprovacoes))
    if status in STATUS:
        q = q.filter(LimpezaSolicitacao.status == status)
    if categoria and categoria in catalogo(incluir_inativos=True):
        q = q.filter(filtro_tipo(LimpezaSolicitacao.categorias, categoria))
    if tipos is not None:
        from sqlalchemy import false, or_
        q = q.filter(or_(*[filtro_tipo(LimpezaSolicitacao.categorias, t) for t in sorted(tipos)])
                     if tipos else false())
    if desde:
        q = q.filter(LimpezaSolicitacao.criado_em >= datetime.combine(desde, time.min, BR_TZ).astimezone(timezone.utc))
    if ate:
        q = q.filter(LimpezaSolicitacao.criado_em
                     < datetime.combine(ate + timedelta(days=1), time.min, BR_TZ).astimezone(timezone.utc))
    if autor_id:
        q = q.filter(LimpezaSolicitacao.autor_id == autor_id)
    return q.order_by(LimpezaSolicitacao.criado_em.desc()).limit(2000).all()


def como_ponto(s, *, ver_autor: bool):
    comprovacao = s.comprovacao_valida
    ponto = {
        "id": s.id, "numero": s.num, "status": s.status, "status_rotulo": STATUS.get(s.status, s.status),
        "categorias": s.lista_categorias, "categoria_rotulo": rotulo_categorias(s.categorias),
        "descricao": s.descricao or "", "referencia": s.referencia or "",
        "lat": s.latitude, "lon": s.longitude, "precisao_m": s.precisao_m, "origem_local": s.origem_local,
        "foto": s.foto_url, "criado_em": _iso(s.criado_em), "criado_local": _local(s.criado_em),
        "horas_ate_limpeza": horas_ate_limpeza(s),
        "recusas": sum(1 for c in s.comprovacoes if c.status == "recusada"),
        "comprovacao": None,
    }
    if ver_autor:
        ponto["autor"] = nome_da_conta(s.autor)
    if comprovacao is not None:
        ponto["comprovacao"] = {
            "id": comprovacao.id, "foto": comprovacao.foto_url, "lat": comprovacao.latitude,
            "lon": comprovacao.longitude, "distancia_m": comprovacao.distancia_m,
            "longe": (comprovacao.distancia_m or 0) > DISTANCIA_ALERTA_M,
            "criado_local": _local(comprovacao.criado_em),
            "autor": nome_da_conta(comprovacao.autor) if ver_autor else "",
        }
    return ponto


def indicadores(solicitacoes):
    abertas = [s for s in solicitacoes if s.status == "aberta"]
    concluidas = [s for s in solicitacoes if s.status == "concluida"]
    horas = [h for h in (horas_ate_limpeza(s) for s in concluidas) if h is not None]
    longe = sum(1 for s in concluidas
                if s.comprovacao_valida and (s.comprovacao_valida.distancia_m or 0) > DISTANCIA_ALERTA_M)
    recusadas = sum(1 for s in solicitacoes for c in s.comprovacoes if c.status == "recusada")
    agora = utcnow()

    def idade_h(s):
        criado = s.criado_em if s.criado_em.tzinfo else s.criado_em.replace(tzinfo=agora.tzinfo)
        return (agora - criado).total_seconds() / 3600

    return {
        "total": len(solicitacoes),
        "abertas": len(abertas),
        "abertas_48h": sum(1 for s in abertas if idade_h(s) > 48),
        "concluidas": len(concluidas),
        "descartadas": sum(1 for s in solicitacoes if s.status == "descartada"),
        "mediana_horas": _mediana(horas),
        "comprovacoes_longe": longe,
        "comprovacoes_recusadas": recusadas,
    }


def _mediana(valores):
    if not valores:
        return None
    ordenados = sorted(valores)
    meio = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[meio]
    return round((ordenados[meio - 1] + ordenados[meio]) / 2, 1)
