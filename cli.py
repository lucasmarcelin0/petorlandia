"""Comandos de CLI do Flask (``flask <comando>``).

Extraído de app.py durante a modularização. Registrar com:

    from cli import register_cli_commands
    register_cli_commands(app)
"""
from __future__ import annotations

import click
from flask.cli import with_appcontext

from extensions import db
from models.agenda import VetSchedule
from models.clinica import Clinica
from models.loja import Payment
from models.racao import CasaDeRacao
from models.usuarios import User, Veterinario
from services.finance import run_transactions_history_backfill


# Contas confirmadas como dados de teste no ambiente de producao. Nao inclui
# importacoes VetSmart nem os cadastros da campanha/Controle de Vetores.
KNOWN_TEST_USER_IDS = (
    242, 465, 466, 568, 760, 892, 894, 999, 1521, 1522, 1621, 1627,
    1633, 2839, 2905, 2971, 3004, 3070, 3071, 3072, 3073, 3499,
    3664, 3832, 3863, 3895, 3896, 3897, 3961, 3962, 3968, 3969, 3970,
)


@click.command('cleanup-test-users')
@click.option('--apply', is_flag=True, help='Executa a exclusao. Sem esta opcao, apenas mostra a previa.')
@click.option('--user-id', 'user_ids', type=int, multiple=True, help='ID adicional de conta de teste (repetivel).')
@click.option('--store-owner-id', type=int, default=1, show_default=True, help='Dono para lojas de teste preservadas.')
@with_appcontext
def cleanup_test_users(apply, user_ids, store_owner_id):
    """Remove contas de teste pelo ORM, preservando os dados de producao."""
    target_ids = tuple(sorted(set(KNOWN_TEST_USER_IDS).union(user_ids)))
    users = User.query.filter(User.id.in_(target_ids)).order_by(User.id).all()
    missing = sorted(set(target_ids) - {user.id for user in users})

    click.echo(f'{len(users)} conta(s) encontrada(s): ' + ', '.join(str(user.id) for user in users))
    if missing:
        click.echo('IDs ausentes: ' + ', '.join(map(str, missing)))
    if not apply:
        click.echo('Previa apenas. Execute novamente com --apply para excluir.')
        return

    # Contas de teste podem ser proprietarias de clinicas/lojas criadas para
    # validacao. Clinicas ficam sem dono; lojas exigem dono e sao entregues ao
    # administrador informado para que o catalogo nao fique inconsistente.
    Clinica.query.filter(Clinica.owner_id.in_(target_ids)).update(
        {Clinica.owner_id: None}, synchronize_session=False
    )
    Clinica.query.filter(Clinica.registered_by_id.in_(target_ids)).update(
        {Clinica.registered_by_id: None}, synchronize_session=False
    )
    CasaDeRacao.query.filter(CasaDeRacao.owner_id.in_(target_ids)).update(
        {CasaDeRacao.owner_id: store_owner_id}, synchronize_session=False
    )
    CasaDeRacao.query.filter(CasaDeRacao.registered_by_id.in_(target_ids)).update(
        {CasaDeRacao.registered_by_id: None}, synchronize_session=False
    )

    veterinarian_ids = [
        vet_id for (vet_id,) in db.session.query(Veterinario.id)
        .filter(Veterinario.user_id.in_(target_ids)).all()
    ]
    if veterinarian_ids:
        # A coluna e obrigatoria e o relacionamento legado nao possui
        # delete-orphan; apagar antes evita o ORM tentar desvincula-la.
        VetSchedule.query.filter(VetSchedule.veterinario_id.in_(veterinarian_ids)).delete(
            synchronize_session=False
        )

    for user in users:
        # Espelha a exclusao de conta da aplicacao para relacoes que nao usam
        # cascata no banco, deixando o ORM resolver as demais dependencias.
        for message in set(user.sent_messages).union(user.received_messages):
            db.session.delete(message)
        for payment in Payment.query.filter_by(user_id=user.id).all():
            for subscription in list(payment.subscriptions):
                subscription.payment = None
            db.session.delete(payment)
        db.session.delete(user)

    db.session.commit()
    click.echo(f'{len(users)} conta(s) de teste excluida(s).')


@click.command('classify-transactions-history')
@click.option(
    '--months',
    type=click.IntRange(min=1),
    default=6,
    show_default=True,
    help='Quantidade de meses a reprocessar a partir do mês de referência.',
)
@click.option(
    '--clinic-id',
    'clinic_ids',
    type=int,
    multiple=True,
    help='Limite o processamento a clínicas específicas (pode ser informado múltiplas vezes).',
)
@click.option(
    '--reference-month',
    type=str,
    default=None,
    help='Mês base (YYYY-MM) para iniciar a varredura; padrão: mês atual.',
)
@click.option(
    '--verbose/--quiet',
    default=False,
    help='Mostra logs detalhados para cada combinação clínica/mês.',
)
@with_appcontext
def classify_transactions_history(months, clinic_ids, reference_month, verbose):
    """Reprocessa classificações de receitas e despesas para meses anteriores."""

    def _verbose_callback(clinic_id, month_start):
        click.echo(
            f"Classificando clínica {clinic_id} — mês {month_start:%Y-%m}",
            err=False,
        )

    def _error_callback(clinic_id, month_start, exc):
        click.echo(
            f"Erro ao classificar a clínica {clinic_id} no mês {month_start:%Y-%m}: {exc}",
            err=True,
        )

    try:
        result = run_transactions_history_backfill(
            months=months,
            reference_month=reference_month,
            clinic_ids=clinic_ids,
            progress_callback=_verbose_callback if verbose else None,
            error_callback=_error_callback,
        )
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc

    if not result.clinics:
        click.echo('Nenhuma clínica encontrada para processar.')
        return

    if result.failures:
        click.echo(
            f'{len(result.failures)} combinação(ões) falharam; verifique os logs acima.',
            err=True,
        )
    click.echo(
        f'Classificação executada para {result.processed} combinações de clínica/mês.'
    )


def register_cli_commands(app):
    app.cli.add_command(classify_transactions_history)
    app.cli.add_command(cleanup_test_users)
