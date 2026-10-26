"""Mesclagem de duas contas de tutor que são a mesma pessoa.

Núcleo usado pelo script ``scripts/merge_tutor_accounts.py`` (linha de
comando) e pela tela de edição do tutor, quando o e-mail informado já pertence
a outro cadastro. Fica em ``services`` para que o app importe sem executar a
configuração de logging do script.

Por que é genérico em vez de uma lista de tabelas: existem mais de cem chaves
estrangeiras apontando para user.id. As colunas são descobertas do metadata do
SQLAlchemy, então tabela nova entra sozinha.
"""

from __future__ import annotations

import logging

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
    extra_inherit_fields: tuple = (),
) -> int:
    """Executa a mesclagem. Exige um app context ja ativo.

    ``extra_inherit_fields`` acrescenta campos do tutor herdados quando a conta
    que fica está sem eles (a tela usa para não tirar o tutor da clínica).

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
    for field in tuple(_INHERITABLE_FIELDS) + tuple(extra_inherit_fields or ()):
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
