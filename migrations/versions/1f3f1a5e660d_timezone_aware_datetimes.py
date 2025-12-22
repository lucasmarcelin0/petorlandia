"""
Make scheduling datetimes timezone aware and backfill data.
"""

from alembic import op
import sqlalchemy as sa
from datetime import timezone
from zoneinfo import ZoneInfo

revision = "1f3f1a5e660d"
down_revision = "e1b9a8e9d0f1"
branch_labels = None
depends_on = None

BR_TZ = ZoneInfo("America/Sao_Paulo")


def _normalize_naive(value):
    if value is None:
        return None
    if getattr(value, "tzinfo", None):
        return value.astimezone(timezone.utc)

    utc_assumed = value.replace(tzinfo=timezone.utc)
    brt_assumed = value.replace(tzinfo=BR_TZ).astimezone(timezone.utc)

    utc_local_hour = utc_assumed.astimezone(BR_TZ).hour
    brt_local_hour = value.hour

    utc_score = 1 if 6 <= utc_local_hour <= 22 else 0
    brt_score = 1 if 6 <= brt_local_hour <= 22 else 0

    if brt_score > utc_score:
        return brt_assumed
    return utc_assumed


def _upgrade_column(table, column, *, nullable):
    op.alter_column(
        table,
        column,
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=nullable,
    )

    conn = op.get_bind()
    rows = conn.execute(sa.text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")).mappings()
    for row in rows:
        normalized = _normalize_naive(row[column])
        conn.execute(
            sa.text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
            {"id": row["id"], "value": normalized},
        )


def upgrade():
    _upgrade_column("appointment", "scheduled_at", nullable=False)
    _upgrade_column("appointment", "created_at", nullable=False)

    _upgrade_column("exam_appointment", "scheduled_at", nullable=False)
    _upgrade_column("exam_appointment", "request_time", nullable=True)
    _upgrade_column("exam_appointment", "confirm_by", nullable=True)

    _upgrade_column("agenda_evento", "inicio", nullable=False)
    _upgrade_column("agenda_evento", "fim", nullable=False)


def downgrade():
    op.alter_column(
        "agenda_evento",
        "fim",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
    )
    op.alter_column(
        "agenda_evento",
        "inicio",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
    )

    op.alter_column(
        "exam_appointment",
        "confirm_by",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=True,
    )
    op.alter_column(
        "exam_appointment",
        "request_time",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=True,
    )
    op.alter_column(
        "exam_appointment",
        "scheduled_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
    )

    op.alter_column(
        "appointment",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
    )
    op.alter_column(
        "appointment",
        "scheduled_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
    )
