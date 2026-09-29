"""Simulações com voluntários: grupos, percurso SINAN → T0 → T7 → T30 e análise.

Cada grupo (ex.: "Instituto", "Equipe da vigilância") tem um link de convite.
Quem entra recebe um link pessoal e responde às mesmas perguntas, com as mesmas
validações, dos formulários reais. As respostas ficam só nas tabelas
``sfa_simulacao_*``: nada aqui cria SfaPaciente, registro SINAN ou assinatura
de TCLE, e a coorte municipal nunca enxerga estes dados.

A análise trabalha sobre "variáveis" achatadas a partir dos esquemas vigentes,
de modo que um mesmo motor serve para a ficha SINAN (matrizes, idade, exames)
e para os formulários T0/T7/T30 (rádio, múltipla escolha, números, datas).
"""
from __future__ import annotations

import copy
import io
import json
import math
import re
import secrets
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from security.csv_safe import safe_csv_dict_writer

ETAPAS = ("sinan", "t0", "t7", "t30")
ETAPA_ROTULOS = {"sinan": "Ficha SINAN", "t0": "T0", "t7": "T7", "t30": "T30"}
ETAPA_DESCRICOES = {
    "sinan": "Notificação preenchida pela unidade de saúde, antes do T0.",
    "t0": "Primeira entrevista com a pessoa doente.",
    "t7": "Acompanhamento no 7º dia de doença.",
    "t30": "Encerramento no 30º dia de doença.",
}
DIAS_ALVO = {"t7": 7, "t30": 30}
AGENDAS = {
    "imediata": "Sequencial imediata: cada etapa abre logo após a anterior",
    "protocolo": "Calendário do protocolo: T7 no D7 e T30 no D30 do início dos sintomas",
}
PERFIS = [
    "Profissional da assistência à saúde",
    "Vigilância em saúde",
    "Docente ou pesquisador(a)",
    "Estudante",
    "Gestão ou área administrativa",
    "Outro",
]
EXPERIENCIAS_SINAN = [
    "Nunca preenchi uma ficha SINAN",
    "Já preenchi algumas vezes",
    "Preencho com frequência",
]
FACILIDADE = [("1", "Muito difícil"), ("2", "Difícil"), ("3", "Regular"), ("4", "Fácil"), ("5", "Muito fácil")]
FEEDBACK_TEXTOS = [
    ("confusa", "Alguma pergunta ficou confusa? Qual, e por quê?"),
    ("faltou", "Faltou alguma opção de resposta ou pergunta?"),
    ("sugestao", "Que mudança você sugere?"),
]
FEEDBACK_ROTULOS = {"confusa": "Pergunta confusa", "faltou": "Faltou", "sugestao": "Sugestão"}

# Paleta categórica validada (ordem fixa, checada para daltonismo). A cor de
# um grupo depende da posição dele entre todos os grupos, não do filtro.
COR_GRUPOS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
COR_EXCEDENTE = "#8c8b86"
COR_CONSOLIDADO = "#52514e"

MARCADOR_OCULTO = "[preenchido]"
# Identificadores diretos nunca são guardados, mesmo que o voluntário digite
# dados reais: fica só a marca de que o campo foi preenchido.
SINAN_IDENTIFICADORES = {
    "nome", "nome_mae", "cartao_sus", "telefone", "logradouro", "numero_residencia",
    "complemento", "cep", "ponto_referencia", "geo_campo_1", "geo_campo_2",
}
SINAN_INVESTIGADOR_IDENTIFICADORES = {"nome", "assinatura"}
FORM_IDENTIFICADORES = {"respondent_name"}
# Chaves que o coletor nativo injeta a partir do paciente; na simulação vêm
# vazias e não têm significado analítico.
CAMPOS_TECNICOS = {
    "token_acesso", "id_estudo", "ficha_sinan", "nome", "data_nascimento",
    "_imported_context", "consentimento_ip", "consentimento_user_agent",
}
LIMITE_TEXTO = 3000
LIMITE_CENARIO = 4000
DURACAO_MAXIMA_SEGUNDOS = 2 * 24 * 3600
BR_TZ = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def hoje_local() -> date:
    return datetime.now(BR_TZ).date()


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _como_utc(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    # SQLite devolve datetimes sem fuso; gravamos sempre em UTC.
    return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor.astimezone(timezone.utc)


def formatar_data_hora(valor: datetime | None) -> str:
    valor = _como_utc(valor)
    return valor.astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M") if valor else ""


def formatar_numero(valor, casas: int = 1) -> str:
    if valor is None:
        return "–"
    if casas == 0 or float(valor).is_integer() and casas <= 1:
        texto = f"{valor:,.0f}"
    else:
        texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_pct(valor) -> str:
    return "–" if valor is None else f"{round(valor * 100):d}%"


def formatar_duracao(segundos) -> str:
    if segundos is None:
        return "–"
    minutos = segundos / 60
    if minutos < 1:
        return "< 1 min"
    if minutos < 90:
        return f"{formatar_numero(minutos, 1)} min"
    return f"{formatar_numero(minutos / 60, 1)} h"


def _texto(form, nome: str, limite: int) -> str:
    valor = str(form.get(nome) or "").strip()
    if len(valor) > limite:
        raise ValueError("Um dos textos ficou longo demais. Resuma a resposta e envie novamente.")
    return valor


def _json(texto, padrao):
    try:
        valor = json.loads(texto or "")
    except (TypeError, ValueError):
        return padrao
    return valor if isinstance(valor, type(padrao)) else padrao


def _parse_data(valor) -> date | None:
    from services.sfa_service import parse_data
    return parse_data(valor)


def _numero(valor) -> float | None:
    if valor in (None, "", []):
        return None
    try:
        numero = float(str(valor).strip().replace(",", "."))
    except ValueError:
        return None
    return numero if math.isfinite(numero) else None


def _percentil(valores: list[float], fracao: float) -> float | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    posicao = (len(ordenados) - 1) * fracao
    baixo, alto = math.floor(posicao), math.ceil(posicao)
    if baixo == alto:
        return ordenados[int(posicao)]
    return ordenados[baixo] + (ordenados[alto] - ordenados[baixo]) * (posicao - baixo)


def _estatisticas(valores: list[float]) -> dict | None:
    if not valores:
        return None
    return {
        "n": len(valores),
        "media": sum(valores) / len(valores),
        "mediana": _percentil(valores, 0.5),
        "p25": _percentil(valores, 0.25),
        "p75": _percentil(valores, 0.75),
        "min": min(valores),
        "max": max(valores),
    }


# ---------------------------------------------------------------------------
# Grupos e participantes
# ---------------------------------------------------------------------------

def etapas_grupo(grupo) -> list[str]:
    escolhidas = {item.strip() for item in str(getattr(grupo, "etapas", "") or "").split(",")}
    escolhidas.add("t0")
    return [etapa for etapa in ETAPAS if etapa in escolhidas]


def cenarios_grupo(grupo) -> dict[str, str]:
    dados = _json(getattr(grupo, "cenarios_json", "{}"), {})
    return {chave: str(dados.get(chave) or "").strip() for chave in ("geral", *ETAPAS)
            if str(dados.get(chave) or "").strip()}


def _validar_grupo(nome, descricao, etapas, agenda, cenarios) -> tuple[str, str, str, str, str]:
    nome = str(nome or "").strip()
    if not nome or len(nome) > 120:
        raise ValueError("Dê um nome ao grupo, com até 120 caracteres.")
    descricao = str(descricao or "").strip()
    if len(descricao) > LIMITE_TEXTO:
        raise ValueError("A descrição do grupo ficou longa demais.")
    etapas_validas = [etapa for etapa in ETAPAS if etapa in set(etapas or []) or etapa == "t0"]
    if agenda not in AGENDAS:
        raise ValueError("Escolha como as etapas serão liberadas.")
    limpos = {}
    for chave, texto in (cenarios or {}).items():
        if chave not in ("geral", *ETAPAS):
            continue
        texto = str(texto or "").strip()
        if len(texto) > LIMITE_CENARIO:
            raise ValueError("Um dos roteiros do caso ficou longo demais.")
        if texto:
            limpos[chave] = texto
    return nome, descricao, ",".join(etapas_validas), agenda, json.dumps(limpos, ensure_ascii=False)


def criar_grupo(nome, descricao, etapas, agenda, cenarios, creation_key):
    """Cadastro idempotente: reenviar o mesmo formulário não duplica o grupo."""
    from extensions import db
    from models.sfa import SfaSimulacaoGrupo
    from sqlalchemy.exc import IntegrityError

    creation_key = str(creation_key or "").strip()
    if not creation_key or len(creation_key) > 64:
        raise ValueError("Recarregue a página e tente novamente.")
    existente = SfaSimulacaoGrupo.query.filter_by(creation_key=creation_key).first()
    if existente:
        return existente
    nome, descricao, etapas_txt, agenda, cenarios_txt = _validar_grupo(nome, descricao, etapas, agenda, cenarios)
    grupo = SfaSimulacaoGrupo(nome=nome, descricao=descricao, etapas=etapas_txt, agenda=agenda,
                              cenarios_json=cenarios_txt, token_convite=secrets.token_urlsafe(24),
                              creation_key=creation_key, status="aberto")
    db.session.add(grupo)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existente = SfaSimulacaoGrupo.query.filter_by(creation_key=creation_key).first()
        if existente:
            return existente
        raise
    return grupo


def atualizar_grupo(grupo, nome, descricao, etapas, agenda, cenarios):
    from extensions import db

    nome, descricao, etapas_txt, agenda, cenarios_txt = _validar_grupo(nome, descricao, etapas, agenda, cenarios)
    grupo.nome, grupo.descricao, grupo.etapas = nome, descricao, etapas_txt
    grupo.agenda, grupo.cenarios_json = agenda, cenarios_txt
    db.session.commit()
    return grupo


def definir_status_grupo(grupo, aberto: bool):
    from extensions import db

    grupo.status = "aberto" if aberto else "encerrado"
    db.session.commit()


def _proximo_codigo(grupo_id: int) -> str:
    from models.sfa import SfaSimulacaoParticipante

    maior = 0
    for (codigo,) in SfaSimulacaoParticipante.query.with_entities(SfaSimulacaoParticipante.codigo).filter_by(grupo_id=grupo_id):
        match = re.fullmatch(r"P(\d+)", codigo or "")
        if match:
            maior = max(maior, int(match.group(1)))
    return f"P{maior + 1:02d}"


def inscrever_participante(grupo, apelido="", perfil="", experiencia=""):
    from extensions import db
    from models.sfa import SfaSimulacaoParticipante
    from sqlalchemy.exc import IntegrityError

    if grupo.status != "aberto":
        raise ValueError("Este grupo foi encerrado e não recebe novos participantes.")
    apelido = str(apelido or "").strip()
    if len(apelido) > 60:
        raise ValueError("Use um apelido com até 60 caracteres.")
    perfil = perfil if perfil in PERFIS else ""
    experiencia = experiencia if experiencia in EXPERIENCIAS_SINAN else ""
    for _tentativa in range(5):
        participante = SfaSimulacaoParticipante(
            grupo_id=grupo.id, codigo=_proximo_codigo(grupo.id), apelido=apelido,
            perfil=perfil, experiencia_sinan=experiencia, token=secrets.token_urlsafe(32))
        db.session.add(participante)
        try:
            db.session.commit()
            return participante
        except IntegrityError:
            # Duas inscrições simultâneas disputaram o mesmo código.
            db.session.rollback()
    raise RuntimeError("Não foi possível reservar um código agora. Tente novamente.")


def remover_participante(participante):
    from extensions import db

    db.session.delete(participante)
    db.session.commit()


def remover_grupo_vazio(grupo):
    from extensions import db

    if any(p.respostas for p in grupo.participantes):
        raise ValueError("O grupo já tem respostas. Encerre-o em vez de excluir, para preservar os dados.")
    db.session.delete(grupo)
    db.session.commit()


def nome_participante(participante) -> str:
    apelido = str(getattr(participante, "apelido", "") or "").strip()
    return f"{participante.codigo} · {apelido}" if apelido else participante.codigo


# ---------------------------------------------------------------------------
# Respostas e calendário do participante
# ---------------------------------------------------------------------------

def carregar_respostas(resposta) -> dict:
    return _json(getattr(resposta, "respostas_json", "{}"), {}) if resposta else {}


def carregar_avaliacao(resposta) -> dict:
    return _json(getattr(resposta, "avaliacao_json", "{}"), {}) if resposta else {}


def carregar_erros(resposta) -> list[list[str]]:
    tentativas = _json(getattr(resposta, "erros_json", "[]"), []) if resposta else []
    return [[str(item) for item in tentativa] for tentativa in tentativas if isinstance(tentativa, list)]


def respostas_por_etapa(participante) -> dict:
    return {resposta.etapa: resposta for resposta in participante.respostas}


def inicio_sintomas_participante(participante) -> tuple[date | None, str]:
    """Na simulação vale o T0; sem T0, a data da ficha SINAN."""
    respostas = respostas_por_etapa(participante)
    for etapa, fonte in (("t0", "T0"), ("sinan", "Ficha SINAN")):
        inicio = _parse_data(carregar_respostas(respostas.get(etapa)).get("data_inicio_sintomas"))
        if inicio:
            return inicio, fonte
    return None, ""


def calendario_participante(participante, hoje: date | None = None) -> dict:
    hoje = hoje or hoje_local()
    grupo = participante.grupo
    respostas = respostas_por_etapa(participante)
    inicio, fonte = inicio_sintomas_participante(participante)
    itens = []
    anterior = None
    for etapa in etapas_grupo(grupo):
        resposta = respostas.get(etapa)
        abre_em = inicio + timedelta(days=DIAS_ALVO[etapa]) if inicio and etapa in DIAS_ALVO else None
        status, motivo = "disponivel", ""
        if resposta:
            status = "respondida"
        elif grupo.status != "aberto":
            status, motivo = "encerrada", "O grupo foi encerrado pela equipe e não recebe novas respostas."
        elif anterior and anterior["status"] != "respondida":
            status, motivo = "bloqueada", f"Responda primeiro a etapa {anterior['rotulo']}."
        elif grupo.agenda == "protocolo" and etapa in DIAS_ALVO:
            if not inicio:
                status, motivo = "bloqueada", "Informe o início dos sintomas no T0 para liberar esta etapa."
            elif hoje < abre_em:
                status = "agendada"
                motivo = f"Abre em {abre_em:%d/%m/%Y}, no D{DIAS_ALVO[etapa]} do início dos sintomas."
        item = {"etapa": etapa, "rotulo": ETAPA_ROTULOS[etapa], "descricao": ETAPA_DESCRICOES[etapa],
                "status": status, "motivo": motivo, "abre_em": abre_em, "resposta": resposta}
        itens.append(item)
        anterior = item
    return {
        "etapas": itens,
        "inicio": inicio,
        "inicio_fonte": fonte,
        "proxima": next((item for item in itens if item["status"] == "disponivel"), None),
        "concluido": all(item["status"] == "respondida" for item in itens),
        "respondidas": sum(item["status"] == "respondida" for item in itens),
    }


def _registro_para_regras(resposta) -> SimpleNamespace:
    return SimpleNamespace(
        dados_json=json.dumps(carregar_respostas(resposta), ensure_ascii=False),
        timestamp=_como_utc(resposta.enviado_em), id=resposta.id, data_inicio_sintomas=None)


def adaptador_participante(participante) -> SimpleNamespace:
    """Objeto com a forma de SfaPaciente que os coletores nativos esperam.

    Identificadores ficam vazios de propósito: com ``id_estudo`` e
    ``ficha_sinan`` em branco o coletor não consulta o SINAN real, então um
    número de ficha fictício nunca puxa dados de um caso verdadeiro.
    """
    respostas = respostas_por_etapa(participante)
    inicio_sinan = carregar_respostas(respostas.get("sinan")).get("data_inicio_sintomas")
    return SimpleNamespace(
        id_estudo="", ficha_sinan="", nome="", data_nascimento="", token_acesso="",
        retorno_contato="", contexto=None, _sinan_log=None,
        _sinan_dados={"data_inicio_sintomas": inicio_sinan} if inicio_sinan else {},
        resposta_t0=_registro_para_regras(respostas["t0"]) if "t0" in respostas else None,
        respostas_t7=[_registro_para_regras(respostas["t7"])] if "t7" in respostas else [],
        respostas_t10=[],
        respostas_t30=[_registro_para_regras(respostas["t30"])] if "t30" in respostas else [],
    )


def _carregador_schema(etapa: str):
    from services import sfa_service

    return {"t0": sfa_service.carregar_t0_form_schema, "t7": sfa_service.carregar_t7_form_schema,
            "t30": sfa_service.carregar_t30_form_schema}[etapa]


def schema_base_etapa(etapa: str) -> dict:
    if etapa == "sinan":
        from services.sfa_pre_t0 import carregar_esquema_pre_t0
        return carregar_esquema_pre_t0()
    return _carregador_schema(etapa)()


def schema_etapa(etapa: str, participante) -> dict:
    """Esquema que o participante vê, com as condições resolvidas pelas etapas anteriores."""
    if etapa == "sinan":
        return schema_base_etapa("sinan")
    from services.sfa_service import filtrar_form_schema_condicional
    return filtrar_form_schema_condicional(schema_base_etapa(etapa), adaptador_participante(participante), etapa)


def valores_iniciais(etapa: str, schema: dict, participante) -> dict:
    from services import sfa_service

    construtor = {"t0": sfa_service.construir_valores_iniciais_t0,
                  "t7": sfa_service.construir_valores_iniciais_t7,
                  "t30": sfa_service.construir_valores_iniciais_t30}[etapa]
    return construtor(adaptador_participante(participante), schema)


def coletar_etapa(etapa: str, schema: dict, form, participante) -> tuple[dict, dict[str, str]]:
    """Aplica as validações reais. Devolve (dados, erros por campo)."""
    if etapa == "sinan":
        from services.sfa_pre_t0 import coletar_respostas_pre_t0
        try:
            return coletar_respostas_pre_t0(form, schema), {}
        except ValueError as exc:
            return {}, {"__all__": str(exc)}
    from services import sfa_service

    coletor = {"t0": sfa_service.coletar_resposta_t0_nativa,
               "t7": sfa_service.coletar_resposta_t7_nativa,
               "t30": sfa_service.coletar_resposta_t30_nativa}[etapa]
    return coletor(schema, form, adaptador_participante(participante))


def _ocultar(valor) -> str:
    return MARCADOR_OCULTO if str(valor or "").strip() else ""


def redigir_sinan(respostas: dict) -> dict:
    limpo = copy.deepcopy(respostas)
    for chave in SINAN_IDENTIFICADORES & set(limpo):
        valor = limpo[chave]
        limpo[chave] = {k: _ocultar(v) for k, v in valor.items()} if isinstance(valor, dict) else _ocultar(valor)
    investigador = limpo.get("investigador")
    if isinstance(investigador, dict):
        for chave in SINAN_INVESTIGADOR_IDENTIFICADORES & set(investigador):
            investigador[chave] = _ocultar(investigador[chave])
    return limpo


def limpar_payload_formulario(etapa: str, dados: dict, schema: dict) -> dict:
    from services.sfa_service import iterar_campos_form

    chaves = {campo["key"] for campo in iterar_campos_form(schema)}
    limpo = {k: v for k, v in dados.items() if not (k in CAMPOS_TECNICOS and k not in chaves)}
    for chave in FORM_IDENTIFICADORES & chaves:
        limpo[chave] = _ocultar(limpo.get(chave))
    limpo["_origem"] = f"simulacao_{etapa}"
    return limpo


# Tempo de preenchimento: o formulário carrega o instante em que foi aberto,
# assinado, e ele é mantido entre tentativas com erro.
def _serializador():
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer

    segredo = current_app.secret_key
    return URLSafeTimedSerializer(segredo, salt="sfa-simulacao-inicio") if segredo else None


def assinar_inicio(participante, etapa: str) -> str:
    serializador = _serializador()
    return serializador.dumps({"p": participante.id, "e": etapa}) if serializador else ""


def ler_inicio(valor: str, participante, etapa: str) -> datetime | None:
    from itsdangerous import BadSignature

    serializador = _serializador()
    if not serializador or not valor:
        return None
    try:
        dados, instante = serializador.loads(valor, max_age=DURACAO_MAXIMA_SEGUNDOS, return_timestamp=True)
    except (BadSignature, TypeError, ValueError):
        return None
    if dados != {"p": participante.id, "e": etapa}:
        return None
    return _como_utc(instante)


def inicio_valido_ou_novo(valor: str, participante, etapa: str) -> str:
    return valor if ler_inicio(valor, participante, etapa) else assinar_inicio(participante, etapa)


def _tentativas_validas(texto) -> list[list[str]]:
    """O histórico volta do navegador: aceita só listas curtas de textos curtos."""
    return [[item for item in tentativa if isinstance(item, str) and len(item) <= 160][:60]
            for tentativa in _json(texto, []) if isinstance(tentativa, list)][:30]


def acumular_erros(valor_anterior: str, erros: dict[str, str]) -> str:
    """Cada tentativa com erro vira uma lista de campos; o histórico viaja no formulário."""
    tentativas = _tentativas_validas(valor_anterior)
    atual = []
    for chave, mensagem in erros.items():
        atual.append(str(mensagem if chave == "__all__" else chave)[:160])
    if atual:
        tentativas.append(sorted(atual))
    return json.dumps(tentativas, ensure_ascii=False)


def salvar_resposta(participante, etapa: str, dados: dict, schema: dict, inicio_assinado: str, erros_txt: str):
    """Grava a etapa. Devolve (resposta, criada)."""
    from extensions import db
    from models.sfa import SfaSimulacaoResposta
    from sqlalchemy.exc import IntegrityError

    if etapa == "sinan":
        payload = redigir_sinan(dados)
        versao = str(schema.get("version") or "sinan")
    else:
        payload = limpar_payload_formulario(etapa, dados, schema)
        versao = str(dados.get("_instrument_version") or schema.get("instrument_version") or "")
    agora = _agora_utc()
    iniciado_em = ler_inicio(inicio_assinado, participante, etapa)
    duracao = int((agora - iniciado_em).total_seconds()) if iniciado_em else None
    inicio = _parse_data(payload.get("data_inicio_sintomas")) if etapa in ("sinan", "t0") else None
    inicio = inicio or inicio_sintomas_participante(participante)[0]
    payload["_simulacao"] = {
        "grupo_id": participante.grupo_id, "participante": participante.codigo,
        "agenda": participante.grupo.agenda, "data_envio": hoje_local().isoformat(),
        "inicio_sintomas": inicio.isoformat() if inicio else "",
        "dia_doenca": (hoje_local() - inicio).days if inicio else None,
    }
    tentativas = _tentativas_validas(erros_txt)
    resposta = SfaSimulacaoResposta(
        participante_id=participante.id, etapa=etapa, instrument_version=versao[:80],
        respostas_json=json.dumps(payload, ensure_ascii=False), avaliacao_json="{}",
        erros_json=json.dumps(tentativas, ensure_ascii=False), iniciado_em=iniciado_em,
        enviado_em=agora, duracao_segundos=max(0, duracao) if duracao is not None else None)
    db.session.add(resposta)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existente = SfaSimulacaoResposta.query.filter_by(participante_id=participante.id, etapa=etapa).first()
        if existente is None:
            raise
        return existente, False
    return resposta, True


def registrar_avaliacao(resposta, form) -> dict:
    from extensions import db

    facilidade = str(form.get("facilidade") or "").strip()
    avaliacao = {"facilidade": facilidade if facilidade in dict(FACILIDADE) else ""}
    for chave, _rotulo in FEEDBACK_TEXTOS:
        avaliacao[chave] = _texto(form, chave, LIMITE_TEXTO)
    avaliacao["registrada_em"] = _agora_utc().isoformat(timespec="seconds")
    resposta.avaliacao_json = json.dumps(avaliacao, ensure_ascii=False)
    db.session.commit()
    return avaliacao


# ---------------------------------------------------------------------------
# Variáveis analíticas
# ---------------------------------------------------------------------------

def _var(vid, rotulo, secao, tipo, extrair, opcoes=None, visivel=None):
    return {"id": vid, "rotulo": rotulo, "secao": secao, "tipo": tipo, "extrair": extrair,
            "opcoes": list(opcoes or []), "visivel": visivel}


def _get(chave, sub=None):
    def extrair(payload):
        valor = payload.get(chave)
        if sub is not None:
            valor = valor.get(sub) if isinstance(valor, dict) else ""
        return valor
    return extrair


def _idade_em_anos(payload):
    idade = payload.get("idade") if isinstance(payload.get("idade"), dict) else {}
    valor = _numero(idade.get("valor"))
    fator = {"1": 1 / 8760, "2": 1 / 365, "3": 1 / 12, "4": 1}.get(str(idade.get("unidade") or ""))
    return round(valor * fator, 2) if valor is not None and fator else None


def _variaveis_sinan(schema: dict) -> list[dict]:
    variaveis = []
    for secao in schema.get("sections", []):
        titulo = secao.get("title", "")
        for campo in secao.get("fields", []):
            tipo, chave = campo["type"], campo["key"]
            numero = str(campo.get("number") or "")
            rotulo = f"{numero}. {campo.get('campo', chave)}" if numero else campo.get("campo", chave)
            oculto = chave in SINAN_IDENTIFICADORES
            opcoes = [(o["value"], o["label"]) for o in campo.get("options", [])]
            if tipo == "fixed":
                continue
            if tipo in ("text", "tel", "textarea"):
                variaveis.append(_var(chave, rotulo, titulo, "oculto" if oculto else "texto", _get(chave)))
            elif tipo == "date":
                variaveis.append(_var(chave, rotulo, titulo, "data", _get(chave)))
            elif tipo == "paired_text":
                variaveis.append(_var(chave, rotulo, titulo, "oculto" if oculto else "texto", _get(chave, "valor")))
                variaveis.append(_var(f"{chave}__codigo", f"{rotulo} — {campo.get('extra_label', 'Código')}",
                                      titulo, "oculto" if oculto else "texto", _get(chave, "codigo")))
            elif tipo == "radio":
                variaveis.append(_var(chave, rotulo, titulo, "categorica", _get(chave), opcoes))
            elif tipo == "age":
                variaveis.append(_var("idade_anos", f"{rotulo} (convertida em anos)", titulo, "numerica", _idade_em_anos))
                variaveis.append(_var("idade__unidade", f"{rotulo} — unidade", titulo, "categorica",
                                      _get(chave, "unidade"), [(o["value"], o["label"]) for o in campo["units"]]))
            elif tipo == "matrix":
                for item, item_rotulo in campo["items"]:
                    variaveis.append(_var(f"{chave}__{item}", f"{rotulo} — {item_rotulo}", titulo,
                                          "categorica", _get(chave, item), opcoes))
            elif tipo == "flag_matrix":
                variaveis.append(_var(chave, rotulo, titulo, "categorica", _get(chave, "status"), opcoes))
                variaveis.append(_var(f"{chave}__sinais", f"{rotulo} — sinais marcados", titulo, "multipla",
                                      _get(chave, "sinais_marcados"), campo["items"]))
            elif tipo == "test_result":
                variaveis.append(_var(chave, f"{rotulo} — resultado", titulo, "categorica", _get(chave, "resultado"), opcoes))
                variaveis.append(_var(f"{chave}__amostras", f"{rotulo} — amostras", titulo, "multipla",
                                      _get(chave, "amostras"), campo["samples"]))
            elif tipo == "severity":
                itens = [item for _grupo, grupo_itens in campo["groups"] for item in grupo_itens]

                def marcados(payload, chave=chave):
                    valor = payload.get(chave) if isinstance(payload.get(chave), dict) else {}
                    sinais = valor.get("sinais_marcados") if isinstance(valor.get("sinais_marcados"), dict) else {}
                    return [item for item, marcado in sinais.items() if marcado == "1"]
                variaveis.append(_var(chave, rotulo, titulo, "categorica", _get(chave, "status"), opcoes))
                variaveis.append(_var(f"{chave}__sinais", f"{rotulo} — sinais marcados", titulo, "multipla", marcados, itens))
                variaveis.append(_var(f"{chave}__outros", f"{rotulo} — outros órgãos", titulo, "texto",
                                      _get(chave, "outros_orgaos_especificar")))
            elif tipo == "investigator":
                for item, item_rotulo, _maximo in campo["items"]:
                    variaveis.append(_var(f"{chave}__{item}", f"Investigador — {item_rotulo}", titulo,
                                          "oculto" if item in SINAN_INVESTIGADOR_IDENTIFICADORES else "texto",
                                          _get(chave, item)))
    return variaveis


def _variaveis_formulario(etapa: str, schema: dict) -> list[dict]:
    from services.sfa_service import _avaliar_regra_visibilidade

    variaveis = []
    for secao in schema.get("sections", []):
        titulo = secao.get("title", "")
        for campo in secao.get("fields", []):
            if not isinstance(campo, dict) or not campo.get("key"):
                continue
            chave, tipo = campo["key"], campo.get("type", "text")
            regra = campo.get("visible_if")
            visivel = (lambda payload, anteriores, regra=regra: _avaliar_regra_visibilidade(regra, payload, anteriores)) if regra else None
            if tipo in ("radio", "select"):
                variaveis.append(_var(chave, campo.get("label", chave), titulo, "categorica", _get(chave),
                                      [(o, o) for o in campo.get("options", [])], visivel))
            elif tipo == "checkboxes":
                variaveis.append(_var(chave, campo.get("label", chave), titulo, "multipla", _get(chave),
                                      [(o, o) for o in campo.get("options", [])], visivel))
            elif tipo == "number":
                variaveis.append(_var(chave, campo.get("label", chave), titulo, "numerica", _get(chave), visivel=visivel))
            elif tipo == "date":
                variaveis.append(_var(chave, campo.get("label", chave), titulo, "data", _get(chave), visivel=visivel))
            else:
                variaveis.append(_var(chave, campo.get("label", chave), titulo,
                                      "oculto" if chave in FORM_IDENTIFICADORES else "texto", _get(chave), visivel=visivel))
    variaveis.append(_var("_dia_doenca", f"Dia da doença no envio do {ETAPA_ROTULOS[etapa]} (D0 = início dos sintomas)",
                          "Calendário da simulação", "numerica",
                          lambda payload: (payload.get("_simulacao") or {}).get("dia_doenca")))
    return variaveis


def variaveis_etapa(etapa: str, schema: dict | None = None) -> list[dict]:
    schema = schema or schema_base_etapa(etapa)
    return _variaveis_sinan(schema) if etapa == "sinan" else _variaveis_formulario(etapa, schema)


def _normalizar(var: dict, bruto):
    tipo = var["tipo"]
    if tipo == "multipla":
        if isinstance(bruto, str):
            bruto = [bruto] if bruto.strip() else []
        return [str(item) for item in (bruto or []) if str(item or "").strip()]
    if tipo == "numerica":
        return _numero(bruto)
    if tipo == "data":
        return _parse_data(bruto)
    texto = "" if bruto is None else str(bruto).strip()
    return texto


def _preenchido(valor) -> bool:
    return valor not in (None, "", [])


def _rotulo_opcao(var: dict, valor) -> str:
    return dict(var["opcoes"]).get(valor, valor)


def valor_legivel(var: dict, valor) -> str:
    if not _preenchido(valor):
        return ""
    if var["tipo"] == "multipla":
        return " | ".join(_rotulo_opcao(var, item) for item in valor)
    if var["tipo"] == "categorica":
        return _rotulo_opcao(var, valor)
    if var["tipo"] == "numerica":
        return formatar_numero(valor, 2).rstrip("0").rstrip(",") if not float(valor).is_integer() else formatar_numero(valor, 0)
    if var["tipo"] == "data":
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def _payloads_anteriores(respostas: dict, etapa: str) -> list[dict]:
    anteriores = {"t7": ["t0"], "t30": ["t0", "t7"]}.get(etapa, [])
    return [carregar_respostas(respostas[e]) for e in anteriores if e in respostas]


def respostas_legiveis(etapa: str, resposta, respostas_participante: dict, variaveis=None) -> list[dict]:
    """Pergunta a pergunta, para a ficha individual do participante."""
    payload = carregar_respostas(resposta)
    anteriores = _payloads_anteriores(respostas_participante, etapa)
    linhas = []
    for var in variaveis if variaveis is not None else variaveis_etapa(etapa):
        exibida = var["visivel"](payload, anteriores) if var["visivel"] else True
        valor = _normalizar(var, var["extrair"](payload))
        if not exibida and not _preenchido(valor):
            continue
        linhas.append({"secao": var["secao"], "rotulo": var["rotulo"], "tipo": var["tipo"],
                       "valor": valor_legivel(var, valor) if var["tipo"] != "oculto" else
                       ("Preenchido (conteúdo não guardado)" if _preenchido(valor) else ""),
                       "vazio": not _preenchido(valor)})
    return linhas


# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------

def _concordancia(var: dict, valores: list) -> float | None:
    """Com um mesmo caso fictício, respostas diferentes apontam pergunta ambígua."""
    if len(valores) < 2 or var["tipo"] in ("texto", "oculto"):
        return None
    if var["tipo"] == "multipla":
        conjuntos = [frozenset(v) for v in valores]
        pares = list(combinations(conjuntos, 2))
        return sum(len(a & b) / len(a | b) for a, b in pares) / len(pares)
    contagem = Counter(valores)
    return contagem.most_common(1)[0][1] / len(valores)


def _resumir_coluna(var: dict, observacoes: list[dict]) -> dict:
    exibidas = [obs for obs in observacoes if obs["exibida"]]
    valores = [obs["valor"] for obs in exibidas if _preenchido(obs["valor"])]
    resumo = {
        "n_respostas": len(observacoes),
        "n_exibida": len(exibidas),
        "n_preenchida": len(valores),
        "pct_preenchida": len(valores) / len(exibidas) if exibidas else None,
        "concordancia": _concordancia(var, valores),
    }
    tipo = var["tipo"]
    if tipo in ("categorica", "multipla"):
        contagem = Counter()
        for valor in valores:
            contagem.update(valor if tipo == "multipla" else [valor])
        ordem = [valor for valor, _ in var["opcoes"]] + sorted(set(contagem) - {v for v, _ in var["opcoes"]})
        resumo["opcoes"] = {valor: {"n": contagem.get(valor, 0),
                                    "pct": contagem.get(valor, 0) / len(valores) if valores else None}
                            for valor in ordem}
        resumo["ordem"] = ordem
    elif tipo == "numerica":
        resumo["estat"] = _estatisticas(valores)
    elif tipo == "data":
        if valores:
            moda, n_moda = Counter(valores).most_common(1)[0]
            resumo["datas"] = {"min": min(valores), "max": max(valores), "moda": moda, "n_moda": n_moda}
    elif tipo == "texto":
        resumo["textos"] = [(obs["participante"], obs["grupo"], obs["valor"]) for obs in exibidas
                            if _preenchido(obs["valor"])]
    return resumo


def _grupos_ordenados(grupos) -> list:
    return sorted(grupos, key=lambda g: g.id)


def _colunas(grupos) -> list[dict]:
    colunas = [{"chave": "todos", "rotulo": "Consolidado" if len(grupos) > 1 else grupos[0].nome,
                "grupo_ids": {g.id for g in grupos}, "consolidado": True}]
    if len(grupos) > 1:
        colunas += [{"chave": str(g.id), "rotulo": g.nome, "grupo_ids": {g.id}, "consolidado": False}
                    for g in grupos]
    return colunas


def montar_analise(grupos) -> dict:
    grupos = _grupos_ordenados(grupos)
    if not grupos:
        return {"vazio": True}
    colunas = _colunas(grupos)
    participantes = [p for g in grupos for p in g.participantes]
    respostas_de = {p.id: respostas_por_etapa(p) for p in participantes}
    # Cada JSON é lido uma vez; a análise percorre centenas de perguntas.
    payload_de = {r.id: carregar_respostas(r) for respostas in respostas_de.values() for r in respostas.values()}
    anteriores_de = {(p.id, etapa): [payload_de[respostas_de[p.id][e].id] for e in {"t7": ["t0"], "t30": ["t0", "t7"]}.get(etapa, [])
                                     if e in respostas_de[p.id]]
                     for p in participantes for etapa in ETAPAS}

    # Funil e perfil por coluna.
    funil, perfis, experiencias = [], {}, {}
    for coluna in colunas:
        membros = [p for p in participantes if p.grupo_id in coluna["grupo_ids"]]
        linha = {"coluna": coluna, "inscritos": len(membros), "etapas": []}
        for etapa in ETAPAS:
            elegiveis = [p for p in membros if etapa in etapas_grupo(p.grupo)]
            n = sum(etapa in respostas_de[p.id] for p in membros)
            linha["etapas"].append({"etapa": etapa, "n": n, "elegiveis": len(elegiveis),
                                    "pct": n / len(elegiveis) if elegiveis else None})
        funil.append(linha)
        perfis[coluna["chave"]] = Counter(p.perfil or "Não informado" for p in membros)
        experiencias[coluna["chave"]] = Counter(p.experiencia_sinan or "Não informado" for p in membros)

    etapas_com_resposta = [e for e in ETAPAS if any(e in respostas_de[p.id] for p in participantes)]
    etapas_presentes = [e for e in ETAPAS if any(e in etapas_grupo(g) for g in grupos)]

    # Esforço, facilidade e erros por etapa × coluna.
    resumo_etapas, erros_campos, comentarios = {}, {}, []
    for etapa in etapas_presentes:
        resumo_etapas[etapa] = {}
        rotulos = {var["id"]: var["rotulo"] for var in variaveis_etapa(etapa)} if etapa in etapas_com_resposta else {}
        contagem_erros = Counter()
        for coluna in colunas:
            respostas = [respostas_de[p.id][etapa] for p in participantes
                         if p.grupo_id in coluna["grupo_ids"] and etapa in respostas_de[p.id]]
            duracoes = [r.duracao_segundos for r in respostas if r.duracao_segundos is not None]
            notas = [int(carregar_avaliacao(r).get("facilidade")) for r in respostas
                     if str(carregar_avaliacao(r).get("facilidade") or "") in dict(FACILIDADE)]
            tentativas = [len(carregar_erros(r)) for r in respostas]
            resumo_etapas[etapa][coluna["chave"]] = {
                "n": len(respostas),
                "duracao": _estatisticas(duracoes),
                "facilidade": _estatisticas(notas),
                "facilidade_dist": Counter(notas),
                "com_erro": sum(t > 0 for t in tentativas),
                "pct_com_erro": sum(t > 0 for t in tentativas) / len(respostas) if respostas else None,
                "tentativas_media": sum(tentativas) / len(respostas) if respostas else None,
            }
            if coluna["consolidado"]:
                for resposta in respostas:
                    for tentativa in carregar_erros(resposta):
                        contagem_erros.update(rotulos.get(item, item) for item in tentativa)
        erros_campos[etapa] = contagem_erros.most_common(8)

    for p in participantes:
        for etapa, resposta in respostas_de[p.id].items():
            avaliacao = carregar_avaliacao(resposta)
            for chave, _rotulo in FEEDBACK_TEXTOS:
                if avaliacao.get(chave):
                    comentarios.append({"grupo": p.grupo.nome, "participante": p.codigo, "etapa": etapa,
                                        "etapa_rotulo": ETAPA_ROTULOS.get(etapa, etapa),
                                        "tipo": FEEDBACK_ROTULOS[chave], "texto": avaliacao[chave],
                                        "enviado_em": formatar_data_hora(resposta.enviado_em)})
    comentarios.sort(key=lambda c: (ETAPAS.index(c["etapa"]) if c["etapa"] in ETAPAS else 9, c["grupo"], c["participante"]))

    # Pergunta a pergunta.
    perguntas = {}
    for etapa in etapas_com_resposta:
        resultado = []
        for var in variaveis_etapa(etapa):
            observacoes = []
            for p in participantes:
                resposta = respostas_de[p.id].get(etapa)
                if not resposta:
                    continue
                payload = payload_de[resposta.id]
                exibida = var["visivel"](payload, anteriores_de[(p.id, etapa)]) if var["visivel"] else True
                observacoes.append({"grupo_id": p.grupo_id, "grupo": p.grupo.nome, "participante": p.codigo,
                                    "exibida": exibida, "valor": _normalizar(var, var["extrair"](payload))})
            por_coluna = {c["chave"]: _resumir_coluna(var, [o for o in observacoes if o["grupo_id"] in c["grupo_ids"]])
                          for c in colunas}
            diferenca = None
            if var["tipo"] in ("categorica", "multipla") and len(colunas) > 2:
                comparaveis = [por_coluna[c["chave"]] for c in colunas[1:] if por_coluna[c["chave"]]["n_preenchida"] >= 3]
                if len(comparaveis) >= 2 and por_coluna["todos"]["ordem"]:
                    def pct(resumo, valor):
                        return (resumo["opcoes"].get(valor) or {}).get("pct") or 0
                    diferenca = max(
                        max(pct(r, v) for r in comparaveis) - min(pct(r, v) for r in comparaveis)
                        for v in por_coluna["todos"]["ordem"]
                    )
            resultado.append({"id": var["id"], "rotulo": var["rotulo"], "secao": var["secao"], "tipo": var["tipo"],
                              "opcoes": dict(var["opcoes"]), "colunas": por_coluna, "diferenca": diferenca,
                              "condicional": bool(var["visivel"])})
        perguntas[etapa] = resultado

    destaques = {"baixa_concordancia": [], "diferencas": [], "baixo_preenchimento": []}
    for etapa, lista in perguntas.items():
        for pergunta in lista:
            todos = pergunta["colunas"]["todos"]
            base = {"etapa": etapa, "etapa_rotulo": ETAPA_ROTULOS[etapa], "id": pergunta["id"], "rotulo": pergunta["rotulo"]}
            if todos["concordancia"] is not None and todos["n_preenchida"] >= 3 and todos["concordancia"] < 0.7:
                destaques["baixa_concordancia"].append({**base, "valor": todos["concordancia"], "n": todos["n_preenchida"]})
            if pergunta["diferenca"] is not None and pergunta["diferenca"] >= 0.3:
                destaques["diferencas"].append({**base, "valor": pergunta["diferenca"]})
            if (todos["pct_preenchida"] is not None and todos["n_exibida"] >= 3 and todos["pct_preenchida"] < 0.5
                    and pergunta["id"] != "_dia_doenca"):
                destaques["baixo_preenchimento"].append({**base, "valor": todos["pct_preenchida"], "n": todos["n_exibida"]})
    destaques["baixa_concordancia"].sort(key=lambda d: d["valor"])
    destaques["diferencas"].sort(key=lambda d: -d["valor"])
    destaques["baixo_preenchimento"].sort(key=lambda d: d["valor"])
    for chave in destaques:
        destaques[chave] = destaques[chave][:12]

    # Coerência entre a ficha SINAN e o T0 quanto ao início dos sintomas.
    ambos = diverge = 0
    for p in participantes:
        respostas = respostas_de[p.id]
        if "sinan" in respostas and "t0" in respostas:
            sinan = _parse_data(carregar_respostas(respostas["sinan"]).get("data_inicio_sintomas"))
            t0 = _parse_data(carregar_respostas(respostas["t0"]).get("data_inicio_sintomas"))
            if sinan and t0:
                ambos += 1
                diverge += sinan != t0

    total_respostas = sum(len(r) for r in respostas_de.values())
    concluidos = sum(calendario_participante(p)["concluido"] for p in participantes)
    return {
        "vazio": False,
        "grupos": grupos,
        "colunas": colunas,
        "kpis": {"grupos": len(grupos), "participantes": len(participantes), "respostas": total_respostas,
                 "concluidos": concluidos, "pct_concluidos": concluidos / len(participantes) if participantes else None},
        "funil": funil,
        "perfis": perfis,
        "experiencias": experiencias,
        "etapas_presentes": etapas_presentes,
        "etapas_com_resposta": etapas_com_resposta,
        "resumo_etapas": resumo_etapas,
        "erros_campos": erros_campos,
        "perguntas": perguntas,
        "destaques": destaques,
        "comentarios": comentarios,
        "divergencia_inicio": {"ambos": ambos, "diverge": diverge},
    }


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------

def _linhas_participantes(grupos):
    for grupo in _grupos_ordenados(grupos):
        for participante in grupo.participantes:
            yield grupo, participante, respostas_por_etapa(participante)


def exportar_csv_longo(grupos) -> str:
    """Uma linha por pergunta respondida: pronto para tabela dinâmica ou R."""
    campos = ["grupo_id", "grupo", "participante", "perfil", "experiencia_sinan", "etapa", "enviado_em",
              "duracao_min", "facilidade", "tentativas_com_erro", "secao", "variavel", "pergunta", "tipo",
              "exibida", "valor"]
    saida = io.StringIO(newline="")
    escritor = safe_csv_dict_writer(saida, fieldnames=campos)
    escritor.writeheader()
    variaveis = {}
    for grupo, participante, respostas in _linhas_participantes(grupos):
        for etapa in ETAPAS:
            resposta = respostas.get(etapa)
            if not resposta:
                continue
            if etapa not in variaveis:
                variaveis[etapa] = variaveis_etapa(etapa)
            payload = carregar_respostas(resposta)
            anteriores = _payloads_anteriores(respostas, etapa)
            base = {
                "grupo_id": grupo.id, "grupo": grupo.nome, "participante": participante.codigo,
                "perfil": participante.perfil, "experiencia_sinan": participante.experiencia_sinan,
                "etapa": ETAPA_ROTULOS[etapa], "enviado_em": formatar_data_hora(resposta.enviado_em),
                "duracao_min": formatar_numero(resposta.duracao_segundos / 60, 1) if resposta.duracao_segundos is not None else "",
                "facilidade": carregar_avaliacao(resposta).get("facilidade", ""),
                "tentativas_com_erro": len(carregar_erros(resposta)),
            }
            for var in variaveis[etapa]:
                exibida = var["visivel"](payload, anteriores) if var["visivel"] else True
                valor = _normalizar(var, var["extrair"](payload))
                escritor.writerow({**base, "secao": var["secao"], "variavel": var["id"], "pergunta": var["rotulo"],
                                   "tipo": var["tipo"], "exibida": "sim" if exibida else "não",
                                   "valor": MARCADOR_OCULTO if var["tipo"] == "oculto" and _preenchido(valor)
                                   else valor_legivel(var, valor)})
    return saida.getvalue()


def exportar_csv_largo(grupos) -> str:
    """Uma linha por participante, com todas as etapas lado a lado."""
    variaveis = {etapa: variaveis_etapa(etapa) for etapa in ETAPAS}
    campos = ["grupo_id", "grupo", "participante", "perfil", "experiencia_sinan", "inscrito_em"]
    for etapa in ETAPAS:
        campos += [f"{etapa}__enviado_em", f"{etapa}__duracao_min", f"{etapa}__facilidade", f"{etapa}__tentativas_com_erro"]
        campos += [f"{etapa}__{var['id']}" for var in variaveis[etapa]]
    saida = io.StringIO(newline="")
    escritor = safe_csv_dict_writer(saida, fieldnames=campos)
    escritor.writeheader()
    for grupo, participante, respostas in _linhas_participantes(grupos):
        linha = {"grupo_id": grupo.id, "grupo": grupo.nome, "participante": participante.codigo,
                 "perfil": participante.perfil, "experiencia_sinan": participante.experiencia_sinan,
                 "inscrito_em": formatar_data_hora(participante.created_at)}
        for etapa in ETAPAS:
            resposta = respostas.get(etapa)
            if not resposta:
                continue
            payload = carregar_respostas(resposta)
            linha[f"{etapa}__enviado_em"] = formatar_data_hora(resposta.enviado_em)
            linha[f"{etapa}__duracao_min"] = (formatar_numero(resposta.duracao_segundos / 60, 1)
                                              if resposta.duracao_segundos is not None else "")
            linha[f"{etapa}__facilidade"] = carregar_avaliacao(resposta).get("facilidade", "")
            linha[f"{etapa}__tentativas_com_erro"] = len(carregar_erros(resposta))
            for var in variaveis[etapa]:
                valor = _normalizar(var, var["extrair"](payload))
                linha[f"{etapa}__{var['id']}"] = (MARCADOR_OCULTO if var["tipo"] == "oculto" and _preenchido(valor)
                                                  else valor_legivel(var, valor))
        escritor.writerow(linha)
    return saida.getvalue()
