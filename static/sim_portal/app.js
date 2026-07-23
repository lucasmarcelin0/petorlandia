const STORAGE_KEY = "portal-sim-orlandia-v1";
const TOKEN_KEY = "portal-sim-orlandia-token";
// Quando servido como blueprint do PetOrlandia em /sim, a API fica em /sim/api.
const BASE_PATH = location.pathname.replace(/\/(index\.html)?$/, "");
const API_ROOT = `${BASE_PATH}/api`;

const initialState = {
  role: "establishment",
  view: "dashboard",
  printForm: "anexoI",
  protocol: {
    id: "SIM-ORL-2026-0001",
    status: "corrections",
    version: 2,
    submittedAt: "2026-07-23T09:14:00-03:00",
    updatedAt: "2026-07-23T09:32:00-03:00",
    assignedTo: "Lucas Marcelino Campos Ferreira",
  },
  application: {
    actType: "Registro de estabelecimento",
    otherAct: "",
    commitment: "Declaro que as informacoes prestadas sao verdadeiras e que o estabelecimento se compromete a cumprir a legislacao sanitaria aplicavel aos produtos de origem animal.",
  },
  establishment: {
    legalName: "LF-GUERRA MILK ORLANDIA - ME",
    tradeName: "GUERRA MILK",
    cnpj: "12.934.929/0001-77",
    cnae: "1052-0/00 - Fabricacao de laticinios",
    classification: "Unidade de beneficiamento de leite e derivados",
    address: "Avenida F, 464-A",
    district: "Jardim Boa Vista",
    city: "Orlandia",
    state: "SP",
    zip: "14620-000",
    email: "",
    phone: "",
    simNumber: "Pendente",
    propertyLink: "Proprietario",
    stateRegistration: "",
    municipalRegistration: "",
    area: "",
    legalNature: "Empresa privada",
  },
  legalResponsible: {
    name: "Jose Francisco Guerra",
    cpf: "",
    email: "",
    phone: "",
  },
  technicalResponsible: {
    name: "",
    cpf: "",
    council: "",
    email: "",
    phone: "",
  },
  production: {
    monthlyCapacity: "",
    rawMaterialOrigin: "",
    waterSupply: "",
    effluents: "",
    flow: "",
    transport: "",
    qualityControls: "",
    activities: "",
    employees: "",
    laundry: "",
    landDetails: "",
    locationArea: "",
    equipment: "",
    floorWalls: "",
    doorsWindowsCeiling: "",
    sanitaryBarrier: "",
    bathrooms: "",
    lightingVentilation: "",
    storage: "",
    labAnalysis: "",
    productionSchedule: "",
  },
  construction: {
    requestReason: "",
    buildingDescription: "",
    rooms: "",
    materials: "",
    coldRooms: "",
    waterAndSewage: "",
    observations: "",
  },
  products: [
    {
      id: crypto.randomUUID(),
      name: "Queijo / derivado lacteo a confirmar",
      brand: "Guerra Milk",
      status: "Rascunho",
      conservation: "Refrigerado",
      notes: "Denominacao e RTIQ precisam ser confirmados.",
      requestNature: "Registro de produto e rotulo",
      packageType: "",
      labelFeatures: "",
      composition: "",
      nutrition: "",
      manufacturingProcess: "",
      packagingProcess: "",
      storageConditions: "",
      marketTransport: "",
    },
  ],
  fiscalAct: {
    type: "Auto de infracao",
    number: "",
    date: "",
    inspectionPlace: "",
    legalBasis: "Lei Complementar municipal n. 84/2024 e Decreto municipal n. 5.368/2024.",
    facts: "",
    seizedMaterial: "",
    otherInfo: "",
    attenuatingAggravating: "",
    notification: "",
    witnesses: "",
  },
  journey: {
    signedAck: false,
  },
  documents: [
    { id: "requerimento-assinado", item: "01", group: "art11", name: "Requerimento ao SIM solicitando o registro", hint: "Preencha a ficha no portal, imprima o Anexo I, assine no gov.br e envie aqui.", required: true, status: "Pendente", file: "" },
    { id: "plantas-baixas", item: "02", group: "art11", name: "Planta baixa ou croqui das construcoes/reformas + memorial descritivo da construcao", hint: "Elaborados por profissional habilitado; o Anexo III do portal ajuda no memorial descritivo.", required: true, status: "Pendente", file: "" },
    { id: "contrato-social-cnpj", item: "03", group: "art11", name: "Contrato ou estatuto social registrado, quando houver firma constituida", hint: "Junta Comercial (empresas) ou cartorio; MEI usa o Certificado CCMEI.", required: true, status: "Pendente", file: "" },
    { id: "cpf-cnpj", item: "04", group: "art11", name: "CPF ou CNPJ, conforme o caso", hint: "Cartao CNPJ: emissao gratuita no site da Receita Federal.", link: "https://solucoes.receita.fazenda.gov.br/servicos/cnpjreva/cnpjreva_solicitacao.asp", required: true, status: "Pendente", file: "" },
    { id: "inscricao-estadual", item: "05", group: "art11", name: "Inscricao estadual/ICMS ou inscricao de Produtor Rural", hint: "Cadesp/Sefaz-SP; produtor rural usa a inscricao de produtor.", required: true, status: "Pendente", file: "" },
    { id: "alvara-prefeitura", item: "06", group: "art11", name: "Alvara de construcao e/ou localizacao e funcionamento", hint: "Emitido pela Prefeitura de Orlandia (setor de obras/tributos), ou documento equivalente.", required: true, status: "Pendente", file: "" },
    { id: "certidoes-ambientais", item: "07", group: "art11", name: "Licenca ambiental ou dispensa emitida pelo orgao ambiental", hint: "CETESB: licenca de operacao ou certidao de dispensa, conforme a atividade.", required: true, status: "Pendente", file: "" },
    { id: "exames-agua", item: "08", group: "art11", name: "Exames fisico-quimico e microbiologico da agua de abastecimento", hint: "Laboratorio credenciado; colete conforme orientacao do laboratorio.", required: true, status: "Pendente", file: "" },
    { id: "memorial-economico-sanitario", item: "09", group: "art11", name: "Memorial descritivo economico e sanitario do estabelecimento", hint: "Preencha o Anexo II (MTSE) no portal: ele atende este item. Imprima, assine e envie.", required: true, status: "Pendente", file: "" },
    { id: "manual-bpf", item: "10", group: "art11", name: "Manual de Boas Praticas de Fabricacao de Alimentos - BPF", hint: "Elaborado com o responsavel tecnico; descreve higiene, processos e controles do estabelecimento.", required: true, status: "Pendente", file: "" },
    { id: "registro-crmv", item: "11", group: "art11", name: "Registro do estabelecimento no CRMV-SP, se aplicavel", hint: "Confirme com o responsavel tecnico se a atividade exige registro no conselho.", required: false, status: "Pendente", file: "" },
    { id: "comprovante-taxa", item: "12", group: "art11", name: "Comprovante da Taxa de Inspecao Sanitaria", hint: "DISPENSADO em 2026: os servicos do art. 175-C sao prestados sem cobranca neste ano (LC 104/2026, art. 3, par. unico).", required: false, status: "Dispensado em 2026", file: "" },
    { id: "mtse", group: "anexos", name: "Anexo II - Memorial Tecnico-Sanitario (rascunho de trabalho)", hint: "Versao de trabalho do MTSE; a versao final assinada vai no item 09.", required: false, status: "Em correcao", file: "MTSE_rascunho.pdf" },
    { id: "rotulos-produtos", group: "anexos", name: "Anexo IV - Rotulos e memoriais por produto", hint: "Um Anexo IV por produto; cadastre os produtos no portal e imprima.", required: true, status: "Pendente", file: "" },
    { id: "doc-responsavel-legal", group: "anexos", name: "Documento do responsavel legal (RG/CPF ou CNH)", hint: "Copia simples e legivel.", required: true, status: "Pendente", file: "" },
    { id: "art-responsavel-tecnico", group: "anexos", name: "ART ou contrato do responsavel tecnico", hint: "Anotacao de responsabilidade tecnica emitida no conselho do RT.", required: true, status: "Pendente", file: "" },
    { id: "planta-fluxo", group: "anexos", name: "Croqui de fluxo (apoio)", hint: "Opcional; ajuda a analise do fluxo de producao.", required: false, status: "Pendente", file: "" },
  ],
  review: {
    decision: "Correcoes solicitadas",
    note: "Completar telefone, e-mail, responsavel tecnico, ART, produtos fabricados, origem da materia-prima e area de comercializacao. Cadastro SIVISA usado somente como historico.",
  },
  audit: [
    { at: "2026-07-23T08:58:00-03:00", who: "SIM Orlandia", action: "Processo criado a partir do historico SIVISA.", version: 1 },
    { at: "2026-07-23T09:14:00-03:00", who: "GUERRA MILK", action: "Ficha inicial enviada para analise.", version: 1 },
    { at: "2026-07-23T09:32:00-03:00", who: "Lucas Marcelino Campos Ferreira", action: "Correcoes solicitadas pelo SIM.", version: 2 },
  ],
};

let session = null;
let backendAvailable = false;
let notifications = [];
let activeUpload = null;
let registry = { establishments: [], fiscalActs: [], inspections: [], samples: [], audit: [] };
let registryEditing = { establishment: null, inspection: null, sample: null };
let fiscalActContext = { establishmentId: "", status: "Lavrado", scienceDate: "", loadedNumber: "" };
let state = loadState();

const SITUATIONS = ["Em registro", "Ativo", "Suspenso", "Interditado parcialmente", "Interditado totalmente", "Paralisado", "Cancelado"];
const RISK_LEVELS = ["Baixo", "Medio", "Alto"];
const ACT_TYPES = [
  "Auto de infracao",
  "Termo de advertencia",
  "Auto de apreensao",
  "Termo de suspensao de atividades",
  "Termo de interdicao",
  "Notificacao",
  "Termo de coleta de amostras",
];
const ACT_STATUSES = [
  "Lavrado",
  "Cientificado",
  "Em prazo de defesa",
  "Defesa apresentada",
  "Julgado em 1a instancia",
  "Em recurso",
  "Transitado em julgado",
  "Arquivado",
];
const INSPECTION_KINDS = [
  "Vistoria inicial de registro",
  "Inspecao periodica",
  "Inspecao permanente (abate)",
  "Reinspecao / retorno",
  "Supervisao",
  "Apuracao de denuncia",
  "Combate a clandestinidade",
];
const INSPECTION_DECISIONS = [
  "Sem nao conformidades",
  "Orientacao com prazo",
  "Notificacao formal",
  "Auto de infracao",
  "Apreensao de produtos",
  "Suspensao de atividades",
  "Interdicao total ou parcial",
  "Coleta de amostras",
];
const SAMPLE_STATUSES = ["Coletada", "Enviada ao laboratorio", "Resultado conforme", "Resultado nao conforme", "Contraprova solicitada"];

function loadState() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return structuredClone(initialState);
  try {
    return deepMerge(structuredClone(initialState), JSON.parse(raw));
  } catch {
    return structuredClone(initialState);
  }
}

function deepMerge(base, patch) {
  if (!patch || typeof patch !== "object") return base;
  Object.entries(patch).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      base[key] = value.map((item, index) => (
        item && typeof item === "object" && !Array.isArray(item)
          ? deepMerge(structuredClone((base[key] || [])[index] || {}), item)
          : item
      ));
    } else if (value && typeof value === "object") {
      base[key] = deepMerge(structuredClone(base[key] || {}), value);
    } else {
      base[key] = value;
    }
  });
  return base;
}

function saveState() {
  state.protocol.updatedAt = new Date().toISOString();
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  persistState();
}

async function api(path, options = {}) {
  const token = localStorage.getItem(TOKEN_KEY);
  const headers = { ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const response = await fetch(`${API_ROOT}${path}`, {
    ...options,
    headers,
    body: options.body instanceof FormData ? options.body : options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Falha na comunicacao com o servidor.");
  return data;
}

async function persistState() {
  if (!backendAvailable || !session) return;
  try {
    await api("/state", { method: "POST", body: { state } });
  } catch (error) {
    console.warn(error);
  }
}

async function bootstrap() {
  try {
    const sessionResponse = await api("/session");
    backendAvailable = true;
    session = sessionResponse.user;
    if (session) {
      const data = await api("/state");
      state = deepMerge(structuredClone(initialState), data.state);
      state.role = session.role;
      notifications = data.notifications || [];
      await loadRegistry();
    }
  } catch {
    backendAvailable = false;
    session = null;
  }
  render();
}

async function loadRegistry() {
  if (!backendAvailable || !session || session.role !== "sim") return;
  try {
    const data = await api("/registry");
    registry = data.registry;
  } catch (error) {
    console.warn(error);
  }
}

function establishmentName(id) {
  const est = registry.establishments.find((item) => String(item.id) === String(id));
  return est ? est.trade_name || est.legal_name : "-";
}

function collectFields(scope) {
  const values = {};
  document.querySelectorAll(`[data-reg="${scope}"]`).forEach((el) => {
    values[el.dataset.field] = el.value;
  });
  return values;
}

function regField(scope, field, label, value, opts = {}) {
  const cls = opts.full ? "field full" : "field";
  if (opts.options) {
    return `<div class="${cls}"><label>${label}</label><select data-reg="${scope}" data-field="${field}">
      ${opts.options.map((option) => `<option ${String(value ?? "") === String(option) ? "selected" : ""}>${option}</option>`).join("")}
    </select></div>`;
  }
  if (opts.textarea) {
    return `<div class="${cls}"><label>${label}</label><textarea data-reg="${scope}" data-field="${field}">${escapeHtml(value ?? "")}</textarea></div>`;
  }
  return `<div class="${cls}"><label>${label}</label><input type="${opts.type || "text"}" data-reg="${scope}" data-field="${field}" value="${escapeHtml(value ?? "")}"></div>`;
}

function establishmentSelect(scope, value, label = "Estabelecimento") {
  return `<div class="field"><label>${label}</label><select data-reg="${scope}" data-field="establishment_id">
    <option value="">Selecione...</option>
    ${registry.establishments.map((est) => `<option value="${est.id}" ${String(value ?? "") === String(est.id) ? "selected" : ""}>${escapeHtml(est.trade_name || est.legal_name)} (${est.sim_number || "sem SIM"})</option>`).join("")}
  </select></div>`;
}

function icon(name) {
  const icons = {
    home: "M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V11z",
    file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h8 M8 9h2",
    clip: "M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 1 1 5.66 5.66l-9.2 9.19a2 2 0 1 1-2.83-2.83l8.49-8.48",
    check: "M20 6L9 17l-5-5",
    print: "M6 9V2h12v7 M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2 M6 14h12v8H6z",
    send: "M22 2L11 13 M22 2l-7 20-4-9-9-4 20-7z",
    shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  };
  return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${icons[name] || icons.file}"/></svg>`;
}

function statusClass(status) {
  if (/aprov/i.test(status)) return "approved";
  if (/corre/i.test(status)) return "corrections";
  if (/anal/i.test(status)) return "review";
  return "pending";
}

function statusLabel() {
  const labels = {
    pending: "Rascunho",
    review: "Em analise",
    corrections: "Correcoes solicitadas",
    approved: "Aprovado",
  };
  return labels[state.protocol.status] || state.protocol.status;
}

function formatDate(value) {
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function setRole(role) {
  if (backendAvailable && session) {
    toast("Perfil definido pela conta autenticada.");
    return;
  }
  state.role = role;
  if (role === "establishment" && ["review", "fiscal"].includes(state.view)) state.view = "dashboard";
  saveState();
  render();
}

function setView(view) {
  state.view = view;
  saveState();
  render();
}

function update(path, value) {
  const parts = path.split(".");
  let target = state;
  for (let i = 0; i < parts.length - 1; i += 1) target = target[parts[i]];
  target[parts.at(-1)] = value;
  saveState();
}

function toast(message) {
  const el = document.querySelector(".toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

function record(action, who = state.role === "sim" ? "Lucas Marcelino Campos Ferreira" : state.establishment.tradeName) {
  state.audit.unshift({
    at: new Date().toISOString(),
    who,
    action,
    version: state.protocol.version,
  });
}

function submitProtocol() {
  state.protocol.status = "review";
  state.protocol.version += 1;
  state.protocol.submittedAt = new Date().toISOString();
  record("Protocolo enviado para analise do SIM.");
  notifications.unshift({
    title: "Protocolo enviado ao SIM",
    message: `${state.establishment.tradeName} enviou a versao ${state.protocol.version} para analise.`,
    created_at: new Date().toISOString(),
  });
  saveState();
  render();
  toast("Protocolo enviado para analise.");
}

function reviewDecision(decision) {
  const map = {
    approve: ["approved", "Processo aprovado pelo SIM.", "Aprovado"],
    reject: ["pending", "Processo reprovado pelo SIM.", "Reprovado"],
    corrections: ["corrections", "Correcoes solicitadas pelo SIM.", "Correcoes solicitadas"],
  };
  const [status, action, label] = map[decision];
  state.protocol.status = status;
  state.review.decision = label;
  state.protocol.version += 1;
  record(action, "Lucas Marcelino Campos Ferreira");
  notifications.unshift({
    title: label,
    message: state.review.note || action,
    created_at: new Date().toISOString(),
  });
  saveState();
  render();
  toast(label);
}

function input(path, label, opts = {}) {
  const value = path.split(".").reduce((acc, key) => acc?.[key], state) ?? "";
  const type = opts.type || "text";
  const cls = opts.full ? "field full" : "field";
  const locked =
    (opts.owner === "establishment" && state.role !== "establishment") ||
    (opts.owner === "sim" && state.role !== "sim");
  const hint = opts.owner === "sim" ? "Exclusivo SIM" : opts.owner === "establishment" ? "Estabelecimento" : "";
  const disabled = locked ? "disabled" : "";
  if (opts.textarea) {
    return `<div class="${cls}"><label>${label}${hint ? `<span>${hint}</span>` : ""}</label><textarea data-path="${path}" ${disabled}>${value}</textarea></div>`;
  }
  return `<div class="${cls}"><label>${label}${hint ? `<span>${hint}</span>` : ""}</label><input type="${type}" data-path="${path}" value="${escapeHtml(value)}" ${disabled}></div>`;
}

function selectInput(path, label, options, opts = {}) {
  const value = path.split(".").reduce((acc, key) => acc?.[key], state) ?? "";
  const locked =
    (opts.owner === "establishment" && state.role !== "establishment") ||
    (opts.owner === "sim" && state.role !== "sim");
  const hint = opts.owner === "sim" ? "Exclusivo SIM" : opts.owner === "establishment" ? "Estabelecimento" : "";
  return `
    <div class="${opts.full ? "field full" : "field"}">
      <label>${label}${hint ? `<span>${hint}</span>` : ""}</label>
      <select data-path="${path}" ${locked ? "disabled" : ""}>
        ${options.map((option) => `<option ${value === option ? "selected" : ""}>${option}</option>`).join("")}
      </select>
    </div>
  `;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function renderShell(content) {
  const establishmentNav = [
    ["dashboard", "home", "Painel"],
    ["establishment", "file", "Ficha mestre"],
    ["documents", "clip", "Documentos"],
    ["products", "file", "Produtos"],
    ["print", "print", "Imprimir PDFs"],
  ];
  const simNav = [
    ["dashboard", "home", "Painel"],
    ["registry", "file", "Estabelecimentos"],
    ["inspections", "shield", "Inspecoes"],
    ["fiscal", "file", "Atos fiscais"],
    ["samples", "clip", "Amostras"],
    ["review", "shield", "Analise SIM"],
    ["documents", "clip", "Documentos"],
    ["print", "print", "Imprimir PDFs"],
    ["legislation", "file", "Base legal"],
  ];
  const nav = state.role === "sim" ? simNav : establishmentNav;

  return `
    <div class="app">
      <aside class="sidebar">
        <div class="brand">
          <img src="./assets/brasao-orlandia.png" alt="Brasao do Municipio de Orlandia">
          <div><strong>Portal SIM</strong><span>Prefeitura de Orlandia/SP</span></div>
        </div>
        ${accountPanel()}
        <nav class="nav">
          ${nav.map(([id, iconName, label]) => `<button class="${state.view === id ? "active" : ""}" data-view="${id}">${icon(iconName)}${label}</button>`).join("")}
        </nav>
        <div class="side-panel">
          <label>Processo ativo</label>
          <strong>${state.protocol.id}</strong><br>
          <span>${state.establishment.tradeName} - versao ${state.protocol.version}</span>
        </div>
      </aside>
      <main class="main">
        <header class="topbar">
          <div>
            <h1>${pageTitle()}</h1>
            <p>${pageSubtitle()}</p>
          </div>
          <div class="actions">${topActions()}</div>
        </header>
        <section class="content">${content}</section>
      </main>
      <div class="toast" role="status"></div>
      ${activeUpload ? renderUploadModal(activeUpload) : ""}
    </div>
  `;
}

function renderLogin() {
  return `
    <div class="login-screen">
      <section class="login-panel">
        <div class="login-brand">
          <img src="./assets/brasao-orlandia.png" alt="Brasao do Municipio de Orlandia">
          <div>
            <h1>Portal SIM Orlandia</h1>
            <p>Servico de Inspecao Municipal - acesso rastreavel</p>
          </div>
        </div>
        <form class="login-form" data-login-form>
          <div class="field">
            <label>E-mail</label>
            <input name="email" type="email" autocomplete="username" placeholder="seu-email@exemplo.com.br" required>
          </div>
          <div class="field">
            <label>Senha</label>
            <input name="password" type="password" autocomplete="current-password" required>
          </div>
          <button class="btn primary" type="submit">Entrar</button>
        </form>
        <p class="small muted">Acesso fornecido pelo Servico de Inspecao Municipal de Orlandia. Para obter sua conta de estabelecimento, procure o SIM na Divisao de Agronegocios ou envie e-mail para o servico.</p>
      </section>
    </div>
  `;
}

function accountPanel() {
  if (backendAvailable && session) {
    return `
      <div class="mode-switch">
        <label>Conta autenticada</label>
        <div class="account-box">
          <strong>${session.name}</strong>
          <span>${session.email}</span>
          <span>${session.role === "sim" ? "Servidor SIM" : "Estabelecimento"}</span>
        </div>
        <button class="btn ghost" data-action="logout">Sair</button>
      </div>
    `;
  }
  return `
    <div class="mode-switch">
      <label>Entrar como</label>
      <div class="segmented">
        <button class="${state.role === "establishment" ? "active" : ""}" data-role="establishment">Estabelecimento</button>
        <button class="${state.role === "sim" ? "active" : ""}" data-role="sim">SIM</button>
      </div>
    </div>
  `;
}

function pageTitle() {
  const titles = {
    dashboard: "Acompanhamento do processo",
    establishment: "Ficha mestre do estabelecimento",
    documents: "Documentos e anexos",
    products: "Produtos e rotulos",
    print: "Formularios para impressao",
    review: "Analise do SIM",
    fiscal: "Atos fiscais",
    registry: "Cadastro de estabelecimentos",
    inspections: "Inspecoes e fiscalizacoes",
    samples: "Coleta de amostras",
    legislation: "Base legal do SIM",
  };
  return titles[state.view] || "Portal SIM";
}

function pageSubtitle() {
  if (state.role === "sim") return "Area interna do SIM com analise, decisao e atos fiscais.";
  return "Preencha uma vez. O portal reutiliza os dados nos formularios oficiais.";
}

function topActions() {
  if (state.role === "establishment") {
    return `
      <button class="btn" data-action="save">${icon("check")}Salvar</button>
      <button class="btn primary" data-action="submit">${icon("send")}Enviar ao SIM</button>
    `;
  }
  if (["registry", "inspections", "samples", "fiscal", "legislation"].includes(state.view)) {
    return "";
  }
  if (state.view !== "review") {
    return `<button class="btn" data-action="save">${icon("check")}Salvar analise</button>`;
  }
  return `
    <button class="btn warn" data-action="corrections">Solicitar correcoes</button>
    <button class="btn danger" data-action="reject">Reprovar</button>
    <button class="btn primary" data-action="approve">${icon("check")}Aprovar</button>
  `;
}

const GOVBR_SIGNER_URL = "https://assinador.iti.br";

function docReceived(doc) {
  return (doc.versions || []).length > 0 || doc.status === "Recebido";
}

function art11Docs() {
  return state.documents.filter((doc) => doc.group === "art11");
}

function art11Progress() {
  const required = art11Docs().filter((doc) => doc.required);
  const sent = required.filter(docReceived).length;
  return { sent, total: required.length };
}

function journeySteps() {
  const est = state.establishment;
  const fichaDone = Boolean(est.email && est.phone && state.legalResponsible.cpf && state.technicalResponsible.name);
  const mtseDone = Boolean(state.production.activities && state.production.monthlyCapacity && state.production.waterSupply);
  const productsDone = state.products.some((product) => (product.name || "").trim());
  const docs = art11Progress();
  const docsDone = docs.total > 0 && docs.sent === docs.total;
  const signDone = Boolean(state.journey?.signedAck);
  const submitted = ["review", "approved"].includes(state.protocol.status);
  const approved = state.protocol.status === "approved";
  return [
    { id: "ficha", title: "Preencher a ficha do estabelecimento", desc: "Dados da empresa, responsavel legal e responsavel tecnico. Preencha uma vez; o portal reaproveita em todos os formularios.", done: fichaDone, view: "establishment", cta: "Abrir ficha" },
    { id: "mtse", title: "Descrever a producao (Memorial/MTSE)", desc: "Atividades, capacidade, agua, higiene e fluxo. Atende o item 09 do checklist.", done: mtseDone, view: "establishment", cta: "Preencher memorial" },
    { id: "produtos", title: "Cadastrar os produtos", desc: "Um Anexo IV por produto: nome, composicao, rotulo e conservacao.", done: productsDone, view: "products", cta: "Cadastrar produtos" },
    { id: "assinar", title: "Imprimir e assinar no gov.br", desc: "Imprima os formularios em PDF e assine de graca com sua conta gov.br, sem cartorio.", done: signDone, view: "print", cta: "Ver formularios" },
    { id: "documentos", title: `Enviar os documentos (${docs.sent} de ${docs.total})`, desc: "Checklist oficial do art. 11 da LC 84/2024. Cada item diz onde conseguir o documento.", done: docsDone, view: "documents", cta: "Enviar documentos" },
    { id: "protocolar", title: "Enviar tudo ao SIM", desc: "Protocola o pedido; o SIM analisa e responde por aqui, com notificacao.", done: submitted, view: "dashboard", cta: "Enviar ao SIM", action: "submit" },
    { id: "analise", title: "Acompanhar a analise", desc: "O SIM confere, agenda a vistoria e emite o registro. Voce acompanha tudo nesta tela.", done: approved, view: "dashboard", cta: "Ver andamento" },
  ];
}

function renderJourney() {
  const steps = journeySteps();
  const doneCount = steps.filter((step) => step.done).length;
  const percent = Math.round((doneCount / steps.length) * 100);
  const current = steps.find((step) => !step.done);
  return `
    <div class="span-12 panel journey">
      <div class="panel-header">
        <div>
          <h2>Seu registro no SIM, passo a passo</h2>
          <p class="muted">Complete os passos no seu ritmo. Nada se perde: tudo fica salvo automaticamente.</p>
        </div>
        <span class="journey-score">${percent}%</span>
      </div>
      <div class="progress-track"><div class="progress-fill" style="width:${percent}%"></div></div>
      ${current ? `
        <div class="next-action">
          <div>
            <strong>Proximo passo: ${current.title}</strong>
            <span>${current.desc}</span>
          </div>
          ${current.action === "submit"
            ? `<button class="btn primary" data-action="submit">${icon("send")}${current.cta}</button>`
            : `<button class="btn primary" data-view="${current.view}">${current.cta}</button>`}
        </div>
      ` : `
        <div class="next-action done">
          <div><strong>Tudo certo por aqui!</strong><span>Seu processo foi aprovado pelo SIM.</span></div>
        </div>
      `}
      <div class="journey-steps">
        ${steps.map((step, index) => `
          <button class="journey-step ${step.done ? "done" : ""} ${current && step.id === current.id ? "current" : ""}" data-view="${step.view}">
            <span class="step-badge">${step.done ? "&#10003;" : index + 1}</span>
            <span class="step-text"><strong>${step.title}</strong><span>${step.desc}</span></span>
          </button>
        `).join("")}
      </div>
      <p class="small muted" style="margin-top:12px">Sem taxa em 2026: a Taxa de Inspecao Sanitaria esta dispensada neste ano (LC 104/2026). Registrar agora e gratuito.</p>
    </div>
  `;
}

function simServicePanel() {
  if (state.role !== "sim") return "";
  const latest = latestInspectionByEstablishment();
  const overdue = registry.establishments.filter((est) => {
    const last = latest.get(est.id);
    return !/cancelado|paralisado/i.test(est.situation || "") && (!last || isOverdue(last.next_due));
  });
  const openActs = registry.fiscalActs.filter((act) => !/transitado|arquivado/i.test(act.status || ""));
  const badSamples = registry.samples.filter((item) => /nao conforme/i.test(item.status || ""));
  return `
    <div class="span-12 panel">
      <div class="panel-header"><h2>Pendencias do servico</h2><span class="status review">Visao SIM</span></div>
      <div class="metrics">
        <div class="metric"><strong>${registry.establishments.length}</strong><span>Estabelecimentos cadastrados</span></div>
        <div class="metric"><strong>${overdue.length}</strong><span>Inspecao vencida ou nunca realizada</span></div>
        <div class="metric"><strong>${openActs.length}</strong><span>Atos fiscais em andamento</span></div>
        <div class="metric"><strong>${badSamples.length}</strong><span>Amostras nao conformes</span></div>
      </div>
      ${overdue.length ? `<p class="small muted" style="margin-top:10px">Prioridade por risco: ${overdue.map((est) => `${est.trade_name || est.legal_name} (${est.risk_level || "sem risco definido"})`).join("; ")}.</p>` : ""}
    </div>
  `;
}

function renderDashboard() {
  const missingRequired = state.documents.filter((doc) => doc.required && doc.status !== "Recebido").length;
  return `
    <div class="grid">
      ${simServicePanel()}
      ${state.role === "establishment" ? renderJourney() : ""}
      <div class="span-12 metrics">
        <div class="metric"><strong>${statusLabel()}</strong><span>Status atual</span></div>
        <div class="metric"><strong>${state.protocol.version}</strong><span>Versao protocolada</span></div>
        <div class="metric"><strong>${missingRequired}</strong><span>Pendencias obrigatorias</span></div>
        <div class="metric"><strong>${state.products.length}</strong><span>Produtos declarados</span></div>
      </div>
      <div class="span-7 panel">
        <div class="panel-header">
          <div>
            <h2>${state.establishment.tradeName}</h2>
            <p class="muted">${state.establishment.legalName}</p>
          </div>
          <span class="status ${statusClass(state.protocol.status)}">${statusLabel()}</span>
        </div>
        <table class="table">
          <tr><th>CNPJ</th><td>${state.establishment.cnpj}</td></tr>
          <tr><th>Atividade</th><td>${state.establishment.cnae}</td></tr>
          <tr><th>Endereco</th><td>${state.establishment.address}, ${state.establishment.district}, ${state.establishment.city}/${state.establishment.state}</td></tr>
          <tr><th>Responsavel legal</th><td>${state.legalResponsible.name || "Nao informado"}</td></tr>
          <tr><th>Responsavel tecnico</th><td>${state.technicalResponsible.name || "Pendente"}</td></tr>
        </table>
      </div>
      <div class="span-5 panel">
        <div class="panel-header"><h2>Ultima manifestacao</h2></div>
        <p><strong>${state.review.decision}</strong></p>
        <p class="muted">${state.review.note}</p>
        <p class="small muted">Atualizado em ${formatDate(state.protocol.updatedAt)}</p>
      </div>
      <div class="span-6 panel">
        <div class="panel-header"><h2>Proximas acoes</h2></div>
        <div class="checklist">
          ${nextActions().map((item) => `<label class="check-item"><input type="checkbox"><span>${item}</span><span class="muted small">SIM</span></label>`).join("")}
        </div>
      </div>
      <div class="span-6 panel">
        <div class="panel-header"><h2>Trilha de auditoria</h2></div>
        <div class="timeline">
          ${state.audit.slice(0, 6).map((event) => `
            <div class="event"><div><strong>${event.action}</strong><span>${event.who} - ${formatDate(event.at)} - v${event.version}</span></div></div>
          `).join("")}
        </div>
      </div>
      <div class="span-6 panel">
        <div class="panel-header"><h2>Notificacoes</h2></div>
        <div class="timeline">
          ${(notifications.length ? notifications : [{ title: "Sem notificacoes novas", message: "Eventos do processo apareceriam aqui para ciencia e acompanhamento.", created_at: state.protocol.updatedAt }]).slice(0, 5).map(notificationItem).join("")}
        </div>
      </div>
    </div>
  `;
}

function notificationItem(item) {
  const upload = item.upload_id ? findUpload(item.upload_id) : null;
  const action = upload
    ? `<button class="link-button" data-open-upload="${upload.id}">Abrir versao enviada</button>`
    : "";
  return `
    <div class="event">
      <div>
        <strong>${item.title}</strong>
        <span>${item.message} - ${formatDate(item.created_at)}</span>
        ${action}
      </div>
    </div>
  `;
}

function nextActions() {
  if (state.protocol.status === "approved") return ["Emitir registro/ato correspondente.", "Arquivar versao aprovada no processo."];
  if (state.protocol.status === "review") return ["Aguardar analise do SIM.", "Manter documentos originais disponiveis."];
  return ["Completar responsavel tecnico e ART.", "Informar origem da materia-prima.", "Declarar produtos e anexar rotulos.", "Imprimir formulario consolidado para conferencia."];
}

function renderEstablishment() {
  return `
    <div class="grid">
      <div class="span-8 panel">
        <div class="panel-header"><div><h2>Anexo I - Informacoes do estabelecimento</h2><p class="muted">Base do requerimento, MTSE, produto/rotulo e atos fiscais.</p></div><span class="status ${statusClass(state.protocol.status)}">${statusLabel()}</span></div>
        <div class="form-grid">
          ${input("establishment.legalName", "Razao social / nome", { owner: "establishment" })}
          ${input("establishment.tradeName", "Nome fantasia", { owner: "establishment" })}
          ${input("establishment.cnpj", "CNPJ / CPF", { owner: "establishment" })}
          ${input("establishment.stateRegistration", "Inscricao estadual", { owner: "establishment" })}
          ${input("establishment.municipalRegistration", "Inscricao municipal", { owner: "establishment" })}
          ${input("establishment.cnae", "CNAE", { owner: "establishment" })}
          ${input("establishment.address", "Endereco", { owner: "establishment" })}
          ${input("establishment.district", "Bairro", { owner: "establishment" })}
          ${input("establishment.city", "Municipio", { owner: "establishment" })}
          ${input("establishment.state", "UF", { owner: "establishment" })}
          ${input("establishment.zip", "CEP", { owner: "establishment" })}
          ${input("establishment.email", "E-mail", { owner: "establishment" })}
          ${input("establishment.phone", "Telefone", { owner: "establishment" })}
          ${input("establishment.area", "Area do estabelecimento", { owner: "establishment" })}
          ${input("establishment.legalNature", "Natureza juridica", { owner: "establishment" })}
          ${input("establishment.classification", "Classificacao do estabelecimento", { full: true, owner: "establishment" })}
        </div>
      </div>
      <div class="span-4 panel">
        <div class="panel-header"><h2>Responsabilidade</h2></div>
        <p class="muted">Campos marcados como Estabelecimento sao preenchidos pelo requerente. Campos exclusivos do SIM ficam bloqueados para o estabelecimento e servem para analise ou emissao de ato fiscal.</p>
        <button class="btn primary" data-view="print">${icon("print")}Ver formularios preenchidos</button>
      </div>
      <div class="span-6 panel">
        <div class="panel-header"><h2>Anexo I/II - Responsavel legal</h2></div>
        <div class="form-grid">
          ${input("legalResponsible.name", "Nome", { owner: "establishment" })}
          ${input("legalResponsible.cpf", "CPF", { owner: "establishment" })}
          ${input("legalResponsible.email", "E-mail", { owner: "establishment" })}
          ${input("legalResponsible.phone", "Telefone", { owner: "establishment" })}
        </div>
      </div>
      <div class="span-6 panel">
        <div class="panel-header"><h2>Anexo II/IV - Responsavel tecnico</h2></div>
        <div class="form-grid">
          ${input("technicalResponsible.name", "Nome", { owner: "establishment" })}
          ${input("technicalResponsible.cpf", "CPF", { owner: "establishment" })}
          ${input("technicalResponsible.council", "Conselho / UF", { owner: "establishment" })}
          ${input("technicalResponsible.email", "E-mail", { owner: "establishment" })}
          ${input("technicalResponsible.phone", "Telefone", { owner: "establishment" })}
        </div>
      </div>
      <div class="span-12 panel">
        <div class="panel-header"><h2>Anexo I - Tipo de solicitacao e compromisso</h2></div>
        <div class="form-grid">
          ${selectInput("application.actType", "Tipo de solicitacao", [
            "Registro de estabelecimento",
            "Aprovacao de reforma ou ampliacao",
            "Transferencia cadastral",
            "Solicitacao de vistoria in loco",
            "Paralisacao das atividades",
            "Reinicio das atividades",
            "Cancelamento de registro de estabelecimento",
            "Cancelamento de registro de produto",
            "Alteracao cadastral",
            "Outro ato"
          ], { owner: "establishment" })}
          ${input("application.otherAct", "Outro ato / complemento", { owner: "establishment" })}
          ${input("application.commitment", "Termo de compromisso", { textarea: true, full: true, owner: "establishment" })}
        </div>
      </div>
      <div class="span-12 panel">
        <div class="panel-header"><h2>Anexo II - Memorial tecnico-sanitario do estabelecimento</h2></div>
        <div class="form-grid">
          ${input("production.activities", "Lista de atividades gerais", { textarea: true, owner: "establishment" })}
          ${input("production.monthlyCapacity", "Produtos e capacidade mensal", { textarea: true, owner: "establishment" })}
          ${input("production.rawMaterialOrigin", "Origem da materia-prima e rastreamento", { textarea: true, owner: "establishment" })}
          ${input("production.employees", "Funcionarios", { textarea: true, owner: "establishment" })}
          ${input("production.laundry", "Lavanderia", { textarea: true, owner: "establishment" })}
          ${input("production.landDetails", "Detalhes do terreno", { textarea: true, owner: "establishment" })}
          ${input("production.locationArea", "Area de localizacao", { textarea: true, owner: "establishment" })}
          ${input("production.flow", "Disposicao das instalacoes e fluxo de producao", { textarea: true, owner: "establishment" })}
          ${input("production.equipment", "Equipamentos", { textarea: true, owner: "establishment" })}
          ${input("production.floorWalls", "Piso e material de impermeabilizacao", { textarea: true, owner: "establishment" })}
          ${input("production.doorsWindowsCeiling", "Janelas, portas, teto e bloqueio sanitario", { textarea: true, owner: "establishment" })}
          ${input("production.bathrooms", "Banheiros, vestiarios e instalacoes para funcionarios", { textarea: true, owner: "establishment" })}
          ${input("production.lightingVentilation", "Iluminacao e ventilacao", { textarea: true, owner: "establishment" })}
          ${input("production.storage", "Depositos de embalagens, materias-primas, condimentos e utensilios", { textarea: true, owner: "establishment" })}
          ${input("production.waterSupply", "Sistema de abastecimento de agua", { textarea: true, owner: "establishment" })}
          ${input("production.effluents", "Destino das aguas servidas", { textarea: true, owner: "establishment" })}
          ${input("production.transport", "Transporte de produtos expedidos", { textarea: true, owner: "establishment" })}
          ${input("production.labAnalysis", "Analises laboratoriais", { textarea: true, owner: "establishment" })}
          ${input("production.productionSchedule", "Dias e horarios de producao", { textarea: true, owner: "establishment" })}
          ${input("production.qualityControls", "Controles de qualidade e autocontroles", { textarea: true, full: true, owner: "establishment" })}
        </div>
      </div>
      <div class="span-12 panel">
        <div class="panel-header"><h2>Anexo III - Memorial descritivo de construcao/reforma</h2></div>
        <div class="form-grid">
          ${input("construction.requestReason", "Motivo da obra/reforma/ampliacao", { owner: "establishment" })}
          ${input("construction.rooms", "Ambientes e dependencias", { textarea: true, owner: "establishment" })}
          ${input("construction.buildingDescription", "Descricao da construcao", { textarea: true, owner: "establishment" })}
          ${input("construction.materials", "Materiais construtivos e acabamentos", { textarea: true, owner: "establishment" })}
          ${input("construction.coldRooms", "Camara fria / controle de temperatura", { textarea: true, owner: "establishment" })}
          ${input("construction.waterAndSewage", "Agua, esgoto e drenagem", { textarea: true, owner: "establishment" })}
          ${input("construction.observations", "Observacoes", { textarea: true, full: true, owner: "establishment" })}
        </div>
      </div>
    </div>
  `;
}

function renderDocuments() {
  const art11 = state.documents.filter((doc) => doc.group === "art11");
  const anexos = state.documents.filter((doc) => !doc.internal && doc.group !== "art11");
  const internalDocs = state.documents.filter((doc) => doc.internal);
  const progress = art11Progress();
  const percent = progress.total ? Math.round((progress.sent / progress.total) * 100) : 0;
  return `
    <div class="grid">
      <div class="span-12 banner-warn">
        <strong>Taxa do SIM em 2026: nao e preciso pagar nada.</strong>
        A Taxa de Inspecao Sanitaria esta dispensada neste ano (LC 104/2026, art. 3, par. unico). O item 12 do checklist fica sem exigencia em 2026.
      </div>
      <div class="span-8 panel">
        <div class="panel-header">
          <div><h2>Checklist do registro - art. 11 da LC 84/2024</h2>
          <p class="muted">${state.role === "sim" ? "O SIM confere documentos e define o status." : "Envie cada documento em PDF. Cada item explica o que e e onde conseguir."}</p></div>
          <span class="journey-score">${progress.sent}/${progress.total}</span>
        </div>
        <div class="progress-track"><div class="progress-fill" style="width:${percent}%"></div></div>
        <div class="document-group">
          ${art11.map(documentCard).join("")}
        </div>
        <div class="document-group">
          <h3>Anexos complementares</h3>
          ${anexos.map(documentCard).join("")}
        </div>
        ${state.role === "sim" ? `
          <div class="document-group">
            <h3>Anexos internos do SIM</h3>
            <p class="muted small">Nao aparecem para o estabelecimento. Servem para parecer, checklist, despachos e instrucao interna.</p>
            ${internalDocs.map(documentCard).join("")}
          </div>
        ` : ""}
      </div>
      <div class="span-4 panel">
        <div class="panel-header"><h2>Assine de graca no gov.br</h2></div>
        <ol class="signer-steps">
          <li>Imprima os formularios do portal em PDF (botao Imprimir - salvar como PDF).</li>
          <li>Acesse o assinador oficial e entre com sua conta gov.br (nivel prata ou ouro).</li>
          <li>Envie o PDF, posicione a assinatura e baixe o arquivo assinado.</li>
          <li>Volte aqui e envie o PDF assinado no item correspondente.</li>
        </ol>
        <a class="btn primary" href="${GOVBR_SIGNER_URL}" target="_blank" rel="noreferrer">Abrir assinador gov.br</a>
        ${state.role === "establishment" ? `
          <label class="check-item" style="margin-top:12px">
            <input type="checkbox" data-journey-signed ${state.journey?.signedAck ? "checked" : ""}>
            <span>Ja assinei meus documentos no gov.br</span>
          </label>
        ` : ""}
        <div class="panel-header" style="margin-top:18px"><h2>Rastreabilidade</h2></div>
        <p class="muted small">Cada envio registra conta, horario, tamanho e hash SHA-256. Reenviar cria nova versao; nada e apagado.</p>
        <div class="panel-header" style="margin-top:18px"><h2>Historico de modificacoes</h2></div>
        <div class="timeline compact">
          ${(state.stateHistory || []).slice(0, 8).map((item) => `
            <div class="event"><div><strong>${item.reason}</strong><span>${item.changed_by_name} - ${formatDate(item.changed_at)}</span></div></div>
          `).join("") || `<p class="muted small">As alteracoes de ficha apareceriam aqui.</p>`}
        </div>
      </div>
    </div>
  `;
}

function documentCard(doc) {
  const versions = doc.versions || [];
  const canUpload = backendAvailable && (state.role === "sim" || !doc.internal);
  const isTaxWaived = doc.id === "comprovante-taxa";
  const received = docReceived(doc);
  return `
    <section class="document-card ${doc.internal ? "internal" : ""} ${received ? "received" : ""}">
      <div class="document-main">
        <div>
          <strong>${doc.item ? `<span class="doc-number ${received ? "ok" : ""}">${received ? "&#10003;" : doc.item}</span>` : ""}${doc.name}${doc.required ? " *" : ""}
          ${isTaxWaived ? `<span class="status approved" style="margin-left:8px">Sem taxa em 2026</span>` : ""}</strong>
          ${doc.hint ? `<span class="doc-hint">${doc.hint}${doc.link ? ` <a href="${doc.link}" target="_blank" rel="noreferrer">Abrir site</a>` : ""}</span>` : ""}
          <span>${documentSummary(doc)}</span>
        </div>
        <div class="upload-controls">
          ${canUpload && !isTaxWaived ? `<input type="file" data-upload-doc="${doc.id}" aria-label="Enviar ${doc.name}">` : ""}
          ${doc.uploadId ? `<button class="btn" data-open-upload="${doc.uploadId}">Abrir atual</button>` : ""}
          ${doc.uploadId ? `<a class="btn" href="${downloadUrl(doc.uploadId)}" target="_blank" rel="noreferrer">Baixar</a>` : ""}
          ${isTaxWaived && state.role !== "sim" ? "" : `<select data-doc="${doc.id}" ${state.role === "sim" ? "" : "disabled"}>
            ${["Pendente", "Em correcao", "Recebido", "Interno", "Dispensado em 2026"].map((status) => `<option ${doc.status === status ? "selected" : ""}>${status}</option>`).join("")}
          </select>`}
        </div>
      </div>
      <div class="version-list">
        ${versions.length ? versions.map((version) => `
          <div class="version-row">
            <div>
              <strong>v${version.versionNo} - ${version.file}</strong>
              <span>${version.uploadedBy} - ${formatDate(version.uploadedAt)} - ${formatBytes(version.sizeBytes)} - SHA-256 ${version.sha256.slice(0, 16)}...</span>
            </div>
            <div class="upload-controls">
              <button class="btn" data-open-upload="${version.id}">Abrir</button>
              <a class="btn" href="${downloadUrl(version.id)}" target="_blank" rel="noreferrer">Baixar</a>
            </div>
          </div>
        `).join("") : `<div class="empty small">Nenhuma versao enviada.</div>`}
      </div>
    </section>
  `;
}

function documentSummary(doc) {
  if (!doc.file) return "Nenhum arquivo enviado";
  const pieces = [`v${doc.versionNo || 1} - ${doc.file}`];
  if (doc.uploadedBy) pieces.push(`enviado por ${doc.uploadedBy}`);
  if (doc.uploadedAt) pieces.push(formatDate(doc.uploadedAt));
  if (doc.sha256) pieces.push(`SHA-256 ${doc.sha256.slice(0, 16)}...`);
  return pieces.join(" - ");
}

function formatBytes(value) {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function findUpload(uploadId) {
  for (const doc of state.documents || []) {
    for (const version of doc.versions || []) {
      if (version.id === uploadId) return { ...version, documentName: doc.name, internal: doc.internal };
    }
  }
  return null;
}

function downloadUrl(uploadId) {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? `${API_ROOT}/uploads/${uploadId}?token=${encodeURIComponent(token)}` : `${API_ROOT}/uploads/${uploadId}`;
}

function renderUploadModal(upload) {
  return `
    <div class="modal-backdrop" role="dialog" aria-modal="true">
      <section class="modal">
        <div class="modal-header">
          <div>
            <h2>${upload.documentName || "Anexo do processo"} - v${upload.versionNo}</h2>
            <p>${upload.file}</p>
          </div>
          <button class="btn" data-action="close-modal">Fechar</button>
        </div>
        <div class="modal-meta">
          <div><strong>Enviado por</strong><span>${upload.uploadedBy}</span></div>
          <div><strong>Horario</strong><span>${formatDate(upload.uploadedAt)}</span></div>
          <div><strong>Tamanho</strong><span>${formatBytes(upload.sizeBytes)}</span></div>
          <div><strong>Visibilidade</strong><span>${upload.visibility === "sim" || upload.internal ? "Interno SIM" : "Estabelecimento e SIM"}</span></div>
          <div class="full"><strong>SHA-256</strong><span>${upload.sha256}</span></div>
        </div>
        <div class="modal-actions">
          <a class="btn primary" href="${downloadUrl(upload.id)}" target="_blank" rel="noreferrer">Baixar arquivo original</a>
        </div>
        <iframe class="upload-preview" src="${downloadUrl(upload.id)}" title="Previa do anexo ${upload.file}"></iframe>
      </section>
    </div>
  `;
}

function renderProducts() {
  return `
    <div class="grid">
      <div class="span-12 panel">
        <div class="panel-header">
          <div><h2>Produtos e rotulos</h2><p class="muted">Cada produto puxa automaticamente os dados da ficha mestre para o Anexo IV.</p></div>
          <button class="btn primary" data-action="add-product">Adicionar produto</button>
        </div>
        <div class="product-list">
          ${state.products.map((product, index) => productEditor(product, index)).join("")}
        </div>
      </div>
    </div>
  `;
}

function productField(product, field, label, opts = {}) {
  const value = product[field] ?? "";
  const locked = state.role !== "establishment";
  const control = opts.textarea
    ? `<textarea data-product="${product.id}" data-field="${field}" ${locked ? "disabled" : ""}>${value}</textarea>`
    : `<input data-product="${product.id}" data-field="${field}" value="${escapeHtml(value)}" ${locked ? "disabled" : ""}>`;
  return `<div class="${opts.full ? "field full" : "field"}"><label>${label}<span>Estabelecimento</span></label>${control}</div>`;
}

function productEditor(product, index) {
  return `
    <section class="subform">
      <div class="subform-title">
        <h3>Produto ${index + 1} - Anexo IV</h3>
        <span class="status ${statusClass(product.status)}">${product.status}</span>
      </div>
      <div class="form-grid">
        ${productField(product, "requestNature", "Natureza da solicitacao")}
        ${productField(product, "status", "Status do produto")}
        ${productField(product, "name", "Nome do produto")}
        ${productField(product, "brand", "Marca")}
        ${productField(product, "conservation", "Condicoes de conservacao")}
        ${productField(product, "packageType", "Tipo de embalagem")}
        ${productField(product, "labelFeatures", "Caracteristicas do rotulo e da embalagem", { textarea: true })}
        ${productField(product, "composition", "Composicao do produto", { textarea: true })}
        ${productField(product, "nutrition", "Informacao nutricional", { textarea: true })}
        ${productField(product, "manufacturingProcess", "Processo de fabricacao", { textarea: true })}
        ${productField(product, "packagingProcess", "Processo de embalagem", { textarea: true })}
        ${productField(product, "storageConditions", "Condicoes de armazenamento", { textarea: true })}
        ${productField(product, "notes", "Medidas de controle de qualidade", { textarea: true })}
        ${productField(product, "marketTransport", "Transporte e expedicao ao mercado consumidor", { textarea: true })}
      </div>
    </section>
  `;
}

function renderReview() {
  return `
    <div class="grid">
      <div class="span-7 panel">
        <div class="panel-header"><h2>Analise tecnica</h2><span class="status ${statusClass(state.protocol.status)}">${statusLabel()}</span></div>
        <table class="table">
          <tr><th>Protocolo</th><td>${state.protocol.id}</td></tr>
          <tr><th>Estabelecimento</th><td>${state.establishment.legalName}</td></tr>
          <tr><th>CNAE</th><td>${state.establishment.cnae}</td></tr>
          <tr><th>Ultimo envio</th><td>${formatDate(state.protocol.submittedAt)}</td></tr>
          <tr><th>Versao</th><td>${state.protocol.version}</td></tr>
        </table>
        <div class="field full" style="margin-top:14px">
          <label>Manifestacao do SIM</label>
          <textarea data-review-note>${state.review.note}</textarea>
        </div>
      </div>
      <div class="span-5 panel">
        <div class="panel-header"><h2>Acoes do fiscal</h2></div>
        <div class="checklist">
          <button class="btn warn" data-action="corrections">Solicitar correcoes</button>
          <button class="btn danger" data-action="reject">Reprovar</button>
          <button class="btn primary" data-action="approve">Aprovar</button>
        </div>
      </div>
      <div class="span-12 panel">
        <div class="panel-header"><h2>Auditoria do processo</h2></div>
        <table class="table">
          <thead><tr><th>Horario</th><th>Conta</th><th>Acao</th><th>Versao</th></tr></thead>
          <tbody>${state.audit.map((event) => `<tr><td>${formatDate(event.at)}</td><td>${event.who}</td><td>${event.action}</td><td>${event.version}</td></tr>`).join("")}</tbody>
        </table>
      </div>
    </div>
  `;
}

function formatDay(value) {
  if (!value) return "-";
  const [year, month, day] = String(value).slice(0, 10).split("-");
  return day && month && year ? `${day}/${month}/${year}` : value;
}

function isOverdue(value) {
  return value && String(value).slice(0, 10) < new Date().toISOString().slice(0, 10);
}

function latestInspectionByEstablishment() {
  const map = new Map();
  registry.inspections.forEach((item) => {
    if (!item.establishment_id) return;
    if (!map.has(item.establishment_id)) map.set(item.establishment_id, item);
  });
  return map;
}

function renderRegistry() {
  const editing = registryEditing.establishment || {};
  const latest = latestInspectionByEstablishment();
  return `
    <div class="grid">
      <div class="span-12 panel">
        <div class="panel-header">
          <div><h2>Estabelecimentos registrados e em registro</h2><p class="muted">Cadastro informatizado com as informacoes minimas exigidas para o SISBI-POA.</p></div>
          <button class="btn" data-action="new-establishment">Novo estabelecimento</button>
        </div>
        <table class="table">
          <thead><tr><th>Estabelecimento</th><th>CNPJ/CPF</th><th>N. SIM</th><th>Situacao</th><th>Classificacao</th><th>Risco</th><th>Proxima inspecao</th><th></th></tr></thead>
          <tbody>
            ${registry.establishments.map((est) => {
              const last = latest.get(est.id);
              const due = last ? last.next_due : "";
              return `<tr>
                <td><strong>${escapeHtml(est.trade_name || est.legal_name)}</strong><br><span class="muted small">${escapeHtml(est.legal_name)}</span></td>
                <td>${escapeHtml(est.cnpj_cpf || "-")}</td>
                <td>${escapeHtml(est.sim_number || "-")}</td>
                <td><span class="status ${/ativo/i.test(est.situation) ? "approved" : /cancelado|interditado/i.test(est.situation) ? "corrections" : "review"}">${escapeHtml(est.situation)}</span></td>
                <td>${escapeHtml(est.classification || "-")}</td>
                <td>${escapeHtml(est.risk_level || "-")} (${est.inspection_frequency_days || 90}d)</td>
                <td>${due ? `<span class="${isOverdue(due) ? "status corrections" : ""}">${formatDay(due)}${isOverdue(due) ? " - vencida" : ""}</span>` : "Sem inspecao registrada"}</td>
                <td><button class="btn" data-edit-establishment="${est.id}">Editar</button></td>
              </tr>`;
            }).join("") || `<tr><td colspan="8" class="muted">Nenhum estabelecimento cadastrado.</td></tr>`}
          </tbody>
        </table>
      </div>
      <div class="span-12 panel">
        <div class="panel-header">
          <div><h2>${editing.id ? `Editando: ${escapeHtml(editing.trade_name || editing.legal_name)}` : "Novo cadastro"}</h2>
          <p class="muted">Campos conforme exigencia de cadastro informatizado (razao social, SIM, situacao, RT, classificacao, especies e capacidade).</p></div>
          <button class="btn primary" data-action="save-establishment">${icon("check")}Salvar cadastro</button>
        </div>
        <div class="form-grid">
          ${regField("establishment", "legal_name", "Razao social / nome *", editing.legal_name)}
          ${regField("establishment", "trade_name", "Nome fantasia", editing.trade_name)}
          ${regField("establishment", "cnpj_cpf", "CNPJ / CPF", editing.cnpj_cpf)}
          ${regField("establishment", "sim_number", "Numero do SIM", editing.sim_number)}
          ${regField("establishment", "registration_date", "Data do registro inicial", editing.registration_date, { type: "date" })}
          ${regField("establishment", "last_project_protocol", "Protocolo/data do ultimo projeto aprovado", editing.last_project_protocol)}
          ${regField("establishment", "address", "Endereco", editing.address)}
          ${regField("establishment", "district", "Bairro", editing.district)}
          ${regField("establishment", "city", "Municipio", editing.city ?? "Orlandia")}
          ${regField("establishment", "state", "UF", editing.state ?? "SP")}
          ${regField("establishment", "zip", "CEP", editing.zip)}
          ${regField("establishment", "phone", "Telefone", editing.phone)}
          ${regField("establishment", "email", "E-mail", editing.email)}
          ${regField("establishment", "legal_responsible", "Responsavel legal", editing.legal_responsible)}
          ${regField("establishment", "technical_responsible", "Responsavel tecnico", editing.technical_responsible)}
          ${regField("establishment", "situation", "Situacao", editing.situation ?? "Em registro", { options: SITUATIONS })}
          ${regField("establishment", "classification", "Classificacao (Dec. 9.013/2017 no que couber)", editing.classification, { full: true })}
          ${regField("establishment", "species_capacity", "Especies abatidas e capacidade (quando couber)", editing.species_capacity, { full: true })}
          ${regField("establishment", "risk_level", "Risco estimado", editing.risk_level ?? "Medio", { options: RISK_LEVELS })}
          ${regField("establishment", "inspection_frequency_days", "Frequencia de inspecao (dias)", editing.inspection_frequency_days ?? 90, { type: "number" })}
          ${regField("establishment", "notes", "Observacoes", editing.notes, { textarea: true, full: true })}
        </div>
      </div>
    </div>
  `;
}

function renderInspections() {
  const editing = registryEditing.inspection || {};
  return `
    <div class="grid">
      <div class="span-12 panel">
        <div class="panel-header">
          <div><h2>${editing.id ? "Editando inspecao" : "Registrar inspecao / fiscalizacao"}</h2>
          <p class="muted">A proxima inspecao e calculada pela frequencia de risco do estabelecimento (art. 9 e 11, Dec. 5.368/2024).</p></div>
          <div class="actions">
            <button class="btn" data-action="new-inspection">Nova</button>
            <button class="btn primary" data-action="save-inspection">${icon("check")}Salvar inspecao</button>
          </div>
        </div>
        <div class="form-grid">
          ${establishmentSelect("inspection", editing.establishment_id)}
          ${regField("inspection", "inspection_date", "Data", editing.inspection_date, { type: "date" })}
          ${regField("inspection", "kind", "Tipo", editing.kind ?? "Inspecao periodica", { options: INSPECTION_KINDS })}
          ${regField("inspection", "inspector", "Servidor responsavel", editing.inspector ?? (session ? session.name : ""))}
          ${regField("inspection", "decision", "Decisao / providencia", editing.decision ?? "Sem nao conformidades", { options: INSPECTION_DECISIONS })}
          ${regField("inspection", "findings", "Constatacoes (higiene, agua, temperaturas, rotulagem, rastreabilidade, autocontroles...)", editing.findings, { textarea: true, full: true })}
        </div>
      </div>
      <div class="span-12 panel">
        <div class="panel-header"><h2>Historico de inspecoes</h2></div>
        <table class="table">
          <thead><tr><th>Data</th><th>Estabelecimento</th><th>Tipo</th><th>Servidor</th><th>Decisao</th><th>Proxima</th><th></th></tr></thead>
          <tbody>
            ${registry.inspections.map((item) => `<tr>
              <td>${formatDay(item.inspection_date)}</td>
              <td>${escapeHtml(item.establishment_name || establishmentName(item.establishment_id))}</td>
              <td>${escapeHtml(item.kind || "-")}</td>
              <td>${escapeHtml(item.inspector || "-")}</td>
              <td>${escapeHtml(item.decision || "-")}</td>
              <td>${item.next_due ? `<span class="${isOverdue(item.next_due) ? "status corrections" : ""}">${formatDay(item.next_due)}</span>` : "-"}</td>
              <td><button class="btn" data-edit-inspection="${item.id}">Editar</button></td>
            </tr>`).join("") || `<tr><td colspan="7" class="muted">Nenhuma inspecao registrada.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function renderSamples() {
  const editing = registryEditing.sample || {};
  return `
    <div class="grid">
      <div class="span-12 panel">
        <div class="panel-header">
          <div><h2>${editing.id ? "Editando coleta" : "Registrar coleta de amostra"}</h2>
          <p class="muted">Coletas para analise fiscal (art. 10, VI e art. 115, Dec. 5.368/2024) e gestao dos resultados.</p></div>
          <div class="actions">
            <button class="btn" data-action="new-sample">Nova</button>
            <button class="btn primary" data-action="save-sample">${icon("check")}Salvar coleta</button>
          </div>
        </div>
        <div class="form-grid">
          ${establishmentSelect("sample", editing.establishment_id)}
          ${regField("sample", "collection_date", "Data da coleta", editing.collection_date, { type: "date" })}
          ${regField("sample", "product", "Produto / matriz", editing.product)}
          ${regField("sample", "analysis_type", "Tipo de analise", editing.analysis_type ?? "Microbiologica", { options: ["Microbiologica", "Fisico-quimica", "Agua de abastecimento", "Residuos e contaminantes", "Outra"] })}
          ${regField("sample", "lab", "Laboratorio", editing.lab)}
          ${regField("sample", "status", "Status", editing.status ?? "Coletada", { options: SAMPLE_STATUSES })}
          ${regField("sample", "result", "Resultado / laudo", editing.result, { textarea: true })}
          ${regField("sample", "notes", "Observacoes", editing.notes, { textarea: true })}
        </div>
      </div>
      <div class="span-12 panel">
        <div class="panel-header"><h2>Amostras coletadas</h2></div>
        <table class="table">
          <thead><tr><th>Data</th><th>Estabelecimento</th><th>Produto</th><th>Analise</th><th>Laboratorio</th><th>Status</th><th></th></tr></thead>
          <tbody>
            ${registry.samples.map((item) => `<tr>
              <td>${formatDay(item.collection_date)}</td>
              <td>${escapeHtml(item.establishment_name || establishmentName(item.establishment_id))}</td>
              <td>${escapeHtml(item.product || "-")}</td>
              <td>${escapeHtml(item.analysis_type || "-")}</td>
              <td>${escapeHtml(item.lab || "-")}</td>
              <td><span class="status ${/nao conforme/i.test(item.status || "") ? "corrections" : /conforme/i.test(item.status || "") ? "approved" : "review"}">${escapeHtml(item.status || "-")}</span></td>
              <td><button class="btn" data-edit-sample="${item.id}">Editar</button></td>
            </tr>`).join("") || `<tr><td colspan="7" class="muted">Nenhuma coleta registrada.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function lawLink(url, label) {
  return `<a href="${url}" target="_blank" rel="noreferrer">${label}</a>`;
}

function renderLegislation() {
  return `
    <div class="grid">
      <div class="span-7 panel">
        <div class="panel-header"><h2>Base legal municipal</h2><span class="status review">Publicacoes oficiais</span></div>
        <table class="table">
          <tr><th>LC 84/2024</th><td>Institui a obrigatoriedade de previa inspecao e fiscalizacao de POA e reestrutura o SIM. Art. 11: documentos do registro; art. 18: multas de 20 a 1.000 UFESP; art. 21: arrecadacao vinculada ao SIM.<br>${lawLink("https://www.orlandia.sp.gov.br/novo/wp-content/uploads/2024/08/Edicao-1844-de-19-de-junho-de-2024-Extraordinaria.pdf", "Publicacao oficial - ed. 1844, 19/06/2024 (PDF)")} - ${lawLink("https://leis.org/municipais/sp/orlandia/lei/lei-complementar/2024/84/lei-complementar-n-84-2024-dispoe-sobre-a-obrigatoriedade-de-previa-inspecao-e-fiscalizacao-dos-produtos-de-origem-animal-no-ambito-do-municipio-de-orlandia-reestrutura-o-servico-de-inspecao-municipal-sim-e-da-outras", "texto consolidado")}</td></tr>
          <tr><th>LC 104/2026</th><td>Institui a Taxa de Inspecao Sanitaria do SIM no Codigo Tributario (arts. 175-A a 175-D da LC 3.333/2003) e altera a LC 84/2024 (divida ativa das multas).<br>${lawLink("https://dosp.com.br/exibe_do.php?i=ODM4OTQ0", "Publicacao oficial - ed. 2338, 25/06/2026")}</td></tr>
          <tr><th>Decreto 5.368/2024</th><td>Regulamento operacional do SIM. Registro (arts. 21-25), medidas cautelares (art. 115), infracoes (art. 117), sancoes (art. 129), processo administrativo (arts. 141-154).<br>${lawLink("https://www.dosp.com.br/exibe_do.php?i=NTE2NTQx", "Publicacao oficial - ed. 1854, 03/07/2024")}</td></tr>
          <tr><th>Decretos 5.373 e 5.374/2024</th><td>Carimbos/identidade visual do SIM e formularios oficiais (Anexos I a VII; atos fiscais em 4 vias).<br>${lawLink("https://www.dosp.com.br/exibe_do.php?i=NTI5MjMy", "Publicacao oficial - ed. 1871, 30/07/2024")}</td></tr>
          <tr><th>Portarias SIM (dez/2024)</th><td>Autocontrole obrigatorio, mitigacao de conflitos, auditoria/supervisao e frequencia de inspecao por risco.<br>${lawLink("https://cespro.com.br/visualizarDiarioOficialLeituraDigital.php?cdMunicipio=9314&dtDiario=2024-12-20&nrEdicao=12061", "DO 20/12/2024 (autocontrole, p. 10-11; mitigacao, p. 8-9)")} - ${lawLink("https://dosp.com.br/exibe_do.php?i=NTY2Nzg1", "DO (auditoria p. 4-15; frequencia por risco p. 16-24)")}</td></tr>
          <tr><th>Portaria 33.159/2026</th><td>Designacao do Medico Veterinario Oficial responsavel pelo SIM (13/07/2026). Rotina minima semanal de 6 horas; substituicao em afastamentos.</td></tr>
        </table>
      </div>
      <div class="span-5 panel">
        <div class="panel-header"><h2>Taxa de Inspecao Sanitaria (LC 104/2026)</h2></div>
        <table class="table">
          <tr><th>Registro inicial de estabelecimento e renovacao anual</th><td>100 UFMO</td></tr>
          <tr><th>Analise de projeto de reforma/ampliacao; inclusao ou alteracao de categoria</th><td>60 UFMO</td></tr>
          <tr><th>Transferencia de titularidade / alteracao cadastral</th><td>40 UFMO</td></tr>
          <tr><th>Registro inicial de produto</th><td>40 UFMO</td></tr>
          <tr><th>Alteracao de registro de produto</th><td>40 UFMO</td></tr>
        </table>
        <p class="small muted">Pagamento antecipado a prestacao do servico (art. 175-D); conversao pela UFMO do mes do pagamento. <strong>Em 2026 os servicos sao prestados sem cobranca</strong>; a exigibilidade comeca no exercicio seguinte, respeitadas as anterioridades anual e nonagesimal (art. 3 da LC 104/2026).</p>
        <div class="panel-header" style="margin-top:18px"><h2>Prazos do processo administrativo</h2></div>
        <table class="table">
          <tr><th>Defesa do autuado</th><td>10 dias da cientificacao (art. 145, Dec. 5.368/2024).</td></tr>
          <tr><th>Recurso</th><td>10 dias da ciencia da decisao de 1a instancia (art. 148).</td></tr>
          <tr><th>Multa</th><td>Em UFESP, pela data da lavratura (art. 150). Nao paga em 30 dias: divida ativa com correcao, multa moratoria de 2% e juros de 1% ao mes (art. 18, par. 4, LC 84/2024, incluido pela LC 104/2026).</td></tr>
          <tr><th>Interdicao</th><td>Nao levantada em 12 meses: cancelamento do registro (art. 129, par. 3).</td></tr>
        </table>
      </div>
      <div class="span-12 panel">
        <div class="panel-header"><h2>Base federal aplicavel</h2></div>
        <table class="table">
          <tr><th>${lawLink("https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2017/decreto/d9013.htm", "Decreto 9.013/2017 (RIISPOA)")}</th><td>Classificacao dos estabelecimentos (Titulo II) e condicoes de higiene, aplicaveis no que couber (arts. 14 e 42 do Dec. 5.368/2024). Art. 153: condicoes para equivalencia/SISBI.</td></tr>
          <tr><th>${lawLink("https://www.planalto.gov.br/ccivil_03/leis/l1283.htm", "Lei 1.283/1950")} e ${lawLink("https://www.planalto.gov.br/ccivil_03/leis/l7889.htm", "Lei 7.889/1989")}</th><td>Obrigatoriedade da inspecao de POA e competencia municipal.</td></tr>
          <tr><th>${lawLink("https://www.planalto.gov.br/ccivil_03/leis/l8171.htm", "Lei 8.171/1991")} e ${lawLink("https://www.planalto.gov.br/ccivil_03/leis/l9712.htm", "Lei 9.712/1998")}</th><td>SUASA e agroindustria de pequeno porte. Base para equivalencia e adesao ao SISBI-POA (comercio intermunicipal/interestadual).</td></tr>
          <tr><th>${lawLink("https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm", "LC 123/2006")} e ${lawLink("https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2019/lei/l13874.htm", "Lei 13.874/2019")}</th><td>Tratamento diferenciado a ME/EPP (atenuante do art. 131) e liberdade economica.</td></tr>
          <tr><th>${lawLink("https://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm", "Lei 8.078/1990 (CDC)")}</th><td>Defesa do consumidor, principio orientador do Dec. 5.368/2024.</td></tr>
        </table>
      </div>
    </div>
  `;
}

function renderFiscalActs() {
  return `
    <div class="grid">
      <div class="span-8 panel">
        <div class="panel-header">
          <div><h2>Lavratura de ato fiscal</h2><p class="muted">Preenchimento exclusivo do fiscal. O numero e gerado automaticamente pelo livro de atos ao lavrar.</p></div>
          <span class="status review">Exclusivo SIM</span>
        </div>
        <div class="form-grid">
          ${establishmentSelect("fiscalCtx", fiscalActContext.establishmentId, "Estabelecimento autuado")}
          ${selectInput("fiscalAct.type", "Tipo de ato", ACT_TYPES, { owner: "sim" })}
          ${input("fiscalAct.date", "Data da fiscalizacao", { type: "date", owner: "sim" })}
          ${input("fiscalAct.inspectionPlace", "Local da fiscalizacao", { owner: "sim" })}
          ${input("fiscalAct.legalBasis", "Dispositivos legais", { textarea: true, full: true, owner: "sim" })}
          ${input("fiscalAct.facts", "Infracao / fatos constatados", { textarea: true, full: true, owner: "sim" })}
          ${input("fiscalAct.seizedMaterial", "Material apreendido", { textarea: true, owner: "sim" })}
          ${input("fiscalAct.attenuatingAggravating", "Circunstancias atenuantes e agravantes", { textarea: true, owner: "sim" })}
          ${input("fiscalAct.notification", "Notificacao e orientacao ao autuado/advertido", { textarea: true, owner: "sim" })}
          ${input("fiscalAct.otherInfo", "Outras informacoes", { textarea: true, owner: "sim" })}
          ${input("fiscalAct.witnesses", "Testemunhas", { textarea: true, full: true, owner: "sim" })}
        </div>
      </div>
      <div class="span-4 panel">
        <div class="panel-header"><h2>Livro de atos</h2></div>
        <p class="muted small">Ao lavrar, o ato recebe numero sequencial (ex.: AI-2026-001), fica gravado no banco com autor e horario e passa a compor o historico de infracoes do estabelecimento. O prazo de defesa (10 dias, art. 145) e calculado a partir da data de ciencia.</p>
        <div class="checklist">
          <button class="btn primary" data-action="record-fiscal-act">${icon("check")}Lavrar ato no livro</button>
          <button class="btn" data-view="print">${icon("print")}Imprimir ato em tela</button>
        </div>
        <div class="panel-header" style="margin-top:18px"><h2>Modelos oficiais</h2></div>
        <div class="checklist">
          <label class="check-item"><input type="checkbox" checked disabled><span>Anexo V - Auto de Infracao</span><span class="muted small">4 vias</span></label>
          <label class="check-item"><input type="checkbox" checked disabled><span>Anexo VI - Termo de Advertencia</span><span class="muted small">4 vias</span></label>
          <label class="check-item"><input type="checkbox" checked disabled><span>Anexo VII - Auto de Apreensao</span><span class="muted small">4 vias</span></label>
        </div>
      </div>
      <div class="span-12 panel">
        <div class="panel-header"><h2>Livro de atos fiscais / historico de infracoes</h2></div>
        <table class="table">
          <thead><tr><th>Numero</th><th>Tipo</th><th>Estabelecimento</th><th>Data</th><th>Ciencia</th><th>Prazo de defesa</th><th>Status</th><th></th></tr></thead>
          <tbody>
            ${registry.fiscalActs.map((act) => `<tr>
              <td><strong>${escapeHtml(act.act_number)}</strong></td>
              <td>${escapeHtml(act.act_type)}</td>
              <td>${escapeHtml(act.establishment_name || establishmentName(act.establishment_id))}</td>
              <td>${formatDay(act.act_date)}</td>
              <td><input type="date" data-act-science="${act.id}" value="${escapeHtml(act.science_date || "")}"></td>
              <td>${act.defense_deadline ? `<span class="${isOverdue(act.defense_deadline) && !/transitado|arquivado|julgado/i.test(act.status) ? "status corrections" : ""}">${formatDay(act.defense_deadline)}</span>` : "-"}</td>
              <td><select data-act-status="${act.id}">${ACT_STATUSES.map((status) => `<option ${act.status === status ? "selected" : ""}>${status}</option>`).join("")}</select></td>
              <td><button class="btn" data-load-act="${act.id}">Carregar p/ impressao</button></td>
            </tr>`).join("") || `<tr><td colspan="8" class="muted">Nenhum ato lavrado.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function renderPrint() {
  const establishmentTabs = [
    ["anexoI", "Anexo I"],
    ["mtse", "MTSE"],
    ["construction", "Construcao/reforma"],
    ["produto", "Produto/rotulo"],
  ];
  const fiscalTabs = [
    ["infracao", "Auto de infracao"],
    ["advertencia", "Advertencia"],
    ["apreensao", "Apreensao"],
  ];
  // Atos fiscais (infracao/advertencia/apreensao) sao ferramenta exclusiva do
  // fiscal: o estabelecimento nao lavra nem imprime esses modelos por conta propria.
  const tabs = state.role === "sim" ? [...establishmentTabs, ...fiscalTabs] : establishmentTabs;
  if (state.role !== "sim" && fiscalTabs.some(([id]) => id === state.printForm)) {
    state.printForm = "anexoI";
  }
  return `
    <div class="tabs no-print">${tabs.map(([id, label]) => `<button class="${state.printForm === id ? "active" : ""}" data-print-form="${id}">${label}</button>`).join("")}</div>
    <div class="actions no-print" style="margin-bottom:14px">
      <button class="btn primary" data-action="print">${icon("print")}Imprimir</button>
    </div>
    ${printSheet()}
  `;
}

function printSheet() {
  if (state.printForm === "mtse") return printMtse();
  if (state.printForm === "construction") return printConstruction();
  if (state.printForm === "produto") return printProduct();
  if (state.printForm === "advertencia") return printFiscal("TERMO DE ADVERTENCIA");
  if (state.printForm === "apreensao") return printFiscal("AUTO DE APREENSAO");
  if (state.printForm === "infracao") return printFiscal("AUTO DE INFRACAO");
  return printAnexoI();
}

function printHeader(title) {
  return `
    <div class="print-sheet">
      <div class="print-brand">
        <img src="./assets/brasao-orlandia.png" alt="Brasao de Orlandia">
        <h2>PREFEITURA MUNICIPAL DE ORLANDIA-SP<br>SECRETARIA MUNICIPAL DE DESENVOLVIMENTO ECONOMICO E TURISMO<br>SERVICO DE INSPECAO MUNICIPAL</h2>
      </div>
      <h2>${title}</h2>
  `;
}

function masterRows() {
  return `
    <tr><th>Razao social / nome</th><td>${state.establishment.legalName}</td><th>CNPJ/CPF</th><td>${state.establishment.cnpj}</td></tr>
    <tr><th>Nome fantasia</th><td>${state.establishment.tradeName}</td><th>CNAE</th><td>${state.establishment.cnae}</td></tr>
    <tr><th>Inscricao estadual</th><td>${state.establishment.stateRegistration || "&nbsp;"}</td><th>Inscricao municipal</th><td>${state.establishment.municipalRegistration || "&nbsp;"}</td></tr>
    <tr><th>Endereco</th><td>${state.establishment.address}</td><th>Bairro</th><td>${state.establishment.district}</td></tr>
    <tr><th>Municipio/UF</th><td>${state.establishment.city}/${state.establishment.state}</td><th>CEP</th><td>${state.establishment.zip}</td></tr>
    <tr><th>E-mail</th><td>${state.establishment.email || "&nbsp;"}</td><th>Telefone</th><td>${state.establishment.phone || "&nbsp;"}</td></tr>
  `;
}

function printAnexoI() {
  return `${printHeader("ANEXO I - SOLICITACAO DE ATOS DO S.I.M.")}
    <table class="print-table">${masterRows()}
      <tr><th>Responsavel legal</th><td>${state.legalResponsible.name}</td><th>CPF</th><td>${state.legalResponsible.cpf || "&nbsp;"}</td></tr>
      <tr><th>Responsavel tecnico</th><td>${state.technicalResponsible.name || "&nbsp;"}</td><th>Conselho/UF</th><td>${state.technicalResponsible.council || "&nbsp;"}</td></tr>
      <tr><th>Classificacao</th><td colspan="3">${state.establishment.classification}</td></tr>
      <tr><th>Tipo de solicitacao</th><td colspan="3">${state.application.actType}${state.application.otherAct ? ` - ${state.application.otherAct}` : ""}</td></tr>
      <tr><th>Termo de compromisso</th><td colspan="3">${state.application.commitment}</td></tr>
    </table>
    <p>Declaramos cumprir a legislacao vigente e assumimos responsabilidade pela veracidade das informacoes.</p>
    <div class="signature"><div>Responsavel legal</div><div>Responsavel tecnico</div></div>
  </div>`;
}

function printMtse() {
  return `${printHeader("ANEXO II - MEMORIAL TECNICO-SANITARIO DO ESTABELECIMENTO")}
    <table class="print-table">${masterRows()}
      <tr><th>Classificacao</th><td colspan="3">${state.establishment.classification}</td></tr>
      <tr><th>Atividades gerais</th><td colspan="3">${state.production.activities || "&nbsp;"}</td></tr>
      <tr><th>Produtos e capacidade mensal</th><td colspan="3">${state.production.monthlyCapacity || "&nbsp;"}</td></tr>
      <tr><th>Origem da materia-prima / rastreamento</th><td colspan="3">${state.production.rawMaterialOrigin || "&nbsp;"}</td></tr>
      <tr><th>Funcionarios</th><td colspan="3">${state.production.employees || "&nbsp;"}</td></tr>
      <tr><th>Lavanderia</th><td colspan="3">${state.production.laundry || "&nbsp;"}</td></tr>
      <tr><th>Terreno e area de localizacao</th><td colspan="3">${[state.production.landDetails, state.production.locationArea].filter(Boolean).join(" / ") || "&nbsp;"}</td></tr>
      <tr><th>Fluxo e disposicao das instalacoes</th><td colspan="3">${state.production.flow || "&nbsp;"}</td></tr>
      <tr><th>Equipamentos</th><td colspan="3">${state.production.equipment || "&nbsp;"}</td></tr>
      <tr><th>Piso, paredes e impermeabilizacao</th><td colspan="3">${state.production.floorWalls || "&nbsp;"}</td></tr>
      <tr><th>Janelas, portas, teto e bloqueio sanitario</th><td colspan="3">${state.production.doorsWindowsCeiling || "&nbsp;"}</td></tr>
      <tr><th>Banheiros, vestiarios e funcionarios</th><td colspan="3">${state.production.bathrooms || "&nbsp;"}</td></tr>
      <tr><th>Iluminacao e ventilacao</th><td colspan="3">${state.production.lightingVentilation || "&nbsp;"}</td></tr>
      <tr><th>Depositos</th><td colspan="3">${state.production.storage || "&nbsp;"}</td></tr>
      <tr><th>Abastecimento de agua</th><td colspan="3">${state.production.waterSupply || "&nbsp;"}</td></tr>
      <tr><th>Aguas servidas</th><td colspan="3">${state.production.effluents || "&nbsp;"}</td></tr>
      <tr><th>Transporte</th><td colspan="3">${state.production.transport || "&nbsp;"}</td></tr>
      <tr><th>Analises laboratoriais</th><td colspan="3">${state.production.labAnalysis || "&nbsp;"}</td></tr>
      <tr><th>Dias e horarios de producao</th><td colspan="3">${state.production.productionSchedule || "&nbsp;"}</td></tr>
      <tr><th>Controles de qualidade</th><td colspan="3">${state.production.qualityControls || "&nbsp;"}</td></tr>
    </table>
    <div class="signature"><div>Responsavel legal</div><div>Responsavel tecnico</div></div>
  </div>`;
}

function printConstruction() {
  return `${printHeader("ANEXO III - MEMORIAL DESCRITIVO DE CONSTRUCAO/REFORMA")}
    <table class="print-table">${masterRows()}
      <tr><th>Caracterizacao do estabelecimento</th><td colspan="3">${state.establishment.classification}</td></tr>
      <tr><th>Motivo</th><td colspan="3">${state.construction.requestReason || state.application.actType || "&nbsp;"}</td></tr>
      <tr><th>Ambientes e dependencias</th><td colspan="3">${state.construction.rooms || "&nbsp;"}</td></tr>
      <tr><th>Descricao da construcao</th><td colspan="3">${state.construction.buildingDescription || "&nbsp;"}</td></tr>
      <tr><th>Materiais e acabamentos</th><td colspan="3">${state.construction.materials || "&nbsp;"}</td></tr>
      <tr><th>Camara fria / temperatura</th><td colspan="3">${state.construction.coldRooms || "&nbsp;"}</td></tr>
      <tr><th>Agua, esgoto e drenagem</th><td colspan="3">${state.construction.waterAndSewage || "&nbsp;"}</td></tr>
      <tr><th>Observacao</th><td colspan="3">${state.construction.observations || "&nbsp;"}</td></tr>
    </table>
    <div class="signature"><div>Responsavel legal</div><div>Responsavel tecnico</div></div>
  </div>`;
}

function printProduct() {
  const product = state.products[0] || { name: "", brand: "", conservation: "", notes: "" };
  return `${printHeader("ANEXO IV - REGISTRO DE ROTULO E/OU PRODUTO DE ORIGEM ANIMAL")}
    <table class="print-table">${masterRows()}
      <tr><th>SIM do estabelecimento</th><td>${state.establishment.simNumber}</td><th>Responsavel legal</th><td>${state.legalResponsible.name}</td></tr>
      <tr><th>Natureza da solicitacao</th><td colspan="3">${product.requestNature || "&nbsp;"}</td></tr>
      <tr><th>Nome do produto</th><td>${product.name}</td><th>Marca</th><td>${product.brand}</td></tr>
      <tr><th>Conservacao</th><td>${product.conservation}</td><th>Embalagem</th><td>${product.packageType || "&nbsp;"}</td></tr>
      <tr><th>Caracteristicas do rotulo/embalagem</th><td colspan="3">${product.labelFeatures || "&nbsp;"}</td></tr>
      <tr><th>Composicao</th><td colspan="3">${product.composition || "&nbsp;"}</td></tr>
      <tr><th>Informacao nutricional</th><td colspan="3">${product.nutrition || "&nbsp;"}</td></tr>
      <tr><th>Processo de fabricacao</th><td colspan="3">${product.manufacturingProcess || product.notes || "&nbsp;"}</td></tr>
      <tr><th>Processo de embalagem</th><td colspan="3">${product.packagingProcess || "&nbsp;"}</td></tr>
      <tr><th>Condicoes de armazenamento</th><td colspan="3">${product.storageConditions || "&nbsp;"}</td></tr>
      <tr><th>Medidas de controle</th><td colspan="3">${product.notes || state.production.qualityControls || "&nbsp;"}</td></tr>
      <tr><th>Transporte e expedicao</th><td colspan="3">${product.marketTransport || state.production.transport || "&nbsp;"}</td></tr>
    </table>
    <div class="signature"><div>Responsavel legal</div><div>Responsavel tecnico</div></div>
  </div>`;
}

function printFiscal(title) {
  return `${printHeader(title)}
    <table class="print-table">${masterRows()}
      <tr><th>Numero</th><td>${state.fiscalAct.number || "&nbsp;"}</td><th>Data</th><td>${state.fiscalAct.date || "&nbsp;"}</td></tr>
      <tr><th>Responsavel pelo estabelecimento</th><td>${state.legalResponsible.name || "&nbsp;"}</td><th>CPF</th><td>${state.legalResponsible.cpf || "&nbsp;"}</td></tr>
      <tr><th>Local da fiscalizacao</th><td colspan="3">${state.fiscalAct.inspectionPlace || `${state.establishment.address}, ${state.establishment.district}`}</td></tr>
      <tr><th>Dispositivos legais</th><td colspan="3">${state.fiscalAct.legalBasis || "&nbsp;"}</td></tr>
      <tr><th>Infracao / fatos constatados</th><td colspan="3" style="height:120px">${state.fiscalAct.facts || "&nbsp;"}</td></tr>
      <tr><th>Material apreendido</th><td colspan="3">${state.fiscalAct.seizedMaterial || "&nbsp;"}</td></tr>
      <tr><th>Atenuantes e agravantes</th><td colspan="3">${state.fiscalAct.attenuatingAggravating || "&nbsp;"}</td></tr>
      <tr><th>Notificacao e orientacao</th><td colspan="3">${state.fiscalAct.notification || "&nbsp;"}</td></tr>
      <tr><th>Outras informacoes</th><td colspan="3">${state.fiscalAct.otherInfo || "&nbsp;"}</td></tr>
      <tr><th>Testemunhas</th><td colspan="3">${state.fiscalAct.witnesses || "&nbsp;"}</td></tr>
    </table>
    <p>Modelo destinado a impressao em 4 vias, conforme anexos fiscais do Decreto municipal n. 5.374/2024.</p>
    <div class="signature"><div>Fiscal do SIM</div><div>Ciencia do autuado</div></div>
  </div>`;
}

function render() {
  if (backendAvailable && !session) {
    document.querySelector("#app").innerHTML = renderLogin();
    bindLoginEvents();
    return;
  }
  const views = {
    dashboard: renderDashboard,
    establishment: renderEstablishment,
    documents: renderDocuments,
    products: renderProducts,
    print: renderPrint,
    review: renderReview,
    fiscal: renderFiscalActs,
    registry: renderRegistry,
    inspections: renderInspections,
    samples: renderSamples,
    legislation: renderLegislation,
  };
  const establishmentViews = ["dashboard", "establishment", "documents", "products", "print"];
  if (state.role === "establishment" && !establishmentViews.includes(state.view)) {
    state.view = "dashboard";
  }
  document.querySelector("#app").innerHTML = renderShell((views[state.view] || renderDashboard)());
  bindEvents();
}

function bindEvents() {
  document.querySelectorAll("[data-role]").forEach((el) => el.addEventListener("click", () => setRole(el.dataset.role)));
  document.querySelectorAll("[data-view]").forEach((el) => el.addEventListener("click", () => setView(el.dataset.view)));
  document.querySelectorAll("[data-path]").forEach((el) => {
    el.addEventListener("input", () => update(el.dataset.path, el.value));
  });
  document.querySelectorAll("[data-doc]").forEach((el) => {
    el.addEventListener("change", () => {
      const doc = state.documents.find((item) => item.id === el.dataset.doc);
      doc.status = el.value;
      record(`Documento atualizado: ${doc.name} (${doc.status}).`);
      saveState();
      render();
    });
  });
  document.querySelectorAll("[data-product]").forEach((el) => {
    el.addEventListener("input", updateProduct);
    el.addEventListener("change", updateProduct);
  });
  document.querySelectorAll("[data-upload-doc]").forEach((el) => {
    el.addEventListener("change", () => uploadDocument(el.dataset.uploadDoc, el.files[0]));
  });
  document.querySelectorAll("[data-open-upload]").forEach((el) => {
    el.addEventListener("click", () => openUpload(el.dataset.openUpload));
  });
  document.querySelectorAll("[data-print-form]").forEach((el) => {
    el.addEventListener("click", () => {
      state.printForm = el.dataset.printForm;
      saveState();
      render();
    });
  });
  const reviewNote = document.querySelector("[data-review-note]");
  if (reviewNote) {
    reviewNote.addEventListener("input", () => {
      state.review.note = reviewNote.value;
      saveState();
    });
  }
  const journeySigned = document.querySelector("[data-journey-signed]");
  if (journeySigned) {
    journeySigned.addEventListener("change", () => {
      state.journey = state.journey || {};
      state.journey.signedAck = journeySigned.checked;
      saveState();
      toast(journeySigned.checked ? "Passo de assinatura concluido." : "Passo de assinatura reaberto.");
    });
  }
  document.querySelectorAll("[data-edit-establishment]").forEach((el) => el.addEventListener("click", () => {
    registryEditing.establishment = registry.establishments.find((item) => String(item.id) === el.dataset.editEstablishment) || null;
    render();
  }));
  document.querySelectorAll("[data-edit-inspection]").forEach((el) => el.addEventListener("click", () => {
    registryEditing.inspection = registry.inspections.find((item) => String(item.id) === el.dataset.editInspection) || null;
    render();
  }));
  document.querySelectorAll("[data-edit-sample]").forEach((el) => el.addEventListener("click", () => {
    registryEditing.sample = registry.samples.find((item) => String(item.id) === el.dataset.editSample) || null;
    render();
  }));
  document.querySelectorAll("[data-act-status]").forEach((el) => el.addEventListener("change", () => {
    saveRegistryRecord("/fiscal-acts", { id: Number(el.dataset.actStatus), status: el.value }, "Status do ato atualizado.");
  }));
  document.querySelectorAll("[data-act-science]").forEach((el) => el.addEventListener("change", () => {
    saveRegistryRecord("/fiscal-acts", { id: Number(el.dataset.actScience), science_date: el.value }, "Ciencia registrada; prazo de defesa calculado.");
  }));
  document.querySelectorAll("[data-load-act]").forEach((el) => el.addEventListener("click", () => loadActForPrint(el.dataset.loadAct)));
  document.querySelectorAll("[data-action]").forEach((el) => el.addEventListener("click", () => handleAction(el.dataset.action)));
}

async function saveRegistryRecord(path, body, message) {
  try {
    const data = await api(path, { method: "POST", body });
    registry = data.registry;
    render();
    toast(message);
    return data;
  } catch (error) {
    toast(error.message);
    return null;
  }
}

function loadActForPrint(actId) {
  const act = registry.fiscalActs.find((item) => String(item.id) === String(actId));
  if (!act) return;
  state.fiscalAct = {
    type: act.act_type,
    number: act.act_number,
    date: act.act_date || "",
    inspectionPlace: act.place || "",
    legalBasis: act.legal_basis || "",
    facts: act.facts || "",
    seizedMaterial: act.seized_material || "",
    otherInfo: act.other_info || "",
    attenuatingAggravating: act.attenuating_aggravating || "",
    notification: act.notification || "",
    witnesses: act.witnesses || "",
  };
  const printMap = {
    "Termo de advertencia": "advertencia",
    "Auto de apreensao": "apreensao",
  };
  state.printForm = printMap[act.act_type] || "infracao";
  state.view = "print";
  saveState();
  render();
  toast(`Ato ${act.act_number} carregado para impressao.`);
}

function bindLoginEvents() {
  const form = document.querySelector("[data-login-form]");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    await login(formData.get("email"), formData.get("password"));
  });
}

async function login(email, password) {
  try {
    const data = await api("/login", { method: "POST", body: { email, password } });
    localStorage.setItem(TOKEN_KEY, data.token);
    session = data.user;
    state.role = session.role;
    const remote = await api("/state");
    state = deepMerge(structuredClone(initialState), remote.state);
    state.role = session.role;
    notifications = remote.notifications || [];
    await loadRegistry();
    render();
    toast("Sessao iniciada.");
  } catch (error) {
    toast(error.message);
  }
}

async function logout() {
  try {
    await api("/logout", { method: "POST" });
  } catch {
    // Sessao local sera encerrada mesmo que o token ja tenha expirado.
  }
  localStorage.removeItem(TOKEN_KEY);
  session = null;
  render();
}

async function uploadDocument(docId, file) {
  if (!file) return;
  const form = new FormData();
  form.append("docId", docId);
  form.append("file", file);
  try {
    const data = await api("/uploads", { method: "POST", body: form });
    state = deepMerge(structuredClone(initialState), data.state);
    state.role = session.role;
    notifications.unshift({
      title: "Anexo protocolado",
      message: `${file.name} recebido com SHA-256 ${data.upload.sha256.slice(0, 16)}...`,
      upload_id: data.upload.id,
      document_id: docId,
      created_at: new Date().toISOString(),
    });
    render();
    toast("Arquivo enviado e hasheado.");
  } catch (error) {
    toast(error.message);
  }
}

function openUpload(uploadId) {
  const upload = findUpload(uploadId);
  if (!upload) {
    toast("Versao do anexo nao encontrada no estado atual.");
    return;
  }
  activeUpload = upload;
  render();
}

function updateProduct(event) {
  const product = state.products.find((item) => item.id === event.target.dataset.product);
  product[event.target.dataset.field] = event.target.value;
  saveState();
}

function handleAction(action) {
  if (action === "save") {
    saveState();
    toast("Dados salvos.");
  }
  if (action === "submit") submitProtocol();
  if (action === "approve") reviewDecision("approve");
  if (action === "reject") reviewDecision("reject");
  if (action === "corrections") reviewDecision("corrections");
  if (action === "print") window.print();
  if (action === "logout") logout();
  if (action === "close-modal") {
    activeUpload = null;
    render();
  }
  if (action === "mock-upload") {
    const doc = state.documents.find((item) => item.status !== "Recebido");
    if (doc) {
      doc.status = "Recebido";
      doc.file = `${doc.name.replaceAll(" ", "_")}.pdf`;
      record(`Upload recebido: ${doc.name}.`);
      saveState();
      render();
      toast("Upload simulado registrado.");
    }
  }
  if (action === "new-establishment") {
    registryEditing.establishment = null;
    render();
  }
  if (action === "new-inspection") {
    registryEditing.inspection = null;
    render();
  }
  if (action === "new-sample") {
    registryEditing.sample = null;
    render();
  }
  if (action === "save-establishment") {
    const values = collectFields("establishment");
    if (!values.legal_name) {
      toast("Informe a razao social.");
      return;
    }
    if (registryEditing.establishment?.id) values.id = registryEditing.establishment.id;
    saveRegistryRecord("/establishments", values, "Cadastro do estabelecimento salvo.").then((data) => {
      if (data) registryEditing.establishment = null;
    });
  }
  if (action === "save-inspection") {
    const values = collectFields("inspection");
    if (!values.establishment_id) {
      toast("Selecione o estabelecimento.");
      return;
    }
    if (registryEditing.inspection?.id) values.id = registryEditing.inspection.id;
    saveRegistryRecord("/inspections", values, "Inspecao registrada; proxima inspecao calculada pelo risco.").then((data) => {
      if (data) registryEditing.inspection = null;
    });
  }
  if (action === "save-sample") {
    const values = collectFields("sample");
    if (!values.establishment_id) {
      toast("Selecione o estabelecimento.");
      return;
    }
    if (registryEditing.sample?.id) values.id = registryEditing.sample.id;
    saveRegistryRecord("/samples", values, "Coleta de amostra registrada.").then((data) => {
      if (data) registryEditing.sample = null;
    });
  }
  if (action === "record-fiscal-act") {
    const ctx = collectFields("fiscalCtx");
    if (!ctx.establishment_id) {
      toast("Selecione o estabelecimento autuado.");
      return;
    }
    fiscalActContext.establishmentId = ctx.establishment_id;
    const act = state.fiscalAct;
    saveRegistryRecord("/fiscal-acts", {
      establishment_id: Number(ctx.establishment_id),
      act_type: act.type,
      act_date: act.date,
      place: act.inspectionPlace,
      legal_basis: act.legalBasis,
      facts: act.facts,
      seized_material: act.seizedMaterial,
      attenuating_aggravating: act.attenuatingAggravating,
      notification: act.notification,
      witnesses: act.witnesses,
      other_info: act.otherInfo,
      status: "Lavrado",
    }, "Ato lavrado no livro com numero sequencial.").then((data) => {
      if (data) {
        const created = registry.fiscalActs.find((item) => item.id === data.id);
        if (created) state.fiscalAct.number = created.act_number;
        saveState();
        render();
      }
    });
  }
  if (action === "add-product") {
    state.products.push({
      id: crypto.randomUUID(),
      name: "",
      brand: state.establishment.tradeName,
      status: "Rascunho",
      conservation: "",
      notes: "",
      requestNature: "Registro de produto e rotulo",
      packageType: "",
      labelFeatures: "",
      composition: "",
      nutrition: "",
      manufacturingProcess: "",
      packagingProcess: "",
      storageConditions: "",
      marketTransport: "",
    });
    record("Produto adicionado ao protocolo.");
    saveState();
    render();
  }
}

bootstrap();
