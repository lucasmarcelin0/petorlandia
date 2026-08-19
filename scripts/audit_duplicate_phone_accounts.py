"""
audit_duplicate_phone_accounts.py
=================================
Lista os celulares que apontam para mais de uma conta - a situacao em que o
login e o primeiro acesso nao conseguem desempatar sozinhos ("Ha mais de uma
conta com este celular").

Para cada telefone mostra as contas, se o e-mail e provisorio da campanha
(@petorlandia.local, que a pessoa nao conhece e portanto nao serve como saida)
e as visitas PMO ligadas a cada conta.

E somente leitura: nao altera nada no banco.

Uso:
  python scripts/audit_duplicate_phone_accounts.py
  python scripts/audit_duplicate_phone_accounts.py --nome "marcia"
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def run(nome: str | None = None) -> int:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app_factory import create_app
    from models import PmoVaccinationVisit, User
    from services.vacina_pmo_service import _normalize_login_phone, _same_person_name

    app = create_app()
    with app.app_context():
        por_telefone: dict[str, list[User]] = defaultdict(list)
        for user in User.query.filter(User.phone.isnot(None), User.phone != "").all():
            normalizado = _normalize_login_phone(user.phone)
            if normalizado:
                por_telefone[normalizado].append(user)

        duplicados = {
            telefone: sorted(contas, key=lambda u: u.id)
            for telefone, contas in por_telefone.items()
            if len(contas) > 1
        }
        if nome:
            alvo = nome.strip().lower()
            duplicados = {
                telefone: contas
                for telefone, contas in duplicados.items()
                if any(alvo in (conta.name or "").lower() for conta in contas)
            }

        log.info("Telefones com mais de uma conta: %s", len(duplicados))
        mesmo_nome = 0
        for telefone, contas in sorted(duplicados.items()):
            nomes_iguais = any(
                _same_person_name(a.name, b.name)
                for i, a in enumerate(contas)
                for b in contas[i + 1 :]
            )
            if nomes_iguais:
                mesmo_nome += 1
            log.info("")
            log.info("%s%s", telefone, "  <- mesma pessoa duplicada" if nomes_iguais else "")
            for conta in contas:
                visitas = PmoVaccinationVisit.query.filter_by(tutor_user_id=conta.id).count()
                provisorio = (conta.email or "").endswith("@petorlandia.local")
                log.info(
                    "  #%-6s %-40s %-45s %s visita(s) PMO%s",
                    conta.id,
                    (conta.name or "")[:40],
                    (conta.email or "")[:45],
                    visitas,
                    "  [e-mail provisorio]" if provisorio else "",
                )

        log.info("")
        log.info("Provavel duplicacao da mesma pessoa: %s telefone(s)", mesmo_nome)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nome", help="filtra pelos telefones cujas contas contenham este nome")
    args = parser.parse_args()
    return run(nome=args.nome)


if __name__ == "__main__":
    raise SystemExit(main())
