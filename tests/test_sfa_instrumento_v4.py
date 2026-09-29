"""Instrumento collective-v4-2026-09-29, a partir da simulação com voluntários.

- T0: bebidas em festa, bar ou confraternização entre as exposições.
- T7: para quem já se recuperou, a permanência da fonte só é perguntada se o
  próprio T7 trouxer caso novo ou pista nova. Sinais de alerta continuam: na
  dengue a fase crítica começa quando a febre cede e a pessoa se sente melhor.
- T30: apresentação explicando por que ainda há contato no 30º dia.

A versão anterior fica arquivada com hash, e respostas antigas continuam
lidas com as perguntas que a pessoa realmente viu.
"""
import json
from datetime import date
from types import SimpleNamespace

from services import sfa_service, sfa_workflow

V3 = "collective-v3-disease-clock"
V4 = "collective-v4-2026-09-29"
BEBIDAS = "Bebidas em festa, bar ou confraternizacao (alcoolicas ou nao)"


def _campo(schema, chave):
    return next(f for f in sfa_service.iterar_campos_form(schema) if f["key"] == chave)


def test_versao_anterior_fica_arquivada_com_hash_e_contagens():
    versoes = {v["id"]: v for v in sfa_service.listar_historico_instrumentos()}
    arquivada = versoes[V3]
    assert arquivada["status"] == "archived" and arquivada["archived_at"] == "2026-09-29"
    assert {etapa: dados["field_count"] for etapa, dados in arquivada["stages"].items()} == {
        "t0": 35, "t7": 19, "t30": 28}
    for etapa in ("t0", "t7", "t30"):
        assert sfa_service.carregar_form_schema(etapa)["instrument_version"] == V4


def test_resposta_antiga_continua_lida_com_as_perguntas_que_a_pessoa_viu():
    antiga = sfa_service.carregar_schema_para_payload("t0", {"_instrument_version": V3})
    atual = sfa_service.carregar_schema_para_payload("t0", {"_instrument_version": V4})
    assert antiga["_instrument_version"] == V3 and antiga["_readonly"]
    assert BEBIDAS not in _campo(antiga, "exposicao_alimentar")["options"]
    assert BEBIDAS in _campo(atual, "exposicao_alimentar")["options"]


def test_t0_inclui_bebidas_em_festas():
    t0 = sfa_service.carregar_t0_form_schema()
    opcoes = _campo(t0, "exposicao_alimentar")["options"]
    assert opcoes.index(BEBIDAS) == opcoes.index("Refeicao em evento ou estabelecimento") + 1
    assert "bebida" in _campo(t0, "exposicao_alimentar")["label"]
    assert "bebida" in _campo(t0, "exposicao_alimentar_item")["label"]
    # Marcar bebidas abre as perguntas de detalhe, como as outras exposições.
    regra = _campo(t0, "exposicao_alimentar_item")["visible_if"]
    assert sfa_service._avaliar_regra_visibilidade(regra, {"exposicao_alimentar": [BEBIDAS]}, [])


def test_t7_fluxo_curto_para_quem_se_recuperou_mantem_sinais_de_alerta():
    t7 = sfa_service.carregar_t7_form_schema()
    pista_no_t0 = [{"_submitted_stage": "t0", "outras_pessoas_com_sintomas": "Sim"}]
    for chave in ("fonte_ainda_ativa", "outras_pessoas_ainda_expostas"):
        regra = _campo(t7, chave)["visible_if"]

        def visivel(respostas):
            return sfa_service._avaliar_regra_visibilidade(regra, respostas, pista_no_t0)
        assert visivel({"classificacao_melhora": "Melhorando"})
        assert not visivel({"classificacao_melhora": "Recuperado(a)", "novos_casos_semelhantes": "Nao",
                            "nova_pista_exposicao": "Nao"})
        assert visivel({"classificacao_melhora": "Recuperado(a)", "nova_pista_exposicao": "Sim"})
        # Sem pista nenhuma, nada muda: só abre com caso novo ou pista nova.
        assert not sfa_service._avaliar_regra_visibilidade(regra, {"classificacao_melhora": "Melhorando"}, [])
    assert "visible_if" not in _campo(t7, "sinais_alerta_atuais")


def test_t30_explica_por_que_ainda_ha_contato():
    subtitulo = sfa_service.carregar_t30_form_schema()["subtitle"]
    assert subtitulo.startswith("Mesmo que você já esteja bem há semanas")
    assert "dengue e chikungunya" in subtitulo


def test_inicio_dos_sintomas_ausente_e_sinalizado_nas_duas_versoes(monkeypatch):
    monkeypatch.setattr(sfa_workflow, "hoje_local", lambda: date(2026, 9, 29))
    for versao in (V3, V4):
        paciente = SimpleNamespace(contexto=None, _sinan_log=None, _sinan_dados={}, resposta_t0=SimpleNamespace(
            dados_json=json.dumps({"_instrument_version": versao}), data_inicio_sintomas=None))
        inicio, motivo = sfa_workflow.inicio_doenca(paciente)
        assert inicio is None and "não informado no T0" in motivo, versao
