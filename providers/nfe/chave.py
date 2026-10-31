"""Chave de acesso da NF-e/NFC-e (44 dígitos).

Composição: cUF(2) AAMM(4) CNPJ(14) mod(2) serie(3) nNF(9) tpEmis(1)
cNF(8) cDV(1). O AAMM deve ser o da data de emissão (``dhEmi``) e o código
numérico ``cNF`` é aleatório e diferente do número da nota.
"""
from __future__ import annotations

from dataclasses import dataclass
import secrets


@dataclass(frozen=True)
class ChaveAcesso:
    chave: str

    @property
    def c_dv(self) -> str:
        return self.chave[-1]

    @property
    def c_nf(self) -> str:
        return self.chave[35:43]

    @property
    def tp_emis(self) -> str:
        return self.chave[34]

    @property
    def modelo(self) -> str:
        return self.chave[20:22]

    @property
    def serie(self) -> int:
        return int(self.chave[22:25])

    @property
    def numero(self) -> int:
        return int(self.chave[25:34])


def only_digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def mod11(value: str) -> int:
    """Dígito verificador da chave (módulo 11, pesos 2 a 9)."""
    weights = list(range(2, 10))
    total = 0
    for index, digit in enumerate(reversed(value)):
        total += int(digit) * weights[index % len(weights)]
    remainder = total % 11
    return 0 if remainder in (0, 1) else 11 - remainder


def gerar_codigo_numerico(numero: int) -> str:
    """cNF aleatório de 8 dígitos, diferente do número da nota."""
    numero_txt = str(int(numero)).zfill(8)[-8:]
    while True:
        candidato = f"{secrets.randbelow(10**8):08d}"
        if candidato != numero_txt:
            return candidato


def montar_chave(
    *,
    c_uf: str,
    dh_emi: str,
    cnpj: str,
    modelo: str,
    serie: int | str,
    numero: int,
    tp_emis: str = "1",
    c_nf: str | None = None,
) -> ChaveAcesso:
    """Monta a chave; ``dh_emi`` no formato do leiaute (AAAA-MM-DDThh:mm:ss±hh:mm)."""
    aamm = f"{dh_emi[2:4]}{dh_emi[5:7]}"
    if not aamm.isdigit():
        raise ValueError("dhEmi inválido para a chave de acesso.")
    cnpj_digits = only_digits(cnpj).zfill(14)
    if len(cnpj_digits) != 14:
        raise ValueError("CNPJ do emitente inválido para a chave de acesso.")
    codigo = c_nf or gerar_codigo_numerico(numero)
    base = (
        f"{int(c_uf):02d}{aamm}{cnpj_digits}{int(modelo):02d}"
        f"{int(serie):03d}{int(numero):09d}{int(tp_emis)}{int(codigo):08d}"
    )
    if len(base) != 43:
        raise ValueError("Dados insuficientes para montar a chave de acesso.")
    return ChaveAcesso(f"{base}{mod11(base)}")
