from pathlib import Path
from types import SimpleNamespace
import importlib.util


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('services_bulario_test', ROOT / 'services' / 'bulario.py')
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
sugerir_dose = MODULE.sugerir_dose


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
