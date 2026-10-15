"""Ficha SINAN preenchida online, impressa na disposição da folha oficial.

Guarda de classe: tudo o que a ficha digital pergunta tem lugar na folha. Um campo
novo no esquema que não entre na impressão derruba estes testes em vez de sumir do papel.
"""
import json
import re

from bs4 import BeautifulSoup
from werkzeug.datastructures import MultiDict

from extensions import db
from models.sfa import SfaSimulacaoGrupo, SfaSimulacaoParticipante
from services import sfa_simulacao as simulacao
from services.sfa_pre_t0 import carregar_esquema_pre_t0, coletar_respostas_pre_t0, montar_folha_pre_t0

# Casas que a folha oferece para cada código; o texto livre dos demais campos só respeita o maxlength.
DIGITOS = {"ficha_sinan": 7, "cartao_sus": 15, "cep": 8, "telefone": 11, "telefone_hospital": 10,
           "codigo_logradouro": 6, "investigador__codigo_unidade": 7}


def _campos(schema):
    return [field for section in schema["sections"] for field in section["fields"]]


def _formulario_completo(schema):
    """Um envio com todos os campos da ficha preenchidos, cada um com um valor reconhecível."""
    form, contador = {}, iter(range(1, 10_000))

    def digitos(nome, quantidade):
        return str(next(contador)).rjust(DIGITOS.get(nome, quantidade), "7")

    def texto(nome, limite):
        if nome.startswith("uf_"):
            return "SP"
        return f"valor {nome}"[:limite]

    for field in _campos(schema):
        key, kind = field["key"], field["type"]
        if kind == "fixed":
            form[key] = field["value"]
        elif kind in {"text", "tel"}:
            numerico = field.get("numeric") or kind == "tel"
            form[key] = digitos(key, 7) if numerico else texto(key, field["maxlength"])
        elif kind == "textarea":
            form[key] = "Primeira linha das observações.\nSegunda linha."
        elif kind == "date":
            form[key] = f"2026-{next(contador) % 12 + 1:02d}-{next(contador) % 28 + 1:02d}"
        elif kind == "radio":
            form[key] = field["options"][-1]["value"]
        elif kind == "paired_text":
            form[key] = texto(key, field["maxlength"])
            form[field["extra_key"]] = digitos(field["extra_key"], min(7, field["extra_maxlength"]))
        elif kind == "age":
            form["idade_valor"], form["idade_unidade"] = "42", field["units"][-1]["value"]
        elif kind == "matrix":
            for posicao, (item, _rotulo) in enumerate(field["items"]):
                form[f"{key}__{item}"] = field["options"][posicao % len(field["options"])]["value"]
        elif kind == "test_result":
            for posicao, (amostra, _rotulo) in enumerate(field["samples"]):
                form[f"{key}__res__{amostra}"] = field["options"][posicao % len(field["options"])]["value"]
        elif kind == "flag_matrix":
            form[key] = "1"
            for item, _rotulo in field["items"][::2]:
                form[f"{key}__{item}"] = "1"
        elif kind == "severity":
            form[key] = "1"
            for _grupo, itens in field["groups"]:
                form[f"{key}__{itens[-1][0]}"] = "1"
            form["outros_orgaos_especificar"] = "valor outros_orgaos_especificar"
        elif kind == "investigator":
            for item, _rotulo, limite in field["items"]:
                nome = f"{key}__{item}"
                form[nome] = digitos(nome, 7) if nome in DIGITOS else texto(nome, limite)
        else:
            raise AssertionError(f"Tipo de campo sem caso neste teste: {kind}")
    return form


def _no_papel(valor):
    """Como um valor do formulário é lido na folha: a data perde as barras e ocupa as oito casas."""
    data = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", valor)
    return "".join(reversed(data.groups())) if data else valor


def _escrito(elemento):
    if elemento.has_attr("data-valor"):
        return elemento["data-valor"]
    casas = elemento.find_all("i", recursive=False)
    return "".join(casa.get_text() for casa in casas) if casas else elemento.get_text()


def _folha_do_caso(client, form):
    enviado = client.post("/sfa/pre-t0", data=form)
    assert enviado.status_code == 200
    pagina = BeautifulSoup(enviado.get_data(as_text=True), "html.parser")
    link = pagina.find("a", string=re.compile("Imprimir no formato SINAN"))
    assert link, "A tela de ficha enviada precisa oferecer a impressão no formato SINAN."
    resposta = client.get(link["href"])
    assert resposta.status_code == 200
    return resposta, BeautifulSoup(resposta.get_data(as_text=True), "html.parser")


def test_tudo_o_que_foi_preenchido_online_sai_na_folha(app, client):
    schema = carregar_esquema_pre_t0()
    form = _formulario_completo(schema)

    resposta, folha = _folha_do_caso(client, form)

    assert resposta.headers["Cache-Control"] == "private, no-store"
    ausentes, divergentes = [], []
    for nome, valor in form.items():
        casas = folha.select(f'.folha [data-campo="{nome.replace("__res__", "__")}"]')
        if len(casas) != 1:
            ausentes.append(f"{nome} ({len(casas)} lugares)")
        elif _escrito(casas[0]) != _no_papel(valor):
            divergentes.append(f"{nome}: enviado {valor!r}, impresso {_escrito(casas[0])!r}")
    assert not ausentes, "Campos da ficha digital sem lugar único na folha: " + ", ".join(ausentes)
    assert not divergentes, "Valores impressos diferentes dos enviados: " + "; ".join(divergentes)


def test_folha_nao_tem_casa_sem_resposta_correspondente(app, client):
    schema = carregar_esquema_pre_t0()
    form = _formulario_completo(schema)
    previsto = set(montar_folha_pre_t0(coletar_respostas_pre_t0(MultiDict(form), schema), schema)["valores"])

    _resposta, folha = _folha_do_caso(client, form)

    # Um data-campo com nome errado no template renderiza vazio sem erro: aqui ele aparece.
    impresso = {elemento["data-campo"] for elemento in folha.select(".folha [data-campo]")}
    assert impresso == previsto


def test_folha_segue_a_numeracao_e_a_divisao_de_paginas_da_ficha_oficial(app, client):
    _resposta, folha = _folha_do_caso(client, _formulario_completo(carregar_esquema_pre_t0()))

    paginas = folha.select("section.folha")
    assert len(paginas) == 2
    numeros = [[numero.get_text() for numero in pagina.select("b.n")] for pagina in paginas]
    assert numeros[0] == [str(n) for n in range(1, 50)]
    assert numeros[1] == [str(n) for n in range(50, 72)]
    for pagina in paginas:
        assert "Sinan Online" in pagina.select_one(".rodape").get_text(" ", strip=True)
        assert "14/03/2016" in pagina.select_one(".rodape").get_text()
    assert "Observações Adicionais" in paginas[1].get_text()
    assert "Assinatura" in paginas[1].get_text()


def test_cada_codigo_impresso_tem_a_legenda_do_proprio_campo_ao_lado(app, client):
    schema = carregar_esquema_pre_t0()
    _resposta, folha = _folha_do_caso(client, _formulario_completo(schema))

    def casa_de(nome):
        return folha.select_one(f'.folha [data-campo="{nome}"]').find_parent(class_="campo").get_text(" ")

    faltando = []
    for field in _campos(schema):
        key, kind = field["key"], field["type"]
        alvo = {"age": "idade_unidade", "matrix": f"{key}__{field['items'][0][0]}" if kind == "matrix" else "",
                "test_result": f"{key}__{field['samples'][0][0]}" if kind == "test_result" else ""}.get(kind, key)
        for opcao in field.get("options") or field.get("units") or []:
            if opcao["label"] not in casa_de(alvo):
                faltando.append(f"{field['number']}: {opcao['label']}")
    assert not faltando, "Opções sem legenda junto da casa do código: " + ", ".join(faltando)


def test_sinais_de_alarme_viram_um_codigo_por_casa(app):
    schema = carregar_esquema_pre_t0()

    def codigos(status, marcados):
        valores = montar_folha_pre_t0({"sinais_alarme": {"status": status, "sinais_marcados": marcados}}, schema)["valores"]
        return valores["sinais_alarme__queda_plaquetas"], valores["sinais_alarme__hepatomegalia"]

    assert codigos("1", ["queda_plaquetas"]) == ("1", "2")
    assert codigos("2", []) == ("2", "2")
    assert codigos("9", []) == ("9", "9")
    # "Sim" sem nenhum sinal marcado não diz quais são: as casas ficam em branco.
    assert codigos("1", []) == ("", "")
    assert codigos("", []) == ("", "")


def test_ficha_antiga_e_valor_fora_das_casas_continuam_legiveis(app):
    schema = carregar_esquema_pre_t0()
    valores = montar_folha_pre_t0({
        "prnt_resultado": {"amostras": ["s1", "prnt"], "resultado": "2"},  # formato anterior ao resultado por exame
        "telefone": "16 3826 1234 ramal 22",
        "data_notificacao": "outubro de 2026",
        "idade": {"valor": "7", "unidade": "4"},
        "cep": "14620000",
    }, schema)["valores"]

    assert (valores["prnt_resultado__s1"], valores["prnt_resultado__s2"], valores["prnt_resultado__prnt"]) == ("2", "", "2")
    assert valores["telefone"] == "16 3826 1234 ramal 22"
    assert valores["data_notificacao"] == "outubro de 2026"
    assert valores["idade_valor"] == ["", "", "7"]
    assert valores["cep"] == list("14620000")
    assert valores["data_obito"] == [""] * 8


def test_observacoes_longas_diminuem_a_letra_em_vez_de_serem_cortadas(app, client):
    schema = carregar_esquema_pre_t0()
    form = _formulario_completo(schema)
    form["observacoes_adicionais"] = "\n".join(f"Linha {numero} das observações." for numero in range(1, 25))

    _resposta, folha = _folha_do_caso(client, form)

    assert montar_folha_pre_t0({"observacoes_adicionais": "Uma linha."}, schema)["densidade_observacoes"] == 1
    assert "--densidade:3" in folha.select_one(".pautas")["style"]
    assert folha.select_one('[data-campo="observacoes_adicionais"]').get_text() == form["observacoes_adicionais"]


def test_caso_sem_ficha_digital_nao_tem_folha(app, client):
    assert client.get("/sfa/paciente/SFA-INEXISTENTE/ficha-pre-t0/imprimir").status_code == 404


def _participante_da_simulacao(client):
    criado = client.post("/sfa/simulacoes", data=MultiDict([
        ("nome", "Equipe da vigilância"), ("descricao", "Teste"), ("agenda", "imediata"),
        ("creation_key", "impressao"), ("etapas", "sinan"), ("etapas", "t0")]))
    assert criado.status_code == 302
    grupo = SfaSimulacaoGrupo.query.filter_by(creation_key="impressao").one()
    entrada = client.post(f"/sfa/simulacao/{grupo.token_convite}", data={"ciente": "sim"})
    assert entrada.status_code == 302
    return SfaSimulacaoParticipante.query.filter_by(grupo_id=grupo.id).one()


def test_simulacao_imprime_a_ficha_com_todos_os_dados(app, client):
    participante = _participante_da_simulacao(client)
    sem_ficha = client.get(f"/sfa/simulacoes/participante/{participante.id}/ficha-sinan")
    assert sem_ficha.status_code == 404

    form = _formulario_completo(carregar_esquema_pre_t0())
    form["nome"] = "Pessoa Real Digitada"
    enviado = client.post(f"/sfa/simulacao/p/{participante.token}/sinan", data=form)
    assert enviado.status_code == 302

    painel = client.get(f"/sfa/simulacoes/participante/{participante.id}").get_data(as_text=True)
    endereco = f"/sfa/simulacoes/participante/{participante.id}/ficha-sinan"
    assert f'href="{endereco}"' in painel

    resposta = client.get(endereco)
    assert resposta.status_code == 200
    assert resposta.headers["Cache-Control"].startswith("no-store")
    html = resposta.get_data(as_text=True)
    folha = BeautifulSoup(html, "html.parser")
    # A simulação guarda tudo o que foi digitado: a folha sai como a real, sem campo a completar.
    nome = folha.select_one('.folha [data-campo="nome"]')
    assert nome.get_text() == "Pessoa Real Digitada" and not nome.has_attr("contenteditable")
    assert folha.select_one('.folha [data-campo="bairro"]').get_text() == form["bairro"]
    assert not folha.select(".nao-guardado") and not folha.select_one(".aviso")
    for pagina in folha.select("section.folha"):
        assert "SIMULAÇÃO" in pagina.select_one(".margem").get_text()
        assert "sem valor de notificação" in pagina.select_one(".margem").get_text()

    # Ficha enviada antes de a simulação guardar tudo: o identificador gravado como "[preenchido]"
    # continua editável na tela, só para a impressão, e a folha avisa por quê.
    enviada = simulacao.respostas_por_etapa(participante)["sinan"]
    antiga = simulacao.carregar_respostas(enviada)
    antiga["nome"] = simulacao.MARCADOR_OCULTO
    enviada.respostas_json = json.dumps(antiga, ensure_ascii=False)
    db.session.commit()
    folha = BeautifulSoup(client.get(endereco).data, "html.parser")
    nome = folha.select_one('.folha [data-campo="nome"]')
    assert nome.get_text() == simulacao.MARCADOR_OCULTO and nome["contenteditable"] == "true"
    assert "antes de a simulação guardar todos os dados" in folha.select_one(".aviso").get_text()
    assert not folha.select_one('.folha [data-campo="bairro"]').has_attr("contenteditable")
