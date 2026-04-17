import json
from datetime import date, timedelta

from extensions import db
from models import (
    Animal,
    Appointment,
    BlocoExames,
    BlocoPrescricao,
    Clinica,
    Consulta,
    ExamAppointment,
    ExameSolicitado,
    OAuthAccessToken,
    Prescricao,
    User,
    Vacina,
    Veterinario,
)
from time_utils import utcnow


def _create_token(user_id: int, scope: str = "") -> str:
    token_value = f"token-{user_id}-{scope.replace(':', '-') or 'none'}"
    token = OAuthAccessToken(
        client_id="integration-client",
        user_id=user_id,
        access_token=token_value,
        token_type="Bearer",
        scope=scope,
        expires_at=utcnow() + timedelta(minutes=30),
    )
    db.session.add(token)
    db.session.commit()
    return token_value


def test_integrations_endpoint_requires_bearer_token(app, client):
    response = client.get("/api/integrations/pets")

    assert response.status_code == 401
    body = response.get_json()
    assert body["error"]["code"] == "missing_bearer_token"


def test_integrations_endpoint_requires_scope(app, client):
    with app.app_context():
        user = User(name="Tutor", email="tutor-scope@example.com", role="adotante")
        user.set_password("secret123")
        db.session.add(user)
        db.session.commit()
        token_value = _create_token(user.id, scope="profile")

    response = client.get(
        "/api/integrations/pets",
        headers={"Authorization": f"Bearer {token_value}"},
    )

    assert response.status_code == 403
    payload = response.get_json()
    assert payload["error"]["code"] == "insufficient_scope"
    assert "pets:read" in payload["error"]["details"]["missing_scopes"]


def test_integrations_me_and_resource_endpoints(app, client):
    with app.app_context():
        tutor = User(name="Tutor Full", email="tutor-full@example.com", role="adotante")
        tutor.set_password("secret123")
        vet_user = User(name="Vet", email="vet-full@example.com", role="veterinario", worker="veterinario")
        vet_user.set_password("secret123")
        db.session.add_all([tutor, vet_user])
        db.session.flush()

        vet = Veterinario(user_id=vet_user.id, crmv="CRMV-123")
        db.session.add(vet)
        db.session.flush()

        pet = Animal(name="Rex", user_id=tutor.id)
        db.session.add(pet)
        db.session.flush()

        appt = Appointment(
            animal_id=pet.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=utcnow() + timedelta(days=1),
            status="scheduled",
            kind="general",
        )
        db.session.add(appt)
        db.session.commit()

        token_value = _create_token(tutor.id, scope="profile pets:read appointments:read")

    me_response = client.get(
        "/api/integrations/me",
        headers={"Authorization": f"Bearer {token_value}"},
    )
    assert me_response.status_code == 200
    assert me_response.get_json()["data"]["sub"]

    pets_response = client.get(
        "/api/integrations/pets",
        headers={"Authorization": f"Bearer {token_value}"},
    )
    assert pets_response.status_code == 200
    pets_payload = pets_response.get_json()["data"]
    assert len(pets_payload) == 1
    assert pets_payload[0]["name"] == "Rex"

    appointments_response = client.get(
        "/api/integrations/appointments",
        headers={"Authorization": f"Bearer {token_value}"},
    )
    assert appointments_response.status_code == 200
    appointments_payload = appointments_response.get_json()["data"]
    assert len(appointments_payload) == 1
    assert appointments_payload[0]["animal_id"] == pets_payload[0]["id"]


def test_integrations_clinical_endpoints_for_veterinarian(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica Clinica")
        db.session.add(clinic)
        db.session.flush()

        vet_user = User(
            name="Dra. Ana",
            email="ana-integrations@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        vet_user.set_password("secret123")
        tutor = User(name="Tutor Resumo", email="tutor-resumo@example.com", role="adotante", clinica_id=clinic.id)
        tutor.set_password("secret123")
        db.session.add_all([vet_user, tutor])
        db.session.flush()

        vet = Veterinario(user_id=vet_user.id, crmv="CRMV-555", clinica_id=clinic.id)
        db.session.add(vet)
        db.session.flush()

        pet = Animal(name="Thor", user_id=tutor.id, clinica_id=clinic.id)
        db.session.add(pet)
        db.session.flush()

        consulta = Consulta(
            animal_id=pet.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            queixa_principal="Vômito e apatia",
            historico_clinico="Sintomas há 2 dias.",
            exame_fisico="Desidratação leve.",
            conduta="Hidratação e dieta leve.",
            exames_solicitados="Hemograma completo",
            status="finalizada",
            finalizada_em=utcnow(),
        )
        db.session.add(consulta)
        db.session.flush()

        agenda_at = utcnow().replace(hour=15, minute=0, second=0, microsecond=0)
        retorno_at = agenda_at + timedelta(hours=2)

        retorno = Appointment(
            animal_id=pet.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=retorno_at,
            status="scheduled",
            kind="retorno",
            consulta_id=consulta.id,
            clinica_id=clinic.id,
        )
        agenda = Appointment(
            animal_id=pet.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=agenda_at,
            status="scheduled",
            kind="consulta",
            clinica_id=clinic.id,
        )
        db.session.add_all([retorno, agenda])

        bloco_prescricao = BlocoPrescricao(
            animal_id=pet.id,
            clinica_id=clinic.id,
            saved_by_id=vet_user.id,
            instrucoes_gerais="Oferecer água em pequenas quantidades e observar vômitos.",
        )
        db.session.add(bloco_prescricao)
        db.session.flush()
        db.session.add(
            Prescricao(
                bloco_id=bloco_prescricao.id,
                animal_id=pet.id,
                medicamento="Omeprazol",
                dosagem="10 mg",
                frequencia="a cada 24h",
                duracao="5 dias",
            )
        )

        bloco_exames = BlocoExames(animal_id=pet.id, observacoes_gerais="Suspeita gastrointestinal")
        db.session.add(bloco_exames)
        db.session.flush()
        db.session.add(
            ExameSolicitado(
                bloco_id=bloco_exames.id,
                nome="Hemograma completo",
                justificativa="Avaliar processo inflamatório",
                status="pendente",
            )
        )

        db.session.add(
            ExamAppointment(
                animal_id=pet.id,
                specialist_id=vet.id,
                requester_id=vet_user.id,
                scheduled_at=utcnow() + timedelta(days=1),
                status="pending",
            )
        )

        db.session.add_all(
            [
                Vacina(
                    animal_id=pet.id,
                    nome="V10",
                    tipo="Reforço",
                    aplicada=False,
                    aplicada_em=date.today() - timedelta(days=7),
                ),
                Vacina(
                    animal_id=pet.id,
                    nome="Antirrábica",
                    tipo="Campanha",
                    aplicada=False,
                    aplicada_em=date.today() + timedelta(days=15),
                ),
            ]
        )
        pet_id = pet.id
        db.session.commit()

        token_value = _create_token(
            vet_user.id,
            scope=(
                "profile pets:read appointments:read clinical_summary:read "
                "consultations:read prescriptions:read exams:read vaccines:read "
                "handoff:read tutor_guidance:generate"
            ),
        )

    headers = {"Authorization": f"Bearer {token_value}"}

    summary_response = client.get(f"/api/integrations/clinical-summary/{pet_id}", headers=headers)
    assert summary_response.status_code == 200
    summary_payload = summary_response.get_json()["data"]
    assert summary_payload["animal"]["nome"] == "Thor"
    assert summary_payload["ultima_consulta"]["queixa_principal"] == "Vômito e apatia"
    assert summary_payload["pendencias"]["vacinas_atrasadas"][0]["nome"] == "V10"

    agenda_response = client.get(
        f"/api/integrations/today-agenda?date={agenda_at.date().isoformat()}",
        headers=headers,
    )
    assert agenda_response.status_code == 200
    agenda_payload = agenda_response.get_json()["data"]
    assert agenda_payload["total_agendamentos"] >= 1
    assert any(item["animal"]["nome"] == "Thor" for item in agenda_payload["agendamentos"])

    pendencias_response = client.get("/api/integrations/clinical-pendencies", headers=headers)
    assert pendencias_response.status_code == 200
    pendencias_payload = pendencias_response.get_json()["data"]
    assert pendencias_payload["resumo"]["vacinas_atrasadas"] == 1
    assert pendencias_payload["resumo"]["retornos_pendentes"] == 1
    assert pendencias_payload["resumo"]["solicitacoes_de_exame_pendentes"] == 1

    guidance_response = client.get(f"/api/integrations/tutor-guidance/{pet_id}", headers=headers)
    assert guidance_response.status_code == 200
    guidance_payload = guidance_response.get_json()["data"]
    assert "Thor" in guidance_payload["rascunho"]
    assert "Omeprazol" in guidance_payload["rascunho"]

    handoff_response = client.get(f"/api/integrations/handoff/{pet_id}", headers=headers)
    assert handoff_response.status_code == 200
    handoff_payload = handoff_response.get_json()["data"]
    assert handoff_payload["animal"]["nome"] == "Thor"
    assert "Handoff clínico" in handoff_payload["handoff_texto"]


def test_integrations_clinical_summary_respects_clinic_scope(app, client):
    with app.app_context():
        clinic_a = Clinica(nome="Clinica A")
        clinic_b = Clinica(nome="Clinica B")
        db.session.add_all([clinic_a, clinic_b])
        db.session.flush()

        tutor = User(name="Tutor Escopo", email="tutor-escopo@example.com", role="adotante", clinica_id=clinic_a.id)
        tutor.set_password("secret123")
        vet_user = User(
            name="Dra. Escopo",
            email="vet-escopo@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic_b.id,
        )
        vet_user.set_password("secret123")
        db.session.add_all([tutor, vet_user])
        db.session.flush()

        db.session.add(Veterinario(user_id=vet_user.id, crmv="CRMV-777", clinica_id=clinic_b.id))
        db.session.flush()

        pet = Animal(name="Bolt", user_id=tutor.id, clinica_id=clinic_a.id)
        db.session.add(pet)
        db.session.flush()
        pet_id = pet.id
        db.session.commit()

        token_value = _create_token(vet_user.id, scope="profile clinical_summary:read")

    response = client.get(
        f"/api/integrations/clinical-summary/{pet_id}",
        headers={"Authorization": f"Bearer {token_value}"},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "animal_not_found"


def test_mcp_clinical_tools_return_structured_payload(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica MCP Operacional")
        db.session.add(clinic)
        db.session.flush()

        vet_user = User(
            name="Dra. Julia",
            email="julia-mcp@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        vet_user.set_password("secret123")
        tutor = User(name="Tutor MCP", email="tutor-mcp@example.com", role="adotante", clinica_id=clinic.id)
        tutor.set_password("secret123")
        db.session.add_all([vet_user, tutor])
        db.session.flush()

        vet = Veterinario(user_id=vet_user.id, crmv="CRMV-888", clinica_id=clinic.id)
        db.session.add(vet)
        db.session.flush()

        pet = Animal(name="Luna", user_id=tutor.id, clinica_id=clinic.id)
        db.session.add(pet)
        db.session.flush()

        consulta = Consulta(
            animal_id=pet.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            queixa_principal="Coceira intensa",
            conduta="Banho terapêutico e retorno",
            status="finalizada",
            finalizada_em=utcnow(),
        )
        db.session.add(consulta)
        db.session.flush()

        db.session.add(
            Appointment(
                animal_id=pet.id,
                tutor_id=tutor.id,
                veterinario_id=vet.id,
                scheduled_at=utcnow() + timedelta(hours=4),
                status="scheduled",
                kind="retorno",
                consulta_id=consulta.id,
                clinica_id=clinic.id,
            )
        )
        pet_id = pet.id
        db.session.commit()

        token_value = _create_token(
            vet_user.id,
            scope="profile appointments:read clinical_summary:read handoff:read tutor_guidance:generate exams:read vaccines:read",
        )

    summary_response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {"name": "obter_resumo_clinico_animal", "arguments": {"animal_id": pet_id}},
        },
    )
    assert summary_response.status_code == 200
    summary_payload = summary_response.get_json()
    summary_result = json.loads(summary_payload["result"]["content"][0]["text"])
    assert summary_result["animal"]["nome"] == "Luna"

    guidance_response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {"name": "gerar_orientacao_tutor", "arguments": {"animal_id": pet_id}},
        },
    )
    assert guidance_response.status_code == 200
    guidance_payload = guidance_response.get_json()
    guidance_result = json.loads(guidance_payload["result"]["content"][0]["text"])
    assert "Luna" in guidance_result["rascunho"]


def test_mcp_write_tools_create_records(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica Writes")
        db.session.add(clinic)
        db.session.flush()

        vet_user = User(
            name="Dra. Helena",
            email="helena-writes@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        vet_user.set_password("secret123")
        db.session.add(vet_user)
        db.session.flush()

        vet = Veterinario(user_id=vet_user.id, crmv="CRMV-9090", clinica_id=clinic.id)
        db.session.add(vet)
        db.session.commit()

        token_value = _create_token(
            vet_user.id,
            scope=(
                "profile tutors:write pets:write appointments:write consultations:write "
                "exams:write pets:read appointments:read"
            ),
        )

    headers = {"Authorization": f"Bearer {token_value}"}

    register_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {
                "name": "cadastrar_tutor_e_pets",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "tutor": {
                        "nome": "Carlos Tutor",
                        "telefone": "16999990000",
                        "endereco": "Rua A, 10",
                    },
                    "pets": [
                        {
                            "nome": "Meg",
                            "especie": "cao",
                            "idade": "3 anos",
                            "sexo": "Fêmea",
                        }
                    ],
                    "observacao_clinica": "Paciente com tosse recorrente.",
                    "disponibilidade": "Preferência por manhã.",
                },
            },
        },
    )
    assert register_response.status_code == 200
    register_result = json.loads(register_response.get_json()["result"]["content"][0]["text"])
    animal_id = register_result["pets"][0]["id"]

    consulta_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 32,
            "method": "tools/call",
            "params": {
                "name": "registrar_consulta_clinica",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "animal_id": animal_id,
                    "queixa_principal": "Tosse há uma semana",
                    "historico_clinico": "Sem febre, apetite preservado.",
                    "exame_fisico": "Ausculta com ruído leve.",
                    "diagnostico": "Suspeita de traqueobronquite",
                    "conduta": "Nebulização e monitoramento",
                    "exames_solicitados": "Radiografia torácica",
                    "finalizar": True,
                },
            },
        },
    )
    assert consulta_response.status_code == 200
    consulta_result = json.loads(consulta_response.get_json()["result"]["content"][0]["text"])
    consulta_id = consulta_result["consulta_id"]
    assert consulta_result["status"] == "finalizada"

    exames_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 33,
            "method": "tools/call",
            "params": {
                "name": "registrar_bloco_exames",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "animal_id": animal_id,
                    "observacoes_gerais": "Investigar padrão respiratório.",
                    "exames": [
                        {
                            "nome": "Radiografia torácica",
                            "justificativa": "Avaliar padrão pulmonar",
                            "status": "pendente",
                        }
                    ],
                },
            },
        },
    )
    assert exames_response.status_code == 200
    exames_result = json.loads(exames_response.get_json()["result"]["content"][0]["text"])
    assert exames_result["total_exames"] == 1

    agendamento_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 34,
            "method": "tools/call",
            "params": {
                "name": "agendar_consulta",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "animal_id": animal_id,
                    "data": (utcnow() + timedelta(days=2)).date().isoformat(),
                    "hora": "09:30",
                    "tipo": "consulta",
                    "motivo": "Retorno respiratório",
                },
            },
        },
    )
    assert agendamento_response.status_code == 200
    agendamento_result = json.loads(agendamento_response.get_json()["result"]["content"][0]["text"])
    assert agendamento_result["tipo"] == "consulta"

    retorno_response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 35,
            "method": "tools/call",
            "params": {
                "name": "agendar_retorno",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "consulta_id": consulta_id,
                    "data": (utcnow() + timedelta(days=7)).date().isoformat(),
                    "hora": "10:00",
                    "motivo": "Reavaliar evolução clínica",
                },
            },
        },
    )
    assert retorno_response.status_code == 200
    retorno_result = json.loads(retorno_response.get_json()["result"]["content"][0]["text"])
    assert retorno_result["success"] is True

    with app.app_context():
        tutor = User.query.filter_by(name="Carlos Tutor").one()
        pet = Animal.query.filter_by(id=animal_id).one()
        assert tutor.email.endswith("@cadastro.petorlandia.local")
        assert pet.user_id == tutor.id
        consulta = Consulta.query.get(consulta_id)
        assert "Diagnóstico" in (consulta.conduta or "")
        assert ExameSolicitado.query.count() == 1
        assert Appointment.query.filter_by(animal_id=animal_id).count() >= 2


def test_mcp_registration_tool_requires_write_scopes(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica MCP")
        db.session.add(clinic)
        db.session.flush()

        professional = User(
            name="Colaborador",
            email="colaborador-mcp@example.com",
            role="adotante",
            worker="colaborador",
            clinica_id=clinic.id,
        )
        professional.set_password("secret123")
        db.session.add(professional)
        db.session.commit()

        token_value = _create_token(professional.id, scope="profile pets:read")

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "cadastrar_tutor_e_pets",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "tutor": {"nome": "Nelson Benedito"},
                    "pets": [{"nome": "Marron"}],
                },
            },
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["error"]["code"] == -32003
    assert "tutors:write" in payload["error"]["data"]["missing_scopes"]
    assert "pets:write" in payload["error"]["data"]["missing_scopes"]


def test_mcp_registration_tool_requires_veterinarian_profile(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica Restrita")
        db.session.add(clinic)
        db.session.flush()

        user = User(
            name="Atendente",
            email="atendente-restrito@example.com",
            role="adotante",
            worker="colaborador",
            clinica_id=clinic.id,
        )
        user.set_password("secret123")
        db.session.add(user)
        db.session.commit()

        token_value = _create_token(
            user.id,
            scope="profile tutors:write pets:write pets:read appointments:read",
        )

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "cadastrar_tutor_e_pets",
                "arguments": {
                    "confirmar_gravacao": "sim",
                    "tutor": {"nome": "Nelson Benedito"},
                    "pets": [{"nome": "Marron"}],
                },
            },
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["error"]["code"] == -32003
    assert "veterinarian accounts" in payload["error"]["message"]


def test_mcp_registration_tool_creates_and_reuses_tutor_and_pets(app, client):
    with app.app_context():
        clinic = Clinica(nome="Clinica ChatGPT")
        db.session.add(clinic)
        db.session.flush()
        clinic_id = clinic.id

        professional = User(
            name="Dra. Marina",
            email="marina-chatgpt@example.com",
            role="veterinario",
            worker="veterinario",
            clinica_id=clinic.id,
        )
        professional.set_password("secret123")
        db.session.add(professional)
        db.session.flush()

        db.session.add(
            Veterinario(
                user_id=professional.id,
                crmv="CRMV-2026",
            )
        )
        db.session.commit()

        token_value = _create_token(
            professional.id,
            scope="profile tutors:write pets:write pets:read appointments:read",
        )

    request_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "cadastrar_tutor_e_pets",
            "arguments": {
                "confirmar_gravacao": "sim",
                "tutor": {
                    "nome": "Nelson Benedito",
                    "telefone": "99344-5088",
                    "endereco": "Travessa V, 1211 - CEP 14620-000",
                },
                "pets": [
                    {"nome": "Marron", "especie": "cao", "idade": "2 anos"},
                    {"nome": "Tigrinho", "especie": "cão", "idade": "2 anos"},
                ],
                "observacao_clinica": "Problema ocular com aspecto azulado. Alimentação normal.",
                "disponibilidade": "Qualquer horário (preferência: 12/11 entre 14h e 16h)",
            },
        },
    }

    first_response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json=request_payload,
    )
    assert first_response.status_code == 200
    first_payload = first_response.get_json()
    first_result = json.loads(first_payload["result"]["content"][0]["text"])

    assert first_result["tutor"]["ja_existia"] is False
    assert first_result["tutor"]["email_provisorio"] is True
    assert first_result["resumo"]["pets_criados"] == 2
    assert first_result["resumo"]["consultas_iniciais_criadas"] == 2

    with app.app_context():
        tutor = User.query.filter_by(name="Nelson Benedito").one()
        assert tutor.clinica_id == clinic_id
        assert tutor.address == "Travessa V, 1211 - CEP 14620-000"
        assert tutor.email.endswith("@cadastro.petorlandia.local")

        pets = Animal.query.filter_by(user_id=tutor.id).order_by(Animal.name).all()
        assert [pet.name for pet in pets] == ["Marron", "Tigrinho"]
        assert all(pet.species and pet.species.name == "Cachorro" for pet in pets)

        consultas = Consulta.query.filter(Consulta.animal_id.in_([pet.id for pet in pets])).all()
        assert len(consultas) == 2
        assert all(
            consulta.queixa_principal == "Problema ocular com aspecto azulado. Alimentação normal."
            for consulta in consultas
        )
        assert all(
            "Disponibilidade informada: Qualquer horário (preferência: 12/11 entre 14h e 16h)"
            in (consulta.historico_clinico or "")
            for consulta in consultas
        )

    second_response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token_value}"},
        json=request_payload,
    )
    assert second_response.status_code == 200
    second_payload = second_response.get_json()
    second_result = json.loads(second_payload["result"]["content"][0]["text"])

    assert second_result["tutor"]["ja_existia"] is True
    assert all(pet["ja_existia"] is True for pet in second_result["pets"])
    assert second_result["resumo"]["pets_criados"] == 0
    assert second_result["resumo"]["pets_reaproveitados"] == 2

    with app.app_context():
        assert User.query.filter_by(name="Nelson Benedito").count() == 1
        tutor = User.query.filter_by(name="Nelson Benedito").one()
        assert Animal.query.filter_by(user_id=tutor.id).count() == 2
        assert Consulta.query.count() == 2
