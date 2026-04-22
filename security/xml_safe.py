"""Parsing de XML externo com defesa contra XXE / DoS.

Por que esse módulo existe:
    O parser padrão do lxml e do `xml.etree.ElementTree` resolve entidades
    externas por default. Se a prefeitura (ou um man-in-the-middle) responder
    um XML com entidades malformadas, o processo pode:

      - Ler arquivos locais do servidor (LFI)
      - Fazer requests arbitrários a partir do servidor (SSRF)
      - Consumir toda a memória (billion laughs attack)

    Em NFS-e isso é particularmente grave porque o código parseia resposta
    de webservice público, assinado ou não, sem que a gente controle o
    remetente. OWASP classifica como A04:2021 (XML External Entity Injection).

Uso:
    - Stdlib ElementTree com defesa:     from security.xml_safe import SafeET
                                          root = SafeET.fromstring(xml)
    - lxml (quando precisar de XPath):    from security.xml_safe import safe_lxml_fromstring
                                          root = safe_lxml_fromstring(xml_bytes)

    Ambos lançam as mesmas exceções do módulo original em caso de XML inválido.

Regra: **todo XML que vem de fora do processo** (HTTP response, upload,
conteúdo de banco assinado por terceiro, webservice) passa por um destes
dois APIs. XML que a gente mesmo gera com Element/SubElement não precisa
defuse, mas também não fere usar.
"""
from __future__ import annotations

from typing import Any, Union

# stdlib — usamos defusedxml.ElementTree como drop-in do xml.etree.ElementTree
from defusedxml import ElementTree as SafeET  # noqa: F401  (re-export)

from lxml import etree as _lxml_etree


def _reject_forbidden_xml_markup(xml: Union[str, bytes]) -> None:
    raw = xml if isinstance(xml, bytes) else xml.encode("utf-8")
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("DOCTYPE/ENTITY declarations are not allowed in external XML.")


# Parser lxml hardened — desliga as três portas de ataque conhecidas.
#   resolve_entities=False → não expande &entity; (billion laughs / LFI / SSRF)
#   no_network=True        → não busca DTD externo por HTTP
#   load_dtd=False         → nem local, nem externo
#   huge_tree=False        → rejeita árvores absurdamente profundas/grandes
#
# Criamos um parser novo a cada chamada: XMLParser do lxml não é thread-safe
# e reutilizar o mesmo entre threads do Flask/Celery é fonte clássica de bug.
def _build_safe_parser() -> "_lxml_etree.XMLParser":
    return _lxml_etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        recover=False,
    )


def safe_lxml_fromstring(xml: Union[str, bytes]) -> Any:
    """Parse seguro de XML externo com lxml. Retorna Element."""
    _reject_forbidden_xml_markup(xml)
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    return _lxml_etree.fromstring(xml, parser=_build_safe_parser())
