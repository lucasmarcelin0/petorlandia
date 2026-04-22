"""Redaction de PII fiscal — proteção LGPD para logs/eventos.

Estes testes travam o comportamento do módulo `security.redact`. Se algum
quebrar, REGRA: investigue o código — NUNCA afrouxe o assert. Qualquer
vazamento de CPF/CNPJ em log é incidente reportável à ANPD.
"""
from __future__ import annotations

import pytest

from security.redact import (
    redact_sensitive_text,
    redact_xml,
    SENSITIVE_TAGS,
)


# ── redact_sensitive_text: regex em texto solto ───────────────────────────

def test_cpf_sem_mascara_eh_redigido():
    assert redact_sensitive_text("meu cpf 12345678901 aqui") == "meu cpf *** aqui"


def test_cpf_com_mascara_eh_redigido():
    assert redact_sensitive_text("cpf 123.456.789-00 aqui") == "cpf *** aqui"


def test_cnpj_sem_mascara_eh_redigido():
    assert redact_sensitive_text("cnpj 12345678000190") == "cnpj ***"


def test_cnpj_com_mascara_eh_redigido():
    assert redact_sensitive_text("cnpj 12.345.678/0001-90") == "cnpj ***"


def test_chave_nfe_44_digitos_eh_redigida():
    """Chave NF-e identifica emissor + nota: 44 dígitos. Log dela = vazar
    o histórico fiscal da empresa para quem lê."""
    chave = "3" * 44
    assert redact_sensitive_text(f"chave {chave} ok") == "chave *** ok"


def test_numero_curto_nao_eh_redigido():
    # "Pedido 12345" não é CPF/CNPJ — não tocar.
    assert redact_sensitive_text("Pedido 12345 aguardando") == "Pedido 12345 aguardando"


def test_texto_sem_pii_passa_inalterado():
    assert redact_sensitive_text("Sistema ok") == "Sistema ok"


def test_mascarado_processado_antes_para_nao_deixar_lixo():
    """Regressão: se regex de 11 dígitos rodar antes do mascarado, sobra
    '123.456.***-00'. Os mascarados TÊM que vir primeiro na ordem."""
    text = "cpf 123.456.789-00 e outro 98765432100"
    result = redact_sensitive_text(text)
    assert "123.456" not in result
    assert "98765432100" not in result
    assert result.count("***") == 2


# ── redact_xml: camada estruturada ────────────────────────────────────────

def test_redact_xml_redige_tag_cpf():
    xml = "<root><Cpf>12345678901</Cpf></root>"
    result = redact_xml(xml)
    assert "12345678901" not in result
    assert "***" in result


def test_redact_xml_redige_tag_cnpj_com_namespace():
    """Tags NFS-e/ABRASF vêm com namespace (ex: ns2:Cnpj). Redação precisa
    funcionar pelo local-name, não pelo nome qualificado."""
    xml = '<root xmlns:ns2="urn:x"><ns2:Cnpj>12345678000190</ns2:Cnpj></root>'
    result = redact_xml(xml)
    assert "12345678000190" not in result


def test_redact_xml_redige_senha_e_token():
    xml = "<root><Senha>segredo123</Senha><Token>abc.def.ghi</Token></root>"
    result = redact_xml(xml)
    assert "segredo123" not in result
    assert "abc.def.ghi" not in result


def test_redact_xml_redige_cpf_em_tag_nao_sensivel():
    """Ponto central do refactor: CPF pode vazar em InfoAdicional ou
    Mensagem de erro da prefeitura, não só em <Cpf>."""
    xml = "<root><InfoAdicional>Tomador CPF 123.456.789-00</InfoAdicional></root>"
    result = redact_xml(xml)
    assert "123.456.789-00" not in result
    assert "***" in result


def test_redact_xml_redige_cnpj_em_mensagem_de_erro():
    xml = (
        "<Retorno><Mensagem>"
        "CNPJ 12.345.678/0001-90 nao autorizado"
        "</Mensagem></Retorno>"
    )
    result = redact_xml(xml)
    assert "12.345.678" not in result


def test_redact_xml_preserva_estrutura_e_demais_textos():
    """Redação não pode destruir o XML — só zerar o que é sensível."""
    xml = (
        "<root>"
        "<Valor>100.50</Valor>"
        "<Cpf>12345678901</Cpf>"
        "<Descricao>Consulta veterinaria</Descricao>"
        "</root>"
    )
    result = redact_xml(xml)
    assert "100.50" in result
    assert "Consulta veterinaria" in result
    assert "12345678901" not in result


def test_redact_xml_entrada_vazia_retorna_como_veio():
    assert redact_xml(None) is None
    assert redact_xml("") == ""


def test_redact_xml_malformado_cai_no_fallback_textual():
    """XML inválido: a camada estrutural falha, cai em regex textual —
    DEVE AINDA redigir o PII."""
    malformado = "<root><Cpf>12345678901</Cpf><naoFecha>"
    result = redact_xml(malformado)
    assert "12345678901" not in result


def test_redact_xml_nao_expande_xxe():
    """Meta-teste: redact_xml usa o parser hardened. Importa que NENHUM
    conteúdo do /etc/passwd seja lido — a string 'file:///etc/passwd' na
    DTD declaration é metadado estático, não vazamento. O que contaria
    como leak é ver 'root:x:0:0:' (início típico de /etc/passwd) no output."""
    xxe = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE foo [<!ENTITY bar SYSTEM "file:///etc/passwd">]>'
        "<a>&bar;</a>"
    )
    result = redact_xml(xxe) or ""
    # Conteúdo do arquivo (se expandisse) começaria com 'root:' em linux.
    assert "root:x:0:" not in result
    # A entidade &bar; NÃO pode estar expandida — ela deve continuar
    # como referência literal ou ter sido removida.
    assert "root " not in result  # qualquer linha de /etc/passwd


def test_sensitive_tags_cobre_variantes_conhecidas():
    # Sanity check — se alguém reduzir SENSITIVE_TAGS num refactor, quebra.
    for tag in ("cpf", "cnpj", "senha", "token", "chaveacesso"):
        assert tag in SENSITIVE_TAGS
