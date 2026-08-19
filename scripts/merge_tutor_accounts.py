"""
merge_tutor_accounts.py
=======================
Junta duas contas que sao a mesma pessoa. Move TUDO que aponta para a conta de
origem (animais, consultas, visitas PMO, pagamentos, mensagens...) para a conta
que fica, e preserva na ficha o que a origem tinha de diferente.

Por que e generico em vez de uma lista de tabelas: existem 104 chaves
estrangeiras apontando para user.id. Uma lista escrita a mao ficaria
desatualizada no primeiro model novo e deixaria registro orfao sem avisar. Aqui
as colunas sao descobertas do metadata do SQLAlchemy, entao tabela nova entra
sozinha.

Colisao de unicidade: ha constraints como oauth_consent(user_id, client_id) e
medicamento_favorito(user_id, medicamento_id). Se a conta que fica ja tem a
linha equivalente, mover geraria IntegrityError -- nesses casos a linha da
origem e descartada (e um duplicado por definicao), e o script informa quantas.

O tutor de origem NAO e apagado por padrao. Ele fica sem vinculos, marcado nas
observacoes, para voce conferir antes. Use --delete-source quando tiver certeza.

Uso:
  python scripts/merge_tutor_accounts.py --from 123 --into 456 --dry-run
  python scripts/merge_tutor_accounts.py --from 123 --into 456
  python scripts/merge_tutor_accounts.py --from 123 --into 456 --delete-source

Para descobrir os ids:
  python scripts/audit_duplicate_phone_accounts.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# Campos do tutor que valem a pena herdar quando a conta que fica esta sem eles.
_INHERITABLE_FIELDS = (
    "cpf",
    "rg",
    "phone",
    "phone2",
    "date_of_birth",
    "profile_photo",
    "address",
    "endereco_id",
)


def _user_referencing_columns(metadata):
    """Toda coluna do banco que aponta para user.id, descoberta do metadata."""
    columns = []
    for table in metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name == "user" and fk.column.name == "id":
                columns.append((table, fk.parent))
    return columns


def _unique_companion_groups(table, column):
    """Colunas que acompanham ``column`` em alguma restricao de unicidade.

    Ex.: medicamento_favorito tem unique(user_id, medicamento_id) -> devolve
    [[medicamento_id]]. Mover a linha da origem para um destino que ja tem o
    mesmo medicamento violaria a restricao.
    """
    from sqlalchemy import UniqueConstraint

    def _involves(columns):
        # ColumnCollection.__contains__ so aceita string; compara por identidade.
        return any(c is column for c in columns)

    groups = []
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint) and _involves(constraint.columns):
            groups.append([c for c in constraint.columns if c is not column])
    for index in table.indexes:
        if index.unique and _involves(index.columns):
            groups.append([c for c in index.columns if c is not column])
    return groups


def _rows_colliding_with_target(session, table, column, target_id, rows):
    """Linhas da origem que ja existem no destino sob alguma unicidade.

    Detectado pelas restricoes declaradas, e nao capturando IntegrityError: o
    driver pysqlite nao honra SAVEPOINT, entao um rollback parcial nao e
    confiavel -- e sem isso o dry-run deixaria de ser dry.
    """
    from sqlalchemy import select

    colliding = set()
    for group in _unique_companion_groups(table, column):
        if not group:
            # Unicidade so na propria coluna: nunca colide ao trocar o dono.
            continue
        existing = {
            tuple(row)
            for row in session.execute(
                select(*group).where(column == target_id)
            ).fetchall()
        }
        if not existing:
            continue
        for index, row in enumerate(rows):
            mapping = row._mapping
            if tuple(mapping[col.name] for col in group) in existing:
                colliding.add(index)
    return colliding


def merge_accounts(
    source_id: int,
    target_id: int,
    dry_run: bool = False,
    delete_source: bool = False,
) -> int:
    """Executa a mesclagem. Exige um app context ja ativo.

    Separado de ``run`` para que os testes (e uma futura tela de admin) usem a
    sessao que ja existe: empurrar um segundo app context criaria uma segunda
    sessao sobre a mesma conexao, e o rollback do dry-run deixaria de valer.
    """
    from extensions import db
    from models import User
    from sqlalchemy import update

    if source_id == target_id:
        log.error("A conta de origem e a de destino sao a mesma (%s).", source_id)
        return 2

    source = db.session.get(User, source_id)
    target = db.session.get(User, target_id)
    if source is None:
        log.error("Conta de origem %s nao encontrada.", source_id)
        return 2
    if target is None:
        log.error("Conta de destino %s nao encontrada.", target_id)
        return 2

    prefix = "[DRY-RUN] " if dry_run else ""
    log.info("Origem : id=%s  %r  %s  %s", source.id, source.name, source.email, source.phone)
    log.info("Destino: id=%s  %r  %s  %s", target.id, target.name, target.email, target.phone)
    log.info("")

    moved_total = 0
    dropped_total = 0

    for table, column in _user_referencing_columns(db.metadata):
        rows = db.session.execute(table.select().where(column == source_id)).fetchall()
        if not rows:
            continue

        primary = list(table.primary_key.columns)
        colliding = _rows_colliding_with_target(
            db.session, table, column, target_id, rows
        )

        if not primary:
            # Tabela de associacao sem PK: nao da para enderecar linha a linha.
            result = db.session.execute(
                update(table).where(column == source_id).values({column.name: target_id})
            )
            moved = result.rowcount or len(rows)
            dropped = 0
        else:
            drop = [row for index, row in enumerate(rows) if index in colliding]
            for row in drop:
                mapping = row._mapping
                db.session.execute(
                    table.delete().where(*[col == mapping[col.name] for col in primary])
                )

            # As duplicadas ja sairam; o que sobrou com column == source_id e
            # exatamente o que deve mudar de dono.
            result = db.session.execute(
                update(table).where(column == source_id).values({column.name: target_id})
            )
            moved = result.rowcount if result.rowcount is not None else len(rows) - len(drop)
            dropped = len(drop)

        moved_total += moved
        dropped_total += dropped
        detail = f"{moved} movido(s)"
        if dropped:
            detail += f", {dropped} descartado(s) por duplicidade"
        log.info("%s%-42s %s", prefix, f"{table.name}.{column.name}", detail)

    # A sessao ainda tem os objetos com os valores antigos; recarrega antes de
    # mexer nos campos, senao o flush desfaz os UPDATEs feitos via Core.
    db.session.expire(source)
    db.session.expire(target)

    user_table = User.__table__
    inherited = []
    for field in _INHERITABLE_FIELDS:
        source_value = getattr(source, field, None)
        if not source_value or getattr(target, field, None):
            continue
        setattr(target, field, source_value)
        inherited.append(field)
        # Campo unico (cpf) nao pode existir nas duas contas ao mesmo tempo: se
        # a origem continuar com o valor, o UPDATE do destino viola a
        # constraint. Como a origem esta sendo esvaziada, ela cede o valor.
        column = user_table.columns.get(field)
        if column is not None and column.unique:
            setattr(source, field, None)
    if inherited:
        log.info("%sHerdados da origem: %s", prefix, ", ".join(inherited))

    # Registro na ficha: quem olhar depois precisa saber de onde veio.
    note = (
        f"Conta mesclada: dados da conta #{source.id} ({source.name}, "
        f"{source.email}, {source.phone or 'sem telefone'}) foram movidos para ca."
    )
    if note not in (target.observacoes or ""):
        target.observacoes = f"{(target.observacoes or '').rstrip()}\n{note}".strip()

    if delete_source:
        log.info("%sApagando a conta de origem #%s.", prefix, source.id)
        db.session.delete(source)
    else:
        marker = f"Conta mesclada em #{target.id}. Nao usar."
        if marker not in (source.observacoes or ""):
            source.observacoes = f"{(source.observacoes or '').rstrip()}\n{marker}".strip()
        log.info(
            "%sConta de origem #%s mantida, sem vinculos e marcada. "
            "Use --delete-source para apaga-la.",
            prefix, source.id,
        )

    log.info("")
    log.info(
        "%sTotal: %s registro(s) movido(s), %s descartado(s) por duplicidade.",
        prefix, moved_total, dropped_total,
    )

    if dry_run:
        db.session.rollback()
        log.info("[DRY-RUN] Nada foi gravado.")
    else:
        db.session.commit()
        log.info("Mesclagem concluida.")
    return 0


def run(
    source_id: int,
    target_id: int,
    dry_run: bool = False,
    delete_source: bool = False,
) -> int:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app_factory import create_app

    app = create_app()
    with app.app_context():
        return merge_accounts(
            source_id=source_id,
            target_id=target_id,
            dry_run=dry_run,
            delete_source=delete_source,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source_id", type=int, required=True,
                        help="Id da conta que sera esvaziada.")
    parser.add_argument("--into", dest="target_id", type=int, required=True,
                        help="Id da conta que fica.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostra o que mudaria sem gravar nada.")
    parser.add_argument("--delete-source", action="store_true",
                        help="Apaga a conta de origem ao final (irreversivel).")
    args = parser.parse_args()
    return run(
        source_id=args.source_id,
        target_id=args.target_id,
        dry_run=args.dry_run,
        delete_source=args.delete_source,
    )


if __name__ == "__main__":
    raise SystemExit(main())
