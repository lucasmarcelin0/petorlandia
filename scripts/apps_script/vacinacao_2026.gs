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
    .addSeparator()
    .addItem("🔄 Sincronizar com Planilha Origem", "sincronizarPlanilhas")
    .addSeparator()
    .addItem("🔄 Atualizar status (PetOrlândia)", "atualizarStatusPMO")
    .addItem("💉 Compilar Controle de doses", "compilarControleDeDoses")
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
  "Jardim Timboré": "E",

  // Morada do Sol (F) - SEXTO
  "Morada do Sol": "F",
  "Condomínio Quebec": "F",
  "Condomínio Toruino": "F",
  "Max Define": "F",
  "Jardim das Flores": "F",
  "Jardim Paineiras": "F",
  "Jardim José Luiz Simões": "F",
  "1º De Maio": "F",
  "Jardim dos Servidores": "F",
  "Zita de Oliveira": "F",
  "Palmito": "F",

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

  // Centro (C)
  "centro": "Centro",
  "vila marcussi": "Vila Marcussi",
  "marcussi": "Vila Marcussi",
  "jardim teixeira": "Jardim Teixeira",
  "teixeira": "Jardim Teixeira",
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
  "timbore": "Jardim Timboré",

  // Morada do Sol (F)
  "morada do sol": "Morada do Sol",
  "morada sol": "Morada do Sol",
  "condominio quebec": "Condomínio Quebec",
  "quebec": "Condomínio Quebec",
  "condominio toruino": "Condomínio Toruino",
  "toruino": "Condomínio Toruino",
  "torino": "Condomínio Toruino",
  "max define": "Max Define",
  "max leonardo define": "Max Define",
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
//     ~1000 entre a Rua 10 e a Rua 12 e ~1460 entre a Rua 18 e a Rua 20.
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
var ORDEM_CLUSTERS = {"A":1, "B":2, "C1":3, "C2":4, "D":5, "E1":6, "E2":7, "E3":8,
                      "F1":9, "F2":10, "F3":11, "F4":12, "Z":13, "ZZ":14};

// Usada só quando a rua não permite decidir (rua com nome, casa sem número).
var ZONA_PADRAO_DO_BAIRRO = {
  "Jardim Bandeirantes": "C2",
  "Jardim Santa Rita": "E1", "Jardim Siena": "E2", "Jardim Boa Vista": "E3", "Jardim Formoso": "E3",
  "Jardim Leonor Degiovani": "E3", "Jardim Timboré": "E3", "Jardim Benini": "F1",
  "Jardim Vista Linda": "F4", "Jardim José Vieira Brazão": "F4",
  "Morada do Sol": "F2", "Condomínio Quebec": "F2", "Condomínio Toruino": "F2", "Palmito": "F2",
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
    if (casa > 0) banda = casa < 280 ? "P" : casa < 1000 ? "S" : casa < 1460 ? "N" : "NN";
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
function routeOptimizeByCluster() {
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    const range = sheet.getDataRange();
    const data = range.getValues();

    if (data.length < 2) {
      SpreadsheetApp.getUi().alert("Nada para otimizar nesta aba.");
      return { success: false, totalProcessed: 0 };
    }

    const notes = range.getNotes();
    const backgrounds = range.getBackgrounds();
    // getValues() devolve o RESULTADO da fórmula. Regravar isso transformaria
    // os links de WhatsApp (=HYPERLINK) em texto morto, então as fórmulas
    // viajam junto com a linha e têm prioridade na hora de escrever.
    const formulas = range.getFormulas();
    // Cor, tamanho e estilo da letra também viajam com a linha (ex.: vermelho = encaixe), e o
    // texto com só um trecho colorido (rich text) é reaplicado depois.
    const fontes = {
      fc: range.getFontColors(), fz: range.getFontSizes(), ff: range.getFontFamilies(),
      fw: range.getFontWeights(), fs: range.getFontStyles(), fl: range.getFontLines(),
      rich: range.getRichTextValues()
    };

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
          originalFormulas: formulas[index].slice(),
          originalNotes: notes[index].slice(),
          originalBackgrounds: backgrounds[index].slice(),
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
          originalFormulas: formulas[index].slice(),
          originalNotes: notes[index].slice(),
          originalBackgrounds: backgrounds[index].slice(),
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

    const outValues = [];
    const outNotes = [];
    const outBackgrounds = [];
    const outFontes = { fc: [], fz: [], ff: [], fw: [], fs: [], fl: [] };
    const padraoFonte = { fc: "#000000", fz: 10, ff: "Arial", fw: "normal", fs: "normal", fl: "none" };

    processed.forEach(function (item) {
      const rowFormulas = item.originalFormulas || [];
      const values = item.originalData.map(function (valor, indice) {
        const formula = rowFormulas[indice];
        return (formula !== undefined && formula !== "") ? formula : valor;
      });
      const rowNotes = item.originalNotes.slice();
      const rowBackgrounds = item.originalBackgrounds.slice();

      while (values.length < totalColumns) values.push("");
      while (rowNotes.length < totalColumns) rowNotes.push("");
      while (rowBackgrounds.length < totalColumns) rowBackgrounds.push("#ffffff");

      values[clusterCol] = item.cluster;
      values[bairroCol] = item.normalizedNeighborhood;

      outValues.push(values.slice(0, totalColumns));
      outNotes.push(rowNotes.slice(0, totalColumns));
      outBackgrounds.push(rowBackgrounds.slice(0, totalColumns));

      const src = item.rowIndex - 1;
      Object.keys(outFontes).forEach(function (chave) {
        const linha = (fontes[chave][src] || []).slice(0, totalColumns);
        while (linha.length < totalColumns) linha.push(padraoFonte[chave]);
        outFontes[chave].push(linha);
      });
    });

    if (sheet.getMaxColumns() < totalColumns) {
      sheet.insertColumnsAfter(sheet.getMaxColumns(), totalColumns - sheet.getMaxColumns());
    }

    sheet.getRange(1, 1, 1, totalColumns).setValues([header]);

    if (outValues.length > 0) {
      const destino = sheet.getRange(2, 1, outValues.length, totalColumns);
      destino.setValues(outValues);
      destino.setNotes(outNotes);
      destino.setBackgrounds(outBackgrounds);
      destino.setFontColors(outFontes.fc);
      destino.setFontSizes(outFontes.fz);
      destino.setFontFamilies(outFontes.ff);
      destino.setFontWeights(outFontes.fw);
      destino.setFontStyles(outFontes.fs);
      destino.setFontLines(outFontes.fl);
      // Reaplica o texto com trechos em outra cor (ex.: só a palavra "Encaixe" em vermelho),
      // nas células que têm isso e não têm fórmula.
      processed.forEach(function (item, r) {
        const src = item.rowIndex - 1;
        const richRow = fontes.rich[src] || [];
        const rowFormulas = item.originalFormulas || [];
        const baseColors = fontes.fc[src] || [];
        richRow.forEach(function (rt, c) {
          if (!rt || rowFormulas[c] || c >= totalColumns) return;
          if (c === clusterCol || c === bairroCol) return;
          if (rt.getText() === "") return;
          const runs = rt.getRuns();
          const base = baseColors[c];
          const styled = runs.length > 1 || runs.some(function (run) {
            const cor = run.getTextStyle().getForegroundColor();
            return cor && base && cor.toLowerCase() !== String(base).toLowerCase();
          });
          if (styled) sheet.getRange(r + 2, c + 1).setRichTextValue(rt);
        });
      });
    }

    applyFormatting(sheet, outValues.length, clusterCol + 1);

    const report = generateOptimizationReport(processed);
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

function applyFormatting(sheet, dataLength, clusterColumn) {
  if (dataLength === 0) return;

  const clusterRange = sheet.getRange(2, clusterColumn, dataLength, 1);
  const rules = sheet.getConditionalFormatRules();

  rules.splice(0, rules.length);

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
    "Z": "#F5F5F5", // Cinza - Rural
    "ZZ": "#FFEBEE" // Vermelho claro - Não classificado
  };

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
  try {
    const sourceId = '1GFp6yyjPVj4UDhDEh8o-9rhmOhSAnQb6hwQprgje304';
    const nomeAbaOrigem = 'Respostas ao formulário 1';
    const nomeAbaDestino = 'Vacinação 2026';

    const sourceSpreadsheet = SpreadsheetApp.openById(sourceId);
    const sourceSheet = sourceSpreadsheet.getSheetByName(nomeAbaOrigem);

    if (!sourceSheet) {
      ui.alert('❌ Erro', 'Aba "' + nomeAbaOrigem + '" não encontrada!', ui.ButtonSet.OK);
      return;
    }

    const destSheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(nomeAbaDestino);
    if (!destSheet) {
      ui.alert('❌ Erro', 'Aba "' + nomeAbaDestino + '" não encontrada!', ui.ButtonSet.OK);
      return;
    }

    const sourceData = sourceSheet.getDataRange().getValues();

    if (sourceData.length < 2) {
      ui.alert('⚠️ Atenção', 'Planilha origem está vazia!', ui.ButtonSet.OK);
      return;
    }

    // Recolar a base inteira reposiciona todo mundo. As notas e as cores de
    // status ficam presas à célula, não ao tutor: sem limpá-las, a nota de um
    // tutor sobra no cadastro de quem passa a ocupar aquela linha.
    const ultimaLinha = destSheet.getLastRow();
    if (ultimaLinha > 1) {
      const antigo = destSheet.getRange(2, 1, ultimaLinha - 1, destSheet.getLastColumn());
      antigo.clearContent();
      antigo.clearNote();
      antigo.setBackground(null);
    }

    destSheet.getRange(2, 1, sourceData.length - 1, sourceData[0].length).setValues(sourceData.slice(1));

    ui.alert(
      '✅ Sincronização Concluída!',
      (sourceData.length - 1) + ' registros sincronizados de "' + nomeAbaOrigem + '" para "' + nomeAbaDestino + '".' +
      '\n\nRode "🔄 Atualizar status (PetOrlândia)" para o Status PMO ser recompilado nas novas posições.',
      ui.ButtonSet.OK
    );

  } catch (error) {
    ui.alert('❌ Erro', error.toString(), ui.ButtonSet.OK);
    console.error(error);
  }
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
function addWhatsAppLinks() {
  try {
    const sheet = SpreadsheetApp.getActiveSheet();
    const dataRange = sheet.getDataRange();
    const data = dataRange.getValues();
    const displayData = dataRange.getDisplayValues();

    const col = colunas_(detectarOffset_(data));

    // Reaproveita as colunas de WhatsApp se já existirem (evita uma coluna nova
    // a cada execução).
    let colWhatsApp1 = data[0].indexOf('WhatsApp 1') + 1;
    let colWhatsApp2 = data[0].indexOf('WhatsApp 2') + 1;
    if (colWhatsApp1 === 0 || colWhatsApp2 === 0) {
      colWhatsApp1 = data[0].length + 1;
      colWhatsApp2 = data[0].length + 2;
    }

    sheet.getRange(1, colWhatsApp1).setValue('WhatsApp 1');
    sheet.getRange(1, colWhatsApp2).setValue('WhatsApp 2');

    let linksAdicionados = 0;

    for (let i = 1; i < data.length; i++) {
      const row = data[i];
      const displayRow = displayData[i];

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
        data: displayRow[col.data] || '',
        turno: row[col.turno] || ''
      };

      if (tutorInfo.nome && tutorInfo.nome.toString().trim() !== '' &&
          (tutorInfo.telefone1 || tutorInfo.telefone2)) {

        const message = generateMessage(tutorInfo);
        const phone1 = cleanPhoneNumber(tutorInfo.telefone1);
        const phone2 = cleanPhoneNumber(tutorInfo.telefone2);

        if (phone1) {
          const whatsappUrl1 = 'https://wa.me/55' + phone1 + '?text=' + encodeURIComponent(message);
          sheet.getRange(i + 1, colWhatsApp1).setFormula('=HYPERLINK("' + whatsappUrl1 + '", "WhatsApp 1")');
        }

        if (phone2) {
          const whatsappUrl2 = 'https://wa.me/55' + phone2 + '?text=' + encodeURIComponent(message);
          sheet.getRange(i + 1, colWhatsApp2).setFormula('=HYPERLINK("' + whatsappUrl2 + '", "WhatsApp 2")');
        }

        linksAdicionados++;
      }
    }

    SpreadsheetApp.getUi().alert('Links do WhatsApp adicionados com sucesso!\n\n' +
                                'Total de linhas processadas: ' + linksAdicionados + '\n' +
                                'Agora você pode clicar diretamente nos links na planilha para enviar as mensagens.');

  } catch (error) {
    console.error('Erro detalhado:', error);
    SpreadsheetApp.getUi().alert('Erro: ' + error.toString());
  }
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
    horario = '14h30 às 17h00';
  }

  let dataFormatada = tutorInfo.data;
  let dayOfWeek = 'Data a confirmar';

  if (tutorInfo.data && tutorInfo.data.toString().trim() !== '') {
    try {
      const dataStr = tutorInfo.data.toString().trim();
      const dateMatch = dataStr.match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
      if (dateMatch) {
        const dia = parseInt(dateMatch[1], 10);
        const mes = parseInt(dateMatch[2], 10);
        const ano = parseInt(dateMatch[3], 10);

        const dateObj = new Date(ano, mes - 1, dia);

        if (!isNaN(dateObj.getTime())) {
          const daysOfWeek = ['Domingo', 'Segunda-Feira', 'Terça-Feira', 'Quarta-Feira', 'Quinta-Feira', 'Sexta-Feira', 'Sábado'];
          dayOfWeek = daysOfWeek[dateObj.getDay()];
          dataFormatada = ('0' + dia).slice(-2) + '/' + ('0' + mes).slice(-2) + '/' + ano;
        }
      } else {
        dataFormatada = dataStr;
      }
    } catch (error) {
      dataFormatada = tutorInfo.data.toString();
    }
  }

  return 'Olá!\n' +
'Aqui é do setor de Controle de Vetores. Estamos organizando a Vacinação Contra a Raiva Animal 2026 e identificamos um cadastro em seu nome.\n\n' +
'Gostaríamos de confirmar algumas informações para que possamos vacinar seu animal com segurança:\n\n' +
'Data sugerida para a vacinação: ' + dataFormatada + ' (' + dayOfWeek + ')\n' +
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
