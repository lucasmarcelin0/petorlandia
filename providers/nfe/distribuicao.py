"""Distribuição de DF-e (Ambiente Nacional): notas emitidas contra o CNPJ.

É o "baixar XML direto da Receita": a SEFAZ entrega, por NSU, o resumo de
cada NF-e em que a loja é destinatária. Para receber o XML completo, a loja
registra a "Ciência da Operação" (evento 210210) e pede a nota pela chave.

Regras do serviço (NT 2014.002): até 50 documentos por consulta; com
cStat 137 (nada novo) ou 656 (consumo indevido) é preciso esperar 1 hora.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime
import gzip
from typing import Optional

from lxml import etree

from providers.fiscal.sefaz_soap import SoapResult, post_soap12
from providers.nfe.chave import only_digits
from providers.nfe.sefaz_sp.client import (
    SefazSoapResponse,
    _cleanup_cert_files,
    _pfx_to_temp_pem,
)
from providers.nfe.xml_builder import format_dh
from security.xml_safe import safe_lxml_fromstring


NFE_NS = "http://www.portalfiscal.inf.br/nfe"
_NS = {"n": NFE_NS}

URLS_DISTRIBUICAO = {
    "prod": "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
    "homolog": "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
}
URLS_EVENTO_NACIONAL = {
    "prod": "https://www.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx",
    "homolog": "https://hom1.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx",
}
C_ORGAO_NACIONAL = "91"
TP_EVENTO_CIENCIA = "210210"
CSTAT_NADA_NOVO = "137"
CSTAT_ENCONTRADO = "138"
CSTAT_CONSUMO_INDEVIDO = "656"
# Ciência registrada (135) ou já registrada antes (573: duplicidade de evento).
CSTAT_CIENCIA_OK = {"135", "136", "573"}


def nsu15(valor: str | int | None) -> str:
    return f"{int(only_digits(str(valor or '0')) or 0):015d}"


def build_dist_nsu_xml(*, tp_amb: str, c_uf_autor: str, cnpj: str, ult_nsu: str | int) -> str:
    return (
        f'<distDFeInt xmlns="{NFE_NS}" versao="1.01"><tpAmb>{tp_amb}</tpAmb>'
        f"<cUFAutor>{c_uf_autor}</cUFAutor><CNPJ>{only_digits(cnpj)}</CNPJ>"
        f"<distNSU><ultNSU>{nsu15(ult_nsu)}</ultNSU></distNSU></distDFeInt>"
    )


def build_cons_chave_xml(*, tp_amb: str, c_uf_autor: str, cnpj: str, chave: str) -> str:
    return (
        f'<distDFeInt xmlns="{NFE_NS}" versao="1.01"><tpAmb>{tp_amb}</tpAmb>'
        f"<cUFAutor>{c_uf_autor}</cUFAutor><CNPJ>{only_digits(cnpj)}</CNPJ>"
        f"<consChNFe><chNFe>{only_digits(chave)}</chNFe></consChNFe></distDFeInt>"
    )


def build_evento_ciencia_xml(*, chave: str, cnpj: str, tp_amb: str, data_evento: datetime | None = None) -> str:
    """``envEvento`` da Ciência da Operação (assinar o ``infEvento`` antes de enviar)."""
    chave = only_digits(chave)
    return (
        f'<envEvento xmlns="{NFE_NS}" versao="1.00"><idLote>1</idLote>'
        f'<evento versao="1.00"><infEvento Id="ID{TP_EVENTO_CIENCIA}{chave}01">'
        f"<cOrgao>{C_ORGAO_NACIONAL}</cOrgao><tpAmb>{tp_amb}</tpAmb><CNPJ>{only_digits(cnpj)}</CNPJ>"
        f"<chNFe>{chave}</chNFe><dhEvento>{format_dh(data_evento)}</dhEvento>"
        f"<tpEvento>{TP_EVENTO_CIENCIA}</tpEvento><nSeqEvento>1</nSeqEvento><verEvento>1.00</verEvento>"
        '<detEvento versao="1.00"><descEvento>Ciencia da Operacao</descEvento></detEvento>'
        "</infEvento></evento></envEvento>"
    )


# ------------------------------------------------------------------ retorno

@dataclass
class DocumentoDistribuido:
    nsu: str
    schema: str
    xml: str

    @property
    def tipo(self) -> str:
        if self.schema.startswith("resNFe"):
            return "resumo"
        if self.schema.startswith("procNFe"):
            return "completa"
        if self.schema.startswith("resEvento"):
            return "resumo_evento"
        if self.schema.startswith("procEventoNFe"):
            return "evento"
        return "outro"


@dataclass
class RetornoDistribuicao:
    c_stat: Optional[str] = None
    x_motivo: Optional[str] = None
    ult_nsu: Optional[str] = None
    max_nsu: Optional[str] = None
    documentos: list[DocumentoDistribuido] = field(default_factory=list)

    @property
    def nada_novo(self) -> bool:
        return self.c_stat == CSTAT_NADA_NOVO

    @property
    def bloqueio(self) -> bool:
        """Precisa esperar 1 hora antes de consultar de novo."""
        return self.c_stat in {CSTAT_NADA_NOVO, CSTAT_CONSUMO_INDEVIDO}


def _texto(no, caminho: str) -> Optional[str]:
    if no is None:
        return None
    alvo = no.find(caminho, _NS)
    return alvo.text.strip() if alvo is not None and alvo.text else None


def _descompactar(conteudo_b64: str) -> str:
    return gzip.decompress(base64.b64decode(conteudo_b64)).decode("utf-8")


def parse_retorno_distribuicao(xml: str | bytes | None) -> RetornoDistribuicao:
    if not xml:
        return RetornoDistribuicao()
    try:
        root = safe_lxml_fromstring(xml if isinstance(xml, bytes) else xml.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return RetornoDistribuicao()
    ret = root if root.tag == f"{{{NFE_NS}}}retDistDFeInt" else root.find(".//n:retDistDFeInt", _NS)
    if ret is None:
        return RetornoDistribuicao()
    retorno = RetornoDistribuicao(
        c_stat=_texto(ret, "n:cStat"),
        x_motivo=_texto(ret, "n:xMotivo"),
        ult_nsu=_texto(ret, "n:ultNSU"),
        max_nsu=_texto(ret, "n:maxNSU"),
    )
    for doc in ret.findall("n:loteDistDFeInt/n:docZip", _NS):
        try:
            conteudo = _descompactar(doc.text or "")
        except Exception:  # noqa: BLE001 - documento corrompido: ignora só ele
            continue
        retorno.documentos.append(
            DocumentoDistribuido(nsu=nsu15(doc.get("NSU")), schema=doc.get("schema") or "", xml=conteudo)
        )
    return retorno


@dataclass
class ResumoNFe:
    chave: str
    emitente_cnpj: str
    emitente_nome: str
    dh_emi: Optional[str]
    valor: Optional[str]
    situacao: Optional[str]  # 1 autorizada, 2 denegada, 3 cancelada
    protocolo: Optional[str] = None


def parse_resumo_nfe(xml: str) -> Optional[ResumoNFe]:
    try:
        root = safe_lxml_fromstring(xml.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if root.tag != f"{{{NFE_NS}}}resNFe":
        return None
    return ResumoNFe(
        chave=_texto(root, "n:chNFe") or "",
        emitente_cnpj=only_digits(_texto(root, "n:CNPJ") or _texto(root, "n:CPF")),
        emitente_nome=(_texto(root, "n:xNome") or "")[:160],
        dh_emi=_texto(root, "n:dhEmi"),
        valor=_texto(root, "n:vNF"),
        situacao=_texto(root, "n:cSitNFe"),
        protocolo=_texto(root, "n:nProt"),
    )


@dataclass
class EventoDistribuido:
    chave: str
    tp_evento: str


def parse_evento_distribuido(xml: str) -> Optional[EventoDistribuido]:
    """Resumo ou XML de evento (ex.: cancelamento 110111 pelo emitente)."""
    try:
        root = safe_lxml_fromstring(xml.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    chave = _texto(root, ".//n:chNFe")
    tp_evento = _texto(root, ".//n:tpEvento")
    if not chave or not tp_evento:
        return None
    return EventoDistribuido(chave=chave, tp_evento=tp_evento)


# ------------------------------------------------------------------ cliente

class DistribuicaoClient:
    """Fala com os serviços nacionais usando o certificado A1 da loja."""

    def __init__(self, env: str, pfx_bytes: bytes, pfx_password: str | None, timeout: int = 40) -> None:
        self.env = "prod" if env == "prod" else "homolog"
        self.pfx_bytes = pfx_bytes
        self.pfx_password = pfx_password
        self.timeout = timeout

    def _post(self, url: str, service: str, operation: str, xml: str, **extra) -> SefazSoapResponse:
        cert_files = _pfx_to_temp_pem(self.pfx_bytes, self.pfx_password)
        try:
            result: SoapResult = post_soap12(
                url, service, operation, xml, cert_files=cert_files, timeout=self.timeout, **extra
            )
        finally:
            _cleanup_cert_files(cert_files)
        return SefazSoapResponse(result.ok, result.body_xml, result.request_xml, result.response_xml, result.error_message)

    def distribuicao(self, xml: str) -> SefazSoapResponse:
        return self._post(
            URLS_DISTRIBUICAO[self.env],
            "NFeDistribuicaoDFe",
            "nfeDistDFeInteresse",
            xml,
            operation_wrapper="nfeDistDFeInteresse",
            result_tags=("nfeDistDFeInteresseResult",),
        )

    def evento(self, xml_assinado: str) -> SefazSoapResponse:
        return self._post(URLS_EVENTO_NACIONAL[self.env], "NFeRecepcaoEvento4", "nfeRecepcaoEvento", xml_assinado)
