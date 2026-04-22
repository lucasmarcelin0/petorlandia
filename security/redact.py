"""Redaction de PII fiscal (CPF, CNPJ, senhas, tokens) para logs e auditoria.

Por que esse módulo existe:
    Temos três lugares que logam XML de resposta fiscal: (1) logger do Flask
    em caso de falha, (2) `FiscalEvent.response_xml` no banco para auditoria,
    (3) e-mails/alertas de erro pra operação. Em qualquer um deles, deixar
    CPF/CNPJ/Senha do emissor ou do tomador vazar é LGPD Art. 46 (incidente
    de segurança reportável à ANPD).

    A versão antiga redatava *só por nome de tag* (ex: `<Cpf>…</Cpf>`). Mas
    CPF/CNPJ vazam em três outros caminhos:

      1. Dentro de `<InfoAdicional>CPF do tomador: 123.456.789-00</InfoAdicional>`
         — texto livre em tag não-sensível.
      2. Mensagens de erro da prefeitura: `<Mensagem>CNPJ 12.345.678/0001-90
         não autorizado</Mensagem>`.
      3. Em formato mascarado (`123.456.789-00`) que os padrões `\\d{11}\\b`
         não pegavam.

    Este módulo cobre todos os três caminhos com uma única chamada pública:
    `redact_xml(xml)`.
"""
from __future__ import annotations

import re
from typing import Iterable

from lxml import etree

from security.xml_safe import safe_lxml_fromstring


# Tags que por si só são 100% sensíveis — texto inteiro vai pra ***.
# Case-insensitive no match; cobrir variações ABRASF (Cpf, CPF, cpf) e
# NF-e (CPF, CNPJ, IE) e Betha (Senha, Token).
SENSITIVE_TAGS: frozenset[str] = frozenset({
    "cpf",
    "cnpj",
    "ie",
    "inscricaoestadual",
    "inscricaomunicipal",
    "im",
    "senha",
    "password",
    "pwd",
    "token",
    "chaveacesso",  # chave NF-e (44 dígitos) identifica emissor+nota
    "clientsecret",
    "secret",
})


# Regexes de PII em TEXTO LIVRE (aparecem dentro de tags não-sensíveis
# ou em logs em texto puro). Ordem importa: os mascarados vêm primeiro
# para não serem destruídos pelos \d{11}/\d{14} que capturariam "789" do
# meio de "123.456.789-00" deixando lixo.
_PII_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # CNPJ mascarado: 12.345.678/0001-90
    (re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"), "***"),
    # CPF mascarado: 123.456.789-00
    (re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"), "***"),
    # Chave NF-e: 44 dígitos contíguos
    (re.compile(r"\b\d{44}\b"), "***"),
    # CNPJ sem máscara: 14 dígitos contíguos
    (re.compile(r"\b\d{14}\b"), "***"),
    # CPF sem máscara: 11 dígitos contíguos
    (re.compile(r"\b\d{11}\b"), "***"),
)


def redact_sensitive_text(text: str) -> str:
    """Mascara CPF/CNPJ/chave em texto solto (útil pra logs puros e
    pra sanitizar cada text-node do XML). Idempotente: já redatado
    permanece redatado."""
    if not text:
        return text
    redacted = text
    for pattern, replacement in _PII_TEXT_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _normalize_local_tag(tag: object) -> str:
    """Retorna o local-name do tag em lowercase (ignora namespace)."""
    if not isinstance(tag, str):
        return ""
    return tag.split("}", 1)[-1].lower()


def redact_xml(xml: str | None, extra_tags: Iterable[str] | None = None) -> str | None:
    """Redige PII em XML fiscal.

    Estratégia em duas camadas:

      1. **Camada estruturada (primeira tentativa)**: parseia o XML (com
         parser hardened anti-XXE), zera o texto de toda tag listada em
         SENSITIVE_TAGS, e AINDA aplica `redact_sensitive_text` ao texto
         de todas as demais tags — pegando CPF/CNPJ que vazam dentro de
         `<InfoAdicional>` ou `<Mensagem>`.
      2. **Camada textual (fallback)**: se o XML for malformado e o parse
         falhar, regex-redige a nível de string. Menos preciso, mas
         nunca pior que plaintext.

    Args:
        xml: string XML (pode ter BOM/whitespace). None/vazio retorna como veio.
        extra_tags: conjunto de nomes adicionais a considerar sensíveis (para
            domínios específicos que adicionem novas tags no futuro).

    Returns:
        XML com PII substituída por '***'. Sempre que possível retorna o XML
        re-serializado pelo lxml; se o parse falhou, volta a string filtrada
        por regex.
    """
    if not xml:
        return xml

    sensitive = set(SENSITIVE_TAGS)
    if extra_tags:
        sensitive.update(tag.lower() for tag in extra_tags)

    try:
        root = safe_lxml_fromstring(xml)
    except (etree.XMLSyntaxError, ValueError):
        # Fallback textual. Cobre tags conhecidas + regex de PII solta.
        return _redact_textual(xml, sensitive)

    # Camada estruturada: varre todo nodo.
    for node in root.iter():
        local = _normalize_local_tag(node.tag)
        if not node.text:
            continue
        if local in sensitive:
            node.text = "***"
        else:
            # Texto livre dentro de tag não-sensível: aplica regex por
            # segurança (CPF em InfoAdicional, CNPJ em Mensagem de erro).
            node.text = redact_sensitive_text(node.text)
    return etree.tostring(root, encoding="unicode")


def _redact_textual(xml: str, sensitive_tags: set[str]) -> str:
    """Fallback usado quando o XML não parseia. Best-effort."""
    text = xml
    # Redige texto entre tags sensíveis (<Cpf>...</Cpf>).
    for tag in sensitive_tags:
        text = re.sub(
            rf"(<(?:\w+:)?{re.escape(tag)}\b[^>]*>)(.*?)(</(?:\w+:)?{re.escape(tag)}>)",
            r"\1***\3",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    # E aplica os regex de PII soltos.
    text = redact_sensitive_text(text)
    return text
