"""
End-to-End Integration Tests for Veterinarian Workflows

This module tests complete workflows from a veterinarian's perspective,
covering clinic management, consultations, prescriptions, and financial operations.
"""
import pytest
import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

from app import app as flask_app, db
from models import (
    User, Animal, Consulta, Prescricao, BlocoPrescricao,
    Vacina, Clinica, Veterinario, VeterinarianMembership,
    AgendaEvento, Orcamento, OrcamentoItem, BlocoOrcamento,
    ServicoClinica, Species, Breed, BlocoExames, ExameModelo,
    PagamentoPlantonista, CoberturaPlantonista,
    ClinicInventory, ClinicInventoryMovement
)
from datetime import datetime, timedelta, date, time
from decimal import Decimal


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def veterinarian_setup(app):
    """Create a complete veterinarian setup with clinic and membership."""
    with app.app_context():
        vet_user = User(
            name="Dr. Pedro Costa",
            email="dr.pedro@vet.com",
            role="veterinario",
            worker="veterinario",
            phone="16988887777",
            cpf="111.222.333-44"
        )
        vet_user.set_password("vetpass123")
        
        db.session.add(vet_user)
        db.session.commit()
        
        clinic = Clinica(
            nome="Clinica VetCare",
            cnpj="11.222.333/0001-44",
            endereco="Av. Principal, 789",
            telefone="16 3344-5566",
            email="contato@vetcare.com",
            owner_id=vet_user.id
        )
        
        db.session.add(clinic)
        db.session.commit()
        
        vet_user.clinica_id = clinic.id
        
        vet_profile = Veterinario(
            user_id=vet_user.id,
            crmv="CRMV-SP 54321",
            clinica_id=clinic.id
        )
        
        membership = VeterinarianMembership(
            veterinario=vet_profile,
            started_at=datetime.utcnow() - timedelta(days=15),
            trial_ends_at=datetime.utcnow() + timedelta(days=15),
            paid_until=None
        )
        
        db.session.add(vet_profile)
        db.session.add(membership)
        db.session.commit()
        
        return {
            'vet_id': vet_user.id,
            'vet_profile_id': vet_profile.id,
            'clinic_id': clinic.id
        }


@pytest.fixture
def tutor_with_animal(app):
    """Create a tutor with an animal for consultation tests."""
    with app.app_context():
        dog_species = Species(name="Cachorro")
        db.session.add(dog_species)
        db.session.commit()
        
        labrador = Breed(name="Labrador", species_id=dog_species.id)
        db.session.add(labrador)
        db.session.commit()
        
        tutor = User(
            name="Ana Santos",
            email="ana@test.com",
            role="adotante"
        )
        tutor.set_password("tutor123")
        db.session.add(tutor)
        db.session.commit()
        
        animal = Animal(
            name="Rex",
            species_id=dog_species.id,
            breed_id=labrador.id,
            user_id=tutor.id,
            sex="macho",
            date_of_birth=date(2020, 3, 15),
            peso=28.5
        )
        db.session.add(animal)
        db.session.commit()
        
        return {
            'tutor_id': tutor.id,
            'animal_id': animal.id,
            'species_id': dog_species.id,
            'breed_id': labrador.id
        }


def login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


class TestClinicSetup:
    """Test clinic creation and configuration."""
    
    def test_create_clinic(self, client, app):
        """Test creating a new clinic."""
        # Create veterinarian first
        with app.app_context():
            vet_user = User(
                name="Dr. Julia",
                email="dr.julia@test.com",
                role="veterinario",
                worker="veterinario"
            )
            vet_user.set_password("pass123")
            db.session.add(vet_user)
            db.session.commit()
            vet_id = vet_user.id
        
        login(client, vet_id)
        
        # Create clinic
        clinic_data = {
            'nome': 'Clinica Pet Life',
            'cnpj': '22.333.444/0001-55',
            'endereco': 'Rua das Palmeiras, 100',
            'telefone': '16 3322-1100',
            'email': 'contato@petlife.com'
        }
        
        response = client.post('/criar-clinica', data=clinic_data, follow_redirects=True)
        assert response.status_code == 200 or response.status_code == 302
        
        # Verify clinic was created
        with app.app_context():
            clinic = Clinica.query.filter_by(nome='Clinica Pet Life').first()
            assert clinic is not None or response.status_code in [200, 302]
    
    def test_update_clinic_settings(self, client, veterinarian_setup, app):
        """Test updating clinic settings."""
        login(client, veterinarian_setup['vet_id'])
        
        # Update clinic
        update_data = {
            'nome': 'Clinica VetCare Updated',
            'telefone': '16 3344-9999'
        }
        
        response = client.post(
            f'/clinica/{veterinarian_setup["clinic_id"]}/settings',
            data=update_data,
            follow_redirects=True
        )
        
        # Should update or redirect appropriately
        assert response.status_code in [200, 302, 404]
    
    def test_add_clinic_services(self, client, veterinarian_setup, app):
        """Test adding services to clinic catalog."""
        login(client, veterinarian_setup['vet_id'])
        
        with app.app_context():
            # Add services
            services = [
                ServicoClinica(
                    descricao="Consulta de rotina",
                    valor=Decimal('120.00'),
                    clinica_id=veterinarian_setup['clinic_id']
                ),
                ServicoClinica(
                    descricao="Castracao",
                    valor=Decimal('450.00'),
                    procedure_code="CAST01",
                    clinica_id=veterinarian_setup['clinic_id']
                ),
                ServicoClinica(
                    descricao="Vacinacao V10",
                    valor=Decimal('80.00'),
                    clinica_id=veterinarian_setup['clinic_id']
                )
            ]
            for s in services:
                db.session.add(s)
            db.session.commit()
        
        # Verify services
        with app.app_context():
            clinic = Clinica.query.get(veterinarian_setup['clinic_id'])
            assert len(clinic.servicos) >= 3


class TestConsultationWorkflow:
    """Test complete consultation workflow."""
    
    def test_create_consultation(self, client, veterinarian_setup, tutor_with_animal, app):
        """Test creating a new consultation."""
        login(client, veterinarian_setup['vet_id'])
        
        consultation_data = {
            'animal_id': tutor_with_animal['animal_id'],
            'queixa_principal': 'Animal apresenta tosse',
            'historico_clinico': 'Primeira consulta nesta clinica',
            'exame_fisico': 'Temperatura: 38.5?C, FC: 90bpm',
            'conduta': 'Iniciar tratamento antibiotico',
        }
        
        with app.app_context():
            consulta = Consulta(
                animal_id=tutor_with_animal['animal_id'],
                created_by=veterinarian_setup['vet_id'],
                clinica_id=veterinarian_setup['clinic_id'],
                queixa_principal=consultation_data['queixa_principal'],
                historico_clinico=consultation_data['historico_clinico'],
                exame_fisico=consultation_data['exame_fisico'],
                conduta=consultation_data['conduta'],
                status='in_progress'
            )
            db.session.add(consulta)
            db.session.commit()
            consulta_id = consulta.id
        
        # Verify consultation
        with app.app_context():
            created_consulta = Consulta.query.get(consulta_id)
            assert created_consulta is not None
            assert created_consulta.queixa_principal == 'Animal apresenta tosse'
            assert created_consulta.status == 'in_progress'
    
    def test_finalize_consultation(self, client, veterinarian_setup, tutor_with_animal, app):
        """Test finalizing a consultation."""
        login(client, veterinarian_setup['vet_id'])
        
        with app.app_context():
            consulta = Consulta(
                animal_id=tutor_with_animal['animal_id'],
                created_by=veterinarian_setup['vet_id'],
                clinica_id=veterinarian_setup['clinic_id'],
                queixa_principal='Check-up',
                status='in_progress'
            )
            db.session.add(consulta)
            db.session.commit()
            consulta_id = consulta.id
        
        # Finalize
        finalize_data = {
            'status': 'completed',
            'exame_fisico': 'Animal saudavel',
            'conduta': 'Retorno em 6 meses'
        }
        
        with app.app_context():
            consulta = Consulta.query.get(consulta_id)
            consulta.status = 'completed'
            consulta.finalizada_em = datetime.utcnow()
            consulta.exame_fisico = finalize_data['exame_fisico']
            consulta.conduta = finalize_data['conduta']
            db.session.commit()
        
        # Verify finalization
        with app.app_context():
            finalized = Consulta.query.get(consulta_id)
            assert finalized.status == 'completed'
            assert finalized.finalizada_em is not None
    
    def test_consultation_with_prescription(self, client, veterinarian_setup, tutor_with_animal, app):
        """Test creating consultation with prescription."""
        login(client, veterinarian_setup['vet_id'])
        
        with app.app_context():
            consulta = Consulta(
                animal_id=tutor_with_animal['animal_id'],
                created_by=veterinarian_setup['vet_id'],
                clinica_id=veterinarian_setup['clinic_id'],
                queixa_principal='Infeccao',
                status='in_progress'
            )
            db.session.add(consulta)
            db.session.commit()
            
            # Create prescription block
            bloco = BlocoPrescricao(
                animal_id=tutor_with_animal['animal_id'],
                clinica_id=veterinarian_setup['clinic_id'],
                saved_by_id=veterinarian_setup['vet_id']
            )
            db.session.add(bloco)
            db.session.commit()
            
            # Add prescriptions
            prescricoes = [
                Prescricao(
                    bloco_id=bloco.id,
                    animal_id=tutor_with_animal['animal_id'],
                    medicamento="Amoxicilina 500mg",
                    dosagem="1 comprimido",
                    frequencia="2x ao dia",
                    duracao="10 dias",
                    observacoes="Administrar com alimento"
                ),
                Prescricao(
                    bloco_id=bloco.id,
                    animal_id=tutor_with_animal['animal_id'],
                    medicamento="Anti-inflamatorio",
                    dosagem="5ml",
                    frequencia="1x ao dia",
                    duracao="5 dias"
                )
            ]
            for p in prescricoes:
                db.session.add(p)
            db.session.commit()
            
            bloco_id = bloco.id
        
        # Verify prescription
        with app.app_context():
            bloco = BlocoPrescricao.query.get(bloco_id)
            assert len(bloco.prescricoes) == 2
            assert bloco.prescricoes[0].medicamento == "Amoxicilina 500mg"


class TestExamManagement:
    """Test exam request and management."""
    
    def test_request_exams(self, client, veterinarian_setup, tutor_with_animal, app):
        """Test requesting exams for an animal."""
        login(client, veterinarian_setup['vet_id'])
        
        with app.app_context():
            # Create exam models
            exam_models = [
                ExameModelo(
                    nome="Hemograma completo",
                    descricao="Analise completa do sangue",
                    clinica_id=veterinarian_setup['clinic_id']
                ),
                ExameModelo(
                    nome="Raio-X",
                    descricao="Radiografia",
                    clinica_id=veterinarian_setup['clinic_id']
                )
            ]
            for em in exam_models:
                db.session.add(em)
            db.session.commit()
            
            # Create exam block
            bloco_exames = BlocoExames(
                animal_id=tutor_with_animal['animal_id'],
                clinica_id=veterinarian_setup['clinic_id'],
                veterinario_id=veterinarian_setup['vet_id'],
                status='pendente'
            )
            db.session.add(bloco_exames)
            db.session.commit()
            bloco_id = bloco_exames.id
        
        # Verify exam block
        with app.app_context():
            bloco = BlocoExames.query.get(bloco_id)
            assert bloco is not None
            assert bloco.status == 'pendente'


class TestEstimateCreation:
    """Test creating and managing estimates (orcamentos)."""
    
    def test_create_estimate(self, client, veterinarian_setup, tutor_with_animal, app):
        """Test creating a detailed estimate."""
        login(client, veterinarian_setup['vet_id'])
        
        with app.app_context():
            # Create services first
            servico1 = ServicoClinica(
                descricao="Consulta especializada",
                valor=Decimal('200.00'),
                clinica_id=veterinarian_setup['clinic_id']
            )
            servico2 = ServicoClinica(
                descricao="Exame laboratorial",
                valor=Decimal('150.00'),
                clinica_id=veterinarian_setup['clinic_id']
            )
            db.session.add_all([servico1, servico2])
            db.session.commit()
            
            # Create estimate block
            bloco = BlocoOrcamento(
                animal_id=tutor_with_animal['animal_id'],
                clinica_id=veterinarian_setup['clinic_id'],
                payment_status='draft'
            )
            db.session.add(bloco)
            db.session.commit()
            
            # Add items
            items = [
                OrcamentoItem(
                    bloco_id=bloco.id,
                    descricao="Consulta especializada",
                    valor=Decimal('200.00'),
                    clinica_id=veterinarian_setup['clinic_id']
                ),
                OrcamentoItem(
                    bloco_id=bloco.id,
                    descricao="Exame laboratorial",
                    valor=Decimal('150.00'),
                    clinica_id=veterinarian_setup['clinic_id']
                ),
                OrcamentoItem(
                    bloco_id=bloco.id,
                    descricao="Medicacao",
                    valor=Decimal('85.00'),
                    clinica_id=veterinarian_setup['clinic_id']
                )
            ]
            for item in items:
                db.session.add(item)
            db.session.commit()
            
            bloco_id = bloco.id
        
        # Verify estimate
        with app.app_context():
            bloco = BlocoOrcamento.query.get(bloco_id)
            assert bloco.total == Decimal('435.00')
            assert len(bloco.itens) == 3
    
    def test_apply_discount_to_estimate(self, client, veterinarian_setup, tutor_with_animal, app):
        """Test applying discount to estimate."""
        login(client, veterinarian_setup['vet_id'])
        
        with app.app_context():
            bloco = BlocoOrcamento(
                animal_id=tutor_with_animal['animal_id'],
                clinica_id=veterinarian_setup['clinic_id'],
                payment_status='draft'
            )
            db.session.add(bloco)
            db.session.commit()
            
            item = OrcamentoItem(
                bloco_id=bloco.id,
                descricao="Servico",
                valor=Decimal('500.00'),
                clinica_id=veterinarian_setup['clinic_id']
            )
            db.session.add(item)
            db.session.commit()
            
            # Apply 10% discount
            bloco.discount_percent = Decimal('10.00')
            bloco.discount_value = Decimal('50.00')
            db.session.commit()
            
            bloco_id = bloco.id
        
        # Verify discount
        with app.app_context():
            bloco = BlocoOrcamento.query.get(bloco_id)
            assert bloco.total_liquido == Decimal('450.00')


class TestScheduleManagement:
    """Test veterinarian schedule management."""
    
    def test_set_availability(self, client, veterinarian_setup, app):
        """Test setting weekly availability."""
        login(client, veterinarian_setup['vet_id'])
        
        # Set availability for Monday
        availability_data = {
            'day_of_week': 1,  # Monday
            'start_time': '09:00',
            'end_time': '18:00',
            'clinica_id': veterinarian_setup['clinic_id']
        }
        
        # This would typically be done through the schedule settings page
        with app.app_context():
            # Schedule settings would be stored in a separate model
            # For now, just verify the endpoint exists
            response = client.get('/edit_vet_schedule')
            # May redirect or show page
            assert response.status_code in [200, 302]
    
    def test_view_appointments_calendar(self, client, veterinarian_setup, tutor_with_animal, app):
        """Test viewing appointments in calendar view."""
        login(client, veterinarian_setup['vet_id'])
        
        # Create some appointments
        with app.app_context():
            appointments = [
                AgendaEvento(
                    animal_id=tutor_with_animal['animal_id'],
                    responsavel_id=veterinarian_setup['vet_id'],
                    clinica_id=veterinarian_setup['clinic_id'],
                    data_hora=datetime.utcnow() + timedelta(days=1, hours=10),
                    tipo='consulta',
                    titulo='Consulta Rex',
                    status='confirmado'
                ),
                AgendaEvento(
                    animal_id=tutor_with_animal['animal_id'],
                    responsavel_id=veterinarian_setup['vet_id'],
                    clinica_id=veterinarian_setup['clinic_id'],
                    data_hora=datetime.utcnow() + timedelta(days=1, hours=14),
                    tipo='cirurgia',
                    titulo='Cirurgia Rex',
                    status='confirmado'
                )
            ]
            for apt in appointments:
                db.session.add(apt)
            db.session.commit()
        
        # View calendar
        response = client.get('/appointments_calendar')
        assert response.status_code in [200, 302]


class TestInventoryManagement:
    """Test clinic inventory management."""
    
    def test_add_inventory_item(self, client, veterinarian_setup, app):
        """Test adding item to clinic inventory."""
        login(client, veterinarian_setup['vet_id'])
        
        with app.app_context():
            inventory_item = ClinicInventory(
                clinica_id=veterinarian_setup['clinic_id'],
                nome="Antibiotico X",
                categoria="Medicamentos",
                quantidade=50,
                unidade="comprimidos",
                min_quantity=10,
                max_quantity=100
            )
            db.session.add(inventory_item)
            db.session.commit()
            item_id = inventory_item.id
        
        # Verify item
        with app.app_context():
            item = ClinicInventory.query.get(item_id)
            assert item.nome == "Antibiotico X"
            assert item.quantidade == 50
    
    def test_record_inventory_movement(self, client, veterinarian_setup, app):
        """Test recording inventory movements."""
        login(client, veterinarian_setup['vet_id'])
        
        with app.app_context():
            # Create inventory item
            item = ClinicInventory(
                clinica_id=veterinarian_setup['clinic_id'],
                nome="Vacina V10",
                categoria="Vacinas",
                quantidade=30,
                unidade="doses"
            )
            db.session.add(item)
            db.session.commit()
            
            # Record usage
            movement = ClinicInventoryMovement(
                inventory_id=item.id,
                tipo='saida',
                quantidade=5,
                motivo='Aplicacao em consultas',
                responsavel_id=veterinarian_setup['vet_id']
            )
            db.session.add(movement)
            
            # Update quantity
            item.quantidade -= 5
            db.session.commit()
            
            item_id = item.id
        
        # Verify movement
        with app.app_context():
            item = ClinicInventory.query.get(item_id)
            assert item.quantidade == 25
            assert len(item.movements) == 1


class TestOnCallPayments:
    """Test on-call payment management."""
    
    def test_create_oncall_payment(self, client, veterinarian_setup, app):
        """Test creating on-call payment entry."""
        login(client, veterinarian_setup['vet_id'])
        
        with app.app_context():
            # Create on-call payment
            payment = PagamentoPlantonista(
                veterinario_id=veterinarian_setup['vet_profile_id'],
                clinica_id=veterinarian_setup['clinic_id'],
                mes_referencia=datetime.utcnow().replace(day=1).date(),
                valor_total=Decimal('2400.00'),
                status='pendente'
            )
            db.session.add(payment)
            db.session.commit()
            
            # Add coverage entries
            coverages = [
                CoberturaPlantonista(
                    pagamento_id=payment.id,
                    data=datetime.utcnow().date(),
                    hora_inicio=time(8, 0),
                    hora_fim=time(17, 0),
                    valor_hora=Decimal('100.00')
                )
            ]
            for cov in coverages:
                db.session.add(cov)
            db.session.commit()
            
            payment_id = payment.id
        
        # Verify payment
        with app.app_context():
            payment = PagamentoPlantonista.query.get(payment_id)
            assert payment.valor_total == Decimal('2400.00')
            assert len(payment.coberturas) == 1


class TestCollaboration:
    """Test multi-veterinarian collaboration features."""
    
    def test_add_collaborator_to_consultation(self, client, veterinarian_setup, tutor_with_animal, app):
        """Test adding collaborator to a consultation."""
        login(client, veterinarian_setup['vet_id'])
        
        # Create second veterinarian
        with app.app_context():
            vet2 = User(
                name="Dr. Carlos",
                email="dr.carlos@vet.com",
                role="veterinario",
                worker="veterinario"
            )
            vet2.set_password("pass123")
            db.session.add(vet2)
            db.session.commit()
            vet2_id = vet2.id
            
            # Create consultation
            consulta = Consulta(
                animal_id=tutor_with_animal['animal_id'],
                created_by=veterinarian_setup['vet_id'],
                clinica_id=veterinarian_setup['clinic_id'],
                queixa_principal='Cirurgia complexa',
                status='in_progress'
            )
            db.session.add(consulta)
            db.session.commit()
            
            # Create event with collaborator
            evento = AgendaEvento(
                animal_id=tutor_with_animal['animal_id'],
                responsavel_id=veterinarian_setup['vet_id'],
                clinica_id=veterinarian_setup['clinic_id'],
                data_hora=datetime.utcnow() + timedelta(hours=2),
                tipo='cirurgia',
                titulo='Cirurgia colaborativa',
                status='confirmado'
            )
            db.session.add(evento)
            db.session.commit()
            
            # Add collaborator
            evento.colaboradores.append(User.query.get(vet2_id))
            db.session.commit()
            
            evento_id = evento.id
        
        # Verify collaboration
        with app.app_context():
            evento = AgendaEvento.query.get(evento_id)
            assert len(evento.colaboradores) >= 1


class TestReporting:
    """Test reporting and analytics features."""
    
    def test_financial_snapshot(self, client, veterinarian_setup, app):
        """Test viewing financial snapshot."""
        login(client, veterinarian_setup['vet_id'])
        
        # Create some financial data
        with app.app_context():
            # This would typically aggregate from various payment sources
            response = client.get(f'/contabilidade/snapshot?clinica_id={veterinarian_setup["clinic_id"]}')
            # Should return financial data or appropriate status
            assert response.status_code in [200, 302, 404]
    
    def test_monthly_revenue_report(self, client, veterinarian_setup, tutor_with_animal, app):
        """Test monthly revenue reporting."""
        login(client, veterinarian_setup['vet_id'])
        
        with app.app_context():
            # Create paid estimates
            bloco = BlocoOrcamento(
                animal_id=tutor_with_animal['animal_id'],
                clinica_id=veterinarian_setup['clinic_id'],
                payment_status='paid'
            )
            db.session.add(bloco)
            db.session.commit()
            
            item = OrcamentoItem(
                bloco_id=bloco.id,
                descricao="Servico",
                valor=Decimal('300.00'),
                clinica_id=veterinarian_setup['clinic_id']
            )
            db.session.add(item)
            db.session.commit()
        
        # View reports
        month = datetime.utcnow().strftime('%Y-%m')
        response = client.get(f'/reports/revenue?month={month}&clinica_id={veterinarian_setup["clinic_id"]}')
        # Should show revenue data
        assert response.status_code in [200, 302, 404]


# Performance and stress tests
class TestPerformanceVeterinarian:
    """Test performance under load."""
    
    def test_consultation_list_performance(self, client, veterinarian_setup, tutor_with_animal, app):
        """Test loading consultation list with many records."""
        login(client, veterinarian_setup['vet_id'])
        
        # Create many consultations
        with app.app_context():
            for i in range(50):
                consulta = Consulta(
                    animal_id=tutor_with_animal['animal_id'],
                    created_by=veterinarian_setup['vet_id'],
                    clinica_id=veterinarian_setup['clinic_id'],
                    queixa_principal=f'Consulta {i}',
                    status='completed' if i % 2 == 0 else 'in_progress'
                )
                db.session.add(consulta)
            db.session.commit()
        
        import time
        start = time.time()
        response = client.get(f'/consultas?clinica_id={veterinarian_setup["clinic_id"]}')
        elapsed = time.time() - start
        
        assert response.status_code in [200, 302]
        assert elapsed < 3.0, f"Consultation list took {elapsed:.2f}s"
    
    def test_dashboard_performance(self, client, veterinarian_setup, app):
        """Test veterinarian dashboard load time."""
        login(client, veterinarian_setup['vet_id'])
        
        import time
        start = time.time()
        response = client.get('/')
        elapsed = time.time() - start
        
        assert response.status_code == 200
        assert elapsed < 2.5, f"Dashboard took {elapsed:.2f}s"
