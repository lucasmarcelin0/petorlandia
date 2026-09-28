"""Página pública do trabalho de campo contra o Aedes em Orlândia.

Mostra somente o último boletim agregado por setor que a equipe publicou em
/sfa/entomologia/atualizar. Sem boletim, exibe apenas orientações à população.
"""
import json

from flask import Blueprint, current_app, render_template

bp = Blueprint("vigilancia_publica", __name__)


def get_blueprint():
    return bp


@bp.route("/aedes")
def painel_aedes_publico():
    from blueprints.entomologia_routes import publicacao_vigente
    from services.entomologia_service import malha_publica

    publicacao = publicacao_vigente()
    boletim = json.loads(publicacao.dados_json) if publicacao else None
    response = current_app.make_response(render_template(
        "vigilancia/aedes.html", boletim=boletim, publicacao=publicacao, previa=False,
        census=malha_publica() if boletim else None,
    ))
    response.headers["Cache-Control"] = "public, max-age=300"
    return response
