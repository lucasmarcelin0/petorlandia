"""Área "Notificação SINAN": unidades de saúde, responsáveis, fichas e panorama.

O administrador cadastra as unidades e indica as contas responsáveis por cada
uma. Ser responsável é um papel adicional: ``User.role`` e os demais acessos
da conta não mudam. Quem responde por uma unidade registra fichas em nome dela,
vê as fichas da própria unidade e um panorama só com contagens das demais.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta

from flask import g, has_request_context

from services.entomologia_acesso import eh_admin
from services.entomologia_service import consultar_sem_interromper

ROTULO_AREA = "Notificação SINAN"
# Perfil interno (``User.worker``) da conta de uma unidade de saúde que só usa esta área.
PERFIL_SO_NOTIFICACAO = "unidade_saude"
LIMITE_FICHAS = 300
SEM_UNIDADE = "Unidade não identificada"

GRUPOS_PENDENCIA = (
    ("notificacao", "Notificação e investigação"),
    ("exames", "Exames"),
    ("encerramento", "Encerramento do caso"),
)
# (campo da data da coleta, campo do resultado)
_EXAMES = (
    ("dengue_igm_data", "dengue_igm_resultado"),
    ("ns1_data_coleta", "ns1_resultado"),
    ("isolamento_data", "isolamento_resultado"),
    ("rt_pcr_data", "rt_pcr_resultado"),
)
# Chikungunya: (campo da data, amostra no campo 38, nome na tela)
_EXAMES_CHIKUNGUNYA = (
    ("chikungunya_s1_data", "s1", "1ª amostra (S1)"),
    ("chikungunya_s2_data", "s2", "2ª amostra (S2)"),
    ("prnt_data", "prnt", "PRNT"),
)
_NAO_REALIZADO = "4"
_DESCARTADO, _ALARME, _GRAVE, _CHIKUNGUNYA = "5", "11", "12", "13"
_OBITOS = {"2", "3", "4"}
_AGRAVOS = {"1": "Dengue", "2": "Chikungunya"}


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------

def unidades_do_usuario(user) -> list:
    """Unidades ativas pelas quais a conta responde; memorizado por requisição (navegação + rota)."""
    if not getattr(user, "is_authenticated", False) or not getattr(user, "id", None):
        return []
    cache = g.setdefault("_sfa_unidades_usuario", {}) if has_request_context() else {}
    if user.id not in cache:
        def consulta():
            from models.sfa import SfaUnidadeResponsavel, SfaUnidadeSaude
            return (SfaUnidadeSaude.query
                    .join(SfaUnidadeResponsavel, SfaUnidadeResponsavel.unidade_id == SfaUnidadeSaude.id)
                    .filter(SfaUnidadeResponsavel.user_id == user.id,
                            SfaUnidadeResponsavel.revogado_em.is_(None),
                            SfaUnidadeSaude.ativa.is_(True))
                    .order_by(SfaUnidadeSaude.nome).all())
        cache[user.id] = consultar_sem_interromper(consulta, [])
    return cache[user.id]


def pode_acessar(user) -> bool:
    return eh_admin(user) or bool(unidades_do_usuario(user))


def conta_so_notificacao(user) -> bool:
    """Conta de unidade de saúde: o resto do site fica fechado para ela. O administrador nunca é restrito."""
    return bool(getattr(user, "is_authenticated", False)
                and (getattr(user, "worker", None) or "").strip().lower() == PERFIL_SO_NOTIFICACAO
                and not eh_admin(user))


def unidades_para_registrar(user) -> list:
    """Em nome de quais unidades a conta pode abrir uma ficha: o administrador, de qualquer unidade ativa."""
    if eh_admin(user):
        from models.sfa import SfaUnidadeSaude
        return SfaUnidadeSaude.query.filter(SfaUnidadeSaude.ativa.is_(True)).order_by(SfaUnidadeSaude.nome).all()
    return unidades_do_usuario(user)


def _esquecer_acessos() -> None:
    if has_request_context():
        g.pop("_sfa_unidades_usuario", None)


# ---------------------------------------------------------------------------
# Unidades e responsáveis (administrador)
# ---------------------------------------------------------------------------

def _chave(texto: object) -> str:
    from services.sfa_service import normalizar_nome_chave
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalizar_nome_chave(str(texto or ""))).split())


def _apelidos(texto: object) -> list[str]:
    linhas = (" ".join(linha.split()) for linha in re.split(r"[\n;]", str(texto or "")))
    return list(dict.fromkeys(linha for linha in linhas if linha))


def validar_unidade(form, *, ignorar_id: int | None = None) -> dict:
    """Campos de uma unidade prontos para gravar; ``ValueError`` com a correção a fazer."""
    from models.sfa import SfaUnidadeSaude

    nome = " ".join(str(form.get("nome") or "").split())
    if not nome:
        raise ValueError("Informe o nome da unidade.")
    if len(nome) > 180:
        raise ValueError("O nome da unidade tem no máximo 180 caracteres.")
    cnes = re.sub(r"\D", "", str(form.get("cnes") or ""))
    if cnes and len(cnes) != 7:
        raise ValueError("O CNES tem 7 dígitos. Deixe em branco se não souber.")
    apelidos = "\n".join(_apelidos(form.get("apelidos")))
    if len(apelidos) > 2000:
        raise ValueError("A lista de outros nomes ficou longa demais.")
    for outra in SfaUnidadeSaude.query.all():
        if outra.id == ignorar_id:
            continue
        if _chave(outra.nome) == _chave(nome):
            raise ValueError("Já existe uma unidade com esse nome.")
        if cnes and outra.cnes == cnes:
            raise ValueError(f"O CNES {cnes} já está cadastrado em {outra.nome}.")
    return {"nome": nome, "cnes": cnes or None, "telefone": str(form.get("telefone") or "").strip()[:25] or None,
            "apelidos": apelidos or None}


def criar_unidade(form, por: str):
    from extensions import db
    from models.sfa import SfaUnidadeSaude

    unidade = SfaUnidadeSaude(**validar_unidade(form), criado_por=por)
    db.session.add(unidade)
    db.session.flush()
    return unidade


def atualizar_unidade(unidade, form) -> list[str]:
    """Devolve os campos que mudaram."""
    dados = validar_unidade(form, ignorar_id=unidade.id)
    dados["ativa"] = str(form.get("ativa") or "") == "1"
    alterados = [campo for campo, valor in dados.items() if getattr(unidade, campo) != valor]
    for campo in alterados:
        setattr(unidade, campo, dados[campo])
    _esquecer_acessos()
    return alterados


def conceder(unidade, user, por: str):
    """Idempotente: devolve (vínculo, criado)."""
    from extensions import db
    from models.sfa import SfaUnidadeResponsavel

    atual = SfaUnidadeResponsavel.query.filter_by(unidade_id=unidade.id, user_id=user.id, revogado_em=None).first()
    if atual:
        return atual, False
    vinculo = SfaUnidadeResponsavel(unidade_id=unidade.id, user_id=user.id, concedido_por=por)
    db.session.add(vinculo)
    _esquecer_acessos()
    return vinculo, True


def revogar(vinculo_id: int, por: str):
    from extensions import db
    from models.sfa import SfaUnidadeResponsavel
    from time_utils import utcnow

    vinculo = db.session.get(SfaUnidadeResponsavel, vinculo_id)
    if vinculo is None or vinculo.revogado_em is not None:
        return None
    vinculo.revogado_em, vinculo.revogado_por = utcnow(), por
    _esquecer_acessos()
    return vinculo


def vinculos_ativos(user) -> list:
    """Vínculos não revogados da conta, inclusive com unidade desativada."""
    from models.sfa import SfaUnidadeResponsavel

    if not getattr(user, "id", None):
        return []
    return (SfaUnidadeResponsavel.query.filter_by(user_id=user.id, revogado_em=None)
            .order_by(SfaUnidadeResponsavel.id).all())


def definir_unidade_da_conta(user, unidade, por: str, *, exclusiva: bool = False) -> tuple[bool, list]:
    """Faz a conta responder por ``unidade``; com ``exclusiva``, deixa de responder pelas outras.

    A conta de uma unidade (perfil ``PERFIL_SO_NOTIFICACAO``) responde só pela dela, e assim
    registra fichas sem precisar escolher a unidade. Devolve (concedido, vínculos revogados).
    """
    _, concedido = conceder(unidade, user, por)
    revogados = []
    if exclusiva:
        for vinculo in vinculos_ativos(user):
            if vinculo.unidade_id != unidade.id:
                revogados.append(revogar(vinculo.id, por))
    return concedido, revogados


def auditar(funcao: str, mensagem: str, detalhes: dict, *, ator=None, id_estudo=None) -> None:
    import json
    from extensions import db
    from models.sfa import SfaAuditoria

    ator_id = ator.get_id() if ator is not None and hasattr(ator, "get_id") else None
    db.session.add(SfaAuditoria(nivel="INFO", categoria="NOTIFICACAO_SINAN", funcao=funcao, id_estudo=id_estudo,
                                mensagem=mensagem,
                                detalhes_json=json.dumps({"ator_autenticado": str(ator_id), **detalhes},
                                                         ensure_ascii=False, default=str)))


# ---------------------------------------------------------------------------
# O que ainda falta em uma ficha
# ---------------------------------------------------------------------------

def pendencias(answers: dict, schema: dict | None = None) -> list[dict]:
    """Campos que a ficha ainda espera, na ordem do formulário. Lista vazia = nada falta.

    Só entra o que faz sentido para as respostas já dadas: resultado de exame
    com coleta registrada, internação quando houve hospitalização, data do
    óbito quando a evolução foi óbito. Campo em branco que a ficha não exige
    naquele caso (hospital sem internação, sorologia não colhida) não é pendência.
    """
    from services.sfa_pre_t0 import carregar_esquema_pre_t0

    schema = schema or carregar_esquema_pre_t0()
    campos = {field["key"]: field for section in schema["sections"] for field in section["fields"]}
    answers = answers if isinstance(answers, dict) else {}
    itens: list[dict] = []

    def grupo(key: str) -> dict:
        value = answers.get(key)
        return value if isinstance(value, dict) else {}

    def texto(key: str) -> str:
        value = answers.get(key)
        if isinstance(value, dict):
            value = value.get("valor")
        return str(value or "").strip()

    def falta(etapa: str, key: str, *, campo: str = "", rotulo: str = "", detalhe: str = "") -> None:
        field = campos[key]
        itens.append({"grupo": etapa, "numero": field["number"], "rotulo": rotulo or field["campo"],
                      "chave": key, "campo": campo or key, "detalhe": detalhe})

    # Notificação e investigação
    if not texto("data_nascimento") and not str(grupo("idade").get("valor") or "").strip():
        falta("notificacao", "data_nascimento", rotulo="Data de nascimento ou idade")
    if not texto("sexo"):
        falta("notificacao", "sexo")
    elif texto("sexo") == "F" and not texto("gestante"):
        falta("notificacao", "gestante")
    for key in ("raca_cor", "escolaridade", "municipio_residencia", "bairro", "logradouro", "zona",
                "data_investigacao"):
        if not texto(key):
            falta("notificacao", key)
    if not grupo("doencas_preexistentes"):
        primeira = campos["doencas_preexistentes"]["items"][0][0]
        falta("notificacao", "doencas_preexistentes", campo=f"doencas_preexistentes__{primeira}")
    hospitalizacao = texto("hospitalizacao")
    if not hospitalizacao:
        falta("notificacao", "hospitalizacao")
    elif hospitalizacao == "1":
        for key in ("data_internacao", "nome_hospital"):
            if not texto(key):
                falta("notificacao", key)

    # Exames: coleta registrada espera o resultado; resultado informado espera a data da coleta.
    def aguardando(data: str) -> str:
        return f"coleta em {data}, aguardando resultado"

    for data_key, resultado_key in _EXAMES:
        data, resultado = texto(data_key), texto(resultado_key)
        if data and not resultado:
            falta("exames", resultado_key, detalhe=aguardando(data))
        elif resultado and resultado != _NAO_REALIZADO and not data:
            falta("exames", data_key)
    chik = grupo("prnt_resultado")
    por_exame = chik.get("resultados") if isinstance(chik.get("resultados"), dict) else {}
    for data_key, amostra, nome in _EXAMES_CHIKUNGUNYA:
        data = texto(data_key)
        # Fichas antigas guardavam um só resultado para as amostras marcadas.
        resultado = por_exame.get(amostra) or (chik.get("resultado") if amostra in (chik.get("amostras") or []) else "")
        if data and not resultado:
            falta("exames", "prnt_resultado", campo=f"prnt_resultado__res__{amostra}",
                  rotulo=f"Resultado · {nome}", detalhe=aguardando(data))
        elif resultado and resultado != _NAO_REALIZADO and not data:
            falta("exames", data_key)

    # Encerramento
    classificacao = texto("classificacao")
    if classificacao != _DESCARTADO and not texto("caso_autoctone"):
        falta("encerramento", "caso_autoctone")
    if not classificacao:
        falta("encerramento", "classificacao")
    if not texto("criterio_confirmacao"):
        falta("encerramento", "criterio_confirmacao")
    if classificacao != _DESCARTADO:
        if classificacao == _CHIKUNGUNYA and not texto("apresentacao_clinica"):
            falta("encerramento", "apresentacao_clinica")
        evolucao = texto("evolucao_caso")
        if not evolucao:
            falta("encerramento", "evolucao_caso")
        elif evolucao in _OBITOS and not texto("data_obito"):
            falta("encerramento", "data_obito")
    if not texto("data_encerramento"):
        falta("encerramento", "data_encerramento")
    for codigo, key, data_key in ((_ALARME, "sinais_alarme", "data_inicio_sinais_alarme"),
                                  (_GRAVE, "dengue_grave", "data_inicio_sinais_gravidade")):
        if classificacao != codigo:
            continue
        status = str(grupo(key).get("status") or "")
        if not status:
            falta("encerramento", key)
        elif status == "1" and not texto(data_key):
            falta("encerramento", data_key)
    return itens


def pendencias_por_grupo(itens: list[dict]) -> list[dict]:
    """Só os grupos que têm algo faltando, na ordem da ficha."""
    return [{"chave": chave, "titulo": titulo, "itens": [item for item in itens if item["grupo"] == chave]}
            for chave, titulo in GRUPOS_PENDENCIA if any(item["grupo"] == chave for item in itens)]


# ---------------------------------------------------------------------------
# Fichas da unidade
# ---------------------------------------------------------------------------

def _respostas(log_entry) -> dict | None:
    from services.sfa_pre_t0 import FULL_KEY, _carregar_payload

    full_form = _carregar_payload(log_entry).get(FULL_KEY)
    if isinstance(full_form, dict) and isinstance(full_form.get("respostas"), dict):
        return full_form["respostas"]
    return None


def ficha_visivel(user, ficha_id: int):
    """A ficha, se foi registrada por uma unidade que a conta pode ver; senão ``None``."""
    from extensions import db
    from models.sfa import SfaSinanLog

    log_entry = db.session.get(SfaSinanLog, ficha_id)
    if log_entry is None or log_entry.unidade_id is None or _respostas(log_entry) is None:
        return None
    if eh_admin(user) or log_entry.unidade_id in {unidade.id for unidade in unidades_do_usuario(user)}:
        return log_entry
    return None


def pode_completar(user, log_entry) -> bool:
    """Completar depois é do autor (enquanto responde pela unidade) e do administrador."""
    if eh_admin(user):
        return True
    return bool(log_entry.preenchido_por_id and log_entry.preenchido_por_id == getattr(user, "id", None)
                and log_entry.unidade_id in {unidade.id for unidade in unidades_do_usuario(user)})


def _caso_da_ficha(log_entry):
    from models.sfa import SfaPaciente

    if not log_entry.id_estudo_vinculado:
        return None
    return SfaPaciente.query.filter_by(id_estudo=log_entry.id_estudo_vinculado).first()


def _caso_em_andamento(paciente) -> bool:
    """O estudo já agiu sobre o caso: contato, WhatsApp, questionário ou ação registrada."""
    from models.sfa import (SfaAcao, SfaContato, SfaContextoEpisodio, SfaEventoVinculo, SfaRespostaT0,
                            SfaRespostaT7, SfaRespostaT10, SfaRespostaT30)

    if (paciente.status_t0 or "SINAN_Aguardando_T0") != "SINAN_Aguardando_T0":
        return True
    if (paciente.status_whatsapp or "NAO_ENVIADO") != "NAO_ENVIADO":
        return True
    if (paciente.retorno_contato or "PENDENTE") != "PENDENTE":
        return True
    return any(modelo.query.filter_by(id_estudo=paciente.id_estudo).first() is not None
               for modelo in (SfaRespostaT0, SfaRespostaT7, SfaRespostaT10, SfaRespostaT30, SfaContextoEpisodio,
                              SfaContato, SfaEventoVinculo, SfaAcao))


def _caso_criado_pela_ficha(paciente, log_entry) -> bool:
    """O caso nasceu desta ficha (e não da planilha) e nenhum outro registro aponta para ele."""
    from models.sfa import SfaAuditoria, SfaSinanLog

    outros = SfaSinanLog.query.filter(SfaSinanLog.id_estudo_vinculado == paciente.id_estudo,
                                      SfaSinanLog.id != log_entry.id).first()
    if outros is not None:
        return False
    criacao = (SfaAuditoria.query.filter_by(funcao="salvar_ficha_pre_t0", id_estudo=paciente.id_estudo)
               .filter(SfaAuditoria.detalhes_json.like('%"novo_caso": true%')).first())
    return criacao is not None


def motivo_para_nao_excluir(log_entry) -> str:
    """Vazio quando a ficha pode ser excluída; senão o motivo, para mostrar na tela."""
    if log_entry.n_caso:
        return "Esta ficha também veio da planilha do SINAN. Para excluí-la, fale com a vigilância."
    paciente = _caso_da_ficha(log_entry)
    if paciente is not None and _caso_em_andamento(paciente):
        return ("Esta notificação já entrou no acompanhamento do estudo (contato ou questionário). "
                "Para excluí-la, fale com a vigilância.")
    return ""


def pode_excluir(user, log_entry) -> bool:
    """Quem pode corrigir a ficha pode excluí-la, enquanto o estudo não agiu sobre ela."""
    return pode_completar(user, log_entry) and not motivo_para_nao_excluir(log_entry)


def excluir_ficha(log_entry) -> dict:
    """Apaga a ficha e o caso que só ela criou. ``ValueError`` com o motivo quando não pode.

    O caso do estudo sai junto apenas se nasceu desta ficha e ainda não teve
    nenhuma ação; caso vindo de outra origem continua, só sem esta ficha.
    """
    from extensions import db

    motivo = motivo_para_nao_excluir(log_entry)
    if motivo:
        raise ValueError(motivo)
    paciente = _caso_da_ficha(log_entry)
    remover_caso = paciente is not None and _caso_criado_pela_ficha(paciente, log_entry)
    resumo = {"ficha_id": log_entry.id, "ficha_sinan": log_entry.ficha_sinan or "", "unidade_id": log_entry.unidade_id,
              "id_estudo": log_entry.id_estudo_vinculado or "", "caso_removido": remover_caso}
    db.session.delete(log_entry)
    if remover_caso:
        db.session.delete(paciente)
    return resumo


def ficha_ja_registrada(numero: object):
    """Registro que já guarda a ficha digital com esse número, se houver."""
    from models.sfa import SfaSinanLog
    from services.sfa_pre_t0 import chave_dedup_da_ficha

    chave = chave_dedup_da_ficha(numero)
    log_entry = SfaSinanLog.query.filter_by(chave_dedup=chave).first() if chave else None
    return log_entry if log_entry is not None and _respostas(log_entry) is not None else None


def listar_fichas(user, *, unidade_id: int | None = None, busca: str = "", so_pendentes: bool = False) -> dict:
    from models.sfa import SfaSinanLog
    from services.sfa_pre_t0 import carregar_esquema_pre_t0

    consulta = SfaSinanLog.query.filter(SfaSinanLog.unidade_id.isnot(None))
    if not eh_admin(user):
        consulta = consulta.filter(SfaSinanLog.unidade_id.in_([u.id for u in unidades_do_usuario(user)] or [0]))
    if unidade_id:
        consulta = consulta.filter(SfaSinanLog.unidade_id == unidade_id)
    # A busca olha o número e o nome que a unidade digitou (sem acento nem maiúscula), em todas as
    # fichas ao alcance da conta; sem busca, a tela traz as mais recentes.
    busca = _chave(str(busca or "")[:80])
    consulta = consulta.order_by(SfaSinanLog.id.desc())
    registros = consulta.all() if busca else consulta.limit(LIMITE_FICHAS + 1).all()

    schema = carregar_esquema_pre_t0()
    fichas, com_pendencia = [], 0
    for log_entry in registros if busca else registros[:LIMITE_FICHAS]:
        respostas = _respostas(log_entry)
        if respostas is None:
            continue
        if busca and busca not in _chave(f"{log_entry.ficha_sinan} {respostas.get('nome')}"):
            continue
        faltam = pendencias(respostas, schema)
        com_pendencia += bool(faltam)
        if so_pendentes and not faltam:
            continue
        fichas.append({
            "id": log_entry.id,
            # Nome, data e agravo saem da ficha que a unidade preencheu, não do registro: o número pode
            # coincidir com uma linha da planilha, e o que veio de lá não é mostrado nesta área.
            "ficha_sinan": log_entry.ficha_sinan or "",
            "nome": str(respostas.get("nome") or ""),
            "data_notificacao": str(respostas.get("data_notificacao") or ""),
            "agravo": agravo_da_ficha(respostas),
            "unidade": log_entry.unidade.nome if log_entry.unidade else "",
            "autor": nome_da_conta(log_entry.preenchido_por),
            "pode_completar": pode_completar(user, log_entry),
            "faltam": Counter(item["grupo"] for item in faltam),
            "total_faltam": len(faltam),
        })
    return {"fichas": fichas, "com_pendencia": com_pendencia,
            "limitado": not busca and len(registros) > LIMITE_FICHAS}


def agravo_da_ficha(respostas: dict) -> str:
    return _AGRAVOS.get(str(respostas.get("agravo") or ""), "")


def nome_da_conta(user) -> str:
    return str(getattr(user, "name", "") or getattr(user, "email", "") or "").strip()


# ---------------------------------------------------------------------------
# Panorama das unidades (somente contagens)
# ---------------------------------------------------------------------------

def agravo_canonico(texto: object) -> str:
    chave = _chave(texto)
    if "chik" in chave:
        return "Chikungunya"
    return "Dengue" if "dengue" in chave else ""


def semana_epidemiologica(dia: date) -> tuple[int, int, date]:
    """(ano, semana, domingo em que começa). A SE vai de domingo a sábado; a SE 1 é a primeira com 4 dias em janeiro."""
    inicio = dia - timedelta(days=(dia.weekday() + 1) % 7)
    ano = (inicio + timedelta(days=3)).year
    primeiro = date(ano, 1, 1)
    inicio_ano = primeiro - timedelta(days=(primeiro.weekday() + 1) % 7)
    if (inicio_ano + timedelta(days=3)).year < ano:
        inicio_ano += timedelta(days=7)
    return ano, (inicio - inicio_ano).days // 7 + 1, inicio


class IndiceUnidades:
    """Liga o nome ou o CNES escrito na origem à unidade cadastrada (nome ou outros nomes informados)."""

    def __init__(self, unidades):
        self.por_nome: dict[str, int] = {}
        self.por_cnes: dict[str, int] = {}
        for unidade in unidades:
            for nome in (unidade.nome, *_apelidos(unidade.apelidos)):
                self.por_nome.setdefault(_chave(nome), unidade.id)
            if unidade.cnes:
                self.por_cnes.setdefault(unidade.cnes, unidade.id)
        self.por_nome.pop("", None)

    def resolver(self, texto: object) -> int | None:
        chave = _chave(texto)
        if not chave:
            return None
        return self.por_nome.get(chave) or self.por_cnes.get(re.sub(r"\D", "", str(texto)))


def _registro_de_teste(ficha: object, nome: object, id_estudo: object) -> bool:
    from services.sfa_service import SFA_TEST_NAME_PREFIX
    return (str(ficha or "").upper().startswith("TESTE-") or str(nome or "").startswith(SFA_TEST_NAME_PREFIX)
            or str(id_estudo or "").upper().startswith("SFA-TESTE"))


def panorama(hoje: date, *, agravo: str = "", minhas: tuple[int, ...] = (), detalhar: bool = False) -> dict:
    """Notificações por unidade na semana, nas últimas 4 semanas e no ano. Nenhum dado de pessoa sai daqui."""
    import json
    from models.sfa import SfaSinanLog, SfaUnidadeSaude
    from services.sfa_service import parse_data

    unidades = SfaUnidadeSaude.query.order_by(SfaUnidadeSaude.nome).all()
    indice = IndiceUnidades(unidades)
    ano_se, semana, inicio_semana = semana_epidemiologica(hoje)
    inicio_quatro = inicio_semana - timedelta(days=21)

    colunas = (SfaSinanLog.id, SfaSinanLog.ficha_sinan, SfaSinanLog.nome, SfaSinanLog.id_estudo_vinculado,
               SfaSinanLog.data_notificacao, SfaSinanLog.agravo, SfaSinanLog.unidade_notificante,
               SfaSinanLog.unidade_id)
    registros = [r for r in SfaSinanLog.query.with_entities(*colunas).all()
                 if not _registro_de_teste(r.ficha_sinan, r.nome, r.id_estudo_vinculado)]
    # Registros anteriores às colunas de agravo e unidade: o que houver está nas variáveis estruturadas.
    incompletos = [r.id for r in registros if not r.agravo or not (r.unidade_id or r.unidade_notificante)]
    estruturados: dict[int, dict] = {}
    for inicio in range(0, len(incompletos), 500):
        lote = incompletos[inicio:inicio + 500]
        for log_id, bruto in (SfaSinanLog.query.with_entities(SfaSinanLog.id, SfaSinanLog.dados_json)
                              .filter(SfaSinanLog.id.in_(lote), SfaSinanLog.dados_json.isnot(None)).all()):
            try:
                dados = json.loads(bruto)
            except (TypeError, ValueError):
                continue
            if isinstance(dados, dict):
                estruturados[log_id] = dados

    vazio = lambda: {"semana": 0, "quatro": 0, "ano": 0}
    contagem: dict[int | None, dict[str, int]] = {}
    sem_nome: Counter = Counter()
    sem_data = 0
    for r in registros:
        extra = estruturados.get(r.id, {})
        if agravo and agravo_canonico(r.agravo or extra.get("agravo")) != agravo:
            continue
        dia = parse_data(r.data_notificacao)
        if dia is None:
            sem_data += 1
            continue
        if dia.year != hoje.year and dia < inicio_quatro:
            continue
        origem = r.unidade_notificante or extra.get("unidade_notificante") or ""
        unidade_id = r.unidade_id or indice.resolver(origem)
        linha = contagem.setdefault(unidade_id, vazio())
        linha["ano"] += dia.year == hoje.year
        linha["quatro"] += inicio_quatro <= dia <= hoje
        linha["semana"] += inicio_semana <= dia <= hoje
        if unidade_id is None and dia.year == hoje.year:
            sem_nome[" ".join(str(origem).split()) or "(unidade em branco na origem)"] += 1

    linhas = [{"id": u.id, "nome": u.nome, "minha": u.id in minhas, **contagem.get(u.id, vazio())}
              for u in unidades if u.ativa or u.id in contagem]
    linhas.sort(key=lambda linha: (-linha["ano"], -linha["quatro"], linha["nome"]))
    outras = contagem.get(None)
    total = vazio()
    for linha in [*linhas, *([outras] if outras else [])]:
        for chave in total:
            total[chave] += linha[chave]
    return {
        "linhas": linhas, "sem_unidade": outras, "total": total, "ano": hoje.year,
        "semana": semana, "ano_semana": ano_se, "inicio_semana": inicio_semana, "inicio_quatro": inicio_quatro,
        "hoje": hoje, "maior": max([linha["quatro"] for linha in linhas] + [1]),
        "sem_data": sem_data if detalhar else 0,
        "nomes_sem_unidade": sem_nome.most_common(30) if detalhar else [],
    }
