"""Redacted municipal drawing references stored privately, independently of edits."""
from functools import lru_cache
import json
TIPO='atlas_cadastre'
@lru_cache(maxsize=1)
def decode(encoded):
    data=json.loads(encoded)
    if data.get('encoding')=='gzip-base64':
        import gzip,base64,hashlib
        raw=gzip.decompress(base64.b64decode(data['payload'],validate=True))
        if hashlib.sha256(raw).hexdigest()!=data['sha256']:raise ValueError('Referência cadastral corrompida.')
        return json.loads(raw)
    return data
def active():
    from models.entomologia import EntomologiaImportacao as E
    from services.entomologia_service import consultar_sem_interromper
    row=consultar_sem_interromper(lambda:E.query.filter_by(tipo=TIPO,status='ATIVA').with_entities(E.id,E.sha256).order_by(E.id.desc()).first())
    if not row:return {'layers':[],'drawings':{},'source':{}}
    from flask import current_app
    return imported(row.id,row.sha256,str(current_app.config.get('SQLALCHEMY_DATABASE_URI','')))

@lru_cache(maxsize=1)
def imported(row_id,digest,database):
    from extensions import db
    from models.entomologia import EntomologiaImportacao as E
    row=db.session.get(E,row_id)
    if not row or row.sha256!=digest:raise LookupError('Referência cadastral não encontrada.')
    return decode(row.dados_json)
def source_layers():
    from copy import deepcopy
    return {layer['id']:deepcopy(layer) for layer in active()['layers']}
def drawing(code):return active()['drawings'].get(code.upper())
