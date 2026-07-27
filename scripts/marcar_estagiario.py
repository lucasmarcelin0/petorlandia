"""Converte um profissional já cadastrado em estagiário sob supervisão.

Existe porque quem foi cadastrado antes da habilitação carrega um CRMV de
fachada (o formulário antigo exigia o campo). Este script remove esse número
e amarra a pessoa a um supervisor com CRMV real.

Uso:
    python scripts/marcar_estagiario.py --clinica 1 --nome "Laiane" --supervisor-nome "Lucas"
    python scripts/marcar_estagiario.py --clinica 1 --nome "Laiane" --supervisor-nome "Lucas" --confirmar

Sem --confirmar apenas mostra o que seria feito.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# create_app() direto: o CLI do flask quebra com este app factory.
from app_factory import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models import Clinica, Veterinario  # noqa: E402
from models.usuarios import HABILITACAO_ESTAGIARIO  # noqa: E402


def _vets_da_clinica(clinica):
    vistos = {}
    for vet in list(clinica.veterinarios or []) + list(clinica.veterinarios_associados or []):
        vistos[vet.id] = vet
    return list(vistos.values())


def _achar(vets, termo):
    termo = termo.lower().strip()
    achados = [
        v for v in vets
        if termo in ((getattr(v.user, 'name', None) or '').lower())
    ]
    return achados


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clinica', type=int, required=True)
    parser.add_argument('--nome', required=True, help='Trecho do nome do estagiário')
    parser.add_argument('--supervisor-nome', required=True, help='Trecho do nome do supervisor')
    parser.add_argument('--confirmar', action='store_true', help='Aplica de fato')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        clinica = db.session.get(Clinica, args.clinica)
        if not clinica:
            sys.exit(f'Clínica {args.clinica} não encontrada.')

        vets = _vets_da_clinica(clinica)
        alvos = _achar(vets, args.nome)
        supervisores = [v for v in _achar(vets, args.supervisor_nome) if v.pode_assinar]

        if len(alvos) != 1:
            sys.exit(
                f'Esperava 1 profissional com "{args.nome}", achei {len(alvos)}: '
                + ', '.join(v.user.name for v in alvos)
            )
        if len(supervisores) != 1:
            sys.exit(
                f'Esperava 1 supervisor com CRMV e nome "{args.supervisor_nome}", '
                f'achei {len(supervisores)}: '
                + ', '.join(f'{v.user.name} (CRMV {v.crmv_exibicao})' for v in supervisores)
            )

        alvo, supervisor = alvos[0], supervisores[0]
        if alvo.id == supervisor.id:
            sys.exit('O estagiário não pode ser o próprio supervisor.')

        print(f'Clínica: {clinica.nome}')
        print(f'  Antes:  {alvo.user.name} | habilitacao={alvo.habilitacao} | crmv={alvo.crmv!r}')
        print(f'  Depois: {alvo.user.name} | habilitacao={HABILITACAO_ESTAGIARIO} | crmv=None')
        print(f'  Supervisor: {supervisor.user.name} (CRMV {supervisor.crmv_exibicao})')

        if not args.confirmar:
            print('\n[simulação] rode de novo com --confirmar para aplicar.')
            return

        alvo.habilitacao = HABILITACAO_ESTAGIARIO
        alvo.crmv = None
        alvo.crmv_estado = None
        alvo.supervisor_id = supervisor.id
        db.session.commit()
        print('\nAplicado.')
        print(f'  Assinatura agora: {alvo.assinatura.linha_completa}')


if __name__ == '__main__':
    main()
