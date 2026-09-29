"""Endereço a partir do CEP (ViaCEP), para a ficha SINAN.

A consulta passa pelo servidor: o ViaCEP vê o IP do servidor, não o de quem
preenche, e a página não precisa liberar um domínio externo. Só o CEP sai
daqui; nome e demais dados da ficha nunca são enviados.
"""
from __future__ import annotations

import re
from collections import OrderedDict

VIACEP_URL = "https://viacep.com.br/ws/{cep}/json/"
TEMPO_LIMITE = 4
_CACHE_MAXIMO = 512
_cache: OrderedDict[str, dict] = OrderedDict()


class CepIndisponivel(RuntimeError):
    """O serviço de CEP não respondeu; a ficha segue preenchida à mão."""


def normalizar_cep(valor: str) -> str:
    digitos = re.sub(r"\D", "", str(valor or ""))
    if len(digitos) != 8:
        raise ValueError("Informe o CEP com 8 números.")
    return digitos


def buscar_cep(valor: str) -> dict | None:
    """Devolve UF, município (com código IBGE), bairro e logradouro, ou None se o CEP não existe."""
    import requests

    cep = normalizar_cep(valor)
    if cep in _cache:
        _cache.move_to_end(cep)
        return dict(_cache[cep])
    try:
        resposta = requests.get(VIACEP_URL.format(cep=cep), timeout=TEMPO_LIMITE,
                                headers={"Accept": "application/json"})
    except requests.RequestException as exc:
        raise CepIndisponivel("Serviço de CEP indisponível.") from exc
    if resposta.status_code == 400:
        return None
    if resposta.status_code != 200:
        raise CepIndisponivel(f"Serviço de CEP respondeu {resposta.status_code}.")
    try:
        dados = resposta.json()
    except ValueError as exc:
        raise CepIndisponivel("Resposta inválida do serviço de CEP.") from exc
    if not isinstance(dados, dict) or dados.get("erro"):
        return None
    endereco = {
        "cep": cep,
        "uf": str(dados.get("uf") or "").strip()[:2].upper(),
        "municipio": str(dados.get("localidade") or "").strip()[:120],
        "codigo_ibge": re.sub(r"\D", "", str(dados.get("ibge") or ""))[:7],
        "bairro": str(dados.get("bairro") or "").strip()[:120],
        "logradouro": str(dados.get("logradouro") or "").strip()[:180],
    }
    _cache[cep] = endereco
    if len(_cache) > _CACHE_MAXIMO:
        _cache.popitem(last=False)
    return dict(endereco)
