#!/usr/bin/env python3
"""Gera relatório de medicamentos com campos incompletos (SQLite/PostgreSQL)."""
from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

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


def _escrever_cabecalho(arquivo, fonte_dados: str) -> None:
    agora = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    arquivo.write("# Relatório de medicamentos com campos incompletos\n\n")
    arquivo.write(f"- Data/hora da análise: {agora}\n")
    arquivo.write(f"- Fonte de dados: `{fonte_dados}`\n")


def _normalizar_database_url(url: str) -> str:
    # Heroku antigo usa postgres://, SQLAlchemy espera postgresql://
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def _build_engine(db_path: str | None, db_url: str | None) -> tuple[Engine, str]:
    if db_url:
        normalizada = _normalizar_database_url(db_url)
        return create_engine(normalizada), "DATABASE_URL/--db-url"

    if db_path is None:
        db_path = "instance/dev.db"

    sqlite_url = f"sqlite:///{db_path}"
    return create_engine(sqlite_url), db_path


def gerar_relatorio(engine: Engine, fonte_dados: str, saida: Path) -> tuple[int, int]:
    saida.parent.mkdir(parents=True, exist_ok=True)

    insp = inspect(engine)
    if not insp.has_table("medicamento"):
        with saida.open("w", encoding="utf-8") as f:
            _escrever_cabecalho(f, fonte_dados)
            f.write("\n")
            f.write("⚠️ A tabela `medicamento` não foi encontrada nesta base.\n")
            f.write(
                "Não foi possível listar registros com campos incompletos porque a base atual está sem schema/dados desse módulo.\n"
            )
        return 0, 0

    campos_select = ", ".join(["id", "nome", *CAMPOS_ANALISADOS])
    query = text(f"SELECT {campos_select} FROM medicamento ORDER BY id")

    with engine.connect() as conn:
        rows = [dict(row._mapping) for row in conn.execute(query)]

    incompletos: list[tuple[int, str, list[str]]] = []
    for row in rows:
        faltantes = [campo for campo in CAMPOS_ANALISADOS if _is_incompleto(row.get(campo))]
        if faltantes:
            incompletos.append((row["id"], row["nome"], faltantes))

    with saida.open("w", encoding="utf-8") as f:
        _escrever_cabecalho(f, fonte_dados)
        f.write(f"- Total de medicamentos avaliados: **{len(rows)}**\n")
        f.write(f"- Medicamentos com ao menos um campo incompleto: **{len(incompletos)}**\n\n")

        if not incompletos:
            f.write("Nenhum medicamento com campos incompletos foi encontrado.\n")
        else:
            f.write("| ID | Nome | Campos incompletos |\n")
            f.write("|---:|---|---|\n")
            for med_id, nome, faltantes in incompletos:
                f.write(f"| {med_id} | {nome} | {', '.join(faltantes)} |\n")

    return len(rows), len(incompletos)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="instance/dev.db", help="Caminho do banco SQLite")
    parser.add_argument(
        "--db-url",
        default=None,
        help="URL de conexão completa (ex.: postgres://... ou postgresql://...). Se omitida, usa DATABASE_URL.",
    )
    parser.add_argument(
        "--out",
        default="reports/relatorio_medicamentos_incompletos.md",
        help="Arquivo de saída do relatório",
    )
    args = parser.parse_args()

    db_url = args.db_url or os.getenv("DATABASE_URL")
    engine, fonte_dados = _build_engine(args.db, db_url)

    total, incompletos = gerar_relatorio(engine, fonte_dados, Path(args.out))
    print(f"Relatório gerado em {args.out} | avaliados={total} | com pendência={incompletos}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
