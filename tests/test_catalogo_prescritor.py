"""O bulário usa o catálogo do prescritor do VetSmart, e o importador é comedido.

O prescritor do VetSmart lista apresentações que a página pública de bula não
tem: as dos princípios ativos genéricos. Na clínica, 246 de 716 receitas são
por princípio ativo (Dipirona, Prednisona, Cefalexina...), justamente onde o
bulário não tinha a lista que o VetSmart oferece.

Os itens abaixo reproduzem respostas reais do catálogo (só os campos lidos).
"""
import urllib.error
from datetime import date
from types import SimpleNamespace

import pytest

from extensions import db
from models import Medicamento, User
from scripts import auditar_prescricao_por_produto as auditor
from services import bulario
from services import catalogo_prescritor as catalogo

escopo = bulario._esc


# ───────────────────────── respostas do catálogo ───────────────────────────


def _forma(dfid, rotulo, concentracao, tipo, ordem, *, quantidade='', info='', nome='Dipirona'):
    return {
        'formattedDrugDosageFormFull': f'{nome} {rotulo}',
        'formattedDrugDosageFormForPrescription': rotulo,
        'concentration': concentracao, 'quantity': quantidade, 'type': tipo, 'info': info,
        'dosageFormId': dfid, 'sortSequence': str(ordem),
    }


def _dose(minimo, maximo, unidade, por, por_unidade, *, grupo='', subgrupo='', caes='1', gatos='1', ordem=1):
    return {
        'minDosage': str(minimo), 'maxDosage': str(maximo), 'dosageUnitOfMeasure': unidade,
        'referenceValue': str(por), 'referenceUnitOfMeasure': por_unidade, 'dosageGroup': grupo,
        'dosageSubGroup': subgrupo, 'animalType1Dosage': caes, 'animalType2Dosage': gatos,
        'sortSequence': str(ordem),
    }


ITEM_DIPIRONA = {
    'itemId': '1682', 'itemName': 'Dipirona', 'isFood': '0', 'unavailable': '0',
    'dosageForms': [
        _forma('DC_1682_4', '500 mg/mL, gotas', '500 mg/mL', 'gotas', 1),
        _forma('DC_1682_3', '50 mg/mL, solução oral', '50 mg/mL', 'solução oral', 2),
        _forma('DC_1682_1', '500 mg, comprimido', '500 mg', 'comprimido', 3),
        _forma('DC_1682_2', '1 g, comprimido', '1 g', 'comprimido', 4),
        _forma('DC_1682_5', '500 mg/mL, solução injetável', '500 mg/mL', 'solução injetável', 5),
    ],
    'dosages': [_dose(25, 25, 'mg', 1, 'kg')],
    'suggestions': {'quantity': '1', 'humanOrVet': 'Humana', 'dosageForms': {
        'DC_1682_4': {'type': 'Gota'}, 'DC_1682_3': {'type': ''}, 'DC_1682_1': {'type': 'Comprimido'},
        'DC_1682_2': {'type': 'Comprimido'}, 'DC_1682_5': {'type': ''},
    }},
}

ITEM_VERMIVET_FILHOTE = {
    'itemId': '288', 'itemName': 'Vermivet Filhote', 'isFood': '0', 'unavailable': '0',
    'dosageForms': [_forma('DC_288_1', 'Frasco (20 mL)', '', 'frasco', 1, quantidade='20 mL',
                           info='com seringa dosadora', nome='Vermivet Filhote,')],
    'dosages': [_dose(1, 1, 'mL', 1, 'kg')],
    'suggestions': {'quantity': '1', 'usage': 'Oral', 'dosageForms': {'DC_288_1': {'type': ''}}},
}

ITEM_VERMIVET_PLUS = {
    'itemId': '2588', 'itemName': 'Vermivet Plus', 'isFood': '0', 'unavailable': '0',
    'dosageForms': [
        _forma('DC_2588_1', '660 mg, comprimido (4 un)', '660 mg', 'comprimido', 1, quantidade='4 un', nome='Vermivet Plus'),
        _forma('DC_2588_2', '2,0 g, comprimido (2 un)', '2,0 g', 'comprimido', 2, quantidade='2 un', nome='Vermivet Plus'),
        _forma('DC_2588_3', '330 mg, comprimido (2 un)', '330 mg', 'comprimido', 3, quantidade='2 un', nome='Vermivet Plus'),
    ],
    'dosages': [
        _dose(1, 1, 'comprimido', 10, 'kg', grupo='Vermivet Plus 660 mg', gatos='0', ordem=1),
        _dose(1, 1, 'comprimido', 30, 'kg', grupo='Vermivet Plus 2 g', gatos='0', ordem=2),
        _dose(1, 1, 'comprimido', 5, 'kg', grupo='Vermivet Plus 330 mg', gatos='0', ordem=3),
    ],
    'suggestions': {'quantity': '1', 'usage': 'Oral', 'dosageForms': {
        'DC_2588_1': {'type': 'Comprimido'}, 'DC_2588_2': {'type': 'Comprimido'}, 'DC_2588_3': {'type': 'Comprimido'},
    }},
}

HOJE = date(2026, 11, 11)


# ───────────────────────── medicamentos em miniatura ───────────────────────


def _ap(id, forma, concentracao, *, pid=None, variante=None, valor=None, unidade=None,
        volume=None, volume_unidade=None, fabricante=None):
    return SimpleNamespace(
        id=id, forma=forma, concentracao=concentracao, nome_variante=variante,
        concentracao_valor=valor, concentracao_unidade=unidade, volume_valor=volume,
        volume_unidade=volume_unidade, nome_comercial=None, fabricante=fabricante,
        vetsmart_produto_id=pid,
    )


def _dipirona(*, com_catalogo=True):
    """Princípio ativo com a entrada genérica do VetSmart e uma marca."""
    conteudo = {'produtos_vetsmart': [
        {'vetsmart_produto_id': 1682, 'nome': 'Dipirona', 'tipo': 'principio_ativo',
         'apresentacoes': [], 'doses': []},
        {'vetsmart_produto_id': 900, 'nome': 'D-500', 'tipo': 'produto', 'apresentacoes': [], 'doses': []},
    ]}
    if com_catalogo:
        conteudo = catalogo.gravar_no_conteudo(conteudo, 1682, catalogo.compactar_item(ITEM_DIPIRONA, HOJE))
    return SimpleNamespace(
        id=1641, nome='Dipirona', principio_ativo='Dipirona', classificacao='Analgésico',
        via_administracao='Oral', dosagem_recomendada=None, frequencia=None, duracao_tratamento=None,
        observacoes=None, bula=None, vetsmart_produto_id=1682, conteudo_estruturado=conteudo,
        apresentacoes=[
            _ap(71, 'comprimido', 'D-500 500 mg (10 un)', pid=900, variante='D-500', valor=500, unidade='mg',
                volume=10, volume_unidade='un', fabricante='Marca'),
            _ap(72, 'comprimido', 'D-500 250 mg (10 un)', pid=900, variante='D-500', valor=250, unidade='mg',
                volume=10, volume_unidade='un', fabricante='Marca'),
            # Mesma força do genérico "1 g, comprimido", gravada em mg.
            _ap(73, 'comprimido', 'D-500 1000 mg (4 un)', pid=900, variante='D-500', valor=1000, unidade='mg',
                volume=4, volume_unidade='un', fabricante='Marca'),
        ],
        doses=[],
    )


def _vermivet(*itens):
    conteudo = {'produtos_vetsmart': [
        {'vetsmart_produto_id': 288, 'nome': 'Vermivet Filhote', 'tipo': 'produto', 'apresentacoes': [], 'doses': []},
        {'vetsmart_produto_id': 2588, 'nome': 'Vermivet Plus', 'tipo': 'produto', 'apresentacoes': [], 'doses': []},
    ]}
    for item in itens:
        conteudo = catalogo.gravar_no_conteudo(conteudo, int(item['itemId']), catalogo.compactar_item(item, HOJE))
    return SimpleNamespace(
        id=6186, nome='Pamoato de Pirantel + Praziquantel + Febantel',
        principio_ativo='Pamoato de Pirantel + Praziquantel + Febantel', classificacao='Endoparasiticida',
        via_administracao='Oral', dosagem_recomendada=None, frequencia=None, duracao_tratamento=None,
        observacoes=None, bula=None, vetsmart_produto_id=288, conteudo_estruturado=conteudo,
        apresentacoes=[
            _ap(6089, 'frasco', 'Vermivet Filhote (20 mL), com seringa dosadora', pid=288,
                variante='Vermivet Filhote (20 mL), com seringa dosadora', volume=20, volume_unidade='ml'),
            _ap(6091, 'comprimido', 'Vermivet Plus 660 mg (4 un)', pid=2588, variante='Vermivet Plus',
                valor=660, unidade='mg', volume=4, volume_unidade='un'),
            # Cadastrada na clínica para o produto; o catálogo não a conhece.
            _ap(7000, 'comprimido', 'Vermivet Plus 165 mg (1 un)', pid=2588, variante='Vermivet Plus',
                valor=165, unidade='mg', volume=1, volume_unidade='un'),
        ],
        doses=[],
    )


def _rotulos(lista, origem):
    return [ap['rotulo_opcao'] for ap in lista if ap.get('origem') == origem]


# ───────────────────────── formato guardado ────────────────────────────────


def test_item_e_guardado_so_com_o_que_o_prescritor_usa():
    item = catalogo.compactar_item(ITEM_VERMIVET_PLUS, HOJE)

    assert item['nome'] == 'Vermivet Plus'
    assert item['via'] == 'Oral'
    assert item['atualizado_em'] == '2026-11-11'
    assert item['apresentacoes'][0] == {
        'id': 'DC_2588_1', 'rotulo': '660 mg, comprimido (4 un)',
        'completo': 'Vermivet Plus 660 mg, comprimido (4 un)', 'concentracao': '660 mg',
        'quantidade': '4 un', 'forma': 'comprimido', 'info': '', 'medida': 'Comprimido', 'ordem': 1,
    }
    assert item['dosagens'][1] == {
        'grupo': 'Vermivet Plus 2 g', 'subgrupo': '', 'min': 1.0, 'max': 1.0, 'unidade': 'comprimido',
        'por': 30.0, 'por_unidade': 'kg', 'caes': True, 'gatos': False, 'ordem': 2,
    }


def test_gravar_o_item_nao_altera_o_conteudo_original():
    original = {'produtos_vetsmart': [], 'indicacoes': {'itens': ['dor']}}

    novo = catalogo.gravar_no_conteudo(original, 1682, {'nome': 'Dipirona'})

    assert 'catalogo_prescritor' not in original
    assert novo['catalogo_prescritor'] == {'1682': {'nome': 'Dipirona'}}
    assert novo['indicacoes'] == {'itens': ['dor']}
    assert catalogo.ja_importado(novo, 1682) and not catalogo.ja_importado(original, 1682)


@pytest.mark.parametrize('texto, esperado', [
    ('500 mg', (500.0, 'mg')),
    ('1 g', (1.0, 'g')),
    ('2,0 g', (2.0, 'g')),
    ('50 mg/mL', (50.0, 'mg/ml')),
    ('250 mg / 5mL', (50.0, 'mg/ml')),
    ('125 mg / 5 mL', (25.0, 'mg/ml')),
    ('0,2%', (0.2, '%')),
    ('1000 UI', (1000.0, 'ui')),
    ('5 mL', (None, None)),
    ('20mg/g + 0,64mg/g', (None, None)),
    ('', (None, None)),
])
def test_concentracao_do_catalogo_vira_numero_para_o_calculo(texto, esperado):
    assert escopo.parse_concentracao(texto) == esperado


@pytest.mark.parametrize('texto, esperado', [
    ('4 un', (4.0, 'un')), ('20 mL', (20.0, 'ml')), ('1,5 kg', (1.5, 'kg')), ('70g', (70.0, 'g')), ('', (None, None)),
])
def test_quantidade_da_embalagem(texto, esperado):
    assert escopo.parse_quantidade(texto) == esperado


# ───────────────────────── princípio ativo genérico ────────────────────────


def test_principio_ativo_ganha_a_lista_generica_do_vetsmart_na_ordem_dele():
    lista = bulario.listar_apresentacoes_medicamento(_dipirona())

    assert _rotulos(lista, 'generico') == [
        '500 mg/mL, gotas',
        '50 mg/mL, solução oral',
        '500 mg, comprimido',
        '1 g, comprimido',
        '500 mg/mL, solução injetável',
    ]


def test_generica_ja_vem_pronta_para_converter_a_dose():
    por_rotulo = {ap['rotulo_opcao']: ap for ap in bulario.listar_apresentacoes_medicamento(_dipirona())
                  if ap.get('origem') == 'generico'}

    gotas = por_rotulo['500 mg/mL, gotas']
    assert (gotas['concentracao_valor'], gotas['concentracao_unidade']) == (500.0, 'mg/mL')
    assert gotas['unidade_pratica'] == 'gota'
    assert gotas['permite_calculo_automatico'] is True
    comprimido = por_rotulo['1 g, comprimido']
    assert (comprimido['concentracao_valor'], comprimido['concentracao_unidade']) == (1.0, 'g')
    assert comprimido['categoria'] == 'solido_oral'
    assert por_rotulo['500 mg/mL, solução injetável']['categoria'] == 'injetavel'


def test_marca_de_mesma_forca_nao_repete_o_generico_e_a_de_outra_forca_continua():
    lista = bulario.listar_apresentacoes_medicamento(_dipirona())

    das_marcas = [ap['id'] for ap in lista if ap.get('origem') != 'generico']
    assert das_marcas == [72], (
        'os comprimidos de 500 mg e de 1000 mg (= 1 g) da marca são o genérico; o de 250 mg não existe nele'
    )


def test_plano_clinico_que_pede_as_variantes_de_marca_fica_com_todas():
    lista = bulario.listar_apresentacoes_medicamento(_dipirona(), preservar_variantes_comerciais=True)

    assert {ap['id'] for ap in lista if ap.get('origem') != 'generico'} == {71, 72, 73}


def test_sem_catalogo_importado_a_lista_do_principio_ativo_e_a_de_antes():
    lista = bulario.listar_apresentacoes_medicamento(_dipirona(com_catalogo=False))

    assert [ap['id'] for ap in lista] == [72, 71, 73]
    assert all('rotulo_opcao' not in ap for ap in lista)


def test_receita_do_generico_leva_o_nome_do_principio_ativo_e_o_rotulo():
    (primeira, *_resto) = bulario.listar_apresentacoes_medicamento(_dipirona())

    assert primeira['produto_nome'] == 'Dipirona'
    assert primeira['nome_variante'] == 'Dipirona 500 mg/mL, gotas'
    assert primeira['id'] >= escopo.ID_SINTETICO_BASE


# ───────────────────────── produto de marca ────────────────────────────────


def test_produto_sem_apresentacao_no_bulario_passa_a_ter_as_do_catalogo():
    med = _vermivet(ITEM_VERMIVET_PLUS)
    med.apresentacoes = []

    dados = bulario.serializar_medicamento_busca(med, nome_comercial_filtro='Vermivet Plus')

    assert dados['apresentacoes_origem'] == {'tipo': 'produto', 'produto': 'Vermivet Plus'}
    assert _rotulos(dados['apresentacoes'], 'produto') == [
        '330 mg, comprimido (2 un)', '660 mg, comprimido (4 un)', '2,0 g, comprimido (2 un)',
    ]


def test_linha_real_e_reaproveitada_com_o_rotulo_do_catalogo():
    lista = bulario.listar_apresentacoes_medicamento(
        _vermivet(ITEM_VERMIVET_FILHOTE), nome_comercial_filtro='Vermivet Filhote',
    )

    (frasco,) = lista
    assert frasco['id'] == 6089, 'mantém o id da linha cadastrada'
    assert frasco['rotulo_opcao'] == 'Frasco (20 mL), com seringa dosadora'
    assert frasco['unidade_pratica'] == 'mL'


def test_linha_do_produto_que_o_catalogo_nao_lista_continua_aparecendo():
    lista = bulario.listar_apresentacoes_medicamento(
        _vermivet(ITEM_VERMIVET_PLUS), nome_comercial_filtro='Vermivet Plus',
    )

    por_id = {ap['id']: ap['rotulo_opcao'] for ap in lista}
    assert por_id[6091] == '660 mg, comprimido (4 un)'
    assert por_id[7000] == '165 mg, comprimido (1 un)'
    assert len(lista) == 4


def test_dosagens_do_catalogo_viram_a_posologia_de_bula_do_produto():
    dados = bulario.serializar_medicamento_busca(
        _vermivet(ITEM_VERMIVET_PLUS), nome_comercial_filtro='Vermivet Plus',
    )

    assert dados['via_administracao'] == 'Oral'
    assert dados['posologia_produto']['dosagens'] == [
        {'grupo': 'Vermivet Plus 660 mg', 'especie': 'Cães', 'rotulo': None, 'dose': '1 comprimido / 10 kg'},
        {'grupo': 'Vermivet Plus 2 g', 'especie': 'Cães', 'rotulo': None, 'dose': '1 comprimido / 30 kg'},
        {'grupo': 'Vermivet Plus 330 mg', 'especie': 'Cães', 'rotulo': None, 'dose': '1 comprimido / 5 kg'},
    ]


def test_auditor_confere_a_lista_do_catalogo():
    assert auditor.violacoes_do_medicamento(_vermivet(ITEM_VERMIVET_FILHOTE, ITEM_VERMIVET_PLUS)) == []
    assert auditor.resumo_do_medicamento(_dipirona())['com_catalogo_do_prescritor'] == 1


# ───────────────────────── o que importar ──────────────────────────────────


def _tuplas(*medicamentos):
    return [(m.id, m.nome, m.principio_ativo, m.vetsmart_produto_id, m.conteudo_estruturado) for m in medicamentos]


def test_nome_prescrito_aponta_para_o_item_do_vetsmart():
    por_nome, donos = catalogo.indice_de_nomes(_tuplas(_dipirona(com_catalogo=False), _vermivet()))

    ids = catalogo.ids_dos_nomes([
        'Dipirona – 500 mg/mL, gotas',                       # princípio ativo → item genérico
        'Vermivet Plus — 660 mg, comprimido (4 un)',          # marca
        'Vermivet Filhote, frasco (20 mL), com seringa dosadora',
        'Dipirona - 500 mg, comprimido',                      # repetido: não duplica
        'Vermivetplus 10 mg',                                 # não é o Vermivet Plus
        'Encaminhamento',
    ], por_nome)

    assert ids == [1682, 2588, 288]
    assert donos[1682] == {1641} and donos[2588] == {6186}


def test_medicamento_importado_no_formato_antigo_responde_pelo_proprio_id():
    antigo = SimpleNamespace(id=5, nome='Rifocina', principio_ativo=None, vetsmart_produto_id=3100,
                             conteudo_estruturado=None)

    por_nome, donos = catalogo.indice_de_nomes(_tuplas(antigo))

    assert catalogo.ids_dos_nomes(['Rifocina – 10 mg/mL, spray (20 mL)'], por_nome) == [3100]
    assert donos == {3100: {5}}


# ───────────────────────── ritmo ───────────────────────────────────────────


def _importar(respostas, ids):
    """Roda o importador com um VetSmart de mentira e sem esperar de verdade."""
    fila = list(respostas)
    esperas, avisos, gravados = [], [], []

    def buscar(pid):
        resposta = fila.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    resumo = catalogo.importar(
        ids, lambda pid, item: gravados.append((pid, item['nome'])) or 1,
        intervalo=25, buscar=buscar, dormir=esperas.append, avisar=avisos.append,
    )
    return resumo, gravados, esperas, avisos


def test_importador_le_um_item_por_vez_com_pausa_entre_eles():
    resumo, gravados, esperas, _avisos = _importar([ITEM_DIPIRONA, ITEM_VERMIVET_PLUS], [1682, 2588])

    assert gravados == [(1682, 'Dipirona'), (2588, 'Vermivet Plus')]
    assert esperas == [25], 'pausa entre os itens, nenhuma depois do último'
    assert resumo == {'lidos': 2, 'gravados': 2, 'indisponiveis': 0, 'pendentes': 0}


def test_pedido_de_espera_do_vetsmart_e_obedecido_antes_de_tentar_de_novo():
    resumo, gravados, esperas, avisos = _importar([catalogo.LimiteDeRitmo(61), ITEM_DIPIRONA], [1682])

    assert gravados == [(1682, 'Dipirona')]
    assert esperas == [66]
    assert any('aguardando 61s' in aviso for aviso in avisos)
    assert resumo['pendentes'] == 0


def test_limite_que_insiste_faz_o_importador_parar_em_vez_de_forcar():
    resumo, gravados, _esperas, avisos = _importar(
        [ITEM_DIPIRONA, catalogo.LimiteDeRitmo(60), catalogo.LimiteDeRitmo(60)], [1682, 2588, 288],
    )

    assert gravados == [(1682, 'Dipirona')]
    assert resumo['pendentes'] == 2
    assert any('parando com 2 item(ns) por ler' in aviso for aviso in avisos)


def test_espera_longa_demais_tambem_encerra_a_execucao():
    resumo, gravados, esperas, _avisos = _importar([catalogo.LimiteDeRitmo(3600)], [1682, 2588])

    assert gravados == [] and esperas == []
    assert resumo['pendentes'] == 2


def test_item_que_nao_existe_mais_e_pulado_sem_derrubar_os_outros():
    resumo, gravados, _esperas, _avisos = _importar(
        [catalogo.ItemIndisponivel('HTTP 404'), ITEM_VERMIVET_PLUS], [999, 2588],
    )

    assert gravados == [(2588, 'Vermivet Plus')]
    assert resumo['indisponiveis'] == 1


def test_resposta_429_vira_pedido_de_espera_com_o_tempo_do_cabecalho():
    def abrir(requisicao, timeout):
        assert requisicao.full_url == 'https://api.vetsmart.com.br/v2/item/1682/dc?with=dosageForms,dosages'
        raise urllib.error.HTTPError(requisicao.full_url, 429, 'Too Many Requests', {'Retry-After': '224'}, None)

    with pytest.raises(catalogo.LimiteDeRitmo) as limite:
        catalogo.buscar_item(1682, abrir=abrir)

    assert limite.value.espera == 224


def test_recusa_do_vetsmart_nao_e_contornada():
    def abrir(requisicao, timeout):
        raise urllib.error.HTTPError(requisicao.full_url, 403, 'Forbidden', {}, None)

    with pytest.raises(catalogo.ItemIndisponivel):
        catalogo.buscar_item(1682, abrir=abrir)


# ───────────────────────── pela aplicação ──────────────────────────────────


def test_importador_grava_no_medicamento_e_o_prescritor_passa_a_ver(app, client):
    from app import _clear_medication_search_cache
    from scripts import importar_catalogo_prescritor_vetsmart as script

    _clear_medication_search_cache()
    modelo = _dipirona(com_catalogo=False)
    user = User(name='Vet', email='vet-importa@example.com', worker='veterinario')
    user.set_password('x')
    db.session.add(user)
    db.session.flush()
    med = Medicamento(
        nome='Dipirona', principio_ativo='Dipirona', via_administracao='Oral', vetsmart_produto_id=1682,
        conteudo_estruturado=modelo.conteudo_estruturado, created_by=user.id,
    )
    db.session.add(med)
    db.session.commit()
    med_id = med.id

    por_nome, donos = script.carregar_indices(db, Medicamento)
    assert catalogo.ids_dos_nomes(['Dipirona – 500 mg/mL, gotas'], por_nome) == [1682]
    resumo = catalogo.importar(
        [1682], script.criar_gravador(db, Medicamento, donos),
        buscar=lambda pid: ITEM_DIPIRONA, dormir=lambda s: None, avisar=lambda t: None,
    )

    assert resumo['gravados'] == 1
    db.session.expire_all()
    salvo = db.session.get(Medicamento, med_id)
    assert catalogo.ja_importado(salvo.conteudo_estruturado, 1682)
    assert salvo.conteudo_estruturado['produtos_vetsmart'] == modelo.conteudo_estruturado['produtos_vetsmart']
    dados = client.get(f'/medicamento/{med_id}/detalhe').get_json()
    assert dados['apresentacoes'][0]['rotulo_opcao'] == '500 mg/mL, gotas'


def test_detalhe_do_principio_ativo_traz_a_lista_generica(app, client):
    from app import _clear_medication_search_cache

    _clear_medication_search_cache()
    modelo = _dipirona()
    user = User(name='Vet', email='vet-catalogo@example.com', worker='veterinario')
    user.set_password('x')
    db.session.add(user)
    db.session.flush()
    med = Medicamento(
        nome='Dipirona', principio_ativo='Dipirona', via_administracao='Oral', vetsmart_produto_id=1682,
        conteudo_estruturado=modelo.conteudo_estruturado, created_by=user.id,
    )
    db.session.add(med)
    db.session.commit()

    dados = client.get(f'/medicamento/{med.id}/detalhe').get_json()

    assert [ap['rotulo_opcao'] for ap in dados['apresentacoes']][:3] == [
        '500 mg/mL, gotas', '50 mg/mL, solução oral', '500 mg, comprimido',
    ]
    assert dados['apresentacoes_origem']['tipo'] == 'principio_ativo'
