"""Consolida Medicamentos legados pré-refatoração em apresentações.

Antes da refatoração que consolida 1 Medicamento por princípio ativo, o banco
acumulou linhas no formato "{PA} - {valor}{unidade}, {forma}" (ex.
"Prednisona - 5mg, comprimido"). Elas poluem o autocomplete e não têm
apresentações nem doses associadas.

Este script:
  1) Parseia o nome legado em (principio_ativo, valor, unidade, forma)
  2) Encontra/cria um Medicamento consolidado para esse PA
  3) Cria uma ApresentacaoMedicamento no consolidado (sem fabricante)
  4) Deleta o Medicamento legado

`prescricao.medicamento` é TEXT (não FK) — não quebra histórico.

Uso:
  python scripts/consolidar_medicamentos_legados.py --dry-run
  python scripts/consolidar_medicamentos_legados.py --apply
"""
import argparse
import logging
import re
import sys
import unicodedata
from typing import Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# "Prednisona - 5mg, comprimido"
# "Dipirona - 500 mg/mL, solução oral"
# "Dipirona - 500 mg/mL, gotas"
# "Ondansetrona" (via Vonau - 4 mg, comprimido (10 un))
# "Ácido Tranexâmico - 250 mg, comprimido (24 un)"
PADRAO_LEGADO = re.compile(
    r'^\s*(?P<nome>.+?)\s*-\s*'
    r'(?P<conc>\d+(?:[.,]\d+)?)\s*'
    r'(?P<unidade>mg/ml|mcg/ml|mg|mcg|g|ml|ui|%)'
    r'\s*,\s*(?P<forma>[^,(]+?)'
    r'(?:\s*\([^)]*\))?\s*$',
    re.IGNORECASE,
)

# Normaliza forma: "comprimido" → "Comprimido", "solução oral" → "Solução Oral"
def _titlecase_forma(forma: str) -> str:
    forma = forma.strip()
    # Palavras pequenas ficam em minúsculo exceto a primeira.
    minus = {'de', 'do', 'da', 'dos', 'das', 'em', 'e'}
    partes = forma.split()
    out = []
    for i, p in enumerate(partes):
        if i > 0 and p.lower() in minus:
            out.append(p.lower())
        else:
            out.append(p.capitalize())
    return ' '.join(out)


def _normaliza_unidade(un: str) -> str:
    """mg→mg, mg/ml→mg/mL, ui→UI."""
    u = un.strip().lower()
    mapa = {
        'mg': 'mg', 'mcg': 'mcg', 'g': 'g', 'ml': 'mL',
        'mg/ml': 'mg/mL', 'mcg/ml': 'mcg/mL',
        'ui': 'UI', '%': '%',
    }
    return mapa.get(u, un)


def _chave_pa(nome: str) -> str:
    """Remove acentos + lowercase + strip — pra comparar princípio ativo
    sem depender de acentuação no banco."""
    s = unicodedata.normalize('NFKD', nome or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()


def parse_nome_legado(nome: str) -> Optional[Tuple[str, float, str, str]]:
    """Retorna (pa, concentracao_valor, concentracao_unidade, forma) ou None."""
    m = PADRAO_LEGADO.match(nome)
    if not m:
        return None
    pa = m.group('nome').strip()
    try:
        conc = float(m.group('conc').replace(',', '.'))
    except ValueError:
        return None
    un = _normaliza_unidade(m.group('unidade'))
    forma = _titlecase_forma(m.group('forma'))
    # Filtra PA claramente não-ativo (ex: "Vonau" — nome comercial).
    # Mantemos esses como princípio ativo "literal" por falta de melhor.
    return pa, conc, un, forma


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Só lista o que faria')
    parser.add_argument('--apply', action='store_true', help='Aplica no banco')
    args = parser.parse_args()

    if not (args.dry_run or args.apply):
        parser.error('Informe --dry-run ou --apply')

    # Importar depois de parse_args pra permitir --help sem conectar ao banco.
    from app import app
    from models.base import db, Medicamento, ApresentacaoMedicamento, DoseMedicamento

    with app.app_context():
        # 1) Lista todos os Medicamentos que batem com o padrão legado.
        #    Filtra os que NÃO têm apresentações nem doses (são seguros).
        candidatos = []
        todos = Medicamento.query.filter(
            Medicamento.nome.op('~')(r'\s*-\s*[0-9]+\s*(mg|mcg|ml|g|ui)')
        ).all()

        log.info(f'Medicamentos candidatos (nome com concentração): {len(todos)}')

        for med in todos:
            parsed = parse_nome_legado(med.nome)
            if not parsed:
                log.warning(f'  [{med.id}] Não parseou: {med.nome!r}')
                continue
            pa, conc, un, forma = parsed
            n_apres = len(med.apresentacoes or [])
            n_doses = len(med.doses or [])
            if n_apres or n_doses:
                log.info(f'  [{med.id}] {med.nome!r} — tem {n_apres}a/{n_doses}d, pulando (não é órfão puro)')
                continue
            candidatos.append((med, pa, conc, un, forma))

        log.info(f'Candidatos órfãos para migrar: {len(candidatos)}')
        log.info('')

        # 2) Pra cada candidato, encontrar/criar consolidado e criar apresentação.
        criados_medicamento = 0
        criados_apres = 0
        deletados = 0
        skipped_dup = 0

        for med_legado, pa, conc, un, forma in candidatos:
            chave_norm = _chave_pa(pa)
            # Busca consolidado por principio_ativo normalizado.
            consolidado = None
            for m in Medicamento.query.filter(
                Medicamento.principio_ativo.isnot(None)
            ).all():
                if _chave_pa(m.principio_ativo) == chave_norm:
                    consolidado = m
                    break

            if not consolidado:
                # Busca por nome (caso o "consolidado" ainda não tenha PA).
                # Ex: o próprio 'Prednisona' id=1587 já tem PA — esse ramo raramente roda.
                for m in Medicamento.query.filter(
                    Medicamento.nome.ilike(pa)
                ).all():
                    if _chave_pa(m.nome) == chave_norm:
                        consolidado = m
                        break

            if not consolidado:
                # Cria um consolidado novo herdando created_by do legado.
                consolidado = Medicamento(
                    nome=pa,
                    principio_ativo=pa,
                    classificacao=med_legado.classificacao,
                    via_administracao=med_legado.via_administracao,
                    created_by=med_legado.created_by,
                )
                db.session.add(consolidado)
                db.session.flush()
                criados_medicamento += 1
                log.info(f'  CRIOU consolidado [{consolidado.id}] {pa!r}')

            # Checa dup na apresentação (forma, concentracao_valor, concentracao_unidade, fabricante=None).
            # Consulta o banco DIRETO pra enxergar adds feitos em iterações anteriores
            # deste mesmo run (que ainda não fizeram commit, mas estão em session).
            db.session.flush()  # garante que adds recentes estejam queryable
            dup = ApresentacaoMedicamento.query.filter_by(
                medicamento_id=consolidado.id,
                forma=forma,
                concentracao_valor=conc,
                concentracao_unidade=un,
                fabricante=None,
            ).first()
            if dup:
                skipped_dup += 1
                log.info(f'  SKIP apres duplicada: {forma} {conc:g} {un} já existe em [{consolidado.id}]')
            else:
                nova = ApresentacaoMedicamento(
                    medicamento_id=consolidado.id,
                    forma=forma,
                    concentracao=f'{conc:g} {un}',
                    concentracao_valor=conc,
                    concentracao_unidade=un,
                    fabricante=None,
                )
                db.session.add(nova)
                db.session.flush()
                criados_apres += 1
                log.info(
                    f'  + APRES [{consolidado.id}] {forma} {conc:g} {un} '
                    f'(do legado #{med_legado.id} {med_legado.nome!r})'
                )

            # Deletar o legado.
            log.info(f'  - DEL legado #{med_legado.id} {med_legado.nome!r}')
            db.session.delete(med_legado)
            deletados += 1

        if args.apply:
            db.session.commit()
            log.info('COMMIT aplicado.')
        else:
            db.session.rollback()
            log.info('DRY-RUN — nenhum commit.')

        print()
        print('=' * 60)
        print(f'  Consolidados criados:   {criados_medicamento}')
        print(f'  Apresentações criadas:  {criados_apres}')
        print(f'  Apresentações dup:      {skipped_dup}')
        print(f'  Legados deletados:      {deletados}')
        print(f'  Modo:                   {"APPLY" if args.apply else "DRY-RUN"}')
        print('=' * 60)


if __name__ == '__main__':
    sys.exit(main() or 0)
