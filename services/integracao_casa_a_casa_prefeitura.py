"""Casa a Casa (entomologia) e Prefeitura integrada funcionando juntos.

A solicitação para outro setor registrada em campo, com foto e local, também
abre uma comunicação no mapa da Prefeitura integrada, ligada a ela por
``LimpezaSolicitacao.entomologia_solicitacao_id``. A partir daí:

* a equipe da Prefeitura comprova o serviço com foto → a solicitação do Casa a
  Casa fica Resolvida; comprovação recusada → volta a Aberta;
* a fiscalização descarta a comunicação → a solicitação volta a Aberta, com o
  motivo no histórico, para o escritório encaminhar por ofício;
* a solicitação é excluída no Casa a Casa → a comunicação aberta é descartada;
  restaurada → a comunicação volta para a fila.

Sem foto (o mapa da Prefeitura trabalha com antes e depois) ou sem local, a
solicitação fica só no Casa a Casa; ganhando a foto numa correção, ela segue.
"""
from __future__ import annotations

import unicodedata

from time_utils import utcnow

# Tipo do Casa a Casa → tipos da Prefeitura integrada (os que existirem no catálogo).
MAPA_TIPOS = {
    "LIXO_ENTULHO": ("lixo", "entulho"),
    "TERRENO": ("lixo",),
    "PONTO_ESTRATEGICO": ("entulho",),
}
ROTULO_ORIGEM = "Casa a Casa"
MOTIVO_EXCLUIDA = "Solicitação excluída no Casa a Casa."


def _sem_acento(texto) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(texto.casefold().split())


def tipos_da_prefeitura(categoria: str, categoria_nome: str) -> str:
    """Chaves da Prefeitura integrada para o tipo do Casa a Casa; "outro" quando não há equivalente."""
    from services import limpeza_urbana as limpeza

    catalogo = limpeza.catalogo()
    nome = _sem_acento(categoria_nome)
    iguais = [chave for chave, rotulo in catalogo.items() if nome and _sem_acento(rotulo) == nome]
    escolhidas = limpeza.normalizar_categorias(iguais or MAPA_TIPOS.get(categoria, ()))
    if escolhidas:
        return escolhidas
    if limpeza.CHAVE_OUTRO in catalogo:
        return limpeza.CHAVE_OUTRO
    return limpeza.normalizar_categorias([limpeza.CHAVE_OUTRO], incluir_inativos=True) or limpeza.CHAVE_OUTRO


def comunicacao_de(solicitacao):
    from models.limpeza import LimpezaSolicitacao

    if solicitacao is None or solicitacao.id is None:
        return None
    return LimpezaSolicitacao.query.filter_by(entomologia_solicitacao_id=solicitacao.id).first()


def _referencia(s) -> str:
    partes = [", ".join(p for p in (s.logradouro, s.numero) if p)]
    if s.complemento:
        partes.append(s.complemento)
    if s.quarteirao:
        partes.append(f"Quarteirão {s.quarteirao}")
    if s.setor:
        partes.append(f"SC {s.setor}")
    return " · ".join(p for p in partes if p)[:200]


def _descricao(s, nome_tipo: str) -> str:
    texto = f"[{ROTULO_ORIGEM} · {nome_tipo}] {s.descricao or ''}".strip()
    if s.destino:
        texto += f" (encaminhar para: {s.destino})"
    return texto[:500]


def enviar(solicitacao, usuario):
    """Abre a comunicação da Prefeitura integrada para a solicitação, se couber. Devolve a comunicação ou None."""
    from extensions import db
    from models.limpeza import LimpezaSolicitacao
    from services import entomologia_casa_a_casa as casa
    from services import limpeza_urbana as limpeza

    if solicitacao is None or solicitacao.excluida_em is not None or solicitacao.status == "RESOLVIDA":
        return None
    if not solicitacao.foto_url or solicitacao.latitude is None or solicitacao.longitude is None:
        return None
    existente = comunicacao_de(solicitacao)
    if existente is not None:
        return existente
    nome_tipo = casa.nomes_das_categorias().get(solicitacao.categoria, solicitacao.categoria)
    autor_id = solicitacao.agente_id or getattr(usuario, "id", None)
    if autor_id is None:
        return None
    comunicacao = LimpezaSolicitacao(
        numero=limpeza.proximo_numero(), autor_id=autor_id,
        categorias=tipos_da_prefeitura(solicitacao.categoria, nome_tipo),
        descricao=_descricao(solicitacao, nome_tipo), referencia=_referencia(solicitacao) or None,
        latitude=solicitacao.latitude, longitude=solicitacao.longitude, precisao_m=solicitacao.precisao_m,
        # Sem precisão é a posição do imóvel no mapa (o aparelho não pegou GPS).
        origem_local="aparelho" if solicitacao.precisao_m is not None else "imovel",
        foto_url=solicitacao.foto_url, foto_capturada_em=solicitacao.registrado_em,
        status="aberta", entomologia_solicitacao_id=solicitacao.id,
    )
    db.session.add(comunicacao)
    db.session.flush()
    limpeza.registrar_evento("comunicada", comunicacao.id, usuario,
                             f"{limpeza.rotulo_categorias(comunicacao.categorias)} (Casa a Casa, imóvel "
                             f"{solicitacao.imovel or '—'})")
    # O andamento e o ofício continuam com o escritório; o vínculo aparece como "Prefeitura integrada nº X".
    return comunicacao


def _mudar_status(solicitacao, usuario, novo: str, nota: str) -> None:
    from services import entomologia_casa_a_casa as casa

    mudou = {"prefeitura": ["", nota]}
    if solicitacao.status != novo:
        mudou["status"] = [solicitacao.status, novo]
        solicitacao.status = novo
    casa._anotar(solicitacao, usuario, "andamento", mudou)


def apos_mudanca_na_prefeitura(comunicacao, usuario) -> None:
    """Leva para a solicitação do Casa a Casa o que aconteceu na comunicação (comprovada, recusada, descartada)."""
    solicitacao = comunicacao.origem_casa_a_casa if comunicacao is not None else None
    if solicitacao is None or solicitacao.excluida_em is not None:
        return
    numero = comunicacao.num
    if comunicacao.status == "concluida":
        _mudar_status(solicitacao, usuario, "RESOLVIDA", f"Nº {numero}: atendimento comprovado com foto")
    elif comunicacao.status == "aberta":
        _mudar_status(solicitacao, usuario, "ABERTA", f"Nº {numero}: comprovação recusada, de volta à fila")
    elif comunicacao.status == "descartada":
        if (comunicacao.motivo_descarte or "") == MOTIVO_EXCLUIDA:
            return
        _mudar_status(solicitacao, usuario, "ABERTA",
                      f"Nº {numero} descartada na Prefeitura: {comunicacao.motivo_descarte or 'sem motivo'}")


def apos_exclusao_no_casa_a_casa(solicitacao, usuario, restaurada: bool) -> None:
    """Exclusão no Casa a Casa descarta a comunicação aberta; restauração a devolve à fila."""
    from services import limpeza_urbana as limpeza

    comunicacao = comunicacao_de(solicitacao)
    if comunicacao is None:
        if restaurada:
            enviar(solicitacao, usuario)
        return
    if not restaurada and comunicacao.status == "aberta":
        comunicacao.status, comunicacao.descartada_em = "descartada", utcnow()
        comunicacao.descartada_por = limpeza.nome_da_conta(usuario)
        comunicacao.motivo_descarte = MOTIVO_EXCLUIDA
        limpeza.registrar_evento("descartada", comunicacao.id, usuario, MOTIVO_EXCLUIDA)
    elif restaurada and comunicacao.status == "descartada" and comunicacao.motivo_descarte == MOTIVO_EXCLUIDA:
        comunicacao.status = "aberta"
        comunicacao.descartada_em = comunicacao.descartada_por = comunicacao.motivo_descarte = None
        limpeza.registrar_evento("reaberta", comunicacao.id, usuario, "Solicitação restaurada no Casa a Casa.")


def vinculos(ids) -> dict:
    """{id da solicitação do Casa a Casa: resumo da comunicação na Prefeitura} numa consulta só."""
    from models.limpeza import LimpezaSolicitacao
    from services import limpeza_urbana as limpeza

    ids = [i for i in (ids or []) if i is not None]
    if not ids:
        return {}
    try:
        linhas = LimpezaSolicitacao.query.filter(LimpezaSolicitacao.entomologia_solicitacao_id.in_(ids)).all()
    except Exception:  # tabela/coluna ausente antes da migration
        from extensions import db
        db.session.rollback()
        return {}
    return {c.entomologia_solicitacao_id: resumo(c, limpeza) for c in linhas}


def resumo(comunicacao, limpeza=None) -> dict:
    if limpeza is None:
        from services import limpeza_urbana as limpeza
    try:
        from flask import url_for
        url = url_for("limpeza_urbana.solicitacao", solicitacao_id=comunicacao.id)
    except Exception:
        url = f"/limpeza-urbana/solicitacao/{comunicacao.id}"
    return {"id": comunicacao.id, "numero": comunicacao.num, "status": comunicacao.status,
            "status_nome": limpeza.STATUS.get(comunicacao.status, comunicacao.status), "url": url}
