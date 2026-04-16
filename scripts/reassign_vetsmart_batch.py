from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_factory import create_app
from extensions import db
from models.base import Animal, Clinica, Consulta, Prescricao, User, Vacina
from scripts.migrate_vetsmart import _dt, transform_consulta, transform_prescricao, transform_vacina


RAW_DIR = Path("scripts/vetsmart_raw")
LOG_PATH = Path("scripts/migrate_vetsmart.log")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reatribui o ultimo lote VetSmart importado para outra clinica/usuario."
    )
    parser.add_argument("--target-clinic-id", type=int, required=True)
    parser.add_argument("--target-user-id", type=int, required=True)
    parser.add_argument("--source-clinic-id", type=int, default=100)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    return parser.parse_args()


def load_raw() -> dict:
    raw = {}
    for name in ("tutores", "animais", "consultas", "prescricoes", "vacinas"):
        raw[name] = json.loads((RAW_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return raw


def parse_latest_batch(log_path: Path) -> tuple[int, list[tuple[str, int]], list[int]]:
    lines = log_path.read_text(encoding="utf-8").splitlines()
    start = None

    for index, line in enumerate(lines):
        if "Usuário sentinela criado" in line or "UsuÃ¡rio sentinela criado" in line:
            start = index

    if start is None:
        raise RuntimeError("Nao encontrei um lote VetSmart no log.")

    end = None
    for index in range(start, len(lines)):
        if "MIGRAÇÃO CONCLUÍDA!" in lines[index] or "MIGRAÃ‡ÃƒO CONCLUÃDA!" in lines[index]:
            end = index
            break

    if end is None:
        raise RuntimeError("Nao encontrei o fim do ultimo lote no log.")

    batch_lines = lines[start : end + 1]
    sentinel_id = None
    tutor_events: list[tuple[str, int]] = []
    animal_ids: list[int] = []

    for line in batch_lines:
        sentinel_match = re.search(r"sentinela criado: .* \(id=(\d+)\)", line)
        if sentinel_match:
            sentinel_id = int(sentinel_match.group(1))
            continue

        tutor_match = re.search(r" Tutor(?P<label> reconciliado por [^:]+)?: .* → id=(\d+)", line)
        if tutor_match:
            event_type = "reconciled" if tutor_match.group("label") else "created"
            tutor_events.append((event_type, int(tutor_match.group(2))))
            continue

        animal_match = re.search(r" Animal: .* → id=(\d+)", line)
        if animal_match:
            animal_ids.append(int(animal_match.group(1)))

    if sentinel_id is None:
        raise RuntimeError("Nao consegui identificar o usuario sentinela do ultimo lote.")

    return sentinel_id, tutor_events, animal_ids


def build_animal_id_map(raw_animals: list[dict], animal_ids: list[int]) -> dict[str, int]:
    if len(raw_animals) != len(animal_ids):
        raise RuntimeError(
            f"Quantidade de animais no raw ({len(raw_animals)}) diferente do lote ({len(animal_ids)})."
        )
    return {
        raw_animal.get("objectId", f"animal_{index}"): animal_id
        for index, (raw_animal, animal_id) in enumerate(zip(raw_animals, animal_ids), 1)
    }


def reassign_batch(
    *,
    target_clinic_id: int,
    target_user_id: int,
    source_clinic_id: int,
    sentinel_id: int,
    tutor_events: list[tuple[str, int]],
    animal_ids: list[int],
    raw: dict,
) -> None:
    app = create_app()
    with app.app_context():
        clinic = db.session.get(Clinica, target_clinic_id)
        user = db.session.get(User, target_user_id)
        sentinel = db.session.get(User, sentinel_id)

        if clinic is None:
            raise RuntimeError(f"Clinica destino nao encontrada: {target_clinic_id}")
        if user is None:
            raise RuntimeError(f"Usuario destino nao encontrado: {target_user_id}")

        if len(raw["tutores"]) != len(tutor_events):
            raise RuntimeError(
                f"Quantidade de tutores no raw ({len(raw['tutores'])}) diferente do lote ({len(tutor_events)})."
            )

        for raw_tutor, (_, tutor_id) in zip(raw["tutores"], tutor_events):
            tutor = db.session.get(User, tutor_id)
            if tutor is None:
                raise RuntimeError(f"Tutor nao encontrado no banco: {tutor_id}")

            tutor.clinica_id = target_clinic_id
            tutor.added_by_id = target_user_id
            tutor.is_private = True

            source_created_at = _dt(
                raw_tutor.get("createdAt") or raw_tutor.get("changedAt") or raw_tutor.get("updatedAt")
            )
            if source_created_at:
                tutor.created_at = source_created_at

        animal_id_map = build_animal_id_map(raw["animais"], animal_ids)

        for raw_animal, animal_id in zip(raw["animais"], animal_ids):
            animal = db.session.get(Animal, animal_id)
            if animal is None:
                raise RuntimeError(f"Animal nao encontrado no banco: {animal_id}")

            animal.clinica_id = target_clinic_id
            animal.added_by_id = target_user_id
            source_date_added = _dt(
                raw_animal.get("createdAt") or raw_animal.get("changedAt") or raw_animal.get("updatedAt")
            )
            if source_date_added:
                animal.date_added = source_date_added

        consultas = (
            Consulta.query
            .filter(Consulta.animal_id.in_(animal_ids))
            .filter(Consulta.created_by == sentinel_id)
            .order_by(Consulta.id)
            .all()
        )
        if len(consultas) != len(raw["consultas"]):
            raise RuntimeError(
                f"Quantidade de consultas no banco ({len(consultas)}) diferente do raw ({len(raw['consultas'])})."
            )

        for consulta, raw_consulta in zip(consultas, raw["consultas"]):
            transformed = transform_consulta(raw_consulta, consulta.animal_id, target_user_id, target_clinic_id)
            consulta.clinica_id = target_clinic_id
            consulta.created_by = target_user_id
            consulta.created_at = transformed["created_at"] or consulta.created_at
            consulta.queixa_principal = transformed["queixa_principal"]
            consulta.historico_clinico = transformed["historico_clinico"]
            consulta.exame_fisico = transformed["exame_fisico"]
            consulta.conduta = transformed["conduta"]
            consulta.exames_solicitados = transformed["exames_solicitados"]
            consulta.prescricao = transformed["prescricao"]
            consulta.finalizada_em = transformed["finalizada_em"]

        expected_prescriptions = []
        for raw_prescricao in raw["prescricoes"]:
            patient = raw_prescricao.get("patient") or raw_prescricao.get("animal") or {}
            animal_vs_id = patient.get("objectId") if isinstance(patient, dict) else None
            animal_id = animal_id_map.get(animal_vs_id)
            if animal_id is None:
                continue
            expected_prescriptions.extend(transform_prescricao(raw_prescricao, animal_id))

        prescricoes = (
            Prescricao.query
            .filter(Prescricao.animal_id.in_(animal_ids))
            .order_by(Prescricao.id)
            .all()
        )
        if len(prescricoes) != len(expected_prescriptions):
            raise RuntimeError(
                f"Quantidade de prescricoes no banco ({len(prescricoes)}) diferente do esperado ({len(expected_prescriptions)})."
            )

        for prescricao, transformed in zip(prescricoes, expected_prescriptions):
            prescricao.animal_id = transformed["animal_id"]
            prescricao.medicamento = transformed["medicamento"]
            prescricao.dosagem = transformed["dosagem"]
            prescricao.frequencia = transformed["frequencia"]
            prescricao.duracao = transformed["duracao"]
            prescricao.observacoes = transformed["observacoes"]
            prescricao.data_prescricao = transformed["data_prescricao"] or prescricao.data_prescricao

        vacinas = (
            Vacina.query
            .filter(Vacina.animal_id.in_(animal_ids))
            .order_by(Vacina.id)
            .all()
        )
        if len(vacinas) != len(raw["vacinas"]):
            raise RuntimeError(
                f"Quantidade de vacinas no banco ({len(vacinas)}) diferente do raw ({len(raw['vacinas'])})."
            )

        for vacina, raw_vacina in zip(vacinas, raw["vacinas"]):
            patient = raw_vacina.get("patient") or raw_vacina.get("animal") or {}
            animal_vs_id = patient.get("objectId") if isinstance(patient, dict) else None
            animal_id = animal_id_map.get(animal_vs_id)
            if animal_id is None:
                raise RuntimeError("Vacina sem animal correspondente no mapa.")
            transformed = transform_vacina(raw_vacina, animal_id, target_user_id)
            vacina.animal_id = animal_id
            vacina.nome = transformed["nome"]
            vacina.fabricante = transformed["fabricante"]
            vacina.aplicada = transformed["aplicada"]
            vacina.aplicada_em = transformed["aplicada_em"]
            vacina.aplicada_por = target_user_id
            vacina.created_by = target_user_id
            vacina.observacoes = transformed["observacoes"]

        if sentinel is not None:
            db.session.delete(sentinel)

        db.session.commit()

        remaining_source_users = User.query.filter_by(clinica_id=source_clinic_id).count()
        remaining_source_animals = Animal.query.filter_by(clinica_id=source_clinic_id).count()
        print(
            "reassigned",
            f"clinic={clinic.id}",
            f"user={user.id}",
            f"remaining_source_users={remaining_source_users}",
            f"remaining_source_animals={remaining_source_animals}",
        )


def main() -> int:
    args = parse_args()
    raw = load_raw()
    sentinel_id, tutor_events, animal_ids = parse_latest_batch(args.log_path)
    reassign_batch(
        target_clinic_id=args.target_clinic_id,
        target_user_id=args.target_user_id,
        source_clinic_id=args.source_clinic_id,
        sentinel_id=sentinel_id,
        tutor_events=tutor_events,
        animal_ids=animal_ids,
        raw=raw,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
