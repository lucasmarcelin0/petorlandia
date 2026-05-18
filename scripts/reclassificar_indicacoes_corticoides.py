"""Reclassifica indicações genéricas de doses em corticosteroides.

Uso:
  python scripts/reclassificar_indicacoes_corticoides.py --filtro-nome prednisolona --dry-run
  python scripts/reclassificar_indicacoes_corticoides.py --filtro-nome prednisolona
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from app import app, db  # noqa: E402
from models.base import Medicamento  # noqa: E402
import importar_medicamentos_vetsmart as scraper  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--filtro-nome', default='prednisolona')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    alterados = 0
    with app.app_context():
        meds = (
            Medicamento.query
            .filter(Medicamento.nome.ilike(f"%{args.filtro_nome}%"))
            .order_by(Medicamento.id.asc())
            .all()
        )
        print(f"Medicamentos encontrados: {len(meds)}")
        for med in meds:
            ce = med.conteudo_estruturado or {}
            raw = ce.get('raw_sections') or {}
            indicacoes_texto = raw.get('IndicaÃ§Ãµes e contraindicaÃ§Ãµes') or getattr(med, 'observacoes', None) or ''
            for dose in (med.doses or []):
                nova = scraper._refinar_indicacao_dose(  # noqa: SLF001
                    dose.indicacao,
                    linha=dose.dose_raw_text or dose.dose or '',
                    seg_txt=dose.dose_raw_text or dose.dose or '',
                    frequencia_texto=dose.frequencia,
                    duracao_texto=dose.duracao,
                    indicacoes_texto=indicacoes_texto,
                    classificacao=med.classificacao,
                )
                atual = (dose.indicacao or None)
                if nova != atual:
                    alterados += 1
                    print(f"[{med.id}] {med.nome} dose#{dose.id}: {atual!r} -> {nova!r}")
                    if not args.dry_run:
                        dose.indicacao = nova
        if args.dry_run:
            db.session.rollback()
            print(f"[DRY-RUN] Alterações propostas: {alterados}")
        else:
            db.session.commit()
            print(f"Alterações gravadas: {alterados}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
