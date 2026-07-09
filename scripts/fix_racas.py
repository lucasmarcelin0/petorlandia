#!/usr/bin/env python3
"""
fix_racas.py — Normaliza e deduplica raças no banco PetOrlândia.

Uso:
    # Ver o que vai mudar (dry-run, padrão):
    DATABASE_URL=<url> python scripts/fix_racas.py

    # Aplicar as correções:
    DATABASE_URL=<url> python scripts/fix_racas.py --apply

    # Só listar as raças atuais com contagem de animais:
    DATABASE_URL=<url> python scripts/fix_racas.py --list

No WSL com variáveis do Heroku:
    heroku config:get DATABASE_URL -a petorlandia | xargs -I{} env DATABASE_URL={} python scripts/fix_racas.py
"""

import os
import re
import sys
import argparse
import unicodedata

import sqlalchemy as sa
from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------------
# Correções manuais de spelling — nome errado → nome correto canônico
# Estas são aplicadas ANTES da deduplicação automática.
# ---------------------------------------------------------------------------
SPELLING_FIXES = {
    # ── Cães ────────────────────────────────────────────────────────────────
    "Labrador Retriver":          "Labrador Retriever",
    "Labrador retriver":          "Labrador Retriever",
    "labrador retriever":         "Labrador Retriever",
    "labrador":                   "Labrador Retriever",
    "Labrador":                   "Labrador Retriever",
    "Golden Retriver":            "Golden Retriever",
    "golden retriever":           "Golden Retriever",
    "Golden retriver":            "Golden Retriever",
    "Poodle Toy":                 "Poodle Toy",
    "poodle":                     "Poodle",
    "POODLE":                     "Poodle",
    "Pastor Alemao":              "Pastor Alemão",
    "pastor alemão":              "Pastor Alemão",
    "pastor alemao":              "Pastor Alemão",
    "Pastor Alemão ":             "Pastor Alemão",
    "Bulldog Frances":            "Bulldog Francês",
    "Bulldog Francês":            "Bulldog Francês",
    "bulldog frances":            "Bulldog Francês",
    "bulldog francês":            "Bulldog Francês",
    "Bulldog Ingles":             "Bulldog Inglês",
    "bulldog inglês":             "Bulldog Inglês",
    "Cocker Spaniel Ingles":      "Cocker Spaniel Inglês",
    "Cocker Spaniel Inglês":      "Cocker Spaniel Inglês",
    "Dachshund (Salsicha)":       "Dachshund",
    "Salsicha":                   "Dachshund",
    "salsicha":                   "Dachshund",
    "Dachshund salsicha":         "Dachshund",
    "Shih Tzu":                   "Shih Tzu",
    "Shih-tzu":                   "Shih Tzu",
    "shih tzu":                   "Shih Tzu",
    "SHIH TZU":                   "Shih Tzu",
    "Yorkshire Terrier":          "Yorkshire Terrier",
    "yorkshire":                  "Yorkshire Terrier",
    "Yorkshire":                  "Yorkshire Terrier",
    "Yorkishire":                 "Yorkshire Terrier",
    "Bichon Frisé":               "Bichon Frisé",
    "Bichon Frise":               "Bichon Frisé",
    "bichon frise":               "Bichon Frisé",
    "Maltese":                    "Maltês",
    "maltese":                    "Maltês",
    "Maltês":                     "Maltês",
    "Maltez":                     "Maltês",
    "Lhasa Apso":                 "Lhasa Apso",
    "lhasa apso":                 "Lhasa Apso",
    "Schnauzer Miniatura":        "Schnauzer Miniatura",
    "schnauzer":                  "Schnauzer",
    "Rottweiler":                 "Rottweiler",
    "rottweiler":                 "Rottweiler",
    "Rotweiler":                  "Rottweiler",
    "Boxer":                      "Boxer",
    "boxer":                      "Boxer",
    "Doberman":                   "Dobermann",
    "doberman":                   "Dobermann",
    "Dobermann":                  "Dobermann",
    "Pit Bull":                   "Pit Bull",
    "Pitbull":                    "Pit Bull",
    "pit bull":                   "Pit Bull",
    "American Pit Bull Terrier":  "Pit Bull",
    "Pit Bull Terrier":           "Pit Bull",
    "Husky Siberiano":            "Husky Siberiano",
    "Husky":                      "Husky Siberiano",
    "Beagle":                     "Beagle",
    "beagle":                     "Beagle",
    "Border Collie":              "Border Collie",
    "border collie":              "Border Collie",
    "Chow Chow":                  "Chow Chow",
    "chow chow":                  "Chow Chow",
    "Spitz Alemao":               "Spitz Alemão",
    "Spitz Alemão":               "Spitz Alemão",
    "spitz alemão":               "Spitz Alemão",
    "Spitz":                      "Spitz Alemão",
    "Pomerania":                  "Spitz Alemão",
    "Pomerânia":                  "Spitz Alemão",
    "lulu da pomerania":          "Spitz Alemão",
    "Lulu da Pomerânia":          "Spitz Alemão",
    "Lulu da Pomerania":          "Spitz Alemão",
    "Pomeranian":                 "Spitz Alemão",
    "SRD":                        "SRD (Sem Raça Definida)",
    "srd":                        "SRD (Sem Raça Definida)",
    "Sem Raça Definida":          "SRD (Sem Raça Definida)",
    "Sem raca definida":          "SRD (Sem Raça Definida)",
    "Vira-lata":                  "SRD (Sem Raça Definida)",
    "Vira lata":                  "SRD (Sem Raça Definida)",
    "viralata":                   "SRD (Sem Raça Definida)",
    "vira lata":                  "SRD (Sem Raça Definida)",
    "Viralata":                   "SRD (Sem Raça Definida)",
    "Mestiço":                    "SRD (Sem Raça Definida)",
    "Mestico":                    "SRD (Sem Raça Definida)",
    "mestiço":                    "SRD (Sem Raça Definida)",
    "Pastor":                     "Pastor Alemão",
    "Akita":                      "Akita",
    "akita":                      "Akita",
    "Pinscher":                   "Pinscher",
    "pinscher":                   "Pinscher",
    "Pinscher Miniatura":         "Pinscher Miniatura",
    "Mini Pinscher":              "Pinscher Miniatura",
    "Minipinscher":               "Pinscher Miniatura",
    "São Bernardo":               "São Bernardo",
    "Sao Bernardo":               "São Bernardo",
    "Dálmata":                    "Dálmata",
    "Dalmata":                    "Dálmata",
    "dalmata":                    "Dálmata",
    "Dalmátia":                   "Dálmata",
    "Cocker":                     "Cocker Spaniel Inglês",
    "Cocker Spaniel":             "Cocker Spaniel Inglês",
    "Weimaraner":                 "Weimaraner",
    "American Bully":             "American Bully",
    "Bully":                      "American Bully",
    "Basset Hound":               "Basset Hound",
    "basset":                     "Basset Hound",
    "Great Dane":                 "Great Dane (Dogue Alemão)",
    "Dogue Alemão":               "Great Dane (Dogue Alemão)",
    "Dogue Alemao":               "Great Dane (Dogue Alemão)",
    "Malinois":                   "Pastor Belga Malinois",
    "Pastor Belga":               "Pastor Belga Malinois",
    "Whippet":                    "Whippet",
    "Cavalier King Charles":      "Cavalier King Charles Spaniel",
    "Cavalier":                   "Cavalier King Charles Spaniel",
    # ── Gatos ───────────────────────────────────────────────────────────────
    "SRD Gato":                   "SRD (Sem Raça Definida)",
    "Gato SRD":                   "SRD (Sem Raça Definida)",
    "Pelo Curto Brasileiro":      "Pelo Curto Brasileiro",
    "Pelo curto brasileiro":      "Pelo Curto Brasileiro",
    "Persa":                      "Persa",
    "persa":                      "Persa",
    "Siamês":                     "Siamês",
    "Siames":                     "Siamês",
    "siamês":                     "Siamês",
    "Maine Coon":                 "Maine Coon",
    "maine coon":                 "Maine Coon",
    "Ragdoll":                    "Ragdoll",
    "ragdoll":                    "Ragdoll",
    "Bengal":                     "Bengalês",
    "Bengalês":                   "Bengalês",
    "British Shorthair":          "British Shorthair",
    "Angorá":                     "Angorá",
    "Angora":                     "Angorá",
    "Scottish Fold":              "Scottish Fold",
    "Sphynx":                     "Sphynx",
    "Abissínio":                  "Abissínio",
    "Abissinio":                  "Abissínio",
    "Buldogue Francês":           "Bulldog Francês",
    "Buldogue francês":           "Bulldog Francês",
    "buldogue frances":           "Bulldog Francês",
}


# ---------------------------------------------------------------------------
# Raças de cachorro cadastradas por engano sob a espécie "Outro" (catálogo
# genérico). IDs levantados manualmente em produção em 2026-07-06 — não é
# detecção automática porque nomes genéricos como "SRD" sob "Outro" são
# ambíguos (podem ser de qualquer espécie) e não devem ser movidos às cegas.
# ---------------------------------------------------------------------------
OUTRO_DOG_BREED_IDS = {
    122, 123, 124, 125, 126, 127, 128, 129, 130, 131,
    132, 133, 134, 135, 136, 137, 138, 139, 140, 141,
}


def normalize_key(name: str) -> str:
    """Remove acentos, lowercase, colapsa espaços — para comparação de duplicatas."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_str).strip().lower()


def best_name(names: list[str]) -> str:
    """Escolhe a versão com mais acentos/maiúsculas (mais 'completa')."""
    def score(n):
        accented = sum(1 for c in n if unicodedata.category(c) == "Ll" and ord(c) > 127)
        uppers = sum(1 for c in n if c.isupper())
        return accented * 10 + uppers
    return max(names, key=score)


def get_engine():
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("❌  Variável DATABASE_URL não definida.")
        sys.exit(1)
    # Heroku usa postgres://, SQLAlchemy 1.4+ quer postgresql://
    url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url)


def list_breeds(conn):
    rows = conn.execute(text(
        "SELECT b.id, b.name, s.name AS species, "
        "       COUNT(a.id) AS animal_count "
        "FROM breed b "
        "JOIN species s ON s.id = b.species_id "
        "LEFT JOIN animal a ON a.breed_id = b.id "
        "GROUP BY b.id, b.name, s.name "
        "ORDER BY s.name, b.name"
    )).fetchall()
    return rows


def reassign_outro_dog_breeds(conn, dry_run: bool):
    """Move raças de cachorro cadastradas por engano sob a espécie 'Outro' de
    volta para 'Cachorro', mesclando com a raça já existente quando o nome
    (após correção de spelling) já tiver um equivalente lá."""
    species_rows = conn.execute(text("SELECT id, name FROM species")).fetchall()
    species_id_by_name = {r[1]: r[0] for r in species_rows}
    cachorro_id = species_id_by_name.get("Cachorro")
    if cachorro_id is None:
        print("⚠️   Espécie 'Cachorro' não encontrada — pulando reclassificação.")
        return

    rows = list_breeds(conn)
    breeds = {r[0]: {"name": r[1], "species": r[2], "count": r[3]} for r in rows}

    cachorro_by_key = {
        normalize_key(SPELLING_FIXES.get(info["name"], info["name"])): bid
        for bid, info in breeds.items()
        if info["species"] == "Cachorro"
    }

    moves = []    # (breed_id, name, effective_name) — vira o próprio breed, sem merge
    merges = []   # (src_id, dst_id, src_name, dst_name, count)

    for bid in sorted(OUTRO_DOG_BREED_IDS):
        info = breeds.get(bid)
        if info is None or info["species"] != "Outro":
            continue
        effective_name = SPELLING_FIXES.get(info["name"], info["name"])
        key = normalize_key(effective_name)
        dst_id = cachorro_by_key.get(key)
        if dst_id is not None and dst_id != bid:
            merges.append((bid, dst_id, info["name"], breeds[dst_id]["name"], info["count"]))
        else:
            moves.append((bid, info["name"], effective_name))

    print("\n" + "=" * 65)
    print(f"  Reclassificação Outro → Cachorro  {'[DRY RUN]' if dry_run else '[APLICANDO]'}")
    print("=" * 65)

    if moves:
        print(f"\n📦  Raças movidas para Cachorro (sem equivalente existente, {len(moves)}):")
        for bid, old, new in moves:
            renamed = f" (renomeada para '{new}')" if new != old else ""
            print(f"     #{bid:>4}  '{old}'{renamed}")
    if merges:
        print(f"\n🔀  Raças mescladas em Cachorro já existente ({len(merges)}):")
        for src_id, dst_id, src_name, dst_name, cnt in merges:
            print(f"     #{src_id:>4} '{src_name}'  →  #{dst_id} '{dst_name}'  ({cnt} animal(is) movido(s))")
    if not moves and not merges:
        print("\n✅  Nada a reclassificar.")

    if dry_run or (not moves and not merges):
        return

    for bid, old, new in moves:
        conn.execute(
            text("UPDATE breed SET name = :name, species_id = :species_id WHERE id = :id"),
            {"name": new, "species_id": cachorro_id, "id": bid},
        )
        conn.execute(
            text("UPDATE animal SET species_id = :species_id WHERE breed_id = :breed_id"),
            {"species_id": cachorro_id, "breed_id": bid},
        )

    for src_id, dst_id, _src_name, _dst_name, cnt in merges:
        if cnt > 0:
            conn.execute(
                text("UPDATE animal SET breed_id = :dst, species_id = :species_id WHERE breed_id = :src"),
                {"dst": dst_id, "species_id": cachorro_id, "src": src_id},
            )
        conn.execute(text("DELETE FROM breed WHERE id = :id"), {"id": src_id})


def fix_srd_species_mismatch(conn, dry_run: bool):
    """Corrige animais cujo breed_id aponta para 'SRD' de outra espécie
    (ex.: cachorro apontando para o SRD cadastrado em Gato). Só mexe no caso
    'SRD', que existe replicado em várias espécies e é o único nome
    suficientemente genérico para ser um erro seguro de corrigir — nomes como
    'Agapornis' ou 'Chinês' associados à espécie errada são prováveis dados de
    teste/lixo e ficam de fora, para revisão manual."""
    rows = conn.execute(text(
        "SELECT a.id, a.name, a.species_id, b.id AS breed_id, b.name AS breed_name, b.species_id AS breed_species_id "
        "FROM animal a JOIN breed b ON b.id = a.breed_id "
        "WHERE a.species_id != b.species_id"
    )).fetchall()

    srd_breed_by_species = {}
    for r in conn.execute(text("SELECT id, name, species_id FROM breed")).fetchall():
        if normalize_key(SPELLING_FIXES.get(r[1], r[1])) == normalize_key("SRD (Sem Raça Definida)"):
            srd_breed_by_species[r[2]] = r[0]

    fixes = []
    unresolved = []
    for animal_id, animal_name, animal_species_id, breed_id, breed_name, breed_species_id in rows:
        if normalize_key(SPELLING_FIXES.get(breed_name, breed_name)) != normalize_key("SRD (Sem Raça Definida)"):
            unresolved.append((animal_id, animal_name, breed_name))
            continue
        dst_breed_id = srd_breed_by_species.get(animal_species_id)
        if dst_breed_id is None or dst_breed_id == breed_id:
            unresolved.append((animal_id, animal_name, breed_name))
            continue
        fixes.append((animal_id, animal_name, breed_id, dst_breed_id))

    print("\n" + "=" * 65)
    print(f"  Correção de SRD com espécie trocada  {'[DRY RUN]' if dry_run else '[APLICANDO]'}")
    print("=" * 65)

    if fixes:
        print(f"\n🐾  Animais com breed_id de SRD redirecionado ({len(fixes)}):")
        for animal_id, animal_name, old_breed_id, new_breed_id in fixes:
            print(f"     animal #{animal_id} '{animal_name}': breed #{old_breed_id} → #{new_breed_id}")
    else:
        print("\n✅  Nenhum caso de SRD com espécie trocada.")

    if unresolved:
        print(f"\n⚠️   Casos que ficam para revisão manual (espécie/raça não batem e não é SRD, {len(unresolved)}):")
        for animal_id, animal_name, breed_name in unresolved:
            print(f"     animal #{animal_id} '{animal_name}' — raça '{breed_name}'")

    if dry_run or not fixes:
        return

    for animal_id, _animal_name, _old_breed_id, new_breed_id in fixes:
        conn.execute(
            text("UPDATE animal SET breed_id = :breed_id WHERE id = :id"),
            {"breed_id": new_breed_id, "id": animal_id},
        )


def apply_fixes(conn, dry_run: bool):
    rows = list_breeds(conn)
    # id → {name, species_id, species_name, animal_count}
    breeds = {r[0]: {"name": r[1], "species": r[2], "count": r[3]} for r in rows}

    changes = []  # (breed_id, old_name, new_name, reason)
    merges  = []  # (src_id, dst_id, src_name, dst_name, animal_count)
    to_delete = set()

    # ── Passo 1: aplicar correções manuais de spelling ───────────────────
    for bid, info in breeds.items():
        old = info["name"]
        if old in SPELLING_FIXES:
            new = SPELLING_FIXES[old]
            if new != old:
                changes.append((bid, old, new, "spelling fix"))

    # Aplicar nomes novos virtualmente para os passos seguintes
    name_map = {bid: info["name"] for bid, info in breeds.items()}
    for bid, old, new, _ in changes:
        name_map[bid] = new

    # ── Passo 2: detectar duplicatas por normalização ────────────────────
    # Agrupar por (species, normalized_name)
    groups: dict[tuple, list[int]] = {}
    for bid, info in breeds.items():
        effective_name = name_map[bid]
        key = (info["species"], normalize_key(effective_name))
        groups.setdefault(key, []).append(bid)

    for (species, norm_key), group_ids in groups.items():
        if len(group_ids) < 2:
            continue
        # Escolher o ID canônico = o com mais animais; em empate, o menor ID
        group_ids_sorted = sorted(group_ids, key=lambda i: (-breeds[i]["count"], i))
        canonical_id = group_ids_sorted[0]
        duplicates   = group_ids_sorted[1:]
        for dup_id in duplicates:
            merges.append((
                dup_id,
                canonical_id,
                name_map[dup_id],
                name_map[canonical_id],
                breeds[dup_id]["count"],
            ))
            to_delete.add(dup_id)

    # ── Relatório ─────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print(f"  PetOrlândia — fix_racas.py  {'[DRY RUN]' if dry_run else '[APLICANDO]'}")
    print("=" * 65)
    print(f"\n📋  Total de raças no banco: {len(breeds)}")

    if changes:
        print(f"\n✏️   Correções de spelling ({len(changes)}):")
        for bid, old, new, reason in changes:
            cnt = breeds[bid]["count"]
            print(f"     #{bid:>4}  '{old}'  →  '{new}'  ({cnt} animal(is))")
    else:
        print("\n✅  Nenhum erro de spelling encontrado.")

    if merges:
        print(f"\n🔀  Deduplicações — redirecionar animais e deletar ({len(merges)}):")
        for src_id, dst_id, src_name, dst_name, cnt in merges:
            print(f"     #{src_id:>4} '{src_name}'  →  #{dst_id} '{dst_name}'  ({cnt} animal(is) movido(s))")
    else:
        print("\n✅  Nenhuma duplicata encontrada.")

    total_changes = len(changes) + len(merges)
    if total_changes == 0:
        print("\n🎉  Banco está limpo — nada a fazer.")
        return

    if dry_run:
        print("\n💡  Rode com --apply para executar as alterações acima.")
        return

    # ── Executar as mudanças ──────────────────────────────────────────────
    print("\n🚀  Executando...")

    # 1. Renomear (spelling fixes) — exceto os que vão ser deletados
    for bid, old, new, _ in changes:
        if bid not in to_delete:
            conn.execute(
                text("UPDATE breed SET name = :new WHERE id = :id"),
                {"new": new, "id": bid}
            )
            print(f"     RENAME #{bid}: '{old}' → '{new}'")

    # 2. Redirecionar animais das duplicatas para o canônico
    for src_id, dst_id, src_name, dst_name, cnt in merges:
        if cnt > 0:
            conn.execute(
                text("UPDATE animal SET breed_id = :dst WHERE breed_id = :src"),
                {"dst": dst_id, "src": src_id}
            )
            print(f"     MOVE {cnt} animais: #{src_id} → #{dst_id}")

    # 3. Deletar duplicatas
    for del_id in sorted(to_delete):
        conn.execute(text("DELETE FROM breed WHERE id = :id"), {"id": del_id})
        print(f"     DELETE breed #{del_id}")

    print(f"\n✅  Concluído: {len(changes) - len(to_delete & {b[0] for b in changes})} renomeações, "
          f"{len(merges)} merges, {len(to_delete)} deleções.")


def main():
    parser = argparse.ArgumentParser(description="Normaliza e deduplica raças no banco PetOrlândia.")
    parser.add_argument("--apply", action="store_true", help="Aplica as mudanças (padrão: dry-run)")
    parser.add_argument("--list", action="store_true", help="Só lista as raças atuais e sai")
    args = parser.parse_args()

    engine = get_engine()
    with engine.connect() as conn:
        if args.list:
            rows = list_breeds(conn)
            print(f"\n{'#ID':>5}  {'Espécie':<12}  {'Raça':<40}  {'Animais':>7}")
            print("-" * 70)
            for r in rows:
                print(f"  {r[0]:>4}  {r[2]:<12}  {r[1]:<40}  {r[3]:>7}")
            print(f"\nTotal: {len(rows)} raças")
            return

        dry_run = not args.apply
        if not dry_run:
            # Usar transação para poder fazer rollback se der erro
            with conn.begin():
                reassign_outro_dog_breeds(conn, dry_run=False)
                fix_srd_species_mismatch(conn, dry_run=False)
                apply_fixes(conn, dry_run=False)
        else:
            reassign_outro_dog_breeds(conn, dry_run=True)
            fix_srd_species_mismatch(conn, dry_run=True)
            apply_fixes(conn, dry_run=True)


if __name__ == "__main__":
    main()
