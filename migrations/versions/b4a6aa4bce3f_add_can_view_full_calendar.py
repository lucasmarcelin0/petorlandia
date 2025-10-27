"""add can_view_full_calendar to clinic staff"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4a6aa4bce3f'
down_revision = 'ffcc9c32861f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'clinic_staff',
        sa.Column(
            'can_view_full_calendar',
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.execute('UPDATE clinic_staff SET can_view_full_calendar = true')
    op.alter_column(
        'clinic_staff',
        'can_view_full_calendar',
        server_default=None,
    )


def downgrade():
    op.drop_column('clinic_staff', 'can_view_full_calendar')
