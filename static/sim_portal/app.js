const STORAGE_KEY = "portal-sim-orlandia-v1";
const TOKEN_KEY = "portal-sim-orlandia-token";
// Quando servido como blueprint do PetOrlandia em /sim, a API fica em /sim/api.
const BASE_PATH = location.pathname.replace(/\/(index\.html)?$/, "");
const API_ROOT = `${BASE_PATH}/api`;
// Prefixo de docId usado para anexar o rotulo direto na tela de cada produto
// (precisa bater com PRODUCT_LABEL_PREFIX no backend).
const PRODUCT_LABEL_PREFIX = "rotulo-produto-";
const LC84_URL = "https://www.orlandia.sp.gov.br/novo/wp-content/uploads/2024/08/Edicao-1844-de-19-de-junho-de-2024-Extraordinaria.pdf";
const DEC5374_URL = "https://www.orlandia.sp.gov.br/novo/wp-content/uploads/2024/08/Edicao-1871-de-30-de-julho-de-2024_compressed.pdf";
const LC104_URL = "https://dosp.com.br/exibe_do.php?i=ODM4OTQ0";
const CFMV1177_URL = "https://www.legisweb.com.br/legislacao/?id=352065";
const CFMV1562_URL = "https://www.crmvse.org.br/wp-content/uploads/2024/01/RESOLUCAO-CFMV-1562.pdf";
const CETESB_PORTAL_URL = "https://e.cetesb.sp.gov.br/portal-servicos-frontend/servicos-disponiveis?aba=servicos";
const CETESB_PROCESSO_GUERRA_URL = "https://licenciamento.cetesb.sp.gov.br/cetesb/processo_resultado2.asp?razao=LF+%2D+GUERRA+MILK+LTDA++%2D+ME&muni=ORL%C2NDIA&logrd=RUA+F&nmuncp=491&nseqnc=1249&cgc=12934929000177";
const CETESB_FATOR_COMPLEXIDADE_URL = "https://repositorio.cetesb.sp.gov.br/bitstreams/0cfd2bf7-65c7-40d1-90d0-286191d285b4/download";
const DEC8468_URL = "https://licenciamento.cetesb.sp.gov.br/legislacao/estadual/decretos/1976_dec_est_8468.pdf";
const DOCUMENT_SOURCES = {
  "requerimento-assinado": [
    { text: "LC 84/2024, art. 11, I", url: LC84_URL },
    { text: "Decreto 5.374/2024, art. 1 (Anexo I)", url: DEC5374_URL },
  ],
  "plantas-baixas": [
    { text: "LC 84/2024, art. 11, II", url: LC84_URL },
    { text: "Decreto 5.374/2024, art. 3 (Anexo III)", url: DEC5374_URL },
  ],
  "contrato-social-cnpj": [{ text: "LC 84/2024, art. 11, III", url: LC84_URL }],
  "cpf-cnpj": [{ text: "LC 84/2024, art. 11, IV", url: LC84_URL }],
  "inscricao-estadual": [{ text: "LC 84/2024, art. 11, V", url: LC84_URL }],
  "alvara-prefeitura": [{ text: "LC 84/2024, art. 11, VI", url: LC84_URL }],
  "certidoes-ambientais": [
    { text: "LC 84/2024, art. 11, VII", url: LC84_URL },
    { text: "CETESB - Portal de Licenciamento Ambiental", url: CETESB_PORTAL_URL },
    { text: "CETESB - fator de complexidade da atividade", url: CETESB_FATOR_COMPLEXIDADE_URL },
    { text: "Decreto estadual 8.468/1976, art. 71", url: DEC8468_URL },
  ],
  "exames-agua": [{ text: "LC 84/2024, art. 11, VIII", url: LC84_URL }],
  "memorial-economico-sanitario": [
    { text: "LC 84/2024, art. 11, IX", url: LC84_URL },
    { text: "Decreto 5.374/2024, art. 2 (Anexo II - MTSE)", url: DEC5374_URL },
  ],
  "manual-bpf": [{ text: "LC 84/2024, art. 11, X", url: LC84_URL }],
  "registro-crmv": [
    { text: "LC 84/2024, art. 11, XI, se aplicavel", url: LC84_URL },
    { text: "Resolucao CFMV 1.177/2017", url: CFMV1177_URL },
  ],
  "comprovante-taxa": [
    { text: "LC 84/2024, art. 11, XII", url: LC84_URL },
    { text: "LC 104/2026, art. 3, par. unico (sem cobranca em 2026)", url: LC104_URL },
  ],
  "rotulos-produtos": [
    { text: "LC 84/2024, art. 15, I e II", url: LC84_URL },
    { text: "Decreto 5.374/2024, art. 4 (Anexo IV)", url: DEC5374_URL },
  ],
  "doc-responsavel-legal": [
    { text: "Documento de apoio: comprova quem assina o Anexo I e o termo de compromisso do Decreto 5.374/2024", url: DEC5374_URL },
  ],
  "art-responsavel-tecnico": [
    { text: "Decreto 5.374/2024, Anexos I e II, pedem identificacao do RT", url: DEC5374_URL },
    { text: "Resolucao CFMV 1.562/2023, art. 3", url: CFMV1562_URL },
  ],
};
const OFFICIAL_ANNEXES = [
  {
    documentId: "requerimento-assinado",
    number: "I",
    title: "Requerimento ao SIM - solicitação de atos",
    intro: "Preencha os dados no portal; eles serão reaproveitados nos próximos formulários.",
    destination: "Depois de assinado, envie neste mesmo item. Corresponde ao item 01 do checklist.",
    view: "establishment",
    formFocus: "anexo-i",
    printForm: "anexoI",
    page: 14,
  },
  {
    documentId: "memorial-economico-sanitario",
    number: "II",
    title: "Memorial Técnico-Sanitário do Estabelecimento - MTSE",
    intro: "Descreva instalações, produção, higiene e controles do estabelecimento.",
    destination: "A versão final assinada atende o item 09 do checklist. Não é necessário enviar outro rascunho.",
    view: "establishment",
    formFocus: "anexo-ii",
    printForm: "mtse",
    page: 16,
  },
  {
    documentId: "plantas-baixas",
    number: "III",
    title: "Memorial descritivo de construção ou reforma",
    intro: "Detalhe a construção ou reforma e reúna as plantas exigidas.",
    destination: "Envie o memorial assinado junto das plantas exigidas no item 02 do checklist.",
    view: "establishment",
    formFocus: "anexo-iii",
    printForm: "construction",
    page: 22,
  },
  {
    documentId: "rotulos-produtos",
    number: "IV",
    title: "Registro de rótulo e/ou produto de origem animal",
    intro: "Crie um formulário para cada produto e anexe o respectivo rótulo.",
    destination: "Obrigatório para cada produto: preencha um formulário e anexe o respectivo rótulo.",
    view: "products",
    formFocus: "",
    printForm: "",
    page: 24,
  },
];
const OFFICIAL_ANNEX_BY_DOCUMENT = new Map(OFFICIAL_ANNEXES.map((annex) => [annex.documentId, annex]));

// Opcoes/estruturas do Anexo IV. Declaradas antes de initialState porque a
// semente do produto ja usa defaultNutritionRows() no carregamento do modulo.
const PRODUCT_NATURE_OPTIONS = [
  "Registro de produto",
  "Registro de rotulo",
  "Alteracao de rotulo",
  "Alteracao de memorial descritivo",
  "Cancelamento de produto",
  "Cancelamento de rotulo",
];
const PRODUCT_LABEL_TYPE_OPTIONS = ["Impresso", "Etiqueta", "Litografado", "Gravado em relevo"];
const PRODUCT_PRIMARY_PACKAGE_OPTIONS = ["Plastico", "Lata", "Papel", "Embalagem natural"];
const NUTRITION_LABELS = [
  "Valor energetico (kcal)",
  "Carboidratos (g)",
  "Proteinas (g)",
  "Gorduras totais (g)",
  "Gorduras saturadas (g)",
  "Gorduras trans (g)",
  "Fibra alimentar (g)",
  "Sodio (mg)",
];
function defaultNutritionRows() {
  return NUTRITION_LABELS.map((label) => ({ label, qty: "", pct: "" }));
}

function blankRows(count, fields) {
  return Array.from({ length: count }, () => Object.fromEntries(fields.map((field) => [field, ""])));
}

const initialState = {
  role: "establishment",
  view: "dashboard",
  formFocus: "",
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
    cadastralChangeType: "",
    signaturePlaceDate: "",
    inspectorName: "",
    inspectorRegistration: "",
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
    smallBusiness: "Nao",
  },
  legalResponsible: {
    name: "Jose Francisco Guerra",
    cpf: "",
    email: "",
    phone: "",
    address: "",
    district: "",
    city: "Orlandia",
    state: "SP",
    zip: "",
  },
  technicalResponsible: {
    name: "",
    cpf: "",
    council: "",
    email: "",
    phone: "",
    address: "",
    district: "",
    city: "Orlandia",
    state: "SP",
    zip: "",
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
    activityRows: blankRows(5, ["number", "activity"]),
    productCapacityRows: blankRows(4, ["product", "temperature", "capacity"]),
    receivedProductRows: blankRows(4, ["product", "average"]),
    rawMaterialRows: blankRows(4, ["product", "manufacturer", "cnpj", "registration"]),
    employeeTotal: "",
    employeeMale: "",
    employeeFemale: "",
    laundryType: "",
    laundryCompany: "",
    laundryCnpj: "",
    alreadyBuilt: "",
    landTotalArea: "",
    landBuildArea: "",
    usefulArea: "",
    streetSetback: "",
    equipmentRows: blankRows(5, ["location", "equipment", "quantity", "material"]),
    productionScheduleRows: blankRows(6, ["day", "time"]),
    signaturePlaceDate: "",
  },
  construction: {
    requestReason: "",
    buildingDescription: "",
    rooms: "",
    materials: "",
    coldRooms: "",
    waterAndSewage: "",
    observations: "",
    locationArea: "",
    landTotalArea: "",
    landBuildArea: "",
    usefulArea: "",
    streetSetback: "",
    boundariesAccess: "",
    ceilingHeight: "",
    roof: "",
    ceilings: "",
    doorsWindowsExhaust: "",
    floorsBaseboards: "",
    walls: "",
    waterPiping: "",
    wastewater: "",
    heatColdIce: "",
    signaturePlaceDate: "",
  },
  products: [
    {
      id: crypto.randomUUID(),
      name: "Queijo / derivado lacteo a confirmar",
      brand: "Guerra Milk",
      status: "Rascunho",
      version: 1,
      previousVersionId: null,
      supersededBy: null,
      supersededAt: null,
      approvedAt: null,
      approvedBy: null,
      simNote: "",
      submittedAt: null,
      conservation: "Refrigerado",
      notes: "Denominacao e RTIQ precisam ser confirmados.",
      requestNature: "Registro de produto e rotulo",
      natureOptions: [],
      labelTypes: [],
      primaryPackagingTypes: [],
      otherLabelType: "",
      otherPrimaryPackagingType: "",
      dateLotIndication: "",
      packageQuantity: "",
      labelingPresentation: "",
      packageType: "",
      labelRegistration: "",
      labelFeatures: "",
      composition: "",
      compositionRows: [],
      nutrition: "",
      nutritionPortion: "",
      nutritionRows: defaultNutritionRows(),
      manufacturingProcess: "",
      packagingProcess: "",
      storageConditions: "",
      marketTransport: "",
      qualityControls: "",
      signaturePlaceDate: "",
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
    time: "",
    seizedDestination: "",
    aggravating: "",
    warningDeadlineDays: "",
    signaturePlaceDate: "",
    inspectorName: "Lucas Marcelino Campos Ferreira",
    inspectorRegistration: "",
    acknowledgedBy: "",
    acknowledgedDocument: "",
    witnessOneName: "",
    witnessOneDocument: "",
    witnessTwoName: "",
    witnessTwoDocument: "",
    infringementRows: blankRows(4, ["article", "item"]),
    seizedItemRows: blankRows(4, ["quantity", "unit", "description"]),
  },
  journey: {
    signedAck: false,
  },
  documents: [
    { id: "requerimento-assinado", item: "01", group: "art11", name: "Requerimento ao SIM solicitando o registro", hint: "Preencha a ficha no portal, imprima o Anexo I, assine no gov.br e envie aqui.", required: true, status: "Pendente", file: "", formView: "establishment", printForm: "anexoI" },
    { id: "plantas-baixas", item: "02", group: "art11", name: "Planta baixa ou croqui das construcoes/reformas + memorial descritivo da construcao", hint: "Preencha o Anexo III no portal. As plantas devem ser elaboradas por profissional habilitado e enviadas junto do memorial assinado.", required: true, status: "Pendente", file: "", formView: "establishment", printForm: "construction" },
    { id: "contrato-social-cnpj", item: "03", group: "art11", name: "Contrato ou estatuto social registrado, quando houver firma constituida", hint: "Junta Comercial (empresas) ou cartorio; MEI usa o Certificado CCMEI.", required: true, status: "Pendente", file: "" },
    { id: "cpf-cnpj", item: "04", group: "art11", name: "CPF ou CNPJ, conforme o caso", hint: "Cartao CNPJ: emissao gratuita no site da Receita Federal.", link: "https://solucoes.receita.fazenda.gov.br/servicos/cnpjreva/cnpjreva_solicitacao.asp", required: true, status: "Pendente", file: "" },
    { id: "inscricao-estadual", item: "05", group: "art11", name: "Inscricao estadual/ICMS ou inscricao de Produtor Rural", hint: "Consulte de graca no Cadesp/Sefaz-SP e anexe a tela; produtor rural usa a inscricao de produtor.", link: "https://www.cadesp.fazenda.sp.gov.br/Pages/Cadastro/Consultas/ConsultaPublica/ConsultaPublica.aspx?idServicoCarta=BDAB67E2-FE2D-44D7-8D19-2CDF9015E3A9", required: true, status: "Pendente", file: "" },
    { id: "alvara-prefeitura", item: "06", group: "art11", name: "Alvara de construcao e/ou localizacao e funcionamento", hint: "Emitido pela Prefeitura de Orlandia (setor de obras/tributos), ou documento equivalente.", required: true, status: "Pendente", file: "" },
    { id: "certidoes-ambientais", item: "07", group: "art11", name: "Licenca ambiental ou dispensa emitida pelo orgao ambiental", hint: "CETESB: para laticinios, consulte primeiro o portal de licenciamento. Se o enquadramento simplificado nao estiver disponivel, siga o fluxo indicado pela CETESB para Licenca de Operacao/MCE.", required: true, status: "Pendente", file: "" },
    { id: "exames-agua", item: "08", group: "art11", name: "Exames fisico-quimico e microbiologico da agua de abastecimento", hint: "Laboratorio credenciado; colete conforme orientacao do laboratorio.", required: true, status: "Pendente", file: "" },
    { id: "memorial-economico-sanitario", item: "09", group: "art11", name: "Anexo II (MTSE) final assinado - Memorial tecnico-sanitario do estabelecimento", hint: "Este e o memorial descritivo economico e sanitario exigido pela lei. Preencha o MTSE no portal, imprima/salve em PDF, assine e envie aqui. Nao envie rascunho separado.", required: true, status: "Pendente", file: "", formView: "establishment", printForm: "mtse" },
    { id: "manual-bpf", item: "10", group: "art11", name: "Manual de Boas Praticas de Fabricacao de Alimentos - BPF", hint: "Elaborado com o responsavel tecnico; descreve higiene, processos e controles do estabelecimento.", required: true, status: "Pendente", file: "" },
    { id: "registro-crmv", item: "11", group: "art11", name: "Registro do estabelecimento no CRMV-SP, se aplicavel", hint: "Confirme com o responsavel tecnico se a atividade exige registro no conselho.", required: false, status: "Pendente", file: "" },
    { id: "comprovante-taxa", item: "12", group: "art11", name: "Comprovante da Taxa de Inspecao Sanitaria", hint: "DISPENSADO em 2026: os servicos do art. 175-C sao prestados sem cobranca neste ano (LC 104/2026, art. 3, par. unico).", required: false, status: "Dispensado em 2026", file: "" },
    { id: "rotulos-produtos", group: "anexos", name: "Anexo IV - Rotulos e memoriais por produto", hint: "Clique em Preencher Anexo IV. Cadastre um formulario por produto e anexe o respectivo rotulo; os dados da empresa entram automaticamente.", required: false, status: "Pendente", file: "" },
    { id: "doc-responsavel-legal", group: "anexos", name: "Documento do responsavel legal (RG/CPF ou CNH)", hint: "Copia simples e legivel para confirmar quem assina o pedido e responde pelas declaracoes.", required: true, status: "Pendente", file: "" },
    { id: "art-responsavel-tecnico", group: "anexos", name: "ART ou contrato do responsavel tecnico", hint: "Comprova a responsabilidade tecnica informada nos formularios oficiais.", required: true, status: "Pendente", file: "" },
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
let previewAccount = null;
let registry = { accounts: [], establishments: [], fiscalActs: [], inspections: [], samples: [], audit: [] };
let registryEditing = { establishment: null, inspection: null, sample: null };
let fiscalActContext = { establishmentId: "", status: "Lavrado", scienceDate: "", loadedNumber: "" };
let state = loadState();
let persistQueue = Promise.resolve();

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
  if (!raw) return normalizeState(structuredClone(initialState));
  try {
    return normalizeState(deepMerge(structuredClone(initialState), JSON.parse(raw)));
  } catch {
    return normalizeState(structuredClone(initialState));
  }
}

function normalizeState(nextState) {
  if (!Array.isArray(nextState.documents)) nextState.documents = [];
  const currentById = new Map(nextState.documents.map((doc) => [doc.id, doc]));
  const knownIds = new Set(initialState.documents.map((doc) => doc.id));
  const internalDocs = nextState.documents.filter((doc) => doc.internal && !knownIds.has(doc.id));
  nextState.documents = initialState.documents.map((baseDoc) => {
    const currentDoc = currentById.get(baseDoc.id);
    return currentDoc ? deepMerge(structuredClone(baseDoc), currentDoc) : structuredClone(baseDoc);
  }).concat(internalDocs).filter((doc) => !["mtse", "planta-fluxo"].includes(doc.id));
  const mtse = nextState.documents.find((doc) => doc.id === "memorial-economico-sanitario");
  if (mtse) {
    mtse.name = initialState.documents.find((doc) => doc.id === "memorial-economico-sanitario")?.name || mtse.name;
    mtse.hint = initialState.documents.find((doc) => doc.id === "memorial-economico-sanitario")?.hint || mtse.hint;
    mtse.required = true;
    mtse.group = "art11";
    mtse.item = "09";
    mtse.formView = "establishment";
    mtse.printForm = "mtse";
  }
  if (!Array.isArray(nextState.products)) nextState.products = [];
  nextState.products = nextState.products.map((product) => {
    const normalized = {
      natureOptions: [],
      labelTypes: [],
      primaryPackagingTypes: [],
      otherLabelType: "",
      otherPrimaryPackagingType: "",
      dateLotIndication: "",
      packageQuantity: "",
      labelingPresentation: "",
      qualityControls: "",
      signaturePlaceDate: "",
      ...product,
    };
    if (!normalized.storageConditions && normalized.conservation) {
      normalized.storageConditions = normalized.conservation;
    }
    if (!normalized.otherPrimaryPackagingType && normalized.packageType) {
      normalized.otherPrimaryPackagingType = normalized.packageType;
    }
    if (!normalized.labelingPresentation && normalized.labelFeatures) {
      normalized.labelingPresentation = normalized.labelFeatures;
    }
    return normalized;
  });
  return nextState;
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
  if (previewAccount) return;
  state.protocol.updatedAt = new Date().toISOString();
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  persistState();
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  if (previewAccount && !["GET", "HEAD"].includes(method)) {
    throw new Error("A visualizacao de suporte e somente leitura.");
  }
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

function persistState() {
  if (!backendAvailable || !session) return;
  const snapshot = structuredClone(state);
  persistQueue = persistQueue
    .then(() => api("/state", { method: "POST", body: { state: snapshot } }))
    .catch((error) => console.warn(error));
}

async function bootstrap() {
  try {
    const sessionResponse = await api("/session");
    backendAvailable = true;
    session = sessionResponse.user;
    if (session) {
      const data = await api("/state");
      state = normalizeState(deepMerge(structuredClone(initialState), data.state));
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

function setView(view, formFocus = "") {
  state.view = view;
  if (view === "establishment") state.formFocus = formFocus;
  saveState();
  render();
  if (view === "establishment" && formFocus) {
    requestAnimationFrame(() => {
      document.querySelector(`#form-${formFocus}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
}

function update(path, value) {
  if (previewAccount) {
    toast("A visualizacao de suporte e somente leitura.");
    render();
    return;
  }
  const parts = path.split(".");
  let target = state;
  for (let i = 0; i < parts.length - 1; i += 1) {
    const key = parts[i];
    const nextKey = parts[i + 1];
    if (target[key] == null || typeof target[key] !== "object") {
      target[key] = /^\d+$/.test(nextKey) ? [] : {};
    }
    target = target[key];
  }
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
    ["accounts", "shield", "Contas"],
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
  if (previewAccount) {
    return `
      <div class="mode-switch">
        <label>Visualizacao de suporte</label>
        <div class="account-box">
          <strong>${escapeHtml(previewAccount.name)}</strong>
          <span>${escapeHtml(previewAccount.email)}</span>
          <span>Somente leitura</span>
        </div>
        <button class="btn ghost" data-exit-preview>Voltar para minha conta</button>
      </div>
    `;
  }
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
    accounts: "Contas do Portal SIM",
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
  // So conta como feito com nome real (nao o placeholder da semente) e rotulo anexado;
  // um nome preenchido sozinho nao significa que o produto esteja pronto.
  const productsDone = visibleProducts().some((product) => {
    const hasRealName = (product.name || "").trim() && product.name !== "Queijo / derivado lacteo a confirmar";
    return hasRealName && Boolean(product.labelUploadId);
  });
  const docs = art11Progress();
  const docsDone = docs.total > 0 && docs.sent === docs.total;
  const signDone = Boolean(state.journey?.signedAck);
  const submitted = ["review", "approved"].includes(state.protocol.status);
  const approved = state.protocol.status === "approved";
  return [
    { id: "ficha", title: "Preencher a ficha do estabelecimento", desc: "Dados da empresa, responsavel legal e responsavel tecnico. Preencha uma vez; o portal reaproveita em todos os formularios.", done: fichaDone, view: "establishment", formFocus: "anexo-i", cta: "Abrir ficha" },
    { id: "mtse", title: "Descrever a producao (Memorial/MTSE)", desc: "Atividades, capacidade, agua, higiene e fluxo. Atende o item 09 do checklist.", done: mtseDone, view: "establishment", formFocus: "anexo-ii", cta: "Preencher memorial" },
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
            : `<button class="btn primary" data-view="${current.view}" ${current.formFocus ? `data-form-focus="${current.formFocus}"` : ""}>${current.cta}</button>`}
        </div>
      ` : `
        <div class="next-action done">
          <div><strong>Tudo certo por aqui!</strong><span>Seu processo foi aprovado pelo SIM.</span></div>
        </div>
      `}
      <div class="journey-steps">
        ${steps.map((step, index) => `
          <button class="journey-step ${step.done ? "done" : ""} ${current && step.id === current.id ? "current" : ""}" data-view="${step.view}" ${step.formFocus ? `data-form-focus="${step.formFocus}"` : ""}>
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
  const focusedAnnex = OFFICIAL_ANNEXES.find((annex) => annex.formFocus === state.formFocus);
  const focusedBanner = focusedAnnex ? `
    <div class="span-12 annex-focus-banner">
      <div>
        <strong>Preenchendo o Anexo ${focusedAnnex.number}</strong>
        <span>${focusedAnnex.title}. Os dados comuns da empresa sao reaproveitados automaticamente.</span>
      </div>
      <div class="doc-quick-actions">
        ${focusedAnnex.printForm ? `<button class="btn primary" data-view="print" data-print-form="${focusedAnnex.printForm}">${icon("print")}Gerar para assinar</button>` : ""}
        <a class="btn" href="${DEC5374_URL}#page=${focusedAnnex.page}" target="_blank" rel="noreferrer">${icon("file")}Ver modelo oficial</a>
      </div>
    </div>
  ` : "";
  return `
    <div class="grid">
      ${focusedBanner}
      <div class="span-8 panel form-anchor" id="form-anexo-i">
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
          ${selectInput("establishment.propertyLink", "Tipo de vinculo com o imovel", ["Proprietario", "Locatario", "Outro"], { owner: "establishment" })}
          ${selectInput("establishment.smallBusiness", "Estabelecimento Agroindustrial de Pequeno Porte?", ["Nao", "Sim"], { owner: "establishment" })}
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
          ${input("legalResponsible.address", "Endereco residencial", { full: true, owner: "establishment" })}
          ${input("legalResponsible.district", "Bairro", { owner: "establishment" })}
          ${input("legalResponsible.city", "Cidade", { owner: "establishment" })}
          ${input("legalResponsible.state", "UF", { owner: "establishment" })}
          ${input("legalResponsible.zip", "CEP", { owner: "establishment" })}
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
          ${input("technicalResponsible.address", "Endereco residencial", { full: true, owner: "establishment" })}
          ${input("technicalResponsible.district", "Bairro", { owner: "establishment" })}
          ${input("technicalResponsible.city", "Cidade", { owner: "establishment" })}
          ${input("technicalResponsible.state", "UF", { owner: "establishment" })}
          ${input("technicalResponsible.zip", "CEP", { owner: "establishment" })}
        </div>
      </div>
      <div class="span-12 panel">
        <div class="panel-header"><h2>Anexo I - Tipo de solicitacao e compromisso</h2></div>
        <div class="form-grid">
          ${selectInput("application.actType", "Tipo de solicitacao", [
            "Registro de estabelecimento",
            "Renovacao do titulo de registro",
            "Reforma ou ampliacao",
            "Transferencia cadastral",
            "Solicitacao de vistoria in loco",
            "Paralisacao das atividades",
            "Reinicio das atividades",
            "Cancelamento do registro",
            "Alteracao cadastral",
            "Outro ato"
          ], { owner: "establishment" })}
          ${input("application.otherAct", "Outro ato / complemento", { owner: "establishment" })}
          ${selectInput("application.cadastralChangeType", "Tipo de alteracao cadastral (se aplicavel)", [
            "",
            "Alteracao de CNPJ",
            "Alteracao de razao social",
            "Classificacao do estabelecimento",
            "Alteracao do endereco",
            "Alteracao de responsavel tecnico"
          ], { owner: "establishment" })}
          ${input("application.commitment", "Termo de compromisso", { textarea: true, full: true, owner: "establishment" })}
        </div>
      </div>
      <div class="span-12 panel form-anchor" id="form-anexo-ii">
        <div class="panel-header"><h2>Anexo II - Memorial tecnico-sanitario do estabelecimento</h2></div>
        <div class="form-grid">
          ${input("production.activities", "Lista de atividades gerais", { textarea: true, owner: "establishment" })}
          ${input("production.monthlyCapacity", "Produtos e capacidade mensal", { textarea: true, owner: "establishment" })}
          ${input("production.rawMaterialOrigin", "Origem da materia-prima e rastreamento", { textarea: true, owner: "establishment" })}
          ${input("production.employees", "Funcionarios", { textarea: true, owner: "establishment" })}
          ${input("production.laundry", "Lavanderia", { textarea: true, owner: "establishment" })}
          ${input("production.landDetails", "Detalhes do terreno", { textarea: true, owner: "establishment" })}
          ${input("production.locationArea", "Area de localizacao", { textarea: true, owner: "establishment" })}
          ${input("production.flow", "12. Disposicao das instalacoes e fluxo de producao", { textarea: true, owner: "establishment" })}
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
      <div class="span-12 panel form-anchor" id="form-anexo-iii">
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
  const visibleDocuments = (state.documents || []).filter((doc) => doc.id !== "mtse");
  const art11 = visibleDocuments.filter((doc) => doc.group === "art11");
  const officialDocumentIds = new Set(OFFICIAL_ANNEXES.map((annex) => annex.documentId));
  const officialDocuments = OFFICIAL_ANNEXES.map((annex) => ({
    annex,
    doc: visibleDocuments.find((doc) => doc.id === annex.documentId),
  })).filter((item) => item.doc);
  const remainingArt11 = art11.filter((doc) => !officialDocumentIds.has(doc.id));
  const anexos = visibleDocuments.filter((doc) => !doc.internal && doc.group !== "art11" && !officialDocumentIds.has(doc.id));
  const internalDocs = visibleDocuments.filter((doc) => doc.internal);
  const progress = art11Progress();
  const percent = progress.total ? Math.round((progress.sent / progress.total) * 100) : 0;
  return `
    <div class="grid">
      <div class="span-12 banner-warn">
        <strong>Taxa do SIM em 2026: nao e preciso pagar nada.</strong>
        A Taxa de Inspecao Sanitaria esta dispensada neste ano (LC 104/2026, art. 3, par. unico). O item 12 do checklist fica sem exigencia em 2026.
      </div>
      <div class="span-12 banner-warn legal-why">
        <strong>Por que pedimos estes documentos?</strong>
        Cada item abaixo mostra a fonte legal usada pelo SIM. O objetivo e cumprir a LC 84/2024 e os formularios oficiais do Decreto 5.374/2024, sem criar exigencia duplicada para o produtor. Itens com * sao obrigatorios; os condicionais informam quando se aplicam.
      </div>
      <section class="span-12 official-annex-section">
        <div class="official-annex-header">
          <div>
            <h2>Formulários oficiais, na ordem</h2>
            <p>Comece por aqui. Preencha no portal, confira com o modelo publicado pela Prefeitura, gere o documento, assine e envie no próprio item.</p>
          </div>
          <span class="annex-law">Decreto 5.374/2024</span>
        </div>
        <div class="official-annex-list">
          ${officialDocuments.map(({ annex, doc }) => documentCard(doc, { annex })).join("")}
        </div>
      </section>
      <div class="span-12 panel document-support-panel">
        <section class="document-support-block">
          <div class="panel-header"><h2>Assine de graça no gov.br</h2></div>
          <ol class="signer-steps">
            <li>Imprima os formulários do portal em PDF.</li>
            <li>Assine gratuitamente com sua conta gov.br prata ou ouro.</li>
            <li>Volte ao item correspondente e envie o PDF assinado.</li>
          </ol>
          <a class="btn primary" href="${GOVBR_SIGNER_URL}" target="_blank" rel="noreferrer">Abrir assinador gov.br</a>
          ${state.role === "establishment" ? `
            <label class="check-item document-support-check">
              <input type="checkbox" data-journey-signed ${state.journey?.signedAck ? "checked" : ""}>
              <span>Já assinei meus documentos no gov.br</span>
            </label>
          ` : ""}
        </section>
        <section class="document-support-block">
          <div class="panel-header"><h2>Rastreabilidade</h2></div>
          <p class="muted small">Cada envio registra conta, horário, tamanho e hash SHA-256. Uma nova versão nunca apaga a anterior.</p>
          <div class="support-feature">
            ${icon("shield")}
            <span><strong>Envio protegido</strong>Arquivos e responsáveis ficam identificados no processo.</span>
          </div>
        </section>
        <section class="document-support-block">
          <div class="panel-header"><h2>Histórico recente</h2></div>
          <div class="timeline compact">
            ${(state.stateHistory || []).slice(0, 4).map((item) => `
              <div class="event"><div><strong>${item.reason}</strong><span>${item.changed_by_name} - ${formatDate(item.changed_at)}</span></div></div>
            `).join("") || `<p class="muted small">As alterações aparecerão aqui.</p>`}
          </div>
        </section>
      </div>
      <div class="span-12 panel registry-documents-panel">
        <div class="panel-header">
          <div><h2>Demais documentos do registro</h2>
          <p class="muted">${state.role === "sim" ? "O SIM confere documentos e define o status." : `Os Anexos I, II e III ja estao acima. Complete aqui os demais documentos do art. 11 da LC 84/2024. O progresso ${progress.sent}/${progress.total} considera todos os obrigatorios.`}</p></div>
          <span class="journey-score">${progress.sent}/${progress.total}</span>
        </div>
        <div class="progress-track"><div class="progress-fill" style="width:${percent}%"></div></div>
        <div class="document-group">
          ${remainingArt11.map(documentCard).join("")}
        </div>
        <div class="document-group">
          <h3>Comprovantes complementares</h3>
          <p class="muted small">Estes itens nao duplicam os formularios oficiais. Eles confirmam a identidade de quem assina e a responsabilidade tecnica informada no processo.</p>
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
    </div>
  `;
}

function documentCard(doc, options = {}) {
  const versions = doc.versions || [];
  const canUpload = backendAvailable && (state.role === "sim" || !doc.internal);
  const isTaxWaived = doc.id === "comprovante-taxa";
  const isProductForm = doc.id === "rotulos-produtos";
  const annex = options.annex || OFFICIAL_ANNEX_BY_DOCUMENT.get(doc.id);
  const products = isProductForm ? visibleProducts() : [];
  const received = docReceived(doc);
  if (annex) {
    return officialAnnexCard(doc, annex, {
      versions,
      canUpload,
      isProductForm,
      products,
      received,
    });
  }
  return registryDocumentCard(doc, {
    versions,
    canUpload,
    isTaxWaived,
    received,
  });
}

function registryDocumentCard(doc, context) {
  const { versions, canUpload, isTaxWaived, received } = context;
  const statusTone = received || isTaxWaived
    ? "approved"
    : (/corre/i.test(doc.status || "") ? "corrections" : "pending");
  const statusText = isTaxWaived ? "Dispensado em 2026" : (received ? "Recebido" : (doc.status || "Pendente"));
  const category = doc.internal
    ? "Documento interno do SIM"
    : (doc.item ? `Item ${doc.item} do checklist` : "Documento complementar");
  const obligation = doc.required ? "obrigatório" : "quando aplicável";
  const historyDetails = isTaxWaived ? "" : `
    <details class="annex-details">
      <summary>
        <span>Histórico de arquivos</span>
        <span class="annex-details-count">${versions.length}</span>
      </summary>
      <div class="annex-history">
        ${versions.length ? versions.map((version) => `
          <div class="annex-history-row">
            <div>
              <strong>v${version.versionNo} · ${escapeHtml(version.file)}</strong>
              <span>${escapeHtml(version.uploadedBy)} · ${formatDate(version.uploadedAt)} · ${formatBytes(version.sizeBytes)} · SHA-256 ${version.sha256.slice(0, 16)}...</span>
            </div>
            <div class="annex-file-actions">
              <button class="btn" data-open-upload="${version.id}">Abrir</button>
              <a class="btn" href="${downloadUrl(version.id)}" download="${escapeHtml(version.file || "")}">Baixar</a>
            </div>
          </div>
        `).join("") : `<div class="empty small">O histórico aparecerá depois do primeiro envio.</div>`}
      </div>
    </details>
  `;
  return `
    <article class="document-card registry-document ${doc.internal ? "internal" : ""} ${doc.required ? "required" : ""} ${received ? "received" : ""}">
      <header class="registry-card-head">
        <div class="registry-card-identity">
          <span class="registry-document-number">${received ? icon("check") : (doc.item || icon("file"))}</span>
          <div>
            <span class="registry-card-kicker">${category} · ${obligation}</span>
            <h3>${doc.name}</h3>
          </div>
        </div>
        <div class="annex-card-status">
          ${state.role === "sim" ? `
            <label>
              <span>Status do SIM</span>
              <select data-doc="${doc.id}">
                ${["Pendente", "Em correcao", "Recebido", "Interno", "Dispensado em 2026"].map((status) => `<option ${doc.status === status ? "selected" : ""}>${status}</option>`).join("")}
              </select>
            </label>
          ` : `<span class="status ${statusTone}">${statusText}</span>`}
        </div>
      </header>
      <p class="registry-card-intro">${doc.hint || "Confira a orientação, envie o arquivo e acompanhe a conferência pelo SIM."}</p>

      <div class="registry-flow" aria-label="Etapas de ${doc.name}">
        <section class="annex-flow-step">
          <span class="annex-step-number">1</span>
          <div class="annex-step-copy">
            <span class="annex-step-kicker">Preparar</span>
            <strong>${isTaxWaived ? "Nenhuma providência necessária" : "Separe o documento correto"}</strong>
            <p>${isTaxWaived ? "A taxa de inspeção sanitária está dispensada durante 2026." : "Confira se o arquivo está atualizado, completo e legível."}</p>
          </div>
          <div class="annex-step-actions">
            ${doc.link ? `<a class="btn" href="${doc.link}" target="_blank" rel="noreferrer">${icon("file")}Abrir site oficial</a>` : ""}
          </div>
        </section>

        <section class="annex-flow-step ${received ? "is-complete" : ""}">
          <span class="annex-step-number">${received ? icon("check") : "2"}</span>
          <div class="annex-step-copy">
            <span class="annex-step-kicker">${received ? "Enviado" : "Enviar"}</span>
            <strong>${isTaxWaived ? "Envio dispensado" : (received ? "Arquivo recebido" : "Envie o arquivo")}</strong>
            <p>${isTaxWaived ? "O item permanece no checklist apenas para registrar a dispensa legal." : (received ? "Se algo mudar, envie uma nova versão por aqui." : "A seleção do arquivo inicia o envio automaticamente.")}</p>
          </div>
          <div class="annex-step-actions">
            ${canUpload && !isTaxWaived ? `
              <label class="btn annex-upload-button">
                ${icon("send")}<span>${received ? "Enviar nova versão" : "Selecionar e enviar"}</span>
                <input type="file" data-upload-doc="${doc.id}" aria-label="Enviar ${doc.name}">
              </label>
            ` : ""}
          </div>
        </section>

        <section class="annex-flow-step ${received || isTaxWaived ? "is-complete" : ""}">
          <span class="annex-step-number">${received || isTaxWaived ? icon("check") : "3"}</span>
          <div class="annex-step-copy">
            <span class="annex-step-kicker">Acompanhar</span>
            <strong>${isTaxWaived ? "Item regularizado" : (received ? escapeHtml(doc.file || "Documento enviado") : "Aguardando envio")}</strong>
            <p class="registry-file-summary">${isTaxWaived ? "Dispensado pela LC 104/2026." : escapeHtml(documentSummary(doc))}</p>
          </div>
          <div class="annex-step-actions">
            ${doc.uploadId ? `
              <button class="btn" data-open-upload="${doc.uploadId}">Abrir atual</button>
              <a class="btn" href="${downloadUrl(doc.uploadId)}" download="${escapeHtml(doc.file || "")}">Baixar</a>
            ` : ""}
          </div>
        </section>
      </div>

      <div class="annex-card-details-grid">
        <details class="annex-details">
          <summary><span>Orientações e base legal</span></summary>
          <div class="annex-details-content">
            <p>${doc.hint || "Documento utilizado na instrução do processo de registro."}</p>
            ${documentSourceHtml(doc)}
            ${documentExtraHtml(doc)}
          </div>
        </details>
        ${historyDetails}
      </div>
    </article>
  `;
}

function officialAnnexCard(doc, annex, context) {
  const { versions, canUpload, isProductForm, products, received } = context;
  const statusTone = received
    ? "approved"
    : (/corre/i.test(doc.status || "") ? "corrections" : "pending");
  const statusText = received ? "Documento enviado" : (doc.status || "Pendente");
  const productCount = `${products.length} ${products.length === 1 ? "produto cadastrado" : "produtos cadastrados"}`;
  const currentFile = !isProductForm && doc.uploadId ? `
    <div class="annex-current-file">
      <div class="annex-current-file-icon">${icon("check")}</div>
      <div>
        <span>Último envio</span>
        <strong>${escapeHtml(doc.file || "Documento enviado")}</strong>
        <small>${escapeHtml(documentSummary(doc))}</small>
      </div>
      <div class="annex-file-actions">
        <button class="btn" data-open-upload="${doc.uploadId}">Abrir</button>
        <a class="btn" href="${downloadUrl(doc.uploadId)}" download="${escapeHtml(doc.file || "")}">Baixar</a>
      </div>
    </div>
  ` : `
    <div class="annex-current-file empty-state">
      <div class="annex-current-file-icon">${icon(isProductForm ? "file" : "send")}</div>
      <div>
        <span>${isProductForm ? "Produtos e rótulos" : "Envio"}</span>
        <strong>${isProductForm ? productCount : "Nenhum documento enviado"}</strong>
        <small>${isProductForm ? "O Anexo IV é gerado individualmente na área de produtos." : "Depois de assinar, selecione o PDF na etapa 3."}</small>
      </div>
    </div>
  `;
  const legalDetails = `
    <details class="annex-details">
      <summary>
        <span>Base legal e orientação de envio</span>
      </summary>
      <div class="annex-details-content">
        <p>${annex.destination}</p>
        ${documentSourceHtml(doc)}
        ${documentExtraHtml(doc)}
      </div>
    </details>
  `;
  const historyDetails = isProductForm ? "" : `
    <details class="annex-details">
      <summary>
        <span>Histórico de arquivos</span>
        <span class="annex-details-count">${versions.length}</span>
      </summary>
      <div class="annex-history">
        ${versions.length ? versions.map((version) => `
          <div class="annex-history-row">
            <div>
              <strong>v${version.versionNo} · ${escapeHtml(version.file)}</strong>
              <span>${escapeHtml(version.uploadedBy)} · ${formatDate(version.uploadedAt)} · ${formatBytes(version.sizeBytes)} · SHA-256 ${version.sha256.slice(0, 16)}...</span>
            </div>
            <div class="annex-file-actions">
              <button class="btn" data-open-upload="${version.id}">Abrir</button>
              <a class="btn" href="${downloadUrl(version.id)}" download="${escapeHtml(version.file || "")}">Baixar</a>
            </div>
          </div>
        `).join("") : `<div class="empty small">O histórico aparecerá depois do primeiro envio.</div>`}
      </div>
    </details>
  `;
  return `
    <article class="document-card official-annex ${received ? "received" : ""}">
      <header class="annex-card-head">
        <div class="annex-card-identity">
          <span class="official-annex-number">${received ? icon("check") : annex.number}</span>
          <div>
            <span class="annex-card-kicker">Anexo ${annex.number}${doc.required ? " · obrigatório" : ""}</span>
            <h3>${annex.title}</h3>
          </div>
        </div>
        <div class="annex-card-status">
          ${state.role === "sim" && !isProductForm ? `
            <label>
              <span>Status do SIM</span>
              <select data-doc="${doc.id}">
                ${["Pendente", "Em correcao", "Recebido", "Interno", "Dispensado em 2026"].map((status) => `<option ${doc.status === status ? "selected" : ""}>${status}</option>`).join("")}
              </select>
            </label>
          ` : `<span class="status ${statusTone}">${statusText}</span>`}
        </div>
      </header>
      <p class="annex-card-intro">${annex.intro || doc.hint || annex.destination}</p>

      <div class="annex-flow" aria-label="Etapas do Anexo ${annex.number}">
        <section class="annex-flow-step">
          <span class="annex-step-number">1</span>
          <div class="annex-step-copy">
            <span class="annex-step-kicker">${isProductForm ? "Cadastrar" : "Preparar"}</span>
            <strong>${isProductForm ? "Cadastre cada produto" : `Preencha o Anexo ${annex.number}`}</strong>
            <p>${isProductForm ? "Informe composição, processo e apresentação do rótulo." : "Os dados já cadastrados são reaproveitados automaticamente."}</p>
          </div>
          <div class="annex-step-actions">
            <button class="btn primary" data-view="${annex.view}" ${annex.formFocus ? `data-form-focus="${annex.formFocus}"` : ""}>${icon("file")}${isProductForm ? "Abrir produtos" : "Começar preenchimento"}</button>
            <a class="annex-text-link" href="${DEC5374_URL}#page=${annex.page}" target="_blank" rel="noreferrer">Consultar modelo oficial</a>
          </div>
        </section>

        <section class="annex-flow-step">
          <span class="annex-step-number">2</span>
          <div class="annex-step-copy">
            <span class="annex-step-kicker">${isProductForm ? "Finalizar" : "Revisar e assinar"}</span>
            <strong>${isProductForm ? "Gere um formulário por produto" : "Gere o documento final"}</strong>
            <p>${isProductForm ? "Cada produto terá seu próprio Anexo IV e respectivo rótulo." : "Confira o conteúdo, salve o PDF e assine gratuitamente pelo gov.br."}</p>
          </div>
          <div class="annex-step-actions">
            ${annex.printForm
              ? `<button class="btn" data-view="print" data-print-form="${annex.printForm}">${icon("print")}Gerar para assinar</button>`
              : `<button class="btn" data-view="${annex.view}">${icon("print")}Gerar por produto</button>`}
          </div>
        </section>

        <section class="annex-flow-step ${received ? "is-complete" : ""}">
          <span class="annex-step-number">${received ? icon("check") : "3"}</span>
          <div class="annex-step-copy">
            <span class="annex-step-kicker">${received ? "Concluído" : "Enviar"}</span>
            <strong>${isProductForm ? "Anexe o rótulo de cada produto" : (received ? "Documento recebido" : "Envie o PDF assinado")}</strong>
            <p>${isProductForm ? "O envio do rótulo acontece dentro do cadastro do produto." : (received ? "Você pode abrir o arquivo ou enviar uma nova versão." : "A seleção do arquivo já inicia o envio com rastreabilidade.")}</p>
          </div>
          <div class="annex-step-actions">
            ${isProductForm
              ? `<button class="btn" data-view="products">${icon("send")}Gerenciar rótulos</button>`
              : (canUpload ? `
                <label class="btn annex-upload-button">
                  ${icon("send")}<span>${received ? "Enviar nova versão" : "Selecionar e enviar PDF"}</span>
                  <input type="file" accept=".pdf,image/*" data-upload-doc="${doc.id}" aria-label="Enviar ${doc.name}">
                </label>
              ` : "")}
          </div>
        </section>
      </div>

      ${currentFile}
      <div class="annex-card-details-grid">
        ${legalDetails}
        ${historyDetails}
      </div>
    </article>
  `;
}

function documentSourceHtml(doc) {
  const sources = DOCUMENT_SOURCES[doc.id] || doc.sources || [];
  if (!sources.length) return "";
  return `<span class="doc-source"><strong>Fonte:</strong> ${sources.map((source) => (
    source.url
      ? `<a href="${source.url}" target="_blank" rel="noreferrer">${escapeHtml(source.text)}</a>`
      : escapeHtml(source.text)
  )).join(" + ")}</span>`;
}

function documentExtraHtml(doc) {
  if (doc.id !== "certidoes-ambientais") return "";
  return `
    <div class="doc-guidance">
      <strong>Roteiro CETESB para laticinios</strong>
      <ol>
        <li>Entre no portal e tente o licenciamento ambiental pelo servico disponivel para a atividade.</li>
        <li>Se o sistema permitir o enquadramento simplificado, salve a licenca ou dispensa emitida e envie neste item.</li>
        <li>Se o sistema nao permitir, siga a orientacao da CETESB para Licenca de Operacao/MCE e anexe o protocolo ou a licenca emitida.</li>
        <li>Quando ja houver historico CETESB, anexe tambem a consulta do processo para facilitar a analise.</li>
      </ol>
      <p>A atividade "fabricacao de produtos do laticinio" aparece na tabela da CETESB com fator de complexidade 3,0. Pelo Decreto estadual 8.468/1976, art. 71, atividades com W = 3 tem Licenca de Operacao com validade de 3 anos. Por isso, uma LO antiga precisa ser conferida ou renovada antes do registro no SIM.</p>
      <p class="doc-guidance-links">
        <a href="${CETESB_PORTAL_URL}" target="_blank" rel="noreferrer">Abrir portal CETESB</a>
        <a href="${CETESB_PROCESSO_GUERRA_URL}" target="_blank" rel="noreferrer">Ver exemplo do processo Guerra Milk</a>
      </p>
    </div>
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
  for (const product of state.products || []) {
    for (const version of product.labelVersions || []) {
      if (version.id === uploadId) return { ...version, documentName: `Rotulo - ${product.name || "produto"}`, internal: false };
    }
  }
  return null;
}

function downloadUrl(uploadId) {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? `${API_ROOT}/uploads/${uploadId}?token=${encodeURIComponent(token)}` : `${API_ROOT}/uploads/${uploadId}`;
}

// URL do formulário Word editável, com a mesma estrutura da via impressa.
// A via oficial continua sendo o PDF assinado.
function docxUrl(form) {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? `${API_ROOT}/forms/${form}.docx?token=${encodeURIComponent(token)}` : `${API_ROOT}/forms/${form}.docx`;
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
          <a class="btn" href="${downloadUrl(upload.id)}" target="_blank" rel="noreferrer">Abrir em nova aba</a>
          <a class="btn primary" href="${downloadUrl(upload.id)}" download="${escapeHtml(upload.file || "")}">Baixar arquivo original</a>
        </div>
        <iframe class="upload-preview" src="${downloadUrl(upload.id)}" title="Previa do anexo ${upload.file}"></iframe>
        <p class="small muted">Se a previa nao aparecer (ex.: .doc/.docx), use "Abrir em nova aba" ou baixe o arquivo.</p>
      </section>
    </div>
  `;
}

// Uma vez aprovado, o produto fica travado para edicao: qualquer alteracao
// precisa abrir uma nova versao (novo processo de analise), preservando a
// versao aprovada intacta e auditavel no historico.
function isProductLocked(product) {
  return product.status === "Aprovado" || Boolean(product.supersededBy);
}

function visibleProducts() {
  // Historico de versoes superadas fica disponivel, mas fora da lista principal.
  return state.products.filter((product) => !product.supersededBy);
}

function renderProducts() {
  const current = visibleProducts();
  const history = state.products.filter((product) => product.supersededBy);
  return `
    <div class="grid">
      <div class="span-12 panel">
        <div class="panel-header">
          <div>
            <h2>Anexo IV - produtos e rotulos</h2>
            <p class="muted">Preencha um cadastro por produto. O portal inclui automaticamente os dados da empresa e monta o formulario oficial para assinatura.</p>
            <a class="source-link" href="${DEC5374_URL}#page=24" target="_blank" rel="noreferrer">Modelo oficial - Decreto 5.374/2024, paginas 24 a 26</a>
          </div>
          ${state.role === "establishment" ? `<button class="btn primary" data-action="add-product">Adicionar produto</button>` : ""}
        </div>
        <div class="product-list">
          ${current.length ? current.map((product) => productEditor(product)).join("") : `<p class="muted small">Nenhum produto cadastrado ainda.</p>`}
        </div>
      </div>
      ${history.length ? `
        <div class="span-12 panel">
          <div class="panel-header"><h2>Historico de versoes anteriores</h2><p class="muted">Somente leitura - preservado para auditoria.</p></div>
          <div class="product-list">
            ${history.map((product) => productEditor(product, { readOnlyHistory: true })).join("")}
          </div>
        </div>
      ` : ""}
    </div>
  `;
}

function productField(product, field, label, opts = {}) {
  const value = product[field] ?? "";
  const locked = state.role !== "establishment" || isProductLocked(product) || opts.readOnlyHistory;
  const control = opts.textarea
    ? `<textarea data-product="${product.id}" data-field="${field}" ${locked ? "disabled" : ""}>${value}</textarea>`
    : `<input data-product="${product.id}" data-field="${field}" value="${escapeHtml(value)}" ${locked ? "disabled" : ""}>`;
  return `<div class="${opts.full ? "field full" : "field"}"><label>${label}<span>Estabelecimento</span></label>${control}</div>`;
}

function productLabelCard(product, locked) {
  const canUpload = backendAvailable && state.role === "establishment" && !locked;
  const hasLabel = Boolean(product.labelUploadId);
  return `
    <div class="label-upload ${hasLabel ? "has-file" : "missing"}">
      <div>
        <strong>Rotulo do produto${hasLabel ? "" : " - pendente"}</strong>
        ${hasLabel
          ? `<span>v${product.labelVersionNo} - ${product.labelFile} - ${product.labelUploadedBy} - ${formatDate(product.labelUploadedAt)} - SHA-256 ${product.labelSha256.slice(0, 16)}...</span>`
          : `<span>Envie a foto ou o PDF do rotulo/embalagem deste produto (obrigatorio para enviar ao SIM).</span>`}
      </div>
      <div class="upload-controls">
        ${canUpload ? `<input type="file" accept="image/*,.pdf" data-upload-doc="${PRODUCT_LABEL_PREFIX}${product.id}" aria-label="Enviar rotulo de ${product.name || "produto"}">` : ""}
        ${hasLabel ? `<button class="btn" data-open-upload="${product.labelUploadId}">Abrir</button>` : ""}
        ${hasLabel ? `<a class="btn" href="${downloadUrl(product.labelUploadId)}" download="${escapeHtml(product.labelFile || "")}">Baixar</a>` : ""}
      </div>
    </div>
  `;
}

// Natureza da solicitacao do Anexo IV: checkboxes (multi) em vez de texto livre.
// Compatibilidade: se natureOptions ainda nao existe mas ha texto legado em
// requestNature, ele aparece como observacao para nao perder o dado.
function productNatureBlock(product, locked) {
  const selected = product.natureOptions || [];
  const legacy = !selected.length && product.requestNature ? product.requestNature : "";
  return `
    <div class="struct-block">
      <label class="struct-label">5. Natureza da solicitacao</label>
      <div class="check-grid">
        ${PRODUCT_NATURE_OPTIONS.map((opt) => `
          <label class="check-item">
            <input type="checkbox" data-pnature="${product.id}" value="${escapeHtml(opt)}" ${selected.includes(opt) ? "checked" : ""} ${locked ? "disabled" : ""}>
            <span>${opt}</span>
          </label>
        `).join("")}
      </div>
      ${legacy ? `<p class="small muted">Registro anterior: ${escapeHtml(legacy)}</p>` : ""}
    </div>
  `;
}

function productOptionBlock(product, field, label, options, locked) {
  const selected = Array.isArray(product[field]) ? product[field] : [];
  return `
    <div class="struct-block">
      <label class="struct-label">${label}</label>
      <div class="check-grid">
        ${options.map((option) => `
          <label class="check-item">
            <input type="checkbox" data-poption="${product.id}" data-poption-field="${field}" value="${escapeHtml(option)}" ${selected.includes(option) ? "checked" : ""} ${locked ? "disabled" : ""}>
            <span>${option}</span>
          </label>
        `).join("")}
      </div>
    </div>
  `;
}

// Composicao do produto: tabela dinamica (materia-prima, kg/L, %).
function productCompositionBlock(product, locked) {
  const rows = product.compositionRows || [];
  const legacy = !rows.length && product.composition ? product.composition : "";
  return `
    <div class="struct-block">
      <label class="struct-label">7. Composicao do produto</label>
      <table class="struct-table">
        <thead><tr><th>Tipo</th><th>Materia-prima / ingrediente</th><th class="num">kg ou L</th><th class="num">%</th><th></th></tr></thead>
        <tbody>
          ${rows.length ? rows.map((row) => `
            <tr>
              <td>
                <select data-pcomp="${product.id}" data-cid="${row.id}" data-cfield="kind" ${locked ? "disabled" : ""}>
                  ${["Materia-prima", "Ingrediente"].map((kind) => `<option ${kind === (row.kind || "Materia-prima") ? "selected" : ""}>${kind}</option>`).join("")}
                </select>
              </td>
              <td><input data-pcomp="${product.id}" data-cid="${row.id}" data-cfield="ingredient" value="${escapeHtml(row.ingredient || "")}" ${locked ? "disabled" : ""}></td>
              <td><input class="num" data-pcomp="${product.id}" data-cid="${row.id}" data-cfield="amount" value="${escapeHtml(row.amount || "")}" ${locked ? "disabled" : ""}></td>
              <td><input class="num" data-pcomp="${product.id}" data-cid="${row.id}" data-cfield="pct" value="${escapeHtml(row.pct || "")}" ${locked ? "disabled" : ""}></td>
              <td>${locked ? "" : `<button class="btn danger btn-mini" data-product-action="del-comp-row" data-product-id="${product.id}" data-row-id="${row.id}">Remover</button>`}</td>
            </tr>
          `).join("") : `<tr><td colspan="5" class="empty small">Nenhuma materia-prima ou ingrediente informado.</td></tr>`}
        </tbody>
      </table>
      ${locked ? "" : `<button class="btn btn-mini" data-product-action="add-comp-row" data-product-id="${product.id}">Adicionar ingrediente</button>`}
      ${legacy ? `<p class="small muted">Registro anterior: ${escapeHtml(legacy)}</p>` : ""}
    </div>
  `;
}

// Informacao nutricional: tabela fixa (porcao + 8 nutrientes padrao).
function productNutritionBlock(product, locked) {
  const rows = product.nutritionRows || defaultNutritionRows();
  const legacy = product.nutrition ? product.nutrition : "";
  return `
    <div class="struct-block">
      <label class="struct-label">8. Informacao nutricional</label>
      <div class="field" style="max-width:280px">
        <label>Quantidade por porcao de<span>Estabelecimento</span></label>
        <input data-pnutport="${product.id}" value="${escapeHtml(product.nutritionPortion || "")}" placeholder="ex.: 100 g" ${locked ? "disabled" : ""}>
      </div>
      <table class="struct-table">
        <thead><tr><th>Nutriente</th><th class="num">Quantidade</th><th class="num">% VD</th></tr></thead>
        <tbody>
          ${rows.map((row, index) => `
            <tr>
              <td>${row.label}</td>
              <td><input class="num" data-pnut="${product.id}" data-nidx="${index}" data-nfield="qty" value="${escapeHtml(row.qty || "")}" ${locked ? "disabled" : ""}></td>
              <td><input class="num" data-pnut="${product.id}" data-nidx="${index}" data-nfield="pct" value="${escapeHtml(row.pct || "")}" ${locked ? "disabled" : ""}></td>
            </tr>
          `).join("")}
        </tbody>
      </table>
      ${legacy ? `<p class="small muted">Registro anterior: ${escapeHtml(legacy)}</p>` : ""}
    </div>
  `;
}

function productEditor(product, opts = {}) {
  const versionTag = product.version > 1 ? `v${product.version}` : null;
  const locked = isProductLocked(product) || opts.readOnlyHistory;
  const canSubmit = state.role === "establishment" && !opts.readOnlyHistory
    && ["Rascunho", "Correcoes solicitadas"].includes(product.status)
    && (product.name || "").trim();
  const canReview = state.role === "sim" && !opts.readOnlyHistory && product.status === "Em analise";
  const canRevise = state.role === "establishment" && !opts.readOnlyHistory && product.status === "Aprovado";
  const canCancel = state.role === "establishment" && !opts.readOnlyHistory && product.status === "Em analise";
  const canDelete = state.role === "establishment" && !opts.readOnlyHistory && product.status !== "Aprovado";
  const metaSummary = [
    product.brand && `Marca: ${escapeHtml(product.brand)}`,
    (product.storageConditions || product.conservation) && `Armazenamento: ${escapeHtml(product.storageConditions || product.conservation)}`,
    product.labelUploadId ? "Rotulo enviado" : "Rotulo pendente",
    product.submittedAt ? `Enviado em ${formatDate(product.submittedAt)}` : null,
  ].filter(Boolean).join(" &middot; ");
  return `
    <section class="subform product-card ${locked ? "locked" : ""}">
      <div class="subform-title">
        <h3>${escapeHtml(product.name || "Produto sem nome")} - Anexo IV ${versionTag ? `<span class="version-tag">${versionTag}</span>` : ""}</h3>
        <span class="status ${statusClass(product.status)}">${product.status}</span>
      </div>
      ${metaSummary ? `<p class="product-meta">${metaSummary}</p>` : ""}
      ${product.status === "Aprovado" ? `<p class="small muted">Aprovado em ${formatDate(product.approvedAt)} por ${product.approvedBy || "SIM"}. Este produto esta travado para edicao.</p>` : ""}
      ${product.status === "Correcoes solicitadas" && product.simNote ? `<p class="small" style="color:#b45309"><strong>Correcoes pedidas pelo SIM:</strong> ${escapeHtml(product.simNote)}</p>` : ""}
      ${opts.readOnlyHistory ? `<p class="small muted">Substituido por uma versao mais recente em ${formatDate(product.supersededAt)}.</p>` : ""}
      <div class="official-form-note">
        <strong>Dados do estabelecimento ja preenchidos</strong>
        <span>Razao social, endereco, CNPJ, inscricao estadual e responsavel legal vem automaticamente da ficha mestre.</span>
      </div>
      <div class="product-section">
        <h4>4. Identificacao do produto</h4>
        <div class="form-grid">
          ${productField(product, "name", "Nome do produto", { readOnlyHistory: locked })}
          ${productField(product, "brand", "Marca", { readOnlyHistory: locked })}
          ${productField(product, "labelRegistration", "N. registro de rotulo", { readOnlyHistory: locked })}
        </div>
      </div>
      <div class="product-section">${productNatureBlock(product, locked)}</div>
      <div class="product-section">
        <h4>6. Caracteristicas do rotulo e da embalagem</h4>
        ${productOptionBlock(product, "labelTypes", "6.1 Rotulo", PRODUCT_LABEL_TYPE_OPTIONS, locked)}
        ${productOptionBlock(product, "primaryPackagingTypes", "6.2 Embalagem primaria", PRODUCT_PRIMARY_PACKAGE_OPTIONS, locked)}
        <div class="form-grid">
          ${productField(product, "otherLabelType", "Outro tipo de rotulo", { readOnlyHistory: locked })}
          ${productField(product, "otherPrimaryPackagingType", "Outro tipo de embalagem primaria", { readOnlyHistory: locked })}
          ${productField(product, "dateLotIndication", "Indicacao da data de fabricacao, validade e lote", { textarea: true, readOnlyHistory: locked })}
          ${productField(product, "packageQuantity", "Quantidade de produto por embalagem", { readOnlyHistory: locked })}
          ${productField(product, "labelingPresentation", "Apresentacao das informacoes de rotulagem", { textarea: true, full: true, readOnlyHistory: locked })}
        </div>
        ${productLabelCard(product, locked)}
      </div>
      <div class="product-section">${productCompositionBlock(product, locked)}</div>
      <div class="product-section">${productNutritionBlock(product, locked)}</div>
      <div class="product-section">
        <div class="form-grid">
          ${productField(product, "manufacturingProcess", "9. Processo de fabricacao", { textarea: true, readOnlyHistory: locked })}
          ${productField(product, "packagingProcess", "10. Processo de embalagem", { textarea: true, readOnlyHistory: locked })}
          ${productField(product, "storageConditions", "11. Condicoes de armazenamento", { textarea: true, readOnlyHistory: locked })}
          ${productField(product, "notes", "12. Medidas de controle de qualidade", { textarea: true, readOnlyHistory: locked })}
          ${productField(product, "marketTransport", "13. Transporte e expedicao ao mercado consumidor", { textarea: true, full: true, readOnlyHistory: locked })}
        </div>
      </div>
      <div class="product-actions">
        <button class="btn" data-product-action="print" data-product-id="${product.id}">${icon("print")}Gerar Anexo IV</button>
        ${canSubmit ? `<button class="btn primary" data-product-action="submit" data-product-id="${product.id}">Enviar produto para analise</button>` : ""}
        ${canCancel ? `<button class="btn" data-product-action="cancel-submit" data-product-id="${product.id}">Cancelar envio e editar</button>` : ""}
        ${canReview ? `
          <button class="btn warn" data-product-action="request-changes" data-product-id="${product.id}">Solicitar correcoes</button>
          <button class="btn primary" data-product-action="approve" data-product-id="${product.id}">${icon("check")}Aprovar produto</button>
        ` : ""}
        ${canRevise ? `<button class="btn" data-product-action="revise" data-product-id="${product.id}">Solicitar alteracao (nova versao)</button>` : ""}
        ${canDelete ? `<button class="btn danger" data-product-action="delete" data-product-id="${product.id}">Excluir pedido</button>` : ""}
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

function renderAccounts() {
  const accounts = registry.accounts || [];
  return `
    <div class="grid">
      <div class="span-12 panel">
        <div class="panel-header">
          <div>
            <h2>Contas com acesso ao portal</h2>
            <p class="muted">Use esta lista para conferir o perfil e o último acesso relatado por cada conta. Senhas e sessões nunca são exibidas.</p>
          </div>
        </div>
        <table class="table">
          <thead><tr><th>Conta</th><th>Perfil</th><th>Status</th><th>Último acesso</th><th>Criada em</th><th></th></tr></thead>
          <tbody>${accounts.length ? accounts.map((account) => `<tr>
            <td><strong>${escapeHtml(account.name)}</strong><br><span class="muted small">${escapeHtml(account.email)}</span></td>
            <td>${account.role === "sim" ? "Servidor SIM" : "Estabelecimento"}</td>
            <td><span class="status ${account.active ? "approved" : "corrections"}">${account.active ? "Ativa" : "Inativa"}</span></td>
            <td>${account.last_seen_at ? formatDate(account.last_seen_at) : "Nunca acessou"}</td>
            <td>${formatDate(account.created_at)}</td>
            <td><button class="btn" data-preview-account="${account.id}">Ver como esta conta</button></td>
          </tr>`).join("") : '<tr><td colspan="6" class="muted">Nenhuma conta cadastrada.</td></tr>'}</tbody>
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
    ["mtse", "Anexo II - MTSE"],
    ["construction", "Anexo III - Obras"],
    ["produto", "Anexo IV - Produto"],
  ];
  const fiscalTabs = [
    ["infracao", "Anexo V - Infracao"],
    ["advertencia", "Anexo VI - Advertencia"],
    ["apreensao", "Anexo VII - Apreensao"],
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
      <button class="btn" data-action="print">${icon("print")}Imprimir P&B</button>
      <button class="btn primary" data-action="print-digital">${icon("print")}Gerar PDF colorido</button>
      ${["anexoI", "mtse", "construction", "produto"].includes(state.printForm) ? `<a class="btn" href="${docxUrl(state.printForm)}" title="Baixa o mesmo formulário em Word, com campos editáveis">${icon("file")}Baixar Word editável</a>` : ""}
    </div>
    <p class="small muted no-print" style="margin:-6px 0 14px">Os campos narrativos crescem enquanto voc&ecirc; escreve. Se ultrapassarem a folha, o PDF cria p&aacute;ginas de continua&ccedil;&atilde;o automaticamente. Use <strong>Imprimir P&amp;B</strong> para a via f&iacute;sica e <strong>Gerar PDF colorido</strong> ao salvar digitalmente.</p>
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

function officialPathValue(path) {
  return path.split(".").reduce((value, key) => value?.[key], state) ?? "";
}

function officialInput(path, options = {}) {
  const value = options.value ?? officialPathValue(path);
  const owner = options.owner || "establishment";
  const readonly =
    (owner === "establishment" && state.role !== "establishment") ||
    (owner === "sim" && state.role !== "sim");
  const binding = options.cnaePart
    ? `data-official-cnae="${options.cnaePart}"`
    : `data-path="${path}"`;
  return `<input
    class="official-fill-input ${options.inline ? "official-fill-inline" : ""}"
    type="${options.type || "text"}"
    ${binding}
    value="${escapeHtml(value)}"
    ${readonly ? "readonly" : ""}
    aria-label="${escapeHtml(options.label || path)}"
  >`;
}

function officialTextarea(path, options = {}) {
  const value = options.value ?? officialPathValue(path);
  const owner = options.owner || "establishment";
  const readonly =
    (owner === "establishment" && state.role !== "establishment") ||
    (owner === "sim" && state.role !== "sim");
  return `<textarea
    class="official-fill-input official-fill-textarea"
    data-path="${path}"
    style="--official-textarea-height:${options.height || 12}mm"
    ${readonly ? "readonly" : ""}
    aria-label="${escapeHtml(options.label || path)}"
  >${escapeHtml(value)}</textarea>`;
}

function autoSizeOfficialTextarea(element) {
  if (!element || !element.matches(".official-fill-textarea")) return;
  const minimum = parseFloat(getComputedStyle(element).minHeight) || 0;
  element.style.height = "auto";
  element.style.height = `${Math.max(element.scrollHeight, minimum)}px`;
}

function splitContinuationText(value, maxCharacters = 2100) {
  const text = String(value || "").trim();
  if (!text) return [];
  const pages = [];
  let remaining = text;
  while (remaining.length > maxCharacters) {
    let cut = remaining.lastIndexOf("\n", maxCharacters);
    if (cut < maxCharacters * .55) cut = remaining.lastIndexOf(" ", maxCharacters);
    if (cut < maxCharacters * .55) cut = maxCharacters;
    pages.push(remaining.slice(0, cut).trim());
    remaining = remaining.slice(cut).trim();
  }
  pages.push(remaining);
  return pages;
}

function cleanupPrintPreparation() {
  document.querySelectorAll(".official-print-value, .official-continuation-page").forEach((element) => element.remove());
  document.querySelectorAll(".official-fill-textarea.has-print-continuation").forEach((element) => {
    element.classList.remove("has-print-continuation");
  });
  document.body.classList.remove("digital-pdf");
}

function prepareLongFormFields() {
  cleanupPrintPreparation();
  const form = document.querySelector(".official-form");
  if (!form) return;
  const header = form.querySelector(".official-form-header");
  const annex = form.querySelector(".official-form-name strong")?.textContent || "ANEXO";
  const formTitle = form.querySelector(".official-form-name span")?.textContent || "FORMULÁRIO";
  const continuationPages = [];

  form.querySelectorAll(".official-fill-textarea").forEach((field) => {
    const value = field.value || "";
    const label = field.getAttribute("aria-label") || "Campo descritivo";
    const printValue = document.createElement("div");
    printValue.className = "official-print-value";
    const needsContinuation = value.length > 500 || value.split("\n").length > 12;
    printValue.textContent = needsContinuation
      ? "O conteúdo integral deste campo segue na página de continuação."
      : value;
    field.after(printValue);
    if (!needsContinuation) return;

    field.classList.add("has-print-continuation");
    splitContinuationText(value).forEach((chunk, index, chunks) => {
      const page = document.createElement("section");
      page.className = "official-page official-document-page official-continuation-page";
      if (header) page.append(header.cloneNode(true));
      const title = document.createElement("div");
      title.className = "official-form-name";
      title.innerHTML = `<strong>${escapeHtml(annex)}</strong><span>CONTINUAÇÃO — ${escapeHtml(label)}</span>`;
      const body = document.createElement("div");
      body.className = "official-page-body official-continuation-body";
      const description = document.createElement("p");
      description.className = "official-continuation-description";
      description.textContent = `${formTitle} · ${label}`;
      const text = document.createElement("div");
      text.className = "official-continuation-text";
      text.textContent = chunk;
      const pageIndex = document.createElement("div");
      pageIndex.className = "official-page-index";
      pageIndex.textContent = `CONTINUAÇÃO ${index + 1} DE ${chunks.length}`;
      body.append(description, text);
      page.append(title, body, pageIndex);
      continuationPages.push(page);
    });
  });
  continuationPages.forEach((page) => form.append(page));
}

function printDocument(mode = "paper") {
  prepareLongFormFields();
  document.body.classList.toggle("digital-pdf", mode === "digital");
  const cleanup = () => cleanupPrintPreparation();
  window.addEventListener("afterprint", cleanup, { once: true });
  window.print();
}

function officialDocumentHeader(number, title) {
  return `
    <header class="official-form-header">
      <div class="official-service-masthead">
        <img src="./assets/brasao-orlandia.png" alt="Brasao de Orlandia">
        <div class="official-government-lines">
          <strong>PREFEITURA MUNICIPAL DE ORL&Acirc;NDIA</strong>
          <span>Estado de S&atilde;o Paulo</span>
          <b>SECRETARIA MUNICIPAL DE DESENVOLVIMENTO ECON&Ocirc;MICO E TURISMO</b>
          <b>SERVI&Ccedil;O DE INSPE&Ccedil;&Atilde;O MUNICIPAL - SIM</b>
        </div>
        <div class="official-service-contact">
          <strong>ATENDIMENTO DO SIM</strong>
          <span>Lucas Marcelino Campos Ferreira</span>
          <span>lucasferreira@orlandia.sp.gov.br</span>
          <span>(31) 99950-5748</span>
        </div>
      </div>
      <div class="official-form-name">
        <strong>ANEXO ${number}</strong>
        <span>${title}</span>
      </div>
    </header>
  `;
}

function officialField(label, path, options = {}) {
  const span = options.span || 12;
  const heightClass = options.tall ? " official-field-tall" : "";
  const owner = options.owner || "establishment";
  const control = options.textarea
    ? officialTextarea(path, { ...options, owner, label: options.ariaLabel || label })
    : officialInput(path, { ...options, owner, label: options.ariaLabel || label });
  return `<div class="official-field official-span-${span}${heightClass}"><span>${label}</span>${control}</div>`;
}

function officialTableInput(path, options = {}) {
  if (options.textarea) {
    return officialTextarea(path, {
      ...options,
      height: options.height || 8,
      label: options.label || path,
    });
  }
  return officialInput(path, { ...options, label: options.label || path });
}

function comparableOfficialValue(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function officialOption(label, selectedValue, aliases = [], options = {}) {
  const selected = comparableOfficialValue(selectedValue);
  const optionValue = options.value || label;
  const candidates = [optionValue, label, ...aliases].map(comparableOfficialValue);
  const checked = Boolean(selected) && candidates.some((candidate) => selected === candidate);
  const owner = options.owner || "establishment";
  const readonly =
    (owner === "establishment" && state.role !== "establishment") ||
    (owner === "sim" && state.role !== "sim");
  const parentBinding = options.parentPath
    ? `data-official-parent-path="${options.parentPath}" data-official-parent-value="${escapeHtml(options.parentValue || "")}"`
    : "";
  return `
    <label class="official-option">
      <input
        class="official-checkbox"
        type="radio"
        name="official-${escapeHtml(options.path || "choice")}"
        data-official-choice-path="${escapeHtml(options.path || "")}"
        value="${escapeHtml(optionValue)}"
        ${parentBinding}
        ${checked ? "checked" : ""}
        ${readonly ? "disabled" : ""}
      >
      <span>${label}</span>
    </label>
  `;
}

function officialCheck(label, path, optionValue, options = {}) {
  const selected = options.selectedValues ?? officialPathValue(path);
  const checked = Array.isArray(selected) && selected.some(
    (value) => comparableOfficialValue(value) === comparableOfficialValue(optionValue)
  );
  const owner = options.owner || "establishment";
  const readonly =
    (owner === "establishment" && state.role !== "establishment") ||
    (owner === "sim" && state.role !== "sim");
  return `
    <label class="official-option">
      <input
        class="official-checkbox"
        type="checkbox"
        data-official-array-path="${escapeHtml(path)}"
        value="${escapeHtml(optionValue)}"
        ${checked ? "checked" : ""}
        ${readonly ? "disabled" : ""}
      >
      <span>${label}</span>
    </label>
  `;
}

function officialSignatureBlock(options = {}) {
  const owner = options.owner || "establishment";
  const path = options.path || "application.signaturePlaceDate";
  return `
    <div class="official-document-signatures">
      <div class="official-signature-location">
        <strong>LOCAL E DATA</strong>
        ${officialInput(path, { owner, label: "Local e data" })}
      </div>
      <div><span></span>${options.left || "ASSINATURA DO PROPRIETARIO OU RESPONSAVEL LEGAL"}</div>
      <div><span></span>${options.right || "ASSINATURA DO RESPONSAVEL TECNICO"}</div>
    </div>
  `;
}

function officialDocumentPage(number, title, page, totalPages, body, className = "") {
  return `
    <section class="official-page official-document-page ${className}">
      ${officialDocumentHeader(number, title)}
      <div class="official-page-body">${body}</div>
      <div class="official-page-index">ANEXO ${number} - P&Aacute;GINA ${page} DE ${totalPages}</div>
    </section>
  `;
}

function officialClassificationGroup(title, options) {
  return `
    <div class="official-classification-group">
      <div>${title}</div>
      ${options.map((option) => officialOption(
        option,
        state.establishment.classification,
        [],
        { path: "establishment.classification", value: option }
      )).join("")}
    </div>
  `;
}

function cnaeParts() {
  const raw = String(state.establishment.cnae || "").trim();
  const match = raw.match(/^([0-9.\-/]+)\s*-\s*(.+)$/);
  if (!match) return { code: raw, activity: raw };
  return { code: match[1], activity: match[2] };
}

function printAnexoI() {
  const cnae = cnaeParts();
  const actType = state.application.actType || "";
  const cadastralChange = state.application.cadastralChangeType || (
    comparableOfficialValue(actType).includes("alteracao cadastral")
      ? state.application.otherAct
      : ""
  );
  return `
    <div class="official-form official-anexo-i">
      <section class="official-page official-anexo-i-page official-anexo-i-page-one">
        ${officialDocumentHeader("I", "SOLICITA&Ccedil;&Atilde;O DE ATOS DO S.I.M.")}

        <h3 class="official-section-title">1. INFORMA&Ccedil;&Otilde;ES DO ESTABELECIMENTO</h3>
        <div class="official-grid official-establishment-grid">
          <div class="official-field official-span-12 official-field-tall"><span>NOME (Raz&atilde;o Social/Pessoa F&iacute;sica):</span>${officialInput("establishment.legalName", { label: "Razao social ou nome" })}</div>
          <div class="official-field official-span-6"><span>CNPJ/CPF:</span>${officialInput("establishment.cnpj", { label: "CNPJ ou CPF" })}</div>
          <div class="official-field official-span-6"><span>MATRIZ/EIRELI/ME/EPP:</span>${officialInput("establishment.legalNature", { label: "Natureza juridica ou porte" })}</div>
          <div class="official-field official-span-6"><span>IDENTIFICA&Ccedil;&Atilde;O DA ATIVIDADE ECON&Ocirc;MICA:</span>${officialInput("establishment.cnae", { value: cnae.activity, cnaePart: "activity", label: "Atividade economica" })}</div>
          <div class="official-field official-span-6"><span>C&Oacute;DIGO DA ATIVIDADE CNAE:</span>${officialInput("establishment.cnae", { value: cnae.code, cnaePart: "code", label: "Codigo CNAE" })}</div>
          <div class="official-field official-span-12 official-field-address"><span>ENDERE&Ccedil;O:</span>${officialInput("establishment.address", { label: "Endereco" })}</div>
          <div class="official-field official-span-4"><span>BAIRRO:</span>${officialInput("establishment.district", { label: "Bairro" })}</div>
          <div class="official-field official-span-3"><span>MUNIC&Iacute;PIO:</span>${officialInput("establishment.city", { label: "Municipio" })}</div>
          <div class="official-field official-span-1"><span>UF:</span>${officialInput("establishment.state", { label: "UF" })}</div>
          <div class="official-field official-span-4"><span>CEP:</span>${officialInput("establishment.zip", { label: "CEP" })}</div>
          <div class="official-field official-span-8"><span>E-MAIL:</span>${officialInput("establishment.email", { type: "email", label: "E-mail" })}</div>
          <div class="official-field official-span-4"><span>TELEFONE:</span>${officialInput("establishment.phone", { label: "Telefone" })}</div>
        </div>

        <h3 class="official-section-title">2. INFORMA&Ccedil;&Otilde;ES DO RESPONS&Aacute;VEL</h3>
        <div class="official-grid">
          <div class="official-field official-span-7"><span>RESPONS&Aacute;VEL LEGAL:</span>${officialInput("legalResponsible.name", { label: "Responsavel legal" })}</div>
          <div class="official-field official-span-5"><span>CPF:</span>${officialInput("legalResponsible.cpf", { label: "CPF do responsavel legal" })}</div>
          <div class="official-field official-span-7"><span>RESPONS&Aacute;VEL T&Eacute;CNICO - RT:</span>${officialInput("technicalResponsible.name", { label: "Responsavel tecnico" })}</div>
          <div class="official-field official-span-5"><span>CPF:</span>${officialInput("technicalResponsible.cpf", { label: "CPF do responsavel tecnico" })}</div>
          <div class="official-field official-span-12 official-field-tall"><span>N&ordm; DE INSCRI&Ccedil;&Atilde;O DO RT NO CONSELHO DE CLASSE PROFISSIONAL/UF:</span>${officialInput("technicalResponsible.council", { label: "Inscricao profissional do responsavel tecnico" })}</div>
        </div>

        <h3 class="official-section-title">3. CLASSIFICA&Ccedil;&Atilde;O DO ESTABELECIMENTO</h3>
        <div class="official-classification">
          ${officialClassificationGroup("Estabelecimento de carne e derivados", [
            "Unidade de beneficiamento de carne e produtos carneos",
          ])}
          ${officialClassificationGroup("Estabelecimento de pescado e derivados", [
            "Unidade de beneficiamento de pescado e produtos de pescado",
            "Estacao depuradora de moluscos bivalves",
          ])}
          ${officialClassificationGroup("Estabelecimento de ovos e derivados", [
            "Granja avicola",
            "Unidade de beneficiamento de ovos e derivados",
          ])}
          ${officialClassificationGroup("Estabelecimento de leite e derivados", [
            "Granja leiteira",
            "Posto de refrigeracao",
            "Unidade de beneficiamento de leite e derivados",
            "Queijaria",
          ])}
        </div>
      </section>

      <section class="official-page official-anexo-i-page official-anexo-i-page-two">
        <div class="official-classification official-classification-continuation">
          ${officialClassificationGroup("Estabelecimento de produtos de abelha e derivados", [
            "Unidade de beneficiamento de produtos de abelhas",
          ])}
          <div class="official-small-business">
            <strong>Aten&ccedil;&atilde;o:</strong> O estabelecimento se enquadra nas especifica&ccedil;&otilde;es de
            &ldquo;Estabelecimento Agroindustrial de Pequeno Porte?&rdquo;
            ${officialOption("Sim", state.establishment.smallBusiness, [], {
              path: "establishment.smallBusiness",
              value: "Sim",
            })}
            ${officialOption("Nao", state.establishment.smallBusiness, [], {
              path: "establishment.smallBusiness",
              value: "Nao",
            })}
          </div>
        </div>

        <h3 class="official-section-title">4. TIPO DE SOLICITA&Ccedil;&Atilde;O</h3>
        <div class="official-request-box">
          ${officialOption("Novo registro de estabelecimento", actType, ["Registro de estabelecimento"], {
            path: "application.actType",
            value: "Registro de estabelecimento",
          })}
          ${officialOption("Renovacao do titulo de registro", actType, [], {
            path: "application.actType",
            value: "Renovacao do titulo de registro",
          })}
          ${officialOption("Reforma ou ampliacao", actType, [], {
            path: "application.actType",
            value: "Reforma ou ampliacao",
          })}
          ${officialOption("Transferencia cadastral", actType, [], {
            path: "application.actType",
            value: "Transferencia cadastral",
          })}
          ${officialOption("Solicitacao de vistoria in loco", actType, [], {
            path: "application.actType",
            value: "Solicitacao de vistoria in loco",
          })}
          ${officialOption("Paralisacao das atividades", actType, [], {
            path: "application.actType",
            value: "Paralisacao das atividades",
          })}
          ${officialOption("Reinicio das atividades", actType, [], {
            path: "application.actType",
            value: "Reinicio das atividades",
          })}
          ${officialOption("Cancelamento do registro", actType, [], {
            path: "application.actType",
            value: "Cancelamento do registro",
          })}
          <label class="official-option official-other-option">
            <input
              class="official-checkbox"
              type="radio"
              name="official-application.actType"
              data-official-choice-path="application.actType"
              value="Outro ato"
              ${comparableOfficialValue(actType) === "outro ato" ? "checked" : ""}
              ${state.role !== "establishment" ? "disabled" : ""}
            >
            <span>Outro (especificar): ${officialInput("application.otherAct", { inline: true, label: "Outro tipo de solicitacao" })}</span>
          </label>
          <div class="official-alteration-title">Altera&ccedil;&atilde;o cadastral (assinalar uma das op&ccedil;&otilde;es abaixo):</div>
          ${officialOption("Alteracao de CNPJ", cadastralChange, [], {
            path: "application.cadastralChangeType",
            value: "Alteracao de CNPJ",
            parentPath: "application.actType",
            parentValue: "Alteracao cadastral",
          })}
          ${officialOption("Alteracao de razao social", cadastralChange, [], {
            path: "application.cadastralChangeType",
            value: "Alteracao de razao social",
            parentPath: "application.actType",
            parentValue: "Alteracao cadastral",
          })}
          ${officialOption("Classificacao do estabelecimento", cadastralChange, [], {
            path: "application.cadastralChangeType",
            value: "Classificacao do estabelecimento",
            parentPath: "application.actType",
            parentValue: "Alteracao cadastral",
          })}
          ${officialOption("Alteracao do endereco", cadastralChange, [], {
            path: "application.cadastralChangeType",
            value: "Alteracao do endereco",
            parentPath: "application.actType",
            parentValue: "Alteracao cadastral",
          })}
          ${officialOption("Alteracao de responsavel tecnico", cadastralChange, [], {
            path: "application.cadastralChangeType",
            value: "Alteracao de responsavel tecnico",
            parentPath: "application.actType",
            parentValue: "Alteracao cadastral",
          })}
        </div>

        <h3 class="official-section-title">5. TERMO DE COMPROMISSO</h3>
        <div class="official-commitment">
          DECLARAMOS CUMPRIR A LEGISLA&Ccedil;&Atilde;O VIGENTE E ASSUMIMOS, CIVIL E CRIMINALMENTE,
          INTEIRA RESPONSABILIDADE PELA VERACIDADE DAS INFORMA&Ccedil;&Otilde;ES PRESTADAS NESTE
          FORMUL&Aacute;RIO E SEUS ANEXOS.
        </div>

        <h3 class="official-section-title">6. ASSINATURAS DOS RESPONS&Aacute;VEIS</h3>
        <div class="official-signatures">
          <div class="official-signature-meta">
            <strong>LOCAL E DATA</strong>
            ${officialInput("application.signaturePlaceDate", { label: "Local e data" })}
            <div>NOME DO AUTUANTE: ${officialInput("application.inspectorName", { inline: true, owner: "sim", label: "Nome do autuante" })}</div>
            <div>MATR&Iacute;CULA: ${officialInput("application.inspectorRegistration", { inline: true, owner: "sim", label: "Matricula do autuante" })}</div>
          </div>
          <div class="official-signature-people">
            <div><span class="official-signature-line"></span>ASSINATURA DO PROPRIET&Aacute;RIO OU RESPONS&Aacute;VEL LEGAL</div>
            <div><span class="official-signature-line"></span>ASSINATURA DO RESPONS&Aacute;VEL T&Eacute;CNICO</div>
          </div>
        </div>
      </section>
    </div>
  `;
}

function printMtse() {
  const title = "MEMORIAL T&Eacute;CNICO-SANIT&Aacute;RIO DO ESTABELECIMENTO - MTSE";
  const propertyLink = state.establishment.propertyLink || "";
  const laundryType = state.production.laundryType || state.production.laundry || "";
  const classificationOptions = [
    "Estacao depuradora de moluscos bivalves",
    "Unidade de beneficiamento de ovos e derivados",
    "Granja avicola",
    "Unidade de beneficiamento de pescado e produtos de pescado",
    "Granja leiteira",
    "Unidade de beneficiamento de produtos de abelhas",
    "Unidade de beneficiamento de carne e produtos carneos",
    "Posto de refrigeracao",
    "Unidade de beneficiamento de leite e derivados",
    "Queijaria",
  ];
  const pageOne = `
    <h3 class="official-section-title">1. INFORMA&Ccedil;&Otilde;ES DO ESTABELECIMENTO</h3>
    <div class="official-grid">
      ${officialField("Nome (Raz&atilde;o Social/Pessoa F&iacute;sica):", "establishment.legalName", { span: 12 })}
      ${officialField("CNPJ/CPF:", "establishment.cnpj", { span: 7 })}
      ${officialField("N&ordm; do registro no S.I.M.:", "establishment.simNumber", { span: 5 })}
      ${officialField("Inscri&ccedil;&atilde;o Estadual:", "establishment.stateRegistration", { span: 6 })}
      ${officialField("Inscri&ccedil;&atilde;o Municipal:", "establishment.municipalRegistration", { span: 6 })}
      ${officialField("Endere&ccedil;o:", "establishment.address", { span: 12 })}
      ${officialField("Bairro:", "establishment.district", { span: 3 })}
      ${officialField("Munic&iacute;pio:", "establishment.city", { span: 4 })}
      ${officialField("UF:", "establishment.state", { span: 1 })}
      ${officialField("CEP:", "establishment.zip", { span: 4 })}
      ${officialField("E-mail:", "establishment.email", { span: 8, type: "email" })}
      ${officialField("Telefone:", "establishment.phone", { span: 4 })}
      <div class="official-field official-span-12">
        <span>Tipo de v&iacute;nculo com o im&oacute;vel:</span>
        <div class="official-inline-options">
          ${officialOption("Propriet&aacute;rio", propertyLink, ["Proprietario"], { path: "establishment.propertyLink", value: "Proprietario" })}
          ${officialOption("Locat&aacute;rio", propertyLink, ["Locatario"], { path: "establishment.propertyLink", value: "Locatario" })}
          ${officialOption("Outro", propertyLink, [], { path: "establishment.propertyLink", value: "Outro" })}
        </div>
      </div>
    </div>
    <h3 class="official-section-title">2. CLASSIFICA&Ccedil;&Atilde;O DO ESTABELECIMENTO</h3>
    <div class="official-option-grid official-box">
      ${classificationOptions.map((option) => officialOption(
        option,
        state.establishment.classification,
        [],
        { path: "establishment.classification", value: option }
      )).join("")}
    </div>
    <h3 class="official-section-title">3. INFORMA&Ccedil;&Otilde;ES DO RESPONS&Aacute;VEL LEGAL</h3>
    <div class="official-grid">
      ${officialField("Nome:", "legalResponsible.name", { span: 8 })}
      ${officialField("CPF:", "legalResponsible.cpf", { span: 4 })}
      ${officialField("Endere&ccedil;o residencial:", "legalResponsible.address", { span: 12 })}
      ${officialField("Bairro:", "legalResponsible.district", { span: 3 })}
      ${officialField("Cidade:", "legalResponsible.city", { span: 4 })}
      ${officialField("UF:", "legalResponsible.state", { span: 1 })}
      ${officialField("CEP:", "legalResponsible.zip", { span: 4 })}
      ${officialField("Telefone:", "legalResponsible.phone", { span: 4 })}
      ${officialField("E-mail:", "legalResponsible.email", { span: 8, type: "email" })}
    </div>
    <h3 class="official-section-title">4. INFORMA&Ccedil;&Otilde;ES DO RESPONS&Aacute;VEL T&Eacute;CNICO</h3>
    <div class="official-grid">
      ${officialField("Nome:", "technicalResponsible.name", { span: 8 })}
      ${officialField("CPF:", "technicalResponsible.cpf", { span: 4 })}
      ${officialField("Endere&ccedil;o residencial:", "technicalResponsible.address", { span: 12 })}
    </div>
  `;
  const pageTwo = `
    <div class="official-grid official-continuation-grid">
      ${officialField("Bairro:", "technicalResponsible.district", { span: 3 })}
      ${officialField("Cidade:", "technicalResponsible.city", { span: 4 })}
      ${officialField("UF:", "technicalResponsible.state", { span: 1 })}
      ${officialField("CEP:", "technicalResponsible.zip", { span: 4 })}
      ${officialField("Telefone:", "technicalResponsible.phone", { span: 4 })}
      ${officialField("E-mail:", "technicalResponsible.email", { span: 8, type: "email" })}
      ${officialField("N&ordm; de inscri&ccedil;&atilde;o no conselho de classe profissional/UF:", "technicalResponsible.council", { span: 12 })}
    </div>
    <h3 class="official-section-title">5. LISTA DE ATIVIDADES GERAIS DO ESTABELECIMENTO</h3>
    <table class="official-data-table">
      <thead><tr><th class="official-col-number">N&ordm;</th><th>LISTA DE ATIVIDADES</th></tr></thead>
      <tbody>${Array.from({ length: 5 }, (_, index) => `
        <tr>
          <td>${officialTableInput(`production.activityRows.${index}.number`, { label: `Numero da atividade ${index + 1}` })}</td>
          <td>${officialTableInput(`production.activityRows.${index}.activity`, {
            value: officialPathValue(`production.activityRows.${index}.activity`) || (index === 0 ? state.production.activities : ""),
            label: `Atividade ${index + 1}`,
          })}</td>
        </tr>
      `).join("")}</tbody>
    </table>
    <h3 class="official-section-title">6. PRODUTOS E CAPACIDADE MENSAL</h3>
    <div class="official-grid">
      ${officialField("Capacidade total mensal de produ&ccedil;&atilde;o:", "production.monthlyCapacity", { span: 12 })}
    </div>
    <div class="official-table-label">Produtos produzidos:</div>
    <table class="official-data-table official-compact-table">
      <thead><tr><th>Denomina&ccedil;&atilde;o de venda conforme RTIQ ou nomenclatura oficial</th><th>Intervalo de temperatura de conserva&ccedil;&atilde;o</th><th>Capacidade m&aacute;xima de produ&ccedil;&atilde;o</th></tr></thead>
      <tbody>${Array.from({ length: 4 }, (_, index) => `
        <tr>
          <td>${officialTableInput(`production.productCapacityRows.${index}.product`, { label: `Produto produzido ${index + 1}` })}</td>
          <td>${officialTableInput(`production.productCapacityRows.${index}.temperature`, { label: `Temperatura ${index + 1}` })}</td>
          <td>${officialTableInput(`production.productCapacityRows.${index}.capacity`, { label: `Capacidade ${index + 1}` })}</td>
        </tr>
      `).join("")}</tbody>
    </table>
    <div class="official-grid official-top-gap">
      ${officialField("Capacidade total mensal de recebimento:", "production.receivedCapacity", { span: 12 })}
    </div>
    <div class="official-table-label">Produtos recebidos:</div>
    <table class="official-data-table official-compact-table">
      <thead><tr><th>Denomina&ccedil;&atilde;o de venda conforme RTIQ ou nomenclatura oficial</th><th>M&eacute;dia de recebimento em kg ou L</th></tr></thead>
      <tbody>${Array.from({ length: 4 }, (_, index) => `
        <tr>
          <td>${officialTableInput(`production.receivedProductRows.${index}.product`, { label: `Produto recebido ${index + 1}` })}</td>
          <td>${officialTableInput(`production.receivedProductRows.${index}.average`, { label: `Media de recebimento ${index + 1}` })}</td>
        </tr>
      `).join("")}</tbody>
    </table>
    <h3 class="official-section-title">7. ORIGEM DA MAT&Eacute;RIA-PRIMA (RASTREAMENTO)</h3>
    <table class="official-data-table official-compact-table">
      <thead><tr><th>Descri&ccedil;&atilde;o do produto</th><th>Raz&atilde;o social do fabricante</th><th>CNPJ</th><th>N&ordm; de registro no &oacute;rg&atilde;o competente</th></tr></thead>
      <tbody>${Array.from({ length: 4 }, (_, index) => `
        <tr>
          <td>${officialTableInput(`production.rawMaterialRows.${index}.product`, {
            value: officialPathValue(`production.rawMaterialRows.${index}.product`) || (index === 0 ? state.production.rawMaterialOrigin : ""),
            label: `Materia-prima ${index + 1}`,
          })}</td>
          <td>${officialTableInput(`production.rawMaterialRows.${index}.manufacturer`, { label: `Fabricante ${index + 1}` })}</td>
          <td>${officialTableInput(`production.rawMaterialRows.${index}.cnpj`, { label: `CNPJ do fabricante ${index + 1}` })}</td>
          <td>${officialTableInput(`production.rawMaterialRows.${index}.registration`, { label: `Registro do fabricante ${index + 1}` })}</td>
        </tr>
      `).join("")}</tbody>
    </table>
    <h3 class="official-section-title">8. FUNCION&Aacute;RIOS</h3>
    <div class="official-grid">
      ${officialField("Total de funcion&aacute;rios:", "production.employeeTotal", { span: 4, value: state.production.employeeTotal || state.production.employees })}
      ${officialField("Masculinos:", "production.employeeMale", { span: 4 })}
      ${officialField("Femininos:", "production.employeeFemale", { span: 4 })}
    </div>
    <h3 class="official-section-title">9. LAVANDERIA</h3>
    <div class="official-inline-options official-box">
      ${officialOption("Pr&oacute;pria", laundryType, ["Propria"], { path: "production.laundryType", value: "Propria" })}
      ${officialOption("Terceirizada", laundryType, [], { path: "production.laundryType", value: "Terceirizada" })}
    </div>
  `;
  const pageThree = `
    <div class="official-table-label">Se terceirizada, informar:</div>
    <div class="official-grid">
      ${officialField("Raz&atilde;o social:", "production.laundryCompany", { span: 8 })}
      ${officialField("CNPJ:", "production.laundryCnpj", { span: 4 })}
    </div>
    <h3 class="official-section-title">10. DETALHES DO TERRENO</h3>
    <div class="official-grid">
      <div class="official-field official-span-12">
        <span>O estabelecimento j&aacute; est&aacute; constru&iacute;do?</span>
        <div class="official-inline-options">
          ${officialOption("Sim", state.production.alreadyBuilt, [], { path: "production.alreadyBuilt", value: "Sim" })}
          ${officialOption("N&atilde;o", state.production.alreadyBuilt, ["Nao"], { path: "production.alreadyBuilt", value: "Nao" })}
        </div>
      </div>
      ${officialField("&Aacute;rea total do terreno (m&sup2;):", "production.landTotalArea", { span: 6 })}
      ${officialField("&Aacute;rea a ser constru&iacute;da (m&sup2;):", "production.landBuildArea", { span: 6 })}
      ${officialField("&Aacute;rea &uacute;til (m&sup2;):", "production.usefulArea", { span: 6, value: state.production.usefulArea || state.establishment.area })}
      ${officialField("Recuo do alinhamento da rua (m):", "production.streetSetback", { span: 6 })}
    </div>
    <h3 class="official-section-title">11. &Aacute;REA DE LOCALIZA&Ccedil;&Atilde;O</h3>
    <div class="official-inline-options official-box">
      ${officialOption("Urbana", state.production.locationArea, [], { path: "production.locationArea", value: "Urbana" })}
      ${officialOption("Rural", state.production.locationArea, [], { path: "production.locationArea", value: "Rural" })}
    </div>
    <h3 class="official-section-title">12. DISPOSI&Ccedil;&Atilde;O DAS INSTALA&Ccedil;&Otilde;ES E FLUXO DE PRODU&Ccedil;&Atilde;O</h3>
    <p class="official-instruction">Listar os setores da ind&uacute;stria, descrevendo sua localiza&ccedil;&atilde;o e destina&ccedil;&atilde;o. Descrever tamb&eacute;m o fluxo de produ&ccedil;&atilde;o, desde a recep&ccedil;&atilde;o da mat&eacute;ria-prima at&eacute; a expedi&ccedil;&atilde;o do produto final.</p>
    ${officialTextarea("production.flow", { height: 58, label: "Disposicao das instalacoes e fluxo de producao" })}
    <h3 class="official-section-title">13. EQUIPAMENTOS</h3>
    <table class="official-data-table">
      <thead><tr><th>Localiza&ccedil;&atilde;o</th><th>Equipamento</th><th>Quantidade</th><th>Material</th></tr></thead>
      <tbody>${Array.from({ length: 5 }, (_, index) => `
        <tr>
          <td>${officialTableInput(`production.equipmentRows.${index}.location`, { label: `Local do equipamento ${index + 1}` })}</td>
          <td>${officialTableInput(`production.equipmentRows.${index}.equipment`, {
            value: officialPathValue(`production.equipmentRows.${index}.equipment`) || (index === 0 ? state.production.equipment : ""),
            label: `Equipamento ${index + 1}`,
          })}</td>
          <td>${officialTableInput(`production.equipmentRows.${index}.quantity`, { label: `Quantidade ${index + 1}` })}</td>
          <td>${officialTableInput(`production.equipmentRows.${index}.material`, { label: `Material ${index + 1}` })}</td>
        </tr>
      `).join("")}</tbody>
    </table>
    <h3 class="official-section-title">14. NATUREZA DO PISO E MATERIAL DE IMPERMEABILIZA&Ccedil;&Atilde;O</h3>
    <p class="official-instruction">Descrever material e cor.</p>
    ${officialTextarea("production.floorWalls", { height: 16, label: "Piso e impermeabilizacao" })}
  `;
  const pageFour = `
    <h3 class="official-section-title">15. JANELAS, PORTAS, TETO, SISTEMA DE BLOQUEIO SANIT&Aacute;RIO E CONTROLE DE VETORES</h3>
    <p class="official-instruction">Descrever tipo de material, forma de apresenta&ccedil;&atilde;o e o sistema de bloqueio sanit&aacute;rio.</p>
    ${officialTextarea("production.doorsWindowsCeiling", { height: 10, label: "Janelas, portas, teto e bloqueio sanitario" })}
    <h3 class="official-section-title">16. BANHEIROS/VESTU&Aacute;RIOS/INSTALA&Ccedil;&Otilde;ES PARA FUNCION&Aacute;RIOS</h3>
    <p class="official-instruction">Descrever localiza&ccedil;&atilde;o, pisos, tetos, paredes e cores. Listar vasos sanit&aacute;rios, pias, chuveiros e arm&aacute;rios.</p>
    ${officialTextarea("production.bathrooms", { height: 10, label: "Banheiros e vestiarios" })}
    <h3 class="official-section-title">17. ILUMINA&Ccedil;&Atilde;O E VENTILA&Ccedil;&Atilde;O</h3>
    <p class="official-instruction">Descrever tipo de ilumina&ccedil;&atilde;o (artificial ou natural) e ventila&ccedil;&atilde;o.</p>
    ${officialTextarea("production.lightingVentilation", { height: 8, label: "Iluminacao e ventilacao" })}
    <h3 class="official-section-title">18. DEP&Oacute;SITO DE EMBALAGENS, MAT&Eacute;RIAS-PRIMAS, CONDIMENTOS E UTENS&Iacute;LIOS</h3>
    <p class="official-instruction">Descrever localiza&ccedil;&atilde;o, pisos, tetos, paredes e cores.</p>
    ${officialTextarea("production.storage", { height: 8, label: "Depositos" })}
    <h3 class="official-section-title">19. SISTEMA DE ABASTECIMENTO DE &Aacute;GUA</h3>
    <p class="official-instruction">Informar proced&ecirc;ncia, vaz&atilde;o, capta&ccedil;&atilde;o, dep&oacute;sito, capacidade e distribui&ccedil;&atilde;o.</p>
    ${officialTextarea("production.waterSupply", { height: 8, label: "Abastecimento de agua" })}
    <h3 class="official-section-title">20. DESTINO DAS &Aacute;GUAS SERVIDAS</h3>
    ${officialTextarea("production.effluents", { height: 8, label: "Destino das aguas servidas" })}
    <h3 class="official-section-title">21. TRANSPORTE DE PRODUTOS EXPEDIDOS</h3>
    <p class="official-instruction">Descrever os meios de transporte usados na recep&ccedil;&atilde;o e expedi&ccedil;&atilde;o, incluindo tipo de ve&iacute;culo e temperatura.</p>
    ${officialTextarea("production.transport", { height: 8, label: "Transporte de produtos" })}
    <h3 class="official-section-title">22. AN&Aacute;LISES LABORATORIAIS</h3>
    <p class="official-instruction">Indicar as an&aacute;lises realizadas em laborat&oacute;rio pr&oacute;prio e terceirizado.</p>
    ${officialTextarea("production.labAnalysis", { height: 8, label: "Analises laboratoriais" })}
    <h3 class="official-section-title">21. DIAS E HOR&Aacute;RIOS DE PRODU&Ccedil;&Atilde;O</h3>
    <table class="official-data-table official-compact-table">
      <thead><tr><th>Dias da semana</th><th>Hor&aacute;rio</th></tr></thead>
      <tbody>${Array.from({ length: 6 }, (_, index) => `
        <tr>
          <td>${officialTableInput(`production.productionScheduleRows.${index}.day`, {
            value: officialPathValue(`production.productionScheduleRows.${index}.day`) || (index === 0 ? state.production.productionSchedule : ""),
            label: `Dia de producao ${index + 1}`,
          })}</td>
          <td>${officialTableInput(`production.productionScheduleRows.${index}.time`, { label: `Horario de producao ${index + 1}` })}</td>
        </tr>
      `).join("")}</tbody>
    </table>
  `;
  const pageFive = `
    <h3 class="official-section-title">22. ASSINATURAS DOS RESPONS&Aacute;VEIS</h3>
    ${officialSignatureBlock({
      path: "production.signaturePlaceDate",
      left: "ASSINATURA DO PROPRIET&Aacute;RIO OU RESPONS&Aacute;VEL LEGAL",
      right: "ASSINATURA DO RESPONS&Aacute;VEL T&Eacute;CNICO",
    })}
  `;
  return `<div class="official-form official-document">
    ${officialDocumentPage("II", title, 1, 5, pageOne, "official-mtse-page")}
    ${officialDocumentPage("II", title, 2, 5, pageTwo, "official-mtse-page")}
    ${officialDocumentPage("II", title, 3, 5, pageThree, "official-mtse-page")}
    ${officialDocumentPage("II", title, 4, 5, pageFour, "official-mtse-page")}
    ${officialDocumentPage("II", title, 5, 5, pageFive, "official-mtse-page official-signature-page")}
  </div>`;
}

function printConstruction() {
  const title = "MEMORIAL DESCRITIVO DE CONSTRU&Ccedil;&Atilde;O/REFORMA";
  const locationArea = state.construction.locationArea || state.production.locationArea || "";
  const pageOne = `
    <h3 class="official-section-title">1. IDENTIFICA&Ccedil;&Atilde;O DO ESTABELECIMENTO</h3>
    <div class="official-grid">
      ${officialField("RAZ&Atilde;O SOCIAL / NOME DO PRODUTOR", "establishment.legalName", { span: 12 })}
      ${officialField("NOME FANTASIA", "establishment.tradeName", { span: 12 })}
      ${officialField("CLASSIFICA&Ccedil;&Atilde;O DO ESTABELECIMENTO", "establishment.classification", { span: 12 })}
      ${officialField("CNPJ/CPF", "establishment.cnpj", { span: 7 })}
      ${officialField("INSCRI&Ccedil;&Atilde;O ESTADUAL", "establishment.stateRegistration", { span: 5 })}
      ${officialField("RESPONS&Aacute;VEL LEGAL PELO ESTABELECIMENTO", "legalResponsible.name", { span: 12 })}
    </div>
    <h3 class="official-section-title">2. LOCALIZA&Ccedil;&Atilde;O</h3>
    <div class="official-grid">
      ${officialField("ENDERE&Ccedil;O", "establishment.address", { span: 12 })}
      ${officialField("BAIRRO/LOCALIDADE", "establishment.district", { span: 4 })}
      ${officialField("MUNIC&Iacute;PIO", "establishment.city", { span: 3 })}
      ${officialField("UF", "establishment.state", { span: 1 })}
      ${officialField("CEP", "establishment.zip", { span: 4 })}
      ${officialField("E-MAIL", "establishment.email", { span: 8, type: "email" })}
      ${officialField("TELEFONE", "establishment.phone", { span: 4 })}
    </div>
    <h3 class="official-section-title">3. CARACTERIZA&Ccedil;&Atilde;O DO ESTABELECIMENTO</h3>
    <div class="official-grid">
      <div class="official-field official-span-12">
        <span>LOCALIZA&Ccedil;&Atilde;O - ZONA:</span>
        <div class="official-inline-options">
          ${officialOption("Rural", locationArea, [], { path: "construction.locationArea", value: "Rural" })}
          ${officialOption("Urbana", locationArea, [], { path: "construction.locationArea", value: "Urbana" })}
        </div>
      </div>
      ${officialField("&Aacute;REA TOTAL DO TERRENO (m&sup2;):", "construction.landTotalArea", { span: 6, value: state.construction.landTotalArea || state.production.landTotalArea })}
      ${officialField("&Aacute;REA A SER CONSTRU&Iacute;DA (m&sup2;):", "construction.landBuildArea", { span: 6, value: state.construction.landBuildArea || state.production.landBuildArea })}
      ${officialField("&Aacute;REA &Uacute;TIL (m&sup2;):", "construction.usefulArea", { span: 6, value: state.construction.usefulArea || state.production.usefulArea || state.establishment.area })}
      ${officialField("RECUO DAS RUAS, AVENIDAS E ESTRADAS (m):", "construction.streetSetback", { span: 6, value: state.construction.streetSetback || state.production.streetSetback })}
      ${officialField("CONFRONTANTES E VIAS DE ACESSO:", "construction.boundariesAccess", { span: 12, textarea: true, height: 19 })}
    </div>
    <h3 class="official-section-title">4. DESCRI&Ccedil;&Atilde;O DA CONSTRU&Ccedil;&Atilde;O</h3>
    <h4 class="official-subsection-title">4.1. P&Eacute; DIREITO</h4>
    ${officialTextarea("construction.ceilingHeight", {
      value: state.construction.ceilingHeight || state.construction.buildingDescription,
      height: 31,
      label: "Pe direito",
    })}
  `;
  const pageTwo = `
    <h4 class="official-subsection-title">4.2. COBERTURA/TELHADO</h4>
    ${officialTextarea("construction.roof", { height: 11, label: "Cobertura e telhado" })}
    <h4 class="official-subsection-title">4.3. FORROS</h4>
    ${officialTextarea("construction.ceilings", { height: 11, label: "Forros" })}
    <h4 class="official-subsection-title">4.4. PORTAS, JANELAS E EXAUSTORES</h4>
    ${officialTextarea("construction.doorsWindowsExhaust", { height: 12, label: "Portas, janelas e exaustores" })}
    <h4 class="official-subsection-title">4.5. PISO E RODAP&Eacute;S</h4>
    ${officialTextarea("construction.floorsBaseboards", {
      value: state.construction.floorsBaseboards || state.construction.materials,
      height: 11,
      label: "Piso e rodapes",
    })}
    <h4 class="official-subsection-title">4.6. PAREDES</h4>
    ${officialTextarea("construction.walls", { height: 11, label: "Paredes" })}
    <h4 class="official-subsection-title">4.7. INSTALA&Ccedil;&Otilde;ES DE &Aacute;GUA E CANALIZA&Ccedil;&Atilde;O</h4>
    ${officialTextarea("construction.waterPiping", {
      value: state.construction.waterPiping || state.construction.waterAndSewage,
      height: 12,
      label: "Instalacoes de agua e canalizacao",
    })}
    <h4 class="official-subsection-title">4.8. SISTEMA DE ESCOAMENTO DAS &Aacute;GUAS RESIDUAIS</h4>
    ${officialTextarea("construction.wastewater", { height: 12, label: "Escoamento de aguas residuais" })}
    <h4 class="official-subsection-title">4.9. FONTE PRODUTORA DE CALOR, BANCO DE &Aacute;GUA GELADA E F&Aacute;BRICA DE GELO</h4>
    ${officialTextarea("construction.heatColdIce", {
      value: state.construction.heatColdIce || state.construction.coldRooms,
      height: 12,
      label: "Calor, agua gelada e fabrica de gelo",
    })}
    <h3 class="official-section-title">5. OBSERVA&Ccedil;&Atilde;O</h3>
    ${officialTextarea("construction.observations", { height: 10, label: "Observacoes" })}
    <div class="official-plant-list">
      <strong>5.1. ANEXAR PLANTAS</strong>
      <span>5.1.1 Situa&ccedil;&atilde;o na escala de 1/500</span>
      <span>5.1.2 Baixa na escala de 1/100 (com layout dos equipamentos)</span>
      <span>5.1.3 Fachada na escala de 1/50</span>
      <span>5.1.4 Cortes na escala de 1/50</span>
    </div>
    ${officialSignatureBlock({
      path: "construction.signaturePlaceDate",
      left: "CARIMBO E ASSINATURA DO RESPONS&Aacute;VEL LEGAL DA FIRMA",
      right: "CARIMBO E ASSINATURA DO RESPONS&Aacute;VEL PELO PROJETO",
    })}
  `;
  return `<div class="official-form official-document">
    ${officialDocumentPage("III", title, 1, 2, pageOne, "official-construction-page")}
    ${officialDocumentPage("III", title, 2, 2, pageTwo, "official-construction-page")}
  </div>`;
}

function printProduct() {
  const options = visibleProducts();
  const product = options.find((item) => item.id === state.printProductId) || options[0] || { name: "", brand: "", conservation: "", notes: "" };
  const productIndex = Math.max(0, state.products.findIndex((item) => item.id === product.id));
  const productPath = `products.${productIndex}`;
  const picker = options.length > 1 ? `
    <div class="tabs no-print" style="margin-bottom:12px">
      ${options.map((item) => `<button class="${item.id === product.id ? "active" : ""}" data-print-product="${item.id}">${escapeHtml(item.name || "Sem nome")}</button>`).join("")}
    </div>
  ` : "";
  const inferredNature = product.natureOptions?.length
    ? product.natureOptions
    : PRODUCT_NATURE_OPTIONS.filter((option) => comparableOfficialValue(product.requestNature).includes(comparableOfficialValue(option)));
  const title = "REGISTRO DE R&Oacute;TULO E/OU PRODUTO DE ORIGEM ANIMAL";
  const pageOne = `
    <h3 class="official-section-title">1. PETI&Ccedil;&Atilde;O</h3>
    <div class="official-petition">
      <strong>SENHOR DIRETOR DA DIVIS&Atilde;O DE AGRONEG&Oacute;CIOS,</strong>
      <p>O estabelecimento abaixo qualificado, atrav&eacute;s do seu representante legal e do seu respons&aacute;vel t&eacute;cnico, requer que seja providenciado o atendimento da solicita&ccedil;&atilde;o especificada neste documento.</p>
    </div>
    <h3 class="official-section-title">2. IDENTIFICA&Ccedil;&Atilde;O DO ESTABELECIMENTO</h3>
    <div class="official-grid">
      ${officialField("RAZ&Atilde;O SOCIAL / NOME DO PRODUTOR", "establishment.legalName", { span: 12 })}
      ${officialField("NOME FANTASIA", "establishment.tradeName", { span: 12 })}
      ${officialField("CLASSIFICA&Ccedil;&Atilde;O DO ESTABELECIMENTO", "establishment.classification", { span: 12 })}
      ${officialField("S.I.M. DO ESTABELECIMENTO", "establishment.simNumber", { span: 12 })}
      ${officialField("CNPJ/CPF", "establishment.cnpj", { span: 7 })}
      ${officialField("INSCRI&Ccedil;&Atilde;O ESTADUAL", "establishment.stateRegistration", { span: 5 })}
      ${officialField("RESPONS&Aacute;VEL LEGAL PELO ESTABELECIMENTO", "legalResponsible.name", { span: 12 })}
    </div>
    <h3 class="official-section-title">3. LOCALIZA&Ccedil;&Atilde;O</h3>
    <div class="official-grid">
      ${officialField("ENDERE&Ccedil;O", "establishment.address", { span: 12 })}
      ${officialField("BAIRRO/LOCALIDADE", "establishment.district", { span: 4 })}
      ${officialField("MUNIC&Iacute;PIO", "establishment.city", { span: 3 })}
      ${officialField("UF", "establishment.state", { span: 1 })}
      ${officialField("CEP", "establishment.zip", { span: 4 })}
      ${officialField("E-MAIL", "establishment.email", { span: 8, type: "email" })}
      ${officialField("TELEFONE", "establishment.phone", { span: 4 })}
    </div>
  `;
  const pageTwo = `
    <h3 class="official-section-title">4. IDENTIFICA&Ccedil;&Atilde;O DO PRODUTO</h3>
    <div class="official-grid">
      ${officialField("NOME DO PRODUTO", `${productPath}.name`, { span: 12 })}
      ${officialField("MARCA", `${productPath}.brand`, { span: 12 })}
      ${officialField("N&ordm; REGISTRO DE R&Oacute;TULO", `${productPath}.labelRegistration`, { span: 12 })}
    </div>
    <h3 class="official-section-title">5. NATUREZA DA SOLICITA&Ccedil;&Atilde;O</h3>
    <div class="official-option-grid official-box">
      ${PRODUCT_NATURE_OPTIONS.map((option) => officialCheck(
        option,
        `${productPath}.natureOptions`,
        option,
        { selectedValues: inferredNature }
      )).join("")}
    </div>
    <h3 class="official-section-title">6. CARACTER&Iacute;STICAS DO R&Oacute;TULO E DA EMBALAGEM</h3>
    <div class="official-two-column-options">
      <div class="official-box">
        <strong>6.1 R&Oacute;TULO</strong>
        ${PRODUCT_LABEL_TYPE_OPTIONS.map((option) => officialCheck(option, `${productPath}.labelTypes`, option)).join("")}
        <label class="official-inline-entry">OUTRO: ${officialInput(`${productPath}.otherLabelType`, { inline: true, label: "Outro tipo de rotulo" })}</label>
      </div>
      <div class="official-box">
        <strong>6.2 EMBALAGEM PRIM&Aacute;RIA</strong>
        ${PRODUCT_PRIMARY_PACKAGE_OPTIONS.map((option) => officialCheck(option, `${productPath}.primaryPackagingTypes`, option)).join("")}
        <label class="official-inline-entry">OUTRA: ${officialInput(`${productPath}.otherPrimaryPackagingType`, {
          value: product.otherPrimaryPackagingType || product.packageType,
          inline: true,
          label: "Outro tipo de embalagem",
        })}</label>
      </div>
    </div>
    <div class="official-grid official-top-gap">
      ${officialField("INDICA&Ccedil;&Atilde;O DA DATA DE FABRICA&Ccedil;&Atilde;O, VALIDADE E LOTE", `${productPath}.dateLotIndication`, { span: 7, textarea: true, height: 14 })}
      ${officialField("QUANTIDADE DE PRODUTO POR EMBALAGEM", `${productPath}.packageQuantity`, { span: 5, textarea: true, height: 14 })}
      ${officialField("APRESENTA&Ccedil;&Atilde;O DAS INFORMA&Ccedil;&Otilde;ES DE ROTULAGEM", `${productPath}.labelingPresentation`, {
        value: product.labelingPresentation || product.labelFeatures,
        span: 12,
        textarea: true,
        height: 15,
      })}
    </div>
    <h3 class="official-section-title">7. COMPOSI&Ccedil;&Atilde;O DO PRODUTO</h3>
    <table class="official-data-table official-composition-table">
      <thead><tr><th>TIPO</th><th>MAT&Eacute;RIA-PRIMA / INGREDIENTE</th><th>kg ou L</th><th>%</th></tr></thead>
      <tbody>${Array.from({ length: 10 }, (_, index) => `
        <tr>
          <td class="official-fixed-cell">${index < 5 ? "MAT&Eacute;RIA-PRIMA" : "INGREDIENTE"}</td>
          <td>${officialTableInput(`${productPath}.compositionRows.${index}.ingredient`, { label: `Componente ${index + 1}` })}</td>
          <td>${officialTableInput(`${productPath}.compositionRows.${index}.amount`, { label: `Quantidade do componente ${index + 1}` })}</td>
          <td>${officialTableInput(`${productPath}.compositionRows.${index}.pct`, { label: `Percentual do componente ${index + 1}` })}</td>
        </tr>
      `).join("")}</tbody>
    </table>
  `;
  const pageThree = `
    <h3 class="official-section-title">8. INFORMA&Ccedil;&Atilde;O NUTRICIONAL</h3>
    <div class="official-grid">
      ${officialField("QUANTIDADE POR POR&Ccedil;&Atilde;O DE", `${productPath}.nutritionPortion`, { span: 12 })}
    </div>
    <table class="official-data-table official-nutrition-table">
      <thead><tr><th>NUTRIENTE</th><th>QUANTIDADE</th><th>%</th></tr></thead>
      <tbody>${NUTRITION_LABELS.map((label, index) => `
        <tr>
          <td class="official-fixed-cell">${label.toUpperCase()}</td>
          <td>${officialTableInput(`${productPath}.nutritionRows.${index}.qty`, { label: `Quantidade de ${label}` })}</td>
          <td>${officialTableInput(`${productPath}.nutritionRows.${index}.pct`, { label: `Percentual de ${label}` })}</td>
        </tr>
      `).join("")}</tbody>
    </table>
    <h3 class="official-section-title">9. PROCESSO DE FABRICA&Ccedil;&Atilde;O</h3>
    ${officialTextarea(`${productPath}.manufacturingProcess`, { height: 14, label: "Processo de fabricacao" })}
    <h3 class="official-section-title">10. PROCESSO DE EMBALAGEM</h3>
    <p class="official-instruction">Nos casos de registro ou altera&ccedil;&atilde;o de r&oacute;tulo, anexar o leiaute do r&oacute;tulo do produto com assinatura e carimbo da empresa e de seu respons&aacute;vel t&eacute;cnico.</p>
    ${officialTextarea(`${productPath}.packagingProcess`, { height: 12, label: "Processo de embalagem" })}
    <h3 class="official-section-title">11. CONDI&Ccedil;&Otilde;ES DE ARMAZENAMENTO</h3>
    ${officialTextarea(`${productPath}.storageConditions`, {
      value: product.storageConditions || product.conservation,
      height: 9,
      label: "Condicoes de armazenamento",
    })}
    <h3 class="official-section-title">12. MEDIDAS DE CONTROLE DE QUALIDADE</h3>
    ${officialTextarea(`${productPath}.qualityControls`, {
      value: product.qualityControls || product.notes || state.production.qualityControls,
      height: 9,
      label: "Medidas de controle de qualidade",
    })}
    <h3 class="official-section-title">13. TRANSPORTE E EXPEDI&Ccedil;&Atilde;O DO PRODUTO PARA O MERCADO CONSUMIDOR</h3>
    ${officialTextarea(`${productPath}.marketTransport`, {
      value: product.marketTransport || state.production.transport,
      height: 9,
      label: "Transporte e expedicao",
    })}
    ${officialSignatureBlock({
      path: `${productPath}.signaturePlaceDate`,
      left: "CARIMBO E ASSINATURA DO RESPONS&Aacute;VEL LEGAL DA FIRMA",
      right: "CARIMBO E ASSINATURA DO RESPONS&Aacute;VEL PELO PROJETO",
    })}
  `;
  return `${picker}<div class="official-form official-document">
    ${officialDocumentPage("IV", title, 1, 3, pageOne, "official-product-page")}
    ${officialDocumentPage("IV", title, 2, 3, pageTwo, "official-product-page")}
    ${officialDocumentPage("IV", title, 3, 3, pageThree, "official-product-page")}
  </div>`;
}

function fiscalIdentitySection(subjectLabel) {
  return `
    <h3 class="official-section-title">1. DADOS DO ${subjectLabel}</h3>
    <div class="official-grid">
      ${officialField("NOME (Raz&atilde;o Social/Pessoa F&iacute;sica):", "establishment.legalName", { span: 12, owner: "sim" })}
      ${officialField("CNPJ/CPF:", "establishment.cnpj", { span: 7, owner: "sim" })}
      ${officialField("REGISTRO NO S.I.M.:", "establishment.simNumber", { span: 5, owner: "sim" })}
      ${officialField("ENDERE&Ccedil;O:", "establishment.address", { span: 12, owner: "sim" })}
      ${officialField("BAIRRO:", "establishment.district", { span: 3, owner: "sim" })}
      ${officialField("MUNIC&Iacute;PIO:", "establishment.city", { span: 4, owner: "sim" })}
      ${officialField("UF:", "establishment.state", { span: 1, owner: "sim" })}
      ${officialField("CEP:", "establishment.zip", { span: 4, owner: "sim" })}
    </div>
    <h3 class="official-section-title">2. INFORMA&Ccedil;&Otilde;ES DO RESPONS&Aacute;VEL PELO ESTABELECIMENTO</h3>
    <div class="official-grid">
      ${officialField("RESPONS&Aacute;VEL LEGAL:", "legalResponsible.name", { span: 8, owner: "sim" })}
      ${officialField("CPF:", "legalResponsible.cpf", { span: 4, owner: "sim" })}
    </div>
  `;
}

function fiscalSignatureSection(subjectLabel) {
  return `
    <div class="official-fiscal-signatures">
      <div>
        <strong>LOCAL, DATA E ASSINATURA</strong>
        ${officialInput("fiscalAct.signaturePlaceDate", { owner: "sim", label: "Local e data" })}
        <span class="official-signature-line"></span>
        <label>Nome do fiscal: ${officialInput("fiscalAct.inspectorName", { inline: true, owner: "sim", label: "Nome do fiscal" })}</label>
        <label>Matr&iacute;cula: ${officialInput("fiscalAct.inspectorRegistration", { inline: true, owner: "sim", label: "Matricula do fiscal" })}</label>
      </div>
      <div>
        <strong>CI&Ecirc;NCIA DO ${subjectLabel}</strong>
        <span class="official-signature-line official-fiscal-science-line"></span>
        <label>Nome: ${officialInput("fiscalAct.acknowledgedBy", { inline: true, owner: "sim", label: `Nome do ${subjectLabel.toLowerCase()}` })}</label>
        <label>CPF/RG: ${officialInput("fiscalAct.acknowledgedDocument", { inline: true, owner: "sim", label: `Documento do ${subjectLabel.toLowerCase()}` })}</label>
      </div>
    </div>
  `;
}

function fiscalCopiesNote() {
  return `<p class="official-copies-note">4 VIAS (1&ordf; via - infrator; 2&ordf; via - instru&ccedil;&atilde;o do processo; 3&ordf; via - arquivo no &oacute;rg&atilde;o competente; 4&ordf; via - permanece no bloco do agente de fiscaliza&ccedil;&atilde;o).</p>`;
}

function printInfraction() {
  const title = "AUTO DE INFRA&Ccedil;&Atilde;O";
  const pageOne = `
    ${fiscalIdentitySection("AUTUADO")}
    <h3 class="official-section-title">3. DA INFRA&Ccedil;&Atilde;O</h3>
    <div class="official-grid">
      ${officialField("N&uacute;mero do Auto de Infra&ccedil;&atilde;o:", "fiscalAct.number", { span: 12, owner: "sim" })}
      ${officialField("Local da Infra&ccedil;&atilde;o:", "fiscalAct.inspectionPlace", {
        span: 12,
        owner: "sim",
        value: state.fiscalAct.inspectionPlace || `${state.establishment.address}, ${state.establishment.district}`,
      })}
      ${officialField("Data da Infra&ccedil;&atilde;o:", "fiscalAct.date", { span: 6, owner: "sim", type: "date" })}
      ${officialField("Hor&aacute;rio de Constata&ccedil;&atilde;o da Infra&ccedil;&atilde;o:", "fiscalAct.time", { span: 6, owner: "sim", type: "time" })}
      ${officialField("Dispositivos Legais Infringidos:", "fiscalAct.legalBasis", { span: 12, owner: "sim", textarea: true, height: 25 })}
      ${officialField("Motivo da Autua&ccedil;&atilde;o:", "fiscalAct.facts", { span: 12, owner: "sim", textarea: true, height: 57 })}
    </div>
  `;
  const pageTwo = `
    <h3 class="official-section-title">4. MATERIAL APREENDIDO</h3>
    <div class="official-grid">
      ${officialField("Caracteriza&ccedil;&atilde;o:", "fiscalAct.seizedMaterial", { span: 12, owner: "sim", textarea: true, height: 23 })}
      ${officialField("Destino dado:", "fiscalAct.seizedDestination", { span: 12, owner: "sim", textarea: true, height: 20 })}
    </div>
    <h3 class="official-section-title">5. OUTRAS INFORMA&Ccedil;&Otilde;ES</h3>
    <p class="official-instruction">Descrever minuciosamente os fatos em ordem cronol&oacute;gica, os procedimentos adotados, o motivo de eventual condena&ccedil;&atilde;o, apreens&atilde;o ou inutiliza&ccedil;&atilde;o, hor&aacute;rios e demais informa&ccedil;&otilde;es relevantes.</p>
    ${officialTextarea("fiscalAct.otherInfo", { owner: "sim", height: 72, label: "Outras informacoes" })}
    <h3 class="official-section-title">6. ASSINATURAS DO AUTUANTE E DO AUTUADO</h3>
    ${fiscalSignatureSection("AUTUADO")}
    <h3 class="official-section-title">7. TESTEMUNHAS</h3>
    <div class="official-witness-grid">
      <div>
        <span class="official-signature-line"></span>
        <label>Nome: ${officialInput("fiscalAct.witnessOneName", { inline: true, owner: "sim", label: "Nome da primeira testemunha" })}</label>
        <label>CPF/RG: ${officialInput("fiscalAct.witnessOneDocument", { inline: true, owner: "sim", label: "Documento da primeira testemunha" })}</label>
      </div>
      <div>
        <span class="official-signature-line"></span>
        <label>Nome: ${officialInput("fiscalAct.witnessTwoName", { inline: true, owner: "sim", label: "Nome da segunda testemunha" })}</label>
        <label>CPF/RG: ${officialInput("fiscalAct.witnessTwoDocument", { inline: true, owner: "sim", label: "Documento da segunda testemunha" })}</label>
      </div>
    </div>
    ${fiscalCopiesNote()}
  `;
  return `<div class="official-form official-document">
    ${officialDocumentPage("V", title, 1, 2, pageOne, "official-fiscal-page")}
    ${officialDocumentPage("V", title, 2, 2, pageTwo, "official-fiscal-page")}
  </div>`;
}

function printWarning() {
  const title = "TERMO DE ADVERT&Ecirc;NCIA";
  const pageOne = `
    ${fiscalIdentitySection("ADVERTIDO")}
    <h3 class="official-section-title">3. DADOS DA FISCALIZA&Ccedil;&Atilde;O</h3>
    <div class="official-grid">
      ${officialField("LOCAL ONDE FOI REALIZADA A FISCALIZA&Ccedil;&Atilde;O:", "fiscalAct.inspectionPlace", {
        span: 12,
        owner: "sim",
        value: state.fiscalAct.inspectionPlace || `${state.establishment.address}, ${state.establishment.district}`,
      })}
      ${officialField("DATA:", "fiscalAct.date", { span: 6, owner: "sim", type: "date" })}
      ${officialField("HOR&Aacute;RIO:", "fiscalAct.time", { span: 6, owner: "sim", type: "time" })}
    </div>
    <h3 class="official-section-title">4. DAS INFRA&Ccedil;&Otilde;ES</h3>
    <p class="official-instruction">Na fiscaliza&ccedil;&atilde;o realizada no estabelecimento acima identificado foram constatadas as infra&ccedil;&otilde;es tipificadas nos seguintes dispositivos da Lei Complementar n&ordm; 84/2024:</p>
    <table class="official-data-table">
      <thead><tr><th>Art.</th><th>Inciso</th></tr></thead>
      <tbody>${Array.from({ length: 4 }, (_, index) => `
        <tr>
          <td>${officialTableInput(`fiscalAct.infringementRows.${index}.article`, { owner: "sim", label: `Artigo ${index + 1}` })}</td>
          <td>${officialTableInput(`fiscalAct.infringementRows.${index}.item`, { owner: "sim", label: `Inciso ${index + 1}` })}</td>
        </tr>
      `).join("")}</tbody>
    </table>
    <h3 class="official-section-title">5. CIRCUNST&Acirc;NCIAS ATENUANTES E AGRAVANTES</h3>
    <div class="official-table-label">Atenuantes:</div>
    ${officialTextarea("fiscalAct.attenuatingAggravating", { owner: "sim", height: 31, label: "Circunstancias atenuantes" })}
  `;
  const pageTwo = `
    <div class="official-table-label">Agravantes:</div>
    ${officialTextarea("fiscalAct.aggravating", { owner: "sim", height: 39, label: "Circunstancias agravantes" })}
    <h3 class="official-section-title">6. NOTIFICA&Ccedil;&Atilde;O E ORIENTA&Ccedil;&Atilde;O</h3>
    <div class="official-fixed-copy">
      Considerando ser prim&aacute;rio ou n&atilde;o ter agido com dolo ou m&aacute;-f&eacute;, o notificado acima qualificado fica advertido quanto &agrave; constata&ccedil;&atilde;o das infra&ccedil;&otilde;es apontadas e orientado a san&aacute;-las no prazo de
      ${officialInput("fiscalAct.warningDeadlineDays", { inline: true, owner: "sim", label: "Prazo em dias" })}
      dias, a contar da data de ci&ecirc;ncia desta advert&ecirc;ncia, sob pena de ser lavrado o competente Auto de Infra&ccedil;&atilde;o e aplicadas as penalidades previstas na legisla&ccedil;&atilde;o vigente.
    </div>
    <div class="official-table-label">Orienta&ccedil;&otilde;es complementares:</div>
    ${officialTextarea("fiscalAct.notification", { owner: "sim", height: 48, label: "Orientacoes complementares" })}
    <h3 class="official-section-title">7. ASSINATURAS</h3>
    ${fiscalSignatureSection("ADVERTIDO")}
    ${fiscalCopiesNote()}
  `;
  return `<div class="official-form official-document">
    ${officialDocumentPage("VI", title, 1, 2, pageOne, "official-fiscal-page")}
    ${officialDocumentPage("VI", title, 2, 2, pageTwo, "official-fiscal-page")}
  </div>`;
}

function printSeizure() {
  const title = "AUTO DE APREENS&Atilde;O";
  const pageOne = `
    ${fiscalIdentitySection("INFRATOR")}
    <h3 class="official-section-title">3. DADOS DA APREENS&Atilde;O</h3>
    <div class="official-grid">
      ${officialField("LOCAL ONDE FOI REALIZADA A APREENS&Atilde;O:", "fiscalAct.inspectionPlace", {
        span: 12,
        owner: "sim",
        value: state.fiscalAct.inspectionPlace || `${state.establishment.address}, ${state.establishment.district}`,
      })}
      ${officialField("DATA:", "fiscalAct.date", { span: 6, owner: "sim", type: "date" })}
      ${officialField("HOR&Aacute;RIO:", "fiscalAct.time", { span: 6, owner: "sim", type: "time" })}
    </div>
    <div class="official-table-label">Foram apreendidos os seguintes bens e/ou produtos:</div>
    <table class="official-data-table">
      <thead><tr><th>Quantidade</th><th>Unidade</th><th>Descri&ccedil;&atilde;o</th></tr></thead>
      <tbody>${Array.from({ length: 4 }, (_, index) => `
        <tr>
          <td>${officialTableInput(`fiscalAct.seizedItemRows.${index}.quantity`, { owner: "sim", label: `Quantidade apreendida ${index + 1}` })}</td>
          <td>${officialTableInput(`fiscalAct.seizedItemRows.${index}.unit`, { owner: "sim", label: `Unidade apreendida ${index + 1}` })}</td>
          <td>${officialTableInput(`fiscalAct.seizedItemRows.${index}.description`, {
            owner: "sim",
            value: officialPathValue(`fiscalAct.seizedItemRows.${index}.description`) || (index === 0 ? state.fiscalAct.seizedMaterial : ""),
            label: `Descricao do item apreendido ${index + 1}`,
          })}</td>
        </tr>
      `).join("")}</tbody>
    </table>
    <h3 class="official-section-title">4. MOTIVO DA APREENS&Atilde;O</h3>
    <div class="official-grid">
      ${officialField("Dispositivos legais infringidos:", "fiscalAct.legalBasis", { span: 12, owner: "sim", textarea: true, height: 25 })}
      ${officialField("Circunst&acirc;ncias da apreens&atilde;o:", "fiscalAct.facts", { span: 12, owner: "sim", textarea: true, height: 43 })}
    </div>
    <h3 class="official-section-title">5. INFORMA&Ccedil;&Atilde;O AO INFRATOR</h3>
  `;
  const pageTwo = `
    <div class="official-fixed-copy">
      Os bens e/ou produtos apreendidos ficar&atilde;o, pelo prazo legal, depositados no local abaixo indicado, at&eacute; a regulariza&ccedil;&atilde;o do motivo determinante para a apreens&atilde;o ou, n&atilde;o ocorrendo, a sua destina&ccedil;&atilde;o final na forma da legisla&ccedil;&atilde;o vigente:
    </div>
    ${officialTextarea("fiscalAct.seizedDestination", { owner: "sim", height: 70, label: "Local de deposito dos bens apreendidos" })}
    <h3 class="official-section-title">6. ASSINATURAS</h3>
    ${fiscalSignatureSection("INFRATOR")}
    ${fiscalCopiesNote()}
  `;
  return `<div class="official-form official-document">
    ${officialDocumentPage("VII", title, 1, 2, pageOne, "official-fiscal-page")}
    ${officialDocumentPage("VII", title, 2, 2, pageTwo, "official-fiscal-page")}
  </div>`;
}

function printFiscal(title) {
  if (title === "TERMO DE ADVERTENCIA") return printWarning();
  if (title === "AUTO DE APREENSAO") return printSeizure();
  return printInfraction();
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
    accounts: renderAccounts,
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
  document.querySelectorAll("[data-view]").forEach((el) => {
    el.addEventListener("click", () => setView(el.dataset.view, el.dataset.formFocus || ""));
  });
  document.querySelectorAll("[data-preview-account]").forEach((el) => {
    el.addEventListener("click", () => startAccountPreview(el.dataset.previewAccount));
  });
  document.querySelector("[data-exit-preview]")?.addEventListener("click", exitAccountPreview);
  document.querySelectorAll("[data-path]").forEach((el) => {
    const eventName = el.tagName === "SELECT" ? "change" : "input";
    el.addEventListener(eventName, () => update(el.dataset.path, el.value));
  });
  document.querySelectorAll(".official-fill-textarea").forEach((el) => {
    autoSizeOfficialTextarea(el);
    el.addEventListener("input", () => autoSizeOfficialTextarea(el));
  });
  document.querySelectorAll("[data-official-choice-path]").forEach((el) => {
    el.addEventListener("change", () => {
      update(el.dataset.officialChoicePath, el.value);
      if (el.dataset.officialParentPath) {
        update(el.dataset.officialParentPath, el.dataset.officialParentValue || "");
        document.querySelectorAll(
          `[data-official-choice-path="${el.dataset.officialParentPath}"]`
        ).forEach((choice) => {
          choice.checked = false;
        });
      }
      if (
        el.dataset.officialChoicePath === "application.actType" &&
        comparableOfficialValue(el.value) !== "alteracao cadastral"
      ) {
        update("application.cadastralChangeType", "");
        document.querySelectorAll(
          '[data-official-choice-path="application.cadastralChangeType"]'
        ).forEach((choice) => {
          choice.checked = false;
        });
      }
    });
  });
  document.querySelectorAll("[data-official-array-path]").forEach((el) => {
    el.addEventListener("change", () => {
      const current = officialPathValue(el.dataset.officialArrayPath);
      const values = Array.isArray(current) ? [...current] : [];
      const normalizedValue = comparableOfficialValue(el.value);
      const filtered = values.filter(
        (value) => comparableOfficialValue(value) !== normalizedValue
      );
      if (el.checked) filtered.push(el.value);
      update(el.dataset.officialArrayPath, filtered);
    });
  });
  document.querySelectorAll("[data-official-cnae]").forEach((el) => {
    el.addEventListener("input", () => {
      const code = document.querySelector('[data-official-cnae="code"]')?.value || "";
      const activity = document.querySelector('[data-official-cnae="activity"]')?.value || "";
      update(
        "establishment.cnae",
        [code, activity].filter(Boolean).join(" - ")
      );
    });
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
  document.querySelectorAll("[data-pnature]").forEach((el) => el.addEventListener("change", toggleNature));
  document.querySelectorAll("[data-poption]").forEach((el) => el.addEventListener("change", toggleProductOption));
  document.querySelectorAll("[data-pcomp]").forEach((el) => {
    el.addEventListener(el.tagName === "SELECT" ? "change" : "input", updateCompRow);
  });
  document.querySelectorAll("[data-pnut]").forEach((el) => el.addEventListener("input", updateNutRow));
  document.querySelectorAll("[data-pnutport]").forEach((el) => el.addEventListener("input", updateNutPortion));
  document.querySelectorAll("[data-product-action]").forEach((el) => {
    el.addEventListener("click", () => handleProductAction(el.dataset.productAction, el.dataset.productId, el.dataset.rowId));
  });
  document.querySelectorAll("[data-print-product]").forEach((el) => {
    el.addEventListener("click", () => {
      state.printProductId = el.dataset.printProduct;
      saveState();
      render();
    });
  });
  document.querySelectorAll("[data-upload-doc]").forEach((el) => {
    el.addEventListener("change", () => uploadDocument(el.dataset.uploadDoc, el.files[0]));
  });
  document.querySelectorAll("[data-open-upload]").forEach((el) => {
    el.addEventListener("click", () => openUpload(el.dataset.openUpload));
  });
  const modalBackdrop = document.querySelector(".modal-backdrop");
  modalBackdrop?.addEventListener("click", (event) => {
    if (event.target !== event.currentTarget) return;
    activeUpload = null;
    render();
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

async function startAccountPreview(accountId) {
  try {
    const data = await api(`/accounts/${accountId}/preview`);
    previewAccount = data.account;
    state = normalizeState(deepMerge(structuredClone(initialState), data.state));
    state.role = previewAccount.role;
    state.view = "dashboard";
    notifications = data.notifications || [];
    render();
    toast(`Visualizando como ${previewAccount.name}. Nenhuma alteracao pode ser salva.`);
  } catch (error) {
    toast(error.message);
  }
}

async function exitAccountPreview() {
  previewAccount = null;
  try {
    const data = await api("/state");
    state = normalizeState(deepMerge(structuredClone(initialState), data.state));
    state.role = session.role;
    state.view = "accounts";
    notifications = data.notifications || [];
    await loadRegistry();
  } catch (error) {
    toast(error.message);
  }
  render();
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
    state = normalizeState(deepMerge(structuredClone(initialState), remote.state));
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
    state = normalizeState(deepMerge(structuredClone(initialState), data.state));
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
  if (!product || isProductLocked(product) || state.role !== "establishment") return;
  product[event.target.dataset.field] = event.target.value;
  saveState();
}

function editableProduct(id) {
  const product = state.products.find((item) => item.id === id);
  if (!product || isProductLocked(product) || state.role !== "establishment") return null;
  return product;
}

function toggleNature(event) {
  const product = editableProduct(event.target.dataset.pnature);
  if (!product) return;
  if (!Array.isArray(product.natureOptions)) product.natureOptions = [];
  const value = event.target.value;
  if (event.target.checked) {
    if (!product.natureOptions.includes(value)) product.natureOptions.push(value);
  } else {
    product.natureOptions = product.natureOptions.filter((item) => item !== value);
  }
  saveState();
}

function toggleProductOption(event) {
  const product = editableProduct(event.target.dataset.poption);
  const field = event.target.dataset.poptionField;
  if (!product || !field) return;
  if (!Array.isArray(product[field])) product[field] = [];
  const value = event.target.value;
  if (event.target.checked) {
    if (!product[field].includes(value)) product[field].push(value);
  } else {
    product[field] = product[field].filter((item) => item !== value);
  }
  saveState();
}

function updateCompRow(event) {
  const product = editableProduct(event.target.dataset.pcomp);
  if (!product) return;
  const row = (product.compositionRows || []).find((item) => item.id === event.target.dataset.cid);
  if (!row) return;
  row[event.target.dataset.cfield] = event.target.value;
  saveState();
}

function updateNutRow(event) {
  const product = editableProduct(event.target.dataset.pnut);
  if (!product) return;
  if (!Array.isArray(product.nutritionRows)) product.nutritionRows = defaultNutritionRows();
  const index = Number(event.target.dataset.nidx);
  if (!product.nutritionRows[index]) return;
  product.nutritionRows[index][event.target.dataset.nfield] = event.target.value;
  saveState();
}

function updateNutPortion(event) {
  const product = editableProduct(event.target.dataset.pnutport);
  if (!product) return;
  product.nutritionPortion = event.target.value;
  saveState();
}

function handleProductAction(action, productId, rowId) {
  const product = state.products.find((item) => item.id === productId);
  if (!product) return;
  const who = state.role === "sim" ? "Lucas Marcelino Campos Ferreira" : state.establishment.tradeName;
  if (action === "print") {
    state.printProductId = product.id;
    state.printForm = "produto";
    state.view = "print";
    saveState();
    render();
    return;
  }
  if (action === "submit") {
    if (isProductLocked(product)) return;
    if (!product.labelUploadId) {
      toast("Anexe o rotulo do produto antes de enviar para analise.");
      return;
    }
    product.status = "Em analise";
    product.submittedAt = new Date().toISOString();
    record(`Produto enviado para analise: ${product.name || "sem nome"}.`, who);
    notifications.unshift({
      title: "Produto enviado para analise",
      message: `${state.establishment.tradeName} enviou "${product.name || "produto sem nome"}" para analise do SIM.`,
      created_at: new Date().toISOString(),
    });
    toast("Produto enviado para analise do SIM.");
  }
  if (action === "approve") {
    if (state.role !== "sim") return;
    product.status = "Aprovado";
    product.approvedAt = new Date().toISOString();
    product.approvedBy = who;
    product.simNote = "";
    record(`Produto aprovado: ${product.name || "sem nome"}.`, who);
    notifications.unshift({
      title: "Produto aprovado",
      message: `"${product.name || "Produto"}" foi aprovado pelo SIM. O cadastro fica travado; qualquer alteracao exige nova versao.`,
      created_at: new Date().toISOString(),
    });
    toast("Produto aprovado.");
  }
  if (action === "request-changes") {
    if (state.role !== "sim") return;
    const note = window.prompt("Descreva o que precisa ser corrigido neste produto:", product.simNote || "");
    if (note === null) return;
    product.status = "Correcoes solicitadas";
    product.simNote = note;
    record(`Correcoes solicitadas no produto: ${product.name || "sem nome"}.`, who);
    notifications.unshift({
      title: "Correcoes solicitadas em produto",
      message: `O SIM pediu ajustes em "${product.name || "produto"}": ${note}`,
      created_at: new Date().toISOString(),
    });
    toast("Correcoes solicitadas.");
  }
  if (action === "revise") {
    if (state.role !== "establishment" || product.status !== "Aprovado") return;
    const revision = {
      ...structuredClone(product),
      id: crypto.randomUUID(),
      version: (product.version || 1) + 1,
      previousVersionId: product.id,
      supersededBy: null,
      supersededAt: null,
      status: "Rascunho",
      approvedAt: null,
      approvedBy: null,
      simNote: "",
      submittedAt: null,
    };
    product.supersededBy = revision.id;
    product.supersededAt = new Date().toISOString();
    state.products.push(revision);
    record(`Nova versao aberta a partir do produto aprovado: ${product.name || "sem nome"} (v${revision.version}).`, who);
    toast("Nova versao criada. A versao aprovada anterior ficou preservada no historico.");
  }
  if (action === "add-comp-row") {
    if (isProductLocked(product) || state.role !== "establishment") return;
    if (!Array.isArray(product.compositionRows)) product.compositionRows = [];
    product.compositionRows.push({ id: crypto.randomUUID(), kind: "Materia-prima", ingredient: "", amount: "", pct: "" });
  }
  if (action === "del-comp-row") {
    if (isProductLocked(product) || state.role !== "establishment") return;
    product.compositionRows = (product.compositionRows || []).filter((item) => item.id !== rowId);
  }
  if (action === "cancel-submit") {
    if (state.role !== "establishment" || product.status !== "Em analise") return;
    product.status = "Rascunho";
    product.submittedAt = null;
    record(`Envio cancelado para edicao: ${product.name || "sem nome"}.`, who);
    toast("Envio cancelado. Produto voltou para rascunho e pode ser editado.");
  }
  if (action === "delete") {
    if (state.role !== "establishment" || product.status === "Aprovado" || product.supersededBy) return;
    if (!window.confirm(`Excluir o produto "${product.name || "sem nome"}"? O pedido sera removido da sua lista.`)) return;
    state.products = state.products.filter((item) => item.id !== product.id);
    record(`Produto excluido do protocolo: ${product.name || "sem nome"}.`, who);
    toast("Produto excluido.");
  }
  saveState();
  render();
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
  if (action === "print") printDocument("paper");
  if (action === "print-digital") printDocument("digital");
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
      version: 1,
      previousVersionId: null,
      supersededBy: null,
      supersededAt: null,
      approvedAt: null,
      approvedBy: null,
      simNote: "",
      submittedAt: null,
      conservation: "",
      notes: "",
      requestNature: "Registro de produto e rotulo",
      natureOptions: [],
      labelTypes: [],
      primaryPackagingTypes: [],
      otherLabelType: "",
      otherPrimaryPackagingType: "",
      dateLotIndication: "",
      packageQuantity: "",
      labelingPresentation: "",
      packageType: "",
      labelRegistration: "",
      labelFeatures: "",
      composition: "",
      compositionRows: [],
      nutrition: "",
      nutritionPortion: "",
      nutritionRows: defaultNutritionRows(),
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
