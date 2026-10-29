"""Validação da camada privada, sem CPF/CNPJ no resultado."""
import json
import math
from datetime import date

def validar(raw):
    if len(raw) > 5_000_000: raise ValueError('Arquivo SIVISA maior que 5 MB.')
    try: data = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeError) as exc: raise ValueError('Arquivo SIVISA inválido.') from exc
    if not isinstance(data, dict) or not isinstance(data.get('registros'), list) or len(data['registros']) > 10000:
        raise ValueError('Lista de inspeções inválida.')
    try:
        inicio, fim = date.fromisoformat(data['inicio']), date.fromisoformat(data['fim'])
        if inicio > fim: raise ValueError()
        registros = []
        for r in data['registros']:
            if not isinstance(r, dict): raise ValueError()
            dia = date.fromisoformat(r['data'])
            validade = date.fromisoformat(r['validade']) if r.get('validade') else None
            if not inicio <= dia <= fim: raise ValueError()
            nome, endereco = r.get('nome',''), r.get('endereco','')
            if not isinstance(nome,str) or len(nome)>160 or not isinstance(endereco,str) or len(endereco)>240: raise ValueError()
            coords = r.get('coordenadas')
            if coords is not None:
                if not isinstance(coords,list) or len(coords)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in coords): raise ValueError()
                if not (-48.2 < coords[0] < -47.6 and -21.2 < coords[1] < -20.5): raise ValueError()
            situacao = ('Sem validade identificada' if not validade else 'Prazo não vencido na data da extração' if validade >= fim else 'Prazo vencido na data da extração')
            registros.append({'nome':nome, 'endereco':endereco, 'data':dia.isoformat(), 'validade':validade.isoformat() if validade else '', 'situacao':situacao, 'coordenadas':coords})
        return {'inicio':inicio.isoformat(),'fim':fim.isoformat(),'registros':registros}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Registros ou datas SIVISA inválidos.') from exc
