"""Cadastra/atualiza o Robson como ultrassonografista público (idempotente).

Garante que o profissional apareça em ``/servicos/ultrassom`` e nos fluxos por
cidade (consultas/exames) cobrindo Belo Horizonte, Contagem e Brumadinho.

Uso (no Heroku, após o deploy):

    python scripts/seed_robson_ultrassom.py
    # ou ajustando dados:
    python scripts/seed_robson_ultrassom.py --crmv "12345" --crmv-uf MG \
        --cidades "Belo Horizonte/MG,Contagem/MG,Brumadinho/MG"

É seguro rodar várias vezes: só adiciona o que estiver faltando.
"""

import argparse

from app_factory import create_app
from extensions import db
from models import Specialty, User, Veterinario, VeterinarioAtendeCidade


DEFAULT_EMAIL = "robson.rs64@gmail.com"
DEFAULT_PHONE = "31994911955"
DEFAULT_SPECIALTY = "Ultrassonografia"
DEFAULT_CIDADES = "Belo Horizonte/MG,Contagem/MG,Brumadinho/MG"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--phone", default=DEFAULT_PHONE)
    parser.add_argument("--specialty", default=DEFAULT_SPECIALTY)
    parser.add_argument(
        "--cidades",
        default=DEFAULT_CIDADES,
        help="Cidades atendidas separadas por vírgula (ex.: 'Belo Horizonte/MG,Contagem/MG').",
    )
    parser.add_argument(
        "--crmv",
        default=None,
        help="CRMV — obrigatório apenas se o Veterinario ainda não existir.",
    )
    parser.add_argument("--crmv-uf", default="MG")
    return parser.parse_args()


def _parse_cidades(raw):
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "/" in part:
            cidade, _, uf = part.rpartition("/")
            cidade, uf = cidade.strip(), uf.strip().upper()
            if len(uf) != 2:
                cidade, uf = part, None
        else:
            cidade, uf = part, None
        if cidade:
            out.append((cidade, uf or None))
    return out


def main():
    args = parse_args()
    app = create_app()
    with app.app_context():
        user = (
            User.query.filter(db.func.lower(User.email) == args.email.lower()).first()
        )
        if user is None:
            raise SystemExit(
                f"Usuário com e-mail {args.email!r} não encontrado. "
                "Confirme o e-mail ou cadastre-o antes de rodar este script."
            )

        vet = getattr(user, "veterinario", None)
        if vet is None:
            if not args.crmv:
                raise SystemExit(
                    "Este usuário ainda não tem perfil de Veterinario. "
                    "Rode novamente passando --crmv \"<numero>\" (e opcionalmente --crmv-uf)."
                )
            vet = Veterinario(user_id=user.id, crmv=args.crmv.strip())
            db.session.add(vet)
            print(f"+ Veterinario criado para {user.name} (CRMV {args.crmv}).")
        else:
            print(f"= Veterinario já existe para {user.name} (CRMV {vet.crmv}).")

        if args.crmv:
            vet.crmv = args.crmv.strip()
        if args.crmv_uf and not vet.crmv_estado:
            vet.crmv_estado = args.crmv_uf.strip().upper()

        # Perfil público
        vet.public_visible = True
        vet.public_profile_type = "profissional"

        # Telefone/WhatsApp (não sobrescreve um número já preenchido)
        if not (user.phone or "").strip():
            user.phone = args.phone
            print(f"+ Telefone definido: {args.phone}.")

        # Especialidade de ultrassonografia
        spec = Specialty.query.filter(
            db.func.lower(Specialty.nome) == args.specialty.lower()
        ).first()
        if spec is None:
            spec = Specialty(nome=args.specialty)
            db.session.add(spec)
            print(f"+ Especialidade criada: {args.specialty}.")
        if spec not in vet.specialties:
            vet.specialties.append(spec)
            print(f"+ Especialidade vinculada: {args.specialty}.")

        # Cidades atendidas (adiciona as que faltarem)
        existing = {
            (c.cidade or "").strip().lower() for c in (vet.cidades_atendidas or [])
        }
        for cidade, uf in _parse_cidades(args.cidades):
            if cidade.strip().lower() not in existing:
                vet.cidades_atendidas.append(
                    VeterinarioAtendeCidade(cidade=cidade, uf=uf)
                )
                existing.add(cidade.strip().lower())
                print(f"+ Cidade adicionada: {cidade}{'/' + uf if uf else ''}.")

        db.session.commit()

        cidades = ", ".join(
            f"{c.cidade}{'/' + c.uf if c.uf else ''}" for c in vet.cidades_atendidas
        )
        print("\nOK — Robson pronto como ultrassonografista público.")
        print(f"  Nome:          {user.name}")
        print(f"  WhatsApp:      {user.phone}")
        print(f"  Especialidades:{', '.join(s.nome for s in vet.specialties)}")
        print(f"  Cidades:       {cidades}")


if __name__ == "__main__":
    main()
