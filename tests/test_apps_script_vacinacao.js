/**
 * Comportamento real do Apps Script da planilha de vacinação.
 *
 * O script roda dentro do Google Sheets, então aqui ele é carregado num
 * contexto com stubs de SpreadsheetApp. O que estes testes fixam é o que
 * quebrou em produção: leitura das colunas na aba que tem carimbo de
 * data/hora, e reordenação levando nota, cor e fórmula junto com a linha.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const SCRIPT = path.join(__dirname, '..', 'scripts', 'apps_script', 'vacinacao_2026.gs');

function carregar(stubs) {
  const ctx = Object.assign({
    console: { log: () => {}, error: () => {} },
    Logger: { log: () => {} },
    SpreadsheetApp: {},
    PropertiesService: {},
    UrlFetchApp: {},
  }, stubs || {});
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(SCRIPT, 'utf8'), ctx);
  return ctx;
}

const CABECALHO_MESTRE = [
  'Carimbo de data/hora', 'Nome completo', 'Endereço', 'Número', 'Complemento',
  'Bairro', 'Telefone', 'Telefone 2', 'Cães', 'Gatos', 'Animais', 'Obs',
  'Status PMO', 'WhatsApp 1'
];

const LINHA_RAQUEL = [
  '17/08/2026 14:42:13', 'Raquel Feliciano', 'Rua 4', '1299', 'A',
  'Jardim Siena', '16992510438', '16991443152', '1', '0', 'Pipoca', '',
  'Vacinado', 'WhatsApp 1'
];

const LINHA_IRANEIDE = [
  '16/08/2026 09:00:00', 'Iraneide Maria de Sousa', 'Rua A', '3', '',
  'Centro', '16992565982', '16981812250', '3', '0', 'Ted', '', 'Pendente',
  'WhatsApp 1'
];

const testes = [];
function teste(nome, fn) { testes.push([nome, fn]); }

// --------------------------------------------------------------------------
// Offset da coluna de carimbo
// --------------------------------------------------------------------------
teste('aba do formulário: nome do tutor está na coluna B', () => {
  const ctx = carregar();
  const dados = [CABECALHO_MESTRE, LINHA_RAQUEL, LINHA_IRANEIDE];
  assert.strictEqual(ctx.detectarOffset_(dados), 1);

  const col = ctx.colunas_(1);
  assert.strictEqual(LINHA_RAQUEL[col.tutor], 'Raquel Feliciano');
  assert.strictEqual(LINHA_RAQUEL[col.endereco], 'Rua 4');
  assert.strictEqual(LINHA_RAQUEL[col.bairro], 'Jardim Siena');
  assert.strictEqual(LINHA_RAQUEL[col.telefone1], '16992510438');
  assert.strictEqual(LINHA_RAQUEL[col.animais], 'Pipoca');
});

teste('aba do dia digitada à mão: nome do tutor está na coluna A', () => {
  const ctx = carregar();
  const dados = [
    ['Nome completo', 'Endereço', 'Número', 'Complemento', 'Bairro', 'Telefone', 'Telefone 2'],
    ['Iraneide Maria de Sousa', 'Rua A', '3', 'Vila comove', 'Vila comovel', '16992565982', '16981812250'],
  ];
  assert.strictEqual(ctx.detectarOffset_(dados), 0);

  const col = ctx.colunas_(0);
  assert.strictEqual(dados[1][col.tutor], 'Iraneide Maria de Sousa');
  assert.strictEqual(dados[1][col.telefone1], '16992565982');
});

teste('uma data solta no meio dos dados não muda o layout da aba', () => {
  const ctx = carregar();
  const dados = [
    ['Nome completo', 'Endereço', 'Número'],
    ['Ana Souza', 'Rua 7', '100'],
    ['12/08/2026', 'Rua 9', '200'],   // alguém digitou a data no lugar do nome
    ['Bruno Lima', 'Rua 11', '300'],
  ];
  assert.strictEqual(ctx.detectarOffset_(dados), 0);
});

// --------------------------------------------------------------------------
// Mensagem de WhatsApp
// --------------------------------------------------------------------------
teste('mensagem leva endereço e nome do tutor corretos', () => {
  const ctx = carregar();
  const col = ctx.colunas_(1);
  const msg = ctx.generateMessage({
    nome: LINHA_RAQUEL[col.tutor],
    endereco: LINHA_RAQUEL[col.endereco],
    numero: LINHA_RAQUEL[col.numero],
    complemento: LINHA_RAQUEL[col.complemento],
    bairro: LINHA_RAQUEL[col.bairro],
    quantCaes: LINHA_RAQUEL[col.caes],
    quantGatos: LINHA_RAQUEL[col.gatos],
    data: '25/09/2026',
    turno: 'Manhã',
  });

  assert.ok(msg.indexOf('REQUISITANTE: Raquel Feliciano') !== -1, 'nome do tutor');
  assert.ok(msg.indexOf('Endereço: Rua 4, 1299 - A - Jardim Siena') !== -1, 'endereço montado');
  assert.ok(msg.indexOf('Quantidade de animais: 1') !== -1, 'quantidade de animais');
  assert.ok(msg.indexOf('8h30 às 11h30') !== -1, 'horário da manhã');
});

// --------------------------------------------------------------------------
// Reordenação por cluster
// --------------------------------------------------------------------------
function planilhaFalsa(values, formulas, notes, backgrounds) {
  const gravado = { values: null, notes: null, backgrounds: null, header: null };
  const sheet = {
    getDataRange: () => ({
      getValues: () => values.map(r => r.slice()),
      getFormulas: () => formulas.map(r => r.slice()),
      getNotes: () => notes.map(r => r.slice()),
      getBackgrounds: () => backgrounds.map(r => r.slice()),
    }),
    getMaxColumns: () => values[0].length + 5,
    insertColumnsAfter: () => {},
    getRange: (row) => ({
      setValues: (v) => { if (row === 1) gravado.header = v[0]; else gravado.values = v; },
      setNotes: (n) => { gravado.notes = n; },
      setBackgrounds: (b) => { gravado.backgrounds = b; },
    }),
    getConditionalFormatRules: () => [],
    setConditionalFormatRules: () => {},
  };
  const stubs = {
    SpreadsheetApp: {
      getActiveSpreadsheet: () => ({ getActiveSheet: () => sheet }),
      getActive: () => ({ toast: () => {} }),
      getUi: () => ({ alert: () => {}, ButtonSet: { OK: 'OK' } }),
      newConditionalFormatRule: () => {
        const b = {
          whenTextEqualTo: () => b, setBackground: () => b,
          setRanges: () => b, build: () => ({}),
        };
        return b;
      },
    },
  };
  return { gravado, stubs };
}

function cenarioMestre() {
  const values = [CABECALHO_MESTRE.slice(), LINHA_RAQUEL.slice(), LINHA_IRANEIDE.slice()];
  const vazio = () => CABECALHO_MESTRE.map(() => '');
  const formulas = [vazio(), vazio(), vazio()];
  formulas[1][13] = '=HYPERLINK("https://wa.me/5516992510438","WhatsApp 1")';
  formulas[2][13] = '=HYPERLINK("https://wa.me/5516992565982","WhatsApp 1")';
  const notes = [vazio(), vazio(), vazio()];
  notes[1][0] = 'PetOrlandia PMO\nTutor: Raquel Feliciano';
  notes[2][0] = 'PetOrlandia PMO\nTutor: Iraneide Maria de Sousa';
  const backgrounds = [
    CABECALHO_MESTRE.map(() => '#ffffff'),
    CABECALHO_MESTRE.map(() => '#ffffff'),
    CABECALHO_MESTRE.map(() => '#ffffff'),
  ];
  backgrounds[1][0] = '#00ff00';   // verde de "vacinado" na linha da Raquel
  return planilhaFalsa(values, formulas, notes, backgrounds);
}

teste('reordenar leva nota, cor e fórmula junto com a linha', () => {
  const { gravado, stubs } = cenarioMestre();
  carregar(stubs).routeOptimizeByCluster();

  assert.strictEqual(gravado.values.length, 2, 'nenhuma linha some na otimização');

  // Arrays criados dentro do contexto do vm têm outro prototype: comparar
  // o texto evita um falso negativo de deepStrictEqual.
  const tutores = Array.from(gravado.values).map(l => l[1]);
  // Centro (C) vem antes de Jardim Siena (E): a ordem muda de verdade.
  assert.strictEqual(tutores.join(' | '), 'Iraneide Maria de Sousa | Raquel Feliciano');

  const donoDaNota = Array.from(gravado.notes).map(n => (n[0].match(/Tutor: (.+)/) || [])[1]);
  assert.strictEqual(donoDaNota.join(' | '), tutores.join(' | '), 'a nota tem que seguir o tutor');

  const linhaRaquel = tutores.indexOf('Raquel Feliciano');
  assert.strictEqual(gravado.backgrounds[linhaRaquel][0], '#00ff00', 'a cor segue o tutor');

  Array.from(gravado.values).forEach(linha => {
    assert.ok(String(linha[13]).indexOf('=HYPERLINK') === 0, 'link de WhatsApp continua fórmula');
  });
  assert.ok(
    gravado.values[linhaRaquel][13].indexOf('5516992510438') !== -1,
    'o link segue o telefone do tutor'
  );
});

teste('rodar duas vezes não duplica as colunas auxiliares', () => {
  const primeiro = cenarioMestre();
  carregar(primeiro.stubs).routeOptimizeByCluster();
  const headerUm = primeiro.gravado.header;

  const values = [Array.from(headerUm)].concat(Array.from(primeiro.gravado.values).map(r => Array.from(r)));
  const vazio = () => Array.from(headerUm).map(() => '');
  const segundo = planilhaFalsa(
    values,
    [vazio(), vazio(), vazio()],
    [vazio(), vazio(), vazio()],
    [vazio().map(() => '#ffffff'), vazio().map(() => '#ffffff'), vazio().map(() => '#ffffff')]
  );
  carregar(segundo.stubs).routeOptimizeByCluster();

  assert.strictEqual(segundo.gravado.header.length, headerUm.length, 'colunas não crescem a cada execução');
  assert.strictEqual(Array.from(headerUm).filter(c => c === 'Cluster').length, 1);
  assert.strictEqual(Array.from(segundo.gravado.header).filter(c => c === 'Cluster').length, 1);
});

teste('linha sem bairro reconhecido vai para o fim, nunca é descartada', () => {
  const values = [
    CABECALHO_MESTRE.slice(),
    ['17/08/2026 10:00:00', 'Zulmira Alves', 'Rua X', '5', '', 'Bairro Inexistente', '16990000001', '', '1', '0', 'Rex', '', '', ''],
    LINHA_RAQUEL.slice(),
  ];
  const vazio = () => CABECALHO_MESTRE.map(() => '');
  const { gravado, stubs } = planilhaFalsa(
    values,
    [vazio(), vazio(), vazio()],
    [vazio(), vazio(), vazio()],
    [CABECALHO_MESTRE.map(() => '#ffffff'), CABECALHO_MESTRE.map(() => '#ffffff'), CABECALHO_MESTRE.map(() => '#ffffff')]
  );
  carregar(stubs).routeOptimizeByCluster();

  const tutores = Array.from(gravado.values).map(l => l[1]);
  assert.strictEqual(tutores.length, 2, 'a linha não classificada continua na planilha');
  assert.strictEqual(tutores[tutores.length - 1], 'Zulmira Alves', 'não classificada vai para o fim');
});

// --------------------------------------------------------------------------
let falhas = 0;
testes.forEach(([nome, fn]) => {
  try {
    fn();
    console.log('ok   - ' + nome);
  } catch (erro) {
    falhas++;
    console.log('FALHA- ' + nome);
    console.log('       ' + (erro && erro.message ? erro.message : erro));
  }
});
console.log('\n' + (testes.length - falhas) + '/' + testes.length + ' testes passaram');
process.exit(falhas === 0 ? 0 : 1);
