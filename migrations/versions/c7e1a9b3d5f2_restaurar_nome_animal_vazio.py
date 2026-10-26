"""Restaura o nome de animais que ficaram sem nome ("None" no prontuário).

O ``update_animal`` gravava ``name = None`` quando o envio do formulário
chegava incompleto (upload da foto interrompido). A rota foi corrigida; aqui
recuperamos o nome dos cadastros já afetados a partir do nome registrado na
campanha da Prefeitura (vacinação antirrábica ou castração) vinculada ao
mesmo animal. Só altera animais cujo nome está vazio; nenhum nome existente
é tocado. Animais sem vínculo com campanha continuam sem nome e precisam ser
corrigidos na tela.

Revision ID: c7e1a9b3d5f2
Revises: a26c1022b001
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7e1a9b3d5f2'
down_revision = 'a26c1022b001'
branch_labels = None
depends_on = None

_SEM_NOME = "(animal.name IS NULL OR TRIM(animal.name) = '')"


def _restaurar_de(conn, tabela):
    inspector = sa.inspect(conn)
    if tabela not in inspector.get_table_names():
        return 0
    # Para cada animal sem nome, o nome mais antigo registrado na campanha.
    linhas = conn.execute(sa.text(
        f"""
        SELECT animal.id AS animal_id, p.name AS nome
        FROM animal
        JOIN {tabela} p ON p.animal_id = animal.id
        WHERE {_SEM_NOME}
          AND p.name IS NOT NULL AND TRIM(p.name) <> ''
        ORDER BY animal.id, p.id
        """
    )).fetchall()
    restaurados = 0
    vistos = set()
    for animal_id, nome in linhas:
        if animal_id in vistos:
            continue
        vistos.add(animal_id)
        resultado = conn.execute(
            sa.text(f"UPDATE animal SET name = :nome WHERE id = :id AND {_SEM_NOME}"),
            {"nome": nome.strip()[:100], "id": animal_id},
        )
        restaurados += resultado.rowcount or 0
    return restaurados


def upgrade():
    conn = op.get_bind()
    total = 0
    for tabela in ('pmo_vaccination_animal', 'pmo_castration_animal'):
        total += _restaurar_de(conn, tabela)
    restantes = conn.execute(sa.text(f"SELECT COUNT(*) FROM animal WHERE {_SEM_NOME}")).scalar() or 0
    print(f"[restaurar_nome_animal] nomes restaurados: {total}; ainda sem nome: {restantes}")


def downgrade():
    # Restaurar nome perdido não tem volta útil: não apagamos nomes de novo.
    pass
