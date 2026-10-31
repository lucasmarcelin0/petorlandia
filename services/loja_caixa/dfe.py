"""Baixa da SEFAZ as NF-e de compra emitidas contra o CNPJ da loja.

Fluxo:
    1. ``buscar_notas`` pede à SEFAZ (Ambiente Nacional) os documentos novos
       desde o último NSU e guarda o resumo de cada nota;
    2. ``baixar_nota`` registra a Ciência da Operação (evento 210210) e pede
       o XML completo pela chave;
    3. o XML completo vira uma entrada em conferência (a mesma tela do
       upload), que a loja confere e lança no estoque.

A SEFAZ bloqueia quem consulta demais: sem documentos novos (137), ou com
a fila em dia, a próxima consulta só depois de 1 hora. O controle respeita
isso para não levar a loja ao "consumo indevido" (656).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import logging
from typing import Optional

from extensions import db
from models import CasaDeRacao, LojaDfeControle, LojaDfeDocumento, LojaEntradaNota, LojaFiscalConfig
from models.loja_fiscal import AMBIENTE_PRODUCAO
from providers.nfe.chave import only_digits
from providers.nfe.distribuicao import (
    CSTAT_CIENCIA_OK,
    CSTAT_ENCONTRADO,
    DistribuicaoClient,
    build_cons_chave_xml,
    build_dist_nsu_xml,
    build_evento_ciencia_xml,
    nsu15,
    parse_evento_distribuido,
    parse_resumo_nfe,
    parse_retorno_distribuicao,
)
from providers.nfe.retorno import parse_evento
from providers.nfe.xml_builder import UF_TO_CUF
from providers.nfe.xml_signer import sign_event_xml
from services.loja_caixa import entrada as entrada_service
from services.loja_caixa.entrada import EntradaError
from time_utils import now_in_brazil


logger = logging.getLogger(__name__)

ESPERA_SEFAZ = timedelta(hours=1)
MAX_LOTES_POR_CONSULTA = 5
MAX_DOWNLOADS_AUTOMATICOS = 10
TP_EVENTO_CANCELAMENTO = "110111"


class DfeError(ValueError):
    """Mensagem pronta para a tela."""


def _config(casa: CasaDeRacao) -> LojaFiscalConfig:
    config = LojaFiscalConfig.query.filter_by(casa_de_racao_id=casa.id).first()
    if config is None or not config.tem_certificado:
        raise DfeError("Para buscar as notas na SEFAZ, configure a parte fiscal e envie o certificado A1 da loja.")
    return config


def _env(config: LojaFiscalConfig) -> str:
    return "prod" if config.ambiente == AMBIENTE_PRODUCAO else "homolog"


def _tp_amb(config: LojaFiscalConfig) -> str:
    return "1" if config.ambiente == AMBIENTE_PRODUCAO else "2"


def _c_uf(config: LojaFiscalConfig) -> str:
    return UF_TO_CUF.get((config.uf or "SP").upper(), "35")


def _cliente(config: LojaFiscalConfig) -> DistribuicaoClient:
    return DistribuicaoClient(_env(config), config.certificado_pfx(), config.certificado_senha())


def controle(casa: CasaDeRacao) -> LojaDfeControle:
    ctl = LojaDfeControle.query.filter_by(casa_de_racao_id=casa.id).first()
    if ctl is None:
        ctl = LojaDfeControle(casa_de_racao_id=casa.id, ult_nsu="000000000000000")
        db.session.add(ctl)
        db.session.flush()
    return ctl


def _comparavel(momento: Optional[datetime]) -> Optional[datetime]:
    """Os horários de controle são gravados em UTC; sem fuso, vale UTC."""
    if momento is None:
        return None
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


def pode_consultar(ctl: LojaDfeControle, agora: Optional[datetime] = None) -> bool:
    proxima = _comparavel(ctl.proxima_consulta)
    return proxima is None or (agora or now_in_brazil()) >= proxima


def _valor(texto: Optional[str]) -> Optional[Decimal]:
    try:
        return Decimal(texto) if texto else None
    except InvalidOperation:
        return None


def _documento(casa_id: int, chave: str) -> Optional[LojaDfeDocumento]:
    return LojaDfeDocumento.query.filter_by(casa_de_racao_id=casa_id, chave=chave).first()


def _importar_completa(casa: CasaDeRacao, doc: LojaDfeDocumento) -> None:
    """XML completo vira entrada em conferência (ou liga na que já existe)."""
    if doc.entrada_id or not doc.xml_completo:
        return
    existente = LojaEntradaNota.query.filter_by(casa_de_racao_id=casa.id, chave=doc.chave).first()
    if existente is not None:
        doc.entrada_id = existente.id
        return
    try:
        entrada = entrada_service.importar_xml(casa, doc.xml_completo.encode("utf-8"), origem="sefaz")
    except EntradaError as exc:
        doc.erro = str(exc)[:255]
        return
    doc.entrada_id = entrada.id
    doc.erro = None


def _processar(casa: CasaDeRacao, documento) -> int:
    """Guarda um documento distribuído. Devolve 1 se for nota nova."""
    if documento.tipo == "resumo":
        resumo = parse_resumo_nfe(documento.xml)
        if resumo is None or len(resumo.chave) != 44:
            return 0
        doc = _documento(casa.id, resumo.chave)
        nova = doc is None
        if nova:
            doc = LojaDfeDocumento(casa_de_racao_id=casa.id, chave=resumo.chave)
            db.session.add(doc)
        doc.nsu = documento.nsu
        doc.emitente_cnpj = resumo.emitente_cnpj[:14] or None
        doc.emitente_nome = resumo.emitente_nome or None
        doc.dh_emi = (resumo.dh_emi or "")[:32] or None
        doc.valor = _valor(resumo.valor)
        doc.situacao = (resumo.situacao or "")[:1] or doc.situacao
        doc.protocolo = (resumo.protocolo or "")[:20] or doc.protocolo
        db.session.flush()
        return 1 if nova else 0

    if documento.tipo == "completa":
        try:
            from providers.nfe.leitor_compra import ler_nota_compra

            nota = ler_nota_compra(documento.xml)
        except Exception:  # noqa: BLE001 - XML que não é NF-e de compra
            return 0
        doc = _documento(casa.id, nota.chave)
        nova = doc is None
        if nova:
            doc = LojaDfeDocumento(casa_de_racao_id=casa.id, chave=nota.chave, situacao="1")
            db.session.add(doc)
        doc.nsu = documento.nsu
        doc.emitente_cnpj = nota.fornecedor_cnpj[:14] or doc.emitente_cnpj
        doc.emitente_nome = nota.fornecedor_nome or doc.emitente_nome
        doc.dh_emi = (nota.dh_emi or "")[:32] or doc.dh_emi
        doc.valor = nota.valor_total
        doc.protocolo = (nota.protocolo or "")[:20] or doc.protocolo
        doc.xml_completo = documento.xml
        db.session.flush()
        _importar_completa(casa, doc)
        return 1 if nova else 0

    if documento.tipo in {"evento", "resumo_evento"}:
        evento = parse_evento_distribuido(documento.xml)
        if evento is not None and evento.tp_evento == TP_EVENTO_CANCELAMENTO:
            doc = _documento(casa.id, evento.chave)
            if doc is not None:
                doc.situacao = "3"
    return 0


def buscar_notas(casa: CasaDeRacao, *, agora: Optional[datetime] = None, forcar: bool = False) -> dict:
    """Consulta a fila da SEFAZ e guarda as notas novas. Respeita a espera de 1 hora."""
    agora = agora or now_in_brazil()
    config = _config(casa)
    ctl = controle(casa)
    if not forcar and not pode_consultar(ctl, agora):
        proxima = _comparavel(ctl.proxima_consulta).astimezone(agora.tzinfo)
        raise DfeError(
            f"A SEFAZ só aceita nova consulta a partir das {proxima:%H:%M} (limite de uma por hora)."
        )
    client = _cliente(config)
    novas = 0
    # Gravado em UTC: o mesmo instante em qualquer banco (o SQLite não guarda fuso).
    agora_utc = agora.astimezone(timezone.utc)
    for _ in range(MAX_LOTES_POR_CONSULTA):
        resposta = client.distribuicao(
            build_dist_nsu_xml(tp_amb=_tp_amb(config), c_uf_autor=_c_uf(config), cnpj=config.cnpj, ult_nsu=ctl.ult_nsu)
        )
        ctl.ultima_consulta = agora_utc
        if not resposta.success and not resposta.response:
            ctl.ultimo_c_stat = None
            ctl.ultimo_x_motivo = (resposta.error_message or "Sem resposta da SEFAZ.")[:255]
            db.session.commit()
            raise DfeError(f"Sem resposta da SEFAZ: {ctl.ultimo_x_motivo}")
        retorno = parse_retorno_distribuicao(resposta.response or resposta.response_xml)
        ctl.ultimo_c_stat = retorno.c_stat
        ctl.ultimo_x_motivo = (retorno.x_motivo or "")[:255] or None
        if retorno.ult_nsu:
            ctl.ult_nsu = nsu15(retorno.ult_nsu)
        if retorno.max_nsu:
            ctl.max_nsu = nsu15(retorno.max_nsu)
        for documento in retorno.documentos:
            novas += _processar(casa, documento)
        em_dia = ctl.max_nsu is not None and ctl.ult_nsu >= ctl.max_nsu
        if retorno.bloqueio or em_dia or retorno.c_stat != CSTAT_ENCONTRADO:
            ctl.proxima_consulta = agora_utc + ESPERA_SEFAZ
            break
    db.session.commit()
    return {"novas": novas, "c_stat": ctl.ultimo_c_stat, "mensagem": ctl.ultimo_x_motivo}


def manifestar_ciencia(casa: CasaDeRacao, doc: LojaDfeDocumento) -> None:
    config = _config(casa)
    xml = build_evento_ciencia_xml(chave=doc.chave, cnpj=config.cnpj, tp_amb=_tp_amb(config))
    assinado = sign_event_xml(xml, config.certificado_pfx(), config.certificado_senha())
    resposta = _cliente(config).evento(assinado)
    retorno = parse_evento(resposta.response or resposta.response_xml)
    if retorno.c_stat in CSTAT_CIENCIA_OK:
        doc.ciencia_em = now_in_brazil()
        doc.erro = None
        db.session.commit()
        return
    doc.erro = (retorno.x_motivo or resposta.error_message or "SEFAZ não registrou a ciência.")[:255]
    db.session.commit()
    raise DfeError(f"A SEFAZ não registrou a ciência da nota: {doc.erro}")


def baixar_nota(casa: CasaDeRacao, doc: LojaDfeDocumento) -> LojaDfeDocumento:
    """Ciência (se faltar) e download do XML completo; vira entrada em conferência."""
    if doc.casa_de_racao_id != casa.id:
        raise DfeError("Nota de outra loja.")
    if doc.situacao == "3":
        raise DfeError("Esta nota foi cancelada pelo emitente.")
    if doc.xml_completo:
        _importar_completa(casa, doc)
        db.session.commit()
        return doc
    if not doc.ciencia_em:
        manifestar_ciencia(casa, doc)
    config = _config(casa)
    resposta = _cliente(config).distribuicao(
        build_cons_chave_xml(tp_amb=_tp_amb(config), c_uf_autor=_c_uf(config), cnpj=config.cnpj, chave=doc.chave)
    )
    if not resposta.success and not resposta.response:
        raise DfeError(f"Sem resposta da SEFAZ: {resposta.error_message or ''}".strip())
    retorno = parse_retorno_distribuicao(resposta.response or resposta.response_xml)
    for documento in retorno.documentos:
        _processar(casa, documento)
    db.session.commit()
    db.session.refresh(doc)
    if not doc.xml_completo:
        raise DfeError(
            "A SEFAZ ainda não liberou o XML desta nota "
            f"({retorno.c_stat or '—'} {retorno.x_motivo or ''}). Tente de novo em alguns minutos."
        )
    return doc


def rotina_horaria(agora: Optional[datetime] = None) -> dict:
    """Job do agendador: lojas em produção com certificado buscam suas notas."""
    agora = agora or now_in_brazil()
    resumo = {"lojas": 0, "novas": 0, "baixadas": 0, "erros": 0}
    configs = LojaFiscalConfig.query.filter(LojaFiscalConfig.ambiente == AMBIENTE_PRODUCAO).all()
    for config in configs:
        if not config.tem_certificado:
            continue
        casa = db.session.get(CasaDeRacao, config.casa_de_racao_id)
        if casa is None:
            continue
        ctl = controle(casa)
        if not pode_consultar(ctl, agora):
            continue
        resumo["lojas"] += 1
        try:
            resumo["novas"] += buscar_notas(casa, agora=agora)["novas"]
            if ctl.ciencia_automatica:
                pendentes = (
                    LojaDfeDocumento.query.filter_by(casa_de_racao_id=casa.id, situacao="1")
                    .filter(LojaDfeDocumento.xml_completo.is_(None))
                    .order_by(LojaDfeDocumento.id)
                    .limit(MAX_DOWNLOADS_AUTOMATICOS)
                    .all()
                )
                for doc in pendentes:
                    try:
                        baixar_nota(casa, doc)
                        resumo["baixadas"] += 1
                    except DfeError:
                        continue
        except Exception:  # noqa: BLE001 - uma loja com problema não para as outras
            db.session.rollback()
            resumo["erros"] += 1
            logger.exception("Falha ao buscar notas da SEFAZ para a loja %s", config.casa_de_racao_id)
    return resumo
