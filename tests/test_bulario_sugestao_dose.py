from pathlib import Path
from types import SimpleNamespace
import importlib.util


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('services_bulario_test', ROOT / 'services' / 'bulario.py')
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
sugerir_dose = MODULE.sugerir_dose
extrair_secoes_vetsmart = MODULE.extrair_secoes_vetsmart
montar_monografia_medicamento = MODULE.montar_monografia_medicamento
listar_apresentacoes_medicamento = MODULE.listar_apresentacoes_medicamento


def _animal_caes(peso=10.0):
    return SimpleNamespace(
        peso=peso,
        species=SimpleNamespace(name='Cachorro'),
    )


def _apresentacao(forma, concentracao='', fabricante='', nome_variante=''):
    return SimpleNamespace(
        id=1,
        forma=forma,
        concentracao=concentracao,
        nome_variante=nome_variante,
        fabricante=fabricante,
        concentracao_valor=None,
        concentracao_unidade=None,
        volume_valor=None,
        volume_unidade=None,
    )


def _dose(
    proto_id,
    via,
    dose,
    dose_min,
    dose_max,
    dose_unidade,
    *,
    especie='Cães',
    especie_code='CAES',
    indicacao=None,
    intervalo_horas=12,
):
    return SimpleNamespace(
        id=proto_id,
        especie=especie,
        especie_code=especie_code,
        faixa_peso=None,
        peso_min_kg=None,
        peso_max_kg=None,
        via=via,
        dose=dose,
        dose_min=dose_min,
        dose_max=dose_max,
        dose_unidade=dose_unidade,
        frequencia=None,
        intervalo_horas=intervalo_horas,
        intervalo_min_horas=None,
        intervalo_max_horas=None,
        duracao=None,
        duracao_min_dias=None,
        duracao_max_dias=None,
        indicacao=indicacao,
        fonte='TESTE',
        confianca='ALTA',
        observacao=None,
    )


def test_sugerir_dose_prefere_via_compativel_com_apresentacoes_orais():
    med = SimpleNamespace(
        id=10,
        via_administracao='IM',
        apresentacoes=[_apresentacao('Comprimido', '5 mg')],
        doses=[
            _dose(100, 'IM', '0,5 - 1 mg/kg', 0.5, 1.0, 'MG_KG', indicacao='Alergia'),
            _dose(200, 'Oral', '0,5 - 1 mg/kg', 0.5, 1.0, 'MG_KG', indicacao='Alergia'),
        ],
    )

    sugestao = sugerir_dose(med, _animal_caes(), indicacao='Alergia')

    assert sugestao is not None
    assert sugestao['protocolo_id'] == 200
    assert sugestao['via'] == 'Oral'


def test_sugerir_dose_nao_forca_indicacao_unica_se_ha_protocolos_genericos():
    med = SimpleNamespace(
        id=20,
        via_administracao='Oral',
        apresentacoes=[_apresentacao('Comprimido', '0,5 mg')],
        doses=[
            _dose(1, 'Oral', '0,1 - 0,2 mg/kg', 0.1, 0.2, 'MG_KG', intervalo_horas=24),
            _dose(2, 'Oral', '0,1 - 0,2 mL/kg', 0.1, 0.2, 'ML_KG', intervalo_horas=24),
            _dose(3, 'IV (cães)', '0,1 mg/kg', 0.1, 0.1, 'MG_KG', indicacao='Anti-inflamatório', intervalo_horas=24),
        ],
    )

    sugestao = sugerir_dose(med, _animal_caes())

    assert sugestao is not None
    assert sugestao['protocolo_id'] == 1
    assert sugestao['via'] == 'Oral'
    assert sugestao['dose_unit_out'] == 'mg'


def test_sugerir_dose_inclui_uso_geral_no_dropdown_quando_misto():
    """Quando coexistem protocolos com indicação nomeada E sem indicação,
    o dropdown precisa oferecer 'Uso geral' como alternativa pro vet trocar.
    Sem isso o usuário fica preso na indicação nomeada (bug do screenshot
    'só tem como escolher Infecção, e Uso geral some')."""
    med = SimpleNamespace(
        id=80,
        via_administracao='Oral',
        apresentacoes=[_apresentacao('Comprimido', '5 mg')],
        doses=[
            # 3 protocolos sem indicação cadastrada (= "Uso geral" no display)
            _dose(801, 'Oral', '10 mg/kg', 10.0, 10.0, 'MG_KG', intervalo_horas=24),
            _dose(802, 'Oral', '5 - 10 mg/kg', 5.0, 10.0, 'MG_KG', intervalo_horas=12),
            _dose(803, 'Oral', '5 mg/kg', 5.0, 5.0, 'MG_KG', intervalo_horas=12),
            # 1 protocolo com indicação nomeada
            _dose(804, 'Oral', '5 mg/kg', 5.0, 5.0, 'MG_KG', indicacao='Infecção', intervalo_horas=12),
        ],
    )

    # Caso A: vet escolheu "Infecção" → resposta deve listar "Uso geral" como
    # alternativa pra ele poder trocar.
    sug_infeccao = sugerir_dose(med, _animal_caes(), indicacao='Infecção')
    assert sug_infeccao is not None
    assert sug_infeccao['indicacao'] == 'Infecção'
    assert 'Uso geral' in (sug_infeccao.get('indicacoes_alternativas') or [])

    # Caso B: vet escolheu "Uso geral" → deve casar com protocolos NULL.
    sug_geral = sugerir_dose(med, _animal_caes(), indicacao='Uso geral')
    assert sug_geral is not None
    assert sug_geral['indicacao'] == 'Uso geral'
    assert sug_geral['protocolo_id'] in {801, 802, 803}, \
        f"Esperava protocolo genérico, veio {sug_geral['protocolo_id']}"


def test_sugerir_dose_em_gotas_preserva_contexto_local():
    med = SimpleNamespace(
        id=30,
        via_administracao='Oftálmico',
        apresentacoes=[_apresentacao('Colírio', '0,3%')],
        doses=[
            _dose(7, 'Oftálmico', '1 - 2 gotas/olho', 1.0, 2.0, 'GOTAS_ANIMAL', especie='Cães e Gatos', especie_code='AMBOS', intervalo_horas=8),
        ],
    )

    sugestao = sugerir_dose(med, _animal_caes())

    assert sugestao is not None
    assert sugestao['dose_exibir'] == '1–2 gota(s) por olho'
    assert sugestao['via'] == 'Oftálmico'


def test_sugerir_dose_expoe_nome_variante_da_apresentacao():
    ap = _apresentacao(
        'Comprimido mastigavel',
        '80 mg',
        fabricante='Zoetis',
        nome_variante='Antipulgas Zoetis Simparic 80 mg para Caes 20,1 a 40 Kg',
    )
    ap.concentracao_valor = 80
    ap.concentracao_unidade = 'mg'
    ap.volume_valor = 1
    ap.volume_unidade = 'un'
    med = SimpleNamespace(
        id=40,
        via_administracao='Oral',
        apresentacoes=[ap],
        doses=[
            _dose(
                8,
                'Oral',
                '1 comprimido / animal (80 mg)',
                1,
                1,
                'COMPRIMIDOS_ANIMAL',
                especie='Caes',
                especie_code='CAES',
                indicacao='Controle de ectoparasitas',
                intervalo_horas=720,
            ),
        ],
    )

    sugestao = sugerir_dose(med, _animal_caes(25), indicacao='Controle de ectoparasitas')

    assert sugestao is not None
    assert sugestao['apresentacao_preferida_id'] == 1
    assert sugestao['apresentacoes'][0]['nome_variante'] == 'Antipulgas Zoetis Simparic 80 mg para Caes 20,1 a 40 Kg'
    assert sugestao['apresentacoes'][0]['faixa_peso_label'] == '20,1 a 40 kg'
    assert sugestao['apresentacoes'][0]['especie_label'] == 'Caes'
    assert sugestao['apresentacoes'][0]['rotulo_escolha'] == {
        'principal': 'Caes 20,1 a 40 kg',
        'secundario': '80 mg Comprimido mastigavel',
        'especie': 'Caes',
    }


def test_sugerir_dose_deduplica_forcas_e_preserva_suspensao():
    ap_75_a = _apresentacao('Comprimido', '75 mg', fabricante='Duprat')
    ap_75_a.id = 101
    ap_75_a.concentracao_valor = 75
    ap_75_a.concentracao_unidade = 'mg'
    ap_75_b = _apresentacao('Comprimido', '75 mg', fabricante='Cepav')
    ap_75_b.id = 102
    ap_75_b.concentracao_valor = 75
    ap_75_b.concentracao_unidade = 'mg'
    susp = _apresentacao('Suspensao', '', fabricante='LigVet Farmacia de Manipulacao')
    susp.id = 103

    med = SimpleNamespace(
        id=41,
        via_administracao='Oral',
        apresentacoes=[ap_75_a, ap_75_b, susp],
        doses=[
            _dose(9, 'Oral', '20 - 30 mg/kg', 20, 30, 'MG_KG', indicacao='Infeccao'),
        ],
    )

    sugestao = sugerir_dose(med, _animal_caes(5), indicacao='Infeccao')

    assert sugestao is not None
    comprimidos_75 = [
        ap for ap in sugestao['apresentacoes']
        if ap['categoria'] == 'solido_oral' and ap['concentracao_valor'] == 75
    ]
    assert len(comprimidos_75) == 1
    assert comprimidos_75[0]['source_count'] == 2
    assert set(comprimidos_75[0]['fabricantes']) == {'Duprat', 'Cepav'}

    suspensoes = [ap for ap in sugestao['apresentacoes'] if ap['categoria'] == 'suspensao_oral']
    assert len(suspensoes) == 1
    assert suspensoes[0]['permite_calculo_automatico'] is False
    assert suspensoes[0]['tipo_origem'] == 'manipulado'


def test_listar_apresentacoes_cefalexina_preserva_concentracao_clinica_e_filtra_embalagem():
    sol_250 = _apresentacao('Solucao oral', '250 mg / 5mL, solucao', fabricante='VetSmart Prescritor')
    sol_250.id = 201
    sol_250.concentracao_valor = 50
    sol_250.concentracao_unidade = 'mg/ml'

    gotas = _apresentacao('Gotas', '100 mg/mL, gotas', fabricante='VetSmart Prescritor')
    gotas.id = 202
    gotas.concentracao_valor = 100
    gotas.concentracao_unidade = 'mg/ml'

    susp = _apresentacao('frasco', 'Suspensao (60 mL)', fabricante='Cepav', nome_variante='Suspensao')
    susp.id = 203
    susp.volume_valor = 60
    susp.volume_unidade = 'ml'

    pacote = _apresentacao('comprimido', 'Lexin (12 un)', fabricante='Duprat', nome_variante='Lexin')
    pacote.id = 204

    med = SimpleNamespace(
        id=42,
        via_administracao='Oral',
        apresentacoes=[sol_250, gotas, susp, pacote],
    )

    apresentacoes = listar_apresentacoes_medicamento(med)
    por_id = {ap['id']: ap for ap in apresentacoes}

    assert set(por_id) == {201, 202, 203}
    assert por_id[201]['rotulo_principal'] == '250 mg/5 mL solução oral'
    assert por_id[201]['concentracao_label'] == '250 mg/5 mL'
    assert por_id[201]['concentracao_unidade'] == 'mg/mL'
    assert por_id[201]['unidade_pratica'] == 'mL'

    assert por_id[202]['rotulo_principal'] == '100 mg/mL gotas'
    assert por_id[202]['unidade_pratica'] == 'gota'

    assert por_id[203]['categoria'] == 'suspensao_oral'
    assert por_id[203]['rotulo_principal'] == 'suspensão oral (60 mL)'
    assert por_id[203]['unidade_pratica'] == 'mL'
    assert por_id[203]['permite_calculo_automatico'] is False


def test_sugerir_dose_preserva_duracao_textual_do_protocolo():
    med = SimpleNamespace(
        id=50,
        nome='Simparic',
        classificacao='Ectoparasiticida',
        via_administracao='Oral',
        apresentacoes=[],
        doses=[
            SimpleNamespace(
                id=9,
                especie='Caes',
                especie_code='CAES',
                faixa_peso='5,1 a 10 Kg',
                peso_min_kg=5.1,
                peso_max_kg=10.0,
                via='Oral',
                dose='1 comprimido / animal (20 mg)',
                dose_min=1,
                dose_max=1,
                dose_unidade='COMPRIMIDOS_ANIMAL',
                frequencia='A cada 30 dias',
                intervalo_horas=None,
                intervalo_min_horas=None,
                intervalo_max_horas=None,
                duracao='Conforme protocolo mensal',
                duracao_min_dias=None,
                duracao_max_dias=None,
                indicacao='Controle de ectoparasitas',
                fonte='TESTE',
                confianca='ALTA',
                observacao=None,
                dose_raw_text='Antipulgas Zoetis Simparic 20 mg para Caes 5,1 a 10 Kg: 1 comprimido por administracao.',
            ),
        ],
    )

    sugestao = sugerir_dose(med, _animal_caes(5.2), indicacao='Controle de ectoparasitas')

    assert sugestao is not None
    assert sugestao['duracao_e_padrao'] is False
    assert sugestao['duracao_texto'] == 'Conforme protocolo mensal'


def test_sugerir_dose_usa_duracao_do_prescritor_vetsmart_como_fallback():
    med = SimpleNamespace(
        id=51,
        nome='Cefalexina',
        classificacao='Antibacteriano',
        via_administracao='Oral',
        conteudo_estruturado={
            'prescritor_vetsmart': {
                'duracao_min_dias': 5,
                'duracao_max_dias': 10,
                'duracao_texto': '5 a 10 dias',
                'frequencia_texto': '8/8 ou 12/12 horas',
            }
        },
        apresentacoes=[],
        doses=[
            _dose(12, 'Oral', '20 - 30 mg/kg', 20, 30, 'MG_KG', intervalo_horas=12),
        ],
    )

    sugestao = sugerir_dose(med, _animal_caes(5))

    assert sugestao is not None
    assert sugestao['duracao_min_dias'] == 5
    assert sugestao['duracao_max_dias'] == 10
    assert sugestao['duracao_do_prescritor_vetsmart'] is True
    assert sugestao['duracao_e_padrao'] is False
    assert 'DURACAO_PRESCRITOR_VETSMART' in {f['codigo'] for f in sugestao['flags_risco']}


def test_sugerir_dose_prefere_duracao_do_painel_vetsmart_produto():
    med = SimpleNamespace(
        id=52,
        nome='Cefalexina',
        classificacao='Antibacteriano',
        via_administracao='Oral',
        conteudo_estruturado={
            'produtos_vetsmart': [
                {
                    'nome': 'Cefalexina',
                    'tipo': 'principio_ativo',
                    'duracao_tratamento': 'Frequentemente usa-se de 5 a 10 dias.',
                    'secoes': {},
                }
            ],
            'prescritor_vetsmart': {
                'duracao_min_dias': 7,
                'duracao_max_dias': 7,
                'duracao_texto': '7 dias',
            },
        },
        apresentacoes=[],
        doses=[
            _dose(13, 'Oral', '20 - 30 mg/kg', 20, 30, 'MG_KG', intervalo_horas=12),
        ],
    )

    sugestao = sugerir_dose(med, _animal_caes(5))

    assert sugestao is not None
    assert sugestao['duracao_min_dias'] == 5
    assert sugestao['duracao_max_dias'] == 10
    assert sugestao['duracao_do_prescritor_vetsmart'] is True


def test_monografia_expoe_produtos_vetsmart():
    med = SimpleNamespace(
        id=53,
        nome='Cefalexina',
        dosagem_recomendada=None,
        frequencia=None,
        duracao_tratamento=None,
        observacoes=None,
        conteudo_estruturado={
            'produtos_vetsmart': [
                {
                    'vetsmart_produto_id': 10,
                    'nome': 'Cefaseptin',
                    'tipo': 'produto',
                    'fabricante': 'Vetoquinol',
                    'frequencia': '12/12 horas',
                    'duracao_tratamento': 'A criterio do medico veterinario.',
                    'apresentacoes': [{'forma': 'Comprimido', 'concentracao': '75 mg'}],
                    'doses': [{'dose': '15 mg/kg'}],
                    'secoes': {'Composição': {'texto': 'Cefalexina 75 mg.'}},
                    'fonte': 'https://vetsmart.com.br/cg/produto/10',
                }
            ]
        },
        doses=[],
    )

    monografia = montar_monografia_medicamento(med)

    assert monografia['produtos_vetsmart'][0]['nome'] == 'Cefaseptin'
    assert monografia['produtos_vetsmart'][0]['apresentacoes_count'] == 1
    assert monografia['produtos_vetsmart'][0]['doses_count'] == 1
    assert monografia['tem_conteudo_clinico'] is True


def test_sugerir_dose_expoe_proveniencia_e_flags_de_validacao():
    med = SimpleNamespace(
        id=60,
        nome='Prednisolona',
        classificacao='Corticosteroide',
        via_administracao='Oral',
        apresentacoes=[],
        doses=[
            SimpleNamespace(
                id=10,
                especie='Caes',
                especie_code='CAES',
                faixa_peso=None,
                peso_min_kg=None,
                peso_max_kg=None,
                via='Oral',
                dose='0,5 - 1 mg/kg',
                dose_min=0.5,
                dose_max=1.0,
                dose_unidade='MG_KG',
                frequencia=None,
                intervalo_horas=24,
                intervalo_min_horas=None,
                intervalo_max_horas=None,
                duracao=None,
                duracao_min_dias=None,
                duracao_max_dias=None,
                indicacao=None,
                fonte='LLM',
                confianca='BAIXA',
                observacao=None,
                dose_raw_text='Caes: 0,5 - 1 mg/kg VO a cada 24h.',
            ),
        ],
    )

    sugestao = sugerir_dose(med, _animal_caes(8))

    assert sugestao is not None
    assert sugestao['origem']['fonte'] == 'LLM'
    assert sugestao['diagnosticos']['requer_validacao_clinica'] is True
    codigos = {flag['codigo'] for flag in sugestao['flags_risco']}
    assert 'PROTOCOLO_ASSISTIDO' in codigos
    assert 'CONFIANCA_BAIXA' in codigos
    assert 'DURACAO_INFERIDA' in codigos
    assert 'INDICACAO_NAO_ESPECIFICADA' in codigos
    assert 'SEM_APRESENTACAO_COMERCIAL' in codigos


def test_sugerir_dose_corticoide_oculta_indicacoes_genericas_quando_ha_especificas():
    med = SimpleNamespace(
        id=61,
        nome='Prednisolona',
        classificacao='Anti-inflamatório Esteroidal',
        principio_ativo='Prednisolona',
        via_administracao='Oral',
        apresentacoes=[],
        doses=[
            _dose(1, 'Oral', '0,5 - 1 mg/kg', 0.5, 1.0, 'MG_KG', indicacao='Anti-inflamatório', intervalo_horas=24),
            _dose(2, 'Oral', '1 mg/kg', 1.0, 1.0, 'MG_KG', indicacao='Alergia', intervalo_horas=12),
            _dose(3, 'Oral', '2 mg/kg', 2.0, 2.0, 'MG_KG', indicacao='Imunossupressão', intervalo_horas=24),
            _dose(4, 'Oral', '0,2 - 0,4 mg/kg', 0.2, 0.4, 'MG_KG', indicacao='Uso prolongado', intervalo_horas=48),
        ],
    )

    sugestao = sugerir_dose(med, _animal_caes(8))

    assert sugestao is not None
    assert sugestao['multiplo'] is True
    assert sugestao['indicacoes'] == ['Alergia', 'Imunossupressão']


def test_monografia_ignora_dose_de_comprimido_ambigua_em_medicamento_consolidado():
    ap1 = _apresentacao('Comprimido', '5 mg')
    ap1.concentracao_valor = 5
    ap1.concentracao_unidade = 'mg'
    ap2 = _apresentacao('Comprimido', '20 mg')
    ap2.id = 2
    ap2.concentracao_valor = 20
    ap2.concentracao_unidade = 'mg'

    dose_ambigua = _dose(10, 'Oral', '1 comprimido/animal', 1, 1, 'COMPRIMIDOS_ANIMAL', intervalo_horas=24)
    dose_ambigua.dose_raw_text = '1 comprimido / animal'
    dose_ambigua.faixa_peso = 'Até 5 kg'
    dose_segura = _dose(11, 'Oral', '0,5 - 1 mg/kg', 0.5, 1.0, 'MG_KG', indicacao='Alergia', intervalo_horas=12)
    dose_segura.dose_raw_text = '0,5 - 1 mg/kg'

    med = SimpleNamespace(
        id=62,
        nome='Prednisolona',
        classificacao='Anti-inflamatório Esteroidal',
        principio_ativo='Prednisolona',
        via_administracao='Oral',
        apresentacoes=[ap1, ap2],
        doses=[dose_ambigua, dose_segura],
    )

    sugestao = sugerir_dose(med, _animal_caes(8), indicacao='Alergia')

    assert sugestao is not None
    assert sugestao['protocolo_id'] == 11


def test_monografia_ignora_ml_animal_sem_concentracao_liquida_inequivoca():
    comp = _apresentacao('Comprimido', '500 mg')
    comp.concentracao_valor = 500
    comp.concentracao_unidade = 'mg'
    gotas = _apresentacao('Gotas', '500 mg/mL')
    gotas.id = 2
    gotas.concentracao_valor = 500
    gotas.concentracao_unidade = 'mg/ml'
    solucao = _apresentacao('Solucao Oral', '50 mg/mL')
    solucao.id = 3
    solucao.concentracao_valor = 50
    solucao.concentracao_unidade = 'mg/ml'

    dose_mg = _dose(20, 'IM', '25 mg/kg', 25, 25, 'MG_KG', intervalo_horas=8)
    dose_ml = _dose(21, 'IM', '1 - 5 ml/animal', 1, 5, 'ML_ANIMAL', intervalo_horas=8)

    med = SimpleNamespace(
        id=63,
        nome='Dipirona',
        classificacao='Analgesico',
        principio_ativo='Dipirona',
        via_administracao='IM',
        apresentacoes=[comp, gotas, solucao],
        doses=[dose_mg, dose_ml],
    )

    monografia = montar_monografia_medicamento(med)
    linhas = monografia['resumo_posologia']['tabs'][0]['protocolos'][0]['linhas']

    assert [linha['dose'] for linha in linhas] == ['25 mg/kg']

    sugestao = sugerir_dose(med, _animal_caes(10))

    assert sugestao is not None
    assert sugestao['protocolo_id'] == 20


def test_monografia_nao_usa_colirio_para_dose_im_em_ml():
    colirio = _apresentacao('Colírio', '1 mg/mL')
    colirio.concentracao_valor = 1
    colirio.concentracao_unidade = 'mg/ml'
    comprimido = _apresentacao('Comprimido', '4 mg')
    comprimido.id = 2
    comprimido.concentracao_valor = 4
    comprimido.concentracao_unidade = 'mg'

    dose_ml_im = _dose(31, 'IM', '0,25 - 0,5 ml/animal', 0.25, 0.5, 'ML_ANIMAL', intervalo_horas=24)
    dose_mg_im = _dose(32, 'IM', '0,25 - 0,5 mg/animal', 0.25, 0.5, 'MG_ANIMAL', intervalo_horas=24)

    med = SimpleNamespace(
        id=64,
        nome='Dexametasona',
        classificacao='Anti-inflamatório Esteroidal',
        principio_ativo='Dexametasona',
        via_administracao='Oral',
        apresentacoes=[colirio, comprimido],
        doses=[dose_ml_im, dose_mg_im],
    )

    monografia = montar_monografia_medicamento(med)
    linhas = monografia['resumo_posologia']['tabs'][0]['protocolos'][0]['linhas']

    assert [linha['dose'] for linha in linhas] == ['0,25 - 0,5 mg/animal']


def test_monografia_exibe_equivalencia_mg_quando_ml_tem_concentracao_compativel():
    colirio = _apresentacao('Colírio', '1 mg/mL')
    colirio.concentracao_valor = 1
    colirio.concentracao_unidade = 'mg/ml'
    dose_ml = _dose(33, 'Conjuntiva', '0,25 - 1 ml/animal', 0.25, 1, 'ML_ANIMAL', intervalo_horas=24)

    med = SimpleNamespace(
        id=65,
        nome='Dexametasona',
        classificacao='Anti-inflamatório Esteroidal',
        principio_ativo='Dexametasona',
        via_administracao='Oftálmica',
        apresentacoes=[colirio],
        doses=[dose_ml],
    )

    monografia = montar_monografia_medicamento(med)
    linha = monografia['resumo_posologia']['tabs'][0]['protocolos'][0]['linhas'][0]

    assert linha['dose'] == '0,25 - 1 ml/animal (equiv. 0,25 - 1 mg; 1 mg/mL)'


def test_extrair_secoes_vetsmart_prefere_html_sanitizado():
    med = SimpleNamespace(
        conteudo_estruturado={
            'raw_sections': {
                'Sobre': 'Aviso\nPrednisolona',
            },
            'raw_sections_html': {
                'Sobre': '<div><p><strong>Aviso</strong></p><script>alert(1)</script><p>Prednisolona</p></div>',
            },
        }
    )

    secoes = extrair_secoes_vetsmart(med)

    assert len(secoes) == 1
    assert secoes[0]['nome'] == 'Sobre'
    assert '<strong>Aviso</strong>' in (secoes[0]['html'] or '')
    assert '<script' not in (secoes[0]['html'] or '')
