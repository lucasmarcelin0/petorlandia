"""Emissão de NFC-e pela loja, direto na SEFAZ-SP, com o certificado da loja.

Fluxo de uma venda:
    1. reserva o próximo número (trava a linha da configuração);
    2. monta, valida e assina o XML (modelo 65) com QR Code;
    3. grava a nota como "pendente" ANTES de enviar (número nunca se perde);
    4. envia o lote síncrono e grava autorizada / rejeitada / denegada.

Falha de rede não é rejeição: a nota fica em "erro" e o reenvio consulta
a chave na SEFAZ antes de transmitir de novo, para nunca autorizar duas
notas para a mesma venda.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
import logging
from typing import Any, Iterable, Optional

from sqlalchemy.orm import aliased

from extensions import db
from models import LojaFiscalConfig, NfceDocumento, NfceEvento
from models.loja_fiscal import AMBIENTE_HOMOLOGACAO, AMBIENTE_PRODUCAO
from providers.fiscal.xml_signature import load_pfx
from providers.nfce.qrcode import URLS_SP, qrcode_v2_online, qrcode_v3_offline, qrcode_v3_online
from providers.nfce.xml_builder import (
    EmitenteNfce,
    ItemNfce,
    NfceDados,
    NfceValidationError,
    PagamentoNfce,
    build_nfce_xml,
)
from providers.nfe.chave import montar_chave, only_digits
from providers.nfe.retorno import (
    CSTAT_DENEGADO,
    parse_autorizacao,
    parse_consulta_situacao,
    parse_evento,
    parse_inutilizacao,
)
from providers.nfe.sefaz_sp.client import SefazSpNfeClient, get_sefaz_sp_nfce_config
from providers.nfe.xml_builder import (
    UF_TO_CUF,
    build_cancel_event_xml,
    build_cancel_substituicao_xml,
    build_cons_sit_xml,
    build_envi_nfe_xml,
    build_inut_xml,
    build_nfe_proc_xml,
    format_dh,
)
from providers.nfe.xml_signer import sign_event_xml, sign_inutilizacao_xml, sign_nfe_xml
from security.redact import redact_xml
from services.fiscal.certificate import parse_pfx
from time_utils import now_in_brazil


logger = logging.getLogger(__name__)

# A NFC-e aceita até 5 minutos entre dhEmi e o recebimento (NT 2025.001).
# Passado isso, um reenvio precisa de nova data de emissão (e nova chave).
JANELA_REENVIO = timedelta(minutes=4)
STATUS_REENVIAVEIS = {"pendente", "erro", "rejeitada"}


class NfceServiceError(Exception):
    """Erro com mensagem pronta para a tela da loja."""


# ---------------------------------------------------------------- configuração

def salvar_certificado(config: LojaFiscalConfig, pfx_bytes: bytes, senha: str) -> dict[str, Any]:
    """Valida o A1 (senha, validade e CNPJ) e guarda cifrado na configuração."""
    if not pfx_bytes:
        raise NfceServiceError("Envie o arquivo do certificado (.pfx ou .p12).")
    try:
        info = parse_pfx(pfx_bytes, senha)
    except ValueError as exc:
        raise NfceServiceError("Não foi possível abrir o certificado. Confira a senha.") from exc
    if info.get("private_key") is None:
        raise NfceServiceError("O arquivo não tem a chave privada do certificado A1.")
    validade = info.get("valid_to")
    if validade is not None and validade <= datetime.now(validade.tzinfo):
        raise NfceServiceError("Este certificado já está vencido.")
    cnpj_certificado = only_digits(info.get("subject_cnpj"))
    if cnpj_certificado and cnpj_certificado != only_digits(config.cnpj):
        raise NfceServiceError(
            "O certificado é de outro CNPJ. Use o e-CNPJ A1 da própria loja."
        )
    config.definir_certificado(pfx_bytes, senha)
    config.certificado_validade = validade
    config.certificado_cnpj = cnpj_certificado or None
    config.certificado_fingerprint = info.get("fingerprint_sha256")
    _registrar(config, None, "certificado", "ok", detalhe="Certificado A1 atualizado")
    return {"validade": validade, "cnpj": cnpj_certificado}


def _env_do_ambiente(ambiente: str | None) -> str:
    return "prod" if ambiente == AMBIENTE_PRODUCAO else "homolog"


def _tp_amb(ambiente: str | None) -> str:
    return "1" if ambiente == AMBIENTE_PRODUCAO else "2"


def _env(config: LojaFiscalConfig) -> str:
    return _env_do_ambiente(config.ambiente)


def _c_uf(config: LojaFiscalConfig) -> str:
    return UF_TO_CUF.get((config.uf or "SP").upper(), "35")


def _cliente(config: LojaFiscalConfig, ambiente: str | None = None) -> SefazSpNfeClient:
    """Cliente da SEFAZ no ambiente pedido (o da nota) ou no atual da loja.

    Uma nota sempre é operada no ambiente em que nasceu: trocar a loja para
    produção não pode mandar uma nota de teste para a SEFAZ de produção.
    """
    if not config.tem_certificado:
        raise NfceServiceError("Envie o certificado digital A1 da loja antes de emitir.")
    return SefazSpNfeClient(
        get_sefaz_sp_nfce_config(_env_do_ambiente(ambiente or config.ambiente)),
        pfx_bytes=config.certificado_pfx(),
        pfx_password=config.certificado_senha(),
    )


def _emitente(config: LojaFiscalConfig) -> EmitenteNfce:
    return EmitenteNfce(
        cnpj=config.cnpj,
        razao_social=config.razao_social,
        nome_fantasia=config.nome_fantasia,
        ie=config.inscricao_estadual,
        crt=config.crt or "1",
        logradouro=config.logradouro,
        numero=config.numero or "S/N",
        complemento=config.complemento,
        bairro=config.bairro,
        codigo_municipio=config.codigo_municipio,
        municipio=config.municipio,
        uf=(config.uf or "SP").upper(),
        cep=config.cep,
        telefone=config.telefone,
    )


def _registrar(
    config: LojaFiscalConfig,
    documento: Optional[NfceDocumento],
    tipo: str,
    status: str,
    *,
    c_stat: str | None = None,
    x_motivo: str | None = None,
    protocolo: str | None = None,
    detalhe: str | None = None,
    request_xml: str | None = None,
    response_xml: str | None = None,
) -> None:
    db.session.add(
        NfceEvento(
            config_id=config.id,
            documento_id=documento.id if documento is not None else None,
            tipo=tipo,
            status=status,
            c_stat=c_stat,
            x_motivo=(x_motivo or "")[:255] or None,
            protocolo=protocolo,
            detalhe=(detalhe or "")[:255] or None,
            request_xml=redact_xml(request_xml),
            response_xml=redact_xml(response_xml),
        )
    )


def consultar_status_servico(config: LojaFiscalConfig) -> tuple[bool, str]:
    """Pergunta à SEFAZ-SP se o serviço de NFC-e está no ar para a loja."""
    response = _cliente(config).test_connection(_c_uf(config))
    ok = bool(response.success)
    mensagem = "SEFAZ-SP em operação e certificado aceito." if ok else (
        response.error_message or "Sem resposta da SEFAZ."
    )
    _registrar(
        config,
        None,
        "status_servico",
        "ok" if ok else "falha",
        detalhe=mensagem,
        request_xml=response.request_xml,
        response_xml=response.response_xml,
    )
    db.session.commit()
    return ok, mensagem


# ------------------------------------------------------------------- numeração

def reservar_numero(config_id: int) -> tuple[LojaFiscalConfig, int]:
    """Próximo número da série no ambiente atual, com trava de linha."""
    config = (
        db.session.query(LojaFiscalConfig)
        .filter(LojaFiscalConfig.id == config_id)
        .with_for_update()
        .one()
    )
    if config.ambiente == AMBIENTE_PRODUCAO:
        config.ultimo_numero_producao = int(config.ultimo_numero_producao or 0) + 1
        numero = config.ultimo_numero_producao
    else:
        config.ultimo_numero_homologacao = int(config.ultimo_numero_homologacao or 0) + 1
        numero = config.ultimo_numero_homologacao
    db.session.flush()
    return config, numero


# --------------------------------------------------------------------- emissão

def _qrcode(config: LojaFiscalConfig, chave: str, tp_amb: str) -> tuple[str, str]:
    urls = URLS_SP[tp_amb]
    if config.qrcode_versao == "2":
        token = config.csc_token()
        if not (config.csc_id and token):
            raise NfceServiceError("QR Code versão 2 exige o CSC (identificador e código) da SEFAZ.")
        return qrcode_v2_online(urls["qrcode"], chave, tp_amb, config.csc_id, token), urls["chave"]
    return qrcode_v3_online(urls["qrcode"], chave, tp_amb), urls["chave"]


def _qrcode_contingencia(config: LojaFiscalConfig, dados: NfceDados, tp_amb: str) -> tuple[str, str]:
    """QR Code v3 off-line: sete parâmetros assinados com a chave do A1."""
    if config.qrcode_versao == "2":
        raise NfceServiceError("A contingência off-line usa o QR Code versão 3. Ajuste a versão na configuração fiscal.")
    urls = URLS_SP[tp_amb]
    chave_privada, _certificado = load_pfx(config.certificado_pfx(), config.certificado_senha())
    cpf = only_digits(dados.cpf_consumidor)
    qrcode = qrcode_v3_offline(
        urls["qrcode"],
        dados.chave.chave,
        tp_amb,
        dados.dh_emi,
        dados.total_nota,
        chave_privada,
        dest_tipo="2" if cpf else None,
        dest_id=cpf or None,
    )
    return qrcode, urls["chave"]


def _serializar(objeto) -> dict[str, Any]:
    return {chave: (str(valor) if isinstance(valor, Decimal) else valor) for chave, valor in asdict(objeto).items()}


_CAMPOS_DECIMAIS_ITEM = ("quantidade", "valor_unitario", "desconto")


def _itens_de(payload: dict[str, Any]) -> list[ItemNfce]:
    itens = []
    for raw in payload.get("entrada_itens") or []:
        dados = dict(raw)
        for campo in _CAMPOS_DECIMAIS_ITEM:
            if dados.get(campo) is not None:
                dados[campo] = Decimal(str(dados[campo]))
        itens.append(ItemNfce(**dados))
    return itens


def _pagamentos_de(payload: dict[str, Any]) -> list[PagamentoNfce]:
    pagamentos = []
    for raw in payload.get("entrada_pagamentos") or []:
        dados = dict(raw)
        dados["valor"] = Decimal(str(dados["valor"]))
        pagamentos.append(PagamentoNfce(**dados))
    return pagamentos


def _snapshot(dados: NfceDados) -> dict[str, Any]:
    """Itens, pagamentos e totais para reimprimir o cupom e remontar a nota.

    Não guarda o CPF do consumidor: ele fica só no XML, que é cifrado.
    """
    def _dec(value: Decimal) -> str:
        return f"{Decimal(value):.4f}".rstrip("0").rstrip(".") if value is not None else None

    return {
        "entrada_itens": [_serializar(item) for item in dados.itens],
        "entrada_pagamentos": [_serializar(pagamento) for pagamento in dados.pagamentos],
        "itens": [
            {
                "codigo": item.codigo,
                "descricao": item.descricao,
                "unidade": item.unidade,
                "quantidade": _dec(item.quantidade),
                "valor_unitario": f"{Decimal(item.valor_unitario):.2f}",
                "valor_bruto": f"{item.valor_bruto:.2f}",
                "desconto": f"{item.valor_desconto:.2f}",
                "valor_liquido": f"{item.valor_liquido:.2f}",
            }
            for item in dados.itens
        ],
        "pagamentos": [
            {"t_pag": pagamento.t_pag, "valor": f"{Decimal(pagamento.valor):.2f}"}
            for pagamento in dados.pagamentos
        ],
        "total_produtos": f"{dados.total_produtos:.2f}",
        "total_desconto": f"{dados.total_desconto:.2f}",
        "total_nota": f"{dados.total_nota:.2f}",
        "total_pago": f"{dados.total_pago:.2f}",
        "troco": f"{dados.troco:.2f}",
        "tributos": f"{dados.tributos_aproximados:.2f}" if dados.tributos_aproximados is not None else None,
        "consumidor_identificado": bool(dados.cpf_consumidor),
    }


def _montar_e_assinar(
    config: LojaFiscalConfig,
    documento: NfceDocumento,
    itens: list[ItemNfce],
    pagamentos: list[PagamentoNfce],
    cpf: str | None,
    nome: str | None,
    *,
    justificativa_contingencia: str | None = None,
    manter_chave: bool = False,
    dh_cont: str | None = None,
) -> str:
    """Monta e assina. Com ``justificativa_contingencia`` sai em tpEmis=9.

    ``manter_chave`` remonta com a mesma data de emissão e o mesmo código
    numérico, ou seja, a mesma chave (contingência rejeitada: o cupom com essa
    chave já está com o cliente).
    """
    tp_amb = _tp_amb(documento.ambiente)
    tp_emis = "9" if justificativa_contingencia else "1"
    manter = bool(manter_chave and documento.chave and documento.dh_emi)
    dh_emi = documento.dh_emi if manter else format_dh(now_in_brazil())
    chave = montar_chave(
        c_uf=_c_uf(config),
        dh_emi=dh_emi,
        cnpj=config.cnpj,
        modelo="65",
        serie=documento.serie,
        numero=documento.numero,
        tp_emis=tp_emis,
        c_nf=documento.chave[35:43] if manter else None,
    )
    if manter and chave.chave != documento.chave:
        raise NfceServiceError(
            "Não foi possível remontar a nota com a mesma chave (o CNPJ ou a UF da loja mudou)."
        )
    dados = NfceDados(
        emitente=_emitente(config),
        itens=itens,
        pagamentos=pagamentos,
        chave=chave,
        serie=documento.serie,
        numero=documento.numero,
        dh_emi=dh_emi,
        tp_amb=tp_amb,
        cpf_consumidor=cpf,
        nome_consumidor=nome,
        inf_cpl=config.mensagem_cupom,
        percentual_tributos=config.percentual_tributos,
        tp_emis=tp_emis,
        dh_cont=(dh_cont or dh_emi) if justificativa_contingencia else None,
        x_just=justificativa_contingencia,
    )
    if justificativa_contingencia:
        qrcode, url_chave = _qrcode_contingencia(config, dados, tp_amb)
    else:
        qrcode, url_chave = _qrcode(config, chave.chave, tp_amb)
    xml = build_nfce_xml(dados, qrcode=qrcode, url_chave=url_chave)
    signed = sign_nfe_xml(xml, config.certificado_pfx(), config.certificado_senha())

    documento.chave = chave.chave
    documento.dh_emi = dh_emi
    documento.tp_emis = tp_emis
    documento.qrcode = qrcode
    documento.url_chave = url_chave
    documento.valor_total = dados.total_nota
    documento.payload_json = _snapshot(dados)
    documento.xml_assinado = signed
    documento.xml_autorizado = None
    documento.status = "pendente"
    documento.c_stat = None
    documento.x_motivo = None
    return signed


def _aplicar_situacao_autorizada(documento: NfceDocumento, prot_nfe_xml: str | None, n_prot: str | None) -> None:
    documento.status = "autorizada"
    documento.protocolo = n_prot
    documento.c_stat = "100"
    documento.x_motivo = "Autorizado o uso da NFC-e"
    if prot_nfe_xml and documento.xml_assinado:
        documento.xml_autorizado = build_nfe_proc_xml(documento.xml_assinado, prot_nfe_xml)


def _aplicar_situacao_final(documento: NfceDocumento, situacao) -> bool:
    """Nota que a SEFAZ diz cancelada ou denegada: registra e devolve True."""
    if situacao.cancelado:
        documento.status = "cancelada"
    elif situacao.c_stat in CSTAT_DENEGADO:
        documento.status = "denegada"
    else:
        return False
    documento.c_stat = situacao.c_stat
    documento.x_motivo = (situacao.x_motivo or "")[:255] or None
    if situacao.n_prot and not documento.protocolo:
        documento.protocolo = situacao.n_prot
    return True


def _consultar_chave(config: LojaFiscalConfig, client: SefazSpNfeClient, documento: NfceDocumento):
    response = client.consulta_protocolo(build_cons_sit_xml(documento.chave, _tp_amb(documento.ambiente)))
    situacao = parse_consulta_situacao(response.response or response.response_xml)
    _registrar(
        config,
        documento,
        "consulta_chave",
        "autorizada" if situacao.autorizado else (situacao.c_stat or "falha"),
        c_stat=situacao.c_stat,
        x_motivo=situacao.x_motivo or response.error_message,
        protocolo=situacao.n_prot,
        request_xml=response.request_xml,
        response_xml=response.response_xml,
    )
    return response, situacao


def _transmitir(config: LojaFiscalConfig, documento: NfceDocumento, signed_xml: str) -> NfceDocumento:
    client = _cliente(config, documento.ambiente)
    response = client.autorizacao(build_envi_nfe_xml(signed_xml, id_lote=documento.id))

    if not response.success and not response.response:
        # Rede/TLS/timeout: a SEFAZ pode ter recebido. Pergunta pela chave.
        _registrar(
            config, documento, "autorizacao", "erro",
            x_motivo=response.error_message, request_xml=response.request_xml, response_xml=response.response_xml,
        )
        consulta, situacao = _consultar_chave(config, client, documento)
        if situacao.autorizado:
            _aplicar_situacao_autorizada(documento, situacao.prot_nfe_xml, situacao.n_prot)
        elif not _aplicar_situacao_final(documento, situacao):
            documento.status = "erro"
            documento.x_motivo = (response.error_message or "Sem resposta da SEFAZ.")[:255]
        db.session.commit()
        return documento

    retorno = parse_autorizacao(response.response or response.response_xml)
    if retorno.autorizado:
        _aplicar_situacao_autorizada(documento, retorno.prot_nfe_xml, retorno.n_prot)
        documento.dh_recbto = retorno.dh_recbto
        documento.c_stat = retorno.c_stat
        documento.x_motivo = retorno.x_motivo
    elif retorno.c_stat == "204":
        _, situacao = _consultar_chave(config, client, documento)
        if situacao.autorizado:
            _aplicar_situacao_autorizada(documento, situacao.prot_nfe_xml, situacao.n_prot)
        elif not _aplicar_situacao_final(documento, situacao):
            # Duplicidade sem confirmação: a chave pode estar autorizada.
            # "erro" faz o reenvio consultar a MESMA chave antes de tudo.
            documento.status = "erro"
            documento.c_stat = retorno.c_stat
            documento.x_motivo = (
                f"Duplicidade na SEFAZ sem confirmação da situação: {retorno.x_motivo or ''}"
            )[:255]
    elif retorno.denegado:
        documento.status = "denegada"
        documento.c_stat = retorno.c_stat
        documento.x_motivo = (retorno.x_motivo or "")[:255]
    elif retorno.em_processamento:
        # Não deveria ocorrer com indSinc=1; trata como falha a reconsultar.
        documento.status = "erro"
        documento.c_stat = retorno.c_stat_lote
        documento.x_motivo = "Lote em processamento na SEFAZ; consulte de novo em instantes."
    else:
        documento.status = "rejeitada"
        documento.c_stat = retorno.c_stat
        documento.x_motivo = (retorno.x_motivo or response.error_message or "Rejeitada pela SEFAZ.")[:255]

    _registrar(
        config,
        documento,
        "autorizacao",
        documento.status,
        c_stat=documento.c_stat,
        x_motivo=documento.x_motivo,
        protocolo=documento.protocolo,
        request_xml=response.request_xml,
        response_xml=response.response_xml,
    )
    db.session.commit()
    return documento


def emitir_nfce(
    config: LojaFiscalConfig,
    *,
    itens: Iterable[ItemNfce],
    pagamentos: Iterable[PagamentoNfce],
    cpf: str | None = None,
    nome: str | None = None,
    origem: str = "venda_balcao",
    origem_id: int | None = None,
    usuario_id: int | None = None,
) -> NfceDocumento:
    """Emite uma NFC-e nova. Erros de dados levantam ``NfceServiceError``."""
    itens = list(itens)
    pagamentos = list(pagamentos)
    if not config.tem_certificado:
        raise NfceServiceError("Envie o certificado digital A1 da loja antes de emitir.")

    config, numero = reservar_numero(config.id)
    documento = NfceDocumento(
        casa_de_racao_id=config.casa_de_racao_id,
        config_id=config.id,
        origem=origem,
        origem_id=origem_id,
        ambiente=config.ambiente,
        serie=int(config.serie or 1),
        numero=numero,
        status="pendente",
        created_by_id=usuario_id,
    )
    db.session.add(documento)
    db.session.flush()
    try:
        signed = _montar_e_assinar(config, documento, itens, pagamentos, cpf, nome)
    except NfceValidationError as exc:
        # Dado inválido: devolve o número reservado (nada foi gravado).
        db.session.rollback()
        raise NfceServiceError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - certificado/chave mestra: não perder o número
        db.session.rollback()
        logger.exception("Falha ao montar/assinar NFC-e da loja %s", config.casa_de_racao_id)
        raise NfceServiceError(
            "Não foi possível assinar a nota com o certificado da loja. Reenvie o certificado A1."
        ) from exc
    # Grava antes de transmitir: se o processo cair, a nota e o número existem.
    db.session.commit()
    return _transmitir(config, documento, signed)


def _cpf_do_xml(documento: NfceDocumento) -> str | None:
    xml = documento.xml_assinado
    if not xml:
        return None
    from security.xml_safe import safe_lxml_fromstring

    try:
        root = safe_lxml_fromstring(xml.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    node = root.find(".//{http://www.portalfiscal.inf.br/nfe}dest/{http://www.portalfiscal.inf.br/nfe}CPF")
    return node.text if node is not None else None


def reenviar_nfce(
    documento: NfceDocumento,
    *,
    itens: Optional[list[ItemNfce]] = None,
    pagamentos: Optional[list[PagamentoNfce]] = None,
) -> NfceDocumento:
    """Reenvia uma nota pendente, com falha de comunicação ou rejeitada.

    1. Se a chave já consta autorizada na SEFAZ, só registra a autorização.
    2. Só segue se a SEFAZ responder que a chave não existe (217): sem essa
       certeza, nada muda (a chave original pode ter sido autorizada).
    3. Dentro da janela de 5 minutos, reenvia o mesmo XML assinado.
    4. Fora dela, ou se rejeitada, monta de novo: mesmo número, nova data e
       nova chave, com os itens informados (ou os da montagem anterior).

    A nota é sempre operada no ambiente em que nasceu.
    """
    if documento.status not in STATUS_REENVIAVEIS:
        raise NfceServiceError("Esta nota não pode ser reenviada.")
    config = documento.config
    client = _cliente(config, documento.ambiente)
    if documento.chave and documento.status in {"pendente", "erro"}:
        _, situacao = _consultar_chave(config, client, documento)
        if situacao.autorizado:
            _aplicar_situacao_autorizada(documento, situacao.prot_nfe_xml, situacao.n_prot)
            db.session.commit()
            return documento
        if _aplicar_situacao_final(documento, situacao):
            db.session.commit()
            return documento
        if not situacao.nao_consta:
            db.session.commit()  # guarda o registro da consulta
            raise NfceServiceError(
                "A SEFAZ não confirmou a situação desta nota agora. Nada foi alterado: "
                "tente reenviar de novo em alguns instantes."
            )

    signed = documento.xml_assinado
    emitida_em = _parse_dh(documento.dh_emi)
    dentro_da_janela = emitida_em is not None and now_in_brazil() - emitida_em < JANELA_REENVIO
    remontar = itens is not None or documento.status == "rejeitada" or not (signed and dentro_da_janela)
    if remontar:
        payload = documento.payload_json or {}
        itens = itens if itens is not None else _itens_de(payload)
        pagamentos = pagamentos if pagamentos is not None else _pagamentos_de(payload)
        if not itens or not pagamentos:
            raise NfceServiceError("Não há dados para remontar esta nota. Refaça a venda.")
        cpf = _cpf_do_xml(documento)
        # Contingência rejeitada: corrige os dados mas mantém tpEmis=9 e a
        # mesma chave, porque o cupom off-line já foi entregue ao cliente.
        contingencia = documento.tp_emis == "9"
        dh_cont, x_just = _contingencia_do_xml(documento) if contingencia else (None, None)
        try:
            signed = _montar_e_assinar(
                config,
                documento,
                itens,
                pagamentos,
                cpf,
                None,
                justificativa_contingencia=(x_just or JUSTIFICATIVA_CONTINGENCIA) if contingencia else None,
                manter_chave=contingencia,
                dh_cont=dh_cont,
            )
        except NfceValidationError as exc:
            db.session.rollback()
            raise NfceServiceError(str(exc)) from exc
        db.session.commit()
    documento = _transmitir(config, documento, signed)
    if documento.tp_emis == "9":
        documento = _apos_envio_contingencia(documento)
    return documento


def _contingencia_do_xml(documento: NfceDocumento) -> tuple[str | None, str | None]:
    """dhCont e xJust da nota em contingência, como foram para o cupom."""
    xml = documento.xml_assinado
    if not xml:
        return None, None
    from security.xml_safe import safe_lxml_fromstring

    try:
        root = safe_lxml_fromstring(xml.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return None, None
    ns = "{http://www.portalfiscal.inf.br/nfe}"
    dh_cont = root.find(f".//{ns}ide/{ns}dhCont")
    x_just = root.find(f".//{ns}ide/{ns}xJust")
    return (
        dh_cont.text if dh_cont is not None else None,
        x_just.text if x_just is not None else None,
    )


def _parse_dh(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def emitir_nota_teste(config: LojaFiscalConfig, usuario_id: int | None = None) -> NfceDocumento:
    """NFC-e de R$ 1,00 em homologação, para validar certificado e cadastro."""
    if config.ambiente != AMBIENTE_HOMOLOGACAO:
        raise NfceServiceError("A nota de teste só pode ser emitida em homologação.")
    item = ItemNfce(
        codigo="TESTE",
        descricao="Produto de teste",
        ncm="23091000",
        quantidade=Decimal("1"),
        valor_unitario=Decimal("1.00"),
        csosn=config.csosn_padrao or "102",
        pis_cst=config.pis_cst or "99",
        cofins_cst=config.cofins_cst or "99",
    )
    pagamento = PagamentoNfce(t_pag="01", valor=Decimal("1.00"))
    return emitir_nfce(
        config,
        itens=[item],
        pagamentos=[pagamento],
        origem="teste",
        usuario_id=usuario_id,
    )


# ------------------------------------------------------------- contingência

JUSTIFICATIVA_CONTINGENCIA = (
    "SEFAZ sem resposta no momento da venda; NFC-e emitida em contingencia off-line"
)


def emitir_em_contingencia(
    config: LojaFiscalConfig,
    *,
    itens: Iterable[ItemNfce],
    pagamentos: Iterable[PagamentoNfce],
    cpf: str | None = None,
    justificativa: str | None = None,
    origem: str = "venda_balcao",
    origem_id: int | None = None,
    usuario_id: int | None = None,
    substitui: Optional[NfceDocumento] = None,
) -> NfceDocumento:
    """NFC-e off-line (tpEmis=9): número novo, cupom impresso na hora, envio depois.

    Nada é transmitido aqui. ``transmitir_contingencia`` (ou o job de 10 em 10
    minutos) envia quando a SEFAZ responder; a nota normal substituída é
    cancelada por substituição (110112) ou inutilizada.
    """
    if not config.tem_certificado:
        raise NfceServiceError("Envie o certificado digital A1 da loja antes de emitir.")
    texto = " ".join((justificativa or JUSTIFICATIVA_CONTINGENCIA).split())[:256]
    if len(texto) < 15:
        raise NfceServiceError("A justificativa da contingência precisa de pelo menos 15 caracteres.")
    itens = list(itens)
    pagamentos = list(pagamentos)
    config, numero = reservar_numero(config.id)
    documento = NfceDocumento(
        casa_de_racao_id=config.casa_de_racao_id,
        config_id=config.id,
        origem=origem,
        origem_id=origem_id,
        ambiente=config.ambiente,
        serie=int(config.serie or 1),
        numero=numero,
        status="contingencia",
        tp_emis="9",
        substitui_id=substitui.id if substitui is not None else None,
        created_by_id=usuario_id,
    )
    db.session.add(documento)
    db.session.flush()
    try:
        _montar_e_assinar(config, documento, itens, pagamentos, cpf, None, justificativa_contingencia=texto)
    except NfceValidationError as exc:
        db.session.rollback()
        raise NfceServiceError(str(exc)) from exc
    except NfceServiceError:
        db.session.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 - certificado/chave mestra
        db.session.rollback()
        logger.exception("Falha ao assinar NFC-e em contingência da loja %s", config.casa_de_racao_id)
        raise NfceServiceError(
            "Não foi possível assinar a nota com o certificado da loja. Reenvie o certificado A1."
        ) from exc
    documento.status = "contingencia"
    documento.x_motivo = "Emitida em contingência off-line; vai para a SEFAZ quando ela responder."
    _registrar(config, documento, "contingencia", "emitida", detalhe=texto)
    db.session.commit()
    return documento


def contingencia_da_nota(
    documento: NfceDocumento, *, justificativa: str | None = None, usuario_id: int | None = None
) -> NfceDocumento:
    """Emite em contingência a venda de uma nota normal que ficou sem resposta."""
    if documento.status != "erro":
        raise NfceServiceError("Só a nota sem resposta da SEFAZ vai para a contingência.")
    payload = documento.payload_json or {}
    itens = _itens_de(payload)
    pagamentos = _pagamentos_de(payload)
    if not itens or not pagamentos:
        raise NfceServiceError("Não há dados para emitir em contingência. Refaça a venda.")
    return emitir_em_contingencia(
        documento.config,
        itens=itens,
        pagamentos=pagamentos,
        cpf=_cpf_do_xml(documento),
        justificativa=justificativa,
        origem=documento.origem,
        origem_id=documento.origem_id,
        usuario_id=usuario_id,
        substitui=documento,
    )


def transmitir_contingencia(documento: NfceDocumento) -> NfceDocumento:
    """Envia a nota off-line. Sem resposta, ela continua em contingência."""
    if documento.status != "contingencia":
        raise NfceServiceError("Esta nota não está em contingência.")
    documento = _transmitir(documento.config, documento, documento.xml_assinado)
    return _apos_envio_contingencia(documento)


def _apos_envio_contingencia(documento: NfceDocumento) -> NfceDocumento:
    """Sem resposta, a nota off-line continua em contingência (o job reenvia);
    autorizada, resolve a nota normal que ela substituiu."""
    if documento.status == "erro":
        documento.status = "contingencia"
        db.session.commit()
    elif documento.status == "autorizada" and documento.substitui_id:
        try:
            resolver_substituida(documento)
        except NfceServiceError:
            logger.warning("Nota substituída %s ainda sem solução", documento.substitui_id)
    return documento


def resolver_substituida(contingencia: NfceDocumento) -> Optional[str]:
    """Com a contingência autorizada, resolve a nota normal que ficou sem resposta:
    cancelada por substituição se a SEFAZ a autorizou; inutilizada se não consta."""
    original = contingencia.substitui
    if original is None or original.status in {"cancelada", "inutilizada"}:
        return None
    config = original.config
    if original.status != "autorizada":
        client = _cliente(config, original.ambiente)
        _, situacao = _consultar_chave(config, client, original)
        if situacao.autorizado:
            _aplicar_situacao_autorizada(original, situacao.prot_nfe_xml, situacao.n_prot)
            db.session.commit()
        elif situacao.nao_consta and original.ambiente == config.ambiente:
            inutilizar_numeros(
                config,
                original.numero,
                original.numero,
                "Numero substituido por NFC-e emitida em contingencia off-line",
            )
            return "inutilizada"
        else:
            db.session.commit()
            return None
    cancelar_por_substituicao(original, contingencia)
    return "cancelada"


def cancelar_por_substituicao(original: NfceDocumento, substituta: NfceDocumento) -> NfceDocumento:
    """Evento 110112: cancela a nota normal autorizada que a contingência substituiu."""
    if original.status != "autorizada" or not original.protocolo:
        raise NfceServiceError("Só nota autorizada pode ser cancelada por substituição.")
    config = original.config
    client = _cliente(config, original.ambiente)
    motivo = "NFC-e substituida por outra emitida em contingencia off-line para a mesma venda"
    xml_evento = build_cancel_substituicao_xml(
        chave=original.chave,
        emitter_cnpj=config.cnpj,
        protocolo=original.protocolo,
        motivo=motivo,
        chave_substituta=substituta.chave,
        tp_amb=_tp_amb(original.ambiente),
        data_evento=now_in_brazil(),
    )
    signed = sign_event_xml(xml_evento, config.certificado_pfx(), config.certificado_senha())
    response = client.recepcao_evento(signed)
    retorno = parse_evento(response.response or response.response_xml)
    if retorno.registrado:
        original.status = "cancelada"
        original.cancel_protocolo = retorno.n_prot
        original.cancel_motivo = motivo
        original.cancelada_em = now_in_brazil()
        original.xml_cancelamento = _proc_evento(signed, retorno.ret_evento_xml)
    _registrar(
        config,
        original,
        "cancelamento_substituicao",
        "cancelada" if retorno.registrado else "recusado",
        c_stat=retorno.c_stat,
        x_motivo=retorno.x_motivo or response.error_message,
        protocolo=retorno.n_prot,
        request_xml=response.request_xml,
        response_xml=response.response_xml,
    )
    db.session.commit()
    if not retorno.registrado:
        raise NfceServiceError(
            f"A SEFAZ não aceitou o cancelamento por substituição: {retorno.x_motivo or response.error_message or 'sem resposta'}."
        )
    return original


def rotina_contingencia(limite: int = 50) -> dict[str, int]:
    """Job: envia as notas em contingência e resolve as notas substituídas."""
    resumo = {"enviadas": 0, "autorizadas": 0, "pendentes": 0, "resolvidas": 0, "erros": 0}
    ids = [
        doc_id
        for (doc_id,) in db.session.query(NfceDocumento.id)
        .filter(NfceDocumento.status == "contingencia")
        .order_by(NfceDocumento.id)
        .limit(limite)
        .all()
    ]
    for doc_id in ids:
        documento = db.session.get(NfceDocumento, doc_id)
        try:
            documento = transmitir_contingencia(documento)
            resumo["enviadas"] += 1
            if documento.status == "autorizada":
                resumo["autorizadas"] += 1
            elif documento.status == "contingencia":
                resumo["pendentes"] += 1
        except Exception:  # noqa: BLE001 - uma nota com problema não para as outras
            db.session.rollback()
            resumo["erros"] += 1
            logger.exception("Falha ao enviar NFC-e em contingência %s", doc_id)
    # As já resolvidas saem na consulta, antes do limite: senão as primeiras
    # ocupariam todas as vagas e as pendentes nunca seriam tentadas de novo.
    original = aliased(NfceDocumento)
    substitutas = (
        NfceDocumento.query.join(original, NfceDocumento.substitui_id == original.id)
        .filter(
            NfceDocumento.status == "autorizada",
            original.status.notin_(("cancelada", "inutilizada")),
        )
        .order_by(NfceDocumento.id)
        .limit(limite)
        .all()
    )
    for documento in substitutas:
        original = documento.substitui
        if original is None or original.status in {"cancelada", "inutilizada"}:
            continue
        try:
            if resolver_substituida(documento):
                resumo["resolvidas"] += 1
        except Exception:  # noqa: BLE001
            db.session.rollback()
            resumo["erros"] += 1
            logger.exception("Falha ao resolver a nota substituída %s", documento.substitui_id)
    return resumo


# ------------------------------------------------------- cancelamento e inutilização

def cancelar_nfce(documento: NfceDocumento, motivo: str) -> NfceDocumento:
    """Cancela uma NFC-e autorizada (evento 110111)."""
    if documento.status != "autorizada" or not documento.protocolo:
        raise NfceServiceError("Só notas autorizadas podem ser canceladas.")
    justificativa = " ".join((motivo or "").split())
    if len(justificativa) < 15:
        raise NfceServiceError("Descreva o motivo do cancelamento com pelo menos 15 caracteres.")
    config = documento.config
    client = _cliente(config, documento.ambiente)
    xml_evento = build_cancel_event_xml(
        chave=documento.chave,
        emitter_cnpj=config.cnpj,
        protocolo=documento.protocolo,
        motivo=justificativa[:255],
        tp_amb=_tp_amb(documento.ambiente),
        data_evento=now_in_brazil(),
    )
    signed = sign_event_xml(xml_evento, config.certificado_pfx(), config.certificado_senha())
    response = client.recepcao_evento(signed)
    retorno = parse_evento(response.response or response.response_xml)
    if retorno.registrado:
        documento.status = "cancelada"
        documento.cancel_protocolo = retorno.n_prot
        documento.cancel_motivo = justificativa[:255]
        documento.cancelada_em = now_in_brazil()
        documento.xml_cancelamento = _proc_evento(signed, retorno.ret_evento_xml)
    _registrar(
        config,
        documento,
        "cancelamento",
        "cancelada" if retorno.registrado else "recusado",
        c_stat=retorno.c_stat,
        x_motivo=retorno.x_motivo or response.error_message,
        protocolo=retorno.n_prot,
        request_xml=response.request_xml,
        response_xml=response.response_xml,
    )
    db.session.commit()
    if not retorno.registrado:
        raise NfceServiceError(
            f"A SEFAZ não aceitou o cancelamento: {retorno.x_motivo or response.error_message or 'sem resposta'}."
        )
    return documento


def _proc_evento(env_evento_assinado: str, ret_evento_xml: str | None) -> str | None:
    """``procEventoNFe`` = evento assinado + retorno da SEFAZ (XML de guarda)."""
    from lxml import etree

    from security.xml_safe import safe_lxml_fromstring

    if not ret_evento_xml:
        return None
    root = safe_lxml_fromstring(env_evento_assinado.encode("utf-8"))
    evento = root.find("{http://www.portalfiscal.inf.br/nfe}evento")
    if evento is None:
        return None
    evento_xml = etree.tostring(evento, encoding="unicode")
    return (
        '<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">'
        f"{evento_xml}{ret_evento_xml}</procEventoNFe>"
    )


def inutilizar_numeros(
    config: LojaFiscalConfig,
    numero_inicial: int,
    numero_final: int,
    justificativa: str,
) -> str:
    """Inutiliza números da série que não viraram nota autorizada."""
    inicio, fim = int(numero_inicial), int(numero_final)
    if inicio <= 0 or fim < inicio:
        raise NfceServiceError("Faixa de números inválida.")
    ultimo = config.ultimo_numero_producao if config.em_producao else config.ultimo_numero_homologacao
    if fim > int(ultimo or 0):
        raise NfceServiceError("Só é possível inutilizar números que o PetOrlândia já reservou.")
    bloqueados = (
        NfceDocumento.query.filter(
            NfceDocumento.config_id == config.id,
            NfceDocumento.ambiente == config.ambiente,
            NfceDocumento.serie == int(config.serie or 1),
            NfceDocumento.numero.between(inicio, fim),
            NfceDocumento.status.in_(["autorizada", "cancelada", "denegada"]),
        ).count()
    )
    if bloqueados:
        raise NfceServiceError("A faixa contém nota autorizada, cancelada ou denegada.")
    try:
        xml = build_inut_xml(
            c_uf=_c_uf(config),
            tp_amb=config.tp_amb,
            ano=now_in_brazil().year,
            cnpj=config.cnpj,
            modelo="65",
            serie=int(config.serie or 1),
            numero_inicial=inicio,
            numero_final=fim,
            justificativa=justificativa,
        )
    except ValueError as exc:
        raise NfceServiceError(str(exc)) from exc
    client = _cliente(config)
    signed = sign_inutilizacao_xml(xml, config.certificado_pfx(), config.certificado_senha())
    response = client.inutilizacao(signed)
    retorno = parse_inutilizacao(response.response or response.response_xml)
    _registrar(
        config,
        None,
        "inutilizacao",
        "homologada" if retorno.homologada else "recusada",
        c_stat=retorno.c_stat,
        x_motivo=retorno.x_motivo or response.error_message,
        protocolo=retorno.n_prot,
        detalhe=f"Série {config.serie}, números {inicio} a {fim}",
        request_xml=response.request_xml,
        response_xml=response.response_xml,
    )
    if retorno.homologada:
        (
            NfceDocumento.query.filter(
                NfceDocumento.config_id == config.id,
                NfceDocumento.ambiente == config.ambiente,
                NfceDocumento.serie == int(config.serie or 1),
                NfceDocumento.numero.between(inicio, fim),
                NfceDocumento.status.in_(["pendente", "erro", "rejeitada"]),
            ).update({"status": "inutilizada"}, synchronize_session=False)
        )
    db.session.commit()
    if not retorno.homologada:
        raise NfceServiceError(
            f"A SEFAZ não aceitou a inutilização: {retorno.x_motivo or response.error_message or 'sem resposta'}."
        )
    return retorno.n_prot or ""
