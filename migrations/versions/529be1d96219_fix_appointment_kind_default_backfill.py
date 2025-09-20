"""fix appointment.kind default/backfill

Revision ID: 529be1d96219
Revises: 2f9a0dc93f25
Create Date: 2025-09-20 18:38:44.919801
"""

from importlib import util as importlib_util

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "529be1d96219"

_HAS_MEDICAMENTO_TEXT_EXPANSION = importlib_util.find_spec(
    "migrations.versions.2f9a0dc93f25_expand_medicamento_text_fields"
) is not None
down_revision = "2f9a0dc93f25" if _HAS_MEDICAMENTO_TEXT_EXPANSION else "b1db1e768d50"
branch_labels = None
depends_on = None


_DEF_VALUE = "general"
_DEF_SERVER_DEFAULT = sa.text(f"'{_DEF_VALUE}'")


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("appointment")}
    kind_column = columns.get("kind")

    if kind_column is None:
        with op.batch_alter_table("appointment") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "kind",
                    sa.String(length=20),
                    nullable=False,
                    server_default=_DEF_SERVER_DEFAULT,
                )
            )
        return

    original_nullable = kind_column.get("nullable", True)

    # Allow temporary NULLs so existing rows can be backfilled safely
    with op.batch_alter_table("appointment") as batch_op:
        batch_op.alter_column(
            "kind",
            existing_type=sa.String(length=20),
            nullable=True,
            existing_nullable=original_nullable,
        )

    op.execute(
        sa.text("UPDATE appointment SET kind = :value WHERE kind IS NULL").bindparams(value=_DEF_VALUE)
    )

    # Enforce NOT NULL and set the default for future inserts
    with op.batch_alter_table("appointment") as batch_op:
        batch_op.alter_column(
            "kind",
            existing_type=sa.String(length=20),
            nullable=False,
            existing_nullable=True,
            server_default=_DEF_SERVER_DEFAULT,
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("appointment")}

    if "kind" not in columns:
        return

    with op.batch_alter_table("appointment") as batch_op:
        batch_op.alter_column(
            "kind",
            existing_type=sa.String(length=20),
            nullable=True,
            existing_nullable=False,
            server_default=None,
        )
