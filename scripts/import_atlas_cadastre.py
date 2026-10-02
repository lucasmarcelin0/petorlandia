"""Import a redacted, compressed cadastral reference; never touches shared DWGs."""
import argparse,json,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--file');parser.add_argument('--stdin',action='store_true');parser.add_argument('--responsavel',required=True);args=parser.parse_args()
    if bool(args.file)==args.stdin:parser.error('Use --file ou --stdin.')
    if not args.responsavel.strip() or len(args.responsavel)>160:parser.error('Responsável inválido.')
    raw=sys.stdin.buffer.read(10*1024*1024+1) if args.stdin else Path(args.file).read_bytes()
    if len(raw)>10*1024*1024:parser.error('Referência maior que 10 MB comprimidos.')
    from services.entomologia_cadastre import decode,TIPO
    encoded=raw.decode('utf-8-sig');data=decode(encoded)
    if data.get('schema_version')!=1 or not data.get('source',{}).get('read_only'):parser.error('Fonte cadastral inválida.')
    from services.entomologia_atlas_editor import geometry
    from services.entomologia_folders import ensure
    total=0
    for layer in data['layers']:
        if not layer['id'].startswith('cadastre-') or layer.get('clinical') or layer['origin']['type'] not in ('cadastre','street_catalog'):parser.error('Camada cadastral inválida.')
        ensure(layer)
        if len(set(f['id'] for f in layer['features']))!=len(layer['features']):parser.error('Números com identificadores repetidos.')
        for f in layer['features']:
            if geometry(f.get('geometry')) is not None:parser.error('A fonte não pode declarar posições geográficas não conferidas.')
        total+=len(layer['features'])
    from app_factory import create_app
    from extensions import db
    from models.entomologia import EntomologiaImportacao as E
    from models.sfa import SfaAuditoria
    from time_utils import utcnow
    digest=hashlib.sha256(raw).hexdigest()
    with create_app().app_context():
        old=E.query.filter_by(tipo=TIPO,status='ATIVA',sha256=digest).first()
        if old:print('Referência já importada: #'+str(old.id));return
        entry=E(tipo=TIPO,status='ATIVA',nome_arquivo='Referência QUADRAS e logradouros',titulo=data['source']['title'],sha256=digest,
            linhas=total,responsavel=args.responsavel,ator='Publicação autorizada do atlas',confirmado_em=utcnow(),dados_json=encoded,
            resumo_json=json.dumps(data['source'],ensure_ascii=False))
        db.session.add(entry);db.session.flush()
        db.session.add(SfaAuditoria(nivel='INFO',categoria='ENTOMOLOGIA',funcao='importar_cadastro',mensagem='Referência cadastral importada por publicação autorizada',
            detalhes_json=json.dumps({'envio':entry.id,'sha256':digest,'linhas':total,'responsavel':args.responsavel},ensure_ascii=False)))
        db.session.commit();print(json.dumps({'import_id':entry.id,'records':total,'source':data['source']},ensure_ascii=False))
if __name__=='__main__':main()
