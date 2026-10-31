"""QR Code da NFC-e (Manual do DANFE NFC-e e QR Code, NT 2025.001).

Versão 3 (padrão):
    - online:  ``<url>?p=<chave>|3|<tpAmb>`` — não usa CSC.
    - offline (contingência, tpEmis=9):
      ``<url>?p=<chave>|3|<tpAmb>|<dia>|<vNF>|<tp_idDest>|<idDest>|<assinatura>``,
      com a assinatura RSA-SHA1 (Base64) dos sete primeiros parâmetros,
      separadores incluídos, feita com o certificado do emitente.

Versão 2 (reserva, se a UF ainda exigir o CSC):
    - online: ``<url>?p=<chave>|2|<tpAmb>|<idCSC>|<hash>``, com o hash SHA-1
      (hex maiúsculo) dos quatro parâmetros concatenados ao CSC.
"""
from __future__ import annotations

import base64
from decimal import Decimal
import hashlib

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding


# Endereços da SEFAZ-SP publicados no portal da NFC-e (Web Services).
URLS_SP = {
    "1": {
        "qrcode": "https://www.nfce.fazenda.sp.gov.br/NFCeConsultaPublica/Paginas/ConsultaQRCode.aspx",
        "chave": "https://www.nfce.fazenda.sp.gov.br/NFCeConsultaPublica",
    },
    "2": {
        "qrcode": "https://www.homologacao.nfce.fazenda.sp.gov.br/NFCeConsultaPublica/Paginas/ConsultaQRCode.aspx",
        "chave": "https://www.homologacao.nfce.fazenda.sp.gov.br/NFCeConsultaPublica",
    },
}


def formatar_valor(valor: Decimal | int | float | str) -> str:
    return f"{Decimal(str(valor)):.2f}"


def qrcode_v3_online(url_qrcode: str, chave: str, tp_amb: str) -> str:
    return f"{url_qrcode}?p={chave}|3|{tp_amb}"


def parametros_v3_offline(
    chave: str,
    tp_amb: str,
    dh_emi: str,
    v_nf: Decimal,
    dest_tipo: str | None = None,
    dest_id: str | None = None,
) -> str:
    """Os sete parâmetros assinados no QR Code offline (com separadores)."""
    dia = dh_emi[8:10]
    tipo = dest_tipo or ""
    ident = (dest_id or "") if tipo else ""
    return f"{chave}|3|{tp_amb}|{dia}|{formatar_valor(v_nf)}|{tipo}|{ident}"


def qrcode_v3_offline(
    url_qrcode: str,
    chave: str,
    tp_amb: str,
    dh_emi: str,
    v_nf: Decimal,
    private_key,
    dest_tipo: str | None = None,
    dest_id: str | None = None,
) -> str:
    """QR Code de contingência; ``dest_tipo``: 1=CNPJ, 2=CPF, 3=estrangeiro."""
    base = parametros_v3_offline(chave, tp_amb, dh_emi, v_nf, dest_tipo, dest_id)
    assinatura = private_key.sign(base.encode("utf-8"), padding.PKCS1v15(), hashes.SHA1())
    return f"{url_qrcode}?p={base}|{base64.b64encode(assinatura).decode('ascii')}"


def qrcode_v2_online(url_qrcode: str, chave: str, tp_amb: str, id_csc: str | int, csc: str) -> str:
    id_token = str(int(str(id_csc).strip()))
    base = f"{chave}|2|{tp_amb}|{id_token}"
    hash_hex = hashlib.sha1(f"{base}{csc.strip()}".encode("utf-8")).hexdigest().upper()
    return f"{url_qrcode}?p={base}|{hash_hex}"
