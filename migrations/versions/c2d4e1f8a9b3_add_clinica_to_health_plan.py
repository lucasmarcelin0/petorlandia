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
        # Drop unique constraint on 'name' (PostgreSQL names it <table>_<col>_key)
        unique_constraints = [
            uc["name"]
            for uc in inspector.get_unique_constraints("health_plan")
            if "name" in uc.get("column_names", [])
        ]
        for uc_name in unique_constraints:
            op.drop_constraint(uc_name, "health_plan", type_="unique")

        op.add_column(
            "health_plan",
            sa.Column("clinica_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_health_plan_clinica",
            "health_plan",
            "clinica",
            ["clinica_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index("ix_health_plan_clinica_id", "health_plan", ["clinica_id"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("health_plan")]

    if "clinica_id" in columns:
        try:
            op.drop_index("ix_health_plan_clinica_id", table_name="health_plan")
        except Exception:
            pass
        try:
            op.drop_constraint("fk_health_plan_clinica", "health_plan", type_="foreignkey")
        except Exception:
            pass
        op.drop_column("health_plan", "clinica_id")
        op.create_unique_constraint("health_plan_name_key", "health_plan", ["name"])
