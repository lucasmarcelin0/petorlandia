"""add fiscal document context fields

Revision ID: a2c4f8d1e0b7
Revises: b7c1a2d3e4f5
Create Date: 2026-02-02 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a2c4f8d1e0b7"
down_revision = "b7c1a2d3e4f5"
branch_labels = None
depends_on = None



def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("fiscal_documents")}

    if "source_type" not in columns:
        op.add_column("fiscal_documents", sa.Column("source_type", sa.String(length=40)))
    if "source_id" not in columns:
        op.add_column("fiscal_documents", sa.Column("source_id", sa.Integer()))
    if "human_reference" not in columns:
        op.add_column("fiscal_documents", sa.Column("human_reference", sa.String(length=255)))
    if "animal_name" not in columns:
        op.add_column("fiscal_documents", sa.Column("animal_name", sa.String(length=120)))
    if "tutor_name" not in columns:
        op.add_column("fiscal_documents", sa.Column("tutor_name", sa.String(length=120)))



def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("fiscal_documents")}

    if "tutor_name" in columns:
        op.drop_column("fiscal_documents", "tutor_name")
    if "animal_name" in columns:
        op.drop_column("fiscal_documents", "animal_name")
    if "human_reference" in columns:
        op.drop_column("fiscal_documents", "human_reference")
    if "source_id" in columns:
        op.drop_column("fiscal_documents", "source_id")
    if "source_type" in columns:
        op.drop_column("fiscal_documents", "source_type")
