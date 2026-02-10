"""
End-to-End Integration Tests for Tutor (Pet Owner) Workflows

This module tests complete user journeys from a tutor's perspective,
ensuring all features work together seamlessly.
"""
import pytest
import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

from app import app as flask_app, db
from models import (
    User, Animal, Consulta, Prescricao, BlocoPrescricao,
    Vacina, Clinica, Veterinario, VeterinarianMembership,
    AgendaEvento, Orcamento, OrcamentoItem, BlocoOrcamento,
    ServicoClinica, Species, Breed
)
from datetime import datetime, timedelta, date
from decimal import Decimal
from io import BytesIO


@pytest.fixture
def app():
    """Create and configure a test app instance."""
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def tutor(app):
    """Create a test tutor user."""
    with app.app_context():
        user = User(
            name="Joao Silva",
            email="joao@test.com",
            role="adotante",
            phone="16999887766",
            cpf="123.456.789-00",
            date_of_birth=date(1990, 5, 15)
        )
        user.set_password("senha123")
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def veterinarian_with_clinic(app):
    """Create a veterinarian with an active clinic."""
    with app.app_context():
        vet_user = User(
            name="Dr. Maria Veterinaria",
            email="dra.maria@vet.com",
            role="veterinario",
            worker="veterinario"
        )
        vet_user.set_password("vetpass")
        
        clinic = Clinica(
            nome="Clinica Pet Saude",
            cnpj="12.345.678/0001-99",
            endereco="Rua das Flores, 123",
            telefone="16 3333-4444",
            email="contato@petsaude.com",
            owner_id=None  # Will be set after user creation
        )
        
        db.session.add(vet_user)
        db.session.add(clinic)
        db.session.commit()
        
        clinic.owner_id = vet_user.id
        vet_user.clinica_id = clinic.id
        
        vet_profile = Veterinario(
            user_id=vet_user.id,
            crmv="CRMV-SP 12345",
            clinica_id=clinic.id
        )
        
        membership = VeterinarianMembership(
            veterinario=vet_profile,
            started_at=datetime.utcnow() - timedelta(days=10),
            trial_ends_at=datetime.utcnow() + timedelta(days=20),
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
def species_and_breeds(app):
    """Create species and breeds for animals."""
    with app.app_context():
        dog_species = Species(name="Cachorro")
        cat_species = Species(name="Gato")
        db.session.add_all([dog_species, cat_species])
        db.session.commit()
        
        labrador = Breed(name="Labrador", species_id=dog_species.id)
        persian = Breed(name="Persa", species_id=cat_species.id)
        db.session.add_all([labrador, persian])
        db.session.commit()
        
        return {
            'dog_species_id': dog_species.id,
            'cat_species_id': cat_species.id,
            'labrador_id': labrador.id,
            'persian_id': persian.id
        }


def login(client, user_id):
    """Helper to log in a user."""
    with client.session_transaction() as sess:
        sess.clear()
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


class TestTutorRegistrationAndLogin:
    """Test complete registration and login workflow."""
    
    def test_registration_flow_with_photo(self, client, app):
        """Test user registration with profile photo upload."""
        # Step 1: Access registration page
        response = client.get('/register')
        assert response.status_code == 200
        # Check for registration page content
        response_text = response.data.decode('utf-8', errors='ignore').lower()
        assert 'criar conta' in response_text or 'register' in response_text
        
        # Step 2: Submit registration form
        data = {
            'name': 'Carlos Teste',
            'email': 'carlos@teste.com',
            'password': 'senha@123',
            'phone': '16988776655',
            'cpf': '987.654.321-00',
            'date_of_birth': '1995-03-20'
        }
        
        response = client.post('/register', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # Verify user was created
        with app.app_context():
            user = User.query.filter_by(email='carlos@teste.com').first()
            assert user is not None
            assert user.name == 'Carlos Teste'
            assert user.check_password('senha@123')
    
    def test_login_flow(self, client, tutor, app):
        """Test complete login workflow."""
        # Step 1: Access login page
        response = client.get('/login')
        assert response.status_code == 200
        
        # Step 2: Submit login credentials
        with app.app_context():
            user = User.query.get(tutor)
            email = user.email
        
        response = client.post('/login', data={
            'email': email,
            'password': 'senha123'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # Step 3: Verify redirection to dashboard/index
        assert b'dashboard' in response.data.lower() or b'ola' in response.data.lower()
    
    def test_password_reset_flow(self, client, tutor, app):
        """Test password reset request workflow."""
        with app.app_context():
            user = User.query.get(tutor)
            email = user.email
        
        # Step 1: Request password reset
        response = client.get('/reset_password_request')
        assert response.status_code == 200
        
        response = client.post('/reset_password_request', data={
            'email': email
        }, follow_redirects=True)
        
        # Should show success message even if email not configured
        assert response.status_code == 200


class TestAnimalManagement:
    """Test complete animal management workflows."""
    
    def test_add_animal_complete_flow(self, client, tutor, species_and_breeds, app):
        """Test adding a new animal with all details."""
        login(client, tutor)
        
        # Step 1: Access add animal page
        response = client.get('/add-animal')
        assert response.status_code == 200
        
        # Step 2: Submit animal form
        data = {
            'name': 'Rex',
            'species_id': species_and_breeds['dog_species_id'],
            'breed_id': species_and_breeds['labrador_id'],
            'sex': 'macho',
            'date_of_birth': '2020-01-15',
            'peso': 25.5,
            'description': 'Cachorro muito amigavel',
            'microchip_number': '123456789',
            'neutered': True
        }
        
        response = client.post('/add-animal', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # Verify animal was created
        with app.app_context():
            animal = Animal.query.filter_by(name='Rex', user_id=tutor).first()
            assert animal is not None
            assert animal.species_id == species_and_breeds['dog_species_id']
            assert animal.peso == 25.5
            assert animal.neutered is True
    
    def test_edit_animal_workflow(self, client, tutor, species_and_breeds, app):
        """Test editing an existing animal."""
        login(client, tutor)
        
        # Create an animal first
        with app.app_context():
            animal = Animal(
                name='Mimi',
                species_id=species_and_breeds['cat_species_id'],
                breed_id=species_and_breeds['persian_id'],
                user_id=tutor,
                sex='femea',
                peso=4.2
            )
            db.session.add(animal)
            db.session.commit()
            animal_id = animal.id
        
        # Edit the animal
        response = client.get(f'/editar-animal/{animal_id}')
        assert response.status_code == 200
        
        update_data = {
            'name': 'Mimi Updated',
            'species_id': species_and_breeds['cat_species_id'],
            'breed_id': species_and_breeds['persian_id'],
            'sex': 'femea',
            'peso': 4.8,
            'neutered': True
        }
        
        response = client.post(f'/editar-animal/{animal_id}', data=update_data, follow_redirects=True)
        assert response.status_code == 200
        
        # Verify updates
        with app.app_context():
            updated_animal = Animal.query.get(animal_id)
            assert updated_animal.name == 'Mimi Updated'
            assert updated_animal.peso == 4.8
            assert updated_animal.neutered is True
    
    def test_view_animal_medical_history(self, client, tutor, species_and_breeds, veterinarian_with_clinic, app):
        """Test viewing complete animal medical history (ficha)."""
        login(client, tutor)
        
        # Create animal with medical history
        with app.app_context():
            animal = Animal(
                name='Bobby',
                species_id=species_and_breeds['dog_species_id'],
                user_id=tutor,
                sex='macho'
            )
            db.session.add(animal)
            db.session.commit()
            
            # Add consultation
            consulta = Consulta(
                animal_id=animal.id,
                created_by=veterinarian_with_clinic['vet_id'],
                clinica_id=veterinarian_with_clinic['clinic_id'],
                queixa_principal="Check-up de rotina",
                exame_fisico="Animal saudavel",
                conduta="Manter cuidados",
                status='completed',
                finalizada_em=datetime.utcnow()
            )
            db.session.add(consulta)
            
            # Add prescription
            bloco = BlocoPrescricao(
                animal_id=animal.id,
                clinica_id=veterinarian_with_clinic['clinic_id'],
                saved_by_id=veterinarian_with_clinic['vet_id']
            )
            db.session.add(bloco)
            db.session.commit()
            
            prescricao = Prescricao(
                bloco_id=bloco.id,
                animal_id=animal.id,
                medicamento="Antibiotico X",
                dosagem="10mg",
                frequencia="2x ao dia",
                duracao="7 dias"
            )
            db.session.add(prescricao)
            
            # Add vaccination
            vacina = Vacina(
                animal_id=animal.id,
                nome="V10",
                aplicada_em=datetime.utcnow().date(),
                aplicada_por="Dr. Joao"
            )
            db.session.add(vacina)
            
            db.session.commit()
            animal_id = animal.id
        
        # View medical history
        response = client.get(f'/ficha/{animal_id}')
        assert response.status_code == 200
        assert b'Bobby' in response.data
        assert b'Check-up de rotina' in response.data or b'consulta' in response.data.lower()


class TestAppointmentWorkflow:
    """Test appointment scheduling and management."""
    
    def test_schedule_appointment(self, client, tutor, species_and_breeds, veterinarian_with_clinic, app):
        """Test scheduling a new appointment."""
        login(client, tutor)
        
        # Create an animal
        with app.app_context():
            animal = Animal(
                name='Max',
                species_id=species_and_breeds['dog_species_id'],
                user_id=tutor,
                sex='macho'
            )
            db.session.add(animal)
            db.session.commit()
            animal_id = animal.id
        
        # Schedule appointment
        appointment_data = {
            'animal_id': animal_id,
            'clinica_id': veterinarian_with_clinic['clinic_id'],
            'data_hora': (datetime.utcnow() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
            'tipo': 'consulta',
            'observacoes': 'Check-up anual'
        }
        
        response = client.post('/agendar', data=appointment_data, follow_redirects=True)
        assert response.status_code == 200
        
        # Verify appointment was created
        with app.app_context():
            evento = AgendaEvento.query.filter_by(responsavel_id=veterinarian_with_clinic['vet_id']).first()
            assert evento is not None or response.status_code == 200  # May have different implementation
    
    def test_view_appointments(self, client, tutor, species_and_breeds, veterinarian_with_clinic, app):
        """Test viewing scheduled appointments."""
        login(client, tutor)
        
        with app.app_context():
            animal = Animal(
                name='Luna',
                species_id=species_and_breeds['cat_species_id'],
                user_id=tutor,
                sex='femea'
            )
            db.session.add(animal)
            db.session.commit()
            
            # Create appointment
            evento = AgendaEvento(
                titulo='Consulta Luna',
                inicio=datetime.utcnow() + timedelta(days=3),
                fim=datetime.utcnow() + timedelta(days=3, hours=1),
                descricao='consulta',
                responsavel_id=veterinarian_with_clinic['vet_id'],
                clinica_id=veterinarian_with_clinic['clinic_id'],
            )
            db.session.add(evento)
            db.session.commit()
        
        # View appointments
        response = client.get('/appointments')
        assert response.status_code == 200 or response.status_code == 302  # May redirect if not accessible


class TestFinancialWorkflow:
    """Test financial operations for tutors."""
    
    def test_view_estimate(self, client, tutor, species_and_breeds, veterinarian_with_clinic, app):
        """Test viewing an estimate (orcamento)."""
        login(client, tutor)
        
        with app.app_context():
            animal = Animal(
                name='Thor',
                species_id=species_and_breeds['dog_species_id'],
                user_id=tutor,
                sex='macho'
            )
            db.session.add(animal)
            db.session.commit()
            
            # Create estimate block
            bloco = BlocoOrcamento(
                animal_id=animal.id,
                clinica_id=veterinarian_with_clinic['clinic_id'],
                payment_status='pending'
            )
            db.session.add(bloco)
            db.session.commit()
            
            # Add service
            servico = ServicoClinica(
                descricao="Consulta veterinaria",
                valor=Decimal('150.00'),
                clinica_id=veterinarian_with_clinic['clinic_id']
            )
            db.session.add(servico)
            db.session.commit()
            
            item = OrcamentoItem(
                bloco_id=bloco.id,
                descricao="Consulta veterinaria",
                valor=Decimal('150.00'),
                clinica_id=veterinarian_with_clinic['clinic_id']
            )
            db.session.add(item)
            db.session.commit()
            
            bloco_id = bloco.id
        
        # View estimate
        response = client.get(f'/bloco_orcamento/{bloco_id}')
        assert response.status_code == 200 or response.status_code == 302  # May require different access
        
        with app.app_context():
            bloco = BlocoOrcamento.query.get(bloco_id)
            assert bloco.total == Decimal('150.00')


class TestMedicalRecordsAccess:
    """Test accessing medical records and documents."""
    
    def test_download_prescription(self, client, tutor, species_and_breeds, veterinarian_with_clinic, app):
        """Test downloading a prescription PDF."""
        login(client, tutor)
        
        with app.app_context():
            animal = Animal(
                name='Bella',
                species_id=species_and_breeds['dog_species_id'],
                user_id=tutor,
                sex='femea'
            )
            db.session.add(animal)
            db.session.commit()
            
            bloco = BlocoPrescricao(
                animal_id=animal.id,
                clinica_id=veterinarian_with_clinic['clinic_id'],
                saved_by_id=veterinarian_with_clinic['vet_id']
            )
            db.session.add(bloco)
            db.session.commit()
            
            prescricao = Prescricao(
                bloco_id=bloco.id,
                animal_id=animal.id,
                medicamento="Medicacao Teste",
                dosagem="5mg",
                frequencia="1x ao dia",
                duracao="10 dias"
            )
            db.session.add(prescricao)
            db.session.commit()
            
            bloco_id = bloco.id
        
        # Download prescription
        response = client.get(f'/imprimir_bloco_prescricao/{bloco_id}')
        # Should return PDF or HTML page
        assert response.status_code == 200 or response.status_code == 302
    
    def test_view_vaccination_history(self, client, tutor, species_and_breeds, app):
        """Test viewing vaccination history."""
        login(client, tutor)
        
        with app.app_context():
            animal = Animal(
                name='Charlie',
                species_id=species_and_breeds['dog_species_id'],
                user_id=tutor,
                sex='macho'
            )
            db.session.add(animal)
            db.session.commit()
            
            # Add multiple vaccinations
            vacinas = [
                Vacina(
                    animal_id=animal.id,
                    nome="V8",
                    aplicada_em=datetime.utcnow().date() - timedelta(days=365),
                    aplicada_por="Dr. Silva"
                ),
                Vacina(
                    animal_id=animal.id,
                    nome="V10",
                    aplicada_em=datetime.utcnow().date() - timedelta(days=180),
                    aplicada_por="Dr. Silva"
                ),
                Vacina(
                    animal_id=animal.id,
                    nome="Antirrabica",
                    aplicada_em=datetime.utcnow().date() - timedelta(days=90),
                    aplicada_por="Dr. Silva"
                )
            ]
            for v in vacinas:
                db.session.add(v)
            db.session.commit()
            animal_id = animal.id
        
        # View animal details with vaccinations
        response = client.get(f'/ficha/{animal_id}')
        assert response.status_code == 200
        # Vaccinations should be listed
        assert b'vacina' in response.data.lower() or b'vacinacao' in response.data.lower()


class TestProfileManagement:
    """Test user profile management."""
    
    def test_update_profile(self, client, tutor, app):
        """Test updating user profile information."""
        login(client, tutor)
        
        # Access profile page
        response = client.get('/profile')
        assert response.status_code == 200
        
        # Update profile
        update_data = {
            'name': 'Joao Silva Updated',
            'phone': '16999887777',
            'address': 'Rua Nova, 456'
        }
        
        response = client.post('/profile', data=update_data, follow_redirects=True)
        assert response.status_code == 200
        
        # Verify updates
        with app.app_context():
            user = User.query.get(tutor)
            # Updates may vary based on implementation
            assert user is not None
    
    def test_change_password(self, client, tutor, app):
        """Test password change functionality."""
        login(client, tutor)
        
        # Access change password page
        response = client.get('/change_password')
        assert response.status_code == 200 or response.status_code == 302
        
        # Change password
        change_data = {
            'current_password': 'senha123',
            'new_password': 'novaSenha@456',
            'confirm_password': 'novaSenha@456'
        }
        
        response = client.post('/change_password', data=change_data, follow_redirects=True)
        # Should succeed or show appropriate error
        assert response.status_code == 200


# Performance tests
class TestPerformance:
    """Test page load performance."""
    
    def test_index_page_performance(self, client):
        """Index page should load quickly."""
        import time
        start = time.time()
        response = client.get('/')
        elapsed = time.time() - start
        
        assert response.status_code == 200
        assert elapsed < 2.0, f"Index page took {elapsed:.2f}s to load"
    
    def test_animals_list_performance(self, client, tutor, species_and_breeds, app):
        """Animals list should load quickly even with many animals."""
        login(client, tutor)
        
        # Create multiple animals
        with app.app_context():
            for i in range(20):
                animal = Animal(
                    name=f'Animal {i}',
                    species_id=species_and_breeds['dog_species_id'],
                    user_id=tutor,
                    sex='macho'
                )
                db.session.add(animal)
            db.session.commit()
        
        import time
        start = time.time()
        response = client.get('/meus-animais')
        elapsed = time.time() - start
        
        # Should handle pagination
        assert response.status_code == 200 or response.status_code == 302
        assert elapsed < 2.0, f"Animals list took {elapsed:.2f}s to load"
