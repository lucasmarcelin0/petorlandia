"""Notas fiscais da loja (NFC-e própria): configuração, emissão e consulta.

Tudo aqui é por loja e fica desligado até a loja configurar os dados
fiscais, enviar o certificado A1 e ligar a emissão. As rotas não alteram
a loja online nem o fiscal das clínicas.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from io import BytesIO
import re
import zipfile

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from extensions import db
from models import LojaFiscalConfig, NfceDocumento, NfceEvento
from models.loja_fiscal import AMBIENTE_HOMOLOGACAO, AMBIENTE_PRODUCAO, NFCE_STATUS_LABELS
from providers.nfe.chave import only_digits
from security.crypto import MissingMasterKeyError
from services.loja_fiscal import nfce_service
from services.loja_fiscal.danfe import dados_cupom
from services.loja_fiscal.nfce_service import NfceServiceError


bp = Blueprint("loja_fiscal_routes", __name__)

MAX_CERTIFICADO_BYTES = 64 * 1024
CSOSN_OPCOES = {
    "102": "102 — Tributada pelo Simples sem permissão de crédito",
    "103": "103 — Isenção do ICMS no Simples para faixa de receita",
    "300": "300 — Imune",
    "400": "400 — Não tributada pelo Simples",
    "500": "500 — ICMS cobrado anteriormente por substituição (ST)",
}


def get_blueprint():
    return bp


def ensure_loja_access(casa_id: int):
    """Dono da loja, quem a cadastrou ou admin; os demais recebem 403."""
    import app as app_module

    return app_module._casa_loja_access(casa_id)


def _config_da_loja(casa) -> LojaFiscalConfig | None:
    return LojaFiscalConfig.query.filter_by(casa_de_racao_id=casa.id).first()


def _documento_da_loja(casa, doc_id: int) -> NfceDocumento:
    documento = NfceDocumento.query.filter_by(id=doc_id, casa_de_racao_id=casa.id).first()
    if documento is None:
        abort(404)
    return documento


def _texto(nome: str, limite: int, obrigatorio: bool = False, erros: list[str] | None = None, rotulo: str = "") -> str | None:
    valor = " ".join((request.form.get(nome) or "").split())[:limite]
    if obrigatorio and not valor and erros is not None:
        erros.append(f"Informe {rotulo or nome}.")
    return valor or None


def _cnpj_valido(cnpj: str) -> bool:
    digits = only_digits(cnpj)
    if len(digits) != 14 or digits == digits[0] * 14:
        return False
    for tamanho in (12, 13):
        pesos = list(range(tamanho - 7, 1, -1)) + list(range(9, 1, -1))
        soma = sum(int(d) * p for d, p in zip(digits[:tamanho], pesos[-tamanho:]))
        resto = soma % 11
        digito = 0 if resto < 2 else 11 - resto
        if digito != int(digits[tamanho]):
            return False
    return True


def _formatar_cnpj(digits: str) -> str:
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


@bp.route("/casa-de-racao/<int:casa_id>/fiscal", methods=["GET", "POST"])
@login_required
def loja_fiscal_config(casa_id):
    casa = ensure_loja_access(casa_id)
    config = _config_da_loja(casa)

    if request.method == "POST":
        erros: list[str] = []
        cnpj = only_digits(request.form.get("cnpj"))
        if not _cnpj_valido(cnpj):
            erros.append("CNPJ inválido.")
        razao = _texto("razao_social", 200, True, erros, "a razão social")
        ie = only_digits(request.form.get("inscricao_estadual"))
        if not ie:
            erros.append("Informe a inscrição estadual.")
        logradouro = _texto("logradouro", 120, True, erros, "a rua")
        bairro = _texto("bairro", 80, True, erros, "o bairro")
        municipio = _texto("municipio", 80, True, erros, "o município")
        codigo_municipio = only_digits(request.form.get("codigo_municipio"))
        if len(codigo_municipio) != 7:
            erros.append("Código IBGE do município deve ter 7 dígitos (Orlândia: 3534302).")
        try:
            serie = int(request.form.get("serie") or 1)
            if not 1 <= serie <= 889:
                raise ValueError
        except ValueError:
            erros.append("Série deve ser um número de 1 a 889.")
            serie = 1
        percentual = (request.form.get("percentual_tributos") or "").replace(",", ".").strip()
        try:
            percentual_valor = Decimal(percentual) if percentual else None
            if percentual_valor is not None and not Decimal("0") <= percentual_valor < Decimal("100"):
                raise InvalidOperation
        except InvalidOperation:
            erros.append("Percentual de tributos inválido.")
            percentual_valor = None
        csosn = request.form.get("csosn_padrao") or "102"
        if csosn not in CSOSN_OPCOES:
            erros.append("CSOSN inválido.")
        qrcode_versao = request.form.get("qrcode_versao") or "3"
        if qrcode_versao not in {"2", "3"}:
            qrcode_versao = "3"
        credenciadora = only_digits(request.form.get("credenciadora_cnpj"))
        if credenciadora and not _cnpj_valido(credenciadora):
            erros.append("CNPJ da credenciadora (maquininha) inválido.")

        if erros:
            for erro in erros:
                flash(erro, "danger")
            return redirect(url_for("loja_fiscal_config", casa_id=casa.id))

        if config is None:
            config = LojaFiscalConfig(casa_de_racao_id=casa.id, ambiente=AMBIENTE_HOMOLOGACAO)
            db.session.add(config)
        elif config.serie != serie and config.documentos.count():
            flash("Série alterada: a numeração continua a partir do último número usado.", "info")
        config.cnpj = _formatar_cnpj(cnpj)
        config.razao_social = razao
        config.nome_fantasia = _texto("nome_fantasia", 200)
        config.inscricao_estadual = ie
        config.crt = "4" if request.form.get("crt") == "4" else "1"
        config.logradouro = logradouro
        config.numero = _texto("numero", 20) or "S/N"
        config.complemento = _texto("complemento", 60)
        config.bairro = bairro
        config.codigo_municipio = codigo_municipio
        config.municipio = municipio
        config.uf = "SP"
        config.cep = only_digits(request.form.get("cep"))[:8] or None
        config.telefone = only_digits(request.form.get("telefone"))[:14] or None
        config.serie = serie
        config.qrcode_versao = qrcode_versao
        config.csosn_padrao = csosn
        config.pis_cst = (only_digits(request.form.get("pis_cst")) or "99")[:2].zfill(2)
        config.cofins_cst = (only_digits(request.form.get("cofins_cst")) or "99")[:2].zfill(2)
        config.percentual_tributos = percentual_valor
        config.mensagem_cupom = _texto("mensagem_cupom", 500)
        config.credenciadora_cnpj = _formatar_cnpj(credenciadora) if credenciadora else None
        config.tp_integra = "1" if request.form.get("tp_integra") == "1" else "2"
        try:
            if request.form.get("csc_token") or request.form.get("csc_limpar"):
                config.definir_csc(
                    request.form.get("csc_id"),
                    None if request.form.get("csc_limpar") else request.form.get("csc_token"),
                )
            elif request.form.get("csc_id") is not None:
                config.csc_id = (request.form.get("csc_id") or "").strip() or None
        except MissingMasterKeyError:
            db.session.rollback()
            flash("A chave de cifra fiscal do servidor não está configurada.", "danger")
            return redirect(url_for("loja_fiscal_config", casa_id=casa.id))
        config.ativo = bool(request.form.get("ativo")) and config.tem_certificado
        config.contingencia_automatica = bool(request.form.get("contingencia_automatica"))
        if request.form.get("ativo") and not config.tem_certificado:
            flash("Envie o certificado A1 antes de ligar a emissão.", "warning")
        db.session.commit()
        flash("Dados fiscais salvos.", "success")
        return redirect(url_for("loja_fiscal_config", casa_id=casa.id))

    sugestao = {
        "cnpj": casa.cnpj or "",
        "razao_social": casa.razao_social or casa.nome,
        "nome_fantasia": casa.nome,
        "telefone": casa.telefone or "",
    }
    teste_autorizado = bool(
        config
        and NfceDocumento.query.filter_by(
            config_id=config.id, ambiente=AMBIENTE_HOMOLOGACAO, status="autorizada"
        ).first()
    )
    eventos = (
        NfceEvento.query.filter_by(config_id=config.id).order_by(NfceEvento.id.desc()).limit(8).all()
        if config
        else []
    )
    return render_template(
        "loja_fiscal/config.html",
        casa=casa,
        fiscal=config,
        sugestao=sugestao,
        csosn_opcoes=CSOSN_OPCOES,
        teste_autorizado=teste_autorizado,
        eventos=eventos,
    )


@bp.route("/casa-de-racao/<int:casa_id>/fiscal/certificado", methods=["POST"])
@login_required
def loja_fiscal_certificado(casa_id):
    casa = ensure_loja_access(casa_id)
    config = _config_da_loja(casa)
    if config is None:
        flash("Salve os dados fiscais da loja antes de enviar o certificado.", "warning")
        return redirect(url_for("loja_fiscal_config", casa_id=casa.id))
    arquivo = request.files.get("certificado")
    conteudo = arquivo.read(MAX_CERTIFICADO_BYTES + 1) if arquivo else b""
    if len(conteudo) > MAX_CERTIFICADO_BYTES:
        flash("Arquivo grande demais para um certificado A1.", "danger")
        return redirect(url_for("loja_fiscal_config", casa_id=casa.id))
    try:
        info = nfce_service.salvar_certificado(config, conteudo, request.form.get("senha") or "")
        db.session.commit()
    except NfceServiceError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except MissingMasterKeyError:
        db.session.rollback()
        flash("A chave de cifra fiscal do servidor não está configurada.", "danger")
    else:
        validade = info.get("validade")
        sufixo = f" Válido até {validade:%d/%m/%Y}." if validade else ""
        flash(f"Certificado A1 salvo.{sufixo}", "success")
    return redirect(url_for("loja_fiscal_config", casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/fiscal/status", methods=["POST"])
@login_required
def loja_fiscal_status(casa_id):
    casa = ensure_loja_access(casa_id)
    config = _config_da_loja(casa)
    if config is None:
        abort(404)
    try:
        ok, mensagem = nfce_service.consultar_status_servico(config)
    except NfceServiceError as exc:
        ok, mensagem = False, str(exc)
    flash(mensagem, "success" if ok else "danger")
    return redirect(url_for("loja_fiscal_config", casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/fiscal/nota-teste", methods=["POST"])
@login_required
def loja_fiscal_nota_teste(casa_id):
    casa = ensure_loja_access(casa_id)
    config = _config_da_loja(casa)
    if config is None:
        abort(404)
    try:
        documento = nfce_service.emitir_nota_teste(config, usuario_id=current_user.id)
    except NfceServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("loja_fiscal_config", casa_id=casa.id))
    _flash_resultado(documento)
    return redirect(url_for("loja_nfce_detalhe", casa_id=casa.id, doc_id=documento.id))


@bp.route("/casa-de-racao/<int:casa_id>/fiscal/ambiente", methods=["POST"])
@login_required
def loja_fiscal_ambiente(casa_id):
    casa = ensure_loja_access(casa_id)
    config = _config_da_loja(casa)
    if config is None:
        abort(404)
    destino = request.form.get("ambiente")
    if destino == AMBIENTE_PRODUCAO:
        teste_ok = NfceDocumento.query.filter_by(
            config_id=config.id, ambiente=AMBIENTE_HOMOLOGACAO, status="autorizada"
        ).first()
        if not config.tem_certificado or not teste_ok:
            flash("Para ir à produção, emita antes uma nota de teste autorizada em homologação.", "warning")
            return redirect(url_for("loja_fiscal_config", casa_id=casa.id))
        if (request.form.get("confirmacao") or "").strip().upper() != "PRODUCAO":
            flash('Digite PRODUCAO para confirmar: as notas passam a ter valor fiscal.', "warning")
            return redirect(url_for("loja_fiscal_config", casa_id=casa.id))
        config.ambiente = AMBIENTE_PRODUCAO
        flash("Emissão em produção: as próximas NFC-e têm valor fiscal.", "success")
    elif destino == AMBIENTE_HOMOLOGACAO:
        config.ambiente = AMBIENTE_HOMOLOGACAO
        flash("Emissão em homologação (testes, sem valor fiscal).", "info")
    else:
        abort(400)
    db.session.commit()
    return redirect(url_for("loja_fiscal_config", casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/nfce", methods=["GET"])
@login_required
def loja_nfce_lista(casa_id):
    casa = ensure_loja_access(casa_id)
    config = _config_da_loja(casa)
    status = request.args.get("status") or ""
    query = NfceDocumento.query.filter_by(casa_de_racao_id=casa.id)
    if status in NFCE_STATUS_LABELS:
        query = query.filter_by(status=status)
    documentos = query.order_by(NfceDocumento.id.desc()).limit(200).all()
    return render_template(
        "loja_fiscal/notas.html",
        casa=casa,
        fiscal=config,
        documentos=documentos,
        status=status,
        status_labels=NFCE_STATUS_LABELS,
    )


@bp.route("/casa-de-racao/<int:casa_id>/nfce/<int:doc_id>", methods=["GET"])
@login_required
def loja_nfce_detalhe(casa_id, doc_id):
    casa = ensure_loja_access(casa_id)
    documento = _documento_da_loja(casa, doc_id)
    eventos = documento.eventos.order_by(NfceEvento.id.desc()).all()
    return render_template("loja_fiscal/nota.html", casa=casa, documento=documento, eventos=eventos)


@bp.route("/casa-de-racao/<int:casa_id>/nfce/<int:doc_id>/cupom", methods=["GET"])
@login_required
def loja_nfce_cupom(casa_id, doc_id):
    casa = ensure_loja_access(casa_id)
    documento = _documento_da_loja(casa, doc_id)
    if not documento.chave:
        abort(404)
    largura = "58" if request.args.get("largura") == "58" else "80"
    return render_template("loja_fiscal/cupom.html", largura=largura, **dados_cupom(documento))


@bp.route("/casa-de-racao/<int:casa_id>/nfce/<int:doc_id>/xml", methods=["GET"])
@login_required
def loja_nfce_xml(casa_id, doc_id):
    casa = ensure_loja_access(casa_id)
    documento = _documento_da_loja(casa, doc_id)
    xml = documento.xml_autorizado or documento.xml_assinado
    if not xml:
        abort(404)
    sufixo = "-procNFe" if documento.xml_autorizado else "-assinada"
    return send_file(
        BytesIO(('<?xml version="1.0" encoding="UTF-8"?>' + xml).encode("utf-8")),
        mimetype="application/xml",
        as_attachment=True,
        download_name=f"{documento.chave}{sufixo}.xml",
    )


@bp.route("/casa-de-racao/<int:casa_id>/nfce/<int:doc_id>/cancelar", methods=["POST"])
@login_required
def loja_nfce_cancelar(casa_id, doc_id):
    casa = ensure_loja_access(casa_id)
    documento = _documento_da_loja(casa, doc_id)
    try:
        nfce_service.cancelar_nfce(documento, request.form.get("motivo") or "")
    except NfceServiceError as exc:
        flash(str(exc), "danger")
    else:
        flash("NFC-e cancelada na SEFAZ.", "success")
    return redirect(url_for("loja_nfce_detalhe", casa_id=casa.id, doc_id=documento.id))


@bp.route("/casa-de-racao/<int:casa_id>/nfce/<int:doc_id>/reenviar", methods=["POST"])
@login_required
def loja_nfce_reenviar(casa_id, doc_id):
    casa = ensure_loja_access(casa_id)
    documento = _documento_da_loja(casa, doc_id)
    try:
        documento = nfce_service.reenviar_nfce(documento)
    except NfceServiceError as exc:
        flash(str(exc), "danger")
    else:
        _flash_resultado(documento)
    return redirect(url_for("loja_nfce_detalhe", casa_id=casa.id, doc_id=documento.id))


@bp.route("/casa-de-racao/<int:casa_id>/nfce/<int:doc_id>/transmitir", methods=["POST"])
@login_required
def loja_nfce_transmitir(casa_id, doc_id):
    """Envia agora uma NFC-e emitida em contingência off-line."""
    casa = ensure_loja_access(casa_id)
    documento = _documento_da_loja(casa, doc_id)
    try:
        documento = nfce_service.transmitir_contingencia(documento)
    except NfceServiceError as exc:
        flash(str(exc), "danger")
    else:
        if documento.status == "contingencia":
            flash("A SEFAZ ainda não respondeu. A nota continua em contingência e será enviada de novo.", "warning")
        else:
            _flash_resultado(documento)
    return redirect(url_for("loja_nfce_detalhe", casa_id=casa.id, doc_id=documento.id))


@bp.route("/casa-de-racao/<int:casa_id>/nfce/inutilizar", methods=["POST"])
@login_required
def loja_nfce_inutilizar(casa_id):
    casa = ensure_loja_access(casa_id)
    config = _config_da_loja(casa)
    if config is None:
        abort(404)
    try:
        protocolo = nfce_service.inutilizar_numeros(
            config,
            int(request.form.get("numero_inicial") or 0),
            int(request.form.get("numero_final") or request.form.get("numero_inicial") or 0),
            request.form.get("justificativa") or "",
        )
    except (NfceServiceError, ValueError) as exc:
        flash(str(exc) if isinstance(exc, NfceServiceError) else "Informe números válidos.", "danger")
    else:
        flash(f"Números inutilizados na SEFAZ. Protocolo {protocolo}.", "success")
    return redirect(url_for("loja_nfce_lista", casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/nfce/xmls", methods=["GET"])
@login_required
def loja_nfce_xmls_mes(casa_id):
    """ZIP com os XMLs do mês (autorizadas e cancelamentos) para o contador."""
    casa = ensure_loja_access(casa_id)
    mes = request.args.get("mes") or ""
    if not re.fullmatch(r"\d{4}-\d{2}", mes):
        abort(400)
    ano, numero_mes = int(mes[:4]), int(mes[5:])
    if not 1 <= numero_mes <= 12:
        abort(400)
    prefixo = f"{ano:04d}-{numero_mes:02d}"
    documentos = (
        NfceDocumento.query.filter(
            NfceDocumento.casa_de_racao_id == casa.id,
            NfceDocumento.ambiente == AMBIENTE_PRODUCAO,
            NfceDocumento.status.in_(["autorizada", "cancelada"]),
            NfceDocumento.dh_emi.like(f"{prefixo}%"),
        )
        .order_by(NfceDocumento.numero)
        .all()
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for documento in documentos:
            if documento.xml_autorizado:
                zf.writestr(f"{documento.chave}-procNFe.xml", documento.xml_autorizado)
            if documento.xml_cancelamento:
                zf.writestr(f"{documento.chave}-cancelamento-procEventoNFe.xml", documento.xml_cancelamento)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"nfce-{only_digits(casa.cnpj) or casa.id}-{prefixo}.zip",
    )


def _flash_resultado(documento: NfceDocumento) -> None:
    if documento.status == "autorizada":
        flash(f"NFC-e nº {documento.numero} autorizada.", "success")
    elif documento.status == "erro":
        flash("Sem resposta da SEFAZ. A nota ficou pendente; tente reenviar.", "warning")
    else:
        motivo = f"{documento.c_stat} - {documento.x_motivo}" if documento.c_stat else (documento.x_motivo or "")
        flash(f"NFC-e não autorizada: {motivo}", "danger")
