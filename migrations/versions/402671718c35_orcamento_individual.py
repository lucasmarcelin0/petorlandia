"""orçamento individual

Revision ID: 402671718c35
Revises: 577a5ea273a3
Create Date: 2024-06-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '402671718c35'
down_revision = '577a5ea273a3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bloco_orcamento', schema=None) as batch_op:
        batch_op.add_column(sa.Column('clinica_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_bloco_orcamento_clinica_id', 'clinica', ['clinica_id'], ['id'])

    connection = op.get_bind()
    connection.execute(sa.text(
        """
        UPDATE bloco_orcamento AS bo
        SET clinica_id = a.clinica_id
        FROM animal AS a
        WHERE bo.animal_id = a.id
        """
    ))

    with op.batch_alter_table('bloco_orcamento', schema=None) as batch_op:
        batch_op.alter_column('clinica_id', existing_type=sa.Integer(), nullable=False)


def downgrade():
    with op.batch_alter_table('bloco_orcamento', schema=None) as batch_op:
        batch_op.drop_constraint('fk_bloco_orcamento_clinica_id', type_='foreignkey')
        batch_op.drop_column('clinica_id')
