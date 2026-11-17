"""Regras da Marcelino Academy: quem vê, quem edita e como os testes são corrigidos."""
from __future__ import annotations

from flask import g
from sqlalchemy import func

from extensions import db
from time_utils import utcnow


class AcademyErro(ValueError):
    """Erro de preenchimento mostrado ao usuário."""


PAPEIS = {"professor": "Professor", "aluno": "Aluno"}


def eh_admin(user) -> bool:
    return bool(getattr(user, "is_authenticated", False)
                and (getattr(user, "role", "") or "").lower() == "admin")


def _vinculos(user):
    """{materia_id: {papéis}} dos vínculos vigentes, memorizado por requisição."""
    if not getattr(user, "is_authenticated", False) or not getattr(user, "id", None):
        return {}
    cache = g.get("_academy_vinculos")
    if cache is not None and cache[0] == user.id:
        return cache[1]
    from models.academy import AcademyMateria, AcademyVinculo
    linhas = (db.session.query(AcademyVinculo.materia_id, AcademyVinculo.papel)
              .join(AcademyMateria, AcademyMateria.id == AcademyVinculo.materia_id)
              .filter(AcademyVinculo.user_id == user.id, AcademyVinculo.revogado_em.is_(None),
                      AcademyMateria.ativo.is_(True))
              .all())
    mapa = {}
    for materia_id, papel in linhas:
        mapa.setdefault(materia_id, set()).add(papel)
    g._academy_vinculos = (user.id, mapa)
    return mapa


def limpar_cache():
    g.pop("_academy_vinculos", None)


def tem_acesso(user) -> bool:
    """Mostra a área no painel: administrador ou alguém com vínculo vigente."""
    try:
        return eh_admin(user) or bool(_vinculos(user))
    except Exception:  # noqa: BLE001 - tabela ausente antes da migração não derruba o painel
        db.session.rollback()
        return False


def eh_professor(user, materia) -> bool:
    return eh_admin(user) or "professor" in _vinculos(user).get(materia.id, set())


def eh_professor_de_alguma(user) -> bool:
    return eh_admin(user) or any("professor" in p for p in _vinculos(user).values())


def pode_ver(user, materia) -> bool:
    if eh_admin(user):
        return True
    return materia.ativo and bool(_vinculos(user).get(materia.id))


def materias_visiveis(user):
    from models.academy import AcademyMateria
    consulta = AcademyMateria.query.order_by(AcademyMateria.ativo.desc(), AcademyMateria.nome)
    if eh_admin(user):
        return consulta.all()
    ids = list(_vinculos(user))
    if not ids:
        return []
    return consulta.filter(AcademyMateria.id.in_(ids), AcademyMateria.ativo.is_(True)).all()


def materias_do_professor(user):
    return [m for m in materias_visiveis(user) if eh_professor(user, m)]


def assinatura(user) -> str:
    return (getattr(user, "name", None) or getattr(user, "email", None) or f"Usuário {user.id}")[:160]


def url_valida(texto: str | None) -> str | None:
    texto = (texto or "").strip()
    if not texto:
        return None
    if not texto.lower().startswith(("https://", "http://")) or len(texto) > 300 or " " in texto:
        raise AcademyErro("Link inválido: use um endereço completo começando com https://")
    return texto


def texto_obrigatorio(texto, campo, limite):
    texto = (texto or "").strip()
    if not texto:
        raise AcademyErro(f"Preencha {campo}.")
    if len(texto) > limite:
        raise AcademyErro(f"{campo.capitalize()} pode ter no máximo {limite} caracteres.")
    return texto


# ---------------------------------------------------------------- pessoas

def vincular(materia, email, papel, por):
    from models import User
    from models.academy import AcademyVinculo
    if papel not in PAPEIS:
        raise AcademyErro("Papel inválido.")
    email = (email or "").strip().lower()
    if not email:
        raise AcademyErro("Informe o e-mail da pessoa.")
    pessoa = User.query.filter(func.lower(User.email) == email).first()
    if pessoa is None:
        raise AcademyErro("Nenhuma conta do PetOrlândia com esse e-mail. Peça para a pessoa criar a conta primeiro.")
    existente = AcademyVinculo.query.filter_by(materia_id=materia.id, user_id=pessoa.id, papel=papel,
                                               revogado_em=None).first()
    if existente:
        raise AcademyErro(f"{pessoa.name or email} já é {PAPEIS[papel].lower()} desta matéria.")
    vinculo = AcademyVinculo(materia_id=materia.id, user_id=pessoa.id, papel=papel, concedido_por=assinatura(por))
    db.session.add(vinculo)
    limpar_cache()
    return vinculo


def vinculos_da_materia(materia):
    from models.academy import AcademyVinculo
    return (AcademyVinculo.query.filter_by(materia_id=materia.id, revogado_em=None)
            .order_by(AcademyVinculo.papel.desc(), AcademyVinculo.id).all())


def revogar(vinculo, por):
    vinculo.revogado_em = utcnow()
    vinculo.revogado_por = assinatura(por)
    limpar_cache()


# ---------------------------------------------------------------- questões

def ler_opcoes(texto: str):
    """Uma opção por linha; ``*`` no início marca a correta. Devolve [(texto, correta)]."""
    opcoes = []
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        correta = linha.startswith("*")
        linha = linha.lstrip("*").strip()
        if not linha:
            continue
        if len(linha) > 300:
            raise AcademyErro("Cada opção pode ter no máximo 300 caracteres.")
        opcoes.append((linha, correta))
    return opcoes


def opcoes_como_texto(questao) -> str:
    return "\n".join(("*" if o.correta else "") + o.texto for o in questao.opcoes)


def aplicar_questao(questao, enunciado, tipo, opcoes_texto):
    from models.academy import TIPOS_QUESTAO, AcademyOpcao
    questao.enunciado = texto_obrigatorio(enunciado, "o enunciado", 2000)
    if tipo not in TIPOS_QUESTAO:
        raise AcademyErro("Tipo de questão inválido.")
    questao.tipo = tipo
    if tipo == "aberta":
        questao.opcoes = []
        return questao
    opcoes = ler_opcoes(opcoes_texto)
    if len(opcoes) < 2:
        raise AcademyErro("Escreva pelo menos duas opções, uma por linha.")
    corretas = sum(1 for _, c in opcoes if c)
    if corretas == 0:
        raise AcademyErro("Marque a opção correta com * no início da linha.")
    if tipo == "unica" and corretas > 1:
        raise AcademyErro("Questão de escolha única tem só uma opção correta. Use múltipla escolha.")
    questao.opcoes = [AcademyOpcao(texto=t, correta=c) for t, c in opcoes]
    return questao


def corrigir(questao, opcao_ids):
    """Nota automática: 1 se as opções marcadas são exatamente as corretas."""
    if questao.tipo == "aberta":
        return None, None
    validas = {o.id: o for o in questao.opcoes}
    escolhidas = [validas[i] for i in opcao_ids if i in validas]
    if not escolhidas:
        raise AcademyErro("Escolha uma opção antes de enviar.")
    if questao.tipo == "unica" and len(escolhidas) > 1:
        raise AcademyErro("Escolha só uma opção.")
    certas = {o.id for o in questao.opcoes if o.correta}
    nota = 1 if {o.id for o in escolhidas} == certas else 0
    return nota, "\n".join(o.texto for o in escolhidas)


def responder(questao, user, form):
    from models.academy import AcademyResposta
    if AcademyResposta.query.filter_by(questao_id=questao.id, user_id=user.id).first():
        raise AcademyErro("Você já respondeu esta questão.")
    if questao.tipo == "aberta":
        texto = texto_obrigatorio(form.get("texto"), "a resposta", 2000)
        resposta = AcademyResposta(questao_id=questao.id, user_id=user.id, texto=texto, nota=None)
    else:
        ids = []
        for valor in form.getlist("opcao"):
            try:
                ids.append(int(valor))
            except (TypeError, ValueError):
                continue
        nota, escolhidas = corrigir(questao, ids)
        resposta = AcademyResposta(questao_id=questao.id, user_id=user.id, opcoes=escolhidas, nota=nota)
    db.session.add(resposta)
    return resposta


def respostas_do_aluno(user, questoes):
    from models.academy import AcademyResposta
    ids = [q.id for q in questoes]
    if not ids:
        return {}
    return {r.questao_id: r for r in AcademyResposta.query.filter(
        AcademyResposta.user_id == user.id, AcademyResposta.questao_id.in_(ids))}


def questoes_da_materia(materia):
    from models.academy import AcademyLicao, AcademyQuestao, AcademyTeste
    return (AcademyQuestao.query.join(AcademyTeste).join(AcademyLicao)
            .filter(AcademyLicao.materia_id == materia.id))


def desempenho_da_turma(materia):
    """[(vínculo do aluno, respondidas, certas, aguardando)] para o professor."""
    from models.academy import AcademyResposta
    ids = [q.id for q in questoes_da_materia(materia).all()]
    alunos = [v for v in vinculos_da_materia(materia) if v.papel == "aluno"]
    linhas = []
    for v in alunos:
        respostas = (AcademyResposta.query.filter(AcademyResposta.user_id == v.user_id,
                                                  AcademyResposta.questao_id.in_(ids)).all() if ids else [])
        linhas.append((v, len(respostas), sum(1 for r in respostas if r.nota == 1),
                       sum(1 for r in respostas if r.nota is None)))
    return linhas


def pendentes_de_correcao(user):
    from models.academy import AcademyLicao, AcademyQuestao, AcademyResposta, AcademyTeste
    ids = [m.id for m in materias_do_professor(user)]
    if not ids:
        return []
    return (AcademyResposta.query.join(AcademyQuestao, AcademyQuestao.id == AcademyResposta.questao_id)
            .join(AcademyTeste).join(AcademyLicao)
            .filter(AcademyLicao.materia_id.in_(ids), AcademyResposta.nota.is_(None))
            .order_by(AcademyResposta.criado_em).all())
