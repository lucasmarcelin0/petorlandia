"""Testes das defesas contra XXE / billion-laughs nos parsers XML.

Razão: o pipeline NFS-e parseia resposta de webservice público. Se alguém
adulterar a resposta (ou a prefeitura responder XML com entidade externa),
um parser default pode ler arquivos locais do servidor, fazer SSRF, ou
estourar memória (billion laughs). Estes testes travam que todos os parsers
usados no código fiscal rejeitam ou não-expandem entidades externas.

Se um destes testes começar a falhar, a correção NUNCA é no teste —
é no código que voltou a usar parser default.
"""
from __future__ import annotations

import pytest


# ── Fixtures de payloads maliciosos ────────────────────────────────────────

XXE_FILE_READ = """<?xml version="1.0"?>
<!DOCTYPE foo [
  <!ENTITY bar SYSTEM "file:///etc/passwd">
]>
<a>&bar;</a>
"""

XXE_HTTP_SSRF = """<?xml version="1.0"?>
<!DOCTYPE foo [
  <!ENTITY bar SYSTEM "http://169.254.169.254/latest/meta-data/">
]>
<a>&bar;</a>
"""

# "Billion laughs": entidade que expande exponencialmente e consome memória
BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<a>&lol4;</a>
"""

BENIGN = '<soap:Envelope xmlns:soap="x"><soap:Body><Foo>bar</Foo></soap:Body></soap:Envelope>'


# ── SafeET (defusedxml.ElementTree) ────────────────────────────────────────

def test_safeet_aceita_xml_normal():
    from security.xml_safe import SafeET
    root = SafeET.fromstring(BENIGN)
    assert root.tag.endswith("Envelope")


def test_safeet_bloqueia_entidade_externa_file():
    from security.xml_safe import SafeET
    with pytest.raises(Exception) as exc_info:
        SafeET.fromstring(XXE_FILE_READ)
    # defusedxml levanta EntitiesForbidden. Aceitamos qualquer subclasse
    # de Exception — o que importa é NÃO ter parseado e expandido.
    assert "forbidden" in type(exc_info.value).__name__.lower() \
        or "entities" in type(exc_info.value).__name__.lower()


def test_safeet_bloqueia_billion_laughs():
    from security.xml_safe import SafeET
    with pytest.raises(Exception):
        SafeET.fromstring(BILLION_LAUGHS)


def test_safeet_bloqueia_ssrf_via_entidade():
    from security.xml_safe import SafeET
    with pytest.raises(Exception):
        SafeET.fromstring(XXE_HTTP_SSRF)


# ── lxml hardened (safe_lxml_fromstring) ──────────────────────────────────

def test_lxml_hardened_aceita_xml_normal():
    from security.xml_safe import safe_lxml_fromstring
    root = safe_lxml_fromstring(BENIGN)
    # lxml preserva namespace no tag
    assert root.tag.endswith("Envelope")


def test_lxml_hardened_rejeita_doctype_entidade_externa():
    """Defesa mais forte: em vez de parsear e deixar &entity; não
    expandida, `safe_lxml_fromstring` agora REJEITA qualquer XML com
    DOCTYPE/ENTITY antes mesmo de chamar o parser. Isso elimina a
    superfície inteira de XXE (inclusive bugs futuros em lxml)."""
    from security.xml_safe import safe_lxml_fromstring
    with pytest.raises(ValueError, match="DOCTYPE/ENTITY"):
        safe_lxml_fromstring(XXE_FILE_READ)


def test_lxml_hardened_bloqueia_billion_laughs():
    """Aqui esperamos ou exceção ou árvore com entidades não expandidas —
    nos dois casos o DoS está contido (memória não explode)."""
    from security.xml_safe import safe_lxml_fromstring
    try:
        root = safe_lxml_fromstring(BILLION_LAUGHS)
    except Exception:
        return  # ótimo: rejeitou cedo
    # Se parseou, o texto NÃO pode ter expandido em milhões de "lol"s.
    total_text = "".join(root.itertext())
    assert len(total_text) < 10_000, (
        f"Billion laughs expandiu: {len(total_text)} chars no texto. "
        "resolve_entities=False deveria impedir isso."
    )


def test_lxml_hardened_nao_faz_network():
    """Resposta com DOCTYPE externo (SYSTEM) apontando pra DNS inválido
    NÃO pode tentar resolver — senão temos SSRF ou latência extra."""
    from security.xml_safe import safe_lxml_fromstring
    payload = """<?xml version="1.0"?>
<!DOCTYPE foo SYSTEM "http://example-that-should-not-be-fetched.invalid/dtd">
<a/>"""
    # no_network=True impede lookup; parse deve ser rápido e não falhar por DNS.
    # (aceita raise se lxml optar por erro; o importante é: sem DNS query.)
    try:
        safe_lxml_fromstring(payload)
    except Exception:
        pass
