"""Orçamento de memória do parser da planilha PMO (dados sintéticos).

O dyno web tem 512 MB: o sync do PMO chegou a 1,2 GB em produção. Medido com
tracemalloc, o parser em si gasta ~7 MB para 5.000 linhas; o pico vem das
leituras com includeGridData (cores/notas de cada célula). Este teste impede
que o parser vire também um gargalo.
"""

import tracemalloc

from services.vacina_pmo_service import parse_vacina_pmo_rows

LINHAS = 5000
ORCAMENTO_MB = 40


def _linha(i):
    return [
        f"Tutor {i} Silva", f"Rua {i % 300}", str(100 + i), "Casa", "Jardim Benini",
        f"1699{i:07d}", "", "1", "1", f"Rex {i}, Mimi {i}",
        "", "", "", "", "", "", "28/05/2026", "Manhã",
    ]


def test_parser_do_pmo_cabe_no_orcamento_de_memoria():
    linhas = [_linha(i) for i in range(LINHAS)]
    tracemalloc.start()
    try:
        resultado = parse_vacina_pmo_rows(linhas)
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(resultado) == LINHAS
    assert pico / 2**20 < ORCAMENTO_MB, f"parser usou {pico / 2**20:.1f} MB para {LINHAS} linhas"
