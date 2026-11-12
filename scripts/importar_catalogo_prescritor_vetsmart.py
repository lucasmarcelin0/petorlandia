"""Traz do catálogo do prescritor do VetSmart as apresentações do que a clínica prescreve.

O prescritor do VetSmart oferece, para cada item, uma lista de apresentações
que a página pública de bula não tem — em especial a dos princípios ativos
genéricos ("Dipirona 500 mg, comprimido", "500 mg/mL, gotas"...). Este script
lê essa lista e a guarda no bulário, onde o prescritor do PetOrlândia a usa.

Por padrão importa só os itens citados nas receitas já emitidas. O endereço do
VetSmart tem limite de ritmo: o script lê um item a cada 25 segundos, obedece
ao pedido de espera e para se o limite insistir. Rodar de novo continua de
onde parou (o que já foi importado é pulado).

Uso (no Heroku, em dyno avulso; a saída vai para os logs):
    heroku run:detached --app petorlandia -- python scripts/importar_catalogo_prescritor_vetsmart.py
    heroku logs --app petorlandia --dyno run.NNNN --num 400 | grep 'CATALOGO|'

Opções:
    --listar            só mostra o que seria importado; não lê o VetSmart
    --ids 1682,1970     importa estes ids do VetSmart, em vez dos prescritos
    --limite 300        no máximo este número de itens por execução
    --intervalo 25      segundos entre leituras
    --refazer           lê de novo o que já foi importado
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import catalogo_prescritor as catalogo  # noqa: E402


def avisar(texto):
    print(f'CATALOGO| {texto}', flush=True)


def carregar_indices(db, Medicamento):
    """(nomes -> ids do VetSmart, id do VetSmart -> ids de medicamento)."""
    linhas = db.session.query(
        Medicamento.id,
        Medicamento.nome,
        Medicamento.principio_ativo,
        Medicamento.vetsmart_produto_id,
        Medicamento.conteudo_estruturado,
    ).yield_per(200)
    return catalogo.indice_de_nomes(linhas)


def nomes_prescritos(db, Prescricao):
    """Nomes de medicamento das receitas, do mais prescrito para o menos."""
    from sqlalchemy import func

    linhas = (
        db.session.query(Prescricao.medicamento, func.count(Prescricao.id))
        .filter(Prescricao.medicamento.isnot(None))
        .group_by(Prescricao.medicamento)
        .order_by(func.count(Prescricao.id).desc())
        .all()
    )
    return [nome for nome, _total in linhas if (nome or '').strip()]


def criar_gravador(db, Medicamento, donos):
    """``gravar(pid, item)``: guarda o item em cada medicamento dono e confirma."""

    def gravar(pid, item):
        gravados = 0
        for med_id in sorted(donos[pid]):
            medicamento = db.session.get(Medicamento, med_id)
            if medicamento is None:
                continue
            # Atribuição nova: coluna JSON não percebe alteração por dentro.
            medicamento.conteudo_estruturado = catalogo.gravar_no_conteudo(
                medicamento.conteudo_estruturado, pid, item,
            )
            gravados += 1
        db.session.commit()
        return gravados

    return gravar


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--listar', action='store_true')
    parser.add_argument('--ids', help='Ids do VetSmart separados por vírgula')
    parser.add_argument('--limite', type=int, default=300)
    parser.add_argument('--intervalo', type=float, default=catalogo.INTERVALO_PADRAO)
    parser.add_argument('--refazer', action='store_true')
    args = parser.parse_args()

    # create_app() direto: o CLI do flask quebra com este app factory.
    from app_factory import create_app
    from extensions import db
    from models.bulario import Medicamento
    from models.consulta import Prescricao

    app = create_app()
    with app.test_request_context():
        try:
            por_nome, donos = carregar_indices(db, Medicamento)
            if args.ids:
                ids = [int(parte) for parte in args.ids.split(',') if parte.strip()]
            else:
                ids = catalogo.ids_dos_nomes(nomes_prescritos(db, Prescricao), por_nome)
            sem_dono = [pid for pid in ids if pid not in donos]
            ids = [pid for pid in ids if pid in donos]

            def falta_importar(pid):
                return any(
                    not catalogo.ja_importado(db.session.get(Medicamento, med_id).conteudo_estruturado, pid)
                    for med_id in donos[pid]
                )

            pendentes = ids if args.refazer else [pid for pid in ids if falta_importar(pid)]
            avisar(
                f'{len(ids)} item(ns) do VetSmart citados; {len(ids) - len(pendentes)} já importado(s); '
                f'{len(pendentes)} por ler'
                + (f'; {len(sem_dono)} sem medicamento no bulário' if sem_dono else '')
            )
            pendentes = pendentes[:max(args.limite, 0)]
            if args.listar:
                for pid in pendentes:
                    avisar(f'  leria o item {pid} (medicamento(s) {sorted(donos[pid])})')
                avisar('FIM (nada foi lido nem gravado)')
                return

            resumo = catalogo.importar(
                pendentes, criar_gravador(db, Medicamento, donos),
                intervalo=args.intervalo, avisar=avisar,
            )
            avisar('resumo: ' + ', '.join(f'{chave}={valor}' for chave, valor in resumo.items()))
            avisar('FIM')
        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.remove()


if __name__ == '__main__':
    main()
