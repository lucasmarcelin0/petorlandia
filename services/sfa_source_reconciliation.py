"""Atualizações da fonte SINAN sem apagar revisões manuais ou respostas."""
import json
from extensions import db
from models.sfa import SfaPaciente, SfaAuditoria


def grupo_resultado(resultado):
    from services.sfa_service import normalizar_nome_chave
    texto = normalizar_nome_chave(resultado)
    if not texto or any(t in texto for t in ('inconclus', 'indetermin', 'aguard', 'pendente')):
        return 'PENDENTE_REVISAO'
    if 'negativ' in texto or 'nao reagente' in texto or 'nao positiv' in texto:
        return 'B'
    if 'positiv' in texto or 'reagente' in texto:
        return 'A'
    return 'PENDENTE_REVISAO'


def reconciliar(log, novos):
    """Atualiza o retrato da fonte. Campos locais divergentes ficam preservados."""
    alteracoes = {key: {'antes': getattr(log, key), 'depois': value}
                  for key, value in novos.items() if (getattr(log, key) or '') != (value or '')}
    if not alteracoes:
        return False
    paciente = SfaPaciente.query.filter_by(id_estudo=log.id_estudo_vinculado).first()
    preservados = []
    if paciente:
        for key in ('nome', 'telefone', 'bairro', 'grupo'):
            if key not in alteracoes:
                continue
            atual = getattr(paciente, key)
            if not atual or atual == alteracoes[key]['antes']:
                setattr(paciente, key, novos[key])
            else:
                preservados.append(key)
    for key, value in novos.items():
        setattr(log, key, value)
    db.session.add(SfaAuditoria(nivel='INFO', categoria='SINAN_ATUALIZADO', funcao='sincronizar_sinan',
                               id_estudo=log.id_estudo_vinculado,
                               mensagem='Fonte atualizada; respostas e revisões locais preservadas.',
                               detalhes_json=json.dumps({'alteracoes': alteracoes, 'campos_locais_preservados': preservados}, ensure_ascii=False)))
    return True
