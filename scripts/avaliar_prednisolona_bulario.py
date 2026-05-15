"""Avalia a qualidade clínica do bulário para medicamentos com "prednisolona".

Uso:
  python scripts/avaliar_prednisolona_bulario.py
  python scripts/avaliar_prednisolona_bulario.py --peso 8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app
from models.base import Medicamento
from services.bulario import montar_monografia_medicamento, sugerir_dose


def _animal_teste(peso: float):
    return SimpleNamespace(
        peso=peso,
        species=SimpleNamespace(name='Cachorro'),
    )


def _fmt_flags(flags):
    if not flags:
        return 'nenhum'
    return '; '.join(f"{item.get('nivel')}: {item.get('titulo')}" for item in flags)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--peso', type=float, default=8.0)
    args = parser.parse_args()

    with app.app_context():
        meds = (
            Medicamento.query
            .filter(Medicamento.nome.ilike('%prednisolona%'))
            .order_by(Medicamento.nome.asc())
            .all()
        )

        print(f"Medicamentos encontrados: {len(meds)}")
        print(f"Peso de teste: {args.peso} kg")
        print()

        animal = _animal_teste(args.peso)
        for med in meds:
            mono = montar_monografia_medicamento(med)
            sugestao = sugerir_dose(med, animal)
            print(f"[{med.id}] {med.nome}")
            print(f"  Classificação: {med.classificacao or '—'}")
            print(f"  Princípio ativo: {med.principio_ativo or '—'}")
            print(f"  Apresentações: {len(med.apresentacoes or [])}")
            print(f"  Protocolos por espécie: {len(mono['resumo_posologia']['tabs'])}")
            print(f"  Conteúdo clínico estruturado: {'sim' if mono['tem_conteudo_clinico'] else 'não'}")
            if sugestao and not sugestao.get('multiplo'):
                print(f"  Dose sugerida: {sugestao.get('dose_exibir') or '—'}")
                print(f"  Via/frequência/duração: {sugestao.get('via') or '—'} | {sugestao.get('frequencia_texto') or '—'} | {sugestao.get('duracao_texto') or '—'}")
                print(f"  Origem: {(sugestao.get('origem') or {}).get('rotulo') or '—'}")
                print(f"  Requer validação: {'sim' if (sugestao.get('diagnosticos') or {}).get('requer_validacao_clinica') else 'não'}")
                print(f"  Flags: {_fmt_flags(sugestao.get('flags_risco') or [])}")
            elif sugestao and sugestao.get('multiplo'):
                print(f"  Múltiplas indicações: {', '.join(sugestao.get('indicacoes') or [])}")
            else:
                print("  Sem sugestão automática para este peso.")
            print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
