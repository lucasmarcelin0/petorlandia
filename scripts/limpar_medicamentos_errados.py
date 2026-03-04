"""
Script: limpar_medicamentos_errados.py
=======================================
Remove todos os medicamentos inseridos incorretamente com prefixo "Avaliar "
e com todos os campos de dados vazios.

USO:
  # Ver o que será apagado (sem apagar nada):
  python scripts/limpar_medicamentos_errados.py --dry-run

  # Apagar de verdade:
  python scripts/limpar_medicamentos_errados.py
"""

import os
import sys
import argparse
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    os.environ.get(
        "SQLALCHEMY_DATABASE_URI",
        "postgresql://u82pgjdcmkbq7v:p0204cb9289674b66bfcbb9248eaf9d6a71e2dece2722fe22d6bd976c77b411e6"
        "@c2hbg00ac72j9d.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/d2nnmcuqa8ljli",
    ),
)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


def main():
    parser = argparse.ArgumentParser(description="Remove medicamentos inseridos com erro.")
    parser.add_argument("--dry-run", action="store_true", help="Apenas mostra, não apaga.")
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=15)
    conn.autocommit = False

    with conn.cursor() as cur:
        # Busca todos os registros com nome começando em "Avaliar "
        # OU com todos os campos de dados vazios (resultado de scraping mal-sucedido)
        cur.execute("""
            SELECT id, nome
            FROM medicamento
            WHERE
                nome LIKE 'Avaliar %%'
                OR (
                    classificacao IS NULL
                    AND principio_ativo IS NULL
                    AND via_administracao IS NULL
                    AND dosagem_recomendada IS NULL
                    AND frequencia IS NULL
                    AND duracao_tratamento IS NULL
                    AND observacoes IS NULL
                    AND bula IS NULL
                )
            ORDER BY nome
        """)
        registros = cur.fetchall()

    print(f"\nEncontrados {len(registros)} registros para remover:\n")
    for r in registros:
        print(f"  [{r['id']}] {r['nome']}")

    if not registros:
        print("\nNada para apagar. Banco já está limpo.")
        conn.close()
        return

    if args.dry_run:
        print(f"\n⚠️  DRY-RUN: Nenhum registro foi apagado.")
        conn.close()
        return

    ids = [r["id"] for r in registros]
    with conn.cursor() as cur:
        # Apaga primeiro as apresentações (FK)
        cur.execute(
            "DELETE FROM apresentacao_medicamento WHERE medicamento_id = ANY(%s)",
            (ids,)
        )
        apres_deletadas = cur.rowcount

        # Apaga os medicamentos
        cur.execute(
            "DELETE FROM medicamento WHERE id = ANY(%s)",
            (ids,)
        )
        med_deletados = cur.rowcount

    conn.commit()
    conn.close()

    print(f"""
{'='*50}
  LIMPEZA CONCLUÍDA
{'='*50}
  Medicamentos removidos:   {med_deletados}
  Apresentações removidas:  {apres_deletadas}
{'='*50}
""")


if __name__ == "__main__":
    main()
