"""Views do domínio mcp (migrado do app.py)."""
from flask import Blueprint
import json
from datetime import date, datetime
from urllib.parse import quote_plus
from extensions import csrf, db
from flask import jsonify, make_response, request, url_for
from helpers import has_veterinarian_profile
from models import (
    AdminActionNotification,
    Animal,
    AnimalHealthRecord,
    AnimalDocumento,
    Appointment,
    Clinica,
    CarteirinhaImportacao,
    Consulta,
    ExameImagem,
    OAuthAccessToken,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    User,
    Vacina,
    Veterinario,
)
from services.appointments import ReturnAppointmentDTO, schedule_return_appointment
from services.oauth_provider import _oauth_allowed_scopes, _oauth_extract_bearer_token, _oauth_issuer, _oauth_order_scopes

# Helpers ainda hospedados no app.py (realocação em fases futuras).
from app import (  # noqa: E402
    LAUDO_VOLANTE_WIDGET_URI,
    _create_external_onboarding_invite,
    _integration_accessible_animals_query,
    _integration_accessible_appointments_query,
    _integration_accessible_consultas_query,
    _integration_build_clinical_pendencies,
    _integration_build_clinical_summary,
    _integration_build_handoff,
    _integration_build_today_agenda,
    _integration_create_exam_block,
    _integration_create_exame_imagem,
    _integration_create_or_reuse_tutor_and_pets,
    _integration_download_and_store_carteirinha_file,
    _integration_ensure_clinic_admin_user,
    _integration_exame_imagem_document_payload,
    _integration_exame_imagem_pdf_summary,
    _integration_execute_assistant_action,
    _integration_extract_freeform_intake,
    _integration_extract_pdf_file_reference,
    _integration_find_accessible_animal,
    _integration_find_exame_by_documento,
    _integration_find_or_create_external_clinic,
    _integration_find_or_create_pet_for_tutor,
    _integration_find_or_create_tutor_for_clinic,
    _integration_format_datetime,
    _integration_generate_tutor_guidance,
    _integration_import_mobile_exam_report,
    _integration_infer_assistant_action,
    _integration_list_exame_imagem_history,
    _integration_normalize_match_text,
    _integration_parse_date_arg,
    _integration_parse_time_arg,
    _integration_reconcile_exam_documents,
    _integration_release_exame_imagem,
    _integration_resolve_breed,
    _integration_resolve_species,
    _integration_schedule_consulta,
    _integration_serialize_exame_imagem,
    _integration_store_exame_pdf,
    _integration_suggest_report_template,
    _integration_upsert_consulta,
    _integration_user_can_access_exame_imagem,
    _integration_user_clinic_id,
    _invite_payload,
    _is_local_chatgpt_file_path,
    _serialize_calendar_pet,
)

# As rotas /mcp são registradas pelo blueprint oauth (endpoints oauth_routes.*).








MCP_PROTOCOL_VERSIONS = (
    '2025-06-18',
    '2025-03-26',
    '2024-11-05',
)


def _mcp_protocol_version(params: dict) -> str:
    """Negocia uma versao MCP atual sem desconectar clientes legados."""
    requested = str((params or {}).get('protocolVersion') or '').strip()
    if requested in MCP_PROTOCOL_VERSIONS:
        return requested
    return MCP_PROTOCOL_VERSIONS[0]


def _mcp_ok(req_id, result):
    return jsonify({'jsonrpc': '2.0', 'id': req_id, 'result': result})


def _mcp_err(req_id, code, message):
    return jsonify({'jsonrpc': '2.0', 'id': req_id, 'error': {'code': code, 'message': message}})


def _mcp_err_with_data(req_id, code, message, data):
    return jsonify({'jsonrpc': '2.0', 'id': req_id, 'error': {'code': code, 'message': message, 'data': data}})


def _mcp_json_content(payload):
    result = {'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False, indent=2)}]}
    if isinstance(payload, dict):
        result['structuredContent'] = payload
    return result


def _mcp_annotations(read_only: bool, *, destructive: bool = False, open_world: bool = False, idempotent: bool | None = None):
    annotations = {
        'readOnlyHint': read_only,
        'destructiveHint': destructive,
        'openWorldHint': open_world,
    }
    if idempotent is not None:
        annotations['idempotentHint'] = idempotent
    return annotations


def _mcp_object_output_schema(description: str | None = None):
    schema = {
        'type': 'object',
        'additionalProperties': True,
    }
    if description:
        schema['description'] = description
    return schema


def _mcp_array_output_schema(property_name: str, item_description: str):
    return {
        'type': 'object',
        'properties': {
            property_name: {
                'type': 'array',
                'description': item_description,
                'items': {'type': 'object', 'additionalProperties': True},
            },
        },
        'required': [property_name],
        'additionalProperties': True,
    }


MCP_TOOL_DESCRIPTOR_DEFAULTS = {
    'listar_meus_pets': {
        'title': 'Listar meus pets',
        'scopes': ['pets:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_array_output_schema('pets', 'Pets acessiveis ao usuario autenticado.'),
    },
    'listar_vacinas_pet': {
        'title': 'Listar vacinas do pet',
        'scopes': ['pets:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_array_output_schema('vacinas', 'Vacinas aplicadas e proximas doses dos pets do usuario.'),
    },
    'obter_carteirinha_pet': {
        'title': 'Obter carteirinha digital do pet',
        'scopes': ['pets:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Link publico da carteirinha digital do pet.'),
    },
    'revisar_carteirinha_fotografada': {
        'title': 'Revisar carteirinha fotografada',
        'scopes': ['pets:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Rascunho revisavel de identificacao, vacinas e vermifugacoes.'),
    },
    'importar_carteirinha_fotografada': {
        'title': 'Importar carteirinha fotografada',
        'scopes': ['pets:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Dados da carteirinha gravados com fotos de origem auditaveis.'),
    },
    'atualizar_perfil_pet': {
        'title': 'Atualizar perfil do pet',
        'scopes': ['pets:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Cadastro do pet atualizado.'),
    },
    'atualizar_perfil_tutor': {
        'title': 'Atualizar perfil do tutor',
        'scopes': ['tutors:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Cadastro do tutor atualizado.'),
    },
    'registrar_vacina_pet': {
        'title': 'Registrar vacina do pet',
        'scopes': ['pets:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Vacina registrada sem duplicidade.'),
    },
    'registrar_vermifugacao_pet': {
        'title': 'Registrar vermifugacao do pet',
        'scopes': ['pets:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Vermifugacao registrada sem duplicidade.'),
    },
    'listar_agendamentos': {
        'title': 'Listar agendamentos',
        'scopes': ['appointments:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_array_output_schema('agendamentos', 'Agendamentos acessiveis ao usuario autenticado.'),
    },
    'interpretar_mensagem_livre_atendimento': {
        'title': 'Interpretar mensagem livre',
        'scopes': ['profile'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Rascunho operacional extraido de mensagens livres.'),
    },
    'assistente_operacional_veterinario': {
        'title': 'Assistente operacional veterinario',
        'scopes': ['profile', 'tutors:write', 'pets:write', 'appointments:write', 'consultations:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Plano operacional e eventual resultado de execucao confirmada.'),
    },
    'cadastrar_tutor_e_pets': {
        'title': 'Cadastrar tutor e pets',
        'scopes': ['tutors:write', 'pets:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Tutor e pets criados ou reaproveitados no PetOrlandia.'),
    },
    'registrar_consulta_clinica': {
        'title': 'Registrar consulta clinica',
        'scopes': ['consultations:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Consulta clinica criada ou atualizada no PetOrlandia.'),
    },
    'registrar_bloco_exames': {
        'title': 'Registrar bloco de exames',
        'scopes': ['exams:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Bloco de exames criado para o paciente.'),
    },
    'criar_exame_imagem': {
        'title': 'Criar exame de imagem',
        'scopes': ['exams:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Exame de imagem criado.'),
    },
    'anexar_pdf_exame_imagem': {
        'title': 'Anexar PDF ao exame de imagem',
        'scopes': ['exams:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('PDF anexado ao exame de imagem.'),
    },
    'liberar_exame_para_clinica': {
        'title': 'Liberar exame para clinica',
        'scopes': ['exams:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Exame liberado para a clinica.'),
    },
    'liberar_exame_para_tutor': {
        'title': 'Liberar exame para tutor',
        'scopes': ['exams:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Exame liberado para o tutor.'),
    },
    'gerar_convite_primeiro_acesso_clinica': {
        'title': 'Gerar convite de primeiro acesso da clinica',
        'scopes': ['exams:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Convite de primeiro acesso gerado.'),
    },
    'gerar_convite_acesso_tutor': {
        'title': 'Gerar convite de acesso do tutor',
        'scopes': ['exams:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Convite de tutor gerado.'),
    },
    'listar_historico_medico_animal': {
        'title': 'Listar historico medico do animal',
        'scopes': ['clinical_summary:read', 'exams:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Historico medico com exames e links humanos de portal/download.'),
    },
    'obter_documento_clinico': {
        'title': 'Obter documento clinico',
        'scopes': ['exams:read'],
        'annotations': _mcp_annotations(True, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Documento clinico com links humanos de portal/download.'),
    },
    'buscar_ou_criar_clinica_requisitante': {
        'title': 'Buscar ou criar clinica requisitante',
        'scopes': ['exams:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Clinica requisitante encontrada ou criada.'),
    },
    'buscar_ou_criar_tutor_animal': {
        'title': 'Buscar ou criar tutor e animal',
        'scopes': ['tutors:write', 'pets:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Tutor e animal encontrados ou criados.'),
    },
    'abrir_importador_laudo_volante': {
        'scopes': ['profile'],
        'annotations': _mcp_annotations(True, idempotent=True),
    },
    'importar_laudo_volante': {
        'scopes': ['tutors:write', 'pets:write', 'exams:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
    },
    'sugerir_modelo_laudo': {
        'title': 'Sugerir modelo de laudo',
        'scopes': ['exams:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema(
            'Modelo de laudo baseado apenas em exames acessiveis ao veterinario.'
        ),
    },
    'agendar_consulta': {
        'title': 'Agendar consulta',
        'scopes': ['appointments:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Consulta, retorno ou compromisso clinico agendado.'),
    },
    'agendar_retorno': {
        'title': 'Agendar retorno',
        'scopes': ['appointments:write'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Retorno agendado a partir de uma consulta existente.'),
    },
    'obter_resumo_clinico_animal': {
        'title': 'Obter resumo clinico do animal',
        'scopes': ['clinical_summary:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Resumo clinico estruturado do paciente.'),
    },
    'listar_agenda_do_dia': {
        'title': 'Listar agenda do dia',
        'scopes': ['appointments:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Agenda diaria com pendencias clinicas resumidas.'),
    },
    'buscar_produtos_loja': {
        'title': 'Buscar produtos da loja',
        'scopes': ['profile'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_array_output_schema('produtos', 'Produtos reais disponiveis na loja PetOrlandia.'),
    },
    'obter_produto_loja': {
        'title': 'Obter produto da loja',
        'scopes': ['profile'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Detalhes reais de um produto da loja PetOrlandia.'),
    },
    'criar_pedido_loja': {
        'title': 'Criar pedido da loja',
        'scopes': ['profile'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Pedido real criado ou atualizado no carrinho do PetOrlandia.'),
    },
    'buscar_paciente': {
        'title': 'Buscar paciente',
        'scopes': ['pets:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_array_output_schema('pacientes', 'Pacientes encontrados no escopo acessivel.'),
    },
    'obter_timeline_clinica': {
        'title': 'Obter timeline clinica',
        'scopes': ['clinical_summary:read', 'exams:read', 'vaccines:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Linha do tempo clinica consolidada do paciente.'),
    },
    'preparar_consulta': {
        'title': 'Preparar consulta',
        'scopes': ['appointments:read', 'clinical_summary:read', 'exams:read', 'vaccines:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Briefing de consulta com resumo, pendencias e perguntas sugeridas.'),
    },
    'listar_pendencias_clinicas': {
        'title': 'Listar pendencias clinicas',
        'scopes': ['appointments:read', 'exams:read', 'vaccines:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Pendencias clinicas do escopo acessivel.'),
    },
    'listar_vacinas_pendentes': {
        'title': 'Listar vacinas pendentes',
        'scopes': ['vaccines:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Vacinas atrasadas e proximas vacinas.'),
    },
    'listar_exames_pendentes': {
        'title': 'Listar exames pendentes',
        'scopes': ['exams:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Exames solicitados ou agendados ainda em aberto.'),
    },
    'listar_retornos_pendentes': {
        'title': 'Listar retornos pendentes',
        'scopes': ['appointments:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Retornos futuros relacionados a consultas.'),
    },
    'gerar_orientacao_tutor': {
        'title': 'Gerar orientacao ao tutor',
        'scopes': ['tutor_guidance:generate'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Rascunho deterministico de orientacao ao tutor.'),
    },
    'gerar_mensagem_whatsapp_tutor': {
        'title': 'Gerar mensagem WhatsApp ao tutor',
        'scopes': ['tutor_guidance:generate'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Mensagem pronta para copiar ou abrir no WhatsApp.'),
    },
    'gerar_handoff_clinico': {
        'title': 'Gerar handoff clinico',
        'scopes': ['handoff:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Handoff clinico resumido para outro profissional.'),
    },
    'listar_alertas_admin': {
        'title': 'Listar alertas administrativos',
        'scopes': ['profile'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_array_output_schema('alertas', 'Alertas administrativos acionaveis do usuario admin.'),
    },
    'resolver_alerta_admin': {
        'title': 'Resolver alerta administrativo',
        'scopes': ['profile'],
        'annotations': _mcp_annotations(False, idempotent=False),
        'outputSchema': _mcp_object_output_schema('Alerta administrativo marcado como lido ou resolvido.'),
    },
}
MAX_MCP_LAUDO_FILE_BYTES = 25 * 1024 * 1024
MCP_FILE_REFERENCE_SCHEMA = {
    'type': 'object',
    'description': (
        'Arquivo do laudo autorizado pelo ChatGPT. Use este campo para anexos; '
        'nao envie caminhos locais como /mnt/data/arquivo.pdf.'
    ),
    'properties': {
        'download_url': {'type': 'string', 'description': 'URL temporaria HTTPS autorizada pelo ChatGPT.'},
        'file_id': {'type': 'string', 'description': 'ID do arquivo no ChatGPT.'},
        'mime_type': {'type': 'string'},
        'file_name': {'type': 'string'},
    },
    'required': ['download_url', 'file_id'],
}
MCP_FILE_REFERENCE_OR_STRING_SCHEMA = {
    'oneOf': [
        MCP_FILE_REFERENCE_SCHEMA,
        {
            'type': 'string',
            'description': (
                'Compatibilidade legada: ID do arquivo ou URL HTTPS temporaria. '
                'Prefira arquivo_pdf/laudo_arquivo no ChatGPT atual.'
            ),
        },
    ]
}

AGENDA_COCKPIT_WIDGET_URI = 'ui://petorlandia/agenda-cockpit-v1.html'
TIMELINE_CLINICA_WIDGET_URI = 'ui://petorlandia/timeline-clinica-v1.html'
ADMIN_COMMAND_CENTER_WIDGET_URI = 'ui://petorlandia/admin-command-center-v1.html'


def _mcp_widget_resource(uri: str, name: str, description: str):
    return {
        'uri': uri,
        'name': name,
        'description': description,
        'mimeType': 'text/html;profile=mcp-app',
    }


def _mcp_dashboard_widget_html(title: str, subtitle: str, mode: str):
    return f"""
<main class="po-shell" data-mode="{mode}">
  <header>
    <div>
      <p>PetOrlandia</p>
      <h1>{title}</h1>
      <span>{subtitle}</span>
    </div>
    <strong id="count">0</strong>
  </header>
  <section id="summary"></section>
  <section id="items" class="items"></section>
</main>
<style>
  :root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  body {{ margin: 0; background: #f8fafc; color: #172033; }}
  .po-shell {{ min-height: 100vh; padding: 18px; box-sizing: border-box; }}
  header {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; border-bottom: 1px solid #dbe3ee; padding-bottom: 14px; }}
  p {{ margin: 0 0 4px; color: #607089; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
  h1 {{ margin: 0; font-size: 24px; line-height: 1.15; }}
  header span {{ display: block; margin-top: 6px; color: #607089; font-size: 14px; }}
  header strong {{ min-width: 42px; min-height: 42px; border-radius: 8px; background: #162033; color: #fff; display: grid; place-items: center; font-size: 18px; }}
  #summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; margin: 16px 0; }}
  .metric, .card {{ background: #fff; border: 1px solid #dbe3ee; border-radius: 8px; box-shadow: 0 1px 2px rgba(15, 23, 42, .04); }}
  .metric {{ padding: 12px; }}
  .metric b {{ display: block; font-size: 20px; margin-bottom: 2px; }}
  .metric span {{ color: #607089; font-size: 12px; }}
  .items {{ display: grid; gap: 10px; }}
  .card {{ padding: 12px; }}
  .card h2 {{ margin: 0 0 6px; font-size: 15px; line-height: 1.25; }}
  .card p {{ margin: 4px 0; color: #334155; font-size: 13px; text-transform: none; letter-spacing: 0; }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
  .tag {{ border-radius: 999px; background: #eef6f5; color: #0f766e; padding: 4px 8px; font-size: 12px; }}
  a {{ color: #0f766e; text-decoration: none; font-weight: 650; }}
</style>
<script>
  const mode = document.querySelector(".po-shell").dataset.mode;
  const summary = document.getElementById("summary");
  const items = document.getElementById("items");
  const count = document.getElementById("count");
  const text = (value) => value === null || value === undefined || value === "" ? "-" : String(value);
  const arr = (value) => Array.isArray(value) ? value : [];
  function metric(label, value) {{
    const node = document.createElement("article");
    node.className = "metric";
    node.innerHTML = `<b>${{text(value)}}</b><span>${{label}}</span>`;
    return node;
  }}
  function tags(values) {{
    const clean = arr(values).filter(Boolean);
    if (!clean.length) return "";
    return `<div class="tags">${{clean.map((v) => `<span class="tag">${{text(v)}}</span>`).join("")}}</div>`;
  }}
  function renderAgenda(payload) {{
    const ag = arr(payload.agendamentos);
    count.textContent = payload.total_agendamentos ?? ag.length;
    summary.append(metric("Data", payload.data || "hoje"), metric("Agendamentos", count.textContent));
    ag.forEach((it) => {{
      const pend = it.pendencias_resumo || {{}};
      const card = document.createElement("article");
      card.className = "card";
      card.innerHTML = `<h2>${{text(it.animal_nome)}} · ${{text(it.horario || it.scheduled_at)}}</h2>
        <p>${{text(it.tipo || it.kind)}} · ${{text(it.status)}}</p>
        <p>${{text(it.observacoes || it.notes)}}</p>
        ${{tags([`Vacinas: ${{pend.vacinas_atrasadas || 0}}`, `Exames: ${{pend.exames_pendentes || 0}}`, `Retornos: ${{pend.retornos_agendados || 0}}`])}}`;
      items.append(card);
    }});
  }}
  function renderTimeline(payload) {{
    const timeline = arr(payload.timeline);
    count.textContent = timeline.length;
    const animal = payload.animal || {{}};
    summary.append(metric("Paciente", animal.nome || animal.name), metric("Eventos", timeline.length), metric("Pendências", arr(payload.pendencias).length));
    timeline.forEach((event) => {{
      const card = document.createElement("article");
      card.className = "card";
      card.innerHTML = `<h2>${{text(event.titulo || event.tipo)}}</h2><p>${{text(event.data || event.quando)}}</p><p>${{text(event.descricao)}}</p>${{tags(event.tags)}}`;
      items.append(card);
    }});
  }}
  function renderAdmin(payload) {{
    const alerts = arr(payload.alertas);
    count.textContent = payload.total_abertos ?? alerts.length;
    summary.append(metric("Abertos", payload.total_abertos ?? alerts.length), metric("Críticos", payload.total_criticos ?? 0), metric("Não lidos", payload.total_nao_lidos ?? 0));
    alerts.forEach((alerta) => {{
      const card = document.createElement("article");
      card.className = "card";
      const link = alerta.url ? `<p><a target="_blank" href="${{alerta.url}}">Abrir no PetOrlandia</a></p>` : "";
      card.innerHTML = `<h2>${{text(alerta.titulo)}}</h2><p>${{text(alerta.corpo)}}</p><p>${{text(alerta.prioridade)}} · ${{text(alerta.status)}} · ${{text(alerta.criado_em)}}</p>${{link}}`;
      items.append(card);
    }});
  }}
  function render(payload) {{
    summary.innerHTML = "";
    items.innerHTML = "";
    if (mode === "agenda") renderAgenda(payload || {{}});
    if (mode === "timeline") renderTimeline(payload || {{}});
    if (mode === "admin") renderAdmin(payload || {{}});
  }}
  render(window.openai?.toolOutput || {{}});
  window.addEventListener("openai:set_globals", (event) => render(event.detail?.globals?.toolOutput || window.openai?.toolOutput || {{}}), {{ passive: true }});
</script>
""".strip()



def _mcp_finalize_tool_descriptors(tools: list[dict]) -> list[dict]:
    for tool in tools:
        defaults = MCP_TOOL_DESCRIPTOR_DEFAULTS.get(tool.get('name'), {})
        title = defaults.get('title')
        if title:
            tool.setdefault('title', title)

        default_annotations = defaults.get('annotations') or _mcp_annotations(False, idempotent=False)
        annotations = {**default_annotations, **(tool.get('annotations') or {})}
        for key in ('readOnlyHint', 'destructiveHint', 'openWorldHint'):
            annotations.setdefault(key, default_annotations[key])
        tool['annotations'] = annotations

        tool.setdefault('outputSchema', defaults.get('outputSchema') or _mcp_object_output_schema())

        scopes = defaults.get('scopes') or []
        if scopes:
            security_schemes = [{'type': 'oauth2', 'scopes': scopes}]
            tool.setdefault('securitySchemes', security_schemes)
            meta = tool.setdefault('_meta', {})
            meta.setdefault('securitySchemes', security_schemes)

    return tools


def _mcp_extract_file_reference(payload: dict, *field_names: str) -> dict | None:
    for field_name in field_names:
        value = payload.get(field_name)
        if isinstance(value, dict) and value.get('download_url') and value.get('file_id'):
            return value
    return None


def _mcp_laudo_volante_widget_html():
    return """
<main class="po-widget">
  <section class="hero">
    <div>
      <p class="eyebrow">PetOrlandia</p>
      <h1>Enviar laudo volante</h1>
      <p class="subtitle">Revise, grave e envie os links sem sair desta tela.</p>
    </div>
    <span id="status-pill" class="pill">Rascunho</span>
  </section>

  <section class="grid">
    <article>
      <span>Clinica</span>
      <strong id="clinica-nome">-</strong>
      <small id="clinica-contato"></small>
    </article>
    <article>
      <span>Tutor</span>
      <strong id="tutor-nome">-</strong>
      <small id="tutor-contato"></small>
    </article>
    <article>
      <span>Animal</span>
      <strong id="animal-nome">-</strong>
      <small id="animal-detalhes"></small>
    </article>
    <article>
      <span>Exame</span>
      <strong id="exame-nome">-</strong>
      <small id="exame-data"></small>
    </article>
  </section>

  <section class="report-strip">
    <div>
      <strong>Laudo recebido</strong>
      <small id="laudo-status">Cole o texto do laudo ou anexe o arquivo.</small>
    </div>
    <button id="abrir-laudo-inicial" type="button" class="secondary" disabled>Abrir laudo</button>
  </section>

  <label class="field">
    <span>Mensagem para a clinica</span>
    <textarea id="mensagem" rows="3"></textarea>
  </label>

  <label class="field">
    <span>Mensagem para o tutor</span>
    <textarea id="mensagem-tutor" rows="3"></textarea>
  </label>

  <label class="field">
    <span>Resumo do laudo</span>
    <textarea id="laudo" rows="6"></textarea>
  </label>

  <section class="file-tools">
    <div>
      <strong>Anexo do laudo</strong>
      <small id="arquivo-status">Opcional. Se o ChatGPT nao conseguir enviar o PDF, cole o texto integral acima.</small>
    </div>
    <input id="arquivo-upload" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx" hidden>
    <button id="selecionar-arquivo" type="button" class="secondary">Selecionar/enviar arquivo</button>
  </section>

  <section id="missing" class="missing" hidden></section>

  <footer>
    <button id="confirmar" type="button">Gravar e preparar mensagens</button>
    <p id="feedback"></p>
  </footer>

  <section id="resultado" class="result" hidden>
    <div class="result-head">
      <div>
        <span>Pronto para enviar</span>
        <h2>Laudo salvo no PetOrlandia</h2>
      </div>
      <button id="abrir-laudo-final" type="button" class="secondary" disabled>Abrir laudo</button>
    </div>

    <div class="actions-grid">
      <article class="action-card">
        <div>
          <span>Clinica</span>
          <strong id="acao-clinica-nome">-</strong>
        </div>
        <p id="acao-clinica-msg"></p>
        <div class="action-buttons">
          <button id="enviar-clinica" type="button" class="secondary" disabled>Enviar WhatsApp</button>
          <button id="copiar-clinica" type="button" class="light">Copiar mensagem</button>
          <button id="abrir-clinica" type="button" class="light" disabled>Abrir link</button>
        </div>
      </article>

      <article class="action-card">
        <div>
          <span>Tutor</span>
          <strong id="acao-tutor-nome">-</strong>
        </div>
        <p id="acao-tutor-msg"></p>
        <div class="action-buttons">
          <button id="enviar-tutor" type="button" class="secondary" disabled>Enviar WhatsApp</button>
          <button id="copiar-tutor" type="button" class="light">Copiar mensagem</button>
          <button id="abrir-tutor" type="button" class="light" disabled>Abrir link</button>
        </div>
      </article>
    </div>
  </section>
</main>

<style>
  :root {
    color: #0f172a;
    background: #f7faf9;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  * { box-sizing: border-box; }
  body { margin: 0; }
  .po-widget { padding: 18px; max-width: 820px; margin: 0 auto; }
  .hero { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
  .eyebrow { margin: 0 0 4px; font-size: 12px; color: #047857; font-weight: 800; text-transform: uppercase; letter-spacing: 0; }
  h1 { margin: 0; font-size: 24px; line-height: 1.15; }
  .subtitle { margin: 7px 0 0; color: #475569; font-size: 13px; line-height: 1.35; }
  .pill { flex: none; border: 1px solid #99f6e4; color: #0f766e; background: #ecfeff; border-radius: 999px; padding: 7px 10px; font-size: 12px; font-weight: 800; }
  .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
  article { border: 1px solid #dbe3ea; background: #ffffff; border-radius: 8px; padding: 12px; min-height: 86px; }
  article span, .field span { display: block; color: #64748b; font-size: 12px; font-weight: 800; margin-bottom: 6px; }
  article strong { display: block; font-size: 16px; line-height: 1.25; overflow-wrap: anywhere; }
  article small { display: block; margin-top: 6px; color: #475569; line-height: 1.35; overflow-wrap: anywhere; }
  .report-strip { align-items: center; background: #ffffff; border: 1px solid #bbf7d0; border-radius: 8px; display: flex; gap: 12px; justify-content: space-between; margin: 12px 0; padding: 12px; }
  .report-strip strong { display: block; color: #14532d; font-size: 14px; }
  .report-strip small { color: #475569; display: block; line-height: 1.35; margin-top: 3px; overflow-wrap: anywhere; }
  .field { display: block; margin: 12px 0; }
  textarea { width: 100%; resize: vertical; border: 1px solid #cbd5e1; border-radius: 8px; padding: 11px 12px; font: inherit; line-height: 1.45; background: #ffffff; color: #0f172a; }
  textarea:focus { outline: 3px solid #bbf7d0; border-color: #059669; }
  .file-tools { border: 1px dashed #99f6e4; background: #f0fdfa; border-radius: 8px; padding: 11px 12px; margin: 12px 0; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .file-tools strong { display: block; color: #0f766e; font-size: 13px; }
  .file-tools small { display: block; color: #475569; margin-top: 3px; line-height: 1.35; }
  .missing { border: 1px solid #fde68a; background: #fffbeb; color: #92400e; border-radius: 8px; padding: 11px 12px; margin: 12px 0; line-height: 1.4; }
  footer { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 14px; }
  button { border: 0; border-radius: 8px; background: #10b981; color: white; padding: 12px 16px; font-weight: 900; cursor: pointer; }
  button.secondary { background: #0f766e; padding: 10px 12px; }
  button.light { background: #e2e8f0; color: #0f172a; padding: 10px 12px; }
  button:disabled { cursor: not-allowed; background: #94a3b8; }
  #feedback { margin: 0; color: #334155; font-size: 13px; }
  .result { border-top: 1px solid #dbe3ea; margin-top: 18px; padding-top: 16px; }
  .result-head { align-items: center; display: flex; gap: 12px; justify-content: space-between; margin-bottom: 12px; }
  .result-head span { color: #047857; display: block; font-size: 12px; font-weight: 900; text-transform: uppercase; }
  .result-head h2 { font-size: 18px; line-height: 1.2; margin: 3px 0 0; }
  .actions-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .action-card { min-height: 0; }
  .action-card p { color: #334155; font-size: 13px; line-height: 1.45; margin: 10px 0 12px; white-space: pre-wrap; }
  .action-buttons { display: flex; flex-wrap: wrap; gap: 8px; }
  .action-buttons button { flex: 1 1 130px; min-height: 40px; }
  @media (max-width: 560px) {
    .po-widget { padding: 14px; }
    .hero { align-items: flex-start; flex-direction: column; }
    .grid { grid-template-columns: 1fr; }
    .report-strip, .result-head { align-items: stretch; flex-direction: column; }
    .actions-grid { grid-template-columns: 1fr; }
    h1 { font-size: 21px; }
    button { width: 100%; }
  }
</style>

<script>
  const fields = {
    clinicaNome: document.getElementById("clinica-nome"),
    clinicaContato: document.getElementById("clinica-contato"),
    tutorNome: document.getElementById("tutor-nome"),
    tutorContato: document.getElementById("tutor-contato"),
    animalNome: document.getElementById("animal-nome"),
    animalDetalhes: document.getElementById("animal-detalhes"),
    exameNome: document.getElementById("exame-nome"),
    exameData: document.getElementById("exame-data"),
    mensagem: document.getElementById("mensagem"),
    mensagemTutor: document.getElementById("mensagem-tutor"),
    laudo: document.getElementById("laudo"),
    missing: document.getElementById("missing"),
    feedback: document.getElementById("feedback"),
    fileStatus: document.getElementById("arquivo-status"),
    fileInput: document.getElementById("arquivo-upload"),
    fileButton: document.getElementById("selecionar-arquivo"),
    button: document.getElementById("confirmar"),
    pill: document.getElementById("status-pill"),
    reportStatus: document.getElementById("laudo-status"),
    openInitialReport: document.getElementById("abrir-laudo-inicial"),
    result: document.getElementById("resultado"),
    openFinalReport: document.getElementById("abrir-laudo-final"),
    actionClinicName: document.getElementById("acao-clinica-nome"),
    actionClinicMsg: document.getElementById("acao-clinica-msg"),
    actionTutorName: document.getElementById("acao-tutor-nome"),
    actionTutorMsg: document.getElementById("acao-tutor-msg"),
    sendClinic: document.getElementById("enviar-clinica"),
    copyClinic: document.getElementById("copiar-clinica"),
    openClinic: document.getElementById("abrir-clinica"),
    sendTutor: document.getElementById("enviar-tutor"),
    copyTutor: document.getElementById("copiar-tutor"),
    openTutor: document.getElementById("abrir-tutor")
  };

  let currentDraft = {};
  let selectedFileRef = null;
  let initialReportUrl = "";
  const text = (value) => value == null || value === "" ? "-" : String(value);
  const compact = (items) => items.filter(Boolean).join(" - ");
  const first = (...values) => values.find((value) => value != null && String(value).trim() !== "") || "";
  const isLocalChatGptPath = (value) => {
    const raw = String(value || "").trim().toLowerCase();
    return raw.startsWith("/mnt/data/")
      || raw.startsWith("/tmp/")
      || raw.startsWith("file:")
      || /^[a-z]:\\/.test(String(value || "").trim());
  };
  const usableReportUrl = (...values) => values.find((value) => {
    const raw = String(value || "").trim();
    return raw && !isLocalChatGptPath(raw);
  }) || "";

  function applyExternalButton(button, url) {
    button.disabled = !url;
    button.dataset.url = url || "";
  }

  async function openUrl(url) {
    if (!url) return;
    if (window.openai?.openExternal) {
      await window.openai.openExternal({ href: url });
      return;
    }
    window.open(url, "_blank", "noopener");
  }

  async function copyText(value, button) {
    const textToCopy = String(value || "").trim();
    if (!textToCopy) return;
    try {
      await navigator.clipboard.writeText(textToCopy);
      const original = button.textContent;
      button.textContent = "Copiado";
      window.setTimeout(() => { button.textContent = original; }, 1400);
    } catch (error) {
      fields.feedback.textContent = "Nao consegui copiar automaticamente. Selecione o texto da mensagem.";
    }
  }

  function digitsOnly(value) {
    return String(value || "").replace(/\\D/g, "");
  }

  function whatsappUrl(phone, message) {
    let digits = digitsOnly(phone);
    if (!digits) return "";
    if (!digits.startsWith("55")) digits = "55" + digits;
    return "https://wa.me/" + digits + "?text=" + encodeURIComponent(message || "");
  }

  function defaultClinicMessage(clinica, animal, exame, url) {
    const animalName = animal?.nome || animal?.name || "paciente";
    const exameName = exame?.nome || exame?.tipo || "laudo";
    const base = "Laudo de " + exameName + " do paciente " + animalName + " disponivel no PetOrlandia.";
    return url ? base + "\\n\\nAcesse: " + url : base;
  }

  function defaultTutorMessage(clinica, animal, exame, url) {
    const animalName = animal?.nome || animal?.name || "paciente";
    const exameName = exame?.nome || exame?.tipo || "exame";
    const clinicName = clinica?.nome || "clinica";
    const base = "O laudo de " + exameName + " do paciente " + animalName + " foi disponibilizado pela " + clinicName + ".";
    return url ? base + "\\n\\nAcesse: " + url : base;
  }

  function render(output) {
    currentDraft = output?.rascunho || output || {};
    const clinica = currentDraft.clinica || {};
    const tutor = currentDraft.tutor || {};
    const animal = currentDraft.animal || {};
    const exame = currentDraft.exame || {};
    fields.clinicaNome.textContent = text(clinica.nome);
    fields.clinicaContato.textContent = compact([clinica.email, clinica.telefone, clinica.cnpj]);
    fields.tutorNome.textContent = text(tutor.nome);
    fields.tutorContato.textContent = compact([tutor.telefone, tutor.email]);
    fields.animalNome.textContent = text(animal.nome);
    fields.animalDetalhes.textContent = compact([animal.especie, animal.raca, animal.sexo, animal.idade]);
    fields.exameNome.textContent = text(exame.nome || exame.tipo);
    fields.exameData.textContent = text(exame.data || currentDraft.data_exame);
    selectedFileRef = currentDraft.laudo_arquivo || currentDraft.arquivo_laudo || null;
    initialReportUrl = usableReportUrl(currentDraft.laudo_url, selectedFileRef?.download_url);
    fields.reportStatus.textContent = initialReportUrl
      ? "Link do laudo pronto para consulta."
      : (selectedFileRef?.file_name ? "Arquivo autorizado pelo ChatGPT: " + selectedFileRef.file_name : "Cole o texto do laudo ou anexe o arquivo.");
    applyExternalButton(fields.openInitialReport, initialReportUrl);
    fields.mensagem.value = currentDraft.mensagem_clinica || defaultClinicMessage(clinica, animal, exame, initialReportUrl);
    fields.mensagemTutor.value = currentDraft.mensagem_tutor || defaultTutorMessage(clinica, animal, exame, initialReportUrl);
    fields.laudo.value = currentDraft.laudo_texto || exame.conclusao || exame.achados || "";
    fields.fileStatus.textContent = selectedFileRef?.file_name
      ? "Arquivo autorizado pelo ChatGPT: " + selectedFileRef.file_name
      : (currentDraft.laudo_filename ? "Arquivo informado: " + currentDraft.laudo_filename : "Opcional. Se o ChatGPT nao conseguir enviar o PDF, cole o texto integral acima.");

    const missing = output?.campos_a_confirmar || [];
    fields.missing.hidden = missing.length === 0;
    fields.missing.textContent = missing.length ? "Conferir antes de gravar: " + missing.join(", ") : "";
    fields.pill.textContent = missing.length ? "Conferir dados" : "Pronto para gravar";
  }

  function showAction(kind, data, fallback) {
    const isClinic = kind === "clinica";
    const nameField = isClinic ? fields.actionClinicName : fields.actionTutorName;
    const msgField = isClinic ? fields.actionClinicMsg : fields.actionTutorMsg;
    const sendButton = isClinic ? fields.sendClinic : fields.sendTutor;
    const copyButton = isClinic ? fields.copyClinic : fields.copyTutor;
    const openButton = isClinic ? fields.openClinic : fields.openTutor;
    const message = data?.mensagem || fallback.message || "";
    const url = data?.url || fallback.url || "";
    const waUrl = data?.whatsapp_url || whatsappUrl(fallback.phone, message);

    nameField.textContent = text(fallback.name);
    msgField.textContent = message || "Mensagem pronta indisponivel.";
    sendButton.disabled = !waUrl;
    sendButton.dataset.url = waUrl || "";
    copyButton.dataset.message = message || "";
    applyExternalButton(openButton, url);
  }

  function showResult(payload) {
    const clinica = currentDraft.clinica || {};
    const tutor = currentDraft.tutor || {};
    const animal = currentDraft.animal || {};
    const exame = currentDraft.exame || {};
    const links = payload?.links || {};
    const access = payload?.links_primeiro_acesso || {};
    const comm = payload?.comunicacao || {};
    const finalReportUrl = usableReportUrl(
      links.laudo,
      payload?.exame?.laudo_url,
      initialReportUrl,
      access.clinica,
      access.tutor
    );

    applyExternalButton(fields.openFinalReport, finalReportUrl);
    showAction("clinica", comm.clinica, {
      name: payload?.clinica?.nome || clinica.nome,
      phone: clinica.telefone || clinica.phone,
      url: access.clinica || links.clinica || finalReportUrl,
      message: fields.mensagem.value || defaultClinicMessage(clinica, animal, exame, access.clinica || finalReportUrl)
    });
    showAction("tutor", comm.tutor, {
      name: payload?.tutor?.nome || tutor.nome,
      phone: tutor.telefone || tutor.phone,
      url: access.tutor || links.tutor || finalReportUrl,
      message: fields.mensagemTutor.value || defaultTutorMessage(clinica, animal, exame, access.tutor || finalReportUrl)
    });
    fields.result.hidden = false;
  }

  async function selectOrUploadFile() {
    try {
      if (window.openai?.selectFiles) {
        const files = await window.openai.selectFiles();
        const file = files?.[0];
        if (file?.fileId) {
          const downloadUrlResult = await window.openai.getFileDownloadUrl({ fileId: file.fileId });
          selectedFileRef = {
            file_id: file.fileId,
            file_name: file.fileName,
            mime_type: file.mimeType,
            download_url: typeof downloadUrlResult === "string" ? downloadUrlResult : (downloadUrlResult?.download_url || downloadUrlResult?.url)
          };
          fields.fileStatus.textContent = "Arquivo autorizado pelo ChatGPT: " + (file.fileName || file.fileId);
          return;
        }
      }
      fields.fileInput.click();
    } catch (error) {
      fields.fileStatus.textContent = error?.message || "Nao foi possivel selecionar o arquivo. Cole o texto integral do laudo.";
    }
  }

  async function uploadPickedFile(event) {
    const file = event.target.files?.[0];
    if (!file || !window.openai?.uploadFile || !window.openai?.getFileDownloadUrl) {
      fields.fileStatus.textContent = "Upload de arquivo indisponivel neste ChatGPT. Cole o texto integral do laudo.";
      return;
    }
    fields.fileStatus.textContent = "Enviando arquivo ao ChatGPT...";
    try {
      const uploaded = await window.openai.uploadFile(file);
      const fileId = uploaded?.fileId || uploaded?.file_id;
      const downloadUrlResult = await window.openai.getFileDownloadUrl({ fileId });
      selectedFileRef = {
        file_id: fileId,
        file_name: file.name,
        mime_type: file.type,
        download_url: typeof downloadUrlResult === "string" ? downloadUrlResult : (downloadUrlResult?.download_url || downloadUrlResult?.url)
      };
      fields.fileStatus.textContent = "Arquivo autorizado pelo ChatGPT: " + file.name;
      fields.reportStatus.textContent = "Arquivo do laudo pronto para gravacao.";
    } catch (error) {
      fields.fileStatus.textContent = error?.message || "Nao foi possivel enviar o arquivo. Cole o texto integral do laudo.";
    }
  }

  async function confirmImport() {
    if (!window.openai?.callTool) {
      fields.feedback.textContent = "Abra este painel dentro do ChatGPT para gravar.";
      return;
    }
    fields.button.disabled = true;
    fields.feedback.textContent = "Gravando no PetOrlandia...";
    try {
      const args = {
        ...currentDraft,
        laudo_texto: fields.laudo.value,
        mensagem_clinica: fields.mensagem.value,
        mensagem_tutor: fields.mensagemTutor.value,
        confirmar_gravacao: "sim"
      };
      if (selectedFileRef?.download_url && selectedFileRef?.file_id) {
        args.laudo_arquivo = selectedFileRef;
      }
      const result = await window.openai.callTool("importar_laudo_volante", args);
      const payload = result?.structuredContent || result;
      fields.feedback.textContent = payload?.exame?.exame_id
        ? "Laudo gravado. Use os botoes abaixo para enviar os acessos."
        : "Solicitacao enviada. Confira a resposta no chat.";
      fields.pill.textContent = "Gravado";
      showResult(payload);
    } catch (error) {
      fields.feedback.textContent = error?.message || "Nao foi possivel gravar agora.";
      fields.button.disabled = false;
    }
  }

  fields.openInitialReport.addEventListener("click", () => openUrl(fields.openInitialReport.dataset.url));
  fields.openFinalReport.addEventListener("click", () => openUrl(fields.openFinalReport.dataset.url));
  fields.sendClinic.addEventListener("click", () => openUrl(fields.sendClinic.dataset.url));
  fields.sendTutor.addEventListener("click", () => openUrl(fields.sendTutor.dataset.url));
  fields.openClinic.addEventListener("click", () => openUrl(fields.openClinic.dataset.url));
  fields.openTutor.addEventListener("click", () => openUrl(fields.openTutor.dataset.url));
  fields.copyClinic.addEventListener("click", () => copyText(fields.copyClinic.dataset.message, fields.copyClinic));
  fields.copyTutor.addEventListener("click", () => copyText(fields.copyTutor.dataset.message, fields.copyTutor));
  fields.fileButton.addEventListener("click", selectOrUploadFile);
  fields.fileInput.addEventListener("change", uploadPickedFile);
  fields.button.addEventListener("click", confirmImport);
  render(window.openai?.toolOutput || {});
  window.addEventListener("openai:set_globals", (event) => {
    render(event.detail?.globals?.toolOutput || window.openai?.toolOutput || {});
  }, { passive: true });
</script>
""".strip()


def _mcp_laudo_volante_widget_resource():
    return {
        'uri': LAUDO_VOLANTE_WIDGET_URI,
        'name': 'Enviar laudo volante',
        'description': 'Aplicativo simples para revisar, gravar e enviar laudo de ultrassonografista volante.',
        'mimeType': 'text/html;profile=mcp-app',
    }


def _mcp_widget_catalog():
    return {
        LAUDO_VOLANTE_WIDGET_URI: (
            _mcp_laudo_volante_widget_resource(),
            _mcp_laudo_volante_widget_html(),
            'Painel para revisar clinica, tutor, animal e laudo antes de gravar o exame no PetOrlandia.',
            True,
            ['https://wa.me'],
        ),
        AGENDA_COCKPIT_WIDGET_URI: (
            _mcp_widget_resource(
                AGENDA_COCKPIT_WIDGET_URI,
                'Agenda e pendencias do dia',
                'Painel operacional para revisar agenda diaria e pendencias antes dos atendimentos.',
            ),
            _mcp_dashboard_widget_html(
                'Agenda do dia',
                'Pacientes, horarios e pendencias clinicas em uma unica visao.',
                'agenda',
            ),
            'Painel de agenda diaria com pacientes, horarios e pendencias resumidas.',
            True,
            [],
        ),
        TIMELINE_CLINICA_WIDGET_URI: (
            _mcp_widget_resource(
                TIMELINE_CLINICA_WIDGET_URI,
                'Timeline clinica do paciente',
                'Linha do tempo de consultas, exames, vacinas, documentos e pendencias.',
            ),
            _mcp_dashboard_widget_html(
                'Timeline clinica',
                'Historico consolidado do paciente para orientar a proxima decisao.',
                'timeline',
            ),
            'Painel de timeline clinica consolidada do paciente.',
            True,
            [],
        ),
        ADMIN_COMMAND_CENTER_WIDGET_URI: (
            _mcp_widget_resource(
                ADMIN_COMMAND_CENTER_WIDGET_URI,
                'Central admin',
                'Fila de alertas administrativos acionaveis do PetOrlandia.',
            ),
            _mcp_dashboard_widget_html(
                'Central admin',
                'Alertas de compras, servicos, carreiras, petsitter e operacao.',
                'admin',
            ),
            'Painel administrativo com alertas abertos e links de acao.',
            True,
            [],
        ),
    }


def _mcp_widget_response(req_id, uri: str):
    catalog = _mcp_widget_catalog()
    if uri not in catalog:
        return _mcp_err(req_id, -32004, f'Resource not found: {uri}')
    resource, html, description, prefers_border, redirect_domains = catalog[uri]
    return _mcp_ok(req_id, {
        'contents': [
            {
                **resource,
                'text': html,
                '_meta': {
                    'openai/widgetDescription': description,
                    'openai/widgetPrefersBorder': prefers_border,
                    'openai/widgetCSP': {
                        'connect_domains': [],
                        'resource_domains': [],
                        'redirect_domains': [_oauth_issuer(), *redirect_domains],
                    },
                    'ui': {
                        'domain': _oauth_issuer(),
                        'csp': {
                            'connectDomains': [_oauth_issuer()],
                            'resourceDomains': [_oauth_issuer()],
                        },
                    },
                },
            }
        ]
    })


def _mcp_user_is_admin(user: User) -> bool:
    return (getattr(user, 'role', '') or '').strip().lower() == 'admin'


def _mcp_local_date_text(value):
    if not value:
        return None
    if hasattr(value, 'astimezone'):
        return _integration_format_datetime(value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _mcp_owner_payload(owner):
    if not owner:
        return {}
    return {
        'id': owner.id,
        'nome': owner.name,
        'email': owner.email,
        'telefone': owner.phone,
    }


def _mcp_animal_payload(animal: Animal):
    spec = getattr(animal, 'species', None)
    breed = getattr(animal, 'breed', None)
    return {
        'id': animal.id,
        'nome': animal.name,
        'especie': spec.name if hasattr(spec, 'name') else (str(spec) if spec else None),
        'raca': breed.name if hasattr(breed, 'name') else (str(breed) if breed else None),
        'sexo': animal.sex,
        'idade': animal.age,
        'peso': animal.peso,
        'status': animal.status,
        'tutor': _mcp_owner_payload(getattr(animal, 'owner', None)),
        'clinica_id': getattr(animal, 'clinica_id', None),
    }


def _mcp_search_animals(user: User, termo: str | None = None, limit: int = 10):
    query = _integration_accessible_animals_query(user).order_by(Animal.name.asc())
    termo = (termo or '').strip()
    if termo:
        token = f'%{termo.lower()}%'
        query = query.join(User, Animal.user_id == User.id).filter(
            db.or_(
                db.func.lower(Animal.name).like(token),
                db.func.lower(User.name).like(token),
                db.func.lower(User.email).like(token),
                db.func.lower(User.phone).like(token),
            )
        )
    return query.limit(max(1, min(int(limit or 10), 25))).all()


def _mcp_build_timeline(user: User, animal: Animal):
    summary = _integration_build_clinical_summary(user, animal)
    timeline = []
    for consulta in (
        _integration_accessible_consultas_query(user)
        .filter(Consulta.animal_id == animal.id)
        .order_by(Consulta.created_at.desc())
        .limit(12)
        .all()
    ):
        timeline.append({
            'tipo': 'consulta',
            'titulo': f'Consulta #{consulta.id}',
            'data': _mcp_local_date_text(getattr(consulta, 'finalizada_em', None) or getattr(consulta, 'created_at', None)),
            'descricao': getattr(consulta, 'queixa_principal', None) or getattr(consulta, 'conduta', None) or getattr(consulta, 'historico', None),
            'tags': [getattr(consulta, 'status', None), 'consulta'],
        })
    for exame in (
        ExameImagem.query.filter_by(animal_id=animal.id)
        .order_by(ExameImagem.data_exame.desc().nullslast(), ExameImagem.created_at.desc())
        .limit(12)
        .all()
    ):
        if not _integration_user_can_access_exame_imagem(user, exame):
            continue
        timeline.append({
            'tipo': 'exame_imagem',
            'titulo': exame.titulo or exame.tipo_exame,
            'data': _mcp_local_date_text(exame.data_exame or exame.created_at),
            'descricao': exame.impressao_diagnostica or exame.descricao,
            'tags': [exame.status, exame.tipo_exame],
        })
    for vacina in (
        Vacina.query.filter_by(animal_id=animal.id)
        .order_by(Vacina.aplicada_em.desc().nullslast(), Vacina.id.desc())
        .limit(12)
        .all()
    ):
        timeline.append({
            'tipo': 'vacina',
            'titulo': getattr(vacina, 'nome', None) or getattr(vacina, 'vacina', None) or 'Vacina',
            'data': _mcp_local_date_text(getattr(vacina, 'aplicada_em', None)),
            'descricao': getattr(vacina, 'observacoes', None) or getattr(vacina, 'fabricante', None),
            'tags': ['aplicada' if getattr(vacina, 'aplicada', False) else 'pendente', 'vacina'],
        })
    for doc in (
        AnimalDocumento.query.filter_by(animal_id=animal.id)
        .order_by(AnimalDocumento.uploaded_at.desc())
        .limit(10)
        .all()
    ):
        timeline.append({
            'tipo': 'documento',
            'titulo': doc.filename,
            'data': _mcp_local_date_text(doc.uploaded_at),
            'descricao': doc.descricao,
            'tags': ['documento'],
            'url': doc.file_url,
        })
    timeline.sort(key=lambda item: item.get('data') or '', reverse=True)
    pendencias = summary.get('pendencias') or {}
    pendencias_lista = []
    for key, value in pendencias.items():
        if isinstance(value, list):
            pendencias_lista.extend({'tipo': key, **item} if isinstance(item, dict) else {'tipo': key, 'descricao': item} for item in value)
    return {
        'animal': _mcp_animal_payload(animal),
        'resumo': summary,
        'pendencias': pendencias_lista[:20],
        'timeline': timeline[:30],
    }


def _mcp_build_consult_prep(user: User, animal: Animal, appointment_id: int | None = None):
    timeline = _mcp_build_timeline(user, animal)
    appointment = None
    if appointment_id:
        appointment = (
            _integration_accessible_appointments_query(user)
            .filter(Appointment.id == appointment_id, Appointment.animal_id == animal.id)
            .first()
        )
    pendencias = timeline.get('pendencias') or []
    perguntas = [
        'Houve mudanca de apetite, sede, urina ou fezes desde o ultimo contato?',
        'O tutor administrou medicacoes, suplementos ou tratamentos em casa?',
        'Existe algum exame, vacina ou retorno pendente que precisa ser resolvido hoje?',
    ]
    if any((item.get('tipo') or '').startswith('vacinas') for item in pendencias if isinstance(item, dict)):
        perguntas.append('Confirmar historico vacinal recente e possiveis reacoes anteriores.')
    if any((item.get('tipo') or '').startswith('exames') for item in pendencias if isinstance(item, dict)):
        perguntas.append('Confirmar se os exames solicitados foram realizados e anexar resultados.')
    return {
        'animal': timeline['animal'],
        'appointment': {
            'id': appointment.id,
            'horario': _integration_format_datetime(appointment.scheduled_at),
            'status': appointment.status,
            'tipo': appointment.kind,
            'observacoes': appointment.notes,
        } if appointment else None,
        'resumo': timeline['resumo'],
        'pendencias_prioritarias': pendencias[:10],
        'perguntas_sugeridas': perguntas,
        'proximas_acoes': [
            'Revisar timeline antes de atender.',
            'Atualizar conduta e exames solicitados ao final.',
            'Gerar orientacao ao tutor depois da consulta, se houver plano definido.',
        ],
    }


def _mcp_admin_alert_payload(note: AdminActionNotification):
    return {
        'id': note.id,
        'titulo': note.title,
        'corpo': note.body,
        'tipo_evento': note.event_type,
        'tipo_entidade': note.entity_type,
        'entidade_id': note.entity_id,
        'prioridade': note.priority,
        'status': note.status,
        'url': note.url,
        'criado_em': _mcp_local_date_text(note.created_at),
        'lido_em': _mcp_local_date_text(note.read_at),
        'resolvido_em': _mcp_local_date_text(note.resolved_at),
    }


def _mcp_admin_alerts(user: User, status='open', limit=30):
    query = AdminActionNotification.query.filter_by(recipient_user_id=user.id)
    status = (status or 'open').strip().lower()
    if status == 'open':
        query = query.filter(AdminActionNotification.status.in_(['unread', 'read']))
    elif status in {'unread', 'read', 'resolved', 'archived'}:
        query = query.filter(AdminActionNotification.status == status)
    elif status != 'all':
        query = query.filter(AdminActionNotification.status.in_(['unread', 'read']))
    notes = (
        query.order_by(
            db.case((AdminActionNotification.priority == 'critical', 0), (AdminActionNotification.priority == 'high', 1), else_=2),
            AdminActionNotification.created_at.desc(),
        )
        .limit(max(1, min(int(limit or 30), 100)))
        .all()
    )
    open_count = AdminActionNotification.query.filter(
        AdminActionNotification.recipient_user_id == user.id,
        AdminActionNotification.status.in_(['unread', 'read']),
    ).count()
    return {
        'total_abertos': open_count,
        'total_nao_lidos': AdminActionNotification.query.filter_by(recipient_user_id=user.id, status='unread').count(),
        'total_criticos': AdminActionNotification.query.filter(
            AdminActionNotification.recipient_user_id == user.id,
            AdminActionNotification.status.in_(['unread', 'read']),
            AdminActionNotification.priority.in_(['critical', 'high']),
        ).count(),
        'alertas': [_mcp_admin_alert_payload(note) for note in notes],
    }


def _mcp_money(value):
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return {
        'valor': round(amount, 2),
        'formatado': f'R$ {amount:.2f}'.replace('.', ','),
    }


def _mcp_product_variant_payload(variant: ProductVariant):
    return {
        'id': variant.id,
        'nome': variant.display_name,
        'sku': variant.sku,
        'codigo_barras': variant.barcode,
        'dosagem': variant.dosage,
        'embalagem': variant.package_quantity,
        'peso_volume': variant.weight_volume,
        'estoque': variant.stock,
        'preco_publico': _mcp_money(variant.preco_publico),
        'imagem_url': variant.image_url,
        'status': variant.status,
    }


def _mcp_product_payload(product: Product, *, include_variants=True):
    variants = product.active_variants if include_variants else []
    seller = None
    if getattr(product, 'clinica', None):
        seller = {'tipo': 'clinica', 'id': product.clinica.id, 'nome': product.clinica.nome}
    elif getattr(product, 'casa_de_racao', None):
        seller = {'tipo': 'casa_de_racao', 'id': product.casa_de_racao.id, 'nome': product.casa_de_racao.nome}
    return {
        'id': product.id,
        'nome': product.name,
        'descricao': product.description,
        'categoria': product.category,
        'categoria_label': product.category_label,
        'estoque': product.stock,
        'preco_publico': _mcp_money(product.public_price_min),
        'preco_publico_max': _mcp_money(product.public_price_max),
        'imagem_url': product.image_url,
        'url': url_for('produto_detail', product_id=product.id, _external=True),
        'vendedor': seller,
        'variantes': [_mcp_product_variant_payload(variant) for variant in variants],
    }


def _mcp_store_products(search_term=None, category=None, limit=12):
    query = (
        Product.query
        .filter(Product.status == 'active')
        .order_by(Product.name.asc())
    )
    search_term = (search_term or '').strip()
    if search_term:
        for token in [part for part in search_term.split() if part.strip()]:
            like = f'%{token}%'
            query = query.filter(db.or_(Product.name.ilike(like), Product.description.ilike(like)))
    if category:
        query = query.filter(Product.category == category)
    return query.limit(max(1, min(int(limit or 12), 30))).all()


def _mcp_resolve_product_item(raw_item: dict):
    product_id = raw_item.get('produto_id') or raw_item.get('product_id')
    variant_id = raw_item.get('variante_id') or raw_item.get('variant_id')
    quantity = max(1, int(raw_item.get('quantidade') or raw_item.get('quantity') or 1))
    product = db.session.get(Product, int(product_id or 0)) if product_id else None
    variant = None
    if variant_id:
        variant = db.session.get(ProductVariant, int(variant_id))
        if variant and product and variant.product_id != product.id:
            raise ValueError('A variante informada não pertence ao produto.')
        if variant and not product:
            product = variant.product
    if not product or product.status != 'active':
        raise ValueError('Produto não encontrado ou indisponível.')
    if variant and variant.status != 'active':
        raise ValueError('Variante indisponível.')
    available_stock = variant.stock if variant else product.stock
    if available_stock is not None and available_stock < quantity:
        raise ValueError(f'Estoque insuficiente para {product.name}. Disponível: {available_stock}.')
    return product, variant, quantity


def _mcp_order_payload(order: Order):
    items = []
    for item in order.items:
        items.append({
            'id': item.id,
            'produto_id': item.product_id,
            'variante_id': item.variant_id,
            'nome': item.item_name,
            'quantidade': item.quantity,
            'preco_unitario': _mcp_money(item.unit_price),
            'subtotal': _mcp_money((item.unit_price or 0) * item.quantity),
        })
    total = sum(float(item.unit_price or 0) * item.quantity for item in order.items)
    return {
        'id': order.id,
        'itens': items,
        'total': _mcp_money(total),
        'endereco_entrega': order.shipping_address,
        'url_carrinho': url_for('retomar_carrinho_chatgpt', order_id=order.id, _external=True),
        'url_pedido': url_for('pedido_detail', order_id=order.id, _external=True),
    }


def _mcp_parse_carteirinha_date(value):
    if isinstance(value, date):
        return value
    raw = str(value or '').strip()
    if not raw:
        return None
    for pattern in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%d/%m/%y', '%d-%m-%y'):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    return None


def _mcp_carteirinha_data(arguments: dict) -> dict:
    data = arguments.get('dados_extraidos') or arguments.get('dados') or {}
    return data if isinstance(data, dict) else {}


def _mcp_carteirinha_preview(user: User, arguments: dict) -> dict:
    data = _mcp_carteirinha_data(arguments)
    pet_data = data.get('pet') or {}
    tutor_data = data.get('tutor') or {}
    pet_name = (pet_data.get('nome') or pet_data.get('name') or '').strip()
    animal = None
    requested_id = arguments.get('animal_id')
    if requested_id:
        try:
            animal = _integration_accessible_animals_query(user).filter(Animal.id == int(requested_id)).first()
        except (TypeError, ValueError):
            animal = None
    if animal is None and pet_name:
        animal = _integration_accessible_animals_query(user).filter(db.func.lower(Animal.name) == pet_name.lower()).first()

    conflicts = []
    birth_date = _mcp_parse_carteirinha_date(pet_data.get('data_nascimento') or pet_data.get('nascimento'))
    source_fields = {
        'nome': pet_name or None,
        'sexo': (pet_data.get('sexo') or '').strip() or None,
        'data_nascimento': birth_date.isoformat() if birth_date else None,
        'especie': (pet_data.get('especie') or '').strip() or None,
        'raca': (pet_data.get('raca') or '').strip() or None,
        'pelagem': (pet_data.get('pelagem') or '').strip() or None,
        'microchip': (pet_data.get('microchip') or '').strip() or None,
    }
    source_tutor = {
        'nome': (tutor_data.get('nome') or tutor_data.get('name') or '').strip() or None,
        'telefone': (tutor_data.get('telefone') or tutor_data.get('phone') or '').strip() or None,
        'endereco': (tutor_data.get('endereco') or tutor_data.get('address') or '').strip() or None,
        'email': (tutor_data.get('email') or '').strip() or None,
    }
    if animal:
        current = _mcp_animal_payload(animal)
        comparisons = {
            'sexo': current.get('sexo'),
            'data_nascimento': animal.date_of_birth.isoformat() if animal.date_of_birth else None,
            'especie': current.get('especie'),
            'raca': current.get('raca'),
            'microchip': animal.microchip_number,
        }
        for field, existing in comparisons.items():
            incoming = source_fields.get(field)
            if incoming and existing and str(incoming).strip().lower() != str(existing).strip().lower():
                conflicts.append({'campo': field, 'atual': existing, 'foto': incoming})

    vaccines = [item for item in (data.get('vacinas') or []) if isinstance(item, dict)]
    dewormings = [item for item in (data.get('vermifugacoes') or []) if isinstance(item, dict)]
    low_confidence = []
    for category, items in (('vacinas', vaccines), ('vermifugacoes', dewormings)):
        for index, item in enumerate(items):
            confidence = (item.get('confianca') or '').strip().lower()
            if confidence in {'baixa', 'low'}:
                low_confidence.append({'tipo': category, 'indice': index, 'motivo': 'leitura de baixa confianca'})
    return {
        'animal_encontrado': _mcp_animal_payload(animal) if animal else None,
        'pet_extraido': source_fields,
        'tutor_extraido': source_tutor,
        'vacinas_para_revisao': vaccines,
        'vermifugacoes_para_revisao': dewormings,
        'campos_em_conflito': conflicts,
        'itens_de_baixa_confianca': low_confidence,
        'proxima_acao': (
            'O pet foi localizado. Dados claros podem ser importados agora; campos ausentes nao bloqueiam a importacao.' if animal
            else 'Nenhum pet correspondente foi encontrado. Cadastre o pet primeiro e depois importe a carteirinha.'
        ),
        'regras_de_seguranca': [
            'Nao importe textos ou datas ilegiveis.',
            'Fotos originais sao preservadas como evidencia da importacao.',
            'Campos que conflitam com o cadastro atual exigem confirmacao especifica.',
        ],
    }


def _mcp_ensure_carteirinha_tables() -> bool:
    try:
        AnimalHealthRecord.__table__.create(db.engine, checkfirst=True)
        CarteirinhaImportacao.__table__.create(db.engine, checkfirst=True)
        return True
    except Exception:
        db.session.rollback()
        return False


def _mcp_should_import_item(item: dict) -> bool:
    if item.get('selecionado') is False:
        return False
    return (item.get('confianca') or '').strip().lower() not in {'baixa', 'low'}


def _mcp_import_carteirinha(user: User, animal: Animal, arguments: dict) -> dict:
    if not _mcp_ensure_carteirinha_tables():
        raise ValueError('Nao foi possivel preparar o armazenamento da importacao da carteirinha.')
    data = _mcp_carteirinha_data(arguments)
    pet_data = data.get('pet') or {}
    preview = _mcp_carteirinha_preview(user, {**arguments, 'animal_id': animal.id})
    conflict_fields = {item['campo'] for item in preview['campos_em_conflito']}
    confirmed_fields = {str(value).strip() for value in (arguments.get('campos_confirmados') or [])}
    updated_fields = []

    birth_date = _mcp_parse_carteirinha_date(pet_data.get('data_nascimento') or pet_data.get('nascimento'))
    updates = {
        'sexo': (pet_data.get('sexo') or '').strip() or None,
        'microchip': (pet_data.get('microchip') or '').strip() or None,
    }
    for field, value in updates.items():
        attribute = {
            'microchip': 'microchip_number',
            'sexo': 'sex',
        }.get(field, field)
        if not value:
            continue
        current = getattr(animal, attribute)
        if not current or field in confirmed_fields:
            setattr(animal, attribute, value)
            updated_fields.append(field)
    if birth_date and (not animal.date_of_birth or 'data_nascimento' in confirmed_fields):
        animal.date_of_birth = birth_date
        updated_fields.append('data_nascimento')
    if (pet_data.get('especie') or '').strip() and (not animal.species_id or 'especie' in confirmed_fields):
        species = _integration_resolve_species(pet_data.get('especie'))
        if species:
            animal.species_id = species.id
            updated_fields.append('especie')
    if (pet_data.get('raca') or '').strip() and (animal.species_id and (not animal.breed_id or 'raca' in confirmed_fields)):
        species = animal.species or _integration_resolve_species(pet_data.get('especie'))
        breed = _integration_resolve_breed(species, pet_data.get('raca')) if species else None
        if breed:
            animal.breed_id = breed.id
            updated_fields.append('raca')
    coat = (pet_data.get('pelagem') or '').strip()
    if coat and 'pelagem' not in conflict_fields:
        note = f'Pelagem informada na carteirinha: {coat}.'
        if note not in (animal.description or ''):
            animal.description = '\n'.join(filter(None, [animal.description, note]))
            updated_fields.append('pelagem')

    # Tutor data is supplemental: a clear missing value can be completed, but a
    # pre-existing different value is never silently replaced by a photo import.
    tutor_data = data.get('tutor') or {}
    tutor = animal.owner
    updated_tutor_fields = []
    tutor_confirmed_fields = {value.removeprefix('tutor.') for value in confirmed_fields}
    if tutor and isinstance(tutor_data, dict):
        tutor_updates = {
            'telefone': ('phone', tutor_data.get('telefone') or tutor_data.get('phone')),
            'endereco': ('address', tutor_data.get('endereco') or tutor_data.get('address')),
        }
        for field, (attribute, raw_value) in tutor_updates.items():
            value = str(raw_value or '').strip()
            current = str(getattr(tutor, attribute) or '').strip()
            if value and (not current or current == value or field in tutor_confirmed_fields):
                if current != value:
                    setattr(tutor, attribute, value)
                    updated_tutor_fields.append(field)

    imported_vaccines = 0
    skipped_vaccines = 0
    for item in data.get('vacinas') or []:
        if not isinstance(item, dict) or not _mcp_should_import_item(item):
            skipped_vaccines += 1
            continue
        name = (item.get('nome') or '').strip()
        applied_on = _mcp_parse_carteirinha_date(item.get('aplicada_em') or item.get('data'))
        if not name or not applied_on:
            skipped_vaccines += 1
            continue
        lot = (item.get('lote') or '').strip() or None
        duplicate = Vacina.query.filter_by(animal_id=animal.id, nome=name, aplicada_em=applied_on, lote=lot).first()
        if duplicate:
            skipped_vaccines += 1
            continue
        next_due = _mcp_parse_carteirinha_date(item.get('proxima_dose') or item.get('proxima_em'))
        interval = (next_due - applied_on).days if next_due and next_due > applied_on else None
        notes = ['Importado de carteirinha fotografada.']
        if item.get('veterinario'):
            notes.append(f"Veterinario informado: {item['veterinario']}.")
        if item.get('crmv'):
            notes.append(f"CRMV informado: {item['crmv']}.")
        db.session.add(Vacina(
            animal_id=animal.id,
            nome=name,
            tipo=(item.get('tipo') or 'Historico importado').strip(),
            fabricante=(item.get('fabricante') or '').strip() or None,
            lote=lot,
            aplicada=True,
            aplicada_em=applied_on,
            intervalo_dias=interval,
            frequencia='anual' if interval and 330 <= interval <= 400 else None,
            observacoes=' '.join(notes),
            created_by=user.id,
        ))
        imported_vaccines += 1

    imported_dewormings = 0
    for item in data.get('vermifugacoes') or []:
        if not isinstance(item, dict) or not _mcp_should_import_item(item):
            continue
        title = (item.get('medicamento') or item.get('nome') or '').strip()
        occurred_on = _mcp_parse_carteirinha_date(item.get('administrada_em') or item.get('data'))
        if not title or not occurred_on:
            continue
        duplicate = AnimalHealthRecord.query.filter_by(animal_id=animal.id, kind='vermifugacao', title=title, occurred_on=occurred_on).first()
        if duplicate:
            continue
        try:
            weight = float(str(item.get('peso_kg') or item.get('peso') or '').replace(',', '.'))
        except ValueError:
            weight = None
        db.session.add(AnimalHealthRecord(
            animal_id=animal.id,
            created_by_id=user.id,
            kind='vermifugacao',
            title=title,
            occurred_on=occurred_on,
            next_due_on=_mcp_parse_carteirinha_date(item.get('proxima_dose') or item.get('proxima_em')),
            weight_kg=weight,
            provider_name=(item.get('veterinario') or '').strip() or None,
            notes='Importado de carteirinha fotografada.',
            source='chatgpt_carteirinha',
        ))
        imported_dewormings += 1

    source_files = []
    for file_ref in arguments.get('fotos_carteirinha') or []:
        if not isinstance(file_ref, dict):
            continue
        stored_url, filename = _integration_download_and_store_carteirinha_file(file_ref)
        source_files.append({'filename': filename, 'url': stored_url})
    audit = CarteirinhaImportacao(
        animal_id=animal.id,
        user_id=user.id,
        status='importada',
        dados_extraidos=json.dumps(data, ensure_ascii=False),
        arquivos_origem=json.dumps(source_files, ensure_ascii=False),
    )
    db.session.add(audit)
    db.session.commit()
    return {
        'importacao_id': audit.id,
        'animal': _mcp_animal_payload(animal),
        'campos_atualizados': sorted(set(updated_fields)),
        'campos_tutor_atualizados': sorted(set(updated_tutor_fields)),
        'campos_em_conflito_nao_alterados': sorted(conflict_fields.difference(confirmed_fields)),
        'vacinas_importadas': imported_vaccines,
        'vacinas_ignoradas': skipped_vaccines,
        'vermifugacoes_importadas': imported_dewormings,
        'arquivos_preservados': source_files,
    }


def _mcp_require_scopes(req_id, token_scope_set, *required_scopes):
    required_scope_set = {scope for scope in required_scopes if scope}
    missing_scopes = sorted(required_scope_set.difference(token_scope_set))
    if not missing_scopes:
        return None
    issuer = _oauth_issuer()
    resource_path = _mcp_resource_path()
    metadata_url = f'{issuer}/.well-known/oauth-protected-resource{resource_path}'
    scope_text = ' '.join(missing_scopes)
    challenge = (
        f'Bearer resource_metadata="{metadata_url}",'
        f' error="insufficient_scope",'
        f' error_description="Additional PetOrlandia permissions are required",'
        f' scope="{scope_text}"'
    )
    return _mcp_ok(
        req_id,
        {
            'content': [{
                'type': 'text',
                'text': 'Authentication required: authorize the additional PetOrlandia permissions and try again.',
            }],
            'isError': True,
            '_meta': {'mcp/www_authenticate': [challenge]},
            'structuredContent': {
            'required_scopes': sorted(required_scope_set),
            'granted_scopes': sorted(token_scope_set),
            'missing_scopes': missing_scopes,
            },
        },
    )


def _mcp_require_confirmation(req_id, tool_args, *, field_name='confirmar_gravacao'):
    value = str(tool_args.get(field_name) or '').strip().lower()
    accepted_values = {'sim', 'true', '1', 'confirmado', 'confirmar'}
    if value in accepted_values:
        return None
    return _mcp_err_with_data(
        req_id,
        -32003,
        'Esta tool grava dados no sistema e exige confirmação explícita.',
        {
            'required_argument': field_name,
            'accepted_values': sorted(accepted_values),
        },
    )


def _mcp_find_animal_for_tool(user, tool_args):
    animal_id = tool_args.get('animal_id')
    animal_name = tool_args.get('nome_animal') or tool_args.get('animal_nome') or tool_args.get('nome')
    try:
        parsed_animal_id = int(animal_id) if animal_id is not None else None
    except (TypeError, ValueError):
        parsed_animal_id = None
    return _integration_find_accessible_animal(
        user,
        animal_id=parsed_animal_id,
        animal_name=animal_name,
    )


def _mcp_resource_path() -> str:
    """Return the MCP resource path for the current legacy or versioned route."""
    return '/mcp/v2' if request.path.endswith('/mcp/v2') else '/mcp'


def _mcp_unauthorized():
    """Return 401 with WWW-Authenticate so that OAuth clients know how to auth."""
    issuer = _oauth_issuer()
    resource_path = _mcp_resource_path()
    resource_url = f'{issuer}{resource_path}'
    # RFC 9728 preserves the resource path after the well-known segment.
    metadata_url = f'{issuer}/.well-known/oauth-protected-resource{resource_path}'
    resp = make_response(
        jsonify({'jsonrpc': '2.0', 'id': None,
                 'error': {'code': -32001, 'message': 'Unauthorized: Bearer token required'}}),
        401,
    )
    resp.headers['WWW-Authenticate'] = (
        f'Bearer realm="{resource_url}",'
        f' resource_metadata="{metadata_url}",'
        f' as_uri="{issuer}"'
    )
    return resp


@csrf.exempt
def mcp_server():
    """MCP server — handles GET (capability probe) and POST (JSON-RPC) from Claude/ChatGPT."""

    if request.method == 'OPTIONS':
        return ('', 204)

    # ── GET: unauthenticated capability probe or SSE handshake ───────────────
    # Claude may send a plain GET before OAuth to verify server existence.
    # Return a JSON description (no auth required) so discovery succeeds.
    if request.method == 'GET':
        issuer = _oauth_issuer()
        return jsonify({
            'server': 'PetOrlândia MCP',
            'version': '2.1.0',
            'resource': f'{issuer}{_mcp_resource_path()}',
            'protocol': f'mcp/{MCP_PROTOCOL_VERSIONS[0]}',
            'authorization_required': True,
            'authorization_server': issuer,
        })

    # ── POST: authenticated JSON-RPC ─────────────────────────────────────────

    # Authentication
    bearer = _oauth_extract_bearer_token()
    if not bearer:
        return _mcp_unauthorized()

    token_obj = OAuthAccessToken.query.filter_by(access_token=bearer).first()
    if not token_obj or not token_obj.is_active:
        return _mcp_unauthorized()

    expected_resource = f'{_oauth_issuer().rstrip("/")}{_mcp_resource_path()}'
    if not token_obj.resource or token_obj.resource.rstrip('/') != expected_resource:
        return _mcp_unauthorized()

    user = db.session.get(User, token_obj.user_id)
    if not user:
        return _mcp_unauthorized()
    token_scope_set = {item.strip() for item in (token_obj.scope or '').split() if item.strip()}

    # Parse JSON-RPC
    data = request.get_json(silent=True) or {}
    method = data.get('method', '')
    req_id = data.get('id')
    params = data.get('params') or {}

    # ── initialize ────────────────────────────────────────────────────────────
    if method == 'initialize':
        return _mcp_ok(req_id, {
            'protocolVersion': _mcp_protocol_version(params),
            'serverInfo': {'name': 'PetOrlandia MCP v2', 'version': '3.1.0'},
            'capabilities': {'tools': {}, 'resources': {}},
            'instructions': (
                'PHOTO IMPORT RULES: Never invent data or merge records from different pets. Missing phone, address, or incomplete history never blocks importing clear data. '
                'A direct user instruction to register, include, save, or import is explicit confirmation: review and import in the same conversation with confirmar_gravacao="sim" when no material conflict exists. '
                'Skip only illegible or low-confidence items and report them after the successful import. '
                'PetOrlandia é um app real de gestão veterinária, loja e serviços. '
                'Quando o usuário pedir produtos, compras, catálogo, preço, estoque, carrinho ou pagamento, '
                'use as tools de loja para consultar produtos reais e criar pedidos reais. '
                'Nunca invente categorias, produtos, marcas, preços, estoque ou formas de pagamento. '
                'Para pagamento, crie ou atualize o pedido e entregue o link do carrinho/checkout do PetOrlandia; '
                'não afirme que processou cartão dentro do ChatGPT. '
                'Quando o tutor enviar fotos de carteirinha de vacinação, leia as imagens, chame revisar_carteirinha_fotografada '
                'com uma transcrição estruturada e apresente no próprio chat somente o retorno efetivo da tool; nunca alegue que abriu um painel. '
                'Só chame importar_carteirinha_fotografada após confirmação explícita. '
                'Também existem atualizar_perfil_pet, registrar_vacina_pet e registrar_vermifugacao_pet. '
                'Nunca afirme que uma ação não existe sem antes usar o catálogo de tools desta conexão. '
                'Para qualquer escrita, peça confirmação explícita antes de chamar tools que gravam dados.'
            ),
        })

    # ── notifications/initialized (client ack — no response body needed) ─────
    if method in ('notifications/initialized', 'initialized'):
        return ('', 204)

    if method == 'resources/list':
        return _mcp_ok(req_id, {'resources': [item[0] for item in _mcp_widget_catalog().values()]})

    if method == 'resources/read':
        uri = str(params.get('uri') or '').strip()
        return _mcp_widget_response(req_id, uri)

    # ── tools/list ───────────────────────────────────────────────────────────
    if method == 'tools/list':
        tools = [
            {
                'name': 'listar_meus_pets',
                'description': (
                    'Lista todos os animais (pets) cadastrados na conta do usuário autenticado. '
                    'Retorna nome, espécie, raça, sexo, idade e peso de cada animal.'
                ),
                'inputSchema': {'type': 'object', 'properties': {}, 'required': []},
            },
            {
                'name': 'listar_vacinas_pet',
                'description': (
                    'Lista as vacinas dos pets do usuário autenticado: aplicadas (com data, '
                    'fabricante e veterinário) e próximas doses previstas ou atrasadas. '
                    'Aceita animal_id opcional para filtrar um pet específico.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer', 'description': 'ID do pet (opcional).'},
                    },
                    'required': [],
                },
            },
            {
                'name': 'obter_carteirinha_pet',
                'description': (
                    'Retorna o link público da carteirinha digital de um pet (vacinas e dados '
                    'básicos, compartilhável). Informa como ativá-la caso ainda não exista.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer', 'description': 'ID do pet.'},
                    },
                    'required': ['animal_id'],
                },
            },
            {
                'name': 'revisar_carteirinha_fotografada',
                'description': (
                    'Use quando o tutor enviar fotos de carteira/cartao de vacinacao no ChatGPT. '
                    'O ChatGPT deve ler as imagens, transcrever apenas campos claros em dados_extraidos '
                    '(identificacao, vacinas e vermifugacoes) e chamar esta tool antes de gravar. '
                    'Retorna pet correspondente, conflitos e itens que exigem revisao; nao grava dados.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer', 'description': 'ID do pet ja escolhido, se houver.'},
                        'dados_extraidos': {
                            'type': 'object',
                            'description': 'Transcricao estruturada feita a partir das fotos. Use pet, vacinas e vermifugacoes; omita trechos ilegiveis.',
                        },
                    },
                    'required': ['dados_extraidos'],
                },
            },
            {
                'name': 'importar_carteirinha_fotografada',
                'description': (
                    'Importa para um pet confirmado os dados revisados de uma carteirinha fotografada. '
                    'Preserva as fotos originais como evidencia, cria vacinas historicas e eventos de vermifugacao. '
                    'Uma ordem direta para registrar ou importar e confirmacao suficiente. Importe itens claros mesmo com dados complementares ausentes; '
                    'itens de baixa confianca devem ficar fora da importacao.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer', 'description': 'ID do pet que recebera os dados.'},
                        'dados_extraidos': {'type': 'object', 'description': 'Mesmo rascunho aprovado na revisao.'},
                        'fotos_carteirinha': {'type': 'array', 'items': MCP_FILE_REFERENCE_SCHEMA, 'maxItems': 12},
                        'campos_confirmados': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'description': 'Campos em conflito que o tutor confirmou substituir: sexo, data_nascimento, especie, raca ou microchip.',
                        },
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['animal_id', 'dados_extraidos', 'confirmar_gravacao'],
                },
                '_meta': {'openai/fileParams': ['fotos_carteirinha']},
            },
            {
                'name': 'atualizar_perfil_pet',
                'description': 'Atualiza os dados confirmados de identificacao do pet, como nome, sexo, nascimento, especie, raca, pelagem e microchip.',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer'},
                        'nome': {'type': 'string'},
                        'sexo': {'type': 'string'},
                        'data_nascimento': {'type': 'string', 'description': 'DD/MM/AAAA ou YYYY-MM-DD.'},
                        'especie': {'type': 'string'},
                        'raca': {'type': 'string'},
                        'pelagem': {'type': 'string'},
                        'microchip': {'type': 'string'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['animal_id', 'confirmar_gravacao'],
                },
            },
            {
                'name': 'atualizar_perfil_tutor',
                'description': (
                    'Atualiza o tutor vinculado a um pet acessivel: nome, telefone, telefone alternativo, endereco e e-mail. '
                    'Use somente dados claros; nao invente nem substitua dado conflitante sem ordem expressa do usuario.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer'},
                        'tutor_id': {'type': 'integer'},
                        'nome': {'type': 'string'},
                        'telefone': {'type': 'string'},
                        'telefone_alternativo': {'type': 'string'},
                        'endereco': {'type': 'string'},
                        'email': {'type': 'string'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['confirmar_gravacao'],
                },
            },
            {
                'name': 'registrar_vacina_pet',
                'description': 'Registra uma vacina historica ou aplicada para um pet. Evita duplicidade por pet, nome, data e lote.',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer'},
                        'nome': {'type': 'string'},
                        'aplicada_em': {'type': 'string', 'description': 'DD/MM/AAAA ou YYYY-MM-DD.'},
                        'proxima_dose': {'type': 'string'},
                        'tipo': {'type': 'string'},
                        'fabricante': {'type': 'string'},
                        'lote': {'type': 'string'},
                        'observacoes': {'type': 'string'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['animal_id', 'nome', 'aplicada_em', 'confirmar_gravacao'],
                },
            },
            {
                'name': 'registrar_vermifugacao_pet',
                'description': 'Registra uma vermifugacao historica para um pet. Evita duplicidade por pet, medicamento e data.',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer'},
                        'medicamento': {'type': 'string'},
                        'administrada_em': {'type': 'string', 'description': 'DD/MM/AAAA ou YYYY-MM-DD.'},
                        'proxima_dose': {'type': 'string'},
                        'peso_kg': {'type': 'number'},
                        'observacoes': {'type': 'string'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['animal_id', 'medicamento', 'administrada_em', 'confirmar_gravacao'],
                },
            },
            {
                'name': 'listar_agendamentos',
                'description': (
                    'Lista os agendamentos veterinários do usuário autenticado. '
                    'Aceita filtro opcional por status: scheduled, completed ou cancelled.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'status': {
                            'type': 'string',
                            'enum': ['scheduled', 'completed', 'cancelled'],
                            'description': 'Filtrar pelo status do agendamento (opcional).',
                        }
                    },
                    'required': [],
                },
            },
            {
                'name': 'interpretar_mensagem_livre_atendimento',
                'description': (
                    'Interpreta mensagens livres ou trechos de conversa e devolve um rascunho '
                    'operacional com dados extraídos, ação sugerida e campos que ainda faltam. '
                    'Não grava nada no sistema.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'texto': {'type': 'string', 'description': 'Texto livre ou bloco de conversa.'},
                        'mensagens': {
                            'type': 'array',
                            'description': 'Lista opcional de mensagens em texto simples ou objetos com autor/conteudo/timestamp.',
                        },
                    },
                    'required': [],
                },
            },
            {
                'name': 'assistente_operacional_veterinario',
                'description': (
                    'Recebe linguagem natural do veterinário, infere a intenção operacional '
                    'principal e, quando houver dados suficientes e confirmação explícita, '
                    'executa cadastro, agendamento ou registro de consulta.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'texto': {'type': 'string', 'description': 'Texto livre do veterinário.'},
                        'mensagens': {'type': 'array', 'description': 'Lista opcional de mensagens.'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': [],
                },
            },
            {
                'name': 'cadastrar_tutor_e_pets',
                'description': (
                    'Cadastra ou reaproveita um tutor e um ou mais pets, criando também '
                    'consultas iniciais em andamento quando novos pets forem criados.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'tutor': {'type': 'object', 'description': 'Dados básicos do tutor.'},
                        'pets': {'type': 'array', 'description': 'Lista de pets a cadastrar ou reaproveitar.'},
                        'observacao_clinica': {'type': 'string'},
                        'disponibilidade': {'type': 'string'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['tutor', 'pets', 'confirmar_gravacao'],
                },
            },
            {
                'name': 'registrar_consulta_clinica',
                'description': (
                    'Cria ou atualiza uma consulta clínica do animal, preenchendo queixa, histórico, '
                    'exame físico, diagnóstico, conduta e exames solicitados.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer'},
                        'nome_animal': {'type': 'string'},
                        'consulta_id': {'type': 'integer'},
                        'queixa_principal': {'type': 'string'},
                        'historico_clinico': {'type': 'string'},
                        'exame_fisico': {'type': 'string'},
                        'diagnostico': {'type': 'string'},
                        'suspeita_clinica': {'type': 'string'},
                        'conduta': {'type': 'string'},
                        'exames_solicitados': {'type': 'string'},
                        'prescricao': {'type': 'string'},
                        'finalizar': {'type': 'boolean'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['confirmar_gravacao'],
                },
            },
            {
                'name': 'registrar_bloco_exames',
                'description': (
                    'Registra exames solicitados ou resultados em um novo bloco de exames do paciente.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer'},
                        'nome_animal': {'type': 'string'},
                        'observacoes_gerais': {'type': 'string'},
                        'exames': {'type': 'array'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['exames', 'confirmar_gravacao'],
                },
            },
            {
                'name': 'criar_exame_imagem',
                'description': 'Cria exame de imagem com paciente, tutor, clinica requisitante, profissional, CRMV, data e status.',
                'inputSchema': {'type': 'object', 'properties': {'animal_id': {'type': 'integer'}, 'nome_animal': {'type': 'string'}, 'tutor_id': {'type': 'integer'}, 'nome_tutor': {'type': 'string'}, 'clinica_id': {'type': 'integer'}, 'nome_clinica': {'type': 'string'}, 'tipo_exame': {'type': 'string'}, 'data_exame': {'type': 'string'}, 'profissional_nome': {'type': 'string'}, 'profissional_crmv': {'type': 'string'}, 'descricao': {'type': 'string'}, 'impressao_diagnostica': {'type': 'string'}, 'confirmar_gravacao': {'type': 'string'}}, 'required': ['tipo_exame', 'data_exame', 'confirmar_gravacao']},
            },
            {
                'name': 'anexar_pdf_exame_imagem',
                'description': 'Anexa PDF autorizado pelo ChatGPT ao exame de imagem.',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'exame_id': {'type': 'integer'},
                        'arquivo_pdf': MCP_FILE_REFERENCE_SCHEMA,
                        'attachment_id': MCP_FILE_REFERENCE_OR_STRING_SCHEMA,
                        'download_url': {'type': 'string'},
                        'file_name': {'type': 'string'},
                        'mime_type': {'type': 'string'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['exame_id', 'confirmar_gravacao'],
                },
                '_meta': {'openai/fileParams': ['arquivo_pdf']},
            },
            {'name': 'liberar_exame_para_clinica', 'description': 'Libera exame para a clinica requisitante.', 'inputSchema': {'type': 'object', 'properties': {'exame_id': {'type': 'integer'}, 'clinica_id': {'type': 'integer'}, 'confirmar_gravacao': {'type': 'string'}}, 'required': ['exame_id', 'clinica_id', 'confirmar_gravacao']}},
            {'name': 'liberar_exame_para_tutor', 'description': 'Libera exame para o tutor vinculado.', 'inputSchema': {'type': 'object', 'properties': {'exame_id': {'type': 'integer'}, 'tutor_id': {'type': 'integer'}, 'confirmar_gravacao': {'type': 'string'}}, 'required': ['exame_id', 'tutor_id', 'confirmar_gravacao']}},
            {'name': 'gerar_convite_primeiro_acesso_clinica', 'description': 'Gera convite seguro de primeiro acesso gratuito para a clinica requisitante.', 'inputSchema': {'type': 'object', 'properties': {'clinica_id': {'type': 'integer'}, 'nome_clinica': {'type': 'string'}, 'email': {'type': 'string'}, 'telefone': {'type': 'string'}, 'exame_id': {'type': 'integer'}, 'confirmar_gravacao': {'type': 'string'}}, 'required': ['confirmar_gravacao']}},
            {'name': 'gerar_convite_acesso_tutor', 'description': 'Gera convite seguro de acesso do tutor.', 'inputSchema': {'type': 'object', 'properties': {'tutor_id': {'type': 'integer'}, 'nome_tutor': {'type': 'string'}, 'animal_id': {'type': 'integer'}, 'exame_id': {'type': 'integer'}, 'confirmar_gravacao': {'type': 'string'}}, 'required': ['animal_id', 'confirmar_gravacao']}},
            {'name': 'listar_historico_medico_animal', 'description': 'Lista historico medico com exames de imagem, documentos e PDFs disponiveis. Use pdfs_disponiveis[].url, portal_url ou shareable_url ao compartilhar com clinica/tutor; endpoints internos exigem bearer e nao devem ser enviados como link final.', 'inputSchema': {'type': 'object', 'properties': {'animal_id': {'type': 'integer'}, 'nome_animal': {'type': 'string'}}, 'required': []}},
            {'name': 'obter_documento_clinico', 'description': 'Retorna documento clinico e links humanos de portal/download respeitando permissoes. Use shareable_url para o usuario final; nao apresente URL de API protegida como link do exame.', 'inputSchema': {'type': 'object', 'properties': {'exame_id': {'type': 'integer'}, 'documento_id': {'type': 'integer'}}, 'required': []}},
            {'name': 'buscar_ou_criar_clinica_requisitante', 'description': 'Busca ou cria clinica requisitante do exame.', 'inputSchema': {'type': 'object', 'properties': {'nome_clinica': {'type': 'string'}, 'cnpj': {'type': 'string'}, 'email': {'type': 'string'}, 'telefone': {'type': 'string'}, 'confirmar_gravacao': {'type': 'string'}}, 'required': ['nome_clinica', 'confirmar_gravacao']}},
            {'name': 'buscar_ou_criar_tutor_animal', 'description': 'Busca ou cria tutor e animal para o fluxo de exame.', 'inputSchema': {'type': 'object', 'properties': {'clinica_id': {'type': 'integer'}, 'nome_tutor': {'type': 'string'}, 'telefone': {'type': 'string'}, 'email': {'type': 'string'}, 'nome_animal': {'type': 'string'}, 'especie': {'type': 'string'}, 'idade': {'type': 'string'}, 'raca': {'type': 'string'}, 'sexo': {'type': 'string'}, 'confirmar_gravacao': {'type': 'string'}}, 'required': ['nome_tutor', 'nome_animal', 'especie', 'confirmar_gravacao']}},
            {
                'name': 'abrir_importador_laudo_volante',
                'title': 'Abrir importador de laudo volante',
                'description': (
                    'Use imediatamente quando o veterinário enviar fotos, capturas de tela, PDF, texto ou observações '
                    'de exame de imagem no ChatGPT. Para um novo rascunho, chame primeiro sugerir_modelo_laudo, '
                    'redija laudo_texto somente com achados confirmados e então abra este painel na mesma resposta. '
                    'O painel mostra clínica, tutor, animal, laudo e mensagens para edição antes de gravar. Nunca '
                    'invente medidas, achados, órgãos avaliados, diagnóstico ou recomendação; liste dados ausentes '
                    'em campos_a_confirmar. Esta tool não grava nada; o botão chama importar_laudo_volante somente '
                    'após confirmação explícita.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'exame_id': {'type': 'integer'},
                        'bloco_id': {'type': 'integer'},
                        'clinica': {'type': 'object'},
                        'tutor': {'type': 'object'},
                        'animal': {'type': 'object'},
                        'exame': {'type': 'object'},
                        'laudo_texto': {'type': 'string'},
                        'laudo_url': {'type': 'string'},
                        'laudo_filename': {'type': 'string'},
                        'laudo_arquivo': MCP_FILE_REFERENCE_SCHEMA,
                        'mensagem_clinica': {'type': 'string'},
                        'mensagem_tutor': {'type': 'string'},
                        'campos_a_confirmar': {'type': 'array', 'items': {'type': 'string'}},
                    },
                    'required': [],
                },
                'outputSchema': {
                    'type': 'object',
                    'properties': {
                        'rascunho': {'type': 'object'},
                        'campos_a_confirmar': {'type': 'array', 'items': {'type': 'string'}},
                    },
                },
                'annotations': {
                    'readOnlyHint': True,
                    'destructiveHint': False,
                    'openWorldHint': False,
                    'idempotentHint': True,
                },
                '_meta': {
                    'openai/fileParams': ['laudo_arquivo'],
                    'openai/toolInvocation/invoking': 'Abrindo revisao do laudo...',
                    'openai/toolInvocation/invoked': 'Revisao do laudo pronta.',
                },
            },
            {
                'name': 'importar_laudo_volante',
                'description': (
                    'Use quando um ultrassonografista volante enviar ou colar um laudo no ChatGPT. '
                    'Se exame_id ou bloco_id apontarem para um exame existente, a tool apenas anexa o PDF/laudo '
                    'ao exame e nao reescreve resultado, achados ou conclusao. Se nao houver exame existente, '
                    'cria o registro minimo e prepara os links de primeiro acesso.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'exame_id': {'type': 'integer', 'description': 'ID do exame existente quando o objetivo for apenas anexar o PDF.'},
                        'bloco_id': {'type': 'integer', 'description': 'ID do bloco de exames existente quando houver.'},
                        'clinica': {'type': 'object', 'description': 'Clinica solicitante: nome, email, telefone e endereco quando houver.'},
                        'tutor': {'type': 'object', 'description': 'Tutor/responsavel: nome, telefone, email e endereco quando houver.'},
                        'animal': {'type': 'object', 'description': 'Paciente: nome, especie, raca, sexo e idade quando houver.'},
                        'exame': {'type': 'object', 'description': 'Dados do exame: nome/tipo, data, achados, conclusao e justificativa.'},
                        'laudo_texto': {'type': 'string', 'description': 'Texto integral ou resumo fiel do laudo. Preferencial quando o anexo do ChatGPT falhar.'},
                        'laudo_url': {'type': 'string', 'description': 'URL publica http/https do arquivo. Nao envie caminhos locais como /mnt/data; para anexos use laudo_arquivo.'},
                        'laudo_filename': {'type': 'string', 'description': 'Nome do arquivo do laudo quando houver link.'},
                        'laudo_arquivo': MCP_FILE_REFERENCE_SCHEMA,
                        'mensagem_clinica': {'type': 'string', 'description': 'Mensagem curta e cordial para a clinica.'},
                        'mensagem_tutor': {'type': 'string', 'description': 'Mensagem curta e cordial para o tutor.'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['clinica', 'tutor', 'animal', 'exame', 'confirmar_gravacao'],
                },
                'outputSchema': {
                    'type': 'object',
                    'properties': {
                        'clinica': {'type': 'object'},
                        'tutor': {'type': 'object'},
                        'animal': {'type': 'object'},
                        'exame': {'type': 'object'},
                        'links_primeiro_acesso': {'type': 'object'},
                        'links': {'type': 'object'},
                        'comunicacao': {'type': 'object'},
                        'proxima_acao_recomendada': {'type': 'string'},
                        'mensagem_sugerida_para_clinica': {'type': 'string'},
                        'mensagem_sugerida_para_tutor': {'type': 'string'},
                    },
                },
                'annotations': {
                    'readOnlyHint': False,
                    'destructiveHint': False,
                    'openWorldHint': False,
                    'idempotentHint': False,
                },
                '_meta': {
                    'openai/fileParams': ['laudo_arquivo'],
                    'openai/toolInvocation/invoking': 'Importando laudo...',
                    'openai/toolInvocation/invoked': 'Laudo importado.',
                },
            },
            {
                'name': 'sugerir_modelo_laudo',
                'description': (
                    'Use primeiro quando o veterinário enviar imagens ou observações de ultrassom/radiografia e '
                    'pedir um rascunho. Retorna estrutura editável baseada em laudos de imagem, frases-base e '
                    'exemplos acessíveis. Não grava nada nem interpreta o exame de forma autônoma: use apenas '
                    'achados confirmados para redigir laudo_texto e então chame abrir_importador_laudo_volante '
                    'para revisão humana.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'tipo_exame': {'type': 'string', 'description': 'Ex.: Ultrassonografia abdominal.'},
                        'especie': {'type': 'string'},
                        'achados': {'type': 'string', 'description': 'Achados do caso atual para adaptar o modelo.'},
                        'limite_exemplos': {'type': 'integer'},
                    },
                    'required': ['tipo_exame'],
                },
                'annotations': {
                    'readOnlyHint': True,
                    'destructiveHint': False,
                    'openWorldHint': False,
                    'idempotentHint': True,
                },
            },
            {
                'name': 'agendar_consulta',
                'description': (
                    'Agenda consulta, vacina, retorno ou outro compromisso clínico para um animal.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer'},
                        'nome_animal': {'type': 'string'},
                        'veterinario_id': {'type': 'integer'},
                        'data': {'type': 'string', 'description': 'YYYY-MM-DD'},
                        'hora': {'type': 'string', 'description': 'HH:MM'},
                        'tipo': {'type': 'string'},
                        'motivo': {'type': 'string'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['data', 'hora', 'confirmar_gravacao'],
                },
            },
            {
                'name': 'agendar_retorno',
                'description': (
                    'Agenda retorno a partir de uma consulta já existente usando a lógica de retorno do sistema.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'consulta_id': {'type': 'integer'},
                        'data': {'type': 'string', 'description': 'YYYY-MM-DD'},
                        'hora': {'type': 'string', 'description': 'HH:MM'},
                        'veterinario_id': {'type': 'integer'},
                        'motivo': {'type': 'string'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['consulta_id', 'data', 'hora', 'confirmar_gravacao'],
                },
            },
            {
                'name': 'obter_resumo_clinico_animal',
                'description': (
                    'Retorna um resumo clínico estruturado do paciente, incluindo última consulta, '
                    'histórico recente, prescrição mais recente, exames recentes e pendências clínicas.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer', 'description': 'ID do animal.'},
                        'nome_animal': {'type': 'string', 'description': 'Nome exato do animal quando o ID não for informado.'},
                    },
                    'required': [],
                },
            },
            {
                'name': 'listar_agenda_do_dia',
                'description': (
                    'Lista a agenda do dia do usuário autenticado com resumo de pendências clínicas por paciente.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'data': {'type': 'string', 'description': 'Data opcional no formato YYYY-MM-DD.'},
                    },
                    'required': [],
                },
                '_meta': {
                    'openai/toolInvocation/invoking': 'Carregando agenda do dia...',
                    'openai/toolInvocation/invoked': 'Agenda do dia pronta.',
                },
            },
            {
                'name': 'buscar_produtos_loja',
                'description': (
                    'Use quando o usuário quiser comprar, ver catálogo, saber o que há à venda, consultar preço, '
                    'estoque, ração, petiscos, medicamentos, acessórios ou produtos da loja PetOrlandia. '
                    'Retorna apenas produtos reais cadastrados e ativos; não invente produtos ausentes.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'termo': {'type': 'string', 'description': 'Texto de busca, como ração, Premier, gato, cachorro ou 15 kg.'},
                        'categoria': {'type': 'string', 'description': 'Categoria interna opcional, quando conhecida.'},
                        'limite': {'type': 'integer', 'description': 'Máximo de produtos, até 30.'},
                    },
                    'required': [],
                },
            },
            {
                'name': 'obter_produto_loja',
                'description': (
                    'Use quando o usuário escolher um produto específico e precisar de detalhes reais, variações, '
                    'preço público, estoque e link do produto.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'produto_id': {'type': 'integer', 'description': 'ID do produto real retornado por buscar_produtos_loja.'},
                    },
                    'required': ['produto_id'],
                },
            },
            {
                'name': 'criar_pedido_loja',
                'description': (
                    'Use quando o usuário confirmar que quer comprar produtos reais já selecionados. '
                    'Cria ou atualiza um pedido/carrinho no PetOrlandia e retorna link para revisar entrega e pagar. '
                    'Não processa cartão dentro do ChatGPT e exige confirmar_gravacao.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'itens': {
                            'type': 'array',
                            'description': 'Itens confirmados pelo usuário.',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'produto_id': {'type': 'integer'},
                                    'variante_id': {'type': 'integer'},
                                    'quantidade': {'type': 'integer'},
                                },
                                'required': ['produto_id'],
                            },
                        },
                        'endereco_entrega': {'type': 'string', 'description': 'Endereço de entrega, se informado.'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['itens', 'confirmar_gravacao'],
                },
            },
            {
                'name': 'buscar_paciente',
                'description': (
                    'Busca pacientes por nome do animal, tutor, telefone ou email dentro do escopo acessivel. '
                    'Use antes de preparar consulta, obter timeline ou gerar mensagens quando o ID do animal nao estiver claro.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'termo': {'type': 'string', 'description': 'Nome, tutor, telefone ou email a buscar.'},
                        'limite': {'type': 'integer', 'description': 'Quantidade maxima de resultados, ate 25.'},
                    },
                    'required': [],
                },
            },
            {
                'name': 'obter_timeline_clinica',
                'description': (
                    'Mostra a linha do tempo consolidada de um paciente: consultas, exames de imagem, vacinas, '
                    'documentos e pendencias principais.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer', 'description': 'ID do animal.'},
                        'nome_animal': {'type': 'string', 'description': 'Nome exato do animal quando o ID nao for informado.'},
                    },
                    'required': [],
                },
                '_meta': {
                    'openai/toolInvocation/invoking': 'Montando timeline clinica...',
                    'openai/toolInvocation/invoked': 'Timeline clinica pronta.',
                },
            },
            {
                'name': 'preparar_consulta',
                'description': (
                    'Prepara um briefing antes do atendimento com resumo clinico, pendencias, perguntas sugeridas '
                    'e proximas acoes. Nao grava dados.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer', 'description': 'ID do animal.'},
                        'nome_animal': {'type': 'string', 'description': 'Nome exato do animal quando o ID nao for informado.'},
                        'appointment_id': {'type': 'integer', 'description': 'Agendamento especifico quando houver.'},
                    },
                    'required': [],
                },
                '_meta': {
                    'openai/toolInvocation/invoking': 'Preparando consulta...',
                    'openai/toolInvocation/invoked': 'Briefing da consulta pronto.',
                },
            },
            {
                'name': 'listar_pendencias_clinicas',
                'description': (
                    'Lista vacinas atrasadas, retornos pendentes e exames pendentes/agendados do escopo acessível.'
                ),
                'inputSchema': {'type': 'object', 'properties': {}, 'required': []},
            },
            {
                'name': 'listar_vacinas_pendentes',
                'description': 'Lista vacinas atrasadas e próximas vacinas do escopo acessível.',
                'inputSchema': {'type': 'object', 'properties': {}, 'required': []},
            },
            {
                'name': 'listar_exames_pendentes',
                'description': 'Lista exames solicitados pendentes e exames agendados ainda em aberto.',
                'inputSchema': {'type': 'object', 'properties': {}, 'required': []},
            },
            {
                'name': 'listar_retornos_pendentes',
                'description': 'Lista retornos futuros relacionados a consultas já registradas.',
                'inputSchema': {'type': 'object', 'properties': {}, 'required': []},
            },
            {
                'name': 'gerar_orientacao_tutor',
                'description': (
                    'Gera um rascunho de orientação ao tutor com base no prontuário e prescrições existentes.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer', 'description': 'ID do animal.'},
                        'nome_animal': {'type': 'string', 'description': 'Nome exato do animal quando o ID não for informado.'},
                        'consulta_id': {'type': 'integer', 'description': 'Consulta opcional para guiar a orientação.'},
                    },
                    'required': [],
                },
            },
            {
                'name': 'gerar_mensagem_whatsapp_tutor',
                'description': (
                    'Gera uma mensagem pronta para copiar ou abrir no WhatsApp do tutor, com base no prontuario. '
                    'Nao envia a mensagem automaticamente.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer', 'description': 'ID do animal.'},
                        'nome_animal': {'type': 'string', 'description': 'Nome exato do animal quando o ID nao for informado.'},
                        'consulta_id': {'type': 'integer', 'description': 'Consulta opcional para guiar a mensagem.'},
                        'tipo': {'type': 'string', 'description': 'orientacao, retorno, exame, vacina ou livre.'},
                        'contexto': {'type': 'string', 'description': 'Texto adicional a incluir no rascunho.'},
                    },
                    'required': [],
                },
            },
            {
                'name': 'gerar_handoff_clinico',
                'description': (
                    'Gera um handoff clínico resumido para troca entre veterinários e plantonistas.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'animal_id': {'type': 'integer', 'description': 'ID do animal.'},
                        'nome_animal': {'type': 'string', 'description': 'Nome exato do animal quando o ID não for informado.'},
                        'consulta_id': {'type': 'integer', 'description': 'Consulta opcional a destacar no handoff.'},
                    },
                    'required': [],
                },
            },
            {
                'name': 'listar_alertas_admin',
                'description': (
                    'Lista alertas administrativos acionaveis do PetOrlandia para admins: compras, servicos, '
                    'carreiras/petsitter, pagamentos e pendencias operacionais.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'status': {'type': 'string', 'description': 'open, unread, read, resolved, archived ou all.'},
                        'limite': {'type': 'integer', 'description': 'Quantidade maxima de alertas, ate 100.'},
                    },
                    'required': [],
                },
                '_meta': {
                    'openai/toolInvocation/invoking': 'Carregando central admin...',
                    'openai/toolInvocation/invoked': 'Central admin pronta.',
                },
            },
            {
                'name': 'resolver_alerta_admin',
                'description': (
                    'Marca um alerta administrativo como lido ou resolvido. Exige confirmacao explicita.'
                ),
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'alerta_id': {'type': 'integer', 'description': 'ID do alerta administrativo.'},
                        'acao': {'type': 'string', 'description': 'ler ou resolver.'},
                        'confirmar_gravacao': {'type': 'string'},
                    },
                    'required': ['alerta_id', 'acao', 'confirmar_gravacao'],
                },
            },
        ]
        # Mostra apenas as tools cujos scopes foram todos concedidos ao token —
        # uma conexao de tutor (somente leitura) nao ve as tools de escrita da clinica.
        visible = []
        for tool in tools:
            if tool.get('name') in {'listar_alertas_admin', 'resolver_alerta_admin'} and not _mcp_user_is_admin(user):
                continue
            visible.append(tool)
        return _mcp_ok(req_id, {'tools': _mcp_finalize_tool_descriptors(visible)})

    # ── tools/call ───────────────────────────────────────────────────────────
    if method == 'tools/call':
        tool_name = params.get('name', '')
        tool_args = params.get('arguments') or {}

        if tool_name == 'listar_meus_pets':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'pets:read')
            if scope_error:
                return scope_error
            animals = (
                _integration_accessible_animals_query(user)
                .order_by(Animal.name)
                .all()
            )
            pets = []
            for a in animals:
                spec = getattr(a, 'species', None)
                spec_name = spec.name if hasattr(spec, 'name') else str(spec or '')
                brd = getattr(a, 'breed', None)
                brd_name = brd.name if hasattr(brd, 'name') else str(brd or '')
                pets.append({
                    'id': a.id,
                    'nome': a.name,
                    'especie': spec_name or None,
                    'raca': brd_name or None,
                    'sexo': a.sex,
                    'idade': a.age,
                    'peso_kg': a.peso,
                    'nascimento': a.date_of_birth.isoformat() if a.date_of_birth else None,
                })
            return _mcp_ok(req_id, {
                'structuredContent': {'pets': pets},
                'content': [{'type': 'text', 'text': json.dumps(pets, ensure_ascii=False, indent=2) if pets else '[]'}],
            })

        if tool_name == 'listar_vacinas_pet':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'pets:read')
            if scope_error:
                return scope_error
            animals_q = _integration_accessible_animals_query(user)
            animal_id = tool_args.get('animal_id')
            if animal_id:
                animals_q = animals_q.filter(Animal.id == int(animal_id))
            animals = animals_q.order_by(Animal.name).limit(50).all()
            from datetime import date as _date
            hoje = _date.today()
            data_out = []
            for a in animals:
                vacinas = (
                    Vacina.query.filter_by(animal_id=a.id)
                    .order_by(Vacina.aplicada_em.desc().nullslast())
                    .all()
                )
                aplicadas = []
                proximas = []
                for v in vacinas:
                    item = {
                        'nome': v.nome,
                        'data': v.aplicada_em.isoformat() if v.aplicada_em else None,
                        'fabricante': v.fabricante,
                        'veterinario': v.veterinario,
                    }
                    if v.aplicada:
                        aplicadas.append(item)
                    else:
                        item['atrasada'] = bool(v.aplicada_em and v.aplicada_em < hoje)
                        proximas.append(item)
                data_out.append({
                    'animal_id': a.id,
                    'pet': a.name,
                    'aplicadas': aplicadas,
                    'proximas_doses': proximas,
                })
            return _mcp_ok(req_id, {
                'structuredContent': {'vacinas': data_out},
                'content': [{'type': 'text', 'text': json.dumps(data_out, ensure_ascii=False, indent=2) if data_out else '[]'}],
            })

        if tool_name == 'obter_carteirinha_pet':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'pets:read')
            if scope_error:
                return scope_error
            animal_id = tool_args.get('animal_id')
            if not animal_id:
                return _mcp_err(req_id, -32602, 'animal_id é obrigatório.')
            animal = (
                _integration_accessible_animals_query(user)
                .filter(Animal.id == int(animal_id))
                .first()
            )
            if animal is None:
                return _mcp_err(req_id, -32602, 'Pet não encontrado ou sem acesso.')
            if animal.public_token:
                link = url_for('carteirinha_publica', token=animal.public_token, _external=True)
                payload = {'ativa': True, 'pet': animal.name, 'link': link}
                texto = f'Carteirinha de {animal.name}: {link}'
            else:
                payload = {
                    'ativa': False,
                    'pet': animal.name,
                    'como_ativar': (
                        'A carteirinha ainda não foi ativada. O tutor pode ativá-la na '
                        'ficha do pet em PetOrlândia (seção "Carteirinha digital").'
                    ),
                }
                texto = payload['como_ativar']
            return _mcp_ok(req_id, {
                'structuredContent': payload,
                'content': [{'type': 'text', 'text': texto}],
            })

        if tool_name == 'revisar_carteirinha_fotografada':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'pets:read')
            if scope_error:
                return scope_error
            if not _mcp_carteirinha_data(tool_args):
                return _mcp_err(req_id, -32602, 'dados_extraidos e obrigatorio. Envie uma transcricao estruturada das fotos.')
            payload = _mcp_carteirinha_preview(user, tool_args)
            return _mcp_ok(req_id, _mcp_json_content(payload))

        if tool_name == 'importar_carteirinha_fotografada':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'pets:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            try:
                animal_id = int(tool_args.get('animal_id') or 0)
            except (TypeError, ValueError):
                animal_id = 0
            animal = _integration_accessible_animals_query(user).filter(Animal.id == animal_id).first()
            if animal is None:
                return _mcp_err(req_id, -32004, 'Pet nao encontrado ou sem acesso para importar a carteirinha.')
            if not _mcp_carteirinha_data(tool_args):
                return _mcp_err(req_id, -32602, 'dados_extraidos e obrigatorio.')
            try:
                payload = _mcp_import_carteirinha(user, animal, tool_args)
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))
            return _mcp_ok(req_id, _mcp_json_content(payload))

        if tool_name == 'atualizar_perfil_pet':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'pets:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            animal = _mcp_find_animal_for_tool(user, tool_args)
            if animal is None:
                return _mcp_err(req_id, -32004, 'Pet nao encontrado ou sem acesso para atualizacao.')
            changed = []
            for key, attribute in (('nome', 'name'), ('sexo', 'sex'), ('microchip', 'microchip_number')):
                value = str(tool_args.get(key) or '').strip()
                if value and value != getattr(animal, attribute):
                    setattr(animal, attribute, value)
                    changed.append(key)
            birth_date = _mcp_parse_carteirinha_date(tool_args.get('data_nascimento'))
            if birth_date and birth_date != animal.date_of_birth:
                animal.date_of_birth = birth_date
                changed.append('data_nascimento')
            species_value = str(tool_args.get('especie') or '').strip()
            if species_value:
                species = _integration_resolve_species(species_value)
                if species and species.id != animal.species_id:
                    animal.species_id = species.id
                    changed.append('especie')
            breed_value = str(tool_args.get('raca') or '').strip()
            if breed_value:
                species = animal.species or _integration_resolve_species(species_value)
                breed = _integration_resolve_breed(species, breed_value) if species else None
                if breed and breed.id != animal.breed_id:
                    animal.breed_id = breed.id
                    changed.append('raca')
            coat = str(tool_args.get('pelagem') or '').strip()
            if coat:
                coat_note = f'Pelagem informada: {coat}.'
                if coat_note not in (animal.description or ''):
                    animal.description = '\n'.join(filter(None, [animal.description, coat_note]))
                    changed.append('pelagem')
            db.session.commit()
            return _mcp_ok(req_id, _mcp_json_content({'animal': _mcp_animal_payload(animal), 'campos_atualizados': changed}))

        if tool_name == 'atualizar_perfil_tutor':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'tutors:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            tutor = None
            tutor_id = tool_args.get('tutor_id')
            if tutor_id:
                try:
                    tutor = db.session.get(User, int(tutor_id))
                except (TypeError, ValueError):
                    tutor = None
            if tutor is None:
                animal = _mcp_find_animal_for_tool(user, tool_args)
                tutor = animal.owner if animal else None
            if tutor is None:
                return _mcp_err(req_id, -32004, 'Tutor nao encontrado ou sem acesso pelo pet informado.')
            allowed_animal = _integration_accessible_animals_query(user).filter(Animal.user_id == tutor.id).first()
            if allowed_animal is None and not _mcp_user_is_admin(user):
                return _mcp_err(req_id, -32004, 'Tutor nao encontrado ou sem acesso.')
            changed = []
            for key, attribute in (
                ('nome', 'name'), ('telefone', 'phone'), ('telefone_alternativo', 'phone2'),
                ('endereco', 'address'), ('email', 'email'),
            ):
                value = str(tool_args.get(key) or '').strip()
                if not value or value == getattr(tutor, attribute):
                    continue
                if attribute == 'email' and User.query.filter(User.email == value, User.id != tutor.id).first():
                    return _mcp_err(req_id, -32602, 'O e-mail informado ja pertence a outro cadastro.')
                setattr(tutor, attribute, value)
                changed.append(key)
            db.session.commit()
            return _mcp_ok(req_id, _mcp_json_content({'tutor': _mcp_owner_payload(tutor), 'campos_atualizados': changed}))

        if tool_name == 'registrar_vacina_pet':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'pets:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            animal = _mcp_find_animal_for_tool(user, tool_args)
            applied_on = _mcp_parse_carteirinha_date(tool_args.get('aplicada_em'))
            name = str(tool_args.get('nome') or '').strip()
            if animal is None or not name or not applied_on:
                return _mcp_err(req_id, -32602, 'Informe um pet acessivel, nome da vacina e data de aplicacao validos.')
            lot = str(tool_args.get('lote') or '').strip() or None
            vaccine = Vacina.query.filter_by(animal_id=animal.id, nome=name, aplicada_em=applied_on, lote=lot).first()
            created = vaccine is None
            if created:
                next_due = _mcp_parse_carteirinha_date(tool_args.get('proxima_dose'))
                interval = (next_due - applied_on).days if next_due and next_due > applied_on else None
                vaccine = Vacina(
                    animal_id=animal.id, nome=name, tipo=str(tool_args.get('tipo') or 'Historico informado').strip(),
                    fabricante=str(tool_args.get('fabricante') or '').strip() or None, lote=lot, aplicada=True,
                    aplicada_em=applied_on, intervalo_dias=interval,
                    frequencia='anual' if interval and 330 <= interval <= 400 else None,
                    observacoes=str(tool_args.get('observacoes') or 'Registrado pelo ChatGPT.').strip(), created_by=user.id,
                )
                db.session.add(vaccine)
                db.session.commit()
            return _mcp_ok(req_id, _mcp_json_content({'vacina': {'id': vaccine.id, 'nome': vaccine.nome, 'aplicada_em': vaccine.aplicada_em.isoformat()}, 'criada_agora': created}))

        if tool_name == 'registrar_vermifugacao_pet':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'pets:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            if not _mcp_ensure_carteirinha_tables():
                return _mcp_err(req_id, -32603, 'Nao foi possivel preparar o historico de saude do pet.')
            animal = _mcp_find_animal_for_tool(user, tool_args)
            occurred_on = _mcp_parse_carteirinha_date(tool_args.get('administrada_em'))
            title = str(tool_args.get('medicamento') or '').strip()
            if animal is None or not title or not occurred_on:
                return _mcp_err(req_id, -32602, 'Informe um pet acessivel, medicamento e data de administracao validos.')
            record = AnimalHealthRecord.query.filter_by(animal_id=animal.id, kind='vermifugacao', title=title, occurred_on=occurred_on).first()
            created = record is None
            if created:
                try:
                    weight = float(tool_args.get('peso_kg')) if tool_args.get('peso_kg') is not None else None
                except (TypeError, ValueError):
                    return _mcp_err(req_id, -32602, 'peso_kg deve ser numerico quando informado.')
                record = AnimalHealthRecord(
                    animal_id=animal.id, created_by_id=user.id, kind='vermifugacao', title=title, occurred_on=occurred_on,
                    next_due_on=_mcp_parse_carteirinha_date(tool_args.get('proxima_dose')), weight_kg=weight,
                    notes=str(tool_args.get('observacoes') or 'Registrado pelo ChatGPT.').strip(), source='chatgpt_manual',
                )
                db.session.add(record)
                db.session.commit()
            return _mcp_ok(req_id, _mcp_json_content({'vermifugacao': {'id': record.id, 'medicamento': record.title, 'administrada_em': record.occurred_on.isoformat()}, 'criada_agora': created}))

        if tool_name == 'listar_agendamentos':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'appointments:read')
            if scope_error:
                return scope_error
            q = _integration_accessible_appointments_query(user)
            status_filter = str(tool_args.get('status', '') or '').strip()
            if status_filter:
                q = q.filter(Appointment.status == status_filter)
            appts = q.order_by(Appointment.scheduled_at.desc()).limit(50).all()
            data_out = [
                {
                    'id': a.id,
                    'pet': a.animal.name if a.animal else None,
                    'data': a.scheduled_at.isoformat() if a.scheduled_at else None,
                    'status': a.status,
                    'tipo': a.kind,
                    'notas': a.notes,
                }
                for a in appts
            ]
            return _mcp_ok(req_id, {
                'structuredContent': {'agendamentos': data_out},
                'content': [{'type': 'text', 'text': json.dumps(data_out, ensure_ascii=False, indent=2) if data_out else '[]'}],
            })

        if tool_name == 'interpretar_mensagem_livre_atendimento':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'profile')
            if scope_error:
                return scope_error
            try:
                interpreted = _integration_extract_freeform_intake(tool_args)
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))
            return _mcp_ok(req_id, _mcp_json_content(interpreted))

        if tool_name == 'assistente_operacional_veterinario':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'profile')
            if scope_error:
                return scope_error
            try:
                planning = _integration_infer_assistant_action(user, tool_args)
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))

            action = planning.get('acao_sugerida')
            missing_fields = planning.get('campos_a_confirmar') or []
            needs_confirmation = action in {
                'cadastrar_tutor_e_pets',
                'agendar_consulta',
                'registrar_consulta_clinica',
            }
            response_payload = {
                'acao_sugerida': action,
                'argumentos_sugeridos': planning.get('argumentos_sugeridos') or {},
                'campos_a_confirmar': missing_fields,
                'resumo_interpretado': (planning.get('intake') or {}).get('resumo_interpretado'),
                'pode_executar_agora': needs_confirmation and not missing_fields,
                'confirmacao_necessaria': needs_confirmation,
                'executado': False,
            }

            confirmation_value = str(tool_args.get('confirmar_gravacao') or '').strip().lower()
            confirmed = confirmation_value in {'sim', 'true', '1', 'confirmado', 'confirmar'}

            if confirmed:
                required_scopes_by_action = {
                    'cadastrar_tutor_e_pets': ('tutors:write', 'pets:write'),
                    'agendar_consulta': ('appointments:write',),
                    'registrar_consulta_clinica': ('consultations:write',),
                }
                action_scopes = required_scopes_by_action.get(action, ())
                if action_scopes:
                    scope_error = _mcp_require_scopes(req_id, token_scope_set, *action_scopes)
                    if scope_error:
                        return scope_error
                if missing_fields:
                    return _mcp_ok(req_id, _mcp_json_content(response_payload))
                try:
                    execution = _integration_execute_assistant_action(user, planning)
                except PermissionError as exc:
                    return _mcp_err(req_id, -32003, str(exc))
                except ValueError as exc:
                    return _mcp_err(req_id, -32602, str(exc))
                response_payload['executado'] = True
                response_payload['resultado_execucao'] = execution

            return _mcp_ok(req_id, _mcp_json_content(response_payload))

        if tool_name == 'cadastrar_tutor_e_pets':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'tutors:write', 'pets:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            if not has_veterinarian_profile(user):
                return _mcp_err(req_id, -32003, 'This MCP tool is restricted to veterinarian accounts.')
            tutor_data = tool_args.get('tutor') or {}
            pets_data = tool_args.get('pets') or []
            if not tutor_data or not isinstance(pets_data, list) or not pets_data:
                return _mcp_err(req_id, -32602, 'Informe tutor e ao menos um pet para cadastro.')
            result = _integration_create_or_reuse_tutor_and_pets(
                user,
                tutor_data,
                pets_data,
                observacao_clinica=tool_args.get('observacao_clinica'),
                disponibilidade=tool_args.get('disponibilidade'),
            )
            return _mcp_ok(req_id, _mcp_json_content(result))

        if tool_name == 'registrar_consulta_clinica':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'consultations:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            if not has_veterinarian_profile(user):
                return _mcp_err(req_id, -32003, 'This MCP tool is restricted to veterinarian accounts.')
            animal = _mcp_find_animal_for_tool(user, tool_args)
            if not animal:
                return _mcp_err(req_id, -32004, 'Animal não encontrado no escopo disponível para este usuário.')
            try:
                consulta = _integration_upsert_consulta(user, animal, tool_args)
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))
            return _mcp_ok(req_id, _mcp_json_content({
                'consulta_id': consulta.id,
                'animal_id': consulta.animal_id,
                'status': consulta.status,
                'finalizada_em': _integration_format_datetime(consulta.finalizada_em),
                'queixa_principal': consulta.queixa_principal,
                'conduta': consulta.conduta,
            }))

        if tool_name == 'registrar_bloco_exames':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'exams:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            if not has_veterinarian_profile(user):
                return _mcp_err(req_id, -32003, 'This MCP tool is restricted to veterinarian accounts.')
            animal = _mcp_find_animal_for_tool(user, tool_args)
            if not animal:
                return _mcp_err(req_id, -32004, 'Animal não encontrado no escopo disponível para este usuário.')
            try:
                bloco = _integration_create_exam_block(user, animal, tool_args)
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))
            return _mcp_ok(req_id, _mcp_json_content({
                'bloco_id': bloco.id,
                'animal_id': bloco.animal_id,
                'observacoes_gerais': bloco.observacoes_gerais,
                'total_exames': len(bloco.exames or []),
            }))

        if tool_name == 'criar_exame_imagem':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'exams:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            if not has_veterinarian_profile(user):
                return _mcp_err(req_id, -32003, 'This MCP tool is restricted to veterinarian accounts.')
            try:
                result = _integration_create_exame_imagem(user, tool_args)
            except PermissionError as exc:
                return _mcp_err(req_id, -32003, str(exc))
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))
            return _mcp_ok(req_id, _mcp_json_content(result))

        if tool_name == 'anexar_pdf_exame_imagem':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'exams:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            exame = db.session.get(ExameImagem, int(tool_args.get('exame_id') or 0))
            if not exame:
                return _mcp_err(req_id, -32004, 'Exame de imagem nao encontrado.')
            if getattr(user, 'role', '') != 'admin' and exame.profissional_id != user.id:
                return _mcp_err(req_id, -32003, 'Somente o profissional criador pode anexar PDF.')
            try:
                result = _integration_store_exame_pdf(user, exame, _integration_extract_pdf_file_reference(tool_args))
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))
            return _mcp_ok(req_id, _mcp_json_content({'exame': result}))

        if tool_name in {'liberar_exame_para_clinica', 'liberar_exame_para_tutor'}:
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'exams:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            try:
                result = _integration_release_exame_imagem(user, tool_args, target='clinica' if tool_name.endswith('clinica') else 'tutor')
            except PermissionError as exc:
                return _mcp_err(req_id, -32003, str(exc))
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))
            return _mcp_ok(req_id, _mcp_json_content({'exame': result}))

        if tool_name == 'listar_historico_medico_animal':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'clinical_summary:read', 'exams:read')
            if scope_error:
                return scope_error
            animal = _integration_find_accessible_animal(user, animal_id=tool_args.get('animal_id'), animal_name=tool_args.get('nome_animal'))
            if not animal:
                return _mcp_err(req_id, -32004, 'Animal nao encontrado no escopo disponivel.')
            exames_imagem = _integration_list_exame_imagem_history(user, animal)
            if _integration_reconcile_exam_documents(animal, exames_imagem):
                db.session.commit()
            result = {
                'animal': _serialize_calendar_pet(animal),
                'exames': [
                    _integration_serialize_exame_imagem(exame, user, include_internal_links=False)
                    for exame in exames_imagem
                ],
                'pdfs_disponiveis': [
                    summary
                    for summary in (
                        _integration_exame_imagem_pdf_summary(exame, user, include_internal_links=False)
                        for exame in exames_imagem
                    )
                    if summary
                ],
            }
            return _mcp_ok(req_id, _mcp_json_content(result))

        if tool_name == 'obter_documento_clinico':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'exams:read')
            if scope_error:
                return scope_error
            exame = None
            if tool_args.get('exame_id'):
                exame = db.session.get(ExameImagem, int(tool_args.get('exame_id') or 0))
                if exame:
                    _integration_reconcile_exam_documents(exame.animal, [exame])
            elif tool_args.get('documento_id'):
                documento = db.session.get(AnimalDocumento, int(tool_args.get('documento_id') or 0))
                if documento:
                    exame = _integration_find_exame_by_documento(documento, user)
            if not exame:
                return _mcp_err(req_id, -32004, 'Documento clinico nao encontrado.')
            if not _integration_user_can_access_exame_imagem(user, exame):
                return _mcp_err(req_id, -32003, 'Sem permissao para acessar este documento.')
            db.session.commit()
            return _mcp_ok(req_id, _mcp_json_content(
                _integration_exame_imagem_document_payload(exame, user, include_internal_links=False)
            ))

        if tool_name == 'buscar_ou_criar_clinica_requisitante':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'exams:write')
            if scope_error:
                return scope_error
            if not has_veterinarian_profile(user):
                return _mcp_err(req_id, -32003, 'This MCP tool is restricted to veterinarian accounts.')
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            try:
                clinic, created = _integration_find_or_create_external_clinic(user, {'nome': tool_args.get('nome_clinica'), 'cnpj': tool_args.get('cnpj'), 'email': tool_args.get('email'), 'telefone': tool_args.get('telefone')})
                db.session.commit()
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))
            return _mcp_ok(req_id, _mcp_json_content({'clinica': {'id': clinic.id, 'nome': clinic.nome, 'criada_agora': created}}))

        if tool_name == 'buscar_ou_criar_tutor_animal':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'tutors:write', 'pets:write')
            if scope_error:
                return scope_error
            if not has_veterinarian_profile(user):
                return _mcp_err(req_id, -32003, 'This MCP tool is restricted to veterinarian accounts.')
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            clinic = db.session.get(Clinica, int(tool_args.get('clinica_id') or _integration_user_clinic_id(user) or 0))
            if not clinic:
                return _mcp_err(req_id, -32602, 'Informe clinica_id ou conecte um usuario com clinica vinculada.')
            user_clinic_id = _integration_user_clinic_id(user)
            if getattr(user, 'role', '') != 'admin' and user_clinic_id != clinic.id:
                return _mcp_err(req_id, -32003, 'A clinica informada nao pertence ao escopo profissional desta conta.')
            try:
                tutor, tutor_created, provisional = _integration_find_or_create_tutor_for_clinic(user, clinic, {'nome': tool_args.get('nome_tutor'), 'telefone': tool_args.get('telefone'), 'email': tool_args.get('email')})
                animal, animal_created = _integration_find_or_create_pet_for_tutor(user, clinic, tutor, {'nome': tool_args.get('nome_animal'), 'especie': tool_args.get('especie'), 'idade': tool_args.get('idade'), 'raca': tool_args.get('raca'), 'sexo': tool_args.get('sexo')})
                db.session.commit()
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))
            return _mcp_ok(req_id, _mcp_json_content({'tutor': {'id': tutor.id, 'nome': tutor.name, 'criado_agora': tutor_created, 'email_provisorio': provisional}, 'animal': {'id': animal.id, 'nome': animal.name, 'criado_agora': animal_created}, 'clinica': {'id': clinic.id, 'nome': clinic.nome}}))

        if tool_name in {'gerar_convite_primeiro_acesso_clinica', 'gerar_convite_acesso_tutor'}:
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'exams:write')
            if scope_error:
                return scope_error
            if not has_veterinarian_profile(user):
                return _mcp_err(req_id, -32003, 'This MCP tool is restricted to veterinarian accounts.')
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            if tool_name.endswith('clinica'):
                clinic = db.session.get(Clinica, int(tool_args.get('clinica_id'))) if tool_args.get('clinica_id') else None
                if not clinic and tool_args.get('nome_clinica'):
                    clinic, _created = _integration_find_or_create_external_clinic(user, {'nome': tool_args.get('nome_clinica'), 'email': tool_args.get('email'), 'telefone': tool_args.get('telefone')})
                if not clinic:
                    return _mcp_err(req_id, -32602, 'Informe clinica_id ou nome_clinica.')
                if not (tool_args.get('email') or tool_args.get('telefone') or clinic.email or clinic.telefone):
                    return _mcp_err(req_id, -32602, 'Informe email ou telefone para enviar o primeiro acesso da clinica.')
                exame = db.session.get(ExameImagem, int(tool_args.get('exame_id'))) if tool_args.get('exame_id') else None
                if not exame or not _integration_user_can_access_exame_imagem(user, exame):
                    return _mcp_err(req_id, -32003, 'Informe um exame de imagem criado ou acessivel por esta conta.')
                if exame.clinica_requisitante_id and exame.clinica_requisitante_id != clinic.id:
                    return _mcp_err(req_id, -32003, 'A clinica nao corresponde ao exame informado.')
                _integration_reconcile_exam_documents(exame.animal, [exame])
                invite = _create_external_onboarding_invite('clinic', user, clinic=clinic, tutor=getattr(exame, 'tutor', None), animal=getattr(exame, 'animal', None), exam=getattr(exame, 'exame_solicitado', None), exam_image=exame, message='Primeiro acesso gratuito da clinica requisitante.')
            else:
                tutor = db.session.get(User, int(tool_args.get('tutor_id'))) if tool_args.get('tutor_id') else None
                animal = db.session.get(Animal, int(tool_args.get('animal_id') or 0))
                if not tutor and tool_args.get('nome_tutor') and animal and animal.owner and _integration_normalize_match_text(animal.owner.name) == _integration_normalize_match_text(tool_args.get('nome_tutor')):
                    tutor = animal.owner
                if not tutor or not animal or animal.user_id != tutor.id:
                    return _mcp_err(req_id, -32602, 'Informe tutor e animal vinculados.')
                allowed_animal = _integration_accessible_animals_query(user).filter(Animal.id == animal.id).first()
                if not allowed_animal:
                    return _mcp_err(req_id, -32003, 'O animal informado nao pertence ao escopo desta conta.')
                exame = db.session.get(ExameImagem, int(tool_args.get('exame_id'))) if tool_args.get('exame_id') else None
                if exame:
                    if exame.animal_id != animal.id or not _integration_user_can_access_exame_imagem(user, exame):
                        return _mcp_err(req_id, -32003, 'O exame informado nao pertence ao animal acessivel.')
                    _integration_reconcile_exam_documents(exame.animal, [exame])
                invite = _create_external_onboarding_invite('tutor', user, clinic=animal.clinica, tutor=tutor, animal=animal, exam=getattr(exame, 'exame_solicitado', None), exam_image=exame, message='Acesso restrito a ficha do proprio animal.')
            db.session.commit()
            convite = {'token': invite.token if invite else None, **_invite_payload(invite)}
            return _mcp_ok(req_id, _mcp_json_content({'convite': convite}))

        if tool_name == 'abrir_importador_laudo_volante':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'profile')
            if scope_error:
                return scope_error
            draft_laudo_url = (tool_args.get('laudo_url') or '').strip()
            if _is_local_chatgpt_file_path(draft_laudo_url):
                draft_laudo_url = ''
            draft = {
                'exame_id': tool_args.get('exame_id'),
                'bloco_id': tool_args.get('bloco_id'),
                'clinica': tool_args.get('clinica') or {},
                'tutor': tool_args.get('tutor') or {},
                'animal': tool_args.get('animal') or {},
                'exame': tool_args.get('exame') or {},
                'laudo_texto': tool_args.get('laudo_texto') or '',
                'laudo_url': draft_laudo_url,
                'laudo_filename': tool_args.get('laudo_filename') or '',
                'laudo_arquivo': _mcp_extract_file_reference(tool_args, 'laudo_arquivo', 'arquivo_laudo', 'laudo_file'),
                'mensagem_clinica': (
                    tool_args.get('mensagem_clinica')
                    or 'Laudo finalizado e disponivel no PetOrlandia.'
                ),
                'mensagem_tutor': tool_args.get('mensagem_tutor') or '',
            }
            missing_fields = tool_args.get('campos_a_confirmar') or []
            response_payload = {
                'rascunho': draft,
                'campos_a_confirmar': missing_fields if isinstance(missing_fields, list) else [],
            }
            return _mcp_ok(req_id, {
                'structuredContent': response_payload,
                'content': [
                    {
                        'type': 'text',
                        'text': 'Revisão do laudo pronta para confirmação no chat.',
                    }
                ],
            })

        if tool_name == 'importar_laudo_volante':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'tutors:write', 'pets:write', 'exams:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            if not has_veterinarian_profile(user):
                return _mcp_err(req_id, -32003, 'This MCP tool is restricted to veterinarian accounts.')
            try:
                result = _integration_import_mobile_exam_report(user, tool_args)
            except ValueError as exc:
                db.session.rollback()
                return _mcp_err(req_id, -32602, str(exc))
            response = _mcp_json_content(result)
            response['structuredContent'] = result
            return _mcp_ok(req_id, response)

        if tool_name == 'sugerir_modelo_laudo':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'exams:read')
            if scope_error:
                return scope_error
            if not has_veterinarian_profile(user):
                return _mcp_err(req_id, -32003, 'This MCP tool is restricted to veterinarian accounts.')
            try:
                result = _integration_suggest_report_template(user, tool_args)
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))
            response = _mcp_json_content(result)
            response['structuredContent'] = result
            return _mcp_ok(req_id, response)

        if tool_name == 'agendar_consulta':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'appointments:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            animal = _mcp_find_animal_for_tool(user, tool_args)
            if not animal:
                return _mcp_err(req_id, -32004, 'Animal não encontrado no escopo disponível para este usuário.')
            try:
                appointment = _integration_schedule_consulta(user, animal, tool_args)
            except PermissionError as exc:
                return _mcp_err(req_id, -32003, str(exc))
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))
            return _mcp_ok(req_id, _mcp_json_content({
                'appointment_id': appointment.id,
                'animal_id': appointment.animal_id,
                'tipo': appointment.kind,
                'status': appointment.status,
                'scheduled_at': _integration_format_datetime(appointment.scheduled_at),
                'clinica_id': appointment.clinica_id,
            }))

        if tool_name == 'agendar_retorno':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'appointments:write')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            if not has_veterinarian_profile(user):
                return _mcp_err(req_id, -32003, 'This MCP tool is restricted to veterinarian accounts.')
            consulta_id = tool_args.get('consulta_id')
            try:
                consulta_id = int(consulta_id)
            except (TypeError, ValueError):
                return _mcp_err(req_id, -32602, 'consulta_id deve ser numérico.')
            consulta = _integration_accessible_consultas_query(user).filter(Consulta.id == consulta_id).first()
            if not consulta:
                return _mcp_err(req_id, -32004, 'Consulta não encontrada no escopo disponível para este usuário.')
            try:
                selected_vet_id = int(tool_args.get('veterinario_id') or user.veterinario.id)
                selected_vet = db.session.get(Veterinario, selected_vet_id)
                own_vet = getattr(user, 'veterinario', None)
                if not selected_vet or (selected_vet.id != getattr(own_vet, 'id', None) and selected_vet.clinica_id != _integration_user_clinic_id(user)):
                    return _mcp_err(req_id, -32003, 'O veterinario selecionado nao pertence ao escopo desta clinica.')
                payload = ReturnAppointmentDTO(
                    date=_integration_parse_date_arg(tool_args.get('data')),
                    time=_integration_parse_time_arg(tool_args.get('hora')),
                    veterinarian_id=selected_vet_id,
                    reason=(tool_args.get('motivo') or '').strip() or None,
                )
                result = schedule_return_appointment(
                    consulta=consulta,
                    actor_id=user.id,
                    actor_vet_id=getattr(getattr(user, 'veterinario', None), 'id', None),
                    payload=payload,
                )
            except ValueError as exc:
                return _mcp_err(req_id, -32602, str(exc))
            latest_return = (
                Appointment.query
                .filter_by(consulta_id=consulta.id, kind='retorno')
                .order_by(Appointment.id.desc())
                .first()
            )
            return _mcp_ok(req_id, _mcp_json_content({
                'success': result.success,
                'message': result.message,
                'category': result.category,
                'appointment_id': latest_return.id if latest_return else None,
                'scheduled_at': _integration_format_datetime(latest_return.scheduled_at) if latest_return else None,
            }))

        if tool_name == 'obter_resumo_clinico_animal':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'clinical_summary:read')
            if scope_error:
                return scope_error
            animal = _mcp_find_animal_for_tool(user, tool_args)
            if not animal:
                return _mcp_err(req_id, -32004, 'Animal não encontrado no escopo disponível para este usuário.')
            return _mcp_ok(req_id, _mcp_json_content(_integration_build_clinical_summary(user, animal)))

        if tool_name == 'listar_agenda_do_dia':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'appointments:read')
            if scope_error:
                return scope_error
            target_date = None
            raw_date = str(tool_args.get('data') or '').strip()
            if raw_date:
                try:
                    target_date = date.fromisoformat(raw_date)
                except ValueError:
                    return _mcp_err(req_id, -32602, 'A data deve estar no formato YYYY-MM-DD.')
            return _mcp_ok(req_id, _mcp_json_content(_integration_build_today_agenda(user, target_date=target_date)))

        if tool_name == 'buscar_produtos_loja':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'profile')
            if scope_error:
                return scope_error
            products = _mcp_store_products(
                search_term=tool_args.get('termo') or tool_args.get('q'),
                category=tool_args.get('categoria'),
                limit=tool_args.get('limite') or 12,
            )
            return _mcp_ok(req_id, _mcp_json_content({
                'total': len(products),
                'produtos': [_mcp_product_payload(product, include_variants=False) for product in products],
                'observacao': 'Mostre somente estes produtos reais. Se não houver resultado, peça outro termo ou ofereça abrir a loja.',
                'url_loja': url_for('loja', _external=True),
            }))

        if tool_name == 'obter_produto_loja':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'profile')
            if scope_error:
                return scope_error
            try:
                product_id = int(tool_args.get('produto_id') or 0)
            except (TypeError, ValueError):
                return _mcp_err(req_id, -32602, 'produto_id deve ser numérico.')
            product = db.session.get(Product, product_id)
            if not product or product.status != 'active':
                return _mcp_err(req_id, -32004, 'Produto não encontrado ou indisponível.')
            return _mcp_ok(req_id, _mcp_json_content({'produto': _mcp_product_payload(product)}))

        if tool_name == 'criar_pedido_loja':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'profile')
            if scope_error:
                return scope_error
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            raw_items = tool_args.get('itens') or []
            if not isinstance(raw_items, list) or not raw_items:
                return _mcp_err(req_id, -32602, 'Informe ao menos um item confirmado para criar o pedido.')
            try:
                resolved_items = [_mcp_resolve_product_item(item) for item in raw_items if isinstance(item, dict)]
            except (TypeError, ValueError) as exc:
                return _mcp_err(req_id, -32602, str(exc))
            if not resolved_items:
                return _mcp_err(req_id, -32602, 'Nenhum item válido foi informado.')
            order = Order(user_id=user.id, shipping_address=(tool_args.get('endereco_entrega') or '').strip() or None)
            db.session.add(order)
            db.session.flush()
            for product, variant, quantity in resolved_items:
                unit_price = variant.preco_publico if variant else product.preco_publico
                item_name = variant.display_name if variant else product.name
                db.session.add(OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    variant_id=variant.id if variant else None,
                    item_name=item_name,
                    quantity=quantity,
                    unit_price=unit_price or 0,
                ))
            db.session.commit()
            return _mcp_ok(req_id, _mcp_json_content({
                'success': True,
                'message': 'Pedido criado. O usuário deve abrir o link do carrinho para revisar entrega e pagar no PetOrlandia.',
                'pedido': _mcp_order_payload(order),
                'pagamento_no_chatgpt': False,
            }))

        if tool_name == 'buscar_paciente':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'pets:read')
            if scope_error:
                return scope_error
            pacientes = [
                _mcp_animal_payload(animal)
                for animal in _mcp_search_animals(user, tool_args.get('termo'), tool_args.get('limite') or 10)
            ]
            return _mcp_ok(req_id, _mcp_json_content({
                'total': len(pacientes),
                'pacientes': pacientes,
            }))

        if tool_name == 'obter_timeline_clinica':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'clinical_summary:read', 'exams:read', 'vaccines:read')
            if scope_error:
                return scope_error
            animal = _mcp_find_animal_for_tool(user, tool_args)
            if not animal:
                return _mcp_err(req_id, -32004, 'Animal não encontrado no escopo disponível para este usuário.')
            return _mcp_ok(req_id, _mcp_json_content(_mcp_build_timeline(user, animal)))

        if tool_name == 'preparar_consulta':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'appointments:read', 'clinical_summary:read', 'exams:read', 'vaccines:read')
            if scope_error:
                return scope_error
            animal = _mcp_find_animal_for_tool(user, tool_args)
            if not animal:
                return _mcp_err(req_id, -32004, 'Animal não encontrado no escopo disponível para este usuário.')
            appointment_id = tool_args.get('appointment_id')
            try:
                parsed_appointment_id = int(appointment_id) if appointment_id is not None else None
            except (TypeError, ValueError):
                return _mcp_err(req_id, -32602, 'appointment_id deve ser numérico quando informado.')
            return _mcp_ok(req_id, _mcp_json_content(_mcp_build_consult_prep(user, animal, appointment_id=parsed_appointment_id)))

        if tool_name == 'listar_pendencias_clinicas':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'appointments:read', 'exams:read', 'vaccines:read')
            if scope_error:
                return scope_error
            return _mcp_ok(req_id, _mcp_json_content(_integration_build_clinical_pendencies(user)))

        if tool_name == 'listar_vacinas_pendentes':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'vaccines:read')
            if scope_error:
                return scope_error
            pendencias = _integration_build_clinical_pendencies(user)
            return _mcp_ok(req_id, _mcp_json_content({
                'resumo': {
                    'vacinas_atrasadas': pendencias['resumo']['vacinas_atrasadas'],
                },
                'vacinas_atrasadas': pendencias['vacinas_atrasadas'],
            }))

        if tool_name == 'listar_exames_pendentes':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'exams:read')
            if scope_error:
                return scope_error
            pendencias = _integration_build_clinical_pendencies(user)
            return _mcp_ok(req_id, _mcp_json_content({
                'resumo': {
                    'agendamentos_de_exame_pendentes': pendencias['resumo']['agendamentos_de_exame_pendentes'],
                    'solicitacoes_de_exame_pendentes': pendencias['resumo']['solicitacoes_de_exame_pendentes'],
                },
                'exames_agendados_pendentes': pendencias['exames_agendados_pendentes'],
                'exames_solicitados_pendentes': pendencias['exames_solicitados_pendentes'],
            }))

        if tool_name == 'listar_retornos_pendentes':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'appointments:read')
            if scope_error:
                return scope_error
            pendencias = _integration_build_clinical_pendencies(user)
            return _mcp_ok(req_id, _mcp_json_content({
                'resumo': {
                    'retornos_pendentes': pendencias['resumo']['retornos_pendentes'],
                },
                'retornos_pendentes': pendencias['retornos_pendentes'],
            }))

        if tool_name == 'gerar_orientacao_tutor':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'tutor_guidance:generate')
            if scope_error:
                return scope_error
            animal = _mcp_find_animal_for_tool(user, tool_args)
            if not animal:
                return _mcp_err(req_id, -32004, 'Animal não encontrado no escopo disponível para este usuário.')
            consulta_id = tool_args.get('consulta_id')
            try:
                parsed_consulta_id = int(consulta_id) if consulta_id is not None else None
            except (TypeError, ValueError):
                return _mcp_err(req_id, -32602, 'consulta_id deve ser numérico quando informado.')
            return _mcp_ok(
                req_id,
                _mcp_json_content(_integration_generate_tutor_guidance(user, animal, consulta_id=parsed_consulta_id)),
            )

        if tool_name == 'gerar_mensagem_whatsapp_tutor':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'tutor_guidance:generate')
            if scope_error:
                return scope_error
            animal = _mcp_find_animal_for_tool(user, tool_args)
            if not animal:
                return _mcp_err(req_id, -32004, 'Animal não encontrado no escopo disponível para este usuário.')
            consulta_id = tool_args.get('consulta_id')
            try:
                parsed_consulta_id = int(consulta_id) if consulta_id is not None else None
            except (TypeError, ValueError):
                return _mcp_err(req_id, -32602, 'consulta_id deve ser numérico quando informado.')
            guidance = _integration_generate_tutor_guidance(user, animal, consulta_id=parsed_consulta_id)
            tutor = getattr(animal, 'owner', None)
            contexto = (tool_args.get('contexto') or '').strip()
            tipo = (tool_args.get('tipo') or 'orientacao').strip().lower()
            linhas = [
                f'Olá{", " + tutor.name.split()[0] if getattr(tutor, "name", None) else ""}.',
                f'Segue orientação sobre {animal.name}:',
                guidance.get('orientacao') or guidance.get('texto') or guidance.get('message') or '',
            ]
            if contexto:
                linhas.extend(['', contexto])
            linhas.append('')
            linhas.append('PetOrlandia')
            mensagem = '\n'.join([linha for linha in linhas if linha is not None]).strip()
            phone_digits = ''.join(ch for ch in (getattr(tutor, 'phone', '') or '') if ch.isdigit())
            whatsapp_url = None
            if len(phone_digits) in (10, 11):
                whatsapp_url = f'https://wa.me/55{phone_digits}?text={quote_plus(mensagem)}'
            return _mcp_ok(req_id, _mcp_json_content({
                'tipo': tipo,
                'animal': _mcp_animal_payload(animal),
                'mensagem': mensagem,
                'whatsapp_url': whatsapp_url,
                'envio_automatico': False,
            }))

        if tool_name == 'gerar_handoff_clinico':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'handoff:read')
            if scope_error:
                return scope_error
            animal = _mcp_find_animal_for_tool(user, tool_args)
            if not animal:
                return _mcp_err(req_id, -32004, 'Animal não encontrado no escopo disponível para este usuário.')
            consulta_id = tool_args.get('consulta_id')
            try:
                parsed_consulta_id = int(consulta_id) if consulta_id is not None else None
            except (TypeError, ValueError):
                return _mcp_err(req_id, -32602, 'consulta_id deve ser numérico quando informado.')
            return _mcp_ok(
                req_id,
                _mcp_json_content(_integration_build_handoff(user, animal, consulta_id=parsed_consulta_id)),
            )

        if tool_name == 'listar_alertas_admin':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'profile')
            if scope_error:
                return scope_error
            if not _mcp_user_is_admin(user):
                return _mcp_err(req_id, -32003, 'Esta tool é restrita a administradores.')
            return _mcp_ok(
                req_id,
                _mcp_json_content(_mcp_admin_alerts(user, status=tool_args.get('status') or 'open', limit=tool_args.get('limite') or 30)),
            )

        if tool_name == 'resolver_alerta_admin':
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'profile')
            if scope_error:
                return scope_error
            if not _mcp_user_is_admin(user):
                return _mcp_err(req_id, -32003, 'Esta tool é restrita a administradores.')
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            try:
                alerta_id = int(tool_args.get('alerta_id') or 0)
            except (TypeError, ValueError):
                return _mcp_err(req_id, -32602, 'alerta_id deve ser numérico.')
            note = AdminActionNotification.query.filter_by(id=alerta_id, recipient_user_id=user.id).first()
            if not note:
                return _mcp_err(req_id, -32004, 'Alerta administrativo não encontrado.')
            action = (tool_args.get('acao') or 'resolver').strip().lower()
            from time_utils import now_in_brazil
            now = now_in_brazil()
            if action in {'ler', 'read'}:
                if note.status == 'unread':
                    note.status = 'read'
                    note.read_at = now
            elif action in {'resolver', 'resolve', 'resolved'}:
                note.status = 'resolved'
                note.read_at = note.read_at or now
                note.resolved_at = now
                note.resolved_by_id = user.id
            else:
                return _mcp_err(req_id, -32602, 'acao deve ser ler ou resolver.')
            db.session.commit()
            return _mcp_ok(req_id, _mcp_json_content({
                'success': True,
                'alerta': _mcp_admin_alert_payload(note),
            }))

        return _mcp_err(req_id, -32601, f'Tool not found: {tool_name}')

    # ── unknown method ────────────────────────────────────────────────────────
    return _mcp_err(req_id, -32601, f'Method not found: {method}')


@csrf.exempt
def mcp_protected_resource_metadata():
    """RFC 9396 / MCP spec: advertises the authorization server for this resource.

    This endpoint tells OAuth clients (Claude, ChatGPT) which authorization
    server protects the /mcp resource, enabling discovery even when the
    connector URL uses a path (e.g. https://www.petorlandia.com.br/mcp).
    """
    issuer = _oauth_issuer()
    resource_path = _mcp_resource_path()
    return jsonify({
        'resource': f'{issuer}{resource_path}',
        'authorization_servers': [issuer],
        'bearer_methods_supported': ['header'],
        # RFC 9728 §2: the scopes a client must request to access this resource.
        # Without this, MCP clients (ChatGPT/Claude) only request the default
        # OIDC scopes and never obtain pets:read / exams:write / etc.
        'scopes_supported': _oauth_order_scopes(_oauth_allowed_scopes()).split(),
        'resource_documentation': f'{issuer}{resource_path}',
    })

