"""Regras da área de limpeza urbana: quem acessa, onde a foto foi tirada e a auditoria.

Papéis (adicionais, concedidos por um administrador, com período opcional):

* ``colaborador`` — comunica lixo, entulho, móveis e galhos e acompanha as suas;
* ``equipe`` — equipe contratada: vê o mapa e comprova a limpeza com foto no local;
* ``fiscal`` — fiscalização do contrato: vê o mapa, recusa comprovação, descarta
  comunicação indevida e exporta o relatório.

Administrador tem tudo. Com a chave ``limpeza_comunicacao_aberta`` ligada,
qualquer conta pode comunicar, sem precisar de papel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO

from flask import g, has_request_context

from time_utils import now_in_brazil, utcnow

PAPEIS = {
    "colaborador": ("Colaborador", "Comunica pontos que precisam de limpeza e acompanha as próprias comunicações."),
    "equipe": ("Equipe de limpeza", "Vê o mapa das comunicações e comprova a limpeza com foto tirada no local."),
    "fiscal": ("Fiscalização", "Vê o mapa completo, recusa comprovações, descarta comunicações e exporta o relatório."),
}

CATEGORIAS = {
    "lixo": "Lixo acumulado",
    "entulho": "Entulho",
    "moveis": "Móveis e objetos grandes",
    "galhos": "Galhos e poda",
    "canteiro": "Canteiro ou praça sem limpeza",
    "outro": "Outro",
}

STATUS = {"aberta": "Aguardando limpeza", "concluida": "Limpeza comprovada", "descartada": "Descartada"}

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


def papeis_de(user) -> frozenset[str]:
    """Papéis vigentes hoje; memorizado por requisição (navegação + rota)."""
    if not getattr(user, "is_authenticated", False) or not getattr(user, "id", None):
        return frozenset()
    if eh_admin(user):
        return frozenset(PAPEIS)
    cache = g.setdefault("_limpeza_papeis", {}) if has_request_context() else {}
    if user.id not in cache:
        from models.limpeza import LimpezaAcesso
        try:
            linhas = LimpezaAcesso.query.filter_by(user_id=user.id, revogado_em=None).all()
            cache[user.id] = frozenset(a.papel for a in linhas if acesso_vigente(a))
        except Exception:  # tabela ausente antes da migration: área some, site continua
            from extensions import db
            db.session.rollback()
            cache[user.id] = frozenset()
    return cache[user.id]


def comunicacao_aberta() -> bool:
    from models.base import SiteFlag
    return bool(SiteFlag.get(FLAG_COMUNICACAO_ABERTA, default=False))


def pode_comunicar(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(papeis_de(user)) or comunicacao_aberta()


def pode_ver_mapa(user) -> bool:
    return bool(papeis_de(user) & {"equipe", "fiscal"})


def pode_comprovar(user) -> bool:
    return "equipe" in papeis_de(user)


def pode_fiscalizar(user) -> bool:
    return "fiscal" in papeis_de(user)


def nome_da_conta(user) -> str:
    return str(getattr(user, "name", "") or getattr(user, "email", "") or "").strip()[:160]


def _limpar_cache():
    if has_request_context():
        g.pop("_limpeza_papeis", None)
        g.pop("user_experience", None)


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


def conceder(user, papeis, inicio: date | None, fim: date | None, por: str):
    """Concede (ou reabre com o novo período) cada papel. Devolve os vínculos gravados."""
    from extensions import db
    from models.limpeza import LimpezaAcesso
    papeis = [p for p in papeis if p in PAPEIS]
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
                     f"{', '.join(PAPEIS[p][0] for p in papeis)} para a conta #{user.id}"
                     f"{_periodo_texto(inicio, fim)} por {por}")
    _limpar_cache()
    return gravados


def revogar(acesso_id: int, por: str):
    from extensions import db
    from models.limpeza import LimpezaAcesso
    acesso = db.session.get(LimpezaAcesso, acesso_id)
    if acesso is None or acesso.revogado_em is not None:
        return None
    acesso.revogado_em, acesso.revogado_por = utcnow(), por
    registrar_evento("acesso_revogado", None, None,
                     f"{PAPEIS.get(acesso.papel, (acesso.papel,))[0]} da conta #{acesso.user_id} por {por}")
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


def ler_foto(arquivo) -> tuple[bytes, DadosFoto]:
    if arquivo is None:
        raise LimpezaErro("Tire ou escolha uma foto.")
    data = arquivo.read()
    if not data:
        raise LimpezaErro("A foto chegou vazia. Tire a foto de novo.")
    if len(data) > FOTO_MAX_BYTES:
        raise LimpezaErro("A foto é muito grande. Use uma imagem de até 15 MB.")
    return data, ler_exif(data)


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


def consultar(status=None, categoria=None, desde: date | None = None, ate: date | None = None, autor_id=None):
    from datetime import time, timezone

    from sqlalchemy.orm import selectinload

    from models.limpeza import LimpezaSolicitacao
    from time_utils import BR_TZ

    q = LimpezaSolicitacao.query.options(selectinload(LimpezaSolicitacao.comprovacoes))
    if status in STATUS:
        q = q.filter(LimpezaSolicitacao.status == status)
    if categoria in CATEGORIAS:
        q = q.filter(LimpezaSolicitacao.categoria == categoria)
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
        "id": s.id, "status": s.status, "status_rotulo": STATUS.get(s.status, s.status),
        "categoria": s.categoria, "categoria_rotulo": CATEGORIAS.get(s.categoria, s.categoria),
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
