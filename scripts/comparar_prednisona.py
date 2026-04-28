"""
Compara os dados atuais de Prednisona no banco com o que o dry-run do scraper encontrou.
Uso: python scripts/comparar_prednisona.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from models.base import db, Medicamento, DoseMedicamento, ApresentacaoMedicamento

app = create_app()

DRY_RUN = {
    "Prednisona":                   {"doses_scraper": 6,  "apres_scraper": 0, "pa": "Prednisona", "fab": None},
    "Prednisona Animalia Farma Cápsulas": {"doses_scraper": 0,  "apres_scraper": 1, "pa": "Prednisona", "fab": "Animalia Farma"},
    "Prednisona Ligvet":            {"doses_scraper": 9,  "apres_scraper": 5, "pa": "Prednisona", "fab": "LigVet"},
}

with app.app_context():
    meds = (
        db.session.query(Medicamento)
        .filter(Medicamento.nome.ilike("%prednisona%"))
        .order_by(Medicamento.nome)
        .all()
    )

    print(f"\n{'='*80}")
    print(f"  PREDNISONA — banco atual vs dry-run")
    print(f"{'='*80}")
    print(f"{'Medicamento':<42} {'DB doses':>9} {'DRY doses':>9} {'DB apres':>9} {'DRY apres':>10}")
    print(f"{'-'*80}")

    for m in meds:
        doses_db   = db.session.query(DoseMedicamento).filter_by(medicamento_id=m.id).count()
        apres_db   = db.session.query(ApresentacaoMedicamento).filter_by(medicamento_id=m.id).count()
        dry        = DRY_RUN.get(m.nome, {})
        doses_dry  = dry.get("doses_scraper", "?")
        apres_dry  = dry.get("apres_scraper", "?")

        diff_d = ""
        if isinstance(doses_dry, int):
            diff_d = " ✓" if doses_db == doses_dry else f" ← ΔD={doses_dry - doses_db:+d}"
        diff_a = ""
        if isinstance(apres_dry, int):
            diff_a = " ✓" if apres_db == apres_dry else f" ← ΔA={apres_dry - apres_db:+d}"

        print(f"{m.nome:<42} {doses_db:>9} {str(doses_dry):>9}{diff_d:<12} {apres_db:>9} {str(apres_dry):>10}{diff_a}")

    # Detalhe das doses atuais para o medicamento principal
    print(f"\n{'='*80}")
    print("  DOSES ATUAIS — Prednisona (principal)")
    print(f"{'='*80}")
    principal = next((m for m in meds if m.nome == "Prednisona"), None)
    if principal:
        doses = db.session.query(DoseMedicamento).filter_by(medicamento_id=principal.id).all()
        for d in doses:
            print(
                f"  especie={d.especie or '?':10} unidade={d.dose_unidade or '?':20} "
                f"min={d.dose_min} max={d.dose_max} via={d.via_administracao or '?'}"
            )
    else:
        print("  Medicamento 'Prednisona' não encontrado no banco.")

    print()
