"""Formas tópicas não têm dose numérica — e regra de dose não pode migrar de forma.

Dois defeitos apareceram juntos na tela de apoio clínico:

1. O shampoo de clorexidina (frasco 500 mL) saiu na receita do tutor como
   "8 gotas 1 vez por semana 3 meses", com a apresentação "50 g pomada -
   Furanil® Pomada" — outro medicamento. Causa: em
   `_practical_presentation_options`, uma regra com `dose_unit == "gota(s)"`
   atribuía `practical_unit = "gota"` a QUALQUER apresentação, sem checar se
   ela entrega gotas.

2. Mesmo com a apresentação certa, quantificar shampoo/pomada não faz sentido
   clínico: a instrução é o procedimento, não um número.

Doses em mg (ex.: prednisona) seguem pelo caminho antigo de propósito — é o
fluxo que já funcionava e não deve ser afetado por esta correção.
"""
from __future__ import annotations

import pytest

from services.clinical_plan import (
    _INSTRUCAO_SHAMPOO,
    _com_extenso,
    _forma_topica_padronizada,
    _instrucao_pomada,
    _presentation_delivers_unit,
)


class _Item:
    def __init__(self, nome_exibicao):
        self.nome_exibicao = nome_exibicao


# --- guarda de compatibilidade de unidade -----------------------------------

def test_regra_em_gotas_nao_cola_em_pomada():
    """O defeito exato do print: gotas casadas com uma pomada."""
    pomada = {"forma": "pomada", "unidade_pratica": "aplicacao"}
    assert _presentation_delivers_unit(pomada, "gota") is False


def test_regra_em_gotas_aceita_apresentacao_em_gotas():
    frasco = {"forma": "solucao oral", "unidade_pratica": "gota"}
    assert _presentation_delivers_unit(frasco, "gota") is True


def test_comprimido_so_casa_com_comprimido():
    comprimido = {"forma": "comprimido", "unidade_pratica": "comprimido"}
    suspensao = {"forma": "suspensao oral", "unidade_pratica": "mL"}
    assert _presentation_delivers_unit(comprimido, "comprimido") is True
    assert _presentation_delivers_unit(suspensao, "comprimido") is False


@pytest.mark.parametrize("unidade", ["mg", "mcg", "ui"])
def test_unidades_de_principio_ativo_nao_sao_filtradas(unidade):
    """mg descreve quantidade de fármaco, não forma de entrega.

    Prednisona depende deste caminho; filtrar aqui quebraria o que funciona.
    """
    qualquer = {"forma": "pomada", "unidade_pratica": "aplicacao"}
    assert _presentation_delivers_unit(qualquer, unidade) is True


def test_sem_dados_de_forma_nao_inventa_compatibilidade():
    assert _presentation_delivers_unit({}, "gota") is False


# --- instruções padronizadas -------------------------------------------------

def test_shampoo_recebe_protocolo_de_banho():
    texto = _forma_topica_padronizada(
        _Item("Shampoo de clorexidina - 0,20%, frasco (500mL)"), {}
    )
    assert texto == _INSTRUCAO_SHAMPOO
    assert "1 banho por semana" in texto
    assert "10 minutos" in texto
    assert "gota" not in texto, "shampoo não pode voltar a ser dosado em gotas"


def test_pomada_recebe_camada_fina_com_numeros_por_extenso():
    texto = _forma_topica_padronizada(_Item("Cetoconazol generico"), {"forma": "pomada"})
    assert texto == _instrucao_pomada()
    assert "camada fina sobre a area afetada" in texto
    assert "de 12 (doze) em 12 (doze) horas" in texto
    assert "por 10 (dez) dias" in texto


@pytest.mark.parametrize("forma", ["creme", "unguento", "gel dermatologico"])
def test_outras_formas_topicas_seguem_a_mesma_regra(forma):
    assert _forma_topica_padronizada(_Item("Qualquer"), {"forma": forma}) == _instrucao_pomada()


def test_comprimido_nao_vira_texto_topico():
    """Não pode capturar o que continua sendo dose numérica de verdade."""
    assert _forma_topica_padronizada(_Item("Prednisona 20mg comprimido"), {}) is None
    assert _forma_topica_padronizada(_Item("Simparic"), {}) is None


# --- número por extenso ------------------------------------------------------

@pytest.mark.parametrize(
    "valor, esperado",
    [(1, "1 (um)"), (10, "10 (dez)"), (12, "12 (doze)"), (24, "24 (vinte e quatro)")],
)
def test_numero_por_extenso(valor, esperado):
    assert _com_extenso(valor) == esperado


def test_numero_desconhecido_nao_quebra():
    assert _com_extenso(137) == "137"


# --- integração: os dois casos que travaram em produção ---------------------
#
# Depois da primeira correção o painel piorou: o shampoo virou "Dose calculada
# sem apresentacao pratica" e a pomada continuou em "Sem dose estruturada".
# Eram dois caminhos diferentes de saída antecipada, ambos irrelevantes para
# formas tópicas. Estes testes exercem build_clinical_plan de ponta a ponta.

import os

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

from app import app as flask_app, db  # noqa: E402
from models import (  # noqa: E402
    Animal, Clinica, Consulta, Medicamento, ProtocoloClinico,
    ProtocoloClinicoMedicamento, User, Veterinario,
)
from models.base import ApresentacaoMedicamento, Species  # noqa: E402
from services.clinical_plan import READY, build_clinical_plan  # noqa: E402


def _cenario(nome_medicamento, dosagem_texto, *, com_apresentacao_incompativel=False):
    """Monta consulta + protocolo com um único medicamento tópico."""
    db.drop_all()
    db.create_all()
    clinic = Clinica(id=1, nome="Clinica Dermato")
    tutor = User(id=1, name="Tutor", email="tutor-topico@test")
    tutor.set_password("x")
    vet_user = User(id=2, name="Vet", email="vet-topico@test", worker="veterinario")
    vet_user.set_password("x")
    vet = Veterinario(id=1, user_id=vet_user.id, crmv="123", clinica_id=clinic.id)
    species = Species(id=1, name="Cachorro")
    animal = Animal(id=1, name="Nina", user_id=tutor.id, clinica_id=clinic.id,
                    species=species, peso=7.2)
    consulta = Consulta(id=1, animal=animal, created_by=vet_user.id,
                        clinica_id=clinic.id, status="in_progress")
    med = Medicamento(id=50, nome=nome_medicamento, classificacao="Dermatologico",
                      via_administracao="Topica", created_by=vet_user.id)
    db.session.add_all([clinic, tutor, vet_user, vet, species, animal, consulta, med])
    db.session.flush()
    if com_apresentacao_incompativel:
        # Exatamente o dado que gerava "8 gotas - 50 g pomada": apresentação em
        # pomada pendurada num produto que é frasco de shampoo.
        db.session.add(ApresentacaoMedicamento(
            id=1, medicamento=med, forma="Pomada", concentracao="50 g",
            concentracao_valor=50, concentracao_unidade="g",
            volume_valor=50, volume_unidade="g",
            nome_comercial="Furanil Pomada", fabricante="Vetnil",
        ))
    protocolo = ProtocoloClinico(id=1, nome="Protocolo Inicial para Dermatites",
                                 suspeita_principal="dermatite",
                                 clinica_id=clinic.id, created_by=vet_user.id)
    db.session.add(protocolo)
    db.session.flush()
    db.session.add(ProtocoloClinicoMedicamento(
        protocolo_id=protocolo.id, nome_medicamento=nome_medicamento,
        medicamento=med, dosagem_texto=dosagem_texto, prioridade=1,
    ))
    db.session.commit()
    return consulta, protocolo


def test_shampoo_sem_apresentacao_compativel_fica_pronto(app):
    """Antes: "Dose calculada sem apresentacao pratica" + "7,5 gota(s)"."""
    with flask_app.app_context():
        consulta, protocolo = _cenario(
            "Shampoo de clorexidina - 0,20%, frasco (500mL)",
            "Aplicar sobre a pelagem",
            com_apresentacao_incompativel=True,
        )
        plan = build_clinical_plan(consulta, protocolo, session=db.session)
        med = plan["medications"][0]

        assert med["status"] == READY, med.get("status_label")
        assert med["calculation"]["dose_pratica"] == _INSTRUCAO_SHAMPOO
        assert "gota" not in med["calculation"]["posologia_pratica"]
        assert med["draft_prescription"]["dosagem"] == _INSTRUCAO_SHAMPOO


def test_pomada_sem_dose_estruturada_fica_pronta(app):
    """Antes: saía cedo em "Sem dose estruturada" e nunca via a instrução."""
    with flask_app.app_context():
        consulta, protocolo = _cenario(
            "Cetoconazol 20mg/g + Dipropionato de Betametasona 0,64mg/g Generico C",
            "Aplicar uma camada fina sobre a area afetada",
        )
        plan = build_clinical_plan(consulta, protocolo, session=db.session)
        med = plan["medications"][0]

        assert med["status"] == READY, med.get("status_label")
        assert med["calculation"]["dose_pratica"] == _instrucao_pomada()
        assert "12 (doze)" in med["calculation"]["posologia_pratica"]
        assert med["draft_prescription"]["dosagem"] == _instrucao_pomada()
