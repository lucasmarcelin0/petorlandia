"""Views do domínio mcp (migrado do app.py)."""
from flask import Blueprint
import json
from datetime import date
from extensions import csrf, db
from flask import jsonify, make_response, request
from helpers import has_veterinarian_profile
from models import Animal, AnimalDocumento, Appointment, Clinica, Consulta, ExameImagem, OAuthAccessToken, User
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
    'gerar_handoff_clinico': {
        'title': 'Gerar handoff clinico',
        'scopes': ['handoff:read'],
        'annotations': _mcp_annotations(True, idempotent=True),
        'outputSchema': _mcp_object_output_schema('Handoff clinico resumido para outro profissional.'),
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


def _mcp_require_scopes(req_id, token_scope_set, *required_scopes):
    required_scope_set = {scope for scope in required_scopes if scope}
    missing_scopes = sorted(required_scope_set.difference(token_scope_set))
    if not missing_scopes:
        return None
    return _mcp_err_with_data(
        req_id,
        -32003,
        'This MCP tool requires additional OAuth scopes.',
        {
            'required_scopes': sorted(required_scope_set),
            'granted_scopes': sorted(token_scope_set),
            'missing_scopes': missing_scopes,
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


def _mcp_unauthorized():
    """Return 401 with WWW-Authenticate so that OAuth clients know how to auth."""
    issuer = _oauth_issuer()
    resource_url = f'{issuer}/mcp'
    metadata_url = f'{issuer}/.well-known/oauth-protected-resource'
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
            'version': '1.0.0',
            'protocol': 'mcp/2024-11-05',
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
            'protocolVersion': '2024-11-05',
            'serverInfo': {'name': 'PetOrlândia', 'version': '1.0.0'},
            'capabilities': {'tools': {}, 'resources': {}},
        })

    # ── notifications/initialized (client ack — no response body needed) ─────
    if method in ('notifications/initialized', 'initialized'):
        return ('', 204)

    if method == 'resources/list':
        return _mcp_ok(req_id, {'resources': [_mcp_laudo_volante_widget_resource()]})

    if method == 'resources/read':
        uri = str(params.get('uri') or '').strip()
        if uri != LAUDO_VOLANTE_WIDGET_URI:
            return _mcp_err(req_id, -32004, f'Resource not found: {uri}')
        return _mcp_ok(req_id, {
            'contents': [
                {
                    **_mcp_laudo_volante_widget_resource(),
                    'text': _mcp_laudo_volante_widget_html(),
                    '_meta': {
                        'ui': {
                            'prefersBorder': True,
                            'domain': _oauth_issuer(),
                            'csp': {
                                'connectDomains': [],
                                'resourceDomains': [],
                            },
                        },
                        'openai/widgetDescription': (
                            'Painel para revisar clinica, tutor, animal e laudo antes de gravar '
                            'o exame no PetOrlandia.'
                        ),
                        'openai/widgetPrefersBorder': True,
                        'openai/widgetDomain': _oauth_issuer(),
                        'openai/widgetCSP': {
                            'connect_domains': [],
                            'resource_domains': [],
                            'redirect_domains': [_oauth_issuer(), 'https://wa.me'],
                        },
                    },
                }
            ]
        })

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
                    'Use this immediately when o ultrassonografista enviar um link, PDF, arquivo ou texto de laudo '
                    'volante no ChatGPT. Abra este aplicativo na mesma resposta para revisar clinica, tutor, animal, '
                    'laudo e mensagens antes de gravar; o profissional nao deve precisar pedir o app em outra mensagem. '
                    'Esta tool renderiza o painel; o botao do painel chama importar_laudo_volante apos confirmacao.'
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
                    'ui': {'resourceUri': LAUDO_VOLANTE_WIDGET_URI},
                    'openai/outputTemplate': LAUDO_VOLANTE_WIDGET_URI,
                    'openai/widgetAccessible': True,
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
                    'Ajuda o veterinario a escrever novo relatorio/laudo usando laudos antigos como modelo. '
                    'Nao grava dados; retorna estrutura, frases-base e exemplos recentes semelhantes.'
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
        ]
        return _mcp_ok(req_id, {'tools': _mcp_finalize_tool_descriptors(tools)})

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
            confirmation_error = _mcp_require_confirmation(req_id, tool_args)
            if confirmation_error:
                return confirmation_error
            clinic = db.session.get(Clinica, int(tool_args.get('clinica_id') or _integration_user_clinic_id(user) or 0))
            if not clinic:
                return _mcp_err(req_id, -32602, 'Informe clinica_id ou conecte um usuario com clinica vinculada.')
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
                _integration_ensure_clinic_admin_user(
                    clinic,
                    email=tool_args.get('email'),
                    phone=tool_args.get('telefone'),
                    name=tool_args.get('nome_responsavel') or tool_args.get('responsavel_nome'),
                )
                exame = db.session.get(ExameImagem, int(tool_args.get('exame_id'))) if tool_args.get('exame_id') else None
                if exame:
                    _integration_reconcile_exam_documents(exame.animal, [exame])
                invite = _create_external_onboarding_invite('clinic', user, clinic=clinic, tutor=getattr(exame, 'tutor', None), animal=getattr(exame, 'animal', None), exam=getattr(exame, 'exame_solicitado', None), exam_image=exame, message='Primeiro acesso gratuito da clinica requisitante.')
            else:
                tutor = db.session.get(User, int(tool_args.get('tutor_id'))) if tool_args.get('tutor_id') else None
                animal = db.session.get(Animal, int(tool_args.get('animal_id') or 0))
                if not tutor and tool_args.get('nome_tutor') and animal and animal.owner and _integration_normalize_match_text(animal.owner.name) == _integration_normalize_match_text(tool_args.get('nome_tutor')):
                    tutor = animal.owner
                if not tutor or not animal or animal.user_id != tutor.id:
                    return _mcp_err(req_id, -32602, 'Informe tutor e animal vinculados.')
                exame = db.session.get(ExameImagem, int(tool_args.get('exame_id'))) if tool_args.get('exame_id') else None
                if exame:
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
                        'text': 'Abrindo painel para revisar o laudo antes de gravar no PetOrlandia.',
                    }
                ],
                '_meta': {
                    'ui': {'resourceUri': LAUDO_VOLANTE_WIDGET_URI},
                },
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
            scope_error = _mcp_require_scopes(req_id, token_scope_set, 'profile')
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
                payload = ReturnAppointmentDTO(
                    date=_integration_parse_date_arg(tool_args.get('data')),
                    time=_integration_parse_time_arg(tool_args.get('hora')),
                    veterinarian_id=int(tool_args.get('veterinario_id') or user.veterinario.id),
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
    return jsonify({
        'resource': f'{issuer}/mcp',
        'authorization_servers': [issuer],
        'bearer_methods_supported': ['header'],
        # RFC 9728 §2: the scopes a client must request to access this resource.
        # Without this, MCP clients (ChatGPT/Claude) only request the default
        # OIDC scopes and never obtain pets:read / exams:write / etc.
        'scopes_supported': _oauth_order_scopes(_oauth_allowed_scopes()).split(),
        'resource_documentation': f'{issuer}/mcp',
    })

