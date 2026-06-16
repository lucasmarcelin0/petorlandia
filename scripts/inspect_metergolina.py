"""Script de inspeção: mostra apresentações e doses da metergolina/Sec Lac e do Meloxicam."""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app import app
from models.base import Medicamento, DoseMedicamento

with app.app_context():
    for term in ['metergolina', 'sec lac', 'meloxicam']:
        meds = Medicamento.query.filter(
            Medicamento.nome.ilike(f'%{term}%') |
            Medicamento.principio_ativo.ilike(f'%{term}%')
        ).all()
        for m in meds:
            print(f"\n=== MED id={m.id} nome={m.nome!r} PA={m.principio_ativo!r} ===")
            print(f"  Apresentacoes ({len(m.apresentacoes or [])}):")
            for ap in (m.apresentacoes or []):
                print(f"    AP id={ap.id} val={ap.concentracao_valor!r} un={ap.concentracao_unidade!r} forma={ap.forma!r} fab={ap.fabricante!r}")
            print(f"  Doses ({len(m.doses or [])}):")
            for d in (m.doses or []):
                print(f"    DOSE id={d.id} esp={d.especie!r} min={d.dose_min!r} max={d.dose_max!r} un={d.dose_unidade!r} ind={d.indicacao!r}")
        if not meds:
            print(f"Nenhum medicamento encontrado para '{term}'")
