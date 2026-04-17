"""
limpar_duplicatas_migracao.py
==============================
Corrige o banco após múltiplas execuções do migrate_vetsmart.py:

  1. Tutores duplicados (mesmo nome, sem CPF/email)
     → mantém o de menor id, reassocia os animais, deleta os extras

  2. Animais duplicados (mesmo nome + mesmo tutor)
     → mantém o de menor id, reassocia BlocoPrescricao/Prescricao/Consulta/Vacina,
        deleta os extras

  3. Prescrições órfãs (bloco_id IS NULL)
     → deleta todas (invisíveis na UI, resquícios da migração antiga)

  4. BlocoPrescricao duplicados (mesma prescrição importada N vezes)
     → agrupa por (animal_id, data da criação, instrucoes_gerais),
        mantém o de maior id (última importação = dados mais completos),
        deleta os extras junto com seus itens (cascade)

Uso:
  python scripts/limpar_duplicatas_migracao.py --dry-run   # só mostra
  python scripts/limpar_duplicatas_migracao.py             # aplica
"""

import sys
import argparse
import logging
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def run(dry_run: bool):
    from app_factory import create_app
    from extensions import db
    from models.base import User, Animal, Prescricao, BlocoPrescricao, Consulta, Vacina

    app = create_app()
    with app.app_context():

        # ── 1. TUTORES DUPLICADOS ─────────────────────────────────────────
        log.info("=" * 55)
        log.info("PASSO 1 — Tutores duplicados (mesmo nome, sem CPF)")
        log.info("=" * 55)

        tutores = (User.query
                   .filter_by(role="tutor")
                   .filter(User.cpf.is_(None))
                   .order_by(User.id)
                   .all())

        grupos_tutor = defaultdict(list)
        for t in tutores:
            grupos_tutor[t.name.strip().lower()].append(t)

        dup_tutores = {k: v for k, v in grupos_tutor.items() if len(v) > 1}
        tutor_remap: dict[int, int] = {}  # id_antigo → id_mantido

        removidos_tutores = 0
        for nome, lista in dup_tutores.items():
            lista.sort(key=lambda u: u.id)
            manter = lista[0]
            extras = lista[1:]
            for extra in extras:
                tutor_remap[extra.id] = manter.id
                log.info("  Tutor '%s': id=%d → mergeando em id=%d", manter.name, extra.id, manter.id)
                if not dry_run:
                    Animal.query.filter_by(user_id=extra.id).update({"user_id": manter.id})
                    db.session.delete(extra)
                removidos_tutores += 1

        log.info("  Tutores a remover: %d", removidos_tutores)
        if not dry_run:
            db.session.flush()

        # ── 2. ANIMAIS DUPLICADOS ─────────────────────────────────────────
        log.info("=" * 55)
        log.info("PASSO 2 — Animais duplicados (mesmo nome + mesmo tutor)")
        log.info("=" * 55)

        animais = Animal.query.order_by(Animal.user_id, Animal.name, Animal.id).all()
        grupos_animal = defaultdict(list)
        for a in animais:
            grupos_animal[(a.user_id, a.name.strip())].append(a)

        dup_animais = {k: v for k, v in grupos_animal.items() if len(v) > 1}
        animal_remap: dict[int, int] = {}

        removidos_animais = 0
        for (uid, nome), lista in dup_animais.items():
            lista.sort(key=lambda a: a.id)
            manter = lista[0]
            extras = lista[1:]

            for extra in extras:
                animal_remap[extra.id] = manter.id
                log.info("  Animal '%s' (tutor id=%d): id=%d → mergeando em id=%d",
                         nome, uid, extra.id, manter.id)
                if not dry_run:
                    BlocoPrescricao.query.filter_by(animal_id=extra.id).update(
                        {"animal_id": manter.id}, synchronize_session="fetch"
                    )
                    Prescricao.query.filter_by(animal_id=extra.id).update(
                        {"animal_id": manter.id}, synchronize_session="fetch"
                    )
                    Consulta.query.filter_by(animal_id=extra.id).update(
                        {"animal_id": manter.id}, synchronize_session="fetch"
                    )
                    Vacina.query.filter_by(animal_id=extra.id).update(
                        {"animal_id": manter.id}, synchronize_session="fetch"
                    )
                    db.session.delete(extra)
                removidos_animais += 1

        log.info("  Animais a remover: %d", removidos_animais)
        if not dry_run:
            db.session.flush()

        # ── 3. PRESCRIÇÕES ÓRFÃS ──────────────────────────────────────────
        log.info("=" * 55)
        log.info("PASSO 3 — Prescrições órfãs (bloco_id IS NULL)")
        log.info("=" * 55)

        orfas = Prescricao.query.filter(Prescricao.bloco_id.is_(None)).all()
        log.info("  Prescrições órfãs a deletar: %d", len(orfas))
        if not dry_run:
            for p in orfas:
                db.session.delete(p)
            db.session.flush()

        # ── 4. BLOCOS DUPLICADOS ──────────────────────────────────────────
        log.info("=" * 55)
        log.info("PASSO 4 — BlocoPrescricao duplicados (mesma prescrição, N importações)")
        log.info("=" * 55)

        blocos = BlocoPrescricao.query.order_by(
            BlocoPrescricao.animal_id,
            BlocoPrescricao.data_criacao,
            BlocoPrescricao.id,
        ).all()

        # Chave de deduplicação: animal_id + data (sem hora) + instrucoes_gerais
        grupos_bloco = defaultdict(list)
        for b in blocos:
            data_key = b.data_criacao.date() if b.data_criacao else None
            key = (b.animal_id, data_key, (b.instrucoes_gerais or "").strip())
            grupos_bloco[key].append(b)

        dup_blocos = {k: v for k, v in grupos_bloco.items() if len(v) > 1}
        removidos_blocos = 0
        removidos_itens = 0

        for key, lista in dup_blocos.items():
            lista.sort(key=lambda b: b.id)
            manter = lista[-1]   # mantém o mais recente (dados mais completos)
            extras = lista[:-1]
            for extra in extras:
                n_itens = len(extra.prescricoes)
                log.info("  Bloco id=%d (animal=%d, data=%s): deletando (%d medicamentos)",
                         extra.id, extra.animal_id,
                         key[1], n_itens)
                removidos_blocos += 1
                removidos_itens += n_itens
                if not dry_run:
                    db.session.delete(extra)   # cascade deleta os Prescricao filhos

        log.info("  Blocos a remover: %d | Medicamentos a remover: %d",
                 removidos_blocos, removidos_itens)
        if not dry_run:
            db.session.flush()

        # ── COMMIT / RESUMO ───────────────────────────────────────────────
        log.info("=" * 55)
        log.info("RESUMO")
        log.info("=" * 55)
        log.info("  Tutores removidos        : %d", removidos_tutores)
        log.info("  Animais removidos        : %d", removidos_animais)
        log.info("  Prescrições órfãs        : %d", len(orfas))
        log.info("  Blocos duplicados        : %d (+ %d medicamentos)",
                 removidos_blocos, removidos_itens)

        if dry_run:
            log.info("  [DRY-RUN] Nenhuma alteração gravada.")
            db.session.rollback()
        else:
            db.session.commit()
            log.info("  ✅ Commit realizado.")

            # Contagem final
            log.info("=" * 55)
            log.info("ESTADO FINAL")
            log.info("  Tutores (role=tutor)    : %d", User.query.filter_by(role="tutor").count())
            log.info("  Animais                 : %d", Animal.query.count())
            log.info("  BlocoPrescricao         : %d", BlocoPrescricao.query.count())
            log.info("  Prescricao (total)      : %d", Prescricao.query.count())
            log.info("  Prescricao sem bloco_id : %d",
                     Prescricao.query.filter(Prescricao.bloco_id.is_(None)).count())
            log.info("=" * 55)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Simula sem gravar no banco")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
