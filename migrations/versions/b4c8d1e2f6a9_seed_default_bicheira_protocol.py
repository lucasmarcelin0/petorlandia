"""seed default bicheira protocol

Revision ID: b4c8d1e2f6a9
Revises: a91f0d6c3b42
Create Date: 2026-05-04 15:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4c8d1e2f6a9'
down_revision = 'a91f0d6c3b42'
branch_labels = None
depends_on = None


protocolo_clinico = sa.table(
    'protocolo_clinico',
    sa.column('id', sa.Integer()),
    sa.column('nome', sa.String(length=120)),
    sa.column('suspeita_principal', sa.String(length=160)),
    sa.column('especie', sa.String(length=40)),
    sa.column('sinais_gatilho', sa.Text()),
    sa.column('conduta_sugerida', sa.Text()),
    sa.column('orientacoes_tutor', sa.Text()),
    sa.column('alertas', sa.Text()),
    sa.column('prioridade', sa.Integer()),
    sa.column('versao', sa.Integer()),
    sa.column('ativo', sa.Boolean()),
    sa.column('clinica_id', sa.Integer()),
)

protocolo_clinico_medicamento = sa.table(
    'protocolo_clinico_medicamento',
    sa.column('id', sa.Integer()),
    sa.column('protocolo_id', sa.Integer()),
    sa.column('medicamento_id', sa.Integer()),
    sa.column('nome_medicamento', sa.String(length=120)),
    sa.column('justificativa', sa.Text()),
    sa.column('dosagem_texto', sa.Text()),
    sa.column('frequencia_texto', sa.Text()),
    sa.column('duracao_texto', sa.Text()),
    sa.column('observacoes', sa.Text()),
    sa.column('indicacao', sa.String(length=120)),
    sa.column('prioridade', sa.Integer()),
)


def upgrade() -> None:
    bind = op.get_bind()

    existing_protocol = bind.execute(
        sa.select(sa.column('id'))
        .select_from(sa.text('protocolo_clinico'))
        .where(
            sa.text(
                "nome = :nome AND suspeita_principal = :suspeita_principal AND clinica_id IS NULL"
            )
        ),
        {
            'nome': 'Protocolo Inicial para Bicheira',
            'suspeita_principal': 'bicheira',
        },
    ).first()
    if existing_protocol:
        return

    protocol_id = bind.execute(
        sa.insert(protocolo_clinico).returning(sa.column('id')),
        {
            'nome': 'Protocolo Inicial para Bicheira',
            'suspeita_principal': 'bicheira',
            'especie': None,
            'sinais_gatilho': 'Miíase cutânea, presença de larvas, ferida contaminada, odor fétido.',
            'conduta_sugerida': (
                'Realizar retirada manual das larvas de moscas e limpeza criteriosa da lesão '
                'antes de definir a conduta complementar.'
            ),
            'orientacoes_tutor': None,
            'alertas': None,
            'prioridade': 2,
            'versao': 1,
            'ativo': True,
            'clinica_id': None,
        },
    ).scalar_one()

    bind.execute(
        sa.insert(protocolo_clinico_medicamento),
        [
            {
                'protocolo_id': protocol_id,
                'medicamento_id': None,
                'nome_medicamento': 'Cefalexina',
                'justificativa': 'Antibioticoterapia de suporte para ferida infestada, conforme avaliação clínica.',
                'dosagem_texto': None,
                'frequencia_texto': None,
                'duracao_texto': None,
                'observacoes': None,
                'indicacao': 'Suporte infeccioso',
                'prioridade': 1,
            },
            {
                'protocolo_id': protocol_id,
                'medicamento_id': None,
                'nome_medicamento': 'Capstar',
                'justificativa': 'Controle complementar de ectoparasitas quando clinicamente indicado.',
                'dosagem_texto': None,
                'frequencia_texto': None,
                'duracao_texto': None,
                'observacoes': None,
                'indicacao': 'Controle parasitário',
                'prioridade': 2,
            },
            {
                'protocolo_id': protocol_id,
                'medicamento_id': None,
                'nome_medicamento': 'Meloxicam',
                'justificativa': 'Controle de dor e inflamação conforme avaliação clínica.',
                'dosagem_texto': None,
                'frequencia_texto': None,
                'duracao_texto': None,
                'observacoes': None,
                'indicacao': 'Analgesia',
                'prioridade': 3,
            },
            {
                'protocolo_id': protocol_id,
                'medicamento_id': None,
                'nome_medicamento': 'Pomada de sulfadiazina de prata',
                'justificativa': 'Cuidado tópico complementar da lesão após limpeza e manejo inicial.',
                'dosagem_texto': None,
                'frequencia_texto': None,
                'duracao_texto': None,
                'observacoes': None,
                'indicacao': 'Uso tópico',
                'prioridade': 4,
            },
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    protocol_id = bind.execute(
        sa.select(sa.column('id'))
        .select_from(sa.text('protocolo_clinico'))
        .where(
            sa.text(
                "nome = :nome AND suspeita_principal = :suspeita_principal AND clinica_id IS NULL"
            )
        ),
        {
            'nome': 'Protocolo Inicial para Bicheira',
            'suspeita_principal': 'bicheira',
        },
    ).scalar_one_or_none()
    if protocol_id is None:
        return

    bind.execute(
        sa.text('DELETE FROM protocolo_clinico_medicamento WHERE protocolo_id = :protocol_id'),
        {'protocol_id': protocol_id},
    )
    bind.execute(
        sa.text('DELETE FROM protocolo_clinico WHERE id = :protocol_id'),
        {'protocol_id': protocol_id},
    )
