"""add clinica_id to health_plan and drop name unique constraint

Revision ID: c2d4e1f8a9b3
Revises: b2d4e6f8a1c3
Create Date: 2026-05-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c2d4e1f8a9b3"
down_revision = "b2d4e6f8a1c3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("health_plan")]

    if "clinica_id" not in columns:
        # Find and drop unique index on 'name' before batch recreate
        name_unique_idx = None
        for idx in inspector.get_indexes("health_plan"):
            if idx.get("unique") and idx.get("column_names") == ["name"]:
                name_unique_idx = idx["name"]
                break

        with op.batch_alter_table("health_plan", recreate="auto") as batch_op:
            if name_unique_idx:
                batch_op.drop_index(name_unique_idx)
            batch_op.add_column(
                sa.Column("clinica_id", sa.Integer(), nullable=True)
            )
            batch_op.create_foreign_key(
                "fk_health_plan_clinica",
                "clinica",
                ["clinica_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch_op.create_index("ix_health_plan_clinica_id", ["clinica_id"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("health_plan")]

    if "clinica_id" in columns:
        with op.batch_alter_table("health_plan") as batch_op:
            try:
                batch_op.drop_index("ix_health_plan_clinica_id")
            except Exception:
                pass
            try:
                batch_op.drop_constraint("fk_health_plan_clinica", type_="foreignkey")
            except Exception:
                pass
            batch_op.drop_column("clinica_id")
