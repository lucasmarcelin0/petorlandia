#!/usr/bin/env python3
"""Gera relatório de medicamentos com campos incompletos."""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
from pathlib import Path

CAMPOS_ANALISADOS = [
    "classificacao",
    "principio_ativo",
    "via_administracao",
    "dosagem_recomendada",
    "frequencia",
    "duracao_tratamento",
    "observacoes",
    "bula",
]


def _is_incompleto(valor: object) -> bool:
    if valor is None:
        return True
    if isinstance(valor, str) and not valor.strip():
        return True
    return False


def _escrever_cabecalho(arquivo, db_path: Path) -> str:
    agora = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    arquivo.write("# Relatório de medicamentos com campos incompletos\n\n")
    arquivo.write(f"- Data/hora da análise: {agora}\n")
    arquivo.write(f"- Banco analisado: `{db_path}`\n")
    return agora


def gerar_relatorio(db_path: Path, saida: Path) -> tuple[int, int]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    saida.parent.mkdir(parents=True, exist_ok=True)

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='medicamento'"
    )
    if cur.fetchone() is None:
        with saida.open("w", encoding="utf-8") as f:
            _escrever_cabecalho(f, db_path)
            f.write("\n")
            f.write("⚠️ A tabela `medicamento` não foi encontrada neste banco.\n")
            f.write(
                "Não foi possível listar registros com campos incompletos porque o banco atual está sem schema/dados desse módulo.\n"
            )
        con.close()
        return 0, 0

    campos_select = ", ".join(["id", "nome", *CAMPOS_ANALISADOS])
    cur.execute(f"SELECT {campos_select} FROM medicamento ORDER BY id")
    rows = cur.fetchall()

    incompletos: list[tuple[int, str, list[str]]] = []
    for row in rows:
        faltantes = [campo for campo in CAMPOS_ANALISADOS if _is_incompleto(row[campo])]
        if faltantes:
            incompletos.append((row["id"], row["nome"], faltantes))

    with saida.open("w", encoding="utf-8") as f:
        _escrever_cabecalho(f, db_path)
        f.write(f"- Total de medicamentos avaliados: **{len(rows)}**\n")
        f.write(f"- Medicamentos com ao menos um campo incompleto: **{len(incompletos)}**\n\n")

        if not incompletos:
            f.write("Nenhum medicamento com campos incompletos foi encontrado.\n")
        else:
            f.write("| ID | Nome | Campos incompletos |\n")
            f.write("|---:|---|---|\n")
            for med_id, nome, faltantes in incompletos:
                campos = ", ".join(faltantes)
                f.write(f"| {med_id} | {nome} | {campos} |\n")

    con.close()
    return len(rows), len(incompletos)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="instance/dev.db", help="Caminho do banco SQLite")
    parser.add_argument(
        "--out",
        default="reports/relatorio_medicamentos_incompletos.md",
        help="Arquivo de saída do relatório",
    )
    args = parser.parse_args()

    total, incompletos = gerar_relatorio(Path(args.db), Path(args.out))
    print(f"Relatório gerado em {args.out} | avaliados={total} | com pendência={incompletos}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
