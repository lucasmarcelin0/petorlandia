"""Saídas do atlas calculadas uma vez por versão dos dados e guardadas no banco.

Antes, cada processo do site remontava o índice de busca do zero: a cada deploy,
a cada reinício diário do Heroku e a cada reciclagem do worker. A montagem lê e
interpreta todas as camadas (mais de 30 s num dyno Basic) e o celular ficava em
"Preparando a busca…" até o roteador desistir (H12).

Agora o índice (variantes pública e clínica) e as geometrias de ruas e áreas
ficam gravados em ``entomologia_atlas_artefato``, por versão. O site só lê
bytes prontos (já em gzip). Quem monta:

* o scheduler, que a cada poucos minutos confere se a versão mudou;
* uma thread do próprio site, disparada pela própria edição ou importação.
  Enquanto ela trabalha, nenhuma requisição espera: quem tem acesso clínico
  (já vê todas as camadas) recebe a versão anterior; os demais recebem
  "preparando" e o navegador tenta de novo. Assim uma camada que acabou de
  virar clínica nunca aparece para quem não deve vê-la.

A versão combina a assinatura das importações ativas, os arquivos JSON
versionados em ``services/data/entomologia`` e o formato do índice. Qualquer
mudança num deles gera uma versão nova; nada velho é servido como atual.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import threading
import time
import zlib
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / 'data' / 'entomologia'
TIPO_INDICE = 'indice'
VARIANTES = {True: 'clinico', False: 'publico'}
VARIANTE_LUGARES = 'todos'
BALDES = 64                 # geometrias divididas em pedaços: cada toque lê só um pedaço pequeno
MANTER = 2                  # versões guardadas (a atual e a anterior, que serve enquanto a nova é montada)
CACHE_BUSCA_S = 600.0       # índice já interpretado, para a busca de reserva, some da memória após 10 min sem uso

_lock = threading.Lock()
_build_lock = threading.Lock()
_bytes = {}                 # (variante, tipo) -> (versao, corpo_gz, etag, corpo_br): só a versão mais recente lida
_parsed = {}                # variante -> (etag, layers, entries, último uso)
_building = [False]
_falhou_em = [0.0]          # última montagem que deu erro: por um tempo, o caminho direto responde
ESPERA_APOS_FALHA_S = 600.0
PREPARANDO = 'preparando'   # versão atual ainda sendo montada e nada que possa ser servido no lugar


def tipo_lugares(balde):
    return 'lugares-%02d' % balde


def balde(layer_id, feature_id):
    digest = hashlib.sha1((str(layer_id) + '\x1f' + str(feature_id)).encode('utf-8')).digest()
    return int.from_bytes(digest[:4], 'big') % BALDES


@lru_cache(maxsize=1)
def fingerprint_estatico():
    """Conteúdo dos arquivos de dados que entram nas camadas (calculado uma vez por processo)."""
    digest = hashlib.sha256()
    for path in sorted(DATA_DIR.rglob('*.json')):
        digest.update(str(path.relative_to(DATA_DIR)).encode('utf-8'))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def versao(signature):
    from services.entomologia_atlas_search import INDEX_FORMAT
    texto = INDEX_FORMAT + '|' + repr(signature) + '|' + fingerprint_estatico()
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()[:32]


def ativo():
    """Ligado no Heroku (``DYNO``) ou com ``ATLAS_ARTEFATOS``; testes e máquina local seguem o caminho direto."""
    import os
    from flask import current_app
    padrao = bool(os.getenv('DYNO')) or os.getenv('ATLAS_ARTEFATOS') == '1'
    return bool(current_app.config.get('ATLAS_ARTEFATOS', padrao))


def versao_atual():
    """Versão dos dados agora; ``None`` quando o banco não responde ou os artefatos estão desligados."""
    from services import entomologia_atlas_search as busca
    if not ativo():
        return None
    signature = busca._signature()
    return None if signature is None else versao(signature)


def _gz(texto):
    return gzip.compress(texto.encode('utf-8'), compresslevel=6, mtime=0)


def _consultar(consulta):
    from services.entomologia_service import consultar_sem_interromper
    return consultar_sem_interromper(consulta)


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------

def _ler(v, variante, tipo, guardar=True):
    """(corpo_gz, etag, corpo_br ou None) da versão ``v``; ``None`` se ainda não existe."""
    with _lock:
        hit = _bytes.get((variante, tipo))
    if hit and hit[0] == v:
        return hit[1:]
    from models.entomologia import EntomologiaAtlasArtefato as A
    row = _consultar(lambda: A.query.filter_by(versao=v, variante=variante, tipo=tipo)
                     .with_entities(A.corpo, A.etag, A.corpo_br).first())
    if row is None:
        return None
    item = (bytes(row.corpo), row.etag, bytes(row.corpo_br) if row.corpo_br else None)
    if guardar:
        with _lock:
            _bytes[(variante, tipo)] = (v,) + item
    return item


def _versoes_guardadas():
    """Versões gravadas, da mais nova para a mais antiga."""
    from models.entomologia import EntomologiaAtlasArtefato as A
    from extensions import db
    from services.entomologia_atlas_search import INDEX_FORMAT
    # Só versões no formato que este código entende: depois de um deploy que muda o índice, a anterior não serve.
    rows = _consultar(lambda: A.query.with_entities(A.versao, db.func.max(A.id).label('ultimo'))
                      .filter(A.tipo == TIPO_INDICE, A.formato == INDEX_FORMAT).group_by(A.versao)
                      .order_by(db.desc('ultimo')).all()) or []
    return [row.versao for row in rows]


def _pode_preparar():
    return time.monotonic() - _falhou_em[0] >= ESPERA_APOS_FALHA_S if _falhou_em[0] else True


def _preparar(app):
    from flask import current_app
    atualizar_em_segundo_plano(app if app is not None else current_app._get_current_object())


def indice(clinical_allowed, app=None):
    """(corpo_gz, etag, corpo_br) do índice para o navegador, sem montar nada na requisição.

    * versão atual pronta: ela;
    * senão, para quem tem acesso clínico, a anterior: essa pessoa já vê todas as camadas, então nada
      fica exposto se uma camada mudou de visibilidade. Para os demais, ``PREPARANDO`` (o navegador
      mostra as quadras e tenta de novo); a montagem começa em segundo plano nos dois casos;
    * ``None``: artefatos desligados, banco fora ou última montagem com erro: o caminho direto responde.
    """
    variante = VARIANTES[bool(clinical_allowed)]
    v = versao_atual()
    if v is None:
        return None
    item = _ler(v, variante, TIPO_INDICE)
    if item:
        return item
    if not _pode_preparar():
        return None
    _preparar(app)
    if clinical_allowed:
        for antiga in _versoes_guardadas():
            if antiga != v:
                item = _ler(antiga, variante, TIPO_INDICE, guardar=False)
                if item:
                    return item
    return PREPARANDO


def lugar(layer_id, feature_id, clinical_allowed):
    """Geometria pronta de uma rua/área: dict do ``place()``, ``False`` se negado, ``PREPARANDO``, ou ``None``
    (sem artefato pronto para ela: o caminho completo responde)."""
    v = versao_atual()
    if v is None:
        return None
    tipo = tipo_lugares(balde(layer_id, feature_id))
    chave = str(layer_id) + '\x1f' + str(feature_id)
    atual = _ler(v, VARIANTE_LUGARES, tipo, guardar=False)
    if atual:
        return _do_pedaco(atual, chave, clinical_allowed)
    if not _pode_preparar():
        return None
    _preparar(None)
    if clinical_allowed:                      # mesma regra do índice: a anterior só para quem vê tudo
        for antiga in _versoes_guardadas():
            if antiga == v:
                continue
            item = _ler(antiga, VARIANTE_LUGARES, tipo, guardar=False)
            if item:
                achado = _do_pedaco(item, chave, True)
                if achado is not None:
                    return achado
    return PREPARANDO


def _do_pedaco(item, chave, clinical_allowed):
    achado = json.loads(gzip.decompress(item[0])).get(chave)
    if achado is None:
        return None
    if achado['clinical'] and not clinical_allowed:
        return False
    return achado['item']


def busca_compacta(query, clinical_allowed, app=None):
    """Busca de reserva sobre o índice pronto: ``{'layers', 'entries'}`` como o navegador usa, ou ``None``."""
    from services import entomologia_atlas_search as busca
    variante = VARIANTES[bool(clinical_allowed)]
    item = indice(clinical_allowed, app)
    if item is None:
        return None
    if item == PREPARANDO:
        return {'layers': [], 'entries': [], 'preparando': True}
    corpo, etag = item[0], item[1]
    with _lock:
        hit = _parsed.get(variante)
    if hit and hit[0] == etag:
        layers, entries = hit[1], hit[2]
    else:
        data = json.loads(gzip.decompress(corpo))
        layers, entries = data['layers'], data['entries']
    with _lock:
        _parsed[variante] = (etag, layers, entries, time.monotonic())
    _agendar_limpeza()
    return {'layers': layers, 'entries': busca.search_compact(entries, query)}


_timer = [None]


def _agendar_limpeza():
    with _lock:
        if _timer[0] is not None:
            return
        timer = threading.Timer(CACHE_BUSCA_S, _limpar_busca)
        timer.daemon = True
        _timer[0] = timer
    timer.start()


def _limpar_busca():
    agora = time.monotonic()
    with _lock:
        _timer[0] = None
        for variante, hit in list(_parsed.items()):
            if agora - hit[3] >= CACHE_BUSCA_S:
                del _parsed[variante]
        restam = bool(_parsed)
    if restam:
        _agendar_limpeza()


# --------------------------------------------------------------------------
# Montagem
# --------------------------------------------------------------------------

def existe(v):
    from models.entomologia import EntomologiaAtlasArtefato as A
    return bool(_consultar(lambda: A.query.filter_by(versao=v, variante=VARIANTES[False], tipo=TIPO_INDICE)
                           .with_entities(A.id).first()))


def construir(liberar_memoria=True, brotli_qualidade=9):
    """Monta e grava a versão atual, se ainda não existir. Devolve a versão (``None`` sem banco).

    Uma montagem por vez por processo; entre processos (site e scheduler), quem
    gravar primeiro vence e o outro descarta a sua cópia.
    """
    from services import entomologia_atlas_search as busca
    if not ativo():
        return None
    signature = busca._signature()
    if signature is None:
        return None
    v = versao(signature)
    if existe(v):
        return v
    with _build_lock:
        if existe(v):
            return v
        snap = busca.snapshot()
        if snap.signature != signature:      # os dados mudaram no meio: a próxima rodada monta a versão nova
            return None
        linhas = []
        for clinico, variante in VARIANTES.items():
            corpo, _ = busca._build_payload(snap, clinico)
            linhas.append((variante, TIPO_INDICE, corpo))
        pedacos = [{} for _ in range(BALDES)]
        for (layer_id, feature_id), item in busca.places(snap).items():
            pedacos[balde(layer_id, feature_id)][layer_id + '\x1f' + feature_id] = item
        for numero, pedaco in enumerate(pedacos):
            corpo = json.dumps(pedaco, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            linhas.append((VARIANTE_LUGARES, tipo_lugares(numero), corpo))
        _gravar(v, linhas, brotli_qualidade)
        if liberar_memoria:
            # O site passa a servir o que foi gravado: não precisa manter as camadas inteiras na memória.
            busca.reset()
        return v


def _brotli(texto, qualidade):
    try:
        import brotli
    except ImportError:                     # sem a biblioteca, o gzip atende todos os navegadores
        return None
    return brotli.compress(texto.encode('utf-8'), quality=qualidade, lgwin=22)


def _gravar(v, linhas, brotli_qualidade=9):
    from sqlalchemy.exc import IntegrityError
    from services.entomologia_atlas_search import INDEX_FORMAT
    from extensions import db
    from models.entomologia import EntomologiaAtlasArtefato as A
    try:
        for variante, tipo, corpo in linhas:
            gz = _gz(corpo)
            etag = hashlib.sha256(v.encode() + b'|' + variante.encode() + b'|' + tipo.encode()).hexdigest()[:24]
            # Só o índice vai inteiro ao navegador; as geometrias são lidas aqui, pedaço por pedaço.
            br = _brotli(corpo, brotli_qualidade) if tipo == TIPO_INDICE else None
            db.session.add(A(versao=v, variante=variante, tipo=tipo, corpo=gz, corpo_br=br, etag=etag,
                             formato=INDEX_FORMAT, bytes_crus=len(corpo.encode('utf-8'))))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()               # outro processo gravou a mesma versão antes
        return
    except Exception:
        db.session.rollback()
        raise
    _apagar_antigas()


def _apagar_antigas():
    from extensions import db
    from models.entomologia import EntomologiaAtlasArtefato as A
    manter = _versoes_guardadas()[:MANTER]
    if not manter:
        return
    try:
        A.query.filter(~A.versao.in_(manter)).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()


def atualizar_em_segundo_plano(app):
    """Monta a versão atual numa thread, sem segurar a requisição. Devolve a thread (``None`` se já há uma)."""
    with _lock:
        if _building[0]:
            return None
        _building[0] = True

    def run():
        try:
            with app.app_context():
                construir()
            _falhou_em[0] = 0.0
        except Exception:
            _falhou_em[0] = time.monotonic()
            app.logger.warning('Não foi possível pré-calcular os artefatos do atlas.', exc_info=True)
        finally:
            with _lock:
                _building[0] = False

    thread = threading.Thread(target=run, name='atlas-artefatos', daemon=True)
    thread.start()
    return thread


def descomprimir(corpo_gz):
    return zlib.decompress(corpo_gz, 16 + zlib.MAX_WBITS)
