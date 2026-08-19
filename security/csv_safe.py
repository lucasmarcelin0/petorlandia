"""Escrita de CSV com defesa contra injeção de fórmula.

Por que esse módulo existe:
    Excel, LibreOffice e Google Sheets interpretam como fórmula toda célula que
    começa com ``=``, ``+``, ``-``, ``@`` ou com os caracteres de início de
    macro (tab e carriage return). Como o conteúdo dos nossos exports vem do
    que tutores e profissionais digitaram (nome, CRMV, observação), basta
    alguém cadastrar um animal chamado ``=HYPERLINK("https://evil.test")`` para
    que a planilha de quem abrir o relatório execute aquilo.

    O ataque não precisa de nenhuma falha no servidor: o CSV sai correto, e o
    dano acontece na máquina de quem abre. OWASP classifica como CSV Injection
    (também chamada de Formula Injection).

Uso:
    from security.csv_safe import safe_csv_writer

    writer = safe_csv_writer(output)          # no lugar de csv.writer(output)
    writer.writerow([nome, crmv, observacao])

    Para DictWriter: safe_csv_dict_writer(output, fieldnames=[...]).

A defesa é o prefixo de apóstrofo recomendado pela OWASP: a planilha exibe o
texto original e não avalia nada. Números, datas e valores vazios passam
intactos, então o CSV continua servindo para reimportação.

Regra: **todo CSV que carrega texto digitado por usuário** usa este módulo.
"""

from __future__ import annotations

import csv
from typing import Any

# Caracteres que fazem a planilha tratar a célula como fórmula/macro.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def escape_csv_value(value: Any) -> Any:
    """Neutraliza uma célula que a planilha interpretaria como fórmula.

    Mantém o tipo original de valores não textuais (int, float, date, None)
    para que o CSV continue sendo reimportável sem conversões extras.
    """
    if not isinstance(value, str):
        return value
    if not value.startswith(_FORMULA_PREFIXES):
        return value
    return f"'{value}"


def _escape_row(row):
    return [escape_csv_value(cell) for cell in row]


class _SafeWriter:
    """Envelopa ``csv.writer`` aplicando o escape em cada célula."""

    def __init__(self, writer):
        self._writer = writer

    def writerow(self, row):
        return self._writer.writerow(_escape_row(row))

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)

    def __getattr__(self, name):
        return getattr(self._writer, name)


class _SafeDictWriter:
    """Envelopa ``csv.DictWriter``; o cabeçalho é nosso, então não é escapado."""

    def __init__(self, writer):
        self._writer = writer

    def writeheader(self):
        return self._writer.writeheader()

    def writerow(self, row):
        return self._writer.writerow(
            {key: escape_csv_value(value) for key, value in row.items()}
        )

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)

    def __getattr__(self, name):
        return getattr(self._writer, name)


def safe_csv_writer(fileobj, **kwargs) -> _SafeWriter:
    return _SafeWriter(csv.writer(fileobj, **kwargs))


def safe_csv_dict_writer(fileobj, fieldnames, **kwargs) -> _SafeDictWriter:
    return _SafeDictWriter(csv.DictWriter(fileobj, fieldnames=fieldnames, **kwargs))
