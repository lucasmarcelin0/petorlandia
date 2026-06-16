"""Backfill nome_comercial para apresentações de medicamentos com nome comercial conhecido.

Preenche ApresentacaoMedicamento.nome_comercial para marcas específicas cujas
apresentações já estão cadastradas no banco.

Regras iniciais:
  Medicamento: Metergolina
  Fabricante:  Agener  (apresentações 0,5 mg e 2 mg comprimido)
  nome_comercial → 'Sec Lac'

Execute via:
  heroku run python scripts/backfill_nome_comercial.py           # dry-run
  heroku run "python scripts/backfill_nome_comercial.py --apply" # aplica
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from extensions import db
from models.base import Medicamento, ApresentacaoMedicamento

# (medicamento_nome_ilike, fabricante_ilike, nome_comercial)
REGRAS = [
    ('Metergolina', 'Agener', 'Sec Lac'),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Persiste as alterações (padrão: só simula)")
    args = parser.parse_args()

    with app.app_context():
        total_alterados = 0
        for med_nome, fab_like, nome_comercial in REGRAS:
            med = Medicamento.query.filter(
                Medicamento.nome.ilike(med_nome)
            ).first()
            if not med:
                print(f"  ⚠  Medicamento '{med_nome}' não encontrado — pulando.")
                continue

            candidatas = [
                ap for ap in (med.apresentacoes or [])
                if fab_like.lower() in (ap.fabricante or '').lower()
            ]

            if not candidatas:
                print(f"  ⚠  Nenhuma apresentação de '{med_nome}' com fabricante='{fab_like}' — pulando.")
                continue

            for ap in candidatas:
                status = "(já correto)" if ap.nome_comercial == nome_comercial else "(ATUALIZAR)"
                print(
                    f"  AP id={ap.id}: {ap.concentracao_valor!r} {ap.concentracao_unidade!r} "
                    f"{ap.forma!r} fab={ap.fabricante!r} nome_comercial={ap.nome_comercial!r} → '{nome_comercial}' {status}"
                )
                if args.apply and ap.nome_comercial != nome_comercial:
                    ap.nome_comercial = nome_comercial
                    total_alterados += 1

        if args.apply:
            db.session.commit()
            print(f"\n✓ {total_alterados} apresentação(ões) atualizada(s).")
        else:
            print("\n⚠  SIMULAÇÃO — rode com --apply para persistir.")


if __name__ == "__main__":
    main()
