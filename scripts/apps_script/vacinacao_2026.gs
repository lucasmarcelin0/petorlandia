/**
 * ==============================================================================
 * SISTEMA PETORLÂNDIA - VACINAÇÃO 2026 & CONTROLE COMPLETO
 * ==============================================================================
 *
 * Cópia versionada do Apps Script da planilha de vacinação. Editar AQUI e colar
 * no editor de scripts da planilha, para que a correção não se perca.
 *
 * Correções desta versão (ver PR "Status PMO: confere a linha da aba mestre"):
 *
 * 1. DETECÇÃO DA COLUNA DE CARIMBO. A aba "Vacinação 2026" vem do formulário e
 *    tem o carimbo de data/hora na coluna A — o nome do tutor está na B. As
 *    funções liam tudo deslocado em uma coluna: o link do mapa saía como
 *    "Raquel Feliciano Rua 4, A, 1299" (nome do tutor no lugar da rua) e a
 *    mensagem de WhatsApp levava endereço e data trocados. Agora o offset é
 *    detectado por aba, então as abas com e sem carimbo funcionam.
 *
 * 2. REORDENAÇÃO NÃO EMBARALHA MAIS NOTA E COR. `routeOptimizeByCluster` usava
 *    clearContent(), que apaga valores mas NÃO apaga notas nem cor de fundo:
 *    depois de reordenar, a nota e a cor de status ficavam na posição antiga
 *    enquanto o tutor mudava de linha. Agora nota e cor viajam junto com a
 *    linha.
 *
 * 3. NENHUMA LINHA É DESCARTADA na otimização (as não classificadas vão para o
 *    fim) e as colunas "Cluster"/"Bairro Normalizado" são reaproveitadas em vez
 *    de duplicadas a cada execução.
 *
 * Depois de reordenar a aba mestre, rode "🔄 Atualizar status (PetOrlândia)":
 * é o que reencaixa o Status PMO nas novas posições.
 */

// ==============================================================================
// 1. MENU PRINCIPAL INTEGRADO
// ==============================================================================
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  try {
    organizarDiasSeAbasMudaram_(SpreadsheetApp.getActiveSpreadsheet());
  } catch (e) {
    // Quem só tem acesso de leitura não pode gravar no Controle de doses.
  }

  ui.createMenu("🐾 Vacinação 2026")
    .addItem("🔍 Gerar Relatório de Duplicidades e Histórico", "gerarRelatorioDuplicidades")
    .addSeparator()
    .addItem("🔄 Otimizar Rotas por Cluster", "routeOptimizeByCluster")
    .addItem("📍 Medir cobertura no atlas (PetOrlândia)", "medirCoberturaAtlas")
    .addItem("🗺️ Gerar Links do Google Maps", "gerarLinksMapa")
    .addSeparator()
    .addItem("📇 Gerar contatos para WhatsApp", "gerarContatosWhatsApp")
    .addSeparator()
    .addItem("📱 Adicionar Links WhatsApp", "addWhatsAppLinks")
    .addItem("🗑️ Limpar Links WhatsApp", "clearWhatsAppLinks")
    .addItem("📅 Corrigir datas invertidas nas abas", "corrigirDatasInvertidas")
    .addSeparator()
    .addItem("🔄 Sincronizar com Planilha Origem", "sincronizarPlanilhas")
    .addSeparator()
    .addItem("🔄 Atualizar status (PetOrlândia)", "atualizarStatusPMO")
    .addItem("🔗 Conferir links do Status PMO", "conferirQuadroStatusPMOAgora")
    .addItem("💉 Compilar Controle de doses", "compilarControleDeDoses")
    .addItem("📆 Preparar meses no Controle de doses", "prepararMesesNoControleDeDoses")
    .addItem("🗓️ Organizar dias no Controle de doses", "organizarDiasNoControleDeDoses")
    .addSeparator()
    .addItem("🐛 Debug Classificação de Endereços", "debugAddressClassification")
    .addToUi();
}

// ==============================================================================
// 0. DETECÇÃO DA COLUNA DE CARIMBO (a correção que faltava)
// ==============================================================================
/**
 * Quantas colunas existem ANTES do nome do tutor.
 *
 * 1 nas abas que vêm do formulário (coluna A = carimbo de data/hora, B = nome),
 * 0 nas abas digitadas à mão (A = nome). A decisão é por MAIORIA das linhas de
 * dados: uma linha solta com data no lugar do nome não muda o layout da aba.
 */
function detectarOffset_(dados) {
  if (!dados || dados.length < 2) return 0;

  let comCarimbo = 0;
  let analisadas = 0;

  for (let i = 1; i < dados.length && analisadas < 25; i++) {
    const primeira = dados[i][0];
    const segunda = dados[i].length > 1 ? dados[i][1] : "";
    if (!primeira && !segunda) continue;

    analisadas++;
    if (pareceCarimbo_(primeira) && String(segunda || "").trim() !== "") {
      comCarimbo++;
    }
  }

  if (analisadas === 0) return 0;
  return (comCarimbo / analisadas) >= 0.6 ? 1 : 0;
}

function pareceCarimbo_(valor) {
  if (valor instanceof Date) return true;
  const texto = String(valor || "").trim();
  if (!texto) return false;
  // 17/08/2026 ou 17/08/2026 14:42:13
  return /^\d{1,2}\/\d{1,2}\/\d{2,4}(\s+\d{1,2}:\d{2}(:\d{2})?)?$/.test(texto);
}

/** Índices de coluna já com o offset da aba aplicado. */
function colunas_(offset) {
  return {
    carimbo: offset ? 0 : -1,
    tutor: 0 + offset,
    endereco: 1 + offset,
    numero: 2 + offset,
    complemento: 3 + offset,
    bairro: 4 + offset,
    telefone1: 5 + offset,
    telefone2: 6 + offset,
    caes: 7 + offset,
    gatos: 8 + offset,
    animais: 9 + offset,
    obs: 10 + offset,
    data: 16 + offset,
    turno: 17 + offset
  };
}

// ==============================================================================
// 2. MÓDULO: RELATÓRIO DE DUPLICIDADES E HISTÓRICO (V3.1)
// ==============================================================================
var CONFIG_DUPLICIDADES = {
  nomeAbaRelatorio: "Relatório de Duplicidades",
  abasIgnoradas: ["Padrão", "copia", "Teste do bot", "Relatório de Duplicidades", "Respostas ao formulário 1"],
  abasAgendamentoFixas: ["Inscrição a agendar", "Agendadas", "Vacinação 2026"],
  abaEncaixes: "Encaixes"
};

function gerarRelatorioDuplicidades() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const relatorioNome = CONFIG_DUPLICIDADES.nomeAbaRelatorio;

  let abaRelatorio = ss.getSheetByName(relatorioNome);
  if (!abaRelatorio) {
    abaRelatorio = ss.insertSheet(relatorioNome, 0);
  } else {
    abaRelatorio.clear();
  }

  const cabecalhos = ["Aba Origem", "Linha", "Tutor", "Telefone", "Bairro / Endereço", "Animais Informados", "Tipo de Alerta", "Detalhes / Ocorrência"];
  abaRelatorio.appendRow(cabecalhos);

  abaRelatorio.getRange("A1:H1")
    .setFontWeight("bold")
    .setBackground("#1a73e8")
    .setFontColor("#ffffff")
    .setHorizontalAlignment("center");

  const abas = ss.getSheets();
  const abasFuturas = [];
  const abasPassadas = [];

  for (let i = 0; i < abas.length; i++) {
    const nomeAba = abas[i].getName().trim();

    if (CONFIG_DUPLICIDADES.abasIgnoradas.indexOf(nomeAba) !== -1) continue;

    const isDataAba = /^\d+\s*-\s*\d{2}\/\d{2}(\/\d{2,4})?/.test(nomeAba) || /^\d{2}\/\d{2}(\/\d{2,4})?$/.test(nomeAba);
    const isFixa = CONFIG_DUPLICIDADES.abasAgendamentoFixas.indexOf(nomeAba) !== -1 || nomeAba === CONFIG_DUPLICIDADES.abaEncaixes;

    if (isDataAba || isFixa) {
      abasFuturas.push(nomeAba);
    } else {
      abasPassadas.push(nomeAba);
    }
  }

  const historicoVacinados = [];
  const todosTutoresFuturos = [];
  const resultadosParaImprimir = [];

  // 1. Histórico de vacinados (abas passadas)
  for (let p = 0; p < abasPassadas.length; p++) {
    const abaHist = ss.getSheetByName(abasPassadas[p]);
    if (!abaHist) continue;

    const dadosHist = abaHist.getDataRange().getValues();
    const col = colunas_(detectarOffset_(dadosHist));

    for (let r = 1; r < dadosHist.length; r++) {
      const tutor = normalizarTexto(dadosHist[r][col.tutor]);
      const tel1 = cleanPhoneNumber(dadosHist[r][col.telefone1]);
      const tel2 = cleanPhoneNumber(dadosHist[r][col.telefone2]);
      const animaisRaw = dadosHist[r][col.animais] || "";
      const obs = normalizarTexto(dadosHist[r][col.obs]);

      if (!tutor || tutor === "nome completo do tutor") continue;

      const isVacinado = (obs.indexOf("vacinad") !== -1 || obs.indexOf("imunizad") !== -1 || obs.indexOf("atendid") !== -1);
      if (isVacinado) {
        historicoVacinados.push({
          tutor: tutor,
          tel1: tel1,
          tel2: tel2,
          listaAnimais: extrairListaAnimais(animaisRaw),
          animaisOriginal: String(animaisRaw).trim(),
          aba: abasPassadas[p]
        });
      }
    }
  }

  // 2. Abas ativas/futuras
  for (let f = 0; f < abasFuturas.length; f++) {
    const nomeAbaAtual = abasFuturas[f];
    const abaAtual = ss.getSheetByName(nomeAbaAtual);
    if (!abaAtual) continue;

    const rangeAtual = abaAtual.getDataRange();
    const dados = rangeAtual.getValues();
    const col = colunas_(detectarOffset_(dados));
    const cores = (nomeAbaAtual === CONFIG_DUPLICIDADES.abaEncaixes) ? rangeAtual.getBackgrounds() : null;

    for (let rowIdx = 1; rowIdx < dados.length; rowIdx++) {
      const tutorOrig = String(dados[rowIdx][col.tutor] || "").trim();
      const tutorNorm = normalizarTexto(tutorOrig);
      const ruaOrig = String(dados[rowIdx][col.endereco] || "").trim();
      const numOrig = String(dados[rowIdx][col.numero] || "").trim();
      const bairroOrig = String(dados[rowIdx][col.bairro] || "").trim();

      const enderecoCompleto = [ruaOrig, numOrig, bairroOrig].filter(Boolean).join(", ");
      const enderecoNorm = normalizarTexto(enderecoCompleto);

      const tel1Orig = String(dados[rowIdx][col.telefone1] || "").trim();
      const tel2Orig = String(dados[rowIdx][col.telefone2] || "").trim();
      const tel1Limpo = cleanPhoneNumber(tel1Orig);
      const tel2Limpo = cleanPhoneNumber(tel2Orig);

      const animaisOrig = String(dados[rowIdx][col.animais] || "").trim();
      const listaAnimais = extrairListaAnimais(animaisOrig);
      const totalAnimais = (parseInt(dados[rowIdx][col.caes]) || 0) + (parseInt(dados[rowIdx][col.gatos]) || 0);

      if (!tutorNorm || tutorNorm === "nome completo do tutor") continue;

      if (nomeAbaAtual === CONFIG_DUPLICIDADES.abaEncaixes && cores) {
        const corFundo = (cores[rowIdx][0] || "").toLowerCase();
        const isBranco = (corFundo === "#ffffff" || corFundo === "#fff" || corFundo === "");
        if (!isBranco) continue;
      }

      const semTelefone = !tel1Limpo && !tel2Limpo;
      const semEndereco = !ruaOrig;
      const semAnimais = totalAnimais === 0 && listaAnimais.length === 0;

      if (semTelefone || semEndereco || semAnimais) {
        const pendencias = [];
        if (semTelefone) pendencias.push("Sem telefone válido");
        if (semEndereco) pendencias.push("Falta endereço");
        if (semAnimais) pendencias.push("Qtd de animais zerada");

        resultadosParaImprimir.push([
          nomeAbaAtual, rowIdx + 1, tutorOrig, tel1Orig || tel2Orig, enderecoCompleto, animaisOrig, "Dados Incompletos", pendencias.join(" | ")
        ]);
      }

      for (let h = 0; h < historicoVacinados.length; h++) {
        const hist = historicoVacinados[h];
        const mesmoTel = (tel1Limpo && (hist.tel1 === tel1Limpo || hist.tel2 === tel1Limpo)) ||
                         (tel2Limpo && (hist.tel1 === tel2Limpo || hist.tel2 === tel2Limpo));
        const mesmoTutor = (tutorNorm === hist.tutor);

        if (mesmoTel || mesmoTutor) {
          for (let a = 0; a < listaAnimais.length; a++) {
            const petAtual = listaAnimais[a];
            if (petAtual.length < 2) continue;

            if (hist.listaAnimais.indexOf(petAtual) !== -1) {
              resultadosParaImprimir.push([
                nomeAbaAtual, rowIdx + 1, tutorOrig, tel1Orig || tel2Orig, enderecoCompleto, animaisOrig,
                "Possível Já Vacinado",
                "Animal '" + petAtual + "' consta como vacinado na aba '" + hist.aba + "'"
              ]);
            }
          }
        }
      }

      todosTutoresFuturos.push({
        aba: nomeAbaAtual,
        linha: rowIdx + 1,
        tutorOrig: tutorOrig,
        tutorNorm: tutorNorm,
        tel1: tel1Limpo,
        tel2: tel2Limpo,
        telExibir: tel1Orig || tel2Orig,
        enderecoNorm: enderecoNorm,
        enderecoCompleto: enderecoCompleto,
        animaisOrig: animaisOrig,
        listaAnimais: listaAnimais
      });
    }
  }

  // 3. Duplicidades entre agendamentos futuros
  for (let i = 0; i < todosTutoresFuturos.length; i++) {
    for (let j = i + 1; j < todosTutoresFuturos.length; j++) {
      const item1 = todosTutoresFuturos[i];
      const item2 = todosTutoresFuturos[j];

      const mesmoTel = (item1.tel1 && (item1.tel1 === item2.tel1 || item1.tel1 === item2.tel2)) ||
                       (item1.tel2 && (item1.tel2 === item2.tel1 || item1.tel2 === item2.tel2));
      const mesmoTutorEnd = (item1.tutorNorm === item2.tutorNorm && item1.enderecoNorm !== "" && item1.enderecoNorm === item2.enderecoNorm);

      if (mesmoTel || mesmoTutorEnd) {
        const petsComuns = item1.listaAnimais.filter(function (pet) { return item2.listaAnimais.indexOf(pet) !== -1; });
        if (petsComuns.length > 0 || (item1.listaAnimais.length === 0 && item2.listaAnimais.length === 0)) {
          const detalhePet = petsComuns.length > 0 ? " (Pet(s): " + petsComuns.join(", ") + ")" : "";
          resultadosParaImprimir.push([
            item1.aba,
            item1.linha,
            item1.tutorOrig,
            item1.telExibir,
            item1.enderecoCompleto,
            item1.animaisOrig,
            "Inscrição Duplicada",
            "Mesmos dados encontrados na aba '" + item2.aba + "' (Linha " + item2.linha + ")" + detalhePet
          ]);
        }
      }
    }
  }

  if (resultadosParaImprimir.length > 0) {
    abaRelatorio.getRange(2, 1, resultadosParaImprimir.length, 8).setValues(resultadosParaImprimir);
  } else {
    abaRelatorio.appendRow(["-", "-", "Nenhum problema ou duplicidade encontrada!", "-", "-", "-", "-", "-"]);
  }

  abaRelatorio.setFrozenRows(1);
  abaRelatorio.getDataRange().setWrap(true);
  for (let colIdx = 1; colIdx <= 8; colIdx++) {
    abaRelatorio.autoResizeColumn(colIdx);
  }

  SpreadsheetApp.getActiveSpreadsheet().toast("Relatório concluído com " + resultadosParaImprimir.length + " alertas.", "🐾 PetOrlândia", 5);
}

// ==============================================================================
// 3. MÓDULO: OTIMIZAÇÃO DE ROTAS POR CLUSTERS E ENDEREÇOS
// ==============================================================================

// SISTEMA DE CLUSTERS COMPLETO
var CLUSTERS_VACINACAO = {
  // Vilinha (A) - PRIMEIRO
  "Jardim São Francisco": "A",
  "Cidade Jardim": "A",
  "Jardim São João": "A",
  "Jardim Cidade Alta": "A",
  "Jardim Júlio Bucci": "A",

  // Gruta (B) - SEGUNDO
  "Jardim Recreio": "B",
  "Jardim Ciranda": "B",
  "Jardim Paraíso": "B",
  "Jardim Anhanguera": "B",
  "Gruta": "B",
  "Jardim Nova Orlândia": "B",

  // Centro (C) - TERCEIRO
  "Centro": "C",
  "Vila Marcussi": "C",
  "Jardim Teixeira": "C",
  "Jardim Prado": "C",
  "Jardim Arantes Centro": "C",
  "Comove": "C",
  "Vila Comove": "C",
  "Jardim Bandeirantes": "C",

  // Parisi (D) - QUARTO
  "Jardim Jequitibá": "D",
  "Jardim Parisi": "D",
  "Jardim Santo Expedito": "D",
  "José Adalberto Morandini": "D",
  "Jardim Aroeira": "D",
  "Santa Helena": "D",
  "Birucão": "D",
  "Antônio Martins": "D",
  "Alto da Boa Vista": "D",

  // Santa Rita (E) - QUINTO
  "Jardim Santa Rita": "E",
  "Jardim Siena": "E",
  "Jardim Leonor Degiovani": "E",
  "Jardim Formoso": "E",
  "Jardim Boa Vista": "E",
  "Jardim Vista Linda": "E",
  "Jardim Benini": "E",
  "Jardim José Vieira Brazão": "E",

  // Morada do Sol (F) - SEXTO
  "Morada do Sol": "F",
  "Condomínio Quebec": "F",
  "Condomínio Toruino": "F",
  "Condomínio Paris": "F",
  "Parque Cecap": "F",
  "Max Define": "F",
  "Jardim das Flores": "F",
  "Jardim Paineiras": "F",
  "Jardim José Luiz Simões": "F",
  "1º De Maio": "F",
  "Jardim dos Servidores": "F",
  "Zita de Oliveira": "F",
  "Palmito": "F",

  // Timboré (T) - afastado da cidade: não entra na rota de nenhuma região
  "Jardim Timboré": "T",

  // Zona Rural (Z) - ÚLTIMO
  "Zona Rural": "Z",
  "Sitio": "Z",
  "Chácara": "Z",
  "Fazenda": "Z"
};

var VARIACOES_BAIRRO = {
  // Vilinha (A)
  "jardim sao francisco": "Jardim São Francisco",
  "sao francisco": "Jardim São Francisco",
  "jardim francisco": "Jardim São Francisco",
  "cidade jardim": "Cidade Jardim",
  "jardim sao joao": "Jardim São João",
  "sao joao": "Jardim São João",
  "jardim joao": "Jardim São João",
  "jardim cidade alta": "Jardim Cidade Alta",
  "cidade alta": "Jardim Cidade Alta",
  "vilinha": "Jardim Cidade Alta",
  "jardim julio bucci": "Jardim Júlio Bucci",
  "julio bucci": "Jardim Júlio Bucci",
  "bucci": "Jardim Júlio Bucci",

  // Gruta (B)
  "jardim recreio": "Jardim Recreio",
  "recreio": "Jardim Recreio",
  "jardim ciranda": "Jardim Ciranda",
  "ciranda": "Jardim Ciranda",
  "jardim paraiso": "Jardim Paraíso",
  "paraiso": "Jardim Paraíso",
  "jd paraiso": "Jardim Paraíso",
  "jardim anhanguera": "Jardim Anhanguera",
  "anhanguera": "Jardim Anhanguera",
  "gruta": "Gruta",
  "vila gruta": "Gruta",
  "jardim nova orlandia": "Jardim Nova Orlândia",
  "nova orlandia": "Jardim Nova Orlândia",
  "mariot": "Jardim Anhanguera",   // Praça Luiz Mariotto, Avenida 14

  // Centro (C)
  "centro": "Centro",
  "vila marcussi": "Vila Marcussi",
  "marcussi": "Vila Marcussi",
  "jardim teixeira": "Jardim Teixeira",
  "teixeira": "Jardim Teixeira",
  "texeira": "Jardim Teixeira",
  "jardim prado": "Jardim Prado",
  "prado": "Jardim Prado",
  "jardim arantes": "Jardim Arantes Centro",
  "jardim arantes centro": "Jardim Arantes Centro",
  "jd arantes": "Jardim Arantes Centro",
  "comove": "Comove",
  "vila comove": "Vila Comove",
  "jardim bandeirantes": "Jardim Bandeirantes",
  "bandeirantes": "Jardim Bandeirantes",

  // Parisi (D)
  "jardim jequitiba": "Jardim Jequitibá",
  "jequitiba": "Jardim Jequitibá",
  "jd jequitiba": "Jardim Jequitibá",
  "jardim parisi": "Jardim Parisi",
  "jd parisi": "Jardim Parisi",
  "j parisi": "Jardim Parisi",
  "parisi": "Jardim Parisi",
  "parise": "Jardim Parisi",
  "jardim santo expedito": "Jardim Santo Expedito",
  "santo expedito": "Jardim Santo Expedito",
  "adalberto morandini": "José Adalberto Morandini",
  "jose adalberto morandini": "José Adalberto Morandini",
  "morandi": "José Adalberto Morandini",
  "jardim aroeira": "Jardim Aroeira",
  "aroeira": "Jardim Aroeira",
  "santa helena": "Santa Helena",
  "birucao": "Birucão",
  "biruca": "Birucão",
  "antonio martins": "Antônio Martins",
  "ant martins": "Antônio Martins",
  "alto da boa vista": "Alto da Boa Vista",
  "alto boa vista": "Alto da Boa Vista",

  // Santa Rita (E)
  "jardim santa rita": "Jardim Santa Rita",
  "santa rita": "Jardim Santa Rita",
  "sta rita": "Jardim Santa Rita",
  "sata rita": "Jardim Santa Rita",
  "jardim siena": "Jardim Siena",
  "siena": "Jardim Siena",
  "zita siena": "Jardim Siena",
  "jardim formoso": "Jardim Formoso",
  "formoso": "Jardim Formoso",
  "jardim boa vista": "Jardim Boa Vista",
  "jd boa vista": "Jardim Boa Vista",
  "boa vista": "Jardim Boa Vista",
  "jardim vista linda": "Jardim Vista Linda",
  "vista linda": "Jardim Vista Linda",
  "jardim benini": "Jardim Benini",
  "jd benini": "Jardim Benini",
  "benini": "Jardim Benini",
  "benine": "Jardim Benini",
  "jose vieira brazao": "Jardim José Vieira Brazão",
  "jose viera brazao": "Jardim José Vieira Brazão",
  "brasao": "Jardim José Vieira Brazão",
  "brazao": "Jardim José Vieira Brazão",

  // Morada do Sol (F)
  "morada do sol": "Morada do Sol",
  "morada sol": "Morada do Sol",
  "marada do sol": "Morada do Sol",
  "condominio quebec": "Condomínio Quebec",
  "quebec": "Condomínio Quebec",
  "condominio toruino": "Condomínio Toruino",
  "toruino": "Condomínio Toruino",
  "torino": "Condomínio Toruino",
  // Só com "condomínio" na frente: "paris" sozinho pegaria "Jardim Paris", que é o Parisi.
  "condominio paris": "Condomínio Paris",
  "cecap": "Parque Cecap",
  "max define": "Max Define",
  "max leonardo define": "Max Define",
  "max defini": "Max Define",
  "jardim das flores": "Jardim das Flores",
  "jd das flores": "Jardim das Flores",
  "jardim flores": "Jardim das Flores",
  "jd flores": "Jardim das Flores",
  "jardim da flores": "Jardim das Flores",
  "jardim paineiras": "Jardim Paineiras",
  "paineiras": "Jardim Paineiras",
  "jose luiz simoes": "Jardim José Luiz Simões",
  "jose luis simoes": "Jardim José Luiz Simões",
  "1 de maio": "1º De Maio",
  "1o de maio": "1º De Maio",
  "primeiro de maio": "1º De Maio",
  "servidores": "Jardim dos Servidores",
  "zita de oliveira": "Zita de Oliveira",
  "zita": "Zita de Oliveira",
  "palmito": "Palmito",

  // Timboré (T)
  "timbore": "Jardim Timboré",

  // Zona Rural (Z)
  "zona rural": "Zona Rural",
  "rural": "Zona Rural",
  "sitio": "Zona Rural",
  "chacara": "Zona Rural",
  "fazenda": "Zona Rural"
};

function normalizeNeighborhood(rawNeighborhood) {
  if (!rawNeighborhood || rawNeighborhood.toString().trim() === "") {
    return "NÃO INFORMADO";
  }

  const rawName = String(rawNeighborhood).trim();

  // Remove números isolados (telefones digitados na coluna errada)
  if (/^\d+[-\d]*$/.test(rawName)) {
    return "NÃO INFORMADO";
  }

  const cleaned = rawName
    .toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^\w\s]/g, '')
    .replace(/\s+/g, ' ')
    .trim();

  if (VARIACOES_BAIRRO[cleaned]) {
    return VARIACOES_BAIRRO[cleaned];
  }

  for (const variation in VARIACOES_BAIRRO) {
    if (cleaned.indexOf(variation) !== -1) {
      return VARIACOES_BAIRRO[variation];
    }
  }

  // Um texto curto ou genérico ("Orlândia", "Jardim") casava com o primeiro bairro que o
  // contivesse. Só vale o bairro inteiro dentro do texto, ou um pedaço longo do nome dele.
  const genericos = ["jardim", "jd", "vila", "conjunto", "parque", "orlandia", "residencial", "bairro"];
  for (const knownNeighborhood in CLUSTERS_VACINACAO) {
    const knownNormalized = knownNeighborhood.toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '');

    if (cleaned.indexOf(knownNormalized) !== -1 ||
        (cleaned.length >= 6 && genericos.indexOf(cleaned) === -1 && knownNormalized.indexOf(cleaned) !== -1)) {
      return knownNeighborhood;
    }
  }

  return toTitleCase(rawName);
}

// SISTEMA DE PARSING DE ENDEREÇOS INTELIGENTE
function parseStreetAddress(streetRaw, numberRaw, complementRaw) {
  if (!streetRaw) return {
    group: 3, type: "outro", scheme: "other", num: null, letter: null, parity: null, original: streetRaw
  };

  let s = String(streetRaw).trim().toLowerCase();

  s = s.replace(/\b(av|avenida)\b\.?/g, "avenida")
       .replace(/^(r|rua)\b\.?/, "rua")   // só no começo: em "Avenida R" o R é a letra da avenida
       .replace(/\b(trav|travessa)\b\.?/g, "travessa")
       .replace(/\b(al|alameda)\b\.?/g, "alameda")
       .replace(/\b(esquina|com|fundos|casa)\b/g, "")
       .replace(/\s+/g, ' ')
       .trim();

  let type = "outro";
  const typePatterns = [
    { pattern: /\b(avenida)\b/, value: "avenida" },
    { pattern: /\b(rua)\b/, value: "rua" },
    { pattern: /\b(alameda)\b/, value: "alameda" },
    { pattern: /\b(travessa)\b/, value: "travessa" }
  ];

  for (const item of typePatterns) {
    if (item.pattern.test(s)) {
      type = item.value;
      s = s.replace(item.pattern, "").trim();
      break;
    }
  }

  const numeroExtenso = {
    "um":1,"dois":2,"três":3,"tres":3,"quatro":4,"cinco":5,"seis":6,"sete":7,"oito":8,"nove":9,"dez":10,
    "onze":11,"doze":12,"treze":13,"catorze":14,"quatorze":14,"quinze":15,"dezesseis":16,"dezessete":17,
    "dezoito":18,"dezenove":19,"vinte":20,"vinte e um":21,"vinte e dois":22,"vinte e tres":23,"vinte e quatro":24,
    "vinte e cinco":25,"vinte e seis":26,"vinte e sete":27,"vinte e oito":28,"vinte e nove":29,"trinta":30
  };

  Object.keys(numeroExtenso)
    .sort(function (a, b) { return b.length - a.length; })
    .forEach(function (extenso) {
      const regex = new RegExp("\\b" + extenso + "\\b", 'g');
      s = s.replace(regex, String(numeroExtenso[extenso]));
    });

  let num = null, letter = null, scheme = "other";

  const numMatch = s.match(/\b(\d{1,4})\b/);
  if (numMatch) {
    num = parseInt(numMatch[1], 10);
    scheme = "num";
  } else {
    const letterMatch = s.match(/\b([a-z])\b/i);
    if (letterMatch) {
      letter = letterMatch[1].toUpperCase();
      scheme = "letter";
    }
  }

  const group = (type === "rua" || type === "alameda") ? 1
              : (type === "avenida" || type === "travessa") ? 2
              : 3;

  const parity = (scheme === "num" && (type === "rua" || type === "alameda")) ? (num % 2) : null;

  return { group: group, type: type, scheme: scheme, num: num, letter: letter, parity: parity, original: streetRaw };
}

// DIVISÃO DOS CLUSTERS GRANDES PELA RUA E PELO NÚMERO DA CASA
//
// CLUSTERS_VACINACAO dá a REGIÃO do bairro (A a F). As regiões C, E e F são divididas aqui.
// Em Orlândia o número da casa é uma distância em metros:
//   - numa RUA ou ALAMEDA, cresce conforme se afasta do eixo Avenida 1 / Avenida A;
//   - numa AVENIDA ou TRAVESSA, cresce de sul para norte: ~420 na altura da Rua 1/Rua 2,
//     ~1000 entre a Rua 10 e a Rua 12, ~1450 na Rua 18 e ~1565 na Rua 20.
// As ruas pares ficam ao norte da Rua 1 e as ímpares ao sul. Os valores foram medidos nos
// endereços do IBGE que estão no atlas do PetOrlândia.
//
//   C1 Centro Norte     ruas pares; avenidas com número a partir de 420
//   C2 Centro Sul       ruas ímpares; avenidas com número abaixo de 420 (Bandeirantes)
//   E1 Santa Rita       ruas 1 a 10, da Avenida Q em diante       (casa nº 1635 ou mais)
//   E2 Boa Vista Leste  ruas 1 a 10, entre as avenidas I e P      (casa nº 885 a 1634)
//   E3 Boa Vista Oeste  ruas 1 a 10, até a Avenida H              (casa nº até 884)
//   F1 Benini / Flores  Rua 12 para cima, até a Avenida L         (casa nº até 1259)
//   F2 Morada do Sol    Rua 20 para cima, entre as avenidas E e P, e os condomínios
//   F3 Siena / Max Define / J. L. Simões   Rua 12 para cima, avenidas M a T (nº 1260 a 2054)
//   F4 Brazão / Vista Linda                Rua 12 para cima, da Avenida U em diante (nº 2055+)
//   D  Parisi           (igual) + ruas ímpares da 3 em diante do lado leste, casa nº 1000+
//   T  Timboré          bairro afastado: fica sozinho, logo antes da Zona Rural
var ORDEM_CLUSTERS = {"A":1, "B":2, "C1":3, "C2":4, "D":5, "E1":6, "E2":7, "E3":8,
                      "F1":9, "F2":10, "F3":11, "F4":12, "T":13, "Z":14, "ZZ":15};

// Usada só quando a rua não permite decidir (rua com nome, casa sem número).
var ZONA_PADRAO_DO_BAIRRO = {
  "Jardim Bandeirantes": "C2",
  "Jardim Santa Rita": "E1", "Jardim Siena": "E2", "Jardim Boa Vista": "E3", "Jardim Formoso": "E3",
  "Jardim Leonor Degiovani": "E3", "Jardim Benini": "F1",
  "Jardim Vista Linda": "F4", "Jardim José Vieira Brazão": "F4",
  "Morada do Sol": "F2", "Condomínio Quebec": "F2", "Condomínio Toruino": "F2", "Palmito": "F2",
  "Condomínio Paris": "F2", "Parque Cecap": "F1",
  "Jardim das Flores": "F1", "Jardim Paineiras": "F1", "Jardim José Luiz Simões": "F1",
  "Jardim dos Servidores": "F1", "Max Define": "F3", "1º De Maio": "F3", "Zita de Oliveira": "F3"
};
var ZONA_PADRAO_DA_REGIAO = { "C": "C1", "E": "E3", "F": "F1" };

function refinarCluster_(base, bairro, info, casa, ruaDigitada, complemento) {
  if (base !== "C" && base !== "E" && base !== "F") return base;
  const padrao = ZONA_PADRAO_DO_BAIRRO[bairro] || ZONA_PADRAO_DA_REGIAO[base];
  const ruaOuAlameda = info.type === "rua" || info.type === "alameda";
  const avenidaOuTravessa = info.type === "avenida" || info.type === "travessa";

  // Condomínios da Rua 20/Rua 26: a coluna "Número" traz a casa lá dentro, não o número da rua.
  const textoLivre = (String(ruaDigitada || "") + " " + String(complemento || "") + " " + bairro)
    .toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  if (base !== "C" && /\b(torino|toruino|quebec|quebeck|paris)\b/.test(textoLivre)) return "F2";

  // Número da rua escrito junto com o nome ("Rua 20 - 1107", "Avenida N 1501"): é ele que
  // diz onde a casa fica; o da coluna "Número" é a casa/apartamento.
  const numerosNaRua = String(ruaDigitada || "").match(/\d+/g) || [];
  const numeroExtra = info.scheme === "num" ? numerosNaRua[1] : numerosNaRua[0];
  if (numeroExtra && parseInt(numeroExtra, 10) >= 10) casa = parseInt(numeroExtra, 10);

  if (base === "C") {
    if (ruaOuAlameda && info.scheme === "num") return info.num % 2 === 0 ? "C1" : "C2";
    if (avenidaOuTravessa && casa > 0) return casa >= 420 ? "C1" : "C2";
    return padrao;
  }

  // Lado leste (regiões E e F): coluna = posição leste-oeste, banda = posição norte-sul.
  let coluna = null;      // 0: até a Av. H | 1: I a L | 2: M a P | 3: Q a T | 4: U em diante
  let banda = null;       // "P": abaixo da Rua 1 | "S": ruas 1 a 10 | "N": ruas 12 a 18 | "NN": Rua 20 para cima
  let morada = false;     // entre as avenidas E e P
  let parisi = false;     // da Avenida K em diante

  if (ruaOuAlameda && info.scheme === "num") {
    const n = info.num;
    banda = n % 2 === 1 ? (n === 1 ? "S" : "P") : (n <= 10 ? "S" : (n <= 18 ? "N" : "NN"));
    if (casa > 0) {
      coluna = casa < 885 ? 0 : casa < 1260 ? 1 : casa < 1635 ? 2 : casa < 2055 ? 3 : 4;
      morada = casa >= 510 && casa < 1635;
      parisi = casa >= 1000;
    }
  } else if (avenidaOuTravessa && (info.scheme === "letter" || info.num === 100)) {
    const letra = info.scheme === "letter" ? info.letter : "Z";
    coluna = letra <= "H" ? 0 : letra <= "L" ? 1 : letra <= "P" ? 2 : letra <= "T" ? 3 : 4;
    morada = letra >= "E" && letra <= "P";
    parisi = letra >= "K";
    // 1565 e não 1460: a quadra entre a Rua 18 e a Rua 20 (nº 1445 a 1561) é Cecap, Benini,
    // das Flores, 1º de Maio e Max Define. A Morada do Sol só começa depois da Rua 20.
    if (casa > 0) banda = casa < 280 ? "P" : casa < 1000 ? "S" : casa < 1565 ? "N" : "NN";
  }

  if (coluna === null || banda === null) return padrao;
  if (banda === "P") {
    if (parisi) return "D";
    banda = "S";          // ponta sul do Boa Vista
  }
  if (banda === "NN" && morada) return "F2";
  if (banda === "N" || banda === "NN") return coluna <= 1 ? "F1" : coluna <= 3 ? "F3" : "F4";
  return coluna === 0 ? "E3" : coluna <= 2 ? "E2" : "E1";
}

/**
 * Reordena a aba por cluster/rota levando NOTA e COR junto com a linha.
 *
 * A versão anterior usava clearContent(): valores eram reescritos na ordem
 * nova, mas as notas e as cores de fundo ficavam onde estavam. Depois de uma
 * otimização, a nota "Vacinado" de um tutor aparecia no cadastro de quem
 * passou a ocupar aquela linha. Aqui os três (valores, notas e cores) são
 * lidos e regravados juntos.
 */
var ALTURA_LINHA_ROTA = 21; // altura padrão do Sheets, em pixels

function routeOptimizeByCluster() {
  let lock;
  try {
    lock = LockService.getDocumentLock() || LockService.getScriptLock();
    if (!lock.tryLock(1000)) {
      throw new Error("Já existe uma operação na planilha em andamento. Aguarde e tente novamente.");
    }
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    const range = sheet.getDataRange();
    const data = range.getValues();

    if (data.length < 2) {
      lock.releaseLock();
      SpreadsheetApp.getUi().alert("Nada para otimizar nesta aba.");
      return { success: false, totalProcessed: 0 };
    }

    const header = data[0].slice();
    const offset = detectarOffset_(data);
    const col = colunas_(offset);

    const processed = [];
    for (let index = 1; index < data.length; index++) {
      const row = data[index];
      try {
        const normalized = normalizeNeighborhood(row[col.bairro] || "");
        const addressInfo = parseStreetAddress(row[col.endereco], row[col.numero], row[col.complemento]);
        // Região do bairro, dividida pela rua e pelo número da casa.
        const cluster = refinarCluster_(CLUSTERS_VACINACAO[normalized] || "ZZ", normalized, addressInfo,
          parseInt(row[col.numero], 10) || 0, row[col.endereco], row[col.complemento]);
        const hasPhone = row[col.telefone1] && String(row[col.telefone1]).replace(/\D/g, '').length >= 10;
        const totalAnimals = (parseInt(row[col.caes]) || 0) + (parseInt(row[col.gatos]) || 0);

        processed.push({
          originalData: row.slice(),
          cluster: cluster,
          normalizedNeighborhood: normalized,
          addressInfo: addressInfo,
          hasPhone: hasPhone,
          totalAnimals: totalAnimals,
          rowIndex: index + 1,
          offset: offset
        });
      } catch (error) {
        Logger.log("Erro processando linha " + (index + 1) + ": " + error);
        // Linha problemática NÃO é descartada: vai para o fim da aba.
        processed.push({
          originalData: row.slice(),
          cluster: "ZZ",
          normalizedNeighborhood: "NÃO INFORMADO",
          addressInfo: { group: 3, type: "outro", scheme: "other", num: null, letter: null, parity: null },
          hasPhone: false,
          totalAnimals: 0,
          rowIndex: index + 1,
          offset: offset
        });
      }
    }

    processed.sort(function (a, b) {
      const clusterCompare = ORDEM_CLUSTERS[a.cluster] - ORDEM_CLUSTERS[b.cluster];
      if (clusterCompare !== 0) return clusterCompare;

      if (a.addressInfo.group !== b.addressInfo.group) {
        return a.addressInfo.group - b.addressInfo.group;
      }

      const typeOrder = { "rua": 1, "alameda": 2, "avenida": 3, "travessa": 4, "outro": 5 };
      const typeCompare = typeOrder[a.addressInfo.type] - typeOrder[b.addressInfo.type];
      if (typeCompare !== 0) return typeCompare;

      if (a.addressInfo.scheme !== b.addressInfo.scheme) {
        if (a.addressInfo.scheme === "num") return -1;
        if (b.addressInfo.scheme === "num") return 1;
        if (a.addressInfo.scheme === "letter") return -1;
        if (b.addressInfo.scheme === "letter") return 1;
      }

      if (a.addressInfo.group === 1) {
        if (a.addressInfo.scheme === "num" && b.addressInfo.scheme === "num") {
          if (a.addressInfo.parity !== b.addressInfo.parity) {
            return a.addressInfo.parity - b.addressInfo.parity;
          }
          if (a.addressInfo.num !== b.addressInfo.num) {
            return b.addressInfo.num - a.addressInfo.num;
          }
        }
        if (a.addressInfo.scheme === "letter" && b.addressInfo.scheme === "letter") {
          // Só decide aqui se as letras forem diferentes: na mesma via, segue para o número da casa.
          const letterCompare = (b.addressInfo.letter || "").localeCompare(a.addressInfo.letter || "");
          if (letterCompare !== 0) return letterCompare;
        }
      } else if (a.addressInfo.group === 2) {
        if (a.addressInfo.scheme === "num" && b.addressInfo.scheme === "num") {
          if (a.addressInfo.num !== b.addressInfo.num) {
            return b.addressInfo.num - a.addressInfo.num;
          }
        }
        if (a.addressInfo.scheme === "letter" && b.addressInfo.scheme === "letter") {
          // Só decide aqui se as letras forem diferentes: na mesma via, segue para o número da casa.
          const letterCompare = (b.addressInfo.letter || "").localeCompare(a.addressInfo.letter || "");
          if (letterCompare !== 0) return letterCompare;
        }
      }

      const streetA = (a.originalData[a.offset + 1] || "").toString();
      const streetB = (b.originalData[b.offset + 1] || "").toString();

      // Vias com nome (sem número nem letra): primeiro junta a mesma via, depois o número da casa.
      if (a.addressInfo.scheme === "other" && b.addressInfo.scheme === "other") {
        const nameCompare = streetA.trim().toLowerCase().localeCompare(streetB.trim().toLowerCase());
        if (nameCompare !== 0) return nameCompare;
      }

      const houseA = parseInt(a.originalData[a.offset + 2], 10) || 0;
      const houseB = parseInt(b.originalData[b.offset + 2], 10) || 0;
      if (houseB !== houseA) return houseB - houseA;

      return streetA.localeCompare(streetB);
    });

    // Colunas de saída: reaproveita as que já existem em vez de duplicar.
    let clusterCol = header.indexOf("Cluster");
    if (clusterCol === -1) {
      clusterCol = header.length;
      header.push("Cluster");
    }
    let bairroCol = header.indexOf("Bairro Normalizado");
    if (bairroCol === -1) {
      bairroCol = header.length;
      header.push("Bairro Normalizado");
    }

    const totalColumns = header.length;
    const totalLinhas = data.length - 1;
    if (processed.length !== totalLinhas) {
      throw new Error("A quantidade de linhas mudou durante a classificação. Tente novamente.");
    }
    const ordem = data.slice(1).map(function () { return [0]; });
    const clusters = data.slice(1).map(function () { return [""]; });
    const bairros = data.slice(1).map(function () { return [""]; });
    processed.forEach(function (item, posicao) {
      const indice = item.rowIndex - 2;
      ordem[indice] = [posicao + 1];
      clusters[indice] = [item.cluster];
      bairros[indice] = [item.normalizedNeighborhood];
    });

    if (sheet.getMaxColumns() < totalColumns) {
      sheet.insertColumnsAfter(sheet.getMaxColumns(), totalColumns - sheet.getMaxColumns());
    }
    sheet.getRange(1, 1, 1, totalColumns).setValues([header]);

    // A ordenação nativa move as células completas: fórmulas, links, notas,
    // estilos, validações e preenchimentos, sem ler nem repintar suas cores.
    // A coluna temporária contém apenas a posição calculada para cada rota.
    const colunaOrdem = totalColumns + 1;
    sheet.insertColumnAfter(totalColumns);
    try {
      sheet.getRange(2, clusterCol + 1, totalLinhas, 1).setValues(clusters);
      sheet.getRange(2, bairroCol + 1, totalLinhas, 1).setValues(bairros);
      sheet.getRange(2, colunaOrdem, totalLinhas, 1).setValues(ordem);
      sheet.getRange(2, 1, totalLinhas, colunaOrdem)
        .sort({ column: colunaOrdem, ascending: true });
    } finally {
      sheet.deleteColumn(colunaOrdem);
    }

    // Linhas com altura fixa e texto cortado (não quebrado): sem isso o Sheets
    // reajusta a altura de cada linha ao conteúdo e elas crescem a cada execução.
    sheet.getRange(2, 1, totalLinhas, totalColumns)
      .setWrapStrategy(SpreadsheetApp.WrapStrategy.CLIP);
    // "Forced": sem isso, célula com quebra de linha digitada (Alt+Enter) mantém a linha alta.
    sheet.setRowHeightsForced(2, totalLinhas, ALTURA_LINHA_ROTA);

    // Versões antigas gravavam a cor do cluster como preenchimento fixo. Nas
    // colunas auxiliares a única cor é a da regra condicional do Cluster.
    sheet.getRange(2, clusterCol + 1, totalLinhas, 1).setBackground(null);
    sheet.getRange(2, bairroCol + 1, totalLinhas, 1).setBackground(null);

    applyFormatting(sheet, totalLinhas, clusterCol + 1);
    SpreadsheetApp.flush();
    lock.releaseLock();

    const report = generateOptimizationReport(processed);
    // A aba mudou de ordem: o Status PMO passa a apontar para as linhas novas.
    lock.releaseLock();
    try {
      conferirQuadroStatusPMO();
    } catch (err) {
      Logger.log('conferirQuadroStatusPMO erro: ' + err);
    }

    const ui = SpreadsheetApp.getUi();
    ui.alert('🎯 OTIMIZAÇÃO CONCLUÍDA!', report +
      "\n\nDica: rode agora \"🔄 Atualizar status (PetOrlândia)\" para o Status PMO reencaixar nas novas posições.",
      ui.ButtonSet.OK);

    SpreadsheetApp.getActive().toast(
      "✅ Otimização concluída! " + processed.length + " endereços processados.",
      "Vacinação - Sucesso",
      8
    );

    return {
      success: true,
      totalProcessed: processed.length,
      clusters: getClusterStats(processed)
    };

  } catch (error) {
    Logger.log("ERRO CRÍTICO: " + error.toString());
    SpreadsheetApp.getActive().toast(
      "❌ Erro na otimização: " + error.message,
      "Vacinação - Erro",
      10
    );
    throw error;
  } finally {
    if (lock && lock.hasLock()) lock.releaseLock();
  }
}

function toTitleCase(str) {
  if (!str) return "";
  return String(str)
    .toLowerCase()
    .split(" ")
    .map(function (word) { return word.charAt(0).toUpperCase() + word.slice(1); })
    .join(" ");
}

/** O Sheets arredonda a cor da regra ao salvar (#E8F5E8 volta como #E8F4E8). */
function coresProximas_(a, b) {
  const rgb = function (hex) {
    const h = String(hex).replace("#", "");
    return [0, 2, 4].map(function (i) { return parseInt(h.substr(i, 2), 16); });
  };
  const x = rgb(a), y = rgb(b);
  return x.every(function (v, i) { return Math.abs(v - y[i]) <= 3; });
}

function applyFormatting(sheet, dataLength, clusterColumn) {
  if (dataLength === 0) return;

  const clusterRange = sheet.getRange(2, clusterColumn, dataLength, 1);
  const clusterColors = {
    "A": "#E8F5E8", // Verde claro - Vilinha
    "B": "#FFF3E0", // Laranja claro - Gruta
    "C1": "#E3F2FD", // Azul claro - Centro Norte
    "C2": "#BBDEFB", // Azul - Centro Sul
    "D": "#F3E5F5", // Roxo claro - Parisi
    "E1": "#E8EAF6", // Índigo claro - Santa Rita
    "E2": "#C5CAE9", // Índigo - Boa Vista Leste
    "E3": "#D1C4E9", // Lilás - Boa Vista Oeste
    "F1": "#E0F2F1", // Ciano claro - Benini / das Flores
    "F2": "#B2DFDB", // Ciano - Morada do Sol
    "F3": "#DCEDC8", // Verde-limão - Siena / Max Define / J. L. Simões
    "F4": "#FFF9C4", // Amarelo claro - Brazão / Vista Linda
    "T": "#D7CCC8", // Marrom claro - Timboré
    "Z": "#F5F5F5", // Cinza - Rural
    "ZZ": "#FFEBEE" // Vermelho claro - Não classificado
  };

  // Substitui somente as regras criadas por esta função na coluna Cluster.
  // Regras de status, destaques manuais e escalas de cores continuam intactas.
  const rules = [];
  sheet.getConditionalFormatRules().forEach(function (rule) {
    const condition = rule.getBooleanCondition();
    const criteria = condition && condition.getCriteriaValues();
    const cluster = criteria && String(criteria[0]);
    const cor = condition && condition.getBackground();
    const geradaPeloCluster = condition &&
      condition.getCriteriaType() === SpreadsheetApp.BooleanCriteria.TEXT_EQUAL_TO &&
      Object.prototype.hasOwnProperty.call(clusterColors, cluster) &&
      cor && coresProximas_(cor, clusterColors[cluster]);
    if (!geradaPeloCluster) {
      rules.push(rule);
      return;
    }
    const ranges = rule.getRanges();
    const outrosRanges = ranges.filter(function (range) {
      return !(range.getSheet().getSheetId() === sheet.getSheetId() &&
        range.getColumn() === clusterColumn && range.getNumColumns() === 1 && range.getRow() === 2);
    });
    if (outrosRanges.length === ranges.length) rules.push(rule);
    else if (outrosRanges.length) rules.push(rule.copy().setRanges(outrosRanges).build());
  });

  Object.keys(clusterColors).forEach(function (cluster) {
    const rule = SpreadsheetApp.newConditionalFormatRule()
      .whenTextEqualTo(cluster)
      .setBackground(clusterColors[cluster])
      .setRanges([clusterRange])
      .build();
    rules.push(rule);
  });

  sheet.setConditionalFormatRules(rules);
}

function getClusterStats(processedData) {
  const stats = {
    total: processedData.length,
    byCluster: {},
    byNeighborhood: {},
    animals: { dogs: 0, cats: 0, total: 0 },
    issues: { noPhone: 0, noAnimals: 0, unclassified: 0 }
  };

  processedData.forEach(function (item) {
    stats.byCluster[item.cluster] = (stats.byCluster[item.cluster] || 0) + 1;
    stats.byNeighborhood[item.normalizedNeighborhood] =
      (stats.byNeighborhood[item.normalizedNeighborhood] || 0) + 1;

    const offset = item.offset || 0;
    const dogs = parseInt(item.originalData[7 + offset]) || 0;
    const cats = parseInt(item.originalData[8 + offset]) || 0;
    stats.animals.dogs += dogs;
    stats.animals.cats += cats;
    stats.animals.total += dogs + cats;

    if (!item.hasPhone) stats.issues.noPhone++;
    if (item.totalAnimals === 0) stats.issues.noAnimals++;
    if (item.cluster === "ZZ") stats.issues.unclassified++;
  });

  return stats;
}

function generateOptimizationReport(processedData) {
  const stats = getClusterStats(processedData);

  const report = [
    "📊 RELATÓRIO DE OTIMIZAÇÃO - VACINAÇÃO",
    "📅 Gerado em: " + new Date().toLocaleString('pt-BR'),
    "",
    "👥 ESTATÍSTICAS GERAIS:",
    "• Total de endereços: " + stats.total,
    "• Cachorros para vacinar: " + stats.animals.dogs,
    "• Gatos para vacinar: " + stats.animals.cats,
    "• Total de animais: " + stats.animals.total,
    "",
    "📍 DISTRIBUIÇÃO POR CLUSTER:"
  ]
    .concat(Object.keys(stats.byCluster).sort().map(function (cluster) {
      return "• Cluster " + cluster + ": " + stats.byCluster[cluster] + " endereços";
    }))
    .concat([
      "",
      "⚠️  PROBLEMAS IDENTIFICADOS:",
      "• Sem telefone: " + stats.issues.noPhone,
      "• Sem animais: " + stats.issues.noAnimals,
      "• Não classificados: " + stats.issues.unclassified,
      "",
      "🏘️  PRINCIPAIS BAIRROS:"
    ])
    .concat(Object.keys(stats.byNeighborhood)
      .sort(function (a, b) { return stats.byNeighborhood[b] - stats.byNeighborhood[a]; })
      .slice(0, 10)
      .map(function (neighborhood) {
        return "• " + neighborhood + ": " + stats.byNeighborhood[neighborhood] + " endereços";
      }))
    .join('\n');

  Logger.log(report);
  return report;
}

function debugAddressClassification() {
  const testAddresses = [
    "Rua 10", "Rua 14", "Rua 2", "Avenida 20", "Avenida E",
    "Travessa 18", "Alameda 15", "Av 10 960 A", "Rua Vinte e Dois"
  ];

  console.log("=== DEBUG - CLASSIFICAÇÃO DE ENDEREÇOS ===");
  testAddresses.forEach(function (addr) {
    const parsed = parseStreetAddress(addr);
    console.log('"' + addr + '" → Grupo:' + parsed.group + " " + parsed.type + " " +
                parsed.scheme + ":" + (parsed.num || parsed.letter || "N/A") + " Paridade:" + parsed.parity);
  });

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.getSheets().forEach(function (sheet) {
    const dados = sheet.getDataRange().getValues();
    console.log("Aba '" + sheet.getName() + "': offset de carimbo = " + detectarOffset_(dados));
  });
}

// ==============================================================================
// 4. MÓDULO: SINCRONIZAÇÃO E CONTROLE DE DOSES / PMO
// ==============================================================================
function compilarControleDeDoses() {
  const URL   = 'https://www.petorlandia.com.br/vacina-pmo/webhook/compilar-doses';
  try {
    // Dentro do try de propósito: sem PMO_TOKEN configurado, a mensagem
    // explicando o que falta chega como aviso na planilha, não como erro cru
    // do Apps Script.
    const resp = UrlFetchApp.fetch(URL, {
      method: 'post',
      headers: { 'X-PMO-Token': obterTokenPMO_() },
      muteHttpExceptions: true,
    });
    const ok = resp.getResponseCode() === 200;
    SpreadsheetApp.getActiveSpreadsheet().toast(
      ok ? 'Compilação iniciada! A coluna do dia aparece em instantes e a aba fica verde.'
         : 'Falha (' + resp.getResponseCode() + '): ' + resp.getContentText(),
      'Controle de doses', 8);
  } catch (e) {
    SpreadsheetApp.getActiveSpreadsheet().toast('Erro ao chamar o PetOrlandia: ' + e, 'Controle de doses', 10);
  }
}

/**
 * Token do webhook, lido das Propriedades do Script.
 *
 * Menu Extensões > Apps Script > Configurações do projeto > Propriedades do
 * script > adicionar `PMO_TOKEN`. Assim o segredo não fica escrito no código,
 * que é copiado, versionado e compartilhado.
 */
function obterTokenPMO_() {
  const token = PropertiesService.getScriptProperties().getProperty('PMO_TOKEN');
  if (!token) {
    throw new Error(
      'Configure a propriedade de script PMO_TOKEN ' +
      '(Extensões > Apps Script > Configurações do projeto > Propriedades do script).'
    );
  }
  return token;
}

function sincronizarPlanilhas() {
  const ui = SpreadsheetApp.getUi();
  let lock;
  let titulo = '✅ Sincronização Concluída!';
  let mensagem;
  try {
    lock = LockService.getDocumentLock() || LockService.getScriptLock();
    if (!lock.tryLock(1000)) {
      throw new Error('Já existe uma sincronização em andamento. Aguarde e tente novamente.');
    }

    const sourceId = '1GFp6yyjPVj4UDhDEh8o-9rhmOhSAnQb6hwQprgje304';
    const nomeAbaOrigem = 'Respostas ao formulário 1';
    const nomeAbaDestino = 'Vacinação 2026';

    const sourceSpreadsheet = SpreadsheetApp.openById(sourceId);
    const sourceSheet = sourceSpreadsheet.getSheetByName(nomeAbaOrigem);

    if (!sourceSheet) {
      throw new Error('Aba "' + nomeAbaOrigem + '" não encontrada!');
    }

    const destSheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(nomeAbaDestino);
    if (!destSheet) {
      throw new Error('Aba "' + nomeAbaDestino + '" não encontrada!');
    }

    const sourceData = sourceSheet.getDataRange().getValues();

    // A origem tem 12 colunas de cadastro (A:L). A partir de M ficam status,
    // links e outras colunas de trabalho, que não pertencem à importação.
    const totalColunas = 12;
    const normalizar = function (valor) {
      return String(valor == null ? '' : valor).normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
    };
    const destData = destSheet.getDataRange().getValues();
    const ultimaLinha = destSheet.getLastRow();
    if (ultimaLinha < 1 || sourceData[0].length < totalColunas) {
      throw new Error('Confira os cabeçalhos de origem e destino antes de sincronizar.');
    }

    // Aceita o cabeçalho abreviado de Observação e a coluna A sem título da
    // aba mestre. Interrompe antes de escrever se as colunas forem deslocadas.
    for (let c = 0; c < totalColunas; c++) {
      const origem = normalizar(sourceData[0][c]);
      const destino = normalizar(destData[0][c]);
      if (c === 0 && origem === 'carimbo de data/hora' && !destino) continue;
      if (!origem || !destino || (origem !== destino &&
          !(c === 11 && origem.indexOf(destino) === 0))) {
        throw new Error('Cabeçalhos incompatíveis na coluna ' + (c + 1) +
          '. Confira as colunas A:L; nenhum cadastro foi alterado.');
      }
    }

    const fuso = sourceSpreadsheet.getSpreadsheetTimeZone();
    const carimbo = function (valor) {
      if (valor instanceof Date && !isNaN(valor.getTime())) {
        return Utilities.formatDate(valor, fuso, 'dd/MM/yyyy HH:mm:ss');
      }
      const partes = String(valor || '').trim().match(
        /^(\d{1,2})\/(\d{1,2})\/(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
      if (!partes) return '';
      return partes[1].padStart(2, '0') + '/' + partes[2].padStart(2, '0') + '/' +
        partes[3] + ' ' + partes[4].padStart(2, '0') + ':' + partes[5] + ':' + (partes[6] || '00');
    };
    const cadastro = function (linha) {
      const telefones = [linha[6], linha[7]].map(function (valor) {
        const digitos = String(valor || '').replace(/\D/g, '');
        return digitos.length > 11 && digitos.indexOf('55') === 0 ? digitos.slice(2) : digitos;
      }).filter(Boolean).sort();
      return JSON.stringify([normalizar(linha[1]), telefones.length ? telefones :
        linha.slice(2, 6).map(normalizar)]);
    };

    // O carimbo permanece o mesmo quando endereço, telefone ou nome são
    // corrigidos. Se dois tutores responderem no mesmo segundo, o nome
    // desempata, evitando descartar um deles.
    const nomesPorCarimbo = new Map();
    sourceData.slice(1).forEach(function (linha) {
      const data = carimbo(linha[0]);
      const nome = normalizar(linha[1]);
      if (!data || !nome) return;
      if (!nomesPorCarimbo.has(data)) nomesPorCarimbo.set(data, new Set());
      nomesPorCarimbo.get(data).add(nome);
    });
    const chave = function (linha) {
      const data = carimbo(linha[0]);
      if (!data) return '';
      const nomes = nomesPorCarimbo.get(data);
      return JSON.stringify([data, nomes && nomes.size > 1 ? normalizar(linha[1]) : '']);
    };
    const existentes = new Set();
    const cadastrosExistentes = new Set();
    const cadastrosSemCarimbo = new Set();
    destData.slice(1).forEach(function (linha) {
      if (!normalizar(linha[1])) return;
      const id = chave(linha);
      const pessoa = cadastro(linha);
      if (id) existentes.add(id);
      else cadastrosSemCarimbo.add(pessoa);
      cadastrosExistentes.add(pessoa);
    });

    const novasLinhas = [];
    let ignorados = 0;
    sourceData.slice(1).forEach(function (linha) {
      if (!normalizar(linha[1])) return;
      const id = chave(linha);
      const pessoa = cadastro(linha);
      if ((id && existentes.has(id)) || cadastrosSemCarimbo.has(pessoa) ||
          (!id && cadastrosExistentes.has(pessoa))) {
        ignorados++;
        return;
      }
      novasLinhas.push(linha.slice(0, totalColunas));
      if (id) existentes.add(id);
      else cadastrosSemCarimbo.add(pessoa);
      cadastrosExistentes.add(pessoa);
    });

    if (novasLinhas.length) {
      const ultimaLinhaNova = ultimaLinha + novasLinhas.length;
      const maxLinhas = destSheet.getMaxRows();
      if (ultimaLinhaNova > maxLinhas) {
        destSheet.insertRowsAfter(maxLinhas, ultimaLinhaNova - maxLinhas);
      }
      // Escreve exclusivamente depois da última linha, sem limpar, ordenar ou
      // regravar nenhum registro existente, inclusive suas notas e fórmulas.
      destSheet.getRange(ultimaLinha + 1, 1, novasLinhas.length, totalColunas).setValues(novasLinhas);
      SpreadsheetApp.flush();
    }
    mensagem = novasLinhas.length + ' novos cadastros adicionados ao final de "' + nomeAbaDestino + '".' +
      '\n' + ignorados + ' cadastros já importados ignorados.' +
      '\n\nOs registros existentes foram preservados.';

  } catch (error) {
    titulo = '❌ Erro';
    mensagem = error.toString();
    console.error(error);
  } finally {
    if (lock && lock.hasLock()) lock.releaseLock();
  }
  // Alertas suspendem a execução e liberam locks: mostrar só após terminar.
  ui.alert(titulo, mensagem, ui.ButtonSet.OK);
}

function atualizarStatusPMO() {
  const URL   = 'https://www.petorlandia.com.br/vacina-pmo/webhook/atualizar-status';
  const ui = SpreadsheetApp.getUi();
  try {
    const resp = UrlFetchApp.fetch(URL, {
      method: 'post',
      headers: { 'X-PMO-Token': obterTokenPMO_() },
      muteHttpExceptions: true,
    });
    if (resp.getResponseCode() === 200) {
      ui.alert('✅ Atualização iniciada! Aguarde ~1–2 min e confira a coluna "Status PMO".');
    } else {
      ui.alert('⚠️ Falha (' + resp.getResponseCode() + '): ' + resp.getContentText());
    }
  } catch (e) {
    ui.alert('Erro ao chamar o PetOrlândia: ' + e);
  }
}

function onEditInstalado(e) {
  try {
    organizarDiasSeAbasMudaram_(e.source || SpreadsheetApp.getActiveSpreadsheet());
  } catch (err) {
    Logger.log('organizarDiasSeAbasMudaram_ erro: ' + err);
  }
  try {
    conferirQuadroAposEdicao_(e);
  } catch (err) {
    Logger.log('conferirQuadroAposEdicao_ erro: ' + err);
  }
  try {
    const sheet = e.range.getSheet();
    const COLUNA_DATA_VACINA = 12;
    const NOME_ABA = 'Agendadas';

    if (sheet.getName() === NOME_ABA && e.range.getColumn() === COLUNA_DATA_VACINA) {
      if (e.value) {
        atualizarStatusPMO();
      }
    }
  } catch (err) {
    Logger.log('onEditInstalado erro: ' + err);
  }
}

// ==============================================================================
// 4b. MÓDULO: COBERTURA DO ATLAS (quantos endereços têm posição conferida no mapa)
// ==============================================================================
var COBERTURA_ATLAS = {
  url: 'https://www.petorlandia.com.br/vacina-pmo/webhook/cobertura-atlas',
  lote: 150,
  nomeAba: 'Cobertura do Atlas'
};

/**
 * Só rua, número e bairro vão para o PetOrlândia: nome do tutor e telefone ficam na planilha.
 * `linha` é o número da linha na aba (para achar o endereço depois).
 */
function montarLinhasCobertura_(dados, offset) {
  const col = colunas_(offset || 0);
  const linhas = [];
  for (let i = 1; i < dados.length; i++) {
    const rua = String(dados[i][col.endereco] || '').trim();
    if (!rua) continue;
    linhas.push({
      linha: i + 1,
      rua: rua,
      numero: String(dados[i][col.numero] || '').trim(),
      bairro: String(dados[i][col.bairro] || '').trim()
    });
  }
  return linhas;
}

function consolidarCobertura_(parciais) {
  const total = { total: 0, ponto: 0, rua: 0, nenhum: 0, sem_rua: 0, por_bairro: {}, nao_resolvidos: [], cortado: false };
  parciais.forEach(function (p) {
    ['total', 'ponto', 'rua', 'nenhum', 'sem_rua'].forEach(function (k) { total[k] += p[k] || 0; });
    total.cortado = total.cortado || !!p.cortado;
    Object.keys(p.por_bairro || {}).forEach(function (nome) {
      const b = total.por_bairro[nome] || (total.por_bairro[nome] = { total: 0, ponto: 0, rua: 0, nenhum: 0, sem_rua: 0 });
      ['total', 'ponto', 'rua', 'nenhum', 'sem_rua'].forEach(function (k) { b[k] += p.por_bairro[nome][k] || 0; });
    });
    total.nao_resolvidos = total.nao_resolvidos.concat(p.nao_resolvidos || []);
  });
  return total;
}

function textoCobertura_(c) {
  const pct = function (n) { return c.total ? Math.round(100 * n / c.total) + '%' : '—'; };
  return [
    c.total + ' endereços conferidos no atlas do PetOrlândia',
    '• Casa com ponto conferido: ' + c.ponto + ' (' + pct(c.ponto) + ')',
    '• Só a rua existe no mapa: ' + c.rua + ' (' + pct(c.rua) + ')',
    '• Não encontrado: ' + c.nenhum + ' (' + pct(c.nenhum) + ')',
    c.sem_rua ? '• Sem rua preenchida: ' + c.sem_rua : ''
  ].filter(Boolean).join('\n');
}

/**
 * Mede quanto da aba atual o atlas consegue posicionar. NÃO altera a aba de dados:
 * escreve o resultado na aba "Cobertura do Atlas". Nenhuma posição é estimada.
 */
function medirCoberturaAtlas() {
  const ui = SpreadsheetApp.getUi();
  try {
    const planilha = SpreadsheetApp.getActiveSpreadsheet();
    const dados = planilha.getActiveSheet().getDataRange().getValues();
    const linhas = montarLinhasCobertura_(dados, detectarOffset_(dados));
    if (!linhas.length) { ui.alert('Nada para medir nesta aba (sem endereços).'); return; }

    const token = obterTokenPMO_();
    const parciais = [];
    for (let i = 0; i < linhas.length; i += COBERTURA_ATLAS.lote) {
      const resp = UrlFetchApp.fetch(COBERTURA_ATLAS.url, {
        method: 'post',
        contentType: 'application/json',
        headers: { 'X-PMO-Token': token },
        payload: JSON.stringify({ rows: linhas.slice(i, i + COBERTURA_ATLAS.lote) }),
        muteHttpExceptions: true
      });
      if (resp.getResponseCode() !== 200) {
        ui.alert('⚠️ O PetOrlândia respondeu ' + resp.getResponseCode() + '. Tente de novo em alguns minutos.');
        return;
      }
      parciais.push(JSON.parse(resp.getContentText()));
    }
    const c = consolidarCobertura_(parciais);

    let aba = planilha.getSheetByName(COBERTURA_ATLAS.nomeAba);
    if (!aba) aba = planilha.insertSheet(COBERTURA_ATLAS.nomeAba); else aba.clear();
    const saida = [['Cobertura do atlas', textoCobertura_(c).split('\n')[0]], ['', '']];
    saida.push(['Casa com ponto conferido', c.ponto], ['Só a rua existe no mapa', c.rua], ['Não encontrado', c.nenhum], ['Sem rua', c.sem_rua], ['', '']);
    saida.push(['Bairro', 'Total', 'Com ponto', 'Só a rua', 'Não encontrado']);
    Object.keys(c.por_bairro).sort().forEach(function (nome) {
      const b = c.por_bairro[nome];
      saida.push([nome, b.total, b.ponto, b.rua, b.nenhum + b.sem_rua]);
    });
    saida.push(['', ''], ['Linha na aba', 'Rua', 'Número', 'Situação']);
    c.nao_resolvidos.forEach(function (n) {
      saida.push([n.linha, n.rua, n.numero, n.situacao === 'rua' ? 'só a rua' : n.situacao === 'sem_rua' ? 'sem rua' : 'não encontrado']);
    });
    const largura = saida.reduce(function (m, l) { return Math.max(m, l.length); }, 1);
    aba.getRange(1, 1, saida.length, largura).setValues(saida.map(function (l) {
      const copia = l.slice(); while (copia.length < largura) copia.push(''); return copia;
    }));

    ui.alert('📍 Cobertura do atlas', textoCobertura_(c) + (c.cortado ? '\n\n(Lista longa: só as primeiras linhas de cada lote foram conferidas.)' : '') +
      '\n\nDetalhe por bairro e a lista do que ficou de fora: aba "' + COBERTURA_ATLAS.nomeAba + '".', ui.ButtonSet.OK);
  } catch (e) {
    ui.alert('Erro ao medir a cobertura: ' + e);
  }
}

// ==============================================================================
// 5. MÓDULO: LINKS DE WHATSAPP
// ==============================================================================
// Em novembro de 2026 a planilha passou de inglês (EUA) para português (Brasil).
// Duas coisas quebraram com isso, e as funções abaixo não dependem mais da
// localidade:
//   - setFormula('=HYPERLINK("…", "…")') passou a gravar #ERROR!: em pt_BR o
//     separador de argumentos é ";". O link agora é gravado na própria célula
//     (texto com link), sem fórmula para o Sheets interpretar.
//   - a data saía do texto exibido na célula; com a planilha em inglês esse texto
//     é "11/5/2026" e a mensagem dizia 11 de maio. Agora sai do valor da célula.
var DIAS_DA_SEMANA = ['Domingo', 'Segunda-Feira', 'Terça-Feira', 'Quarta-Feira',
                      'Quinta-Feira', 'Sexta-Feira', 'Sábado'];

function ehData_(valor) {
  return Object.prototype.toString.call(valor) === '[object Date]';
}

/** "dd/MM/aaaa" de uma célula de data (Date ou texto brasileiro), ou "" se não for data. */
function dataBR_(valor, fuso) {
  if (ehData_(valor)) {
    return isNaN(valor.getTime()) ? '' : Utilities.formatDate(valor, fuso, 'dd/MM/yyyy');
  }
  const m = String(valor || '').trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!m || +m[1] < 1 || +m[1] > 31 || +m[2] < 1 || +m[2] > 12) return '';
  return ('0' + m[1]).slice(-2) + '/' + ('0' + m[2]).slice(-2) + '/' + m[3];
}

function diaDaSemana_(dataBR) {
  const m = String(dataBR || '').match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!m) return '';
  // Meio-dia em UTC: nenhum fuso horário empurra a data para o dia vizinho.
  return DIAS_DA_SEMANA[new Date(Date.UTC(+m[3], +m[2] - 1, +m[1], 12)).getUTCDay()];
}

/**
 * Data que a aba do dia deve ter, tirada do nome. A cópia do Padrão lê a data
 * do próprio nome (Q13) e o "Controle de doses" procura a aba por esse nome
 * (INDIRETO), então o nome precisa ser exatamente "DD/MM/AAAA".
 */
function dataDoNomeDaAba_(nome) {
  const texto = String(nome || '');
  return /^\d{2}\/\d{2}\/\d{4}$/.test(texto) ? dataBR_(texto) : '';
}

function ehLinkWhatsApp_(formula, rich) {
  const link = rich && rich.getLinkUrl ? (rich.getLinkUrl() || '') : '';
  return /wa\.me|HYPERLINK/i.test(String(formula || '')) || /wa\.me/i.test(link);
}

function addWhatsAppLinks() {
  const ui = SpreadsheetApp.getUi();
  try {
    const r = gerarLinksWhatsAppNaAba_(SpreadsheetApp.getActiveSpreadsheet().getActiveSheet());
    ui.alert(r.titulo, r.mensagem, ui.ButtonSet.OK);
  } catch (error) {
    console.error('Erro detalhado:', error);
    ui.alert('Erro: ' + error.toString());
  }
}

/**
 * Grava os links de WhatsApp da aba e devolve { ok, titulo, mensagem }.
 * Não grava nada se a aba do dia estiver sem nome de data ou com linha de
 * outra data: o convite sairia com o dia errado.
 */
function gerarLinksWhatsAppNaAba_(sheet) {
  const fuso = sheet.getParent().getSpreadsheetTimeZone();
  const data = sheet.getDataRange().getValues();
  if (data.length < 2) {
    return { ok: false, titulo: '📱 Links do WhatsApp', mensagem: 'Nada para gerar nesta aba.' };
  }

  const col = colunas_(detectarOffset_(data));
  const nomeAba = sheet.getName();
  const dataDaAba = dataDoNomeDaAba_(nomeAba);
  // Aba do dia: nome com data ou cópia do Padrão ainda sem nome ("Data a definir").
  const abaDoDia = /\d{1,2}\/\d{1,2}\/\d{2,4}/.test(nomeAba) || data.some(function (linha) {
    return String(linha[col.data] || '').trim() === 'Data a definir';
  });

  if (abaDoDia && !dataDaAba) {
    return {
      ok: false,
      titulo: 'Renomeie a aba antes de gerar os links',
      mensagem: 'O nome da aba precisa ser a data do dia no formato DD/MM/AAAA (exemplo: 06/11/2026).\n\n' +
        'É esse nome que preenche a data da aba e liga a aba ao "Controle de doses".'
    };
  }

  // Reaproveita as colunas de WhatsApp se já existirem (evita uma coluna nova
  // a cada execução).
  let colWhatsApp1 = data[0].indexOf('WhatsApp 1') + 1;
  let colWhatsApp2 = data[0].indexOf('WhatsApp 2') + 1;
  if (colWhatsApp1 === 0 || colWhatsApp2 === 0) {
    colWhatsApp1 = data[0].length + 1;
    colWhatsApp2 = data[0].length + 2;
  }

  const pedidos = [];
  const comOutraData = [];
  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    const tutorInfo = {
      nome: row[col.tutor] || '',
      endereco: row[col.endereco] || '',
      numero: row[col.numero] || '',
      complemento: row[col.complemento] || '',
      bairro: row[col.bairro] || '',
      telefone1: row[col.telefone1] || '',
      telefone2: row[col.telefone2] || '',
      quantCaes: row[col.caes] || 0,
      quantGatos: row[col.gatos] || 0,
      data: dataBR_(row[col.data], fuso),
      turno: row[col.turno] || ''
    };

    const phone1 = cleanPhoneNumber(tutorInfo.telefone1);
    const phone2 = cleanPhoneNumber(tutorInfo.telefone2);
    const contato = tutorInfo.nome.toString().trim() !== '' && !!(phone1 || phone2);
    if (contato && abaDoDia && tutorInfo.data !== dataDaAba) {
      comOutraData.push('linha ' + (i + 1) + ' (' + tutorInfo.nome + '): ' + (tutorInfo.data || 'sem data'));
    }
    pedidos.push({ linha: i + 1, contato: contato, info: tutorInfo, phone1: phone1, phone2: phone2 });
  }

  if (comOutraData.length) {
    return {
      ok: false,
      titulo: 'Data diferente do nome da aba',
      mensagem: 'A aba se chama ' + nomeAba + ', mas estas linhas têm outra data na coluna "Data":\n\n' +
        comOutraData.slice(0, 15).join('\n') + (comOutraData.length > 15 ? '\n…' : '') +
        '\n\nCorrija a data (ou o nome da aba) e gere os links de novo. Nenhum link foi alterado.'
    };
  }

  sheet.getRange(1, colWhatsApp1).setValue('WhatsApp 1');
  sheet.getRange(1, colWhatsApp2).setValue('WhatsApp 2');

  const atuais = [colWhatsApp1, colWhatsApp2].map(function (c) {
    const faixa = sheet.getRange(2, c, data.length - 1, 1);
    return { formulas: faixa.getFormulas(), rich: faixa.getRichTextValues() };
  });

  let linksAdicionados = 0;
  pedidos.forEach(function (p, k) {
    const message = p.contato ? generateMessage(p.info) : '';
    [p.phone1, p.phone2].forEach(function (phone, n) {
      const celula = sheet.getRange(p.linha, n === 0 ? colWhatsApp1 : colWhatsApp2);
      if (p.contato && phone) {
        const url = 'https://wa.me/55' + phone + '?text=' + encodeURIComponent(message);
        celula.setRichTextValue(SpreadsheetApp.newRichTextValue()
          .setText('WhatsApp ' + (n + 1)).setLinkUrl(url).build());
      } else if (ehLinkWhatsApp_(atuais[n].formulas[k][0], atuais[n].rich[k][0])) {
        // Link que sobrou de uma execução antiga (ou #ERROR!) numa linha sem esse telefone.
        celula.clearContent();
      }
    });
    if (p.contato) linksAdicionados++;
  });

  // A aba do dia só entra no "Controle de doses" se a data tiver coluna lá.
  const cd = abaDoDia && sheet.getParent().getSheetByName ? sheet.getParent().getSheetByName(ABA_CONTROLE_DE_DOSES) : null;
  const foraDoControle = cd && !dataNoControleDeDoses_(cd, dataDaAba)
    ? '\n\n⚠️ ' + dataDaAba + ' ainda não tem coluna no "Controle de doses": os vacinados desta aba não ' +
      'entram na conta. Use o menu "🗓️ Organizar dias no Controle de doses" ' +
      '(ou "📆 Preparar meses no Controle de doses", se o mês ainda não existir lá).'
    : '';

  return {
    ok: true,
    titulo: '📱 Links do WhatsApp',
    mensagem: 'Links do WhatsApp adicionados com sucesso!\n\n' +
      'Total de linhas processadas: ' + linksAdicionados + '\n' +
      'Agora você pode clicar diretamente nos links na planilha para enviar as mensagens.' + foraDoControle
  };
}

function clearWhatsAppLinks() {
  try {
    const sheet = SpreadsheetApp.getActiveSheet();
    const data = sheet.getDataRange().getValues();

    const col1 = data[0].indexOf('WhatsApp 1') + 1;
    const col2 = data[0].indexOf('WhatsApp 2') + 1;

    if (col1 > 0 && col2 > 0 && data.length > 1) {
      sheet.getRange(2, Math.min(col1, col2), data.length - 1, 2).clearContent();
      SpreadsheetApp.getUi().alert('Links do WhatsApp removidos!');
      return;
    }

    SpreadsheetApp.getUi().alert('Colunas de WhatsApp não encontradas.');

  } catch (error) {
    SpreadsheetApp.getUi().alert('Erro ao limpar links: ' + error.toString());
  }
}

function cleanPhoneNumber(phone) {
  if (!phone) return '';

  let cleaned = phone.toString().trim().replace(/\D/g, '');

  if (cleaned.length === 11 && cleaned[0] === '0') {
    cleaned = cleaned.substring(1);
  }

  if (cleaned.length === 9 || cleaned.length === 8) {
    cleaned = '16' + cleaned;
  }

  if (cleaned.length === 10 || cleaned.length === 11) {
    return cleaned;
  }

  return '';
}

function generateMessage(tutorInfo) {
  const totalAnimais = (parseInt(tutorInfo.quantCaes) || 0) + (parseInt(tutorInfo.quantGatos) || 0);

  let enderecoCompleto = tutorInfo.endereco + ', ' + tutorInfo.numero;
  if (tutorInfo.complemento && tutorInfo.complemento.toString().trim() !== '') {
    enderecoCompleto += ' - ' + tutorInfo.complemento;
  }
  if (tutorInfo.bairro && tutorInfo.bairro.toString().trim() !== '') {
    enderecoCompleto += ' - ' + tutorInfo.bairro;
  }

  let horario = '8h30 às 11h30';
  if (tutorInfo.turno && tutorInfo.turno.toString().toLowerCase().indexOf('tarde') !== -1) {
    horario = '14h30 às 16h00';
  }

  // A data chega pronta (dd/MM/aaaa) de addWhatsAppLinks, ou como Date.
  const dataFormatada = dataBR_(tutorInfo.data, 'America/Sao_Paulo');
  const dataSugerida = dataFormatada ? dataFormatada + ' (' + diaDaSemana_(dataFormatada) + ')' : 'a confirmar';

  return 'Olá!\n' +
'Aqui é do setor de Controle de Vetores. Estamos organizando a Vacinação Contra a Raiva Animal 2026 e identificamos um cadastro em seu nome.\n\n' +
'Gostaríamos de confirmar algumas informações para que possamos vacinar seu animal com segurança:\n\n' +
'Data sugerida para a vacinação: ' + dataSugerida + '\n' +
'Horário: entre ' + horario + '\n\n' +
'Para isso, pedimos sua colaboração respondendo às seguintes perguntas:\n\n' +
'• O animal está se alimentando normalmente?\n' +
'• O animal está tomando alguma medicação atualmente?\n' +
'• O endereço abaixo está correto? (se sim, favor confirmar, se não, corrigir)\n\n' +
'REQUISITANTE: ' + tutorInfo.nome + '\n' +
'Quantidade de animais: ' + totalAnimais + '\n' +
'Endereço: ' + enderecoCompleto + '\n\n' +
'ATENÇÃO: caso não haja retorno, seu cadastro poderá ser substituído por outro.\n\n' +
'Agradecemos pela colaboração!';
}

/** Formato de data com o mês antes do dia (ex.: "M/d/yyyy", herdado da planilha em inglês). */
function formatoMesAntesDoDia_(formato) {
  const f = String(formato || '').toLowerCase().replace(/"[^"]*"/g, '');
  const dia = f.indexOf('d');
  const mes = f.indexOf('m');
  return dia !== -1 && mes !== -1 && mes < dia;
}

/**
 * Deixa as datas das abas de dia ("DD/MM/AAAA") iguais ao nome da aba e
 * exibidas como dia/mês.
 *
 * Enquanto a planilha estava em inglês (EUA), "10/09/2026" digitado virava
 * 9 de outubro, e as células ganharam formato mês/dia: um erro escondia o
 * outro. Em português, a célula que só tem o formato errado mostra a data
 * invertida, e a que tem os dois mostra a data certa mas guarda o dia errado
 * (é o valor que o "Controle de doses" e o PetOrlândia leem).
 *
 * Valor: só muda a célula sem fórmula que tem exatamente a data do nome com
 * dia e mês invertidos (as fórmulas, como =$Q$13, se corrigem sozinhas).
 * Formato: só muda o das células com a data da aba (ou com ela invertida) e
 * formato mês/dia.
 * Qualquer outra data fica como está.
 */
function corrigirDatasInvertidas() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const fuso = ss.getSpreadsheetTimeZone();
  const corrigidas = [];

  ss.getSheets().forEach(function (sheet) {
    const certa = dataDoNomeDaAba_(sheet.getName());
    if (!certa) return;
    const p = certa.split('/');
    // Com o dia acima de 12 a troca não forma data, e com dia = mês não há troca.
    const invertida = +p[0] > 12 || p[0] === p[1] ? '' : p[1] + '/' + p[0] + '/' + p[2];

    const faixa = sheet.getDataRange();
    const valores = faixa.getValues();
    const formulas = faixa.getFormulas();
    const formatos = faixa.getNumberFormats();
    const valorTrocado = [];
    const formatoTrocado = [];
    valores.forEach(function (linha, i) {
      linha.forEach(function (v, j) {
        if (!ehData_(v)) return;
        const texto = Utilities.formatDate(v, fuso, 'dd/MM/yyyy HH:mm');
        const a1 = faixa.getCell(i + 1, j + 1).getA1Notation();
        let daAba = texto === certa + ' 00:00';
        if (!daAba && invertida && texto === invertida + ' 00:00') {
          // A fórmula passa a valer a data certa quando a célula de origem é corrigida.
          if (!formulas[i][j]) valorTrocado.push(a1);
          daAba = true;
        }
        if (daAba && formatoMesAntesDoDia_(formatos[i][j])) formatoTrocado.push(a1);
      });
    });

    if (valorTrocado.length) {
      sheet.getRangeList(valorTrocado).setValue(Utilities.parseDate(certa, fuso, 'dd/MM/yyyy'));
    }
    if (formatoTrocado.length) sheet.getRangeList(formatoTrocado).setNumberFormat('dd/mm/yyyy');
    if (valorTrocado.length || formatoTrocado.length) {
      corrigidas.push(sheet.getName() + ':' +
        (valorTrocado.length ? ' data em ' + valorTrocado.join(', ') + ';' : '') +
        (formatoTrocado.length ? ' formato em ' + formatoTrocado.join(', ') : ''));
    }
  });

  const resumo = corrigidas.length
    ? 'Datas corrigidas (dia e mês estavam trocados):\n\n' + corrigidas.join('\n')
    : 'Todas as abas de dia já estão com a data do nome, em dia/mês.';
  console.log(resumo);
  try {
    SpreadsheetApp.getUi().alert('📅 Datas das abas', resumo, SpreadsheetApp.getUi().ButtonSet.OK);
  } catch (e) {
    // Rodando pelo editor: o resumo fica no registro de execução.
  }
  return corrigidas;
}

// ==============================================================================
// CONTROLE DE DOSES: UM BLOCO POR MÊS, UMA COLUNA POR DIA
// ==============================================================================
// O bloco de Novembro soma cada aba do dia sozinho: a linha "Dia" tem as datas
// em texto e as fórmulas abaixo leem a aba com esse nome por INDIRECT. Os meses
// seguintes são montados copiando essas fórmulas, com linhas e colunas
// ajustadas. O texto vem de getFormulas() e volta por setFormulas() na mesma
// planilha, então o separador (";" em pt_BR, "," em inglês) é sempre o dela.
var NOMES_DOS_MESES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho',
                       'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
var ABA_CONTROLE_DE_DOSES = 'Controle de doses';

function letraDaColuna_(n) {
  let letras = '';
  while (n > 0) {
    const resto = (n - 1) % 26;
    letras = String.fromCharCode(65 + resto) + letras;
    n = Math.floor((n - 1) / 26);
  }
  return letras;
}

/**
 * Soma `deltaLinha` às linhas de todas as referências A1 da fórmula e troca as
 * colunas listadas em `colunas` ({ B: 'X' }). Texto entre aspas não muda: em
 * INDIRECT("'"&B$30&"'!M2:M") só o B$30 é referência.
 */
function moverFormula_(formula, deltaLinha, colunas) {
  return String(formula || '').split(/("(?:[^"]|"")*")/).map(function (trecho, i) {
    if (i % 2 === 1) return trecho;
    return trecho.replace(/(^|[^A-Za-z0-9_.$])(\$?)([A-Z]{1,3})(\$?)(\d+)(?![A-Za-z0-9_(])/g,
      function (_, antes, fixaCol, col, fixaLinha, linha) {
        return antes + fixaCol + (colunas[col] || col) + fixaLinha + (Number(linha) + deltaLinha);
      });
  }).join('');
}

/** A data (DD/MM/AAAA) já tem coluna em alguma linha "Dia" do Controle de doses? */
function dataNoControleDeDoses_(cd, data) {
  return cd.getDataRange().getDisplayValues().some(function (linha) {
    return String(linha[0]).trim() === 'Dia' && linha.indexOf(data) > 0;
  });
}

/**
 * Monta, depois do mês-modelo e no mesmo ano, cada mês cujo bloco ainda não tem
 * a linha "Dia". Só escreve nas 7 linhas logo abaixo de "Recebida no mês" e só
 * se elas estiverem vazias da coluna B em diante. Devolve o que fez em cada mês.
 */
function montarMesesNoControleDeDoses_(cd) {
  const faixa = cd.getDataRange();
  const valores = faixa.getDisplayValues();
  const formulas = faixa.getFormulas();
  const texto = function (i, j) { return String((valores[i] || [])[j] || '').trim(); };

  let modelo = -1;
  for (let i = 0; i + 1 < valores.length; i++) {
    if (texto(i, 0) === 'Dia' && /INDIRECT/i.test((formulas[i + 1] || [])[1] || '')) { modelo = i; break; }
  }
  if (modelo < 0) {
    throw new Error('Não achei no "Controle de doses" um mês já ligado às abas ' +
      '(linha "Dia" com fórmulas embaixo) para servir de modelo.');
  }
  const totalModelo = valores[modelo].indexOf('Total') + 1;
  const data = valores[modelo].map(function (c) { return dataBR_(String(c).trim()); })
    .filter(function (d) { return d; })[0];
  if (totalModelo < 3 || !data) {
    throw new Error('O mês-modelo do "Controle de doses" precisa ter datas DD/MM/AAAA e a coluna "Total".');
  }
  const mesModelo = Number(data.split('/')[1]);
  const ano = Number(data.split('/')[2]);
  const linhasDoMes = valores.map(function (l, i) { return NOMES_DOS_MESES.indexOf(texto(i, 0)) >= 0 ? i : -1; })
    .filter(function (i) { return i >= 0; });

  const feitos = [];
  for (let mes = mesModelo + 1; mes <= 12; mes++) {
    const nome = NOMES_DOS_MESES[mes - 1];
    const inicio = linhasDoMes.filter(function (i) { return i > modelo && texto(i, 0) === nome; })[0];
    if (inicio === undefined) { feitos.push(nome + ': bloco não encontrado'); continue; }
    const fim = linhasDoMes.filter(function (i) { return i > inicio; })[0] || valores.length + 50;
    let recebida = -1;
    for (let i = inicio + 1; i < Math.min(fim, valores.length); i++) {
      if (/^recebida/i.test(texto(i, 0))) { recebida = i; break; }
    }
    if (recebida < 0) { feitos.push(nome + ': sem a linha "Recebida no mês"'); continue; }
    const cab = recebida + 1;
    if (texto(cab, 0) === 'Dia') { feitos.push(nome + ': já estava montado'); continue; }
    if (cab + 6 >= fim) { feitos.push(nome + ': sem as 7 linhas livres'); continue; }
    const dias = new Date(Date.UTC(ano, mes, 0)).getUTCDate();
    const colTotal = 2 + dias;
    let ocupado = false;
    for (let i = cab; i <= cab + 6; i++) {
      for (let j = 1; j < colTotal; j++) if (texto(i, j) || (formulas[i] || [])[j]) ocupado = true;
    }
    if (ocupado) { feitos.push(nome + ': as linhas ' + (cab + 1) + ' a ' + (cab + 7) + ' já têm dados; nada mudou'); continue; }

    const delta = cab - modelo;
    const ultimoDiaModelo = letraDaColuna_(totalModelo - 1);
    const datas = [];
    for (let d = 1; d <= dias; d++) datas.push(('0' + d).slice(-2) + '/' + ('0' + mes).slice(-2) + '/' + ano);
    const matriz = [];
    for (let k = 1; k <= 5; k++) {
      const linha = [];
      for (let c = 2; c < colTotal; c++) {
        linha.push(moverFormula_(formulas[modelo + k][1], delta, { B: letraDaColuna_(c) }));
      }
      const mapaTotal = {};
      mapaTotal[ultimoDiaModelo] = letraDaColuna_(colTotal - 1);
      linha.push(moverFormula_(formulas[modelo + k][totalModelo - 1], delta, mapaTotal));
      matriz.push(linha);
    }
    const mapaEstoque = {};
    mapaEstoque[letraDaColuna_(totalModelo)] = letraDaColuna_(colTotal);

    // Mês de 31 dias vai até a coluna AG; a aba pode terminar antes.
    if (cd.getMaxColumns() < colTotal) cd.insertColumnsAfter(cd.getMaxColumns(), colTotal - cd.getMaxColumns());
    for (let c = 1; c <= colTotal; c++) {
      const origem = c === 1 ? 1 : c === colTotal ? totalModelo : 2;
      cd.getRange(modelo + 1, origem, 7, 1).copyFormatToRange(cd, c, c, cab + 1, cab + 7);
    }
    cd.getRange(cab + 1, 1, 7, 1).setValues([0, 1, 2, 3, 4, 5, 6].map(function (k) { return [texto(modelo + k, 0)]; }));
    const cabecalho = cd.getRange(cab + 1, 2, 1, dias + 1);
    cabecalho.setNumberFormat('@');
    cabecalho.setValues([datas.concat(['Total'])]);
    cd.getRange(cab + 2, 2, 5, dias + 1).setFormulas(matriz);
    cd.getRange(cab + 7, 2).setFormulas([[moverFormula_(formulas[modelo + 6][1], delta, mapaEstoque)]]);
    feitos.push(nome + ': ' + dias + ' dias ligados às abas (linha ' + (cab + 1) + ')');
  }
  return feitos;
}

function prepararMesesNoControleDeDoses() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const feitos = montarMesesNoControleDeDoses_(ss.getSheetByName(ABA_CONTROLE_DE_DOSES))
    .concat(organizarDiasNoControleDeDoses_(ss));
  const resumo = feitos.length ? feitos.join('\n') : 'Nenhum mês depois do modelo para montar.';
  console.log(resumo);
  try {
    SpreadsheetApp.getUi().alert('📆 Controle de doses', resumo, SpreadsheetApp.getUi().ButtonSet.OK);
  } catch (e) {
    // Rodando pelo editor: o resumo fica no registro de execução.
  }
  return feitos;
}

/**
 * Em cada mês ligado às abas, a linha "Dia" passa a listar só as datas que têm
 * aba, em ordem, e as outras colunas ficam vazias. As fórmulas de baixo leem a
 * aba pelo texto do cabeçalho, então acompanham a data. O mês que tiver número
 * digitado à mão nas linhas de baixo não é mexido: esse número não andaria
 * junto com a data.
 */
function organizarDiasNoControleDeDoses_(ss) {
  const cd = ss.getSheetByName(ABA_CONTROLE_DE_DOSES);
  if (!cd) return [];
  const abas = ss.getSheets().map(function (s) { return dataDoNomeDaAba_(s.getName()); })
    .filter(function (d) { return d; });
  const faixa = cd.getDataRange();
  const valores = faixa.getDisplayValues();
  const formulas = faixa.getFormulas();
  const texto = function (i, j) { return String((valores[i] || [])[j] || '').trim(); };
  const ordem = function (d) { const p = d.split('/'); return p[2] + p[1] + p[0]; };

  let anoPadrao = 0;
  valores.forEach(function (linha, i) {
    if (texto(i, 0) !== 'Dia') return;
    linha.forEach(function (c) { const d = dataBR_(String(c).trim()); if (d) anoPadrao = Number(d.split('/')[2]); });
  });
  if (!anoPadrao) anoPadrao = new Date().getFullYear();

  const feitos = [];
  for (let h = 0; h + 5 < valores.length; h++) {
    if (texto(h, 0) !== 'Dia' || !/INDIRECT/i.test((formulas[h + 1] || [])[1] || '')) continue;
    let mes = 0;
    for (let i = h - 1; i >= 0 && !mes; i--) mes = NOMES_DOS_MESES.indexOf(texto(i, 0)) + 1;
    const total = valores[h].indexOf('Total') + 1;
    if (!mes || total < 3) continue;
    const nome = NOMES_DOS_MESES[mes - 1];
    const vagas = total - 2;

    let ano = 0;
    valores[h].forEach(function (c) { const d = dataBR_(String(c).trim()); if (d) ano = Number(d.split('/')[2]); });
    if (!ano) ano = anoPadrao;
    const mm = ('0' + mes).slice(-2);
    const datas = abas.filter(function (d) { return d.slice(3) === mm + '/' + ano; })
      .sort(function (a, b) { return ordem(a) < ordem(b) ? -1 : ordem(a) > ordem(b) ? 1 : 0; })
      .filter(function (d, i, lista) { return lista.indexOf(d) === i; });
    if (datas.length > vagas) { feitos.push(nome + ': mais abas de dia do que colunas; nada mudou'); continue; }

    let digitado = '';
    for (let i = h + 1; i <= h + 5 && !digitado; i++) {
      for (let j = 1; j < total - 1; j++) {
        if (texto(i, j) && !(formulas[i] || [])[j]) { digitado = faixa.getCell(i + 1, j + 1).getA1Notation(); break; }
      }
    }
    if (digitado) { feitos.push(nome + ': ' + digitado + ' tem número digitado; nada mudou'); continue; }

    const novo = datas.slice();
    while (novo.length < vagas) novo.push('');
    const atual = valores[h].slice(1, total - 1).map(function (c) { return String(c).trim(); });
    if (atual.join('|') === novo.join('|')) continue;
    cd.getRange(h + 1, 2, 1, vagas).setNumberFormat('@').setValues([novo]);
    feitos.push(nome + ': ' + (datas.length ? datas.join(', ') : 'nenhuma aba de dia'));
  }
  return feitos;
}

function organizarDiasNoControleDeDoses() {
  const feitos = organizarDiasNoControleDeDoses_(SpreadsheetApp.getActiveSpreadsheet());
  const resumo = feitos.length ? feitos.join('\n') : 'O "Controle de doses" já mostra só os dias com aba.';
  console.log(resumo);
  try {
    SpreadsheetApp.getUi().alert('🗓️ Dias no Controle de doses', resumo, SpreadsheetApp.getUi().ButtonSet.OK);
  } catch (e) {
    // Rodando pelo editor ou pelo acionador: o resumo fica no registro de execução.
  }
  return feitos;
}

/**
 * Reorganiza os dias do "Controle de doses" só quando a lista de abas de dia
 * mudou desde a última vez (aba criada, renomeada ou apagada). Chamada a cada
 * edição pelo acionador onEditInstalado e ao abrir a planilha, então custa só
 * ler os nomes das abas quando nada mudou.
 */
function organizarDiasSeAbasMudaram_(ss) {
  const assinatura = ss.getSheets().map(function (s) { return dataDoNomeDaAba_(s.getName()); })
    .filter(function (d) { return d; }).sort().join(',');
  const props = PropertiesService.getDocumentProperties();
  if (props.getProperty('DIAS_CONTROLE_DE_DOSES') === assinatura) return [];
  const feitos = organizarDiasNoControleDeDoses_(ss);
  props.setProperty('DIAS_CONTROLE_DE_DOSES', assinatura);
  return feitos;
}

/**
 * Para um acionador instalável "Ao alterar", se um dia for criado: reage na
 * hora a aba criada, renomeada ou apagada.
 */
function aoMudarPlanilha(e) {
  if (e && ['INSERT_GRID', 'REMOVE_GRID', 'OTHER'].indexOf(e.changeType) === -1) return;
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(20000)) return;
  try {
    const feitos = organizarDiasNoControleDeDoses_((e && e.source) || SpreadsheetApp.getActiveSpreadsheet());
    if (feitos.length) console.log(feitos.join('\n'));
  } catch (err) {
    console.error('aoMudarPlanilha: ' + err);
  } finally {
    lock.releaseLock();
  }
}

// ==============================================================================
// 6. MÓDULO: LINKS DO GOOGLE MAPS
// ==============================================================================
function gerarLinksMapa() {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const todasAsAbas = ss.getSheets();

    const abasParaProcessar = todasAsAbas.filter(function (sheet) {
      const nomeAba = sheet.getName();
      const padraoData = /^\d+\s*-\s*\d{2}\/\d{2}\/\d{4}/;
      const nomesEspecificos = ['Manhã', 'Tarde', 'Vacinação', 'Vacinação 2026', 'Agendadas'];
      return padraoData.test(nomeAba) || nomesEspecificos.indexOf(nomeAba) !== -1;
    });

    const resultados = [];

    abasParaProcessar.forEach(function (sheet) {
      const nomeAba = sheet.getName();
      try {
        const resultado = gerarLinksMapaNaAba(sheet);
        resultados.push('✅ ' + nomeAba + ': ' + resultado.linksGerados + ' links gerados');
      } catch (error) {
        resultados.push('❌ ' + nomeAba + ': Erro - ' + error.message);
      }
    });

    const ui = SpreadsheetApp.getUi();
    const mensagem = resultados.length > 0
      ? resultados.join('\n')
      : 'Nenhuma aba com o padrão de data ou nome específico foi encontrada.';

    ui.alert('🗺️ Links do Mapa Gerados', mensagem, ui.ButtonSet.OK);

  } catch (error) {
    Logger.log('Erro em gerarLinksMapa: ' + error.toString());
    SpreadsheetApp.getUi().alert('Erro ao gerar links: ' + error.toString());
  }
}

function gerarLinksMapaNaAba(sheet) {
  try {
    const data = sheet.getDataRange().getValues();

    if (data.length <= 1) {
      return { linksGerados: 0, colunaLink: -1 };
    }

    const col = colunas_(detectarOffset_(data));

    let colunaLink = data[0].indexOf("Link do Mapa") + 1;
    if (colunaLink === 0) {
      colunaLink = data[0].length + 1;
      sheet.getRange(1, colunaLink).setValue("Link do Mapa");
    }

    let linksGerados = 0;

    for (let i = 1; i < data.length; i++) {
      const linha = data[i];

      if (linha[col.endereco] && linha[col.numero] && linha[col.bairro]) {
        const endereco = linha[col.endereco].toString().trim();
        const numero = linha[col.numero].toString().trim();
        const complemento = linha[col.complemento] ? linha[col.complemento].toString().trim() : '';
        const bairro = linha[col.bairro].toString().trim();

        const enderecoLimpo = endereco.replace(/\b(segunda|terça|quarta|quinta|sexta|sábado|domingo)\b/gi, '').trim();

        let enderecoCompleto = enderecoLimpo + ' ' + numero + ', ' + bairro;
        if (complemento) {
          enderecoCompleto += ', ' + complemento;
        }
        enderecoCompleto += ', Orlândia - SP';

        const linkMapa = 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(enderecoCompleto);
        sheet.getRange(i + 1, colunaLink).setValue(linkMapa);
        linksGerados++;
      }
    }

    if (linksGerados > 0) {
      sheet.autoResizeColumn(colunaLink);
    }

    return { linksGerados: linksGerados, colunaLink: colunaLink };

  } catch (error) {
    Logger.log('Erro em gerarLinksMapaNaAba: ' + error.toString());
    throw error;
  }
}

// ==============================================================================
// 7. FUNÇÕES AUXILIARES DE TEXTO E ANIMAIS
// ==============================================================================
function normalizarTexto(texto) {
  if (!texto) return "";
  return String(texto)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function extrairListaAnimais(texto) {
  if (!texto) return [];
  const norm = normalizarTexto(texto);
  return norm
    .replace(/\s+(e|&|\+)\s+/gi, ',')
    .split(/[,;\/]+/)
    .map(function (item) { return item.trim(); })
    .filter(function (item) { return item.length >= 2; });
}


// ==============================================================================
// 8. CONTATOS PARA O WHATSAPP
// ==============================================================================
/**
 * Monta a aba "Contatos V (WhatsApp)" no formato que o Google Contatos importa.
 * Um contato por pessoa: telefones da mesma pessoa viram Phone 1 e Phone 2, e
 * o nome sai como "V Tutor (Animais) - Rua Numero" para identificar a origem.
 */
function gerarContatosWhatsApp() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const origem = ss.getSheetByName("Vacinação 2026");
  if (!origem) { SpreadsheetApp.getUi().alert('Aba "Vacinação 2026" não encontrada.'); return; }
  const dados = origem.getDataRange().getValues().slice(1);

  function normalizarFone(valor) {
    var d = String(valor == null ? "" : valor).replace(/\D/g, "");
    if (!d) return "";
    if (d.length === 13 && d.indexOf("55") === 0) d = d.slice(2);
    if (d.length === 9 && d.charAt(0) === "9") d = "16" + d;
    if (d.length !== 11 || d.charAt(2) !== "9") return "";
    return "+55" + d;
  }
  function limparAnimais(texto) {
    var x = String(texto || "").replace(/\s+/g, " ").trim();
    x = x.replace(/\b(Cachorr[oa]s?|C[ãa]es|C[ãa]o|Gat[oa]s?)\s*\d*\s*[-:]\s*/gi, "");
    x = x.replace(/[;\/]/g, ",").replace(/\s*,\s*/g, ", ").replace(/^[,\s]+|[,\s]+$/g, "");
    var vistos = {}, saida = [];
    x.split(/,| e /i).forEach(function (p) {
      var t = p.trim(); if (!t) return;
      var k = t.toLowerCase(); if (vistos[k]) return; vistos[k] = 1; saida.push(t);
    });
    return saida.join(", ").slice(0, 60);
  }
  function titulo(s) {
    return String(s || "").replace(/\s+/g, " ").trim().split(" ").map(function (w) {
      return w.length > 2 ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : w.toLowerCase();
    }).join(" ");
  }

  const porNumero = {};
  const semCelular = [];
  dados.forEach(function (r) {
    const nome = titulo(r[1]);
    if (!nome) return;
    const endereco = (String(r[2] || "").replace(/\s+/g, " ").trim() + " " + String(r[3] || "").trim()).trim();
    const animais = limparAnimais(r[10]);
    const fones = [normalizarFone(r[6]), normalizarFone(r[7])].filter(function (f, i, a) { return f && a.indexOf(f) === i; });
    if (!fones.length) { semCelular.push(nome); return; }
    fones.forEach(function (f) {
      if (!porNumero[f]) porNumero[f] = { nomes: [], enderecos: [], animais: [] };
      const reg = porNumero[f];
      if (reg.nomes.indexOf(nome) === -1) reg.nomes.push(nome);
      if (endereco && reg.enderecos.indexOf(endereco) === -1) reg.enderecos.push(endereco);
      if (animais && reg.animais.indexOf(animais) === -1) reg.animais.push(animais);
    });
  });

  const porPessoa = {};
  Object.keys(porNumero).forEach(function (fone) {
    const reg = porNumero[fone];
    var complemento = "";
    const animais = limparAnimais(reg.animais.join(", "));
    if (animais) complemento = "(" + animais + ")";
    if (reg.enderecos[0]) complemento += (complemento ? " - " : "") + reg.enderecos[0];
    if (reg.nomes.length > 1) complemento += " [tb " + reg.nomes.slice(1).join("; ") + "]";
    const chave = reg.nomes[0] + "|" + complemento;
    if (!porPessoa[chave]) porPessoa[chave] = { nome: reg.nomes[0], complemento: complemento, fones: [] };
    if (porPessoa[chave].fones.indexOf(fone) === -1) porPessoa[chave].fones.push(fone);
  });

  const linhas = [["Name", "Given Name", "Family Name", "Phone 1 - Type", "Phone 1 - Value", "Phone 2 - Type", "Phone 2 - Value", "Notes"]];
  Object.keys(porPessoa).sort().forEach(function (k) {
    const c = porPessoa[k];
    const nomeCompleto = "V " + c.nome + (c.complemento ? " " + c.complemento : "");
    linhas.push([nomeCompleto, "V " + c.nome, c.complemento, "Mobile", c.fones[0] || "", c.fones[1] ? "Mobile" : "", c.fones[1] || "", "Cadastro da vacinacao antirrabica de Orlandia"]);
  });

  var aba = ss.getSheetByName("Contatos V (WhatsApp)");
  if (!aba) aba = ss.insertSheet("Contatos V (WhatsApp)");
  aba.clear();
  aba.getRange(1, 1, linhas.length, linhas[0].length).setValues(linhas);
  aba.setFrozenRows(1);

  try { SpreadsheetApp.getUi().alert(
    "Contatos prontos",
    (linhas.length - 1) + " contatos na aba \"Contatos V (WhatsApp)\".\n\n" +
    semCelular.length + " tutores ficaram sem celular válido: " + semCelular.slice(0, 10).join(", ") +
    "\n\nPara importar: Arquivo > Fazer download > CSV com esta aba aberta, depois contacts.google.com > Importar.",
    SpreadsheetApp.getUi().ButtonSet.OK
  ); } catch (semUi) { Logger.log("Sem UI: " + (linhas.length - 1) + " contatos; sem celular: " + semCelular.length); }
  return linhas.length - 1;
}

// ==============================================================================
// QUADRO "STATUS PMO": A PLANILHA SE CONFERE SOZINHA
// ==============================================================================
/**
 * Mantém a coluna "Status PMO" da aba "Vacinação 2026" apontando para onde cada
 * inscrição está AGORA.
 *
 * O PetOrlândia grava o quadro com o número da linha de cada aba
 * ("Inscrição a agendar (linha 84)"). Depois disso a equipe agenda a pessoa num
 * dia, reordena a aba ou apaga a linha, e o link passava a abrir uma linha vazia
 * ou o cadastro de outra pessoa. Esta conferência relê as abas, acha cada tutor
 * pelo nome + telefone (ou nome + endereço) e reescreve as linhas do quadro com
 * a posição atual. Quem não é encontrado com segurança fica sem link, como
 * "não encontrado", em vez de apontar para outra pessoa.
 *
 * Roda ao editar a planilha (onEditInstalado), depois de "Otimizar Rotas por
 * Cluster", pelo menu e pelo acionador de tempo `conferirQuadroPeriodico` — este
 * pega o que o PetOrlândia grava pela API, que não dispara "Ao editar".
 */
var QUADRO_STATUS = {
  abaMestre: 'Vacinação 2026',
  colunaStatus: 13, // M
  // Abas de fila e o status de quem aparece nelas sem registro anterior.
  abasDeFila: { 'inscricao a agendar': 'Fluxo ativo', 'agendadas': 'Pendente', 'encaixes': 'Reagendar' },
  intervaloAposEdicaoMs: 60 * 1000,
  intervaloSemEdicaoMs: 15 * 60 * 1000,
  maxLocais: 8,
  corFluxo: '#c9daf8',  // azul claro do PetOrlândia: agendado / fluxo ativo
  corNeutra: '#ffffff'
};

// Primeira linha do quadro, como o PetOrlândia escreve (STATUS_LABELS).
var ROTULOS_STATUS_PMO = ['Vacinado', 'Parcial', 'Parcial encerrado', 'Remarcar', 'Cancelado/recusou',
  'Ausente', 'Pendente', 'Agendado', 'Fluxo ativo', 'Perdeu contato', 'Reagendar', 'Sem registro'];

// Títulos que só dizem "onde está na fila"; os demais são resultado de campo e
// continuam sendo decididos pelo PetOrlândia.
var TITULOS_DE_FLUXO = ['', 'Sem registro', 'Pendente', 'Fluxo ativo', 'Agendado', 'Reagendar'];

function chaveTexto_(valor) {
  return normalizarTexto(String(valor == null ? '' : valor))
    .replace(/[^a-z0-9]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function tokensCasam_(a, b) {
  if (a === b) return true;
  if (a.length === 1 && b.indexOf(a) === 0) return true;
  return b.length === 1 && a.indexOf(b) === 0;
}

function subsequenciaOrdenada_(curta, longa) {
  let j = 0;
  for (let i = 0; i < curta.length; i++) {
    while (j < longa.length && !tokensCasam_(curta[i], longa[j])) j++;
    if (j >= longa.length) return false;
    j++;
  }
  return true;
}

/**
 * Duas grafias que podem ser a MESMA pessoa (mesma regra do PetOrlândia,
 * `_name_texts_compatible`): iguais; a curta é subsequência da longa ("Raquel F."
 * / "Raquel Feliciano"); só o primeiro nome, abrindo o nome completo; ou 75% dos
 * nomes em comum.
 */
function nomesCompativeis_(a, b) {
  const ka = chaveTexto_(a);
  const kb = chaveTexto_(b);
  if (!ka || !kb) return false;
  if (ka === kb) return true;
  const ta = ka.split(' ');
  const tb = kb.split(' ');
  const curta = ta.length <= tb.length ? ta : tb;
  const longa = curta === ta ? tb : ta;
  if (curta.length === 1) return curta[0].length >= 3 && curta[0] === longa[0];
  if (subsequenciaOrdenada_(curta, longa)) return true;
  const sa = ta.filter(function (t) { return t.length >= 3; });
  const sb = tb.filter(function (t) { return t.length >= 3; });
  if (!sa.length || !sb.length) return false;
  const comuns = sa.filter(function (t, i) { return sa.indexOf(t) === i && sb.indexOf(t) !== -1; }).length;
  const menor = Math.min(new Set(sa).size, new Set(sb).size);
  return menor >= 2 && comuns / menor >= 0.75;
}

/**
 * Telefones com DDD (10 ou 11 últimos dígitos). A equipe às vezes digita os dois
 * números na mesma célula ("16 99251-0438 / 16 99144-3152"); cada um vira chave.
 */
function chavesTelefone_(valores) {
  const chaves = {};
  valores.forEach(function (valor) {
    String(valor == null ? '' : valor).split(/\/|;|,|\||\bou\b|\be\b/).forEach(function (parte) {
      const d = parte.replace(/\D+/g, '');
      if (d.length >= 10) chaves[d.slice(-10)] = true;
      if (d.length >= 11) chaves[d.slice(-11)] = true;
    });
  });
  return Object.keys(chaves);
}

function pessoaDaLinha_(linha, col) {
  const nome = String(linha[col.tutor] == null ? '' : linha[col.tutor]).trim();
  const numero = chaveTexto_(linha[col.numero]);
  return {
    nome: nome,
    chaveNome: chaveTexto_(nome),
    telefones: chavesTelefone_([linha[col.telefone1], linha[col.telefone2]]),
    // Sem número a rua sozinha não identifica a casa.
    endereco: numero ? (chaveTexto_(linha[col.endereco]) + numero).replace(/ /g, '') : ''
  };
}

/**
 * A linha de outra aba é a mesma casa da inscrição? Nome compatível sempre; com
 * telefone dos dois lados, o telefone precisa bater (dois "Maria" na mesma rua
 * não se misturam); sem telefone, vale o endereço ou o nome completo idêntico.
 */
function mesmaPessoa_(a, b) {
  if (!nomesCompativeis_(a.nome, b.nome)) return false;
  if (a.telefones.length && b.telefones.length) {
    return a.telefones.some(function (t) { return b.telefones.indexOf(t) !== -1; });
  }
  if (a.endereco && a.endereco === b.endereco) return true;
  return a.chaveNome === b.chaveNome && a.chaveNome.split(' ').length >= 2;
}

function statusPadraoDaAba_(nome) {
  return QUADRO_STATUS.abasDeFila[chaveTexto_(nome)] || '';
}

function ehAbaDoQuadro_(nome) {
  return !!(statusPadraoDaAba_(nome) || dataDoNomeDaAba_(nome));
}

/** Todas as linhas das abas de fila e de dia, indexadas por telefone e nome. */
function indiceDeLocais_(ss) {
  const indice = { porTelefone: {}, porNome: {} };
  ss.getSheets().forEach(function (aba) {
    const nome = aba.getName();
    if (!ehAbaDoQuadro_(nome)) return;
    const ultima = aba.getLastRow();
    if (ultima < 2) return;
    const dados = aba.getRange(1, 1, ultima, Math.min(9, aba.getMaxColumns())).getValues();
    const col = colunas_(detectarOffset_(dados));
    const data = dataDoNomeDaAba_(nome);
    for (let i = 1; i < dados.length; i++) {
      const local = pessoaDaLinha_(dados[i], col);
      if (!local.chaveNome) continue;
      local.aba = nome;
      local.gid = aba.getSheetId();
      local.linha = i + 1;
      local.dia = data ? data.split('/').reverse().join('-') : '';
      local.statusPadrao = statusPadraoDaAba_(nome);
      const primeiro = local.chaveNome.split(' ')[0];
      (indice.porNome[primeiro] = indice.porNome[primeiro] || []).push(local);
      local.telefones.forEach(function (t) {
        (indice.porTelefone[t] = indice.porTelefone[t] || []).push(local);
      });
    }
  });
  return indice;
}

function locaisDaPessoa_(pessoa, indice) {
  const vistos = [];
  const candidatos = (indice.porNome[pessoa.chaveNome.split(' ')[0]] || []).slice();
  pessoa.telefones.forEach(function (t) {
    (indice.porTelefone[t] || []).forEach(function (l) { candidatos.push(l); });
  });
  candidatos.forEach(function (l) {
    if (vistos.indexOf(l) === -1 && mesmaPessoa_(pessoa, l)) vistos.push(l);
  });
  return vistos.sort(function (a, b) {
    // Dias primeiro, em ordem de data; depois as abas de fila.
    const ka = (a.dia ? '0' + a.dia : '1' + a.aba) + ('00000' + a.linha).slice(-5);
    const kb = (b.dia ? '0' + b.dia : '1' + b.aba) + ('00000' + b.linha).slice(-5);
    return ka < kb ? -1 : ka > kb ? 1 : 0;
  });
}

/** O quadro já gravado: título e, por aba, os status de cada linha. */
function lerQuadro_(texto) {
  const linhas = String(texto || '').split('\n')
    .map(function (s) { return s.trim(); }).filter(function (s) { return s; });
  const titulo = linhas.length && ROTULOS_STATUS_PMO.indexOf(linhas[0]) !== -1 ? linhas.shift() : '';
  const locais = [];
  if (titulo) {
    linhas.forEach(function (linha) {
      const m = linha.match(/^(.+?)(?: \(([^)]*)\))?: (.+)$/);
      if (m) locais.push({ aba: m[1], status: m[3] });
    });
  }
  return { titulo: titulo, locais: locais };
}

function tituloDoQuadro_(titulo, linhas, hoje) {
  if (titulo === 'Vacinado') return titulo;
  const achadas = linhas.filter(function (l) { return l.url; });
  // Marcado num dia que ainda vem: de volta ao fluxo, como no PetOrlândia.
  if (achadas.some(function (l) { return l.dia && l.dia >= hoje && !/^Vacinado/.test(l.status); })) {
    return 'Agendado';
  }
  if (TITULOS_DE_FLUXO.indexOf(titulo) === -1) return titulo;
  if (achadas.some(function (l) { return l.dia; })) return 'Agendado';
  const naAba = function (nome) { return achadas.some(function (l) { return chaveTexto_(l.aba) === nome; }); };
  if (naAba('inscricao a agendar')) return 'Fluxo ativo';
  if (naAba('encaixes')) return titulo === 'Reagendar' || titulo === 'Pendente' ? titulo : 'Reagendar';
  if (!titulo || titulo === 'Agendado' || titulo === 'Fluxo ativo') return 'Pendente';
  return titulo;
}

/**
 * Texto novo do quadro. Cada linha encontrada reaproveita o status que o
 * PetOrlândia já tinha escrito para aquela aba; aba de dia que tinha registro e
 * onde a pessoa não está mais vira "não encontrado", sem link. Sair de uma aba de
 * fila é o fluxo normal, então essa linha some.
 */
function montarQuadro_(antigo, achados, hoje, idPlanilha) {
  const anteriores = {};
  antigo.locais.forEach(function (l) { (anteriores[l.aba] = anteriores[l.aba] || []).push(l.status); });
  const linhas = achados.map(function (a) {
    const fila = anteriores[a.aba];
    const status = (fila && fila.length && fila.shift()) ||
      a.statusPadrao || (a.dia >= hoje ? 'Pendente' : 'Conferir');
    return {
      texto: a.aba + ' (linha ' + a.linha + '): ' + status,
      url: 'https://docs.google.com/spreadsheets/d/' + idPlanilha + '/edit#gid=' + a.gid + '&range=A' + a.linha,
      aba: a.aba, dia: a.dia, status: status
    };
  });
  Object.keys(anteriores).forEach(function (aba) {
    const data = dataDoNomeDaAba_(aba);
    if (!data) return;
    anteriores[aba].forEach(function (status) {
      linhas.push({ texto: aba + ' (não encontrado): ' + status, url: '', aba: aba,
        dia: data.split('/').reverse().join('-'), status: status });
    });
  });
  linhas.sort(function (a, b) {
    const ka = a.dia ? '0' + a.dia : '1';
    const kb = b.dia ? '0' + b.dia : '1';
    return ka < kb ? -1 : ka > kb ? 1 : 0;
  });
  const titulo = tituloDoQuadro_(antigo.titulo, linhas, hoje);
  let texto = titulo;
  const links = [];
  linhas.slice(0, QUADRO_STATUS.maxLocais).forEach(function (l) {
    texto += '\n';
    if (l.url) links.push({ inicio: texto.length, fim: texto.length + l.aba.length, url: l.url });
    texto += l.texto;
  });
  if (linhas.length > QUADRO_STATUS.maxLocais) {
    texto += '\n+' + (linhas.length - QUADRO_STATUS.maxLocais) + ' outros';
  }
  return { titulo: titulo, texto: texto, links: links };
}

function linksDoTexto_(rico) {
  if (!rico || !rico.getRuns) return [];
  return rico.getRuns().map(function (r) { return r.getLinkUrl(); }).filter(function (u) { return u; });
}

/** Tutor da nota que o PetOrlândia grava na coluna A ("Tutor: ..."). */
function tutorDaNota_(nota) {
  const m = String(nota || '').match(/^Tutor:\s*(.+)$/m);
  return m && /^\s*PetOrlandia PMO/.test(String(nota)) ? m[1].trim() : '';
}

function corDoTitulo_(titulo) {
  if (titulo === 'Agendado' || titulo === 'Fluxo ativo') return QUADRO_STATUS.corFluxo;
  if (titulo === 'Pendente' || titulo === 'Reagendar' || titulo === 'Sem registro') return QUADRO_STATUS.corNeutra;
  return '';
}

function conferirQuadro_(ss, simular) {
  const resumo = { conferidas: 0, atualizadas: 0, exemplos: [] };
  const mestre = ss.getSheetByName(QUADRO_STATUS.abaMestre);
  if (!mestre) return resumo;
  const ultima = mestre.getLastRow();
  if (ultima < 2) return resumo;
  const dados = mestre.getRange(1, 1, ultima, QUADRO_STATUS.colunaStatus - 1).getValues();
  const col = colunas_(detectarOffset_(dados));
  const notas = mestre.getRange(2, 1, ultima - 1, 1).getNotes();
  const atuais = mestre.getRange(2, QUADRO_STATUS.colunaStatus, ultima - 1, 1).getRichTextValues();
  const indice = indiceDeLocais_(ss);
  const hoje = Utilities.formatDate(new Date(), ss.getSpreadsheetTimeZone(), 'yyyy-MM-dd');
  const idPlanilha = ss.getId();
  const mudancas = [];

  for (let i = 1; i < dados.length; i++) {
    const pessoa = pessoaDaLinha_(dados[i], col);
    if (!pessoa.chaveNome) continue;
    resumo.conferidas++;
    const atual = atuais[i - 1][0];
    const textoAtual = atual ? atual.getText() : '';
    let antigo = lerQuadro_(textoAtual);
    // Texto digitado por alguém na coluna M: não é nosso, não mexe.
    if (textoAtual.trim() && !antigo.titulo) continue;
    // Quadro de OUTRO tutor (a aba mestre foi regravada e a nota ficou): não
    // herda status de ninguém, recomeça só com o que achar agora.
    const tutorNota = tutorDaNota_(notas[i - 1][0]);
    if (tutorNota && !nomesCompativeis_(tutorNota, pessoa.nome)) antigo = { titulo: '', locais: [] };
    const achados = locaisDaPessoa_(pessoa, indice);
    if (!achados.length && !antigo.locais.length) continue;
    const quadro = montarQuadro_(antigo, achados, hoje, idPlanilha);
    const linksNovos = quadro.links.map(function (l) { return l.url; });
    if (quadro.texto === textoAtual && linksNovos.join('\n') === linksDoTexto_(atual).join('\n')) continue;
    const construtor = SpreadsheetApp.newRichTextValue().setText(quadro.texto);
    quadro.links.forEach(function (l) { construtor.setLinkUrl(l.inicio, l.fim, l.url); });
    mudancas.push({ indice: i - 1, rico: construtor.build(),
      cor: quadro.titulo !== antigo.titulo ? corDoTitulo_(quadro.titulo) : '' });
    if (simular) resumo.exemplos.push('linha ' + (i + 1) + ': [' + textoAtual + '] => [' + quadro.texto + ']');
  }
  if (simular) {
    resumo.atualizadas = mudancas.length;
    return resumo;
  }

  // Grava em blocos de linhas seguidas: uma chamada por bloco, não por célula.
  let k = 0;
  while (k < mudancas.length) {
    let fim = k;
    while (fim + 1 < mudancas.length && mudancas[fim + 1].indice === mudancas[fim].indice + 1) fim++;
    const bloco = mudancas.slice(k, fim + 1);
    mestre.getRange(bloco[0].indice + 2, QUADRO_STATUS.colunaStatus, bloco.length, 1)
      .setRichTextValues(bloco.map(function (m) { return [m.rico]; }));
    k = fim + 1;
  }
  mudancas.forEach(function (m) {
    if (!m.cor) return;
    mestre.getRange(m.indice + 2, 1).setBackground(m.cor);
    mestre.getRange(m.indice + 2, QUADRO_STATUS.colunaStatus).setBackground(m.cor);
  });
  resumo.atualizadas = mudancas.length;
  return resumo;
}

/** Mostra no registro de execução o que a conferência mudaria, sem gravar nada. */
function simularConferenciaDoQuadro() {
  const resumo = conferirQuadro_(SpreadsheetApp.getActiveSpreadsheet(), true);
  console.log(resumo.atualizadas + ' de ' + resumo.conferidas + ' inscrições mudariam.\n' +
    resumo.exemplos.join('\n'));
  return resumo;
}

/** Conferência completa (menu, acionador de tempo, depois de reordenar). */
function conferirQuadroStatusPMO() {
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(5000)) return null;
  try {
    const props = PropertiesService.getDocumentProperties();
    props.setProperty('QUADRO_STATUS_ULTIMA', String(Date.now()));
    props.deleteProperty('QUADRO_STATUS_PENDENTE');
    return conferirQuadro_(SpreadsheetApp.getActiveSpreadsheet());
  } finally {
    lock.releaseLock();
  }
}

function conferirQuadroStatusPMOAgora() {
  const resumo = conferirQuadroStatusPMO();
  SpreadsheetApp.getActiveSpreadsheet().toast(
    resumo ? resumo.atualizadas + ' de ' + resumo.conferidas + ' inscrições atualizadas no Status PMO.'
      : 'Outra operação está em andamento. Tente de novo em instantes.',
    'Status PMO', 8);
}

/**
 * Chamado pelo onEditInstalado. Edição numa aba de fila, de dia ou na mestre
 * confere na hora, no máximo uma vez por minuto; o que ficar para trás é marcado
 * como pendente e o acionador de tempo pega no minuto seguinte.
 */
function conferirQuadroAposEdicao_(e) {
  const nome = e && e.range ? e.range.getSheet().getName() : '';
  if (nome && nome !== QUADRO_STATUS.abaMestre && !ehAbaDoQuadro_(nome)) return;
  const props = PropertiesService.getDocumentProperties();
  props.setProperty('QUADRO_STATUS_PENDENTE', '1');
  const ultima = Number(props.getProperty('QUADRO_STATUS_ULTIMA') || 0);
  if (Date.now() - ultima >= QUADRO_STATUS.intervaloAposEdicaoMs) conferirQuadroStatusPMO();
}

/** Acionador de tempo (a cada minuto): só trabalha quando há o que conferir. */
function conferirQuadroPeriodico() {
  const props = PropertiesService.getDocumentProperties();
  const idade = Date.now() - Number(props.getProperty('QUADRO_STATUS_ULTIMA') || 0);
  const pendente = props.getProperty('QUADRO_STATUS_PENDENTE') === '1';
  if (idade < (pendente ? QUADRO_STATUS.intervaloAposEdicaoMs : QUADRO_STATUS.intervaloSemEdicaoMs)) return;
  conferirQuadroStatusPMO();
}
