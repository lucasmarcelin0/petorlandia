"""scope budgets and prescriptions per clinic

Revision ID: 7de8c7e1dd0d
Revises: c49321bb88a2
Create Date: 2024-05-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7de8c7e1dd0d'
down_revision = 'c49321bb88a2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orcamento_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('clinica_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_orcamento_item_clinica_id',
            'clinica',
            ['clinica_id'],
            ['id'],
        )

    with op.batch_alter_table('bloco_prescricao', schema=None) as batch_op:
        batch_op.add_column(sa.Column('clinica_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_bloco_prescricao_clinica_id',
            'clinica',
            ['clinica_id'],
            ['id'],
        )

    conn = op.get_bind()
    conn.execute(sa.text(
        """
        UPDATE orcamento_item
        SET clinica_id = (
            SELECT clinica_id FROM consulta WHERE consulta.id = orcamento_item.consulta_id
        )
        WHERE consulta_id IS NOT NULL
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE orcamento_item
        SET clinica_id = (
            SELECT clinica_id FROM bloco_orcamento WHERE bloco_orcamento.id = orcamento_item.bloco_id
        )
        WHERE clinica_id IS NULL AND bloco_id IS NOT NULL
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE orcamento_item
        SET clinica_id = (
            SELECT clinica_id FROM orcamento WHERE orcamento.id = orcamento_item.orcamento_id
        )
        WHERE clinica_id IS NULL AND orcamento_id IS NOT NULL
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE orcamento_item
        SET clinica_id = (
            SELECT clinica_id FROM servico_clinica WHERE servico_clinica.id = orcamento_item.servico_id
        )
        WHERE clinica_id IS NULL AND servico_id IS NOT NULL
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE bloco_prescricao
        SET clinica_id = (
            SELECT clinica_id FROM animal WHERE animal.id = bloco_prescricao.animal_id
        )
        WHERE clinica_id IS NULL
        """
    ))

    conn.execute(sa.text(
        """
        UPDATE orcamento_item
        SET clinica_id = animal.clinica_id
        FROM consulta
        JOIN animal ON animal.id = consulta.animal_id
        WHERE orcamento_item.clinica_id IS NULL
          AND orcamento_item.consulta_id = consulta.id
          AND animal.clinica_id IS NOT NULL
        """
    ))

    conn.execute(sa.text(
        """
        UPDATE bloco_prescricao
        SET clinica_id = animal.clinica_id
        FROM animal
        WHERE bloco_prescricao.clinica_id IS NULL
          AND bloco_prescricao.animal_id = animal.id
          AND animal.clinica_id IS NOT NULL
        """
    ))

    default_clinic_id = conn.execute(
        sa.text("SELECT id FROM clinica ORDER BY id LIMIT 1")
    ).scalar()
    if default_clinic_id is None:
        raise RuntimeError("Nenhuma clínica cadastrada para definir clinica_id padrão")

    conn.execute(sa.text(
        """
        WITH default_clinic AS (SELECT :default_clinic_id AS id)
        UPDATE orcamento_item AS oi
        SET clinica_id = COALESCE(
            consulta.clinica_id,
            bloco.clinica_id,
            orcamento.clinica_id,
            servico.clinica_id,
            consulta_animal.clinica_id,
            default_clinic.id
        )
        FROM default_clinic
        LEFT JOIN consulta ON consulta.id = oi.consulta_id
        LEFT JOIN animal AS consulta_animal ON consulta_animal.id = consulta.animal_id
        LEFT JOIN bloco_orcamento AS bloco ON bloco.id = oi.bloco_id
        LEFT JOIN orcamento ON orcamento.id = oi.orcamento_id
        LEFT JOIN servico_clinica AS servico ON servico.id = oi.servico_id
        WHERE oi.clinica_id IS NULL
        """
    ), {"default_clinic_id": default_clinic_id})

    conn.execute(sa.text(
        """
        WITH default_clinic AS (SELECT :default_clinic_id AS id)
        UPDATE bloco_prescricao AS bp
        SET clinica_id = COALESCE(
            animal.clinica_id,
            default_clinic.id
        )
        FROM default_clinic
        LEFT JOIN animal ON animal.id = bp.animal_id
        WHERE bp.clinica_id IS NULL
        """
    ), {"default_clinic_id": default_clinic_id})

    remaining_orcamento_items = conn.execute(
        sa.text("SELECT id FROM orcamento_item WHERE clinica_id IS NULL LIMIT 5")
    ).fetchall()
    if remaining_orcamento_items:
        raise RuntimeError(
            "Não foi possível definir clinica_id para os orçamentos: "
            + ", ".join(str(row.id) for row in remaining_orcamento_items)
        )

    remaining_blocos = conn.execute(
        sa.text("SELECT id FROM bloco_prescricao WHERE clinica_id IS NULL LIMIT 5")
    ).fetchall()
    if remaining_blocos:
        raise RuntimeError(
            "Não foi possível definir clinica_id para os blocos de prescrição: "
            + ", ".join(str(row.id) for row in remaining_blocos)
        )

    with op.batch_alter_table('orcamento_item', schema=None) as batch_op:
        batch_op.alter_column('clinica_id', existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table('bloco_prescricao', schema=None) as batch_op:
        batch_op.alter_column('clinica_id', existing_type=sa.Integer(), nullable=False)


def downgrade():
    with op.batch_alter_table('orcamento_item', schema=None) as batch_op:
        batch_op.drop_constraint('fk_orcamento_item_clinica_id', type_='foreignkey')
        batch_op.drop_column('clinica_id')

    with op.batch_alter_table('bloco_prescricao', schema=None) as batch_op:
        batch_op.drop_constraint('fk_bloco_prescricao_clinica_id', type_='foreignkey')
        batch_op.drop_column('clinica_id')
