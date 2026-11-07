"""Passos da pesquisa exibidos no painel do SFA: links e marcação de concluído."""
from urllib.parse import urlparse

from flask import flash, redirect, request, url_for

ANCORA = 'passos-pesquisa'


def url_valida(valor: str) -> str:
    """Aceita só links http(s) completos; devolve '' quando o campo vem vazio."""
    valor = (valor or '').strip()
    if not valor:
        return ''
    partes = urlparse(valor)
    if partes.scheme not in ('http', 'https') or not partes.netloc:
        raise ValueError('link inválido')
    return valor[:500]


def listar_passos():
    from models.sfa import SfaPassoPesquisa
    return SfaPassoPesquisa.query.order_by(SfaPassoPesquisa.ordem, SfaPassoPesquisa.id).all()


def register(bp, require_access):
    from extensions import db
    from models.sfa import SfaPassoPesquisa
    from time_utils import utcnow

    def voltar():
        return redirect(url_for('sfa_routes.dashboard', _anchor=ANCORA))

    @bp.route('/passos/<int:passo_id>/concluido', methods=['POST'])
    @require_access
    def passo_concluido(passo_id):
        passo = db.get_or_404(SfaPassoPesquisa, passo_id)
        passo.concluido = request.form.get('concluido') == '1'
        passo.concluido_em = utcnow() if passo.concluido else None
        db.session.commit()
        return voltar()

    @bp.route('/passos', methods=['POST'])
    @require_access
    def passo_novo():
        titulo = (request.form.get('titulo') or '').strip()[:120]
        try:
            url = url_valida(request.form.get('url'))
        except ValueError:
            flash('O link precisa começar com http:// ou https://. O passo não foi criado.', 'danger')
            return voltar()
        if not titulo:
            flash('Informe o nome do passo.', 'danger')
            return voltar()
        ultima = db.session.query(db.func.max(SfaPassoPesquisa.ordem)).scalar() or 0
        db.session.add(SfaPassoPesquisa(titulo=titulo, url=url, ordem=ultima + 1))
        db.session.commit()
        return voltar()

    @bp.route('/passos/<int:passo_id>', methods=['POST'])
    @require_access
    def passo_editar(passo_id):
        passo = db.get_or_404(SfaPassoPesquisa, passo_id)
        if request.form.get('acao') == 'remover':
            db.session.delete(passo)
            db.session.commit()
            flash(f'Passo "{passo.titulo}" removido.', 'success')
            return voltar()
        titulo = (request.form.get('titulo') or '').strip()[:120]
        try:
            url = url_valida(request.form.get('url'))
        except ValueError:
            flash('O link precisa começar com http:// ou https://. Nada foi alterado.', 'danger')
            return voltar()
        if not titulo:
            flash('Informe o nome do passo. Nada foi alterado.', 'danger')
            return voltar()
        passo.titulo, passo.url = titulo, url
        db.session.commit()
        return voltar()
