"""
backfill_prescricoes.py
=======================
Reimporta as prescrições do VetSmart com os dados que faltavam na primeira
migração:

  - frequencia  → extraída de dosageData.interval + intervalUnit
  - duracao     → extraída de dosageData.duration + durationUnit
  - medicamento → agora inclui dosageForm (ex: "Amoxicilina – 500 mg, comprimido")
  - observacoes → inclui via de administração (usage) e tipo (humana/vet)
  - notes gerais da prescrição → vão para BlocoPrescricao.instrucoes_gerais
  - prescriptionType="1" → marcado como Receituário Especial/Controlado
  - Cada prescrição VetSmart agora cria um BlocoPrescricao, agrupando os
    medicamentos que pertencem à mesma receita

ATENÇÃO: Este script apaga todos os registros de Prescricao e BlocoPrescricao
dos animais importados do VetSmart e os reimporta do checkpoint JSON.
Confirme antes de executar sem --dry-run.

Uso:
  cd <raiz do projeto>
  python scripts/backfill_prescricoes.py [--dry-run]
"""

import sys
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path

RAW_DIR = Path(__file__).parent / "vetsmart_raw"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ─── helpers (replicados para não depender do migrate_vetsmart) ───────────────

def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):
        if v.get("__type") == "Date":
            return v.get("iso", "")
        return str(v)
    return str(v)


def _dt(v):
    if not v:
        return None
    iso = v.get("iso", v) if isinstance(v, dict) else v
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return None


def _frequencia(dosage_data: dict) -> str:
    if not dosage_data:
        return ""
    interval = _str(dosage_data.get("interval") or "").strip()
    unit = _str(dosage_data.get("intervalUnit") or "").strip()
    return f"A cada {interval} {unit}" if interval and unit else ""


def _duracao(dosage_data: dict) -> str:
    if not dosage_data:
        return ""
    duration = _str(dosage_data.get("duration") or "").strip()
    unit = _str(dosage_data.get("durationUnit") or "").strip()
    return f"{duration} {unit}" if duration and unit else ""


def transform_prescricao(vs: dict, animal_pet_id: int) -> dict:
    """Mesma lógica do migrate_vetsmart.py corrigido."""
    drugs = vs.get("drugs") or vs.get("medications") or vs.get("medicamentos") or []
    if not drugs and vs.get("drug"):
        drugs = [vs]

    base_date = _dt(
        vs.get("documentDate") or vs.get("createdAt") or
        vs.get("date") or vs.get("updatedAt")
    )

    notas_gerais = _str(vs.get("notes") or "").strip()
    presc_type = _str(vs.get("prescriptionType") or "")
    tipo_label = "Receituário Especial/Controlado" if presc_type == "1" else ""

    instrucoes_parts = []
    if tipo_label:
        instrucoes_parts.append(tipo_label)
    if notas_gerais:
        instrucoes_parts.append(notas_gerais)

    itens = []
    for idx, drug in enumerate(drugs):
        nome = _str(drug.get("drug") or drug.get("name") or drug.get("medicamento") or "").strip()
        if not nome:
            continue

        dosage_form = _str(drug.get("dosageForm") or "").strip()
        medicamento = f"{nome} – {dosage_form}" if dosage_form else nome

        dosagem = _str(drug.get("dosage") or drug.get("dosagem") or "").strip()
        dosage_data = drug.get("dosageData") or {}
        frequencia = _frequencia(dosage_data)
        duracao = _duracao(dosage_data)

        obs_parts = []
        usage = _str(drug.get("usage") or "").strip()
        if usage:
            obs_parts.append(f"Via: {usage}")
        human_or_vet = _str(drug.get("humanOrVet") or "").strip()
        if human_or_vet:
            obs_parts.append(f"Medicamento {human_or_vet}")

        itens.append({
            "medicamento":     medicamento,
            "dosagem":         dosagem,
            "frequencia":      frequencia,
            "duracao":         duracao,
            "observacoes":     " | ".join(obs_parts) or None,
            "data_prescricao": base_date,
        })

    if not itens:
        nome = _str(vs.get("medication") or vs.get("drug") or
                    vs.get("medicamento") or "Importado do VetSmart")
        dosage_data = vs.get("dosageData") or {}
        itens.append({
            "medicamento":     nome,
            "dosagem":         _str(vs.get("dosage") or vs.get("dosagem") or ""),
            "frequencia":      _frequencia(dosage_data),
            "duracao":         _duracao(dosage_data),
            "observacoes":     None,
            "data_prescricao": base_date,
        })

    return {
        "bloco": {
            "animal_id":         animal_pet_id,
            "data_criacao":      base_date,
            "instrucoes_gerais": "\n".join(instrucoes_parts) or None,
        },
        "itens": itens,
    }


# ─── resolução de animal_id (cruza JSON com banco) ────────────────────────────

def _digits(phone: str) -> str:
    """Extrai apenas dígitos de um número de telefone para comparação."""
    return "".join(c for c in (phone or "") if c.isdigit())


def build_animal_id_map(db, User, Animal, tutores_raw, animais_raw):
    """
    Reconstrói o mapa vetsmart_objectId → animal.id cruzando JSON com banco.
    Estratégia de match do tutor (em ordem de prioridade):
      1. CPF
      2. e-mail
      3. telefone (últimos 8 dígitos — ignora DDI/DDD variações)
      4. nome exato (último recurso)
    """
    # Mapa objectId de tutor VetSmart → user.id no banco
    tutor_id_map: dict[str, int] = {}
    sem_match: list[str] = []

    for vs_t in tutores_raw:
        vs_id = vs_t.get("objectId")
        if not vs_id:
            continue

        cpf   = _str(vs_t.get("cpf") or "").replace(".", "").replace("-", "") or None
        email = _str(vs_t.get("email") or vs_t.get("ownerEmail") or "").lower().strip() or None
        phone_raw = _str(vs_t.get("phone") or vs_t.get("cellphone") or
                         vs_t.get("telefone") or vs_t.get("celular") or "")
        phone_digits = _digits(phone_raw)  # ex: "1699117-8591" → "16991178591"
        nome = _str(vs_t.get("name") or "").strip()

        user = None

        # 1. CPF
        if cpf:
            user = User.query.filter_by(cpf=cpf).first()

        # 2. e-mail
        if not user and email:
            user = User.query.filter_by(email=email).first()

        # 3. telefone — compara últimos 8 dígitos para tolerar variações de DDI
        if not user and len(phone_digits) >= 8:
            suffix = phone_digits[-8:]
            # Busca todos os usuários com telefone não nulo e compara os dígitos
            candidatos = User.query.filter(User.phone.isnot(None)).all()
            for c in candidatos:
                if _digits(c.phone or "").endswith(suffix):
                    user = c
                    break

        # 4. nome exato (fallback final — cuidado com homônimos)
        if not user and nome and nome not in ("Sandra", "Tatiane - Jade"):
            user = User.query.filter(
                User.name == nome,
                User.role == "tutor",
            ).first()

        if user:
            tutor_id_map[vs_id] = user.id
        else:
            sem_match.append(f"{nome} [vs={vs_id}]")

    if sem_match:
        import logging
        logging.getLogger(__name__).warning(
            "  Tutores sem match no banco (%d): %s", len(sem_match), ", ".join(sem_match)
        )

    # Mapa objectId de animal VetSmart → animal.id no banco
    animal_id_map: dict[str, int] = {}
    for vs_a in animais_raw:
        vs_id = vs_a.get("objectId")
        if not vs_id:
            continue

        owner_ptr    = vs_a.get("owner") or vs_a.get("tutor") or vs_a.get("client") or {}
        owner_vs_id  = owner_ptr.get("objectId") if isinstance(owner_ptr, dict) else None
        tutor_db_id  = tutor_id_map.get(owner_vs_id)
        nome         = _str(vs_a.get("name") or vs_a.get("nome") or "").strip()

        if not nome:
            continue

        if tutor_db_id:
            animal = Animal.query.filter_by(name=nome, user_id=tutor_db_id).first()
        else:
            # Tutor não mapeado: tenta pelo nome do animal na clínica (menos preciso)
            animal = Animal.query.filter_by(name=nome).first()

        if animal:
            animal_id_map[vs_id] = animal.id

    return animal_id_map


# ─── main ─────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False):
    for fname in ("prescricoes.json", "tutores.json", "animais.json"):
        if not (RAW_DIR / fname).exists():
            log.error("Arquivo não encontrado: %s", RAW_DIR / fname)
            sys.exit(1)

    prescricoes_raw = json.loads((RAW_DIR / "prescricoes.json").read_text(encoding="utf-8"))
    tutores_raw     = json.loads((RAW_DIR / "tutores.json").read_text(encoding="utf-8"))
    animais_raw     = json.loads((RAW_DIR / "animais.json").read_text(encoding="utf-8"))

    log.info("Checkpoints: %d prescrições | %d tutores | %d animais",
             len(prescricoes_raw), len(tutores_raw), len(animais_raw))

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app_factory import create_app
    from extensions import db
    from models.base import User, Animal, Prescricao, BlocoPrescricao, Clinica

    app = create_app()
    with app.app_context():
        # Seleção interativa de clínica
        clinicas = Clinica.query.order_by(Clinica.nome).all()
        if not clinicas:
            log.error("Nenhuma clínica encontrada no banco.")
            sys.exit(1)

        if len(clinicas) == 1:
            clinica = clinicas[0]
            log.info("Clínica (única): %s (id=%d)", clinica.nome, clinica.id)
        else:
            print("\n🏥 Selecione a CLÍNICA cujas prescrições serão reimportadas:")
            for i, c in enumerate(clinicas, 1):
                print(f"  [{i}] (id={c.id}) {c.nome}")
            while True:
                resp = input(f"  Escolha [1-{len(clinicas)}]: ").strip()
                if resp.isdigit() and 1 <= int(resp) <= len(clinicas):
                    clinica = clinicas[int(resp) - 1]
                    log.info("Clínica selecionada: %s (id=%d)", clinica.nome, clinica.id)
                    break
                print("  Entrada inválida.")

        # Seleção interativa de veterinário
        vets = User.query.filter(
            User.role.in_(["veterinario", "admin"]),
            User.clinica_id == clinica.id,
        ).order_by(User.name).all()
        if not vets:
            vets = User.query.filter_by(clinica_id=clinica.id).order_by(User.name).all()

        if not vets:
            log.error("Nenhum usuário encontrado para a clínica selecionada.")
            sys.exit(1)

        if len(vets) == 1:
            vet = vets[0]
            log.info("Veterinário (único): %s (id=%d)", vet.name, vet.id)
        else:
            print("\n👨‍⚕️ Selecione o VETERINÁRIO responsável pelas prescrições importadas:")
            for i, u in enumerate(vets, 1):
                print(f"  [{i}] (id={u.id}) {u.name} [{u.role}]")
            while True:
                resp = input(f"  Escolha [1-{len(vets)}]: ").strip()
                if resp.isdigit() and 1 <= int(resp) <= len(vets):
                    vet = vets[int(resp) - 1]
                    log.info("Veterinário selecionado: %s (id=%d)", vet.name, vet.id)
                    break
                print("  Entrada inválida.")

        vet_id = vet.id

        # Reconstrói mapa animal VetSmart → DB
        log.info("Construindo mapa de animais...")
        animal_id_map = build_animal_id_map(db, User, Animal, tutores_raw, animais_raw)
        log.info("  %d animais mapeados de %d no JSON", len(animal_id_map), len(animais_raw))

        # Identifica animais a limpar (todos que têm mapeamento)
        animal_db_ids = set(animal_id_map.values())
        log.info("  %d animais únicos no banco serão processados", len(animal_db_ids))

        if not dry_run:
            # Apaga Prescricao e BlocoPrescricao existentes desses animais
            blocos_antigos = BlocoPrescricao.query.filter(
                BlocoPrescricao.animal_id.in_(animal_db_ids)
            ).all()
            prescricoes_antigas = Prescricao.query.filter(
                Prescricao.animal_id.in_(animal_db_ids)
            ).all()
            n_blocos = len(blocos_antigos)
            n_presc = len(prescricoes_antigas)

            for p in prescricoes_antigas:
                db.session.delete(p)
            for b in blocos_antigos:
                db.session.delete(b)
            db.session.flush()
            log.info("  Removidos: %d blocos | %d prescrições antigas", n_blocos, n_presc)
        else:
            n_blocos = BlocoPrescricao.query.filter(BlocoPrescricao.animal_id.in_(animal_db_ids)).count()
            n_presc  = Prescricao.query.filter(Prescricao.animal_id.in_(animal_db_ids)).count()
            log.info("  [DRY-RUN] Removeria: %d blocos | %d prescrições antigas", n_blocos, n_presc)

        # Reimporta com dados corretos
        blocos_criados = 0
        itens_criados = 0
        sem_animal = 0

        for vs_p in prescricoes_raw:
            pat_ptr   = vs_p.get("patient") or vs_p.get("animal") or {}
            animal_vs = pat_ptr.get("objectId") if isinstance(pat_ptr, dict) else None
            if not animal_vs:
                animal_vs = vs_p.get("patientId")

            animal_pet_id = animal_id_map.get(animal_vs)
            if not animal_pet_id:
                log.warning("  ⚠ Prescrição '%s' sem animal mapeado (vs=%s). Pulando.",
                            vs_p.get("objectId"), animal_vs)
                sem_animal += 1
                continue

            resultado = transform_prescricao(vs_p, animal_pet_id)
            itens = resultado["itens"]
            bloco_data = resultado["bloco"]

            if not itens:
                continue

            if dry_run:
                log.info("  [DRY-RUN] Criaria bloco p/ animal id=%d com %d medicamento(s): %s",
                         animal_pet_id, len(itens),
                         " | ".join(i["medicamento"] for i in itens))
                blocos_criados += 1
                itens_criados += len(itens)
                continue

            bloco = BlocoPrescricao(
                animal_id        = animal_pet_id,
                clinica_id       = clinica.id,
                saved_by_id      = vet_id,
                data_criacao     = bloco_data["data_criacao"] or datetime.utcnow(),
                instrucoes_gerais= bloco_data["instrucoes_gerais"],
            )
            db.session.add(bloco)
            db.session.flush()
            blocos_criados += 1

            for item in itens:
                p = Prescricao(
                    bloco_id        = bloco.id,
                    animal_id       = animal_pet_id,
                    medicamento     = item["medicamento"],
                    dosagem         = item["dosagem"],
                    frequencia      = item["frequencia"],
                    duracao         = item["duracao"],
                    observacoes     = item["observacoes"],
                    data_prescricao = item["data_prescricao"] or datetime.utcnow(),
                )
                db.session.add(p)
                itens_criados += 1

        if not dry_run:
            db.session.commit()
            log.info("\n✅ Commit realizado.")

        log.info("=" * 55)
        log.info("Blocos criados      : %d", blocos_criados)
        log.info("Medicamentos criados: %d", itens_criados)
        log.info("Sem animal mapeado  : %d", sem_animal)
        log.info("=" * 55)
        if dry_run:
            log.info("(modo --dry-run: nenhuma alteração foi gravada)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill de prescrições VetSmart")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simula sem gravar no banco")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
