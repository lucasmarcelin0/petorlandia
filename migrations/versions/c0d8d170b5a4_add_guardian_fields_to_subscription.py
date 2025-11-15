"""add guardian consent fields to health_subscription"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c0d8d170b5a4'
down_revision = 'bbe7d8ed2f6f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('health_subscription', sa.Column('guardian_document', sa.String(length=40), nullable=True))
    op.add_column('health_subscription', sa.Column('animal_document', sa.String(length=60), nullable=True))
    op.add_column('health_subscription', sa.Column('contract_reference', sa.String(length=80), nullable=True))
    op.add_column('health_subscription', sa.Column('consent_signed_at', sa.DateTime(), nullable=True))
    op.add_column('health_subscription', sa.Column('consent_ip', sa.String(length=64), nullable=True))


def downgrade():
    op.drop_column('health_subscription', 'consent_ip')
    op.drop_column('health_subscription', 'consent_signed_at')
    op.drop_column('health_subscription', 'contract_reference')
    op.drop_column('health_subscription', 'animal_document')
    op.drop_column('health_subscription', 'guardian_document')
