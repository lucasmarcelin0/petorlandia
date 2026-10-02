"""Import a private, redacted Earth snapshot into the existing import table."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    parser = argparse.ArgumentParser()
    origin=parser.add_mutually_exclusive_group(required=True)
    origin.add_argument('--file')
    origin.add_argument('--stdin', action='store_true')
    parser.add_argument('--responsavel', required=True)
    args = parser.parse_args()
    if not args.responsavel.strip() or len(args.responsavel)>160:
        parser.error('Informe um responsável válido (até 160 caracteres).')
    from services.entomologia_atlas import read_earth, TIPO_ATLAS
    raw = sys.stdin.buffer.read(15*1024*1024+1) if args.stdin else Path(args.file).read_bytes()
    data = read_earth(raw, Path(args.file).name if args.file else 'Cópia de 2026.kml')
    from app_factory import create_app
    from extensions import db
    from models.entomologia import EntomologiaImportacao as E
    from time_utils import utcnow
    with create_app().app_context():
        existing = E.query.filter_by(tipo=TIPO_ATLAS, sha256=data['source']['sha256'], status='ATIVA').order_by(E.id.desc()).first()
        if existing and json.loads(existing.dados_json).get('schema_version',1)>=data.get('schema_version',1):
            print(f'Atlas já importado: #{existing.id}. Nenhuma alteração.')
            return
        entry = E(tipo=TIPO_ATLAS, status='ATIVA', nome_arquivo=data['source']['file'], titulo=data['source']['title'],
                  sha256=data['source']['sha256'], linhas=len(data['features']), responsavel=args.responsavel,
                  ator='Publicação autorizada do atlas', confirmado_em=utcnow(),
                  dados_json=json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False),
                  resumo_json=json.dumps({'camadas': data['source']['counts']}, ensure_ascii=False))
        db.session.add(entry)
        db.session.flush()
        from models.sfa import SfaAuditoria
        db.session.add(SfaAuditoria(nivel='INFO',categoria='ENTOMOLOGIA',funcao='confirmar_envio',
            mensagem=f'Atlas #{entry.id} importado por publicação autorizada',
            detalhes_json=json.dumps({'envio':entry.id,'tipo':TIPO_ATLAS,'sha256':entry.sha256,
                'linhas':entry.linhas,'responsavel_confirmacao':args.responsavel,'ator_autenticado':entry.ator},ensure_ascii=False)))
        db.session.commit()
        print(json.dumps({'import_id': entry.id, 'elements': entry.linhas, 'layers': data['source']['counts']}, ensure_ascii=False))

if __name__ == '__main__':
    main()
