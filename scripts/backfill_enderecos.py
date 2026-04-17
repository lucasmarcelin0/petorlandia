"""
backfill_enderecos.py
=====================
Atualiza tutores já migrados do VetSmart com dados que faltavam na
primeira migração:
  - User.address (string legível montada dos campos estruturados)
  - User.endereco_id (registro Endereco com rua, número, bairro, etc.)
  - User.date_of_birth
  - User.rg

Lê os dados brutos do checkpoint scripts/vetsmart_raw/tutores.json
e cruza com os Users existentes no banco por CPF ou e-mail.

Uso:
  cd <raiz do projeto>
  python scripts/backfill_enderecos.py [--dry-run]
"""

import sys
import json
import argparse
import logging
from pathlib import Path

RAW_FILE = Path(__file__).parent / "vetsmart_raw" / "tutores.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):
        if v.get("__type") == "Date":
            return v.get("iso", "")
        return str(v)
    return str(v)


def _date(v):
    if not v:
        return None
    from datetime import datetime
    iso = v.get("iso", v) if isinstance(v, dict) else v
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).date()
    except Exception:
        return None


def _build_address_string(vs: dict) -> str:
    parts = []
    street      = _str(vs.get("addressStreet") or "").strip()
    number      = _str(vs.get("addressNumber") or "").strip()
    complement  = _str(vs.get("addressComplement") or "").strip()
    neighborhood= _str(vs.get("neighborhood") or "").strip()
    city        = _str(vs.get("city") or "").strip()
    state       = _str(vs.get("stateId") or "").strip()
    zipcode     = _str(vs.get("zipCode") or "").strip()

    if street:
        parts.append(f"{street}, {number}" if number else street)
    elif number:
        parts.append(f"Nº {number}")
    if complement:
        parts.append(complement)
    if neighborhood:
        parts.append(neighborhood)
    if city and state:
        parts.append(f"{city}/{state}")
    elif city:
        parts.append(city)
    if zipcode:
        parts.append(f"CEP {zipcode}")
    return " – ".join(parts)


# ─── main ─────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False):
    if not RAW_FILE.exists():
        log.error("Arquivo não encontrado: %s", RAW_FILE)
        sys.exit(1)

    tutores = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    log.info("Carregados %d tutores do checkpoint.", len(tutores))

    # Bootstrap Flask
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app_factory import create_app
    from extensions import db
    from models.base import User, Endereco

    app = create_app()
    with app.app_context():
        updated = 0
        endereco_criados = 0
        sem_match = 0

        for vs in tutores:
            # Monta campos
            cpf   = _str(vs.get("cpf") or "").replace(".", "").replace("-", "") or None
            email = _str(vs.get("email") or vs.get("ownerEmail") or "").lower().strip() or None

            addr_street    = _str(vs.get("addressStreet") or "").strip()
            addr_number    = _str(vs.get("addressNumber") or "").strip()
            addr_complement= _str(vs.get("addressComplement") or "").strip()
            addr_bairro    = _str(vs.get("neighborhood") or "").strip()
            addr_city      = _str(vs.get("city") or "").strip()
            addr_state     = _str(vs.get("stateId") or "").strip()
            addr_cep       = _str(vs.get("zipCode") or "").strip()
            has_address    = bool(addr_street or addr_city or addr_cep)

            address_str    = _build_address_string(vs)
            dob            = _date(vs.get("birthdate") or vs.get("birthday"))
            rg             = _str(vs.get("rg") or "").strip() or None

            # Nada para atualizar?
            if not has_address and not dob and not rg:
                continue

            # Encontra o User no banco
            user = None
            if cpf:
                user = User.query.filter_by(cpf=cpf).first()
            if not user and email:
                user = User.query.filter_by(email=email).first()

            if not user:
                log.warning("  ⚠ Sem match para tutor '%s' (cpf=%s, email=%s)",
                            vs.get("name"), cpf, email)
                sem_match += 1
                continue

            changed = False

            # Atualiza date_of_birth se estiver vazio
            if dob and not user.date_of_birth:
                if not dry_run:
                    user.date_of_birth = dob
                changed = True

            # Atualiza RG se estiver vazio
            if rg and not user.rg:
                if not dry_run:
                    user.rg = rg
                changed = True

            # Atualiza endereço
            if has_address:
                # Atualiza User.address sempre se estiver vazio ou diferente
                if not user.address or user.address != address_str:
                    if not dry_run:
                        user.address = address_str
                    changed = True

                # Cria Endereco estruturado se ainda não existe
                if not user.endereco_id:
                    if not dry_run:
                        endereco = Endereco(
                            cep         = addr_cep or "",
                            rua         = addr_street or None,
                            numero      = addr_number or None,
                            complemento = addr_complement or None,
                            bairro      = addr_bairro or None,
                            cidade      = addr_city or None,
                            estado      = addr_state or None,
                        )
                        db.session.add(endereco)
                        db.session.flush()
                        user.endereco_id = endereco.id
                        endereco_criados += 1
                    else:
                        log.info("  [DRY-RUN] Criaria Endereco para '%s': %s", user.name, address_str)
                    changed = True

            if changed:
                updated += 1
                log.info("  ✔ Atualizado: %s (id=%d)%s",
                         user.name, user.id,
                         f" → {address_str}" if has_address else "")

        if not dry_run:
            db.session.commit()
            log.info("\n✅ Commit realizado.")

        log.info("=" * 55)
        log.info("Tutores atualizados : %d", updated)
        log.info("Endereços criados   : %d", endereco_criados)
        log.info("Sem match no banco  : %d", sem_match)
        log.info("=" * 55)
        if dry_run:
            log.info("(modo --dry-run: nenhuma alteração foi gravada)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill de endereços de tutores VetSmart")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simula sem gravar no banco")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
