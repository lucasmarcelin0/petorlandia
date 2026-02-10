"""Builders de XML para NFS-e (Betha/ABRASF)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable

from lxml import etree


def _text(value: Any) -> str:
    return str(value) if value is not None else ""


def _format_decimal(value: Any) -> str:
    if value is None:
        return "0.00"
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    try:
        return f"{Decimal(str(value)):.2f}"
    except Exception:  # noqa: BLE001 - proteção para valores inválidos
        return "0.00"


def _append_child(parent: etree._Element, tag: str, text: Any | None) -> etree._Element:
    node = etree.SubElement(parent, tag)
    if text is not None:
        node.text = _text(text)
    return node


def _build_endereco(parent: etree._Element, endereco: dict[str, Any] | None) -> None:
    if not endereco:
        return
    endereco_node = etree.SubElement(parent, "Endereco")
    _append_child(endereco_node, "Endereco", endereco.get("logradouro"))
    _append_child(endereco_node, "Numero", endereco.get("numero"))
    _append_child(endereco_node, "Complemento", endereco.get("complemento"))
    _append_child(endereco_node, "Bairro", endereco.get("bairro"))
    _append_child(endereco_node, "CodigoMunicipio", endereco.get("codigo_municipio"))
    _append_child(endereco_node, "Uf", endereco.get("uf"))
    _append_child(endereco_node, "Cep", endereco.get("cep"))


def build_rps_xml(payload: dict[str, Any]) -> str:
    prestador = payload.get("prestador", {})
    tomador = payload.get("tomador", {})
    servico = payload.get("servico", {})
    rps = payload.get("rps", {})

    numero = rps.get("numero") or payload.get("rps_numero")
    serie = rps.get("serie") or payload.get("rps_serie")
    data_emissao = rps.get("data_emissao") or payload.get("data_emissao")
    if isinstance(data_emissao, datetime):
        data_emissao = data_emissao.isoformat()

    rps_root = etree.Element("Rps")
    inf_rps = etree.SubElement(rps_root, "InfRps", Id=f"RPS{numero}")

    identificacao = etree.SubElement(inf_rps, "IdentificacaoRps")
    _append_child(identificacao, "Numero", numero)
    _append_child(identificacao, "Serie", serie)
    _append_child(identificacao, "Tipo", rps.get("tipo") or "1")

    _append_child(inf_rps, "DataEmissao", data_emissao)
    _append_child(inf_rps, "Status", rps.get("status") or "1")

    servico_node = etree.SubElement(inf_rps, "Servico")
    valores_node = etree.SubElement(servico_node, "Valores")
    _append_child(valores_node, "ValorServicos", _format_decimal(servico.get("valor")))
    if servico.get("aliquota_iss") is not None:
        _append_child(valores_node, "Aliquota", _format_decimal(servico.get("aliquota_iss")))
    _append_child(servico_node, "ItemListaServico", servico.get("item_lista"))
    _append_child(servico_node, "Discriminacao", servico.get("descricao"))

    prestador_node = etree.SubElement(inf_rps, "Prestador")
    _append_child(prestador_node, "Cnpj", prestador.get("cnpj"))
    _append_child(prestador_node, "InscricaoMunicipal", prestador.get("im"))
    _build_endereco(prestador_node, prestador.get("endereco"))

    tomador_node = etree.SubElement(inf_rps, "Tomador")
    identificacao_tomador = etree.SubElement(tomador_node, "IdentificacaoTomador")
    cpf_cnpj = etree.SubElement(identificacao_tomador, "CpfCnpj")
    doc = tomador.get("cpf_cnpj") or tomador.get("cnpj") or tomador.get("cpf")
    if doc:
        tag = "Cnpj" if len("".join(ch for ch in str(doc) if ch.isdigit())) == 14 else "Cpf"
        _append_child(cpf_cnpj, tag, doc)
    _append_child(tomador_node, "RazaoSocial", tomador.get("nome"))
    _build_endereco(tomador_node, tomador.get("endereco"))

    return etree.tostring(rps_root, encoding="unicode")


def build_lote_xml(rps_list: Iterable[str | dict[str, Any]]) -> str:
    lote_payloads = list(rps_list)
    lote = etree.Element("EnviarLoteRpsEnvio")
    lote_rps = etree.SubElement(lote, "LoteRps", Id="Lote1")
    _append_child(lote_rps, "NumeroLote", "1")
    if lote_payloads:
        first_payload = lote_payloads[0]
        if isinstance(first_payload, dict):
            prestador = first_payload.get("prestador", {})
        else:
            prestador = {}
    else:
        prestador = {}

    _append_child(lote_rps, "Cnpj", prestador.get("cnpj"))
    _append_child(lote_rps, "InscricaoMunicipal", prestador.get("im"))
    _append_child(lote_rps, "QuantidadeRps", str(len(lote_payloads)))

    lista = etree.SubElement(lote_rps, "ListaRps")
    for item in lote_payloads:
        if isinstance(item, str):
            rps_el = etree.fromstring(item.encode("utf-8"))
        else:
            rps_el = etree.fromstring(build_rps_xml(item).encode("utf-8"))
        lista.append(rps_el)

    return etree.tostring(lote, encoding="unicode")
