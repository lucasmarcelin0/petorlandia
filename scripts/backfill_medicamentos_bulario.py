"""
Snapshot + limpeza seletiva de apresentações/doses do bulário.

Uso típico:
  python scripts/backfill_medicamentos_bulario.py --dry-run --med-id 1587 --med-id 2246
  python scripts/backfill_medicamentos_bulario.py --apply   --med-id 1587 --med-id 2246

Fluxo recomendado:
  1) rodar este script em --dry-run para gerar um snapshot JSON
  2) rodar em --apply para limpar apenas `apresentacao_medicamento` e
     `dose_medicamento` dos medicamentos-alvo
  3) reimportar os alvos com `scripts/importar_medicamentos_vetsmart.py`

Importante:
  - este script NÃO apaga a linha de `medicamento`
  - este script NÃO mexe em prescrições/histórico
  - o snapshot é salvo em `outputs/bulario_backfill/`
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

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

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "bulario_backfill"


@dataclass
class BackfillSummary:
    medicamentos: int
    apresentacoes: int
    doses: int


def _json_default(obj: Any):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Tipo não serializável: {type(obj)!r}")


def conectar():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=15)
    conn.autocommit = False
    return conn


def buscar_medicamentos(cur, med_ids: List[int]) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT id, nome, principio_ativo, classificacao, via_administracao,
               dosagem_recomendada, frequencia, duracao_tratamento,
               observacoes, bula, vetsmart_produto_id, created_by
          FROM medicamento
         WHERE id = ANY(%s)
         ORDER BY nome
        """,
        (med_ids,),
    )
    return [dict(r) for r in cur.fetchall()]


def buscar_apresentacoes(cur, med_ids: List[int]) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT *
          FROM apresentacao_medicamento
         WHERE medicamento_id = ANY(%s)
         ORDER BY medicamento_id, fabricante NULLS LAST, forma, concentracao
        """,
        (med_ids,),
    )
    return [dict(r) for r in cur.fetchall()]


def buscar_doses(cur, med_ids: List[int]) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT *
          FROM dose_medicamento
         WHERE medicamento_id = ANY(%s)
         ORDER BY medicamento_id, indicacao NULLS FIRST, id
        """,
        (med_ids,),
    )
    return [dict(r) for r in cur.fetchall()]


def montar_snapshot(cur, med_ids: List[int]) -> Dict[str, Any]:
    meds = buscar_medicamentos(cur, med_ids)
    if len(meds) != len(set(med_ids)):
        encontrados = {m["id"] for m in meds}
        faltantes = [m for m in med_ids if m not in encontrados]
        raise SystemExit(f"Medicamentos não encontrados: {faltantes}")

    apres = buscar_apresentacoes(cur, med_ids)
    doses = buscar_doses(cur, med_ids)

    apres_por_med: Dict[int, List[Dict[str, Any]]] = {}
    for ap in apres:
        apres_por_med.setdefault(ap["medicamento_id"], []).append(ap)

    doses_por_med: Dict[int, List[Dict[str, Any]]] = {}
    for dose in doses:
        doses_por_med.setdefault(dose["medicamento_id"], []).append(dose)

    itens = []
    for med in meds:
        itens.append(
            {
                "medicamento": med,
                "apresentacoes": apres_por_med.get(med["id"], []),
                "doses": doses_por_med.get(med["id"], []),
            }
        )

    return {
        "created_at": datetime.now().isoformat(),
        "med_ids": med_ids,
        "items": itens,
    }


def salvar_snapshot(snapshot: Dict[str, Any]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUT_DIR / f"snapshot_{stamp}.json"
    path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return path


def resumir(snapshot: Dict[str, Any]) -> BackfillSummary:
    meds = snapshot["items"]
    return BackfillSummary(
        medicamentos=len(meds),
        apresentacoes=sum(len(item["apresentacoes"]) for item in meds),
        doses=sum(len(item["doses"]) for item in meds),
    )


def imprimir_resumo(snapshot: Dict[str, Any]) -> None:
    summary = resumir(snapshot)
    print("=" * 72)
    print("Snapshot do Bulário")
    print("=" * 72)
    print(f"Medicamentos:  {summary.medicamentos}")
    print(f"Apresentações: {summary.apresentacoes}")
    print(f"Doses:         {summary.doses}")
    print("")
    for item in snapshot["items"]:
        med = item["medicamento"]
        print(
            f"[{med['id']}] {med['nome']} | PA={med.get('principio_ativo') or '-'} "
            f"| apres={len(item['apresentacoes'])} | doses={len(item['doses'])}"
        )
    print("=" * 72)


def limpar_filhos(cur, med_ids: List[int]) -> Dict[str, int]:
    cur.execute(
        "DELETE FROM dose_medicamento WHERE medicamento_id = ANY(%s)",
        (med_ids,),
    )
    doses = cur.rowcount
    cur.execute(
        "DELETE FROM apresentacao_medicamento WHERE medicamento_id = ANY(%s)",
        (med_ids,),
    )
    apres = cur.rowcount
    return {"doses": doses, "apresentacoes": apres}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Só gera snapshot e mostra o que seria limpo.")
    mode.add_argument("--apply", action="store_true", help="Aplica a limpeza das tabelas-filhas.")
    parser.add_argument(
        "--med-id",
        action="append",
        dest="med_ids",
        type=int,
        required=True,
        help="ID do medicamento alvo. Repita a flag para múltiplos IDs.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    med_ids = sorted(set(args.med_ids))

    conn = conectar()
    try:
        with conn.cursor() as cur:
            snapshot = montar_snapshot(cur, med_ids)
            snapshot_path = salvar_snapshot(snapshot)
            imprimir_resumo(snapshot)
            print(f"Snapshot salvo em: {snapshot_path}")

            if args.dry_run:
                print("")
                print("Modo dry-run: nenhuma linha foi apagada.")
                print("Se o snapshot estiver correto, rode novamente com --apply.")
                conn.rollback()
                return

            resultado = limpar_filhos(cur, med_ids)
            conn.commit()
            print("")
            print("Limpeza aplicada com sucesso.")
            print(f"Doses removidas:         {resultado['doses']}")
            print(f"Apresentações removidas: {resultado['apresentacoes']}")
            print("")
            print("Próximo passo: reimportar os alvos com o script do VetSmart.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
