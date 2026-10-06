"""Testes de ponta a ponta para a prescrição do Frontline Plus e suas apresentações."""
from types import SimpleNamespace
import pytest

from app_factory import create_app
from extensions import db
from models.base import User, Animal, Species, Clinica
from models.bulario import (
    Medicamento,
    ApresentacaoMedicamento,
    DoseMedicamento,
    PrescricaoAliasMedicamento,
)
from models.consulta import Prescricao, BlocoPrescricao
from services.bulario import (
    sugerir_dose,
    listar_apresentacoes_medicamento,
    serializar_medicamento_busca,
)


@pytest.fixture
def app_with_frontline(app):
    with app.app_context():
        # Assegura que o seed do Frontline Plus esteja presente
        from scripts.seed_frontline_plus import seed_frontline_plus
        seed_frontline_plus()
        yield app


def test_frontline_busca_por_nome_e_principio_ativo(app_with_frontline):
    """Garante que a busca encontre Frontline Plus tanto pelo nome quanto por Fipronil."""
    client = app_with_frontline.test_client()

    # 1. Busca por 'frontline'
    resp = client.get('/buscar_medicamentos?q=frontline')
    assert resp.status_code == 200
    nomes = [m['nome'] for m in resp.json]
    assert 'Frontline Plus' in nomes

    # 2. Busca por 'fipronil'
    resp = client.get('/buscar_medicamentos?q=fipronil')
    assert resp.status_code == 200
    nomes = [m['nome'] for m in resp.json]
    assert 'Frontline Plus' in nomes


def test_frontline_cinco_apresentacoes_presentes(app_with_frontline):
    """Garante que todas as 5 apresentações da imagem estejam disponíveis no bulário."""
    med = Medicamento.query.filter_by(nome='Frontline Plus').first()
    assert med is not None
    assert len(med.apresentacoes) == 5

    apresentacoes = listar_apresentacoes_medicamento(med)
    assert len(apresentacoes) == 5

    variantes_esperadas = [
        "Frontline® Plus gatos até 10 Kg, pipeta (1 un)",
        "Frontline® Plus cães até 10 Kg, pipeta (1 un)",
        "Frontline® Plus cães de 10 Kg a 20Kg, pipeta (1 un)",
        "Frontline® Plus cães de 20 Kg a 40Kg, pipeta (1 un)",
        "Frontline® Plus cães de 40 Kg a 60Kg, pipeta (1 un)",
    ]

    variantes_obtidas = [a.get('nome_variante') for a in apresentacoes]
    for esperada in variantes_esperadas:
        assert esperada in variantes_obtidas, f"Apresentação {esperada} não encontrada nas variantes obtidas: {variantes_obtidas}"

    # Todas devem ter unidade prática = pipeta e categoria = topico
    for ap in apresentacoes:
        assert ap.get('categoria') == 'topico'
        assert ap.get('unidade_pratica') == 'pipeta'


def test_frontline_sugestao_dose_cao_diferentes_pesos(app_with_frontline):
    """Garante a escolha automática da apresentação e dose correta por faixa de peso em cães."""
    med = Medicamento.query.filter_by(nome='Frontline Plus').first()
    assert med is not None

    cenarios = [
        (4.5, "Frontline® Plus cães até 10 Kg, pipeta (1 un)"),
        (15.0, "Frontline® Plus cães de 10 Kg a 20Kg, pipeta (1 un)"),
        (25.0, "Frontline® Plus cães de 20 Kg a 40Kg, pipeta (1 un)"),
        (55.0, "Frontline® Plus cães de 40 Kg a 60Kg, pipeta (1 un)"),
    ]

    for peso, variante_esperada in cenarios:
        animal = SimpleNamespace(peso=peso, species=SimpleNamespace(name='Cachorro'))
        sug = sugerir_dose(med, animal)
        assert sug is not None, f"Falha ao gerar sugestão para cão de {peso} kg"
        assert sug.get('dose_unit_out') == 'pipeta(s)'
        assert sug.get('via') == 'Tópica'
        assert sug.get('apresentacao_preferida_nome') == variante_esperada, (
            f"Para peso {peso} kg, esperava {variante_esperada} mas obteve {sug.get('apresentacao_preferida_nome')}"
        )


def test_frontline_sugestao_dose_gato(app_with_frontline):
    """Garante a escolha automática da apresentação e dose correta para gatos."""
    med = Medicamento.query.filter_by(nome='Frontline Plus').first()
    assert med is not None

    animal_gato = SimpleNamespace(peso=3.8, species=SimpleNamespace(name='Gato'))
    sug = sugerir_dose(med, animal_gato)
    assert sug is not None
    assert sug.get('dose_unit_out') == 'pipeta(s)'
    assert sug.get('via') == 'Tópica'
    assert sug.get('apresentacao_preferida_nome') == "Frontline® Plus gatos até 10 Kg, pipeta (1 un)"


def test_frontline_prescricao_persistida_em_consulta(app_with_frontline):
    """Testa criação e persistência de prescrição do Frontline Plus associada a um animal e consulta."""
    vet = User.query.filter(User.role.in_(['veterinario', 'admin'])).first()
    if not vet:
        vet = User(
            name="Dr. Veterinário",
            email="vet_frontline@example.com",
            password_hash="test_vet_hash",
            role="veterinario",
        )
        db.session.add(vet)
        db.session.flush()

    clinica = Clinica.query.first()
    if not clinica:
        clinica = Clinica(nome="Clínica Teste Frontline")
        db.session.add(clinica)
        db.session.flush()

    tutor = User.query.filter_by(role='adotante').first()
    if not tutor:
        tutor = User(
            name="Tutor Teste",
            email="tutor_frontline@example.com",
            password_hash="test_tutor_hash",
            role="adotante",
        )
        db.session.add(tutor)
        db.session.flush()

    animal = Animal.query.filter_by(name="Rex Frontline").first()
    if not animal:
        especie_cao = Species.query.filter(Species.name.ilike('%cão%') | Species.name.ilike('%cachorro%')).first()
        if not especie_cao:
            especie_cao = Species(name="Cachorro")
            db.session.add(especie_cao)
            db.session.flush()
        animal = Animal(
            name="Rex Frontline",
            species=especie_cao,
            owner=tutor,
            clinica_id=clinica.id,
            peso=16.5,
        )
        db.session.add(animal)
        db.session.flush()

    med = Medicamento.query.filter_by(nome='Frontline Plus').first()
    sug = sugerir_dose(med, animal)
    assert sug is not None

    # Simula montagem do item de prescrição conforme o frontend do Petorlândia
    nome_prescrito = f"{med.nome} — Cães de 10 Kg a 20Kg, pipeta (1 un)"
    dose_str = "1 (uma) pipeta"
    freq_str = "A cada 30 dias (trinta dias)"
    dur_str = "Dose única (repetir mensalmente se necessário)"
    obs_str = "Aplicar todo o conteúdo da pipeta diretamente na pele da nuca do animal, afastando os pelos."

    bloco = BlocoPrescricao(
        animal_id=animal.id,
        saved_by_id=vet.id,
        clinica_id=clinica.id,
        instrucoes_gerais="Controle preventivo mensal contra pulgas e carrapatos.",
    )
    db.session.add(bloco)
    db.session.flush()

    prescricao = Prescricao(
        bloco_id=bloco.id,
        animal_id=animal.id,
        medicamento=nome_prescrito,
        dosagem=dose_str,
        frequencia=freq_str,
        duracao=dur_str,
        observacoes=obs_str,
    )
    db.session.add(prescricao)
    db.session.commit()

    # Validação do registro gravado
    salva = Prescricao.query.get(prescricao.id)
    assert salva is not None
    assert salva.medicamento == "Frontline Plus — Cães de 10 Kg a 20Kg, pipeta (1 un)"
    assert salva.dosagem == "1 (uma) pipeta"
    assert salva.frequencia == "A cada 30 dias (trinta dias)"
    assert salva.animal.name == "Rex Frontline"
