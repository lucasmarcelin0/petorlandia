"""Testes do normalizador de posologia (frequência / duração / dedup)."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "posologia_normalizacao_test", ROOT / "services" / "posologia_normalizacao.py"
)
assert SPEC and SPEC.loader
PN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PN)


@pytest.mark.parametrize("bruto,esperado", [
    ("8/8 horas 12/12 horas", "8/8h ou 12/12h"),   # dois protocolos colados
    ("Via Oral: 8-12h.", "a cada 8–12h"),          # via vazou no campo freq
    ("12 em 12 horas", "12/12h"),
    ("12 / 12 horas", "12/12h"),
    ("a cada 24 horas", "24/24h"),
    ("2 vezes ao dia", "12/12h"),
    ("BID", "12/12h"),
    ("TID", "8/8h"),
    ("SID", "24/24h"),
    ("q12h", "12/12h"),
    ("a cada 8 a 12 horas", "a cada 8–12h"),
    ("dose única", "Dose única"),
    ("A critério do médico veterinário", "A critério do médico-veterinário"),
    ("", None),
    (None, None),
])
def test_normalizar_frequencia(bruto, esperado):
    assert PN.normalizar_frequencia(bruto) == esperado


def test_normalizar_frequencia_fallback_intervalo():
    # sem texto parseável, mas com intervalos estruturados do scraper
    assert PN.normalizar_frequencia("conforme bula", 12, 12) == "12/12h"
    assert PN.normalizar_frequencia("conforme bula", 8, 12) == "8/8h a 12/12h"


@pytest.mark.parametrize("bruto,esperado", [
    ("7 a 10 dias. Em processos infecciosos recidivantes por 20 dias", "7 a 10 dias"),
    ("A duração pode variar muito de acordo com a gravidade. Frequentemente usa-", "Conforme avaliação clínica"),
    ("A critério do médico veterinário.", "A critério do médico-veterinário"),
    ("De acordo com protocolo médico.", "Conforme protocolo médico"),
    ("por 14 dias", "14 dias"),
    ("3 semanas", "3 semanas"),
    ("1 a 2 meses", "1 a 2 meses"),
    ("", None),
    (None, None),
])
def test_normalizar_duracao(bruto, esperado):
    assert PN.normalizar_duracao(bruto) == esperado


def test_consolidar_linhas_remove_duplicatas_semanticas():
    linhas = [
        {"dose": "30 mg/kg", "via": "Oral", "frequencia": "12/12h",
         "faixa_peso": "Sem faixa definida", "duracao": "—"},
        {"dose": "30 mg/kg", "via": "Oral", "frequencia": "12/12h",
         "faixa_peso": "Sem faixa definida", "duracao": "7 a 10 dias"},
        {"dose": "0,5 - 1 mg/kg", "via": "Oral", "frequencia": "12/12h",
         "faixa_peso": "", "duracao": "—"},
        {"dose": "0.5-1 mg / kg", "via": "oral", "frequencia": "12/12h",
         "faixa_peso": "", "duracao": "—"},
    ]
    out = PN.consolidar_linhas(linhas)
    assert len(out) == 2
    # ao colapsar, mantém a duração mais informativa
    assert out[0]["duracao"] == "7 a 10 dias"
