from alembic import op
import sqlalchemy as sa

revision = '8a0f9b6f2add'
down_revision = '6ec5a8a3dea4'
branch_labels = None
depends_on = None

def upgrade():
    # 1) cria a coluna se não existir
    op.execute("ALTER TABLE delivery_request ADD COLUMN IF NOT EXISTS archived BOOLEAN")

    # 2) garante valor para linhas antigas
    op.execute("UPDATE delivery_request SET archived = COALESCE(archived, FALSE)")

    # 3) aplica DEFAULT e NOT NULL
    op.execute("ALTER TABLE delivery_request ALTER COLUMN archived SET DEFAULT FALSE")
    op.execute("ALTER TABLE delivery_request ALTER COLUMN archived SET NOT NULL")

def downgrade():
    # reverte com segurança
    op.execute("ALTER TABLE delivery_request ALTER COLUMN archived DROP NOT NULL")
    op.execute("ALTER TABLE delivery_request ALTER COLUMN archived DROP DEFAULT")
    op.execute("ALTER TABLE delivery_request DROP COLUMN IF EXISTS archived")
