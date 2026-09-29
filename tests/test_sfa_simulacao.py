"""Simulações com voluntários: percurso SINAN → T0 → T7 → T30 e análise por grupo.

O ponto central: as mesmas perguntas e validações dos formulários reais, sem que
nada chegue à coorte municipal (SfaPaciente, SINAN, T0/T7/T30 reais).
"""
import csv
import io
import json
from datetime import date

import pytest
from werkzeug.datastructures import MultiDict

from extensions import db
from models.sfa import (SfaPaciente, SfaRespostaT0, SfaRespostaT7, SfaRespostaT30, SfaSinanLog,
                        SfaSimulacaoGrupo, SfaSimulacaoParticipante, SfaSimulacaoResposta)
from services import sfa_service
from services import sfa_simulacao as service


def _sinan(**extra):
    dados = {
        "ficha_sinan": "1234567", "tipo_notificacao": "2", "agravo": "1",
        "data_notificacao": "2026-09-22", "data_inicio_sintomas": "2026-09-20",
        "nome": "Pessoa Real Digitada", "nome_mae": "Mãe Real", "telefone": "16999990000",
        "cartao_sus": "123456789012345", "bairro": "Centro", "sexo": "F",
        "idade_valor": "34", "idade_unidade": "4",
        "logradouro": "Rua Verdadeira", "codigo_logradouro": "77",
        "sinais_clinicos__febre": "1", "sinais_clinicos__cefaleia": "1", "sinais_clinicos__exantema": "2",
        "ns1_resultado": "1", "investigador__nome": "Investigador Real", "investigador__funcao": "Enfermeira",
    }
    dados.update(extra)
    return dados


def _t0(**extra):
    dados = MultiDict([
        ("respondent_role", "A propria pessoa"),
        ("aceite_tcle", sfa_service.T0_CONSENT_ACCEPTED),
        ("data_inicio_sintomas", "2026-09-20"),
        ("outras_pessoas_com_sintomas", "Nao"),
        ("exposicao_ambiental", "Nenhuma exposicao ambiental"),
        ("exposicao_animal", "Nenhum contato animal relevante"),
        ("exposicao_alimentar", "Nenhuma dessas"),
        ("diagnostico_medico", "Nao"),
        ("sinais_alerta_atuais", "Nenhum destes sinais agora"),
        ("dias_incap", "2"), ("houve_gasto", "Nao"), ("ausencia_familiar", "Nao"),
    ])
    for chave, valor in extra.items():
        dados[chave] = valor
    return dados


def _t7(**extra):
    dados = {
        "classificacao_melhora": "Melhorando", "sinais_alerta_atuais": "Nenhum destes sinais agora",
        "retornou_servico_saude": "Nao", "diagnostico_medico": "Nao", "novos_casos_semelhantes": "Nao",
        "nova_pista_exposicao": "Nao", "dias_incap_novos": "3", "houve_novos_gastos": "Nao", "perda_renda": "Nao",
    }
    dados.update(extra)
    return dados


def _t30():
    return {
        "respondent_role": "A propria pessoa", "situacao_participante": "Vivo(a)",
        "estado_saude_final": "Quase recuperado(a) - diferencas minimas",
        "sintomas_atuais": "Cansaco ou fraqueza", "sintomas_atuais_origem": "Comecaram com esta doenca",
        "sinais_alerta_atuais": "Nenhum destes sinais agora", "retorno_atividades_normais": "Retorno completo",
        "diagnostico_medico": "Nao", "novos_casos_semelhantes": "Nao", "nova_informacao_fonte": "Nao",
        "dias_incap_novos": "1", "houve_novos_gastos": "Nao", "perda_renda": "Nao",
    }


@pytest.fixture
def hoje(monkeypatch):
    dia = {"valor": date(2026, 9, 29)}
    monkeypatch.setattr(service, "hoje_local", lambda: dia["valor"])
    monkeypatch.setattr("services.sfa_workflow.hoje_local", lambda: dia["valor"])
    return dia


def _criar_grupo(client, nome="Instituto", agenda="imediata", etapas=("sinan", "t0", "t7", "t30"), chave=None):
    resposta = client.post("/sfa/simulacoes", data=MultiDict(
        [("nome", nome), ("descricao", "Turma de teste"), ("agenda", agenda), ("creation_key", chave or nome),
         ("cenario_geral", "Ana, 34 anos, febre desde 20/09.")] + [("etapas", e) for e in etapas]))
    assert resposta.status_code == 302
    return SfaSimulacaoGrupo.query.filter_by(creation_key=chave or nome).one()


def _entrar(client, grupo, **dados):
    form = {"ciente": "sim", "perfil": service.PERFIS[0], "experiencia": service.EXPERIENCIAS_SINAN[1]}
    form.update(dados)
    resposta = client.post(f"/sfa/simulacao/{grupo.token_convite}", data=form)
    assert resposta.status_code == 302, resposta.data[:500]
    token = resposta.headers["Location"].split("/simulacao/p/")[1].split("?")[0]
    return SfaSimulacaoParticipante.query.filter_by(token=token).one()


def _ocultos(html):
    """Campos ocultos que o navegador reenviaria após um erro de validação."""
    import html as html_lib
    import re
    return {nome: html_lib.unescape(valor) for nome, valor in
            re.findall(r'name="(sim_inicio|sim_erros)" value="([^"]*)"', html)}


def _percurso_completo(client, participante, sinan=None, t0=None):
    base = f"/sfa/simulacao/p/{participante.token}"
    for etapa, dados in (("sinan", sinan or _sinan()), ("t0", t0 or _t0()), ("t7", _t7()), ("t30", _t30())):
        resposta = client.post(f"{base}/{etapa}", data=dados)
        assert resposta.status_code == 302, (etapa, resposta.data.decode()[:3000])
        assert resposta.headers["Location"].endswith(f"/{etapa}/avaliacao")


def test_grupo_e_criado_uma_vez_e_convite_inscreve_com_codigo_sequencial(app, client):
    grupo = _criar_grupo(client)
    assert _criar_grupo(client).id == grupo.id  # reenvio do mesmo formulário
    assert len(grupo.token_convite) >= 30
    assert service.cenarios_grupo(grupo) == {"geral": "Ana, 34 anos, febre desde 20/09."}

    pagina = client.get(f"/sfa/simulacao/{grupo.token_convite}")
    assert pagina.status_code == 200
    assert pagina.headers["Cache-Control"].startswith("no-store")
    assert "Ana, 34 anos" in pagina.get_data(as_text=True)

    sem_ciente = client.post(f"/sfa/simulacao/{grupo.token_convite}", data={"apelido": "Lu"})
    assert sem_ciente.status_code == 400
    assert SfaSimulacaoParticipante.query.count() == 0

    p1 = _entrar(client, grupo, apelido="Lu")
    p2 = _entrar(client, grupo)
    assert (p1.codigo, p2.codigo) == ("P01", "P02")
    assert p1.apelido == "Lu" and p1.perfil == service.PERFIS[0]
    # O navegador lembra do participante e oferece continuar.
    assert "Continuar minha simulação" in client.get(f"/sfa/simulacao/{grupo.token_convite}").get_data(as_text=True)
    assert client.get("/sfa/simulacao/token-invalido").status_code == 404
    assert client.get("/sfa/simulacao/p/token-invalido").status_code == 404


def test_percurso_completo_usa_formularios_reais_sem_tocar_na_coorte(app, client, hoje):
    grupo = _criar_grupo(client)
    participante = _entrar(client, grupo)
    base = f"/sfa/simulacao/p/{participante.token}"

    painel = client.get(base).get_data(as_text=True)
    assert "Responder Ficha SINAN" in painel
    assert client.get(f"{base}/t0").status_code == 409  # SINAN vem antes

    ficha = client.get(f"{base}/sinan").get_data(as_text=True)
    assert "SIMULAÇÃO" in ficha and 'name="sim_inicio"' in ficha
    assert "Ficha de investigação" in ficha  # a ficha real, não uma cópia

    # Erro de validação real: ficha sem campos obrigatórios volta com a mensagem
    # e a tentativa fica registrada para a análise.
    erro = client.post(f"{base}/sinan", data=_sinan(nome="", agravo=""))
    assert erro.status_code == 400
    texto = erro.get_data(as_text=True)
    assert "Preencha os campos obrigatórios" in texto
    ocultos = _ocultos(texto)
    assert len(json.loads(ocultos["sim_erros"])) == 1

    ok = client.post(f"{base}/sinan", data=_sinan(**ocultos))
    assert ok.status_code == 302

    t0 = client.get(f"{base}/t0").get_data(as_text=True)
    assert 'value="2026-09-20"' in t0  # início dos sintomas vem da ficha SINAN
    assert "somente nesta simulação" in t0

    incompleto = client.post(f"{base}/t0", data=_t0(dias_incap=""))
    assert incompleto.status_code == 400
    assert "Campo obrigatorio" in incompleto.get_data(as_text=True)
    for etapa, dados in (("t0", _t0(**_ocultos(incompleto.get_data(as_text=True)))), ("t7", _t7()), ("t30", _t30())):
        assert client.post(f"{base}/{etapa}", data=dados).status_code == 302

    respostas = service.respostas_por_etapa(db.session.get(SfaSimulacaoParticipante, participante.id))
    assert set(respostas) == {"sinan", "t0", "t7", "t30"}
    sinan = service.carregar_respostas(respostas["sinan"])
    guardado = json.dumps(sinan, ensure_ascii=False)
    for identificador in ("Pessoa Real", "Mãe Real", "16999990000", "123456789012345", "Rua Verdadeira", "Investigador Real"):
        assert identificador not in guardado
    assert sinan["nome"] == service.MARCADOR_OCULTO
    assert sinan["investigador"]["funcao"] == "Enfermeira"
    assert json.loads(respostas["sinan"].erros_json) == [["Preencha os campos obrigatórios indicados antes de enviar."]]
    assert json.loads(respostas["t0"].erros_json) == [["dias_incap"]]
    assert respostas["sinan"].duracao_segundos is not None

    t0_payload = service.carregar_respostas(respostas["t0"])
    assert t0_payload["_submitted_stage"] == "t0" and t0_payload["_simulacao"]["dia_doenca"] == 9
    assert "token_acesso" not in t0_payload and "nome" not in t0_payload

    for modelo in (SfaPaciente, SfaSinanLog, SfaRespostaT0, SfaRespostaT7, SfaRespostaT30):
        assert modelo.query.count() == 0, modelo.__name__

    assert client.get(f"{base}/t30").status_code == 200  # já respondida: aviso, sem novo envio
    assert client.post(f"{base}/t30", data=_t30()).status_code == 200
    assert SfaSimulacaoResposta.query.count() == 4
    assert "Simulação concluída" in client.get(base).get_data(as_text=True)


def test_ficha_ficticia_nao_puxa_dados_de_caso_real_do_sinan(app, client, hoje):
    db.session.add(SfaSinanLog(chave_dedup="FICHA-1234567", ficha_sinan="1234567", data_inicio_sintomas="01/09/2026",
                               tipo_exame="NS1", resultado="POSITIVO REAL"))
    db.session.commit()
    grupo = _criar_grupo(client)
    participante = _entrar(client, grupo)
    _percurso_completo(client, participante)
    for resposta in SfaSimulacaoResposta.query.all():
        assert "POSITIVO REAL" not in resposta.respostas_json
        assert "01/09/2026" not in resposta.respostas_json


def test_agenda_do_protocolo_libera_t7_no_d7_e_t30_no_d30(app, client, hoje):
    grupo = _criar_grupo(client, agenda="protocolo", etapas=("t0", "t7", "t30"))
    participante = _entrar(client, grupo)
    base = f"/sfa/simulacao/p/{participante.token}"
    hoje["valor"] = date(2026, 9, 22)
    assert client.post(f"{base}/t0", data=_t0()).status_code == 302

    bloqueada = client.get(f"{base}/t7")
    assert bloqueada.status_code == 409
    assert "27/09/2026" in bloqueada.get_data(as_text=True)

    hoje["valor"] = date(2026, 9, 27)
    assert client.post(f"{base}/t7", data=_t7()).status_code == 302
    assert client.get(f"{base}/t30").status_code == 409
    hoje["valor"] = date(2026, 10, 20)
    assert client.post(f"{base}/t30", data=_t30()).status_code == 302


def test_avaliacao_e_grupo_encerrado(app, client, hoje):
    grupo = _criar_grupo(client, etapas=("t0",))
    participante = _entrar(client, grupo)
    base = f"/sfa/simulacao/p/{participante.token}"
    assert client.get(f"{base}/t0/avaliacao").status_code == 302  # nada para avaliar ainda
    client.post(f"{base}/t0", data=_t0())
    assert b"Avalia" in client.get(f"{base}/t0/avaliacao").data
    resposta = client.post(f"{base}/t0/avaliacao", data={"facilidade": "4", "confusa": "A pergunta 3 é longa."})
    assert resposta.status_code == 302 and "feito=t0" in resposta.headers["Location"]
    avaliacao = service.carregar_avaliacao(SfaSimulacaoResposta.query.one())
    assert avaliacao["facilidade"] == "4" and avaliacao["confusa"] == "A pergunta 3 é longa."

    client.post(f"/sfa/simulacoes/{grupo.id}/status", data={"status": "encerrado"})
    assert "foi encerrado" in client.get(f"/sfa/simulacao/{grupo.token_convite}").get_data(as_text=True)
    assert client.post(f"/sfa/simulacao/{grupo.token_convite}", data={"ciente": "sim"}).status_code == 400
    outro = SfaSimulacaoParticipante(grupo_id=grupo.id, codigo="P09", token="t" * 40)
    db.session.add(outro)
    db.session.commit()
    assert client.post(f"/sfa/simulacao/p/{outro.token}/t0", data=_t0()).status_code == 409


def test_analise_por_grupo_consolidada_e_exportacoes(app, client, hoje):
    instituto = _criar_grupo(client, "Instituto")
    trabalho = _criar_grupo(client, "Vigilância")
    for grupo, sexo in ((instituto, "F"), (instituto, "F"), (instituto, "F"), (trabalho, "M"), (trabalho, "M"), (trabalho, "F")):
        _percurso_completo(client, _entrar(client, grupo), sinan=_sinan(sexo=sexo))
    participante_incompleto = _entrar(client, trabalho)
    client.post(f"/sfa/simulacao/p/{participante_incompleto.token}/sinan", data=_sinan())
    client.post(f"/sfa/simulacao/p/{participante_incompleto.token}/sinan/avaliacao",
                data={"facilidade": "2", "sugestao": "Explicar o campo 7."})

    analise = service.montar_analise([instituto, trabalho])
    assert analise["kpis"]["participantes"] == 7 and analise["kpis"]["concluidos"] == 6
    funil = {linha["coluna"]["rotulo"]: {e["etapa"]: e["n"] for e in linha["etapas"]} for linha in analise["funil"]}
    assert funil["Consolidado"] == {"sinan": 7, "t0": 6, "t7": 6, "t30": 6}
    assert funil["Vigilância"]["sinan"] == 4 and funil["Instituto"]["t30"] == 3

    sexo = next(p for p in analise["perguntas"]["sinan"] if p["id"] == "sexo")
    assert sexo["colunas"]["todos"]["opcoes"]["F"]["n"] == 5
    assert sexo["colunas"][str(instituto.id)]["opcoes"]["F"]["pct"] == 1
    # Instituto: 3 de 3 com F. Vigilância: 2 de 4 (o 4º enviou só a ficha, também F).
    assert sexo["diferenca"] == pytest.approx(0.5)
    assert any(d["id"] == "sexo" for d in analise["destaques"]["diferencas"])
    nome = next(p for p in analise["perguntas"]["sinan"] if p["id"] == "nome")
    assert nome["tipo"] == "oculto" and nome["colunas"]["todos"]["n_preenchida"] == 7
    assert analise["comentarios"][0]["texto"] == "Explicar o campo 7."

    pagina = client.get(f"/sfa/simulacoes/analise?g={instituto.id}&g={trabalho.id}&etapa=sinan")
    texto = pagina.get_data(as_text=True)
    assert pagina.status_code == 200
    assert "Consolidado" in texto and "Instituto" in texto and "Vigilância" in texto
    assert "Explicar o campo 7." in texto
    assert "Pessoa Real" not in texto
    assert client.get(f"/sfa/simulacoes/analise?g={instituto.id}&etapa=t0").status_code == 200
    assert client.get("/sfa/simulacoes/analise?visao=consolidado&etapa=t30").status_code == 200

    largo = list(csv.DictReader(io.StringIO(client.get("/sfa/simulacoes/exportar.csv?formato=largo").get_data(as_text=True).lstrip("﻿"))))
    assert len(largo) == 7
    assert {linha["grupo"] for linha in largo} == {"Instituto", "Vigilância"}
    assert largo[0]["sinan__nome"] == service.MARCADOR_OCULTO
    assert largo[0]["t0__dias_incap"] == "2"
    longo = client.get(f"/sfa/simulacoes/exportar.csv?g={instituto.id}").get_data(as_text=True)
    assert "Pessoa Real" not in longo and "Vigilância" not in longo
    assert "sinais_clinicos__febre" in longo

    for url in ("/sfa/simulacoes", f"/sfa/simulacoes/{instituto.id}",
                f"/sfa/simulacoes/participante/{participante_incompleto.id}"):
        assert client.get(url).status_code == 200, url


def test_equipe_remove_participante_de_teste_e_nao_exclui_grupo_com_respostas(app, client, hoje):
    grupo = _criar_grupo(client, etapas=("t0",))
    participante = _entrar(client, grupo)
    client.post(f"/sfa/simulacao/p/{participante.token}/t0", data=_t0())
    client.post(f"/sfa/simulacoes/{grupo.id}/excluir")
    assert db.session.get(SfaSimulacaoGrupo, grupo.id) is not None
    client.post(f"/sfa/simulacoes/participante/{participante.id}/excluir")
    assert SfaSimulacaoParticipante.query.count() == 0 and SfaSimulacaoResposta.query.count() == 0
    client.post(f"/sfa/simulacoes/{grupo.id}/excluir")
    assert db.session.get(SfaSimulacaoGrupo, grupo.id) is None


def test_ficha_sinan_real_renderiza(app, client):
    """A ficha pré-T0 real quebrava com 500: `field.items` devolvia o método do dict."""
    resposta = client.get("/sfa/pre-t0")
    assert resposta.status_code == 200
    texto = resposta.get_data(as_text=True)
    assert 'name="sinais_clinicos__febre"' in texto and 'name="investigador__funcao"' in texto
    assert "SIMULAÇÃO" not in texto  # os ganchos da simulação não vazam para o fluxo real


def test_templates_nao_desempacotam_metodo_de_dict_sem_chamar():
    """Guarda de classe: em Jinja, `x.items` num dict é o método, não a chave "items".

    `{% for a, b in campo.items %}` passa no olho e estoura só em tempo de
    renderização. Use `campo['items']` (chave) ou `campo.items()` (método).
    """
    import re
    from pathlib import Path

    padrao = re.compile(r"{%-?\s*for\s+\w+\s*,[^%]*?\bin\s+[\w.\[\]'\"]+\.(items|keys|values)\s*-?%}")
    raiz = Path(__file__).resolve().parents[1] / "templates"
    achados = []
    for arquivo in raiz.rglob("*.html"):
        for numero, linha in enumerate(arquivo.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if padrao.search(linha):
                achados.append(f"{arquivo.relative_to(raiz)}:{numero}")
    assert not achados, "Iteração sobre método de dict sem chamar: " + ", ".join(achados)
