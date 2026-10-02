"""Import checked public IBGE references into the protected, audited atlas."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--file');parser.add_argument('--stdin',action='store_true');parser.add_argument('--responsavel',required=True);parser.add_argument('--dry-run',action='store_true');args=parser.parse_args()
    if bool(args.file)==args.stdin:parser.error('Use --file ou --stdin.')
    if not args.responsavel.strip() or len(args.responsavel)>160:parser.error('Responsável inválido.')
    raw=sys.stdin.buffer.read(10*1024*1024+1) if args.stdin else Path(args.file).read_bytes()
    if len(raw)>10*1024*1024:parser.error('Base maior que 10 MB comprimidos.')
    from services.entomologia_cadastre import decode
    from services.entomologia_cnefe import validate,TIPO
    encoded=raw.decode('utf-8-sig');data=decode(encoded);validate(data)
    from services.entomologia_folders import ensure
    for layer in data['layers']:ensure(layer)
    if args.dry_run:print(json.dumps(data['source'],ensure_ascii=False));return
    from app_factory import create_app
    from extensions import db
    from models.entomologia import EntomologiaImportacao as E
    from models.sfa import SfaAuditoria
    from time_utils import utcnow
    digest=hashlib.sha256(raw).hexdigest()
    with create_app().app_context():
        old=E.query.filter_by(tipo=TIPO,status='ATIVA',sha256=digest).first()
        if old:print('Referência já importada: #'+str(old.id));return
        entry=E(tipo=TIPO,status='ATIVA',nome_arquivo='CNEFE público · Orlândia · 2022',titulo=data['source']['title'],sha256=digest,linhas=data['source']['records'],responsavel=args.responsavel,ator='Publicação autorizada do atlas',confirmado_em=utcnow(),dados_json=encoded,resumo_json=json.dumps(data['source'],ensure_ascii=False))
        db.session.add(entry);db.session.flush()
        db.session.add(SfaAuditoria(nivel='INFO',categoria='ENTOMOLOGIA',funcao='importar_enderecos_ibge',mensagem='Endereços públicos CNEFE importados por publicação autorizada',detalhes_json=json.dumps({'envio':entry.id,'sha256':digest,'linhas':entry.linhas,'responsavel':args.responsavel},ensure_ascii=False)))
        db.session.commit();print(json.dumps({'import_id':entry.id,'source':data['source']},ensure_ascii=False))
if __name__=='__main__':main()
