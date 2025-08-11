from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '07c9382e9aad'
down_revision = '6ec5a8a3dea4'
branch_labels = None
depends_on = None

def upgrade():
    # Não quebra se a coluna já existir
    op.execute("ALTER TABLE product ADD COLUMN IF NOT EXISTS mp_category_id VARCHAR(50)")

def downgrade():
    # Não quebra se a coluna já tiver sido removida
    op.execute("ALTER TABLE product DROP COLUMN IF EXISTS mp_category_id")
