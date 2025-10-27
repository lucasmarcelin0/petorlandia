"""Create veterinarian membership table"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import column, table
from datetime import datetime, timedelta


# revision identifiers, used by Alembic.
revision = '1e5b8c4d2f3a'
down_revision = 'ffcc9c32861f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'veterinarian_membership',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('veterinario_id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('trial_ends_at', sa.DateTime(), nullable=False),
        sa.Column('paid_until', sa.DateTime(), nullable=True),
        sa.Column('last_payment_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['veterinario_id'], ['veterinario.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['last_payment_id'], ['payment.id']),
        sa.UniqueConstraint('veterinario_id', name='uq_veterinarian_membership_veterinario_id'),
    )

    bind = op.get_bind()
    veterinarian_table = table('veterinario', column('id', sa.Integer()))
    membership_table = table(
        'veterinarian_membership',
        column('veterinario_id', sa.Integer()),
        column('started_at', sa.DateTime()),
        column('trial_ends_at', sa.DateTime()),
    )

    result = bind.execute(sa.select(veterinarian_table.c.id))
    rows = []
    for vet_id, in result:
        started_at = datetime.utcnow()
        rows.append(
            {
                'veterinario_id': vet_id,
                'started_at': started_at,
                'trial_ends_at': started_at + timedelta(days=30),
            }
        )

    if rows:
        op.bulk_insert(membership_table, rows)


def downgrade():
    op.drop_table('veterinarian_membership')
