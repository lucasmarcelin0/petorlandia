"""Confere, produto por produto, o que o prescritor oferece (só leitura).

O bulário guarda os produtos do VetSmart agrupados por princípio ativo. O
prescritor tem de mostrar, para cada produto, as apresentações e as doses
dele — nem mais, nem menos. Este script percorre o catálogo e aponta onde
isso não acontece:

    OUTRO_PRODUTO    apresentação de outra marca na lista do produto
    FALTA_VETSMART   apresentação publicada pelo VetSmart que não aparece
    LINHA_OCULTA     apresentação cadastrada para o produto que não aparece
    LISTA_VAZIA      produto com apresentações cadastradas e lista vazia
    DOSE_SEM_DONO    dose presa a uma apresentação que não está na lista
    ERRO             exceção ao montar a lista ou a dose

Além das violações, informa quantos produtos o bulário não tem como atender
porque não guarda nenhuma apresentação deles (``sem_apresentacao``): é o que
falta importar, não um defeito do prescritor.

Nada é gravado. Uso (no Heroku, em dyno avulso; a saída vai para os logs):
    heroku run:detached --app petorlandia -- python scripts/auditar_prescricao_por_produto.py
    heroku logs --app petorlandia --dyno run.NNNN --num 300 | grep 'PRESCRICAO|'

Filtro opcional: --medicamento 6186 (um medicamento só, com o detalhe).
"""
import argparse
import os
import sys
from collections import Counter
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import bulario  # noqa: E402

_esc = bulario._esc

#: Pacientes de referência para exercitar o cálculo de dose.
PACIENTES = (
    SimpleNamespace(peso=10.0, species=SimpleNamespace(name='Cachorro')),
    SimpleNamespace(peso=4.0, species=SimpleNamespace(name='Gato')),
)


def _tem_conteudo(bruta) -> bool:
    return isinstance(bruta, dict) and bool(
        (bruta.get('forma') or '').strip() or (bruta.get('concentracao') or '').strip()
    )


def violacoes_do_medicamento(medicamento):
    """[(código, produto, detalhe)] para cada produto do medicamento."""
    violacoes = []
    nomes_vistos = set()
    for produto in _esc.produtos(medicamento):
        nome = (produto.get('nome') or '').strip()
        chave = _esc.norm(nome)
        if chave in nomes_vistos:
            continue  # homônimos respondem como um produto só
        nomes_vistos.add(chave)
        produto = _esc.resolver_produto(medicamento, nome) or produto
        pids = _esc.pids_do_produto(produto)
        linhas = [
            ap for ap in (getattr(medicamento, 'apresentacoes', None) or [])
            if getattr(ap, 'vetsmart_produto_id', None) in pids
        ]
        # O que o VetSmart publica para o produto: o catálogo do prescritor,
        # quando já importado; senão, o retrato da página de bula.
        do_catalogo = _esc._formas_do_catalogo(_esc.catalogo_do_produto(medicamento, produto))
        if do_catalogo:
            publicadas = [_esc.rotulo_do_catalogo(forma) for forma in do_catalogo]
        else:
            publicadas = [
                _esc.rotulo_vetsmart(b, nome)
                for b in (produto.get('apresentacoes') or []) if _tem_conteudo(b)
            ]

        try:
            lista = bulario.listar_apresentacoes_medicamento(medicamento, nome_comercial_filtro=nome)
        except Exception as exc:  # noqa: BLE001 - o auditor relata, não derruba
            violacoes.append(('ERRO', nome, f'apresentacoes: {exc!r}'))
            continue

        if not (linhas or publicadas):
            continue  # nada cadastrado para o produto: lacuna de dados

        if not lista:
            violacoes.append(('LISTA_VAZIA', nome, f'{len(linhas)} linha(s), {len(publicadas)} publicada(s)'))
            continue

        ids = {ap['id'] for ap in lista}
        rotulos = {
            _esc.norm(ap.get('rotulo_opcao'))
            for ap in lista if ap.get('origem') == 'produto'
        }
        for ap in (getattr(medicamento, 'apresentacoes', None) or []):
            pid = getattr(ap, 'vetsmart_produto_id', None)
            if ap.id in ids and pid is not None and pid not in pids:
                violacoes.append(('OUTRO_PRODUTO', nome, f'apresentacao {ap.id}'))
        for rotulo in publicadas:
            if _esc.norm(rotulo) not in rotulos:
                violacoes.append(('FALTA_VETSMART', nome, rotulo))
        for ap in linhas:
            # A linha aparece com o próprio id, ou representada por outra de
            # mesmo rótulo (duplicata de importações antigas).
            if ap.id not in ids and _esc.norm(_esc.rotulo_vetsmart(ap, nome)) not in rotulos:
                violacoes.append(('LINHA_OCULTA', nome, f'apresentacao {ap.id}'))

        for paciente in PACIENTES:
            try:
                sugestao = bulario.sugerir_dose(medicamento, paciente, nome_comercial_filtro=nome)
            except Exception as exc:  # noqa: BLE001
                violacoes.append(('ERRO', nome, f'dose: {exc!r}'))
                continue
            if not sugestao or sugestao.get('multiplo'):
                continue
            ids_dose = {ap['id'] for ap in sugestao.get('apresentacoes') or []}
            soltos = set(sugestao.get('apresentacao_ids') or []) - ids_dose
            if soltos:
                violacoes.append(('DOSE_SEM_DONO', nome, f'apresentacoes {sorted(soltos)}'))
    return violacoes


def resumo_do_medicamento(medicamento) -> Counter:
    """Contagem de produtos por situação das apresentações."""
    contagem = Counter()
    nomes_vistos = set()
    for produto in _esc.produtos(medicamento):
        nome = (produto.get('nome') or '').strip()
        chave = _esc.norm(nome)
        if chave in nomes_vistos:
            continue
        nomes_vistos.add(chave)
        contagem['produtos'] += 1
        produto = _esc.resolver_produto(medicamento, nome) or produto
        if _esc._formas_do_catalogo(_esc.catalogo_do_produto(medicamento, produto)):
            contagem['com_catalogo_do_prescritor'] += 1
        escopo = _esc.escopo_de(medicamento, nome)
        if escopo is not None:
            contagem['com_apresentacoes_proprias'] += 1
            if any(getattr(dose, 'apresentacao_ids', None) for dose in escopo.doses):
                contagem['dose_por_apresentacao'] += 1
        elif (produto.get('tipo') or 'produto') == 'principio_ativo':
            contagem['principio_ativo'] += 1
        else:
            contagem['sem_apresentacao'] += 1
    return contagem


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--medicamento', type=int, help='Id de um medicamento só')
    args = parser.parse_args()

    # create_app() direto: o CLI do flask quebra com este app factory.
    from app_factory import create_app
    from extensions import db
    from models.bulario import Medicamento
    from sqlalchemy.orm import selectinload

    app = create_app()
    with app.test_request_context():
        try:
            consulta = Medicamento.query.options(
                selectinload(Medicamento.apresentacoes),
                selectinload(Medicamento.doses),
            ).order_by(Medicamento.id)
            if args.medicamento:
                consulta = consulta.filter(Medicamento.id == args.medicamento)
            total = Counter()
            por_codigo = Counter()
            exemplos = {}
            for medicamento in consulta.yield_per(200):
                total += resumo_do_medicamento(medicamento)
                for codigo, produto, detalhe in violacoes_do_medicamento(medicamento):
                    por_codigo[codigo] += 1
                    exemplos.setdefault(codigo, [])
                    if args.medicamento or len(exemplos[codigo]) < 15:
                        exemplos[codigo].append(f'med {medicamento.id} · {produto} · {detalhe}')
            print('PRESCRICAO| situacao dos produtos: ' + ', '.join(f'{k}={v}' for k, v in sorted(total.items())))
            print('PRESCRICAO| violacoes: ' + (', '.join(f'{k}={v}' for k, v in sorted(por_codigo.items())) or 'nenhuma'))
            for codigo, linhas in sorted(exemplos.items()):
                for linha in linhas:
                    print(f'PRESCRICAO|   [{codigo}] {linha}')
            print('PRESCRICAO| FIM')
        finally:
            db.session.rollback()


if __name__ == '__main__':
    main()
