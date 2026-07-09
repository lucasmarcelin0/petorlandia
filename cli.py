"""Comandos de CLI do Flask (``flask <comando>``).

Extraído de app.py durante a modularização. Registrar com:

    from cli import register_cli_commands
    register_cli_commands(app)
"""
from __future__ import annotations

import click
from flask.cli import with_appcontext

from services.finance import run_transactions_history_backfill


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
