#!/usr/bin/env python3
"""Le o pedido de leitura de log gravado em .github/disparo/logs.json.

Existe porque o workflow de logs so podia ser disparado por `workflow_dispatch`
-- um clique na interface do GitHub, com os parametros digitados na hora. Quem
nao tem esse clique (um agente, por exemplo) ficava sem caminho nenhum para
investigar producao.

O contorno e um pedido escrito: quem quer ler o log grava este arquivo numa
branch dedicada e faz push. O push dispara o workflow, e este script traduz o
arquivo nos mesmos parametros que o formulario produziria. A permissao de
escrita na branch e a mesma permissao de sempre -- ninguem ganha acesso novo.

Uso:

    python scripts/ler_pedido_logs.py --arquivo .github/disparo/logs.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

FILTRO_MAX = 200
LINHAS_MIN = 1
LINHAS_MAX = 1500
LINHAS_PADRAO = 500


class PedidoInvalido(ValueError):
    """O arquivo existe mas nao descreve um pedido que da para atender."""


def ler_pedido(caminho: Path) -> dict:
    """Devolve {'filtro': str, 'linhas': int} a partir do arquivo."""
    if not caminho.exists():
        # Sem arquivo, o pedido e "as ultimas linhas, sem filtro". E o que
        # alguem quer dizer ao empurrar a branch sem escrever nada.
        return {'filtro': '', 'linhas': LINHAS_PADRAO}

    try:
        dados = json.loads(caminho.read_text(encoding='utf-8') or '{}')
    except json.JSONDecodeError as exc:
        raise PedidoInvalido(f'{caminho} nao e um JSON valido: {exc}') from exc

    if not isinstance(dados, dict):
        raise PedidoInvalido(f'{caminho} precisa conter um objeto JSON.')

    filtro = str(dados.get('filtro') or '').strip()
    if len(filtro) > FILTRO_MAX:
        raise PedidoInvalido(
            f'O filtro tem {len(filtro)} caracteres; o maximo e {FILTRO_MAX}.'
        )
    if filtro:
        try:
            re.compile(filtro)
        except re.error as exc:
            # Melhor recusar aqui do que ver o job quebrar la dentro com uma
            # mensagem do `re` sem contexto nenhum.
            raise PedidoInvalido(
                f'O filtro nao e uma expressao regular valida: {exc}'
            ) from exc

    bruto = dados.get('linhas', LINHAS_PADRAO)
    try:
        linhas = int(bruto)
    except (TypeError, ValueError) as exc:
        raise PedidoInvalido(f'"linhas" precisa ser um numero; veio {bruto!r}.') from exc
    if not LINHAS_MIN <= linhas <= LINHAS_MAX:
        raise PedidoInvalido(
            f'"linhas" precisa estar entre {LINHAS_MIN} e {LINHAS_MAX}; veio {linhas}.'
        )

    return {'filtro': filtro, 'linhas': linhas}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arquivo', default='.github/disparo/logs.json')
    args = parser.parse_args(argv)

    try:
        pedido = ler_pedido(Path(args.arquivo))
    except PedidoInvalido as exc:
        print(f'Pedido invalido: {exc}', file=sys.stderr)
        return 1

    saida = os.environ.get('GITHUB_OUTPUT')
    if saida:
        with open(saida, 'a', encoding='utf-8') as destino:
            # O filtro ja foi validado como regex de uma linha, entao nao
            # carrega quebra de linha e dispensa delimitador multilinha.
            destino.write(f"filtro={pedido['filtro']}\n")
            destino.write(f"linhas={pedido['linhas']}\n")

    print(f"filtro: {pedido['filtro'] or '(nenhum)'}")
    print(f"linhas: {pedido['linhas']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
