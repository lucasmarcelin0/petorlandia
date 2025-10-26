"""add finalizada_em to consulta

Revision ID: 9a8b7c6d5e4f
Revises: ffcc9c32861f
Create Date: 2024-06-01 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9a8b7c6d5e4f'
down_revision = 'ffcc9c32861f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('consulta', sa.Column('finalizada_em', sa.DateTime(), nullable=True))

    consulta_table = sa.table(
        'consulta',
        sa.column('id', sa.Integer()),
        sa.column('status', sa.String(length=20)),
        sa.column('finalizada_em', sa.DateTime()),
        sa.column('created_at', sa.DateTime()),
    )

    bind = op.get_bind()
    bind.execute(
        sa.update(consulta_table)
        .where(
            sa.and_(
                consulta_table.c.status == 'finalizada',
                consulta_table.c.finalizada_em.is_(None),
            )
        )
        .values(finalizada_em=consulta_table.c.created_at)
    )


def downgrade():
    op.drop_column('consulta', 'finalizada_em')
