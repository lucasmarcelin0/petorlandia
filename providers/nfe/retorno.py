"""Leitura dos retornos da SEFAZ para NF-e/NFC-e 4.00.

O retorno síncrono (``retEnviNFe``) traz dois ``cStat``: o do LOTE (104,
"Lote processado") e o da NOTA, dentro de ``protNFe/infProt`` (100,
"Autorizado o uso"). Ler o primeiro ``cStat`` do XML confunde os dois e
marca como rejeitada uma nota autorizada; por isso a leitura é explícita.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from lxml import etree

from security.xml_safe import safe_lxml_fromstring


NFE_NS = "http://www.portalfiscal.inf.br/nfe"
_NS = {"n": NFE_NS}

# Autorizado o uso (100) e autorizado fora de prazo (150).
CSTAT_AUTORIZADO = frozenset({"100", "150"})
# Uso denegado: a numeração fica consumida e a nota não pode ser reenviada.
CSTAT_DENEGADO = frozenset({"110", "301", "302", "303"})
# Lote recebido / em processamento (fluxo assíncrono).
CSTAT_LOTE_EM_PROCESSAMENTO = frozenset({"103", "105"})


@dataclass
class AutorizacaoRetorno:
    c_stat_lote: Optional[str] = None
    x_motivo_lote: Optional[str] = None
    n_rec: Optional[str] = None
    c_stat: Optional[str] = None
    x_motivo: Optional[str] = None
    n_prot: Optional[str] = None
    ch_nfe: Optional[str] = None
    dh_recbto: Optional[str] = None
    prot_nfe_xml: Optional[str] = None

    @property
    def autorizado(self) -> bool:
        return self.c_stat in CSTAT_AUTORIZADO

    @property
    def denegado(self) -> bool:
        return self.c_stat in CSTAT_DENEGADO

    @property
    def em_processamento(self) -> bool:
        return self.prot_nfe_xml is None and self.c_stat_lote in CSTAT_LOTE_EM_PROCESSAMENTO


def _text(node: etree._Element | None, path: str) -> Optional[str]:
    if node is None:
        return None
    found = node.find(path, _NS)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def _parse(xml: str | bytes | None) -> etree._Element | None:
    if not xml:
        return None
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml
    try:
        return safe_lxml_fromstring(raw)
    except Exception:  # noqa: BLE001 - retorno inválido vira "sem retorno"
        return None


def _find_first(root: etree._Element, local_name: str) -> etree._Element | None:
    if root.tag == f"{{{NFE_NS}}}{local_name}":
        return root
    return root.find(f".//n:{local_name}", _NS)


def parse_autorizacao(xml: str | bytes | None) -> AutorizacaoRetorno:
    """Lê ``retEnviNFe`` (síncrono) ou ``retConsReciNFe`` (consulta de recibo)."""
    root = _parse(xml)
    if root is None:
        return AutorizacaoRetorno()

    ret = _find_first(root, "retEnviNFe")
    if ret is None:
        ret = _find_first(root, "retConsReciNFe")
    if ret is None:
        ret = root

    result = AutorizacaoRetorno(
        c_stat_lote=_text(ret, "n:cStat"),
        x_motivo_lote=_text(ret, "n:xMotivo"),
        n_rec=_text(ret, "n:infRec/n:nRec") or _text(ret, "n:nRec"),
    )
    prot = ret.find("n:protNFe", _NS)
    if prot is None:
        prot = ret.find(".//n:protNFe", _NS)
    if prot is not None:
        inf_prot = prot.find("n:infProt", _NS)
        result.c_stat = _text(inf_prot, "n:cStat")
        result.x_motivo = _text(inf_prot, "n:xMotivo")
        result.n_prot = _text(inf_prot, "n:nProt")
        result.ch_nfe = _text(inf_prot, "n:chNFe")
        result.dh_recbto = _text(inf_prot, "n:dhRecbto")
        result.prot_nfe_xml = etree.tostring(prot, encoding="unicode")
    else:
        result.c_stat = result.c_stat_lote
        result.x_motivo = result.x_motivo_lote
    return result


@dataclass
class EventoRetorno:
    c_stat_lote: Optional[str] = None
    c_stat: Optional[str] = None
    x_motivo: Optional[str] = None
    n_prot: Optional[str] = None
    ret_evento_xml: Optional[str] = None

    @property
    def registrado(self) -> bool:
        # 135: evento registrado e vinculado; 136: registrado sem vínculo;
        # 155: cancelamento homologado fora de prazo.
        return self.c_stat in {"135", "136", "155"}


def parse_evento(xml: str | bytes | None) -> EventoRetorno:
    root = _parse(xml)
    if root is None:
        return EventoRetorno()
    ret_env = _find_first(root, "retEnvEvento")
    if ret_env is None:
        ret_env = root
    result = EventoRetorno(c_stat_lote=_text(ret_env, "n:cStat"))
    ret_evento = ret_env.find(".//n:retEvento", _NS)
    if ret_evento is not None:
        inf = ret_evento.find("n:infEvento", _NS)
        result.c_stat = _text(inf, "n:cStat")
        result.x_motivo = _text(inf, "n:xMotivo")
        result.n_prot = _text(inf, "n:nProt")
        result.ret_evento_xml = etree.tostring(ret_evento, encoding="unicode")
    else:
        result.c_stat = result.c_stat_lote
        result.x_motivo = _text(ret_env, "n:xMotivo")
    return result


@dataclass
class SituacaoRetorno:
    c_stat: Optional[str] = None
    x_motivo: Optional[str] = None
    prot_nfe_xml: Optional[str] = None
    n_prot: Optional[str] = None

    @property
    def autorizado(self) -> bool:
        return self.c_stat in CSTAT_AUTORIZADO


def parse_consulta_situacao(xml: str | bytes | None) -> SituacaoRetorno:
    """Lê ``retConsSitNFe``: situação atual de uma chave na SEFAZ."""
    root = _parse(xml)
    if root is None:
        return SituacaoRetorno()
    ret = _find_first(root, "retConsSitNFe")
    if ret is None:
        ret = root
    result = SituacaoRetorno(c_stat=_text(ret, "n:cStat"), x_motivo=_text(ret, "n:xMotivo"))
    prot = ret.find("n:protNFe", _NS)
    if prot is not None:
        inf_prot = prot.find("n:infProt", _NS)
        prot_c_stat = _text(inf_prot, "n:cStat")
        if prot_c_stat:
            result.c_stat = prot_c_stat
            result.x_motivo = _text(inf_prot, "n:xMotivo")
        result.n_prot = _text(inf_prot, "n:nProt")
        result.prot_nfe_xml = etree.tostring(prot, encoding="unicode")
    return result


@dataclass
class InutilizacaoRetorno:
    c_stat: Optional[str] = None
    x_motivo: Optional[str] = None
    n_prot: Optional[str] = None
    ret_xml: Optional[str] = None

    @property
    def homologada(self) -> bool:
        return self.c_stat == "102"


def parse_inutilizacao(xml: str | bytes | None) -> InutilizacaoRetorno:
    root = _parse(xml)
    if root is None:
        return InutilizacaoRetorno()
    ret = _find_first(root, "retInutNFe")
    if ret is None:
        ret = root
    inf = ret.find("n:infInut", _NS)
    return InutilizacaoRetorno(
        c_stat=_text(inf, "n:cStat"),
        x_motivo=_text(inf, "n:xMotivo"),
        n_prot=_text(inf, "n:nProt"),
        ret_xml=etree.tostring(ret, encoding="unicode"),
    )
