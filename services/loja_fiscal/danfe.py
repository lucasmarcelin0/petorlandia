"""Dados do cupom (DANFE NFC-e) para impressão em bobina de 80 mm ou 58 mm.

Segue o Manual do DANFE NFC-e: cabeçalho do emitente, itens, totais e
pagamentos, consulta pela chave (11 blocos de 4 dígitos), QR Code de pelo
menos 25 mm, consumidor, número/série/data/protocolo e mensagens fiscais
(homologação e contingência).
"""
from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

import qrcode

from models import NfceDocumento
from providers.nfce.xml_builder import FORMAS_PAGAMENTO
from providers.nfe.chave import only_digits
from security.xml_safe import safe_lxml_fromstring


NFE_NS = "{http://www.portalfiscal.inf.br/nfe}"


def _qrcode_data_uri(conteudo: str) -> str:
    imagem = qrcode.make(conteudo, box_size=6, border=2)
    buffer = BytesIO()
    imagem.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _chave_em_blocos(chave: str | None) -> str:
    digits = only_digits(chave)
    return " ".join(digits[i:i + 4] for i in range(0, len(digits), 4))


def _formatar_cnpj(cnpj: str | None) -> str:
    d = only_digits(cnpj).zfill(14)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _consumidor(documento: NfceDocumento) -> str:
    xml = documento.xml_autorizado or documento.xml_assinado
    if not xml:
        return "CONSUMIDOR NÃO IDENTIFICADO"
    try:
        root = safe_lxml_fromstring(xml.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return "CONSUMIDOR NÃO IDENTIFICADO"
    cpf = root.find(f".//{NFE_NS}dest/{NFE_NS}CPF")
    if cpf is None or not cpf.text:
        return "CONSUMIDOR NÃO IDENTIFICADO"
    d = cpf.text
    return f"CONSUMIDOR CPF: {d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def _formatar_data(dh: str | None) -> str:
    if not dh or len(dh) < 19:
        return dh or ""
    return f"{dh[8:10]}/{dh[5:7]}/{dh[0:4]} {dh[11:19]}"


def dados_cupom(documento: NfceDocumento) -> dict[str, Any]:
    config = documento.config
    payload = documento.payload_json or {}
    homologacao = documento.ambiente != "producao"
    pagamentos = [
        {
            "forma": FORMAS_PAGAMENTO.get(item.get("t_pag"), "Outros"),
            "valor": item.get("valor"),
        }
        for item in payload.get("pagamentos", [])
    ]
    return {
        "documento": documento,
        "emitente": {
            "razao_social": config.razao_social,
            "nome_fantasia": config.nome_fantasia,
            "cnpj": _formatar_cnpj(config.cnpj),
            "ie": config.inscricao_estadual,
            "endereco": ", ".join(
                parte
                for parte in [
                    f"{config.logradouro}, {config.numero}",
                    config.complemento,
                    config.bairro,
                    f"{config.municipio}/{config.uf}",
                ]
                if parte
            ),
        },
        "itens": payload.get("itens", []),
        "quantidade_itens": len(payload.get("itens", [])),
        "total_produtos": payload.get("total_produtos"),
        "total_desconto": payload.get("total_desconto"),
        "total_nota": payload.get("total_nota"),
        "total_pago": payload.get("total_pago"),
        "troco": payload.get("troco"),
        "tributos": payload.get("tributos"),
        "pagamentos": pagamentos,
        "chave_blocos": _chave_em_blocos(documento.chave),
        "url_chave": documento.url_chave,
        "qrcode_img": _qrcode_data_uri(documento.qrcode) if documento.qrcode else None,
        "consumidor": _consumidor(documento),
        "data_emissao": _formatar_data(documento.dh_emi),
        "data_autorizacao": _formatar_data(documento.dh_recbto),
        "homologacao": homologacao,
        "contingencia": documento.tp_emis == "9" and documento.status != "autorizada",
        "mensagem": config.mensagem_cupom,
    }
