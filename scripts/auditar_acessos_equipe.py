"""Mostra o que cada pessoa da equipe consegue fazer numa clínica (só leitura).

Usa ``services.team_access``, o mesmo quadro da tela de permissões. Nada é
gravado: a sessão é descartada no fim. Imprime só o primeiro nome.

Uso (no Heroku, em dyno avulso; a saída vai para os logs):
    heroku run:detached --app petorlandia -- python scripts/auditar_acessos_equipe.py --clinica 1
    heroku logs --app petorlandia --dyno run.NNNN --num 300

Filtros opcionais: --nome "Laiane" (trecho do nome) ou --estagiarios.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# create_app() direto: o CLI do flask quebra com este app factory.
from app_factory import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models import ClinicStaff, Clinica, User, Veterinario  # noqa: E402
from services.team_access import access_report  # noqa: E402


def membros_da_clinica(clinica):
    ids = {s.user_id for s in ClinicStaff.query.filter_by(clinic_id=clinica.id)}
    ids |= {v.user_id for v in Veterinario.query.filter_by(clinica_id=clinica.id)}
    ids |= {v.user_id for v in clinica.veterinarios_associados or []}
    if clinica.owner_id:
        ids.add(clinica.owner_id)
    return [u for u in User.query.filter(User.id.in_(ids)).order_by(User.name)] if ids else []


def _eh_estagiario(user):
    from helpers import is_active_intern, is_intern_account

    vet = getattr(user, 'veterinario', None)
    return bool(getattr(vet, 'is_estagiario', False) or is_intern_account(user) or is_active_intern(user))


def linhas_relatorio(clinica, nome=None, so_estagiarios=False):
    linhas = []
    for user in membros_da_clinica(clinica):
        if nome and nome.lower() not in (user.name or '').lower():
            continue
        if so_estagiarios and not _eh_estagiario(user):
            continue
        primeiro = (user.name or '').split(' ')[0]
        linhas.append(f'ACESSO| {primeiro} (user {user.id})')
        for item in access_report(user, clinica):
            marca = 'OK ' if item.allowed else 'NAO'
            extra = f' -- {item.detail}' if item.detail else ''
            linhas.append(f'ACESSO|   [{marca}] {item.label}{extra}')
    return linhas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clinica', type=int, required=True)
    parser.add_argument('--nome', help='Trecho do nome da pessoa')
    parser.add_argument('--estagiarios', action='store_true', help='Só estagiários')
    args = parser.parse_args()

    app = create_app()
    with app.test_request_context():
        try:
            clinica = db.session.get(Clinica, args.clinica)
            if not clinica:
                sys.exit(f'Clínica {args.clinica} não encontrada.')
            print(f'ACESSO| Clínica {clinica.id}')
            for linha in linhas_relatorio(clinica, args.nome, args.estagiarios):
                print(linha)
            print('ACESSO| FIM')
        finally:
            db.session.rollback()


if __name__ == '__main__':
    main()
