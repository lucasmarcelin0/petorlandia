"""O prescritor mostra, para cada produto, as apresentações e as doses dele.

O bulário agrupa os produtos do VetSmart pelo princípio ativo: "Vermivet
Filhote" (suspensão, 1 mL/kg) e "Vermivet Plus" (comprimidos) moram no mesmo
``Medicamento``. Antes do recorte por produto, escolher "Vermivet Filhote"
listava os comprimidos do Plus e escondia o "Frasco (20 mL), com seringa
dosadora" — a única apresentação que o produto tem.

Os casos abaixo reproduzem os formatos reais do catálogo. O guard de classe
está no fim: o auditor de ``scripts/auditar_prescricao_por_produto.py`` tem de
sair limpo com o recorte ligado e acusar violações com ele desligado.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from extensions import db
from models import ApresentacaoMedicamento, DoseMedicamento, Medicamento, User
from scripts import auditar_prescricao_por_produto as auditor
from services import bulario
from services import posologia_normalizacao as posologia

escopo = bulario._esc
RAIZ = Path(__file__).resolve().parents[1]


# ───────────────────────── catálogo em miniatura ───────────────────────────


def _ap(id, forma, concentracao, *, pid=None, variante=None, valor=None, unidade=None,
        volume=None, volume_unidade=None, comercial=None, fabricante=None):
    return SimpleNamespace(
        id=id, forma=forma, concentracao=concentracao, nome_variante=variante,
        concentracao_valor=valor, concentracao_unidade=unidade, volume_valor=volume,
        volume_unidade=volume_unidade, nome_comercial=comercial, fabricante=fabricante,
        vetsmart_produto_id=pid,
    )


def _dose(id, dose, minimo, maximo, unidade, *, especie_code='CAES', bruto=None, frequencia=None,
          duracao=None, duracao_dias=None, faixa=None, peso_max=None, fonte='SCRAPER', via='Oral'):
    return SimpleNamespace(
        id=id, especie='Cães' if especie_code == 'CAES' else 'Cães e Gatos', especie_code=especie_code,
        faixa_peso=faixa, peso_min_kg=None, peso_max_kg=peso_max, via=via, dose=dose,
        dose_min=minimo, dose_max=maximo, dose_unidade=unidade, frequencia=frequencia,
        intervalo_horas=None, intervalo_min_horas=None, intervalo_max_horas=None,
        duracao=duracao, duracao_min_dias=duracao_dias, duracao_max_dias=duracao_dias,
        dose_raw_text=bruto or dose, fonte=fonte, confianca='MEDIA', indicacao=None, observacao=None,
    )


def _admin(*, via='Oral', frequencia='', duracao='', dosagens=''):
    return {
        'Administração e doses': {
            'texto': (
                f'Via(s)\n{via}\nVideos da(s) via(s)\n'
                f'Frequência de utilização\n{frequencia}\n'
                f'Duração do tratamento\n{duracao}\n'
                f'Dosagem indicada\n{dosagens}\nModo de usar\nAdministrar conforme a bula.'
            ),
        },
    }


FREQUENCIA_FILHOTE = (
    'Deve ser administrado por via oral aos 15 dias, 1º, 2º, 3º, 4º, 5º e 6º mês de idade. '
    'Conforme o tipo e o grau de infestação a posologia pode ser alterada a critério do Médico Veterinário.'
)
DOSAGENS_PLUS = (
    'Vermivet Plus 660 mg\nDosagem para\nCães\nRecomendado\n1 comprimido / 10 kg\nINDICAÇÃO:\n0 comprimido\n'
    'Vermivet Plus 2 g\nDosagem para\nCães\nRecomendado\n1 comprimido / 30 kg\nINDICAÇÃO:\n0 comprimido\n'
    'Vermivet Plus 330 mg\nDosagem para\nCães\nRecomendado\n1 comprimido / 5 kg\nINDICAÇÃO:\n0 comprimido'
)


def _vermivet():
    """O caso que motivou a correção, com os dados como estão em produção."""
    filhote = {
        'vetsmart_produto_id': 288, 'nome': 'Vermivet Filhote', 'tipo': 'produto', 'fabricante': 'Biovet',
        'via_administracao': 'Oral', 'frequencia': FREQUENCIA_FILHOTE[:100],
        'duracao_tratamento': 'Até o 6º mês de idade',
        'apresentacoes': [{
            'forma': 'frasco', 'concentracao': '(20 mL), com seringa dosadora',
            'nome_variante': '(20 mL), com seringa dosadora', 'concentracao_valor': None,
            'concentracao_unidade': None, 'volume_valor': 20.0, 'volume_unidade': 'ml',
        }],
        'doses': [{
            'especie': 'Cães e Gatos', 'especie_code': 'AMBOS', 'via': 'Oral', 'dose': '1 mL/kg',
            'dose_min': 1.0, 'dose_max': 1.0, 'dose_unidade': 'ML_KG', 'dose_raw_text': '1 mL /  kg',
            'frequencia': FREQUENCIA_FILHOTE[:100], 'duracao': 'Até o 6º mês de idade',
            'duracao_min_dias': 15, 'duracao_max_dias': 15, 'fonte': 'SCRAPER', 'confianca': 'MEDIA',
        }],
        'secoes': _admin(
            frequencia=FREQUENCIA_FILHOTE, duracao='Até o 6º mês de idade',
            dosagens='Doses\nDosagem para\nCães e Gatos\nRecomendado\n1 mL / kg\nINDICAÇÃO:\n0 mL',
        ),
    }
    plus = {
        'vetsmart_produto_id': 2588, 'nome': 'Vermivet Plus', 'tipo': 'produto', 'fabricante': 'Biovet',
        'via_administracao': 'Oral',
        'frequencia': 'Dose única, sendo a dose repetida após 15 dias, de acordo com o peso do animal.',
        'duracao_tratamento': 'O tratamento deve ser repetido a cada 3 meses',
        'apresentacoes': [
            {'forma': 'comprimido', 'concentracao': '660 mg (4 un)', 'concentracao_valor': 660.0,
             'concentracao_unidade': 'mg', 'volume_valor': 4.0, 'volume_unidade': 'un'},
            {'forma': 'comprimido', 'concentracao': '2,0 g (2 un)', 'concentracao_valor': 2.0,
             'concentracao_unidade': 'g', 'volume_valor': 2.0, 'volume_unidade': 'un'},
            {'forma': 'comprimido', 'concentracao': '330 mg (2 un)', 'concentracao_valor': 330.0,
             'concentracao_unidade': 'mg', 'volume_valor': 2.0, 'volume_unidade': 'un'},
        ],
        'doses': [],  # o importador descarta dose por comprimido quando há várias forças
        'secoes': _admin(
            frequencia='Dose única, sendo a dose repetida após 15 dias, de acordo com o peso do animal.',
            duracao='O tratamento deve ser repetido a cada 3 meses', dosagens=DOSAGENS_PLUS,
        ),
    }
    repeticao = dict(
        frequencia='Dose única, sendo a dose repetida após 15 dias, de acordo com o peso do animal.',
        duracao='O tratamento deve ser repetido a cada 3 meses', duracao_dias=90,
    )
    return SimpleNamespace(
        id=6186, nome='Pamoato de Pirantel + Praziquantel + Febantel',
        principio_ativo='Pamoato de Pirantel + Praziquantel + Febantel',
        classificacao='Endoparasiticida', via_administracao='Oral',
        dosagem_recomendada=None, frequencia=None, duracao_tratamento=None,
        observacoes=None, bula=None, vetsmart_produto_id=288,
        conteudo_estruturado={'produtos_vetsmart': [filhote, plus]},
        apresentacoes=[
            _ap(6089, 'frasco', 'Vermivet Filhote (20 mL), com seringa dosadora', pid=288,
                variante='Vermivet Filhote (20 mL), com seringa dosadora', volume=20, volume_unidade='ml',
                fabricante='Biovet'),
            _ap(6091, 'comprimido', 'Vermivet Plus 660 mg (4 un)', pid=2588, variante='Vermivet Plus',
                valor=660, unidade='mg', volume=4, volume_unidade='un', fabricante='Biovet'),
            _ap(6092, 'comprimido', 'Vermivet Plus 2,0 g (2 un)', pid=2588, variante='Vermivet Plus',
                valor=2, unidade='g', volume=2, volume_unidade='un', fabricante='Biovet'),
            _ap(6093, 'comprimido', 'Vermivet Plus 330 mg (2 un)', pid=2588, variante='Vermivet Plus',
                valor=330, unidade='mg', volume=2, volume_unidade='un', fabricante='Biovet'),
            # Cadastros manuais feitos na tentativa de contornar a lista errada.
            # O segundo teve "(20 mL)" lido como concentração de 20 mL.
            _ap(12871, 'Frasco (20 mL)', '.', fabricante='.'),
            _ap(12872, 'Frasco', '(20 mL)', valor=20, unidade='mL'),
        ],
        doses=[
            _dose(2269, '1 mL/kg', 1.0, 1.0, 'ML_KG', especie_code='AMBOS', bruto='1 mL /  kg',
                  frequencia=FREQUENCIA_FILHOTE[:100], duracao='Até o 6º mês de idade', duracao_dias=15),
            _dose(3954, '1 comprimido(s) / 10 kg', 0.1, 0.1, 'COMPRIMIDOS_KG',
                  bruto='1 comprimido / 10 kg', **repeticao),
            _dose(3955, '1 comprimido(s) / 30 kg', 0.033, 0.033, 'COMPRIMIDOS_KG',
                  bruto='1 comprimido / 30 kg', **repeticao),
            _dose(3956, '1 comprimido(s) / 5 kg', 0.2, 0.2, 'COMPRIMIDOS_KG',
                  bruto='1 comprimido / 5 kg', **repeticao),
        ],
    )


def _corticoide():
    """Marcas do mesmo princípio ativo: uma só no retrato, uma sem dado nenhum."""
    return SimpleNamespace(
        id=38, nome='Dexametasona', principio_ativo='Dexametasona', classificacao='Corticoide',
        via_administracao='Oral', dosagem_recomendada=None, frequencia=None, duracao_tratamento=None,
        observacoes=None, bula=None, vetsmart_produto_id=None,
        conteudo_estruturado={'produtos_vetsmart': [
            {'vetsmart_produto_id': 501, 'nome': 'Azium® Comprimidos', 'tipo': 'produto',
             'apresentacoes': [{'forma': 'comprimido', 'concentracao': '(20 un)', 'concentracao_valor': None,
                                'concentracao_unidade': None, 'volume_valor': 20.0, 'volume_unidade': 'un'}],
             'doses': []},
            {'vetsmart_produto_id': 502, 'nome': 'Cortvet Pet', 'tipo': 'produto', 'apresentacoes': [], 'doses': []},
            {'vetsmart_produto_id': 503, 'nome': 'Dexagard Comprimidos', 'tipo': 'produto',
             'apresentacoes': [], 'doses': []},
            {'vetsmart_produto_id': 504, 'nome': 'Dexametasona', 'tipo': 'principio_ativo',
             'apresentacoes': [], 'doses': []},
        ]},
        apresentacoes=[
            _ap(1783, 'comprimido', 'Cortvet Pet 0,5 mg (10 un)', pid=502, variante='Cortvet Pet',
                valor=0.5, unidade='mg', volume=10, volume_unidade='un'),
            _ap(1784, 'comprimido', 'Cortvet Pet 1,0 mg (10 un)', pid=502, variante='Cortvet Pet',
                valor=1.0, unidade='mg', volume=10, volume_unidade='un'),
            # Cadastrada à mão, sem produto: força conhecida, vale para qualquer marca.
            _ap(9001, 'comprimido', '4 mg', valor=4, unidade='mg'),
        ],
        doses=[],
    )


def _homonimos():
    """Dois cadastros do VetSmart com o mesmo nome e embalagens diferentes."""
    return SimpleNamespace(
        id=6140, nome='Probiótico', principio_ativo='Probiótico', classificacao='Suplemento',
        via_administracao='Oral', dosagem_recomendada=None, frequencia=None, duracao_tratamento=None,
        observacoes=None, bula=None, vetsmart_produto_id=6904,
        conteudo_estruturado={'produtos_vetsmart': [
            {'vetsmart_produto_id': 6904, 'nome': 'UP Flora', 'tipo': 'produto',
             'apresentacoes': [{'forma': 'cápsulas', 'concentracao': '(8)'}], 'doses': []},
            {'vetsmart_produto_id': 7788, 'nome': 'UP Flora', 'tipo': 'produto',
             'apresentacoes': [{'forma': 'cápsula', 'concentracao': '(30 un)'}], 'doses': []},
        ]},
        apresentacoes=[_ap(5999, 'cápsulas', 'Up Flora (8)', pid=6904, variante='UP Flora')],
        doses=[],
    )


def _produto_unico():
    """Importação antiga: o medicamento é o próprio produto, sem retrato."""
    return SimpleNamespace(
        id=1645, nome='Teste Rápido 4D', principio_ativo=None, classificacao='Teste Diagnóstico',
        via_administracao=None, dosagem_recomendada=None, frequencia=None, duracao_tratamento=None,
        observacoes=None, bula=None, vetsmart_produto_id=2616, conteudo_estruturado=None,
        apresentacoes=[
            _ap(442, 'caixa', 'Teste Rápido 4D (5 un)', pid=2616, variante='Teste Rápido 4D',
                volume=5, volume_unidade='un'),
            _ap(443, 'caixa', 'Teste Rápido 4D (30 un)', pid=2616, variante='Teste Rápido 4D',
                volume=30, volume_unidade='un'),
        ],
        doses=[],
    )


CATALOGO = (_vermivet, _corticoide, _homonimos, _produto_unico)


def _animal(peso, especie='Cachorro'):
    return SimpleNamespace(peso=peso, species=SimpleNamespace(name=especie))


def _rotulos(lista, origem='produto'):
    return [ap['rotulo_opcao'] for ap in lista if ap.get('origem') == origem]


# ───────────────────────── apresentações ───────────────────────────────────


def test_produto_lista_a_propria_apresentacao_e_nenhuma_do_vizinho():
    lista = bulario.listar_apresentacoes_medicamento(_vermivet(), nome_comercial_filtro='Vermivet Filhote')

    assert _rotulos(lista) == ['Frasco (20 mL), com seringa dosadora']
    assert [ap['id'] for ap in lista] == [6089]


def test_frasco_sem_concentracao_e_liquido_oral_medido_em_ml():
    (frasco,) = bulario.listar_apresentacoes_medicamento(_vermivet(), nome_comercial_filtro='Vermivet Filhote')

    assert frasco['categoria'] == 'liquido_oral'
    assert frasco['unidade_pratica'] == 'mL'
    assert frasco['produto_nome'] == 'Vermivet Filhote'


def test_produto_de_comprimidos_nao_recebe_o_frasco_do_vizinho():
    lista = bulario.listar_apresentacoes_medicamento(_vermivet(), nome_comercial_filtro='Vermivet Plus')

    assert _rotulos(lista) == [
        '330 mg, comprimido (2 un)',
        '660 mg, comprimido (4 un)',
        '2,0 g, comprimido (2 un)',
    ]


def test_principio_ativo_continua_juntando_as_marcas():
    lista = bulario.listar_apresentacoes_medicamento(_vermivet())

    assert {ap['id'] for ap in lista} == {6091, 6092, 6093, 12872}
    assert all('rotulo_opcao' not in ap for ap in lista)


def test_apresentacao_que_so_existe_no_retrato_aparece_com_id_sintetico():
    lista = bulario.listar_apresentacoes_medicamento(_corticoide(), nome_comercial_filtro='Azium® Comprimidos')

    assert _rotulos(lista) == ['Comprimido (20 un)']
    assert lista[0]['id'] >= escopo.ID_SINTETICO_BASE
    assert lista[0]['id'] < 2 ** 31


def test_apresentacao_cadastrada_sem_produto_fica_em_grupo_separado():
    lista = bulario.listar_apresentacoes_medicamento(_corticoide(), nome_comercial_filtro='Cortvet Pet')

    assert _rotulos(lista) == ['0,5 mg, comprimido (10 un)', '1,0 mg, comprimido (10 un)']
    avulsas = [ap for ap in lista if ap.get('origem') == 'avulsa']
    assert [ap['id'] for ap in avulsas] == [9001]
    assert avulsas[0]['categoria_label'] == 'Outras cadastradas'


@pytest.mark.parametrize('produto', ['Vermivet Filhote', 'Vermivet Plus'])
def test_cadastro_manual_de_embalagem_nao_entra_no_produto(produto):
    """ "Frasco (20 mL)" solto não diz o que há no frasco: não é do Plus, que é
    comprimido, e no Filhote só repete o frasco que o fabricante publica."""
    lista = bulario.listar_apresentacoes_medicamento(_vermivet(), nome_comercial_filtro=produto)

    assert not {12871, 12872} & {ap['id'] for ap in lista}
    assert all(ap['origem'] == 'produto' for ap in lista)


def test_produto_sem_apresentacao_avisa_que_a_lista_e_de_outras_marcas():
    dados = bulario.serializar_medicamento_busca(
        _corticoide(), nome_exibicao='Dexagard Comprimidos', nome_comercial_filtro='Dexagard Comprimidos',
    )

    assert dados['apresentacoes_origem'] == {'tipo': 'outros_produtos', 'produto': 'Dexagard Comprimidos'}
    assert dados['apresentacoes'], 'sem dado do produto, as opções genéricas continuam disponíveis'
    assert dados['posologia_produto'] is None


def test_entrada_generica_do_principio_ativo_nao_e_tratada_como_marca():
    dados = bulario.serializar_medicamento_busca(_corticoide(), nome_comercial_filtro='Dexametasona')

    assert dados['apresentacoes_origem']['tipo'] == 'principio_ativo'


def test_produtos_homonimos_respondem_como_um():
    lista = bulario.listar_apresentacoes_medicamento(_homonimos(), nome_comercial_filtro='UP Flora')

    assert sorted(_rotulos(lista)) == ['Cápsula (30 un)', 'Cápsulas (8)']


def test_medicamento_que_e_um_produto_so_nao_esconde_embalagem_sem_concentracao():
    lista = bulario.listar_apresentacoes_medicamento(_produto_unico())

    assert _rotulos(lista) == ['Caixa (5 un)', 'Caixa (30 un)']


def test_lista_do_principio_ativo_nunca_fica_vazia_havendo_cadastro():
    med = SimpleNamespace(
        id=1, nome='Vitamina', via_administracao='Oral', conteudo_estruturado=None, vetsmart_produto_id=None,
        apresentacoes=[_ap(1, 'frasco', '(20 mL)', volume=20, volume_unidade='ml'), _ap(2, '.', '.')],
        doses=[],
    )

    lista = bulario.listar_apresentacoes_medicamento(med)

    assert [ap['id'] for ap in lista] == [1]


@pytest.mark.parametrize('forma, texto, produto, esperado', [
    ('frasco', 'Vermivet Filhote (20 mL), com seringa dosadora', 'Vermivet Filhote',
     'Frasco (20 mL), com seringa dosadora'),
    ('comprimido', 'Vermivet Plus 660 mg (4 un)', 'Vermivet Plus', '660 mg, comprimido (4 un)'),
    ('comprimido palatável', 'Algiprofen® 22 mg - Cães até 5 kg (14 un)', 'Algiprofen',
     '22 mg - Cães até 5 kg, comprimido palatável (14 un)'),
    ('comprimido palatável', '® 22 mg - Cães até 5 kg (14 un)', 'Algiprofen',
     '22 mg - Cães até 5 kg, comprimido palatável (14 un)'),
    ('pipeta', 'Frontline® Plus cães de 10 Kg a 20Kg, pipeta (1 un)', 'Frontline Plus',
     'Cães de 10 Kg a 20Kg, pipeta (1 un)'),
    ('Cápsulas', '', 'Carprofeno Manipulado', 'Cápsulas'),
    ('N/A', 'Eritromax Liofilizado 1000 UI, com ampola diluente de 1mL', 'Alfaepoetina',
     'Eritromax Liofilizado 1000 UI, com ampola diluente de 1mL'),
])
def test_rotulo_segue_o_do_fabricante_sem_repetir_o_produto(forma, texto, produto, esperado):
    ap = _ap(1, forma, texto)

    assert escopo.rotulo_vetsmart(ap, produto) == esperado


def test_nome_de_produto_so_e_prefixo_em_fronteira_de_palavra():
    assert escopo.remover_prefixo_nome('Vermivet Plus 660 mg', 'Vermivet') == 'Plus 660 mg'
    assert escopo.remover_prefixo_nome('Vermivetplus 660 mg', 'Vermivet') == 'Vermivetplus 660 mg'


# ───────────────────────── doses ───────────────────────────────────────────


def test_dose_em_ml_do_produto_liquido_e_a_quantidade_a_administrar():
    sugestao = bulario.sugerir_dose(_vermivet(), _animal(3.2), nome_comercial_filtro='Vermivet Filhote')

    assert sugestao['dose_exibir'] == '3,2 mL'
    assert sugestao['produto'] == 'Vermivet Filhote'
    (frasco,) = sugestao['apresentacoes']
    assert frasco['conversao_direta'] is True
    assert frasco['permite_calculo_automatico'] is True


def test_frequencia_cortada_no_cadastro_volta_inteira():
    sugestao = bulario.sugerir_dose(_vermivet(), _animal(3.2), nome_comercial_filtro='Vermivet Filhote')

    assert sugestao['frequencia_texto'] == FREQUENCIA_FILHOTE


def test_duracao_que_o_texto_nao_diz_nao_vira_dias():
    """ "Até o 6º mês de idade" estava gravado como 15 dias."""
    sugestao = bulario.sugerir_dose(_vermivet(), _animal(3.2), nome_comercial_filtro='Vermivet Filhote')

    assert sugestao['duracao_min_dias'] is None
    assert sugestao['duracao_max_dias'] is None
    assert sugestao['duracao_texto'] == 'Até o 6º mês de idade'


@pytest.mark.parametrize('apresentacao_id, variante, dose', [
    (6091, 'Vermivet Plus 660 mg', '1,2 comprimido(s)'),
    (6092, 'Vermivet Plus 2 g', '0,4 comprimido(s)'),
    (6093, 'Vermivet Plus 330 mg', '2,4 comprimido(s)'),
])
def test_dose_segue_a_apresentacao_escolhida(apresentacao_id, variante, dose):
    sugestao = bulario.sugerir_dose(
        _vermivet(), _animal(12), nome_comercial_filtro='Vermivet Plus', apresentacao_id=apresentacao_id,
    )

    assert sugestao['dose_exibir'] == dose
    assert sugestao['variante'] == variante
    assert sugestao['apresentacao_ids'] == [apresentacao_id]
    assert sugestao['apresentacao_preferida_id'] == apresentacao_id
    assert sugestao['depende_da_apresentacao'] is True
    por_id = {ap['id']: ap for ap in sugestao['apresentacoes']}
    assert por_id[apresentacao_id]['conversao_direta'] is True
    assert all(ap['dose_nao_se_aplica'] for id_, ap in por_id.items() if id_ != apresentacao_id)


def test_sem_apresentacao_escolhida_a_dose_ja_aponta_a_sua():
    sugestao = bulario.sugerir_dose(_vermivet(), _animal(12), nome_comercial_filtro='Vermivet Plus')

    assert sugestao['apresentacao_preferida_id'] in sugestao['apresentacao_ids']
    assert {opcao['variante'] for opcao in sugestao['opcoes_recomendadas']} == {
        'Vermivet Plus 330 mg', 'Vermivet Plus 660 mg', 'Vermivet Plus 2 g',
    }


def test_um_comprimido_a_cada_trinta_quilos_da_um_comprimido_aos_trinta():
    """A coluna guarda 0,033; a razão exata está no texto da bula."""
    sugestao = bulario.sugerir_dose(
        _vermivet(), _animal(30), nome_comercial_filtro='Vermivet Plus', apresentacao_id=6092,
    )

    assert sugestao['dose_min'] == pytest.approx(1.0)
    assert sugestao['dose_exibir'] == '1 comprimido(s)'
    # A faixa mostra a razão da bula, não "0,03 cp/kg".
    assert sugestao['faixa_texto'] == '1 comprimido / 30 kg'


def test_dose_do_vizinho_nao_entra_no_produto():
    sugestao = bulario.sugerir_dose(_vermivet(), _animal(12), nome_comercial_filtro='Vermivet Filhote')

    assert sugestao['dose_unit_out'] == 'mL'
    assert [opcao['dose_unit_out'] for opcao in sugestao['opcoes_recomendadas']] == ['mL']


def test_cabecalho_disputado_por_duas_doses_nao_vincula_nada():
    med = _vermivet()
    plus = med.conteudo_estruturado['produtos_vetsmart'][1]
    plus['secoes'] = _admin(dosagens=(
        'Vermivet Plus 660 mg\nDosagem para\nCães\nRecomendado\n1 comprimido / 10 kg\n'
        'Comprimido de 660 mg para filhotes\nDosagem para\nCães\nRecomendado\n1 comprimido / 5 kg'
    ))

    doses = escopo.escopo_de(med, 'Vermivet Plus').doses

    assert all(dose.apresentacao_ids is None for dose in doses)
    assert bulario.sugerir_dose(med, _animal(12), nome_comercial_filtro='Vermivet Plus') is None


def test_copia_da_dose_nao_altera_a_linha_original():
    med = _vermivet()

    bulario.sugerir_dose(med, _animal(30), nome_comercial_filtro='Vermivet Plus', apresentacao_id=6092)

    linha = next(dose for dose in med.doses if dose.id == 3955)
    assert linha.dose_min == 0.033
    assert not hasattr(linha, 'apresentacao_ids')


# ───────────────────────── leitura do texto do VetSmart ────────────────────


@pytest.mark.parametrize('bloco, esperado', [
    ('Doses\nDosagem para\nCães e Gatos\nRecomendado\n5 - 10 mg / kg\nINDICAÇÃO:\n0 mg',
     [(None, 'Cães e Gatos', None, '5 - 10 mg / kg')]),
    ('Canino\nDosagem para\nCães\nRecomendado\n1 comprimido / 10 kg\nINDICAÇÃO:\n0 comprimido\n'
     'Felino\nDosagem para\nGatos\nRecomendado\n1 comprimido / 2,5 kg',
     [('Canino', 'Cães', None, '1 comprimido / 10 kg'), ('Felino', 'Gatos', None, '1 comprimido / 2,5 kg')]),
    ('Algiprofen 22 mg\nDosagem para\nCães e Gatos\nAté 5 kg\n1 comprimido / animal',
     [('Algiprofen 22 mg', 'Cães e Gatos', 'Até 5 kg', '1 comprimido / animal')]),
    ('Doses - Cães\nAté 4 kg\n0,4 mL / animal\nEntre 4 e 10 kg\n1 mL / animal',
     [(None, 'Cães', 'Até 4 kg', '0,4 mL / animal'), (None, 'Cães', 'Entre 4 e 10 kg', '1 mL / animal')]),
    ('Flamavet 0,2 mg - Gatos\nPrimeiro dia de tratamento\n1 comprimido / 2 kg\nINDICAÇÃO:\n0 comprimido\n'
     '2º dia e tratamentos subsequentes\n0,5 comprimido / 2 kg',
     [('Flamavet 0,2 mg', 'Gatos', 'Primeiro dia de tratamento', '1 comprimido / 2 kg'),
      ('Flamavet 0,2 mg', 'Gatos', '2º dia e tratamentos subsequentes', '0,5 comprimido / 2 kg')]),
])
def test_dosagem_indicada_e_lida_em_grupo_especie_rotulo_e_dose(bloco, esperado):
    lidas = escopo.linhas_de_dosagem(bloco.split('\n'))

    assert [(e['grupo'], e['especie'], e['rotulo'], e['dose']) for e in lidas] == esperado


@pytest.mark.parametrize('texto, forcas', [
    ('Vermivet Plus 660 mg', {(660.0, 'mg')}),
    ('Vermivet Plus 2 g', {(2000.0, 'mg')}),
    ('Banni 0,32 mL – até 5kg', {(0.32, 'ml')}),
    ('Solução 50 mg/mL', {(50.0, 'mg/ml')}),
    ('Até 5 kg', set()),
    ('2 gotas', set()),
])
def test_forca_citada_no_cabecalho(texto, forcas):
    assert escopo.forcas_do_texto(texto) == forcas


# ───────────────────────── duração ─────────────────────────────────────────


@pytest.mark.parametrize('texto, esperado', [
    ('Dose única, sendo a dose repetida após 15 dias', (None, None)),
    ('O tratamento deve ser repetido a cada 3 meses', (None, None)),
    ('Aplicar a cada 30 dias', (None, None)),
    ('5 dias. Repetir o tratamento após 14 dias.', (5, 5)),
    ('7 a 10 dias', (7, 10)),
    ('por 2 semanas', (14, 14)),
])
def test_intervalo_de_repeticao_nao_e_duracao(texto, esperado):
    assert bulario._parse_duracao_dias(texto) == esperado


def test_frase_de_repeticao_e_preservada_em_vez_de_virar_duracao():
    assert posologia.normalizar_duracao('O tratamento deve ser repetido a cada 3 meses') == (
        'O tratamento deve ser repetido a cada 3 meses'
    )
    assert posologia.normalizar_duracao('7 a 10 dias. Em processos crônicos, prolongar.') == '7 a 10 dias'


@pytest.mark.parametrize('texto, dias, fonte, esperado', [
    ('Até o 6º mês de idade', 15, 'SCRAPER', (None, None)),
    ('A critério do médico veterinário', 30, 'SCRAPER', (None, None)),
    ('7 dias ou a critério do médico veterinário', 7, 'SCRAPER', (7, 7)),
    ('', 10, 'SCRAPER', (10, 10)),
    ('Uso contínuo', 30, 'HUMANO', (30, 30)),
])
def test_dias_gravados_so_valem_quando_o_texto_os_sustenta(texto, dias, fonte, esperado):
    protocolo = SimpleNamespace(duracao=texto, duracao_min_dias=dias, duracao_max_dias=dias, fonte=fonte)

    assert bulario._duracao_estruturada(protocolo) == esperado


def test_duracao_do_produto_nao_e_garimpada_no_texto_de_frequencia():
    """ "aos 15 dias de idade" na frequência já virou "por 15 dias"."""
    med = _vermivet()

    assert bulario._duracao_produtos_vetsmart(escopo.escopo_de(med, 'Vermivet Filhote')) == (None, None, None)


# ───────────────────────── pela aplicação ──────────────────────────────────


def _login(client, user_id):
    with client.session_transaction() as sessao:
        sessao.clear()
        sessao['_user_id'] = str(user_id)
        sessao['_fresh'] = True


@pytest.fixture
def vermivet_no_banco(app):
    from app import _clear_medication_search_cache

    _clear_medication_search_cache()
    modelo = _vermivet()
    user = User(name='Vet', email='vet-produto@example.com', worker='veterinario', role='veterinario')
    user.set_password('x')
    db.session.add(user)
    db.session.flush()
    med = Medicamento(
        nome=modelo.nome, principio_ativo=modelo.principio_ativo, classificacao=modelo.classificacao,
        via_administracao='Oral', vetsmart_produto_id=288,
        conteudo_estruturado=modelo.conteudo_estruturado, created_by=user.id,
    )
    db.session.add(med)
    db.session.flush()
    for ap in modelo.apresentacoes:
        db.session.add(ApresentacaoMedicamento(
            medicamento_id=med.id, forma=ap.forma, concentracao=ap.concentracao,
            nome_variante=ap.nome_variante, concentracao_valor=ap.concentracao_valor,
            concentracao_unidade=ap.concentracao_unidade, volume_valor=ap.volume_valor,
            volume_unidade=ap.volume_unidade, fabricante=ap.fabricante,
            vetsmart_produto_id=ap.vetsmart_produto_id,
        ))
    for dose in modelo.doses:
        db.session.add(DoseMedicamento(
            medicamento_id=med.id, especie=dose.especie, especie_code=dose.especie_code, via=dose.via,
            dose=dose.dose, dose_min=dose.dose_min, dose_max=dose.dose_max, dose_unidade=dose.dose_unidade,
            frequencia=dose.frequencia, duracao=dose.duracao, duracao_min_dias=dose.duracao_min_dias,
            duracao_max_dias=dose.duracao_max_dias, dose_raw_text=dose.dose_raw_text, fonte=dose.fonte,
        ))
    # Eco de uma receita antiga: o texto da apresentação virou "medicamento".
    db.session.add(Medicamento(nome='Vermivet Filhote, frasco (20 mL), com seringa dosadora', created_by=user.id))
    db.session.commit()
    return SimpleNamespace(med_id=med.id, user_id=user.id)


def test_detalhe_do_produto_traz_a_apresentacao_e_a_posologia_dele(client, vermivet_no_banco):
    resposta = client.get(
        f'/medicamento/{vermivet_no_banco.med_id}/detalhe',
        query_string={'nome_exibicao': 'Vermivet Filhote', 'nome_comercial_filtro': 'Vermivet Filhote'},
    )

    dados = resposta.get_json()
    assert [ap['rotulo_opcao'] for ap in dados['apresentacoes']] == ['Frasco (20 mL), com seringa dosadora']
    assert dados['apresentacoes_origem'] == {'tipo': 'produto', 'produto': 'Vermivet Filhote'}
    assert dados['bula_url'].endswith('/288')
    assert dados['frequencia'] == FREQUENCIA_FILHOTE
    assert dados['duracao_tratamento'] == 'Até o 6º mês de idade'
    assert dados['posologia_produto']['dosagens'] == [
        {'grupo': None, 'especie': 'Cães e Gatos', 'rotulo': None, 'dose': '1 mL / kg'},
    ]


def test_busca_nao_oferece_o_eco_de_receita_antiga_ao_lado_do_produto(client, vermivet_no_banco):
    resposta = client.get('/buscar_medicamentos', query_string={'q': 'vermivet filhote'})

    nomes = [item['nome_exibicao_busca'] for item in resposta.get_json()]
    assert nomes == ['Vermivet Filhote']


def test_apresentacao_cadastrada_num_produto_fica_presa_a_ele(client, vermivet_no_banco):
    _login(client, vermivet_no_banco.user_id)

    resposta = client.post('/apresentacao_medicamento', json={
        'medicamento_id': vermivet_no_banco.med_id, 'forma': 'frasco', 'concentracao': '10 mL',
        'nome_comercial': 'Vermivet Filhote',
    })

    dados = resposta.get_json()
    assert dados['success'] is True
    rotulos = [ap.get('rotulo_opcao') for ap in dados['apresentacoes']]
    assert rotulos == ['Frasco (20 mL), com seringa dosadora', '10 mL, frasco']
    do_vizinho = client.get(
        f'/medicamento/{vermivet_no_banco.med_id}/detalhe',
        query_string={'nome_comercial_filtro': 'Vermivet Plus'},
    ).get_json()
    assert dados['id'] not in {ap['id'] for ap in do_vizinho['apresentacoes']}


# ───────────────────────── a tela ──────────────────────────────────────────


def test_tela_usa_o_rotulo_do_produto_e_recalcula_ao_trocar_a_apresentacao():
    fonte = (RAIZ / 'templates' / 'partials' / 'prescricao_form.html').read_text(encoding='utf-8')

    # Rótulo pronto do servidor antes de qualquer recomposição no navegador.
    funcao = fonte.split('function _rotuloOpcaoApresentacao(ap) {', 1)[1].split('function ', 1)[0]
    assert funcao.index('ap.rotulo_opcao') < funcao.index('ap.nome_variante')
    # A apresentação escolhida vai junto no pedido de dose…
    assert "params.append('apresentacao_id'" in fonte
    # …e trocar de apresentação pede a dose de novo quando ela depende disso.
    troca = fonte.split('function onApresentacaoPrescricaoChange() {', 1)[1].split('\n  function ', 1)[0]
    assert 'depende_da_apresentacao' in troca and 'carregarSugestaoDose(' in troca
    # Dose em mL/comprimidos não pede concentração em mg.
    escolha = fonte.split('function onApresentacaoEscolhida(apresentacaoId) {', 1)[1].split('\n  function ', 1)[0]
    assert escolha.index('ap.conversao_direta') < escolha.index('_mostrarConcWrap(ap)')
    # Apresentação cadastrada com um produto escolhido fica presa a ele.
    assert 'nome_comercial: medicamentoSelecionado?.nome_comercial_filtro' in fonte


# ───────────────────────── guard de classe ─────────────────────────────────


@pytest.mark.parametrize('montar', CATALOGO, ids=lambda f: f.__name__.strip('_'))
def test_auditor_sai_limpo_em_todos_os_formatos_do_catalogo(montar):
    assert auditor.violacoes_do_medicamento(montar()) == []


def test_auditor_acusa_o_defeito_quando_o_recorte_por_produto_e_desligado(monkeypatch):
    """Sem isto, o guard acima passaria mesmo se não verificasse nada."""
    monkeypatch.setattr(bulario, 'escopo_de', lambda medicamento, nome_comercial=None: None)

    codigos = {
        codigo
        for montar in CATALOGO
        for codigo, _produto, _detalhe in auditor.violacoes_do_medicamento(montar())
    }

    assert {'OUTRO_PRODUTO', 'LINHA_OCULTA', 'FALTA_VETSMART'} <= codigos
