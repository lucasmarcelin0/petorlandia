"""Caixa (PDV) e estoque da loja.

Rotas novas e independentes: a loja online, os pedidos e a configuração
fiscal continuam como estão. O caixa só vende produtos da própria loja.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from extensions import db
from models import (
    CaixaSessao,
    EstoqueMovimento,
    Product,
    ProductVariant,
    VendaBalcao,
)
from models.loja_caixa import FORMAS_PAGAMENTO_CAIXA, UNIDADES_FRACIONADAS
from providers.nfe.chave import only_digits
from services.loja_caixa import dfe as dfe_service
from services.loja_caixa import entrada as entrada_service
from services.loja_caixa import estoque, pdv
from services.loja_caixa.dfe import DfeError
from services.loja_caixa.entrada import EntradaError
from services.loja_caixa.estoque import TIPOS_MOVIMENTO, EstoqueError
from services.loja_caixa.pdv import CaixaError, VendaRepetida
from time_utils import BR_TZ, now_in_brazil


bp = Blueprint("loja_caixa_routes", __name__)

UNIDADES = ["UN", "KG", "G", "L", "ML", "CX", "PCT", "SC", "FD", "M", "PAR", "KIT"]
ORIGENS = {
    "0": "0 — Nacional",
    "1": "1 — Importação direta",
    "2": "2 — Importada, adquirida no mercado interno",
    "3": "3 — Nacional, conteúdo de importação > 40%",
    "4": "4 — Nacional, processos produtivos básicos",
    "5": "5 — Nacional, conteúdo de importação ≤ 40%",
    "6": "6 — Importação direta sem similar (CAMEX)",
    "7": "7 — Mercado interno sem similar (CAMEX)",
    "8": "8 — Nacional, conteúdo de importação > 70%",
}
CSOSN_OPCOES = {
    "": "Padrão da loja",
    "102": "102 — Simples sem permissão de crédito",
    "103": "103 — Isenção no Simples por faixa de receita",
    "300": "300 — Imune",
    "400": "400 — Não tributada pelo Simples",
    "500": "500 — ICMS já retido por substituição (ST)",
}


def get_blueprint():
    return bp


def ensure_loja_access(casa_id: int):
    """Dono da loja, quem a cadastrou ou admin; os demais recebem 403."""
    import app as app_module

    return app_module._casa_loja_access(casa_id)


def _venda_da_loja(casa, venda_id: int) -> VendaBalcao:
    venda = VendaBalcao.query.filter_by(id=venda_id, casa_de_racao_id=casa.id).first()
    if venda is None:
        abort(404)
    return venda


def _erro_json(mensagem: str, status: int = 400):
    return jsonify({"ok": False, "erro": mensagem}), status


def _usuario_id():
    return getattr(current_user, "id", None)


# --------------------------------------------------------------------- caixa

@bp.route("/casa-de-racao/<int:casa_id>/caixa", methods=["GET"])
@login_required
def loja_caixa(casa_id):
    casa = ensure_loja_access(casa_id)
    sessao = pdv.caixa_aberto(casa.id)
    config = pdv.config_fiscal(casa.id)
    ultimas = []
    resumo = None
    if sessao is not None:
        resumo = pdv.resumo_caixa(sessao)
        ultimas = (
            VendaBalcao.query.filter_by(sessao_id=sessao.id)
            .order_by(VendaBalcao.id.desc())
            .limit(8)
            .all()
        )
    return render_template(
        "loja_caixa/pdv.html",
        casa=casa,
        sessao=sessao,
        resumo=resumo,
        ultimas=ultimas,
        formas=FORMAS_PAGAMENTO_CAIXA,
        fiscal=config,
        nfce_ligada=pdv.nfce_ligada(casa.id),
    )


@bp.route("/casa-de-racao/<int:casa_id>/caixa/abrir", methods=["POST"])
@login_required
def loja_caixa_abrir(casa_id):
    casa = ensure_loja_access(casa_id)
    try:
        pdv.abrir_caixa(casa.id, valor_abertura=request.form.get("valor_abertura") or "0", usuario_id=_usuario_id())
        flash("Caixa aberto. Boas vendas!", "success")
    except CaixaError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("loja_caixa", casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/caixa/movimento", methods=["POST"])
@login_required
def loja_caixa_movimento(casa_id):
    casa = ensure_loja_access(casa_id)
    sessao = pdv.caixa_aberto(casa.id)
    if sessao is None:
        flash("Abra o caixa primeiro.", "warning")
        return redirect(url_for("loja_caixa", casa_id=casa.id))
    tipo = request.form.get("tipo")
    try:
        pdv.movimentar_caixa(
            sessao,
            tipo=tipo,
            valor=request.form.get("valor"),
            motivo=request.form.get("motivo"),
            usuario_id=_usuario_id(),
        )
        flash("Retirada registrada." if tipo == "sangria" else "Reforço de troco registrado.", "success")
    except CaixaError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("loja_caixa", casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/caixa/fechar", methods=["GET", "POST"])
@login_required
def loja_caixa_fechar(casa_id):
    casa = ensure_loja_access(casa_id)
    sessao = pdv.caixa_aberto(casa.id)
    if sessao is None:
        flash("Não há caixa aberto.", "info")
        return redirect(url_for("loja_caixa", casa_id=casa.id))
    if request.method == "POST":
        try:
            pdv.fechar_caixa(
                sessao,
                valor_contado=request.form.get("valor_contado"),
                usuario_id=_usuario_id(),
                observacao=request.form.get("observacao"),
            )
        except CaixaError as exc:
            flash(str(exc), "warning")
            return redirect(url_for("loja_caixa_fechar", casa_id=casa.id))
        flash("Caixa fechado.", "success")
        return redirect(url_for("loja_caixa_sessao", casa_id=casa.id, sessao_id=sessao.id))
    return render_template(
        "loja_caixa/fechar.html",
        casa=casa,
        sessao=sessao,
        resumo=pdv.resumo_caixa(sessao),
    )


@bp.route("/casa-de-racao/<int:casa_id>/caixa/sessao/<int:sessao_id>", methods=["GET"])
@login_required
def loja_caixa_sessao(casa_id, sessao_id):
    casa = ensure_loja_access(casa_id)
    sessao = CaixaSessao.query.filter_by(id=sessao_id, casa_de_racao_id=casa.id).first()
    if sessao is None:
        abort(404)
    vendas = VendaBalcao.query.filter_by(sessao_id=sessao.id).order_by(VendaBalcao.id).all()
    return render_template(
        "loja_caixa/sessao.html",
        casa=casa,
        sessao=sessao,
        resumo=pdv.resumo_caixa(sessao),
        vendas=vendas,
        movimentos=sessao.movimentos.all(),
    )


@bp.route("/casa-de-racao/<int:casa_id>/caixa/produtos", methods=["GET"])
@login_required
def loja_caixa_produtos(casa_id):
    casa = ensure_loja_access(casa_id)
    return jsonify({"ok": True, "itens": pdv.buscar_itens(casa.id, request.args.get("q") or "")})


@bp.route("/casa-de-racao/<int:casa_id>/caixa/vincular-codigo", methods=["POST"])
@login_required
def loja_caixa_vincular_codigo(casa_id):
    casa = ensure_loja_access(casa_id)
    dados = request.get_json(silent=True) or {}
    try:
        variant = pdv.vincular_codigo_barras(
            casa.id,
            product_id=int(dados.get("product_id") or 0),
            variant_id=dados.get("variant_id"),
            codigo=str(dados.get("codigo") or ""),
        )
    except (CaixaError, ValueError) as exc:
        return _erro_json(str(exc))
    return jsonify({"ok": True, "item": pdv._entrada_catalogo(variant.product, variant)})


def _resposta_venda(casa, venda: VendaBalcao, erro_nfce: str | None = None) -> dict:
    resposta = {
        "ok": True,
        "venda_id": venda.id,
        "total": f"{venda.total:.2f}",
        "troco": f"{venda.troco:.2f}",
        "venda_url": url_for("loja_caixa_venda_detalhe", casa_id=casa.id, venda_id=venda.id),
        "comprovante_url": url_for("loja_caixa_comprovante", casa_id=casa.id, venda_id=venda.id),
        "nfce": None,
    }
    documento = venda.nfce
    if documento is not None:
        resposta["nfce"] = {
            "status": documento.status,
            "rotulo": documento.status_label,
            "autorizada": documento.status == "autorizada",
            "contingencia": documento.status == "contingencia",
            "mensagem": venda.nfce_erro or documento.x_motivo,
            "cupom_url": url_for("loja_nfce_cupom", casa_id=casa.id, doc_id=documento.id),
        }
    elif venda.emitir_nfce:
        resposta["nfce"] = {
            "status": "erro",
            "rotulo": "Não emitida",
            "autorizada": False,
            "mensagem": erro_nfce or venda.nfce_erro or "A NFC-e ainda não foi emitida.",
        }
    return resposta


@bp.route("/casa-de-racao/<int:casa_id>/caixa/venda", methods=["POST"])
@login_required
def loja_caixa_venda(casa_id):
    casa = ensure_loja_access(casa_id)
    dados = request.get_json(silent=True) or {}
    chave = dados.get("chave")
    repetida = pdv.venda_por_chave(casa.id, chave)
    if repetida is not None:
        return jsonify(_resposta_venda(casa, repetida))
    emitir = bool(dados.get("emitir_nfce")) and pdv.nfce_ligada(casa.id)
    try:
        venda = pdv.registrar_venda(
            casa.id,
            pdv.caixa_aberto(casa.id),
            itens=dados.get("itens") or [],
            pagamentos=dados.get("pagamentos") or [],
            desconto_venda=dados.get("desconto") or "0",
            emitir_nfce=emitir,
            usuario_id=_usuario_id(),
            chave_cliente=chave,
        )
    except VendaRepetida as exc:
        return jsonify(_resposta_venda(casa, exc.venda))
    except (CaixaError, ValueError, TypeError, AttributeError) as exc:
        db.session.rollback()
        return _erro_json(str(exc) if isinstance(exc, CaixaError) else "Dados da venda inválidos.")

    erro_nfce = None
    if emitir and venda.nfce is None:
        try:
            pdv.emitir_nfce_venda(venda, cpf=dados.get("cpf"), usuario_id=_usuario_id())
        except CaixaError as exc:
            erro_nfce = str(exc)
        venda = db.session.get(VendaBalcao, venda.id)
    return jsonify(_resposta_venda(casa, venda, erro_nfce))


def _dia_local(momento) -> str | None:
    if momento is None:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=BR_TZ)
    return momento.astimezone(BR_TZ).date().isoformat()


def _intervalo_do_dia(texto: str | None):
    hoje = now_in_brazil().date()
    try:
        dia = datetime.strptime(texto, "%Y-%m-%d").date() if texto else hoje
    except ValueError:
        dia = hoje
    inicio = datetime.combine(dia, time.min, tzinfo=BR_TZ)
    return dia, inicio, datetime.combine(dia + timedelta(days=1), time.min, tzinfo=BR_TZ)


@bp.route("/casa-de-racao/<int:casa_id>/caixa/vendas", methods=["GET"])
@login_required
def loja_caixa_vendas(casa_id):
    casa = ensure_loja_access(casa_id)
    dia, inicio, fim = _intervalo_do_dia(request.args.get("dia"))
    vendas = (
        VendaBalcao.query.filter(
            VendaBalcao.casa_de_racao_id == casa.id,
            VendaBalcao.created_at >= inicio,
            VendaBalcao.created_at < fim,
        )
        .order_by(VendaBalcao.id.desc())
        .all()
    )
    concluidas = [v for v in vendas if v.status == "concluida"]
    sessoes = (
        CaixaSessao.query.filter_by(casa_de_racao_id=casa.id)
        .order_by(CaixaSessao.id.desc())
        .limit(10)
        .all()
    )
    return render_template(
        "loja_caixa/vendas.html",
        casa=casa,
        dia=dia,
        vendas=vendas,
        total_dia=sum((v.total for v in concluidas), Decimal("0")),
        numero_vendas=len(concluidas),
        sessoes=sessoes,
        formas=FORMAS_PAGAMENTO_CAIXA,
    )


@bp.route("/casa-de-racao/<int:casa_id>/caixa/venda/<int:venda_id>", methods=["GET"])
@login_required
def loja_caixa_venda_detalhe(casa_id, venda_id):
    casa = ensure_loja_access(casa_id)
    venda = _venda_da_loja(casa, venda_id)
    return render_template(
        "loja_caixa/venda.html",
        casa=casa,
        venda=venda,
        dia_venda=_dia_local(venda.created_at),
        formas=FORMAS_PAGAMENTO_CAIXA,
        nfce_ligada=pdv.nfce_ligada(casa.id),
    )


@bp.route("/casa-de-racao/<int:casa_id>/caixa/venda/<int:venda_id>/comprovante", methods=["GET"])
@login_required
def loja_caixa_comprovante(casa_id, venda_id):
    casa = ensure_loja_access(casa_id)
    venda = _venda_da_loja(casa, venda_id)
    largura = "58" if request.args.get("largura") == "58" else "80"
    return render_template(
        "loja_caixa/comprovante.html",
        casa=casa,
        venda=venda,
        formas=FORMAS_PAGAMENTO_CAIXA,
        largura=largura,
    )


@bp.route("/casa-de-racao/<int:casa_id>/caixa/venda/<int:venda_id>/nfce", methods=["POST"])
@login_required
def loja_caixa_venda_nfce(casa_id, venda_id):
    casa = ensure_loja_access(casa_id)
    venda = _venda_da_loja(casa, venda_id)
    try:
        documento = pdv.emitir_nfce_venda(venda, cpf=request.form.get("cpf"), usuario_id=_usuario_id())
        if documento.status == "autorizada":
            flash("NFC-e autorizada.", "success")
        else:
            flash(f"NFC-e {documento.status_label.lower()}: {documento.x_motivo or ''}", "warning")
    except CaixaError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("loja_caixa_venda_detalhe", casa_id=casa.id, venda_id=venda_id))


@bp.route("/casa-de-racao/<int:casa_id>/caixa/venda/<int:venda_id>/contingencia", methods=["POST"])
@login_required
def loja_caixa_venda_contingencia(casa_id, venda_id):
    casa = ensure_loja_access(casa_id)
    venda = _venda_da_loja(casa, venda_id)
    try:
        pdv.emitir_contingencia_venda(venda, usuario_id=_usuario_id())
        flash("NFC-e emitida em contingência: imprima o cupom; o envio à SEFAZ é automático.", "success")
    except CaixaError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("loja_caixa_venda_detalhe", casa_id=casa.id, venda_id=venda_id))


@bp.route("/casa-de-racao/<int:casa_id>/caixa/venda/<int:venda_id>/cancelar", methods=["POST"])
@login_required
def loja_caixa_venda_cancelar(casa_id, venda_id):
    casa = ensure_loja_access(casa_id)
    venda = _venda_da_loja(casa, venda_id)
    try:
        pdv.cancelar_venda(venda, motivo=request.form.get("motivo") or "", usuario_id=_usuario_id())
        flash("Venda cancelada e estoque devolvido.", "success")
    except CaixaError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("loja_caixa_venda_detalhe", casa_id=casa.id, venda_id=venda_id))


# ------------------------------------------------------------------- estoque

def _linhas_estoque(produtos):
    linhas = []
    for product in produtos:
        variantes = product.active_variants or [None]
        for variant in variantes:
            unidade = estoque.unidade_de(product)
            linhas.append(
                {
                    "product": product,
                    "variant": variant,
                    "nome": product.name if variant is None or len(variantes) == 1 else f"{product.name} — {variant.display_name}",
                    "unidade": unidade,
                    "saldo": estoque.saldo(product, variant),
                    "saldo_texto": estoque.formatar_quantidade(estoque.saldo(product, variant), unidade),
                    "preco": Decimal(str((variant.price if variant is not None else product.price) or 0)),
                    "codigo_barras": (variant.barcode if variant is not None else None) or "",
                    "sem_ncm": len(only_digits(product.ncm)) != 8,
                }
            )
    return linhas


@bp.route("/casa-de-racao/<int:casa_id>/estoque", methods=["GET"])
@login_required
def loja_estoque(casa_id):
    casa = ensure_loja_access(casa_id)
    termo = " ".join((request.args.get("q") or "").split())[:80]
    filtro = request.args.get("filtro") or ""
    query = Product.query.filter(Product.casa_de_racao_id == casa.id)
    if filtro == "sem_ncm":
        query = query.filter(db.or_(Product.ncm.is_(None), db.func.length(Product.ncm) < 8))
    if termo:
        por_codigo = (
            query.join(ProductVariant, ProductVariant.product_id == Product.id)
            .filter(db.or_(ProductVariant.barcode == termo, db.func.lower(ProductVariant.sku) == termo.lower()))
            .all()
        )
        produtos = por_codigo or pdv.produtos_por_nome(query, termo, 300)
    else:
        produtos = query.order_by(Product.name).limit(300).all()
    linhas = _linhas_estoque(produtos)
    if filtro == "baixo":
        linhas = [linha for linha in linhas if linha["saldo"] <= 2]
    return render_template(
        "loja_caixa/estoque.html",
        casa=casa,
        linhas=linhas,
        termo=termo,
        filtro=filtro,
        sem_ncm=Product.query.filter(
            Product.casa_de_racao_id == casa.id,
            db.or_(Product.ncm.is_(None), db.func.length(Product.ncm) < 8),
        ).count(),
    )


def _salvar_dados_fiscais(product: Product, erros: list[str]) -> None:
    ncm = only_digits(request.form.get("ncm"))
    if ncm and len(ncm) != 8:
        erros.append("NCM deve ter 8 dígitos.")
    cest = only_digits(request.form.get("cest"))
    if cest and len(cest) != 7:
        erros.append("CEST deve ter 7 dígitos.")
    csosn = (request.form.get("csosn") or "").strip()
    if csosn not in CSOSN_OPCOES:
        erros.append("CSOSN inválido.")
    cfop = only_digits(request.form.get("cfop"))
    if cfop and (len(cfop) != 4 or not cfop.startswith("5")):
        erros.append("CFOP de venda no balcão começa com 5 e tem 4 dígitos (ex.: 5102).")
    origem = (request.form.get("origem") or "0").strip()
    if origem not in ORIGENS:
        erros.append("Origem inválida.")
    unidade = (request.form.get("unidade") or "UN").strip().upper()[:6]
    if unidade not in UNIDADES:
        erros.append("Unidade inválida.")
    if erros:
        return
    product.ncm = ncm or None
    product.cest = cest or None
    product.csosn = csosn or None
    product.cfop = cfop or None
    product.origem = origem
    product.unidade = unidade


@bp.route("/casa-de-racao/<int:casa_id>/estoque/produto/<int:product_id>", methods=["GET", "POST"])
@login_required
def loja_estoque_produto(casa_id, product_id):
    casa = ensure_loja_access(casa_id)
    product = Product.query.filter_by(id=product_id, casa_de_racao_id=casa.id).first()
    if product is None:
        abort(404)
    variantes = product.active_variants or [None]

    if request.method == "POST":
        erros: list[str] = []
        _salvar_dados_fiscais(product, erros)
        motivo = " ".join((request.form.get("motivo") or "").split())[:255]
        alteracoes = []
        for variant in variantes:
            sufixo = str(variant.id) if variant is not None else "produto"
            if variant is not None:
                codigo = "".join((request.form.get(f"codigo_barras_{sufixo}") or "").split())[:80] or None
                if codigo:
                    repetido = (
                        ProductVariant.query.join(Product, ProductVariant.product_id == Product.id)
                        .filter(
                            Product.casa_de_racao_id == casa.id,
                            ProductVariant.barcode == codigo,
                            ProductVariant.id != variant.id,
                        )
                        .first()
                    )
                    if repetido is not None:
                        erros.append(f"O código {codigo} já está em \"{repetido.product.name}\".")
                        continue
                variant.barcode = codigo
                variant.sku = (request.form.get(f"sku_{sufixo}") or "").strip()[:80] or None
            novo = (request.form.get(f"saldo_{sufixo}") or "").strip()
            if novo:
                try:
                    alteracoes.append((variant, estoque.decimal_de(novo, "o saldo")))
                except EstoqueError as exc:
                    erros.append(str(exc))
        if erros:
            db.session.rollback()
            for erro in erros:
                flash(erro, "warning")
            return redirect(url_for("loja_estoque_produto", casa_id=casa.id, product_id=product.id))
        try:
            for variant, novo_saldo in alteracoes:
                estoque.ajustar_para(
                    casa_de_racao_id=casa.id,
                    product=product,
                    variant=variant,
                    novo_saldo=novo_saldo,
                    tipo="inventario" if request.form.get("inventario") else "ajuste",
                    usuario_id=_usuario_id(),
                    observacao=motivo or None,
                )
        except EstoqueError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return redirect(url_for("loja_estoque_produto", casa_id=casa.id, product_id=product.id))
        db.session.commit()
        flash("Produto atualizado.", "success")
        return redirect(url_for("loja_estoque_produto", casa_id=casa.id, product_id=product.id))

    movimentos = (
        EstoqueMovimento.query.filter_by(product_id=product.id, casa_de_racao_id=casa.id)
        .order_by(EstoqueMovimento.id.desc())
        .limit(60)
        .all()
    )
    return render_template(
        "loja_caixa/estoque_produto.html",
        casa=casa,
        product=product,
        linhas=_linhas_estoque([product]),
        movimentos=movimentos,
        tipos=TIPOS_MOVIMENTO,
        unidades=UNIDADES,
        fracionadas=UNIDADES_FRACIONADAS,
        origens=ORIGENS,
        csosn_opcoes=CSOSN_OPCOES,
    )


# ------------------------------------------------------- entrada por XML

MAX_UPLOAD_ENTRADA = 20 * 1024 * 1024  # .zip com várias notas


def _entrada_da_loja(casa, entrada_id: int):
    from models import LojaEntradaNota

    entrada = LojaEntradaNota.query.filter_by(id=entrada_id, casa_de_racao_id=casa.id).first()
    if entrada is None:
        abort(404)
    return entrada


@bp.route("/casa-de-racao/<int:casa_id>/estoque/entradas", methods=["GET"])
@login_required
def loja_entradas(casa_id):
    from models import LojaDfeControle, LojaDfeDocumento, LojaEntradaNota

    casa = ensure_loja_access(casa_id)
    entradas = (
        LojaEntradaNota.query.filter_by(casa_de_racao_id=casa.id)
        .order_by(LojaEntradaNota.id.desc())
        .limit(100)
        .all()
    )
    config = pdv.config_fiscal(casa.id)
    dfe_ctl = LojaDfeControle.query.filter_by(casa_de_racao_id=casa.id).first()
    dfe_docs = (
        LojaDfeDocumento.query.filter_by(casa_de_racao_id=casa.id)
        .order_by(LojaDfeDocumento.id.desc())
        .limit(50)
        .all()
    )
    return render_template(
        "loja_caixa/entradas.html",
        casa=casa,
        entradas=entradas,
        dfe_pronto=bool(config and config.tem_certificado),
        dfe_producao=bool(config and config.em_producao),
        dfe_ctl=dfe_ctl,
        dfe_docs=dfe_docs,
        dfe_pode_consultar=dfe_ctl is None or dfe_service.pode_consultar(dfe_ctl),
    )


@bp.route("/casa-de-racao/<int:casa_id>/estoque/entradas/sefaz/buscar", methods=["POST"])
@login_required
def loja_dfe_buscar(casa_id):
    casa = ensure_loja_access(casa_id)
    try:
        resultado = dfe_service.buscar_notas(casa)
        if resultado["novas"]:
            flash(f"{resultado['novas']} nota(s) nova(s) encontrada(s) na SEFAZ.", "success")
        else:
            flash(f"Nenhuma nota nova na SEFAZ. {resultado['mensagem'] or ''}".strip(), "info")
    except DfeError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("loja_entradas", casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/estoque/entradas/sefaz/automatico", methods=["POST"])
@login_required
def loja_dfe_automatico(casa_id):
    casa = ensure_loja_access(casa_id)
    ctl = dfe_service.controle(casa)
    ctl.ciencia_automatica = bool(request.form.get("ciencia_automatica"))
    db.session.commit()
    flash(
        "Pronto: de hora em hora o PetOrlândia dá ciência e baixa o XML das notas novas."
        if ctl.ciencia_automatica
        else "Download automático desligado.",
        "success",
    )
    return redirect(url_for("loja_entradas", casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/estoque/entradas/sefaz/<int:doc_id>/baixar", methods=["POST"])
@login_required
def loja_dfe_baixar(casa_id, doc_id):
    from models import LojaDfeDocumento

    casa = ensure_loja_access(casa_id)
    doc = LojaDfeDocumento.query.filter_by(id=doc_id, casa_de_racao_id=casa.id).first()
    if doc is None:
        abort(404)
    try:
        doc = dfe_service.baixar_nota(casa, doc)
    except DfeError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("loja_entradas", casa_id=casa.id))
    if doc.entrada_id:
        flash("XML baixado da SEFAZ. Confira os itens e lance no estoque.", "success")
        return redirect(url_for("loja_entrada", casa_id=casa.id, entrada_id=doc.entrada_id))
    flash(doc.erro or "XML baixado.", "info")
    return redirect(url_for("loja_entradas", casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/estoque/entradas/importar", methods=["POST"])
@login_required
def loja_entradas_importar(casa_id):
    casa = ensure_loja_access(casa_id)
    arquivos = []
    for arquivo in request.files.getlist("arquivos"):
        if not arquivo or not arquivo.filename:
            continue
        conteudo = arquivo.read(MAX_UPLOAD_ENTRADA + 1)
        if len(conteudo) > MAX_UPLOAD_ENTRADA:
            flash(f"{arquivo.filename}: arquivo grande demais (máximo 20 MB).", "warning")
            continue
        arquivos.append((arquivo.filename, conteudo))
    if not arquivos:
        flash("Escolha o XML da nota (ou um .zip com vários XMLs).", "warning")
        return redirect(url_for("loja_entradas", casa_id=casa.id))
    resultado = entrada_service.importar_arquivos(casa, arquivos, usuario_id=_usuario_id())
    for erro in resultado["erros"][:10]:
        flash(erro, "warning")
    importadas = resultado["importadas"]
    if len(importadas) == 1:
        flash("Nota importada. Confira os itens e lance no estoque.", "success")
        return redirect(url_for("loja_entrada", casa_id=casa.id, entrada_id=importadas[0].id))
    if importadas:
        flash(f"{len(importadas)} notas importadas. Confira cada uma e lance no estoque.", "success")
    return redirect(url_for("loja_entradas", casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/estoque/entradas/<int:entrada_id>", methods=["GET", "POST"])
@login_required
def loja_entrada(casa_id, entrada_id):
    casa = ensure_loja_access(casa_id)
    entrada = _entrada_da_loja(casa, entrada_id)
    if request.method == "POST":
        try:
            avisos = entrada_service.salvar_conferencia(entrada, request.form.to_dict())
            for aviso in avisos:
                flash(aviso, "warning")
            if request.form.get("acao_tela") == "lancar":
                entrada_service.lancar_entrada(entrada, usuario_id=_usuario_id())
                flash("Nota lançada: estoque e custos atualizados.", "success")
            else:
                flash("Conferência salva.", "success")
        except EntradaError as exc:
            flash(str(exc), "warning")
        return redirect(url_for("loja_entrada", casa_id=casa.id, entrada_id=entrada_id))
    return render_template(
        "loja_caixa/entrada.html",
        casa=casa,
        entrada=entrada,
        unidades=entrada_service.UNIDADES_VENDA,
    )


@bp.route("/casa-de-racao/<int:casa_id>/estoque/entradas/<int:entrada_id>/estornar", methods=["POST"])
@login_required
def loja_entrada_estornar(casa_id, entrada_id):
    casa = ensure_loja_access(casa_id)
    entrada = _entrada_da_loja(casa, entrada_id)
    try:
        entrada_service.estornar_entrada(entrada, usuario_id=_usuario_id())
        flash("Entrada estornada: o estoque voltou ao que era.", "success")
    except (EntradaError, EstoqueError) as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("loja_entrada", casa_id=casa.id, entrada_id=entrada_id))


@bp.route("/casa-de-racao/<int:casa_id>/estoque/entradas/<int:entrada_id>/excluir", methods=["POST"])
@login_required
def loja_entrada_excluir(casa_id, entrada_id):
    casa = ensure_loja_access(casa_id)
    entrada = _entrada_da_loja(casa, entrada_id)
    try:
        entrada_service.excluir_rascunho(entrada)
        flash("Nota descartada.", "success")
    except EntradaError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("loja_entrada", casa_id=casa.id, entrada_id=entrada_id))
    return redirect(url_for("loja_entradas", casa_id=casa.id))


@bp.route("/casa-de-racao/<int:casa_id>/estoque/entradas/<int:entrada_id>/xml", methods=["GET"])
@login_required
def loja_entrada_xml(casa_id, entrada_id):
    casa = ensure_loja_access(casa_id)
    entrada = _entrada_da_loja(casa, entrada_id)
    if not entrada.xml:
        abort(404)
    resposta = current_app.response_class(entrada.xml, mimetype="application/xml")
    resposta.headers["Content-Disposition"] = f'attachment; filename="{entrada.chave}-nfe.xml"'
    return resposta
