"""
diagnostico_migracao.py
=======================
Mostra o estado atual do banco após a(s) migração(ões) do VetSmart:
  - Quantos BlocoPrescricao e Prescricao existem por clínica
  - Prescrições órfãs (sem bloco_id) — invisíveis na UI
  - Animais duplicados (mesmo nome + mesmo tutor)
  - Tutores duplicados por nome
  - Clínicas presentes

NÃO altera nada no banco.

Uso:
  python scripts/diagnostico_migracao.py
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from app_factory import create_app
from extensions import db
from models.base import User, Animal, Prescricao, BlocoPrescricao, Clinica

app = create_app()

with app.app_context():
    clinicas = {c.id: c.nome for c in Clinica.query.all()}

    print("=" * 60)
    print("CLÍNICAS NO BANCO")
    print("=" * 60)
    for cid, nome in sorted(clinicas.items()):
        print(f"  id={cid:3d}  {nome}")

    # ── BlocoPrescricao por clínica ────────────────────────────────
    print("\n" + "=" * 60)
    print("BLOCOS DE PRESCRIÇÃO POR CLÍNICA")
    print("=" * 60)
    blocos = BlocoPrescricao.query.all()
    blocos_por_clinica = defaultdict(list)
    for b in blocos:
        blocos_por_clinica[b.clinica_id].append(b)
    for cid, lista in sorted(blocos_por_clinica.items()):
        nome = clinicas.get(cid, f"id={cid} (não encontrada!)")
        itens = sum(len(b.prescricoes) for b in lista)
        print(f"  Clínica {cid:3d} ({nome}): {len(lista)} blocos, {itens} medicamentos")
    if not blocos:
        print("  (nenhum BlocoPrescricao encontrado)")

    # ── Prescrições órfãs (sem bloco_id) ──────────────────────────
    print("\n" + "=" * 60)
    print("PRESCRIÇÕES ÓRFÃS (sem bloco_id — invisíveis na UI)")
    print("=" * 60)
    orfas = Prescricao.query.filter(Prescricao.bloco_id.is_(None)).all()
    print(f"  Total: {len(orfas)} prescrições sem bloco_id")
    if orfas:
        print("  Estas NÃO aparecem na aba Medicamentos do Petorlandia.")
        print("  Exemplo dos primeiros 5:")
        for p in orfas[:5]:
            animal = Animal.query.get(p.animal_id)
            nome_animal = animal.name if animal else f"animal id={p.animal_id}"
            print(f"    id={p.id} | animal: {nome_animal} | {p.medicamento[:50]}")

    # ── Animais duplicados ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("ANIMAIS DUPLICADOS (mesmo nome + mesmo tutor)")
    print("=" * 60)
    animais = Animal.query.order_by(Animal.user_id, Animal.name).all()
    grupos = defaultdict(list)
    for a in animais:
        grupos[(a.user_id, a.name)].append(a)
    duplicados = {k: v for k, v in grupos.items() if len(v) > 1}
    print(f"  Grupos com duplicatas: {len(duplicados)}")
    for (uid, nome), lista in list(duplicados.items())[:10]:
        tutor = User.query.get(uid)
        tutor_nome = tutor.name if tutor else f"id={uid}"
        ids = [f"id={a.id} (clinica={a.clinica_id}, added={str(a.date_added)[:10]})" for a in lista]
        print(f"  Animal '{nome}' / Tutor '{tutor_nome}': {' | '.join(ids)}")
    if len(duplicados) > 10:
        print(f"  ... e mais {len(duplicados)-10} grupos")

    # ── Tutores duplicados por nome ────────────────────────────────
    print("\n" + "=" * 60)
    print("TUTORES DUPLICADOS (mesmo nome)")
    print("=" * 60)
    tutores = User.query.filter_by(role="tutor").order_by(User.name).all()
    t_grupos = defaultdict(list)
    for t in tutores:
        t_grupos[t.name.strip().lower()].append(t)
    t_dup = {k: v for k, v in t_grupos.items() if len(v) > 1}
    print(f"  Grupos com duplicatas: {len(t_dup)}")
    for nome, lista in list(t_dup.items())[:10]:
        ids = [f"id={u.id} cpf={u.cpf or '-'} email={u.email}" for u in lista]
        print(f"  '{lista[0].name}': {' | '.join(ids)}")
    if len(t_dup) > 10:
        print(f"  ... e mais {len(t_dup)-10} grupos")

    # ── Resumo final ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RESUMO")
    print("=" * 60)
    print(f"  Tutores (role=tutor)    : {User.query.filter_by(role='tutor').count()}")
    print(f"  Animais                 : {Animal.query.count()}")
    print(f"  BlocoPrescricao         : {BlocoPrescricao.query.count()}")
    print(f"  Prescricao (total)      : {Prescricao.query.count()}")
    print(f"  Prescricao sem bloco_id : {len(orfas)}")
    print(f"  Animais duplicados      : {sum(len(v)-1 for v in duplicados.values())} registros extras")
    print(f"  Tutores duplicados      : {sum(len(v)-1 for v in t_dup.values())} registros extras")
    print("=" * 60)
