"""Mark accounts created without a contact e-mail."""
from alembic import op
import sqlalchemy as sa
revision = 'f2b8c4d6e1a9'
down_revision = 'f1a7c9e2d4b6'
branch_labels = None
depends_on = None
def upgrade():
    op.add_column('user', sa.Column('email_is_placeholder', sa.Boolean(), nullable=False, server_default=sa.false()))
def downgrade():
    op.drop_column('user', 'email_is_placeholder')
