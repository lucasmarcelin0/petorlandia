"""Ficha do animal: cabeçalho, resumo de saúde, atalhos e permissões.

A ficha ganhou o visual da ficha do tutor. Estes testes garantem que nenhuma
função antiga sumiu (selo, carteirinha, documentos, falecimento) e que cada
perfil vê só o que pode usar.
"""

import os
import sys
from datetime import date, timedelta

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db  # noqa: E402
from models import Animal, Breed, Consulta, Species, User, Vacina  # noqa: E402
from test_intern_start_consulta import _build_clinic, client, login  # noqa: E402,F401
from time_utils import utcnow  # noqa: E402


def _preparar(*, telefone='+5516991234567'):
    _build_clinic()
    tutor = db.session.get(User, 1)
    tutor.clinica_id = 1
    tutor.phone = telefone
    db.session.add(Species(id=1, name='Cachorro'))
    db.session.flush()
    db.session.add(Breed(id=1, name='Pit Bull', species_id=1))
    rex = db.session.get(Animal, 1)
    rex.species_id = 1
    rex.breed_id = 1
    rex.sex = 'Fêmea'
    rex.peso = 18.4
    rex.microchip_number = '985112003456789'
    db.session.commit()


def _html(client, animal_id=1):
    resp = client.get(f'/animal/{animal_id}/ficha')
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_veterinario_ve_cabecalho_atalhos_e_dados(client, monkeypatch):
    with flask_app.app_context():
        _preparar()
        login(monkeypatch, db.session.get(User, 2))
        html = _html(client)

    assert 'Ficha de Rex' in html
    assert 'Cachorro · Pit Bull' in html
    assert '18,4 kg' in html
    assert 'Castrad' in html  # campo sempre presente nos dados
    assert '985112003456789' in html
    # Atalhos: consulta, edição real do cadastro e WhatsApp do tutor.
    assert 'Nova consulta' in html
    assert '/ficha_tutor/1?editar=1#animais' in html
    assert 'https://wa.me/5516991234567' in html
    # O antigo "Editar ficha" levava a uma tela que não salvava nada.
    assert '/animal/1/editar_ficha' not in html
    # Documentos ficam numa aba própria para o profissional.
    assert 'id="documentos-tab"' in html
    assert 'Ver termos' in html
    assert 'Tutor responsável' in html
    assert 'Ver ficha do tutor' in html
    # Status (falecimento) continua disponível, recolhido.
    assert 'Marcar como falecido' in html
    assert 'None' not in html.split('<main', 1)[-1].split('</main>', 1)[0]


def test_tutor_ve_editar_dados_e_carteirinha_sem_documentos(client, monkeypatch):
    with flask_app.app_context():
        _preparar()
        login(monkeypatch, db.session.get(User, 1))
        html = _html(client)

    assert '/editar_animal/1' in html or '/animal/1/editar' in html
    assert 'Editar dados' in html
    assert 'Carteirinha digital' in html
    assert 'id="documentos-tab"' not in html
    assert 'Marcar como falecido' not in html
    # O tutor não precisa de atalho de WhatsApp para si mesmo.
    assert 'ficha-atalho--whatsapp' not in html
    assert 'Nova consulta' not in html


def test_resumo_mostra_ultima_consulta_e_vacinas(client, monkeypatch):
    with flask_app.app_context():
        _preparar()
        hoje = date.today()
        db.session.add_all([
            Consulta(animal_id=1, created_by=2, clinica_id=1, status='finalizada',
                     created_at=utcnow() - timedelta(days=3)),
            Vacina(animal_id=1, nome='V10', aplicada=True, aplicada_em=hoje - timedelta(days=200)),
            Vacina(animal_id=1, nome='Antirrábica', aplicada=False, aplicada_em=hoje - timedelta(days=5)),
            Vacina(animal_id=1, nome='Giárdia', aplicada=False, aplicada_em=hoje - timedelta(days=2)),
            Vacina(animal_id=1, nome='Gripe', aplicada=False, aplicada_em=hoje + timedelta(days=10)),
        ])
        db.session.commit()
        login(monkeypatch, db.session.get(User, 2))
        html = _html(client)

    assert 'Última consulta' in html
    assert '2 atrasadas' in html
    assert 'ficha-resumo__item--alerta' in html
    assert (hoje + timedelta(days=10)).strftime('%d/%m/%Y') in html
    assert 'Gripe' in html


def test_resumo_sem_registros(client, monkeypatch):
    with flask_app.app_context():
        _preparar()
        login(monkeypatch, db.session.get(User, 2))
        html = _html(client)

    assert 'Sem registro' in html
    assert 'Nenhuma agendada' in html
    assert 'ficha-resumo__item--alerta' not in html


def test_animal_sem_nome_nunca_mostra_none(client, monkeypatch):
    with flask_app.app_context():
        _preparar()
        db.session.get(Animal, 1).name = None
        db.session.commit()
        login(monkeypatch, db.session.get(User, 2))
        html = _html(client)

    assert 'Ficha de animal sem nome' in html
    assert 'Cadastro sem nome' in html
    assert 'Ficha de None' not in html


def test_sem_telefone_nao_mostra_atalho_de_contato(client, monkeypatch):
    with flask_app.app_context():
        _preparar(telefone='')
        login(monkeypatch, db.session.get(User, 2))
        html = _html(client)

    assert 'ficha-atalho--whatsapp' not in html
    assert 'ficha-atalho--ligar' not in html
    assert 'Telefone não informado' in html


def test_animal_removido_oferece_restaurar_ao_tutor(client, monkeypatch):
    with flask_app.app_context():
        _preparar()
        db.session.get(Animal, 1).removido_em = utcnow()
        db.session.commit()
        login(monkeypatch, db.session.get(User, 1))
        html = _html(client)
        assert 'O histórico está preservado.' in html
        assert '/animal/1/restaurar' in html

        resp = client.post('/animal/1/restaurar')
        assert resp.status_code in (302, 303)
        db.session.expire_all()
        assert db.session.get(Animal, 1).removido_em is None


def test_animal_falecido_aparece_para_tutor_e_vet_pode_reverter(client, monkeypatch):
    with flask_app.app_context():
        _preparar()
        rex = db.session.get(Animal, 1)
        rex.is_alive = False
        rex.falecido_em = utcnow()
        db.session.commit()

        login(monkeypatch, db.session.get(User, 1))
        html_tutor = _html(client)
        assert 'Este animal foi marcado como falecido' in html_tutor
        assert 'Falecida' in html_tutor
        assert 'Reverter falecimento' not in html_tutor

        login(monkeypatch, db.session.get(User, 2))
        html_vet = _html(client)
        assert 'Reverter falecimento' in html_vet
        assert 'Deletar definitivamente' in html_vet
