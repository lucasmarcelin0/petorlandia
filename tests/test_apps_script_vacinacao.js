/**
 * Comportamento real do Apps Script da planilha de vacinação.
 *
 * O script roda dentro do Google Sheets, então aqui ele é carregado num
 * contexto com stubs de SpreadsheetApp. O que estes testes fixam é o que
 * quebrou em produção: leitura das colunas na aba que tem carimbo de
 * data/hora, reordenação levando nota, cor e fórmula junto com a linha, e
 * links e datas que não dependem da localidade da planilha.
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
// Planilha em memória: cada célula guarda valor, fórmula, nota e cor, e a
// ordenação move a linha inteira, como o sort nativo do Sheets.
function gradeFalsa(values, extras) {
  const grade = values.map((linha, i) => linha.map((v, j) => Object.assign(
    { v: v, f: '', n: '', bg: '#ffffff' },
    (extras && extras[i] && extras[i][j]) || {}
  )));
  const largura = () => grade[0].length;
  const faixa = (r, c, nr, nc) => ({
    setValues: (vals) => {
      for (let i = 0; i < nr; i++) for (let j = 0; j < nc; j++) {
        while (grade[r - 1 + i].length < c + j) grade[r - 1 + i].push({ v: '', f: '', n: '', bg: '#ffffff' });
        grade[r - 1 + i][c - 1 + j].v = vals[i][j];
        grade[r - 1 + i][c - 1 + j].f = '';
      }
    },
    sort: (spec) => {
      const linhas = grade.slice(r - 1, r - 1 + nr);
      linhas.sort((a, b) => (a[spec.column - 1].v - b[spec.column - 1].v) * (spec.ascending === false ? -1 : 1));
      grade.splice(r - 1, nr, ...linhas);
    },
    setWrapStrategy: () => {}, setBackground: () => {},
  });
  const sheet = {
    getDataRange: () => ({ getValues: () => grade.map(l => l.map(c => c.v)) }),
    getMaxColumns: () => largura(),
    insertColumnsAfter: (_c, n) => grade.forEach(l => { for (let k = 0; k < n; k++) l.push({ v: '', f: '', n: '', bg: '#ffffff' }); }),
    insertColumnAfter: (c) => grade.forEach(l => l.splice(c, 0, { v: '', f: '', n: '', bg: '#ffffff' })),
    deleteColumn: (c) => grade.forEach(l => l.splice(c - 1, 1)),
    getRange: (r, c, nr, nc) => faixa(r, c, nr || 1, nc || 1),
    setRowHeightsForced: () => {},
    getConditionalFormatRules: () => [],
    setConditionalFormatRules: () => {},
    getSheetId: () => 1,
  };
  const stubs = {
    LockService: { getDocumentLock: () => ({ tryLock: () => true, releaseLock: () => {}, hasLock: () => false }) },
    SpreadsheetApp: {
      getActiveSpreadsheet: () => ({ getActiveSheet: () => sheet }),
      getActive: () => ({ toast: () => {} }),
      getUi: () => ({ alert: () => {}, ButtonSet: { OK: 'OK' } }),
      flush: () => {},
      WrapStrategy: { CLIP: 'CLIP' },
      BooleanCriteria: { TEXT_EQUAL_TO: 'TEXT_EQUAL_TO' },
      newConditionalFormatRule: () => {
        const b = {
          whenTextEqualTo: () => b, setBackground: () => b,
          setRanges: () => b, build: () => ({}),
        };
        return b;
      },
    },
  };
  return { grade, stubs };
}

function cenarioMestre() {
  const values = [CABECALHO_MESTRE.slice(), LINHA_RAQUEL.slice(), LINHA_IRANEIDE.slice()];
  const extras = [[], [], []];
  extras[1][0] = { n: 'PetOrlandia PMO\nTutor: Raquel Feliciano', bg: '#00ff00' };
  extras[2][0] = { n: 'PetOrlandia PMO\nTutor: Iraneide Maria de Sousa' };
  extras[1][13] = { f: '=HYPERLINK("https://wa.me/5516992510438";"WhatsApp 1")' };
  extras[2][13] = { f: '=HYPERLINK("https://wa.me/5516992565982";"WhatsApp 1")' };
  return gradeFalsa(values, extras);
}

teste('reordenar leva nota, cor e fórmula junto com a linha', () => {
  const { grade, stubs } = cenarioMestre();
  carregar(stubs).routeOptimizeByCluster();

  const linhas = grade.slice(1);
  assert.strictEqual(linhas.length, 2, 'nenhuma linha some na otimização');
  const tutores = linhas.map(l => l[1].v);
  // Centro (C1) vem antes de Jardim Siena (E2): a ordem muda de verdade.
  assert.strictEqual(tutores.join(' | '), 'Iraneide Maria de Sousa | Raquel Feliciano');

  linhas.forEach(l => {
    assert.strictEqual((l[0].n.match(/Tutor: (.+)/) || [])[1], l[1].v, 'a nota tem que seguir o tutor');
  });
  const raquel = linhas[tutores.indexOf('Raquel Feliciano')];
  assert.strictEqual(raquel[0].bg, '#00ff00', 'a cor segue o tutor');
  assert.ok(raquel[13].f.indexOf('5516992510438') !== -1, 'o link segue o telefone do tutor');
  assert.strictEqual(grade[0].length, CABECALHO_MESTRE.length + 2, 'a coluna temporária da ordem é apagada');
});

teste('rodar duas vezes não duplica as colunas auxiliares', () => {
  const { grade, stubs } = cenarioMestre();
  carregar(stubs).routeOptimizeByCluster();
  const largura = grade[0].length;
  carregar(stubs).routeOptimizeByCluster();

  assert.strictEqual(grade[0].length, largura, 'colunas não crescem a cada execução');
  assert.strictEqual(grade[0].filter(c => c.v === 'Cluster').length, 1);
});

teste('linha sem bairro reconhecido vai para o fim, nunca é descartada', () => {
  const { grade, stubs } = gradeFalsa([
    CABECALHO_MESTRE.slice(),
    ['17/08/2026 10:00:00', 'Zulmira Alves', 'Rua X', '5', '', 'Bairro Inexistente', '16990000001', '', '1', '0', 'Rex', '', '', ''],
    LINHA_RAQUEL.slice(),
  ]);
  carregar(stubs).routeOptimizeByCluster();

  const tutores = grade.slice(1).map(l => l[1].v);
  assert.strictEqual(tutores.length, 2, 'a linha não classificada continua na planilha');
  assert.strictEqual(tutores[tutores.length - 1], 'Zulmira Alves', 'não classificada vai para o fim');
});

// --------------------------------------------------------------------------
// Links de WhatsApp e datas: nada pode depender da localidade da planilha
// --------------------------------------------------------------------------
// Em pt_BR o separador de fórmula é ";": setFormula('=HYPERLINK("…", "…")')
// gravou #ERROR! em todos os links da aba 05/11/2026.
// Fórmula só pode ser regravada a partir do texto lido da própria planilha
// (getFormulas), que já vem no separador dela; nunca escrita à mão no código.
teste('o script não grava fórmula escrita no código: o separador muda com a localidade', () => {
  const codigo = fs.readFileSync(SCRIPT, 'utf8')
    .split('\n')
    .filter(l => !/^\s*(\/\/|\*)/.test(l))
    .join('\n');
  const literal = /\.setFormulas?(R1C1)?\(\s*(\[\s*)*(['"`]|[A-Za-z_$][\w$]*\s*\+\s*['"`]|['"`][^'"`]*['"`]\s*\+)/;
  assert.ok(!literal.test(codigo), 'use texto com link (setRichTextValue) ou fórmula lida com getFormulas');
  assert.ok(!/=HYPERLINK\(/i.test(codigo.replace(/\/\*[\s\S]*?\*\//g, '')), 'sem HYPERLINK montado no código');
});

const UTILITIES_FALSO = {
  // Os testes criam as datas em UTC; o fuso não importa aqui.
  formatDate: (d, _fuso, formato) => {
    const p = (n) => ('0' + n).slice(-2);
    return formato
      .replace('dd', p(d.getUTCDate())).replace('MM', p(d.getUTCMonth() + 1))
      .replace('yyyy', d.getUTCFullYear()).replace('HH', p(d.getUTCHours())).replace('mm', p(d.getUTCMinutes()));
  },
  parseDate: (texto) => {
    const m = texto.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    return new Date(Date.UTC(+m[3], +m[2] - 1, +m[1]));
  },
};

teste('mensagem: data vem do valor da célula, com o dia da semana certo', () => {
  const ctx = carregar({ Utilities: UTILITIES_FALSO });
  const base = { nome: 'Ana', endereco: 'Rua 1', numero: '10', turno: 'Tarde' };
  const comDate = ctx.generateMessage(Object.assign({ data: new Date(Date.UTC(2026, 10, 5)) }, base));
  assert.ok(comDate.indexOf('vacinação: 05/11/2026 (Quinta-Feira)') !== -1, comDate.split('\n')[4]);
  const comTexto = ctx.generateMessage(Object.assign({ data: '4/11/2026' }, base));
  assert.ok(comTexto.indexOf('vacinação: 04/11/2026 (Quarta-Feira)') !== -1, comTexto.split('\n')[4]);
  const semData = ctx.generateMessage(Object.assign({ data: 'Data a definir' }, base));
  assert.ok(semData.indexOf('vacinação: a confirmar\n') !== -1, semData.split('\n')[4]);
});

const CABECALHO_DIA = [
  'Nome completo do tutor', 'Endereço', 'Número', 'Complemento', 'Bairro', 'Telefone',
  'Telefone 2', 'Cães', 'Gatos', 'Animais', 'Obs', 'Data Vacina', 'Cães vac', 'Gatos vac',
  'Nome', '', 'Data', 'Turno', 'WhatsApp 1', 'WhatsApp 2'
];

function linhaDia(nome, tel1, tel2, data, turno) {
  const l = CABECALHO_DIA.map(() => '');
  l[0] = nome; l[1] = 'Rua 24'; l[2] = '1613'; l[4] = 'Vilinha';
  l[5] = tel1; l[6] = tel2; l[7] = 1; l[8] = 0; l[16] = data; l[17] = turno;
  return l;
}

// Aba do dia em memória. A célula de link guarda o que foi gravado nela:
// { rich: url } ou { formula: texto }.
function abaDoDia(nome, linhas, celulasIniciais) {
  const values = [CABECALHO_DIA.slice()].concat(linhas);
  const celulas = Object.assign({}, celulasIniciais || {});
  const alertas = [];
  const chave = (r, c) => r + ':' + c;
  const sheet = {
    getName: () => nome,
    getParent: () => ({ getSpreadsheetTimeZone: () => 'America/Sao_Paulo' }),
    getDataRange: () => ({ getValues: () => values.map(l => l.slice()) }),
    getRange: (r, c, nr) => ({
      setValue: () => {},
      setRichTextValue: (rt) => { celulas[chave(r, c)] = { rich: rt.url, texto: rt.texto }; },
      clearContent: () => { delete celulas[chave(r, c)]; },
      setFormula: (f) => { celulas[chave(r, c)] = { formula: f }; },
      getFormulas: () => Array.from({ length: nr }, (_, i) => [(celulas[chave(r + i, c)] || {}).formula || '']),
      getRichTextValues: () => Array.from({ length: nr }, (_, i) => {
        const cel = celulas[chave(r + i, c)] || {};
        return [{ getLinkUrl: () => cel.rich || null }];
      }),
    }),
  };
  const ui = { alert: (...a) => alertas.push(a.join(' ')), ButtonSet: { OK: 'OK' } };
  const stubs = {
    Utilities: UTILITIES_FALSO,
    SpreadsheetApp: {
      getActiveSpreadsheet: () => ({ getActiveSheet: () => sheet, getSpreadsheetTimeZone: () => 'America/Sao_Paulo' }),
      getUi: () => ui,
      newRichTextValue: () => {
        const rt = {};
        const b = { setText: (t) => { rt.texto = t; return b; }, setLinkUrl: (u) => { rt.url = u; return b; }, build: () => rt };
        return b;
      },
    },
  };
  return { celulas, alertas, stubs };
}

const DIA_05_11 = new Date(Date.UTC(2026, 10, 5));

teste('links: gravados como texto com link, com a data e o dia da semana da aba', () => {
  const { celulas, alertas, stubs } = abaDoDia('05/11/2026', [
    linhaDia('Gabriel Fernando', '16 99327-0368', '16 99192-9756', DIA_05_11, 'Manhã'),
    linhaDia('Elisangela Casali', '16 99435-3702', 'o mesmo', DIA_05_11, 'Tarde'),
  ]);
  carregar(stubs).addWhatsAppLinks();

  assert.ok(alertas.some(a => /adicionados com sucesso/.test(a)), alertas.join('|'));
  assert.ok(Object.values(celulas).every(c => !c.formula), 'nenhuma fórmula gravada');
  const l1 = celulas['2:19'];
  assert.strictEqual(l1.texto, 'WhatsApp 1');
  assert.ok(l1.rich.indexOf('https://wa.me/5516993270368?text=') === 0, l1.rich.slice(0, 40));
  const msg = decodeURIComponent(l1.rich.split('?text=')[1]);
  assert.ok(msg.indexOf('vacinação: 05/11/2026 (Quinta-Feira)') !== -1, msg.split('\n')[4]);
  assert.ok(decodeURIComponent(celulas['3:19'].rich).indexOf('14h30') !== -1, 'turno da tarde');
  assert.ok(!celulas['3:20'], '"o mesmo" não vira link');
});

teste('links: substituem o #ERROR! antigo e limpam o link que sobrou sem telefone', () => {
  const quebrado = { formula: '=HYPERLINK("https://wa.me/5516993270368?text=oi", "WhatsApp 1")' };
  const { celulas, stubs } = abaDoDia('05/11/2026', [
    linhaDia('Gabriel Fernando', '16 99327-0368', '', DIA_05_11, 'Manhã'),
    linhaDia('', '', '', DIA_05_11, 'Manhã'),
  ], { '2:19': quebrado, '2:20': quebrado, '3:19': { rich: 'https://wa.me/551699999999?text=x' } });
  carregar(stubs).addWhatsAppLinks();

  assert.ok(celulas['2:19'].rich, 'o link quebrado vira link de verdade');
  assert.ok(!celulas['2:20'], 'telefone 2 apagado: o link antigo sai');
  assert.ok(!celulas['3:19'], 'linha vazia: o link antigo sai');
});

teste('links: cópia do Padrão ainda sem nome de data não gera nada', () => {
  const { celulas, alertas, stubs } = abaDoDia('Cópia de Padrão', [
    linhaDia('Gabriel Fernando', '16 99327-0368', '', 'Data a definir', 'Manhã'),
  ]);
  carregar(stubs).addWhatsAppLinks();
  assert.strictEqual(Object.keys(celulas).length, 0);
  assert.ok(alertas.some(a => /DD\/MM\/AAAA/.test(a)), alertas.join('|'));
});

teste('links: data da linha diferente do nome da aba não gera nada', () => {
  const { celulas, alertas, stubs } = abaDoDia('05/11/2026', [
    linhaDia('Gabriel Fernando', '16 99327-0368', '', DIA_05_11, 'Manhã'),
    linhaDia('Luana Alves', '16994343674', '', new Date(Date.UTC(2026, 4, 11)), 'Manhã'),
  ]);
  carregar(stubs).addWhatsAppLinks();
  assert.strictEqual(Object.keys(celulas).length, 0, 'nenhum link alterado');
  assert.ok(alertas.some(a => /linha 3 \(Luana Alves\): 11\/05\/2026/.test(a)), alertas.join('|'));
});

teste('datas invertidas: só a data do nome da aba é corrigida, no valor e no formato', () => {
  const US = 'M/d/yyyy';
  const BR = 'dd/mm/yyyy';
  const nascidas = {
    '10/09/2026': [
      [new Date(Date.UTC(2026, 9, 10)), '', US],          // Q1 10/10: outra data, fica
      [new Date(Date.UTC(2026, 9, 9)), '', US],           // Q2 09/10: a troca de 10/09, corrige tudo
      [new Date(Date.UTC(2026, 9, 9)), '=$Q$2', US],      // Q3 fórmula: só o formato
      ['09/10/2026', '', ''],                             // Q4 texto: fica
      [new Date(Date.UTC(2026, 8, 10)), '', BR],          // Q5 já certa: fica
    ],
    // Dia > 12: não há troca possível, mas o formato mês/dia mostrava 10/22/2026.
    '22/10/2026': [[new Date(Date.UTC(2026, 9, 22)), '', 'mm/dd/yyyy']],
    'Agendadas': [[new Date(Date.UTC(2026, 9, 9)), '', US]],   // não é aba de dia
  };
  const gravadas = {};
  const sheets = Object.keys(nascidas).map(nome => ({
    getName: () => nome,
    getDataRange: () => ({
      getValues: () => nascidas[nome].map(c => [c[0]]),
      getFormulas: () => nascidas[nome].map(c => [c[1]]),
      getNumberFormats: () => nascidas[nome].map(c => [c[2]]),
      getCell: (r, c) => ({ getA1Notation: () => 'Q' + r + (c === 1 ? '' : '?') }),
    }),
    getRangeList: (a1s) => ({
      setValue: (v) => { gravadas[nome] = Object.assign(gravadas[nome] || {}, { valor: a1s.join(','), data: v }); },
      setNumberFormat: (f) => { gravadas[nome] = Object.assign(gravadas[nome] || {}, { formato: a1s.join(',') + ' ' + f }); },
    }),
  }));
  const ctx = carregar({
    Utilities: UTILITIES_FALSO,
    SpreadsheetApp: {
      getActiveSpreadsheet: () => ({ getSheets: () => sheets, getSpreadsheetTimeZone: () => 'America/Sao_Paulo' }),
      getUi: () => { throw new Error('sem interface no editor'); },
    },
  });
  const corrigidas = ctx.corrigirDatasInvertidas();

  assert.strictEqual(Object.keys(gravadas).join(','), '10/09/2026,22/10/2026');
  assert.strictEqual(gravadas['10/09/2026'].valor, 'Q2');
  assert.strictEqual(gravadas['10/09/2026'].data.toISOString().slice(0, 10), '2026-09-10');
  assert.strictEqual(gravadas['10/09/2026'].formato, 'Q2,Q3 dd/mm/yyyy');
  assert.strictEqual(gravadas['22/10/2026'].valor, undefined, 'data certa não é regravada');
  assert.strictEqual(gravadas['22/10/2026'].formato, 'Q1 dd/mm/yyyy');
  assert.strictEqual(corrigidas.length, 2);
});

// --------------------------------------------------------------------------
// Controle de doses: o mês novo nasce ligado às abas do dia
// --------------------------------------------------------------------------
// Fórmulas do bloco de Novembro como a planilha (pt_BR) devolve em getFormulas().
const NOV = {
  caes: '=IFERROR(SUMIF(INDIRECT("\'"&B$30&"\'!A2:A");"<>";INDIRECT("\'"&B$30&"\'!M2:M"));"")',
  gatos: '=IFERROR(SUMIF(INDIRECT("\'"&B$30&"\'!A2:A");"<>";INDIRECT("\'"&B$30&"\'!N2:N"));"")',
  perdas: '=IFERROR(IF(SUMPRODUCT((INDIRECT("\'"&B$30&"\'!M2:M")="Perdas")*ISNUMBER(INDIRECT("\'"&B$30&"\'!N2:N")))<2;"";SUMIF(INDIRECT("\'"&B$30&"\'!M2:M");"Perdas";INDIRECT("\'"&B$30&"\'!N2:N")));"")',
  doses: '=IF(COUNT(B31:B33)=0;"";SUM(B31:B33))',
  conf: '=IF(B31="";"";IF(DATE(VALUE(RIGHT(B$30;4));VALUE(MID(B$30;4;2));VALUE(LEFT(B$30;2)))>TODAY();"Programado";IF(B33="";"Perdas pendentes";"Conferido")))',
  estoque: '=$B$28+SUM($B$29)-$AC$34',
};

function controleFalso() {
  const linhas = 61;
  const cols = 40;
  const v = Array.from({ length: linhas }, () => Array(cols).fill(''));
  const f = Array.from({ length: linhas }, () => Array(cols).fill(''));
  const pos = (a1) => { const m = a1.match(/^([A-Z]+)(\d+)$/); let c = 0; for (const ch of m[1]) c = c * 26 + ch.charCodeAt(0) - 64; return [Number(m[2]) - 1, c - 1]; };
  const put = (a1, valor, formula) => { const [i, j] = pos(a1); v[i][j] = valor; f[i][j] = formula || ''; };
  put('A26', 'Novembro'); put('A28', 'Estoque:'); put('B28', '100'); put('A29', 'Recebida no mês:');
  put('A30', 'Dia');
  ['A31', 'A32', 'A33', 'A34', 'A35', 'A36'].forEach((a, k) => put(a, ['Cachorros:', 'Gatos:', 'Perdas:', 'Doses utilizadas:', 'Conferência:', 'Estoque ao final do mês:'][k]));
  for (let d = 4; d <= 30; d++) {
    const c = d - 3;  // 04/11 na coluna B (índice 1)
    v[29][c] = ('0' + d).slice(-2) + '/11/2026';
    f[30][c] = NOV.caes.replace(/B\$30/g, () => String.fromCharCode(65 + c) + '$30');
  }
  // Só o necessário das outras colunas: o modelo usado é a coluna B e a do Total.
  v[29][28] = 'Total';
  f[30][1] = NOV.caes; f[31][1] = NOV.gatos; f[32][1] = NOV.perdas; f[33][1] = NOV.doses; f[34][1] = NOV.conf;
  f[30][28] = '=SUM(B31:AB31)'; f[31][28] = '=SUM(B32:AB32)'; f[32][28] = '=IF(COUNT(B33:AB33)=0;"";SUM(B33:AB33))';
  f[33][28] = '=SUM(B34:AB34)'; f[34][28] = '=IF(COUNTIF(B35:AB35;"Perdas pendentes")>0;"Perdas pendentes";"Conferido")';
  f[35][1] = NOV.estoque;
  put('A38', 'Dezembro'); put('A40', 'Estoque:'); put('C40', 'Lote:'); put('A41', 'Recebida no mês:'); put('C41', 'Lote:');
  put('A43', 'Doses utilizadas:'); put('A44', 'Cachorros:'); put('A45', 'Gatos:'); put('A46', 'Perdas:'); put('A48', 'Estoque ao final do mês:');
  put('A61', 'Janeiro');

  const formatos = [];
  let maxColunas = 30;  // a aba real terminava antes da coluna AG
  const sheet = {
    getMaxColumns: () => maxColunas,
    insertColumnsAfter: (_c, n) => { maxColunas += n; },
    getDataRange: () => ({
      getDisplayValues: () => v.map(l => l.map(String)),
      getFormulas: () => f.map(l => l.slice()),
      getCell: (r, c) => ({ getA1Notation: () => String.fromCharCode(64 + c) + r }),
    }),
    getRange: (r, c, nr, nc) => {
      const rg = {
        setValues: (m) => {
          escritas.push(r + ':' + c);
          m.forEach((l, i) => l.forEach((x, j) => { v[r - 1 + i][c - 1 + j] = x; f[r - 1 + i][c - 1 + j] = ''; }));
          return rg;
        },
        setFormulas: (m) => m.forEach((l, i) => l.forEach((x, j) => { f[r - 1 + i][c - 1 + j] = x; v[r - 1 + i][c - 1 + j] = x ? '(calculado)' : ''; })),
        setNumberFormat: () => rg,
        copyFormatToRange: (_s, c1, c2, r1, r2) => {
          if (c1 > maxColunas) throw new Error('As coordenadas do intervalo de destino estão fora das dimensões da página.');
          formatos.push([c, c1, r1, r2]);
        },
      };
      return rg;
    },
  };
  const escritas = [];
  return { sheet, v, f, pos, formatos, escritas };
}

teste('controle: fórmula movida troca linha e coluna, nunca o texto entre aspas', () => {
  const ctx = carregar();
  assert.strictEqual(ctx.moverFormula_(NOV.caes, 12, { B: 'AF' }),
    '=IFERROR(SUMIF(INDIRECT("\'"&AF$42&"\'!A2:A");"<>";INDIRECT("\'"&AF$42&"\'!M2:M"));"")');
  assert.strictEqual(ctx.moverFormula_(NOV.estoque, 12, { AC: 'AG' }), '=$B$40+SUM($B$41)-$AG$46');
  assert.strictEqual(ctx.moverFormula_('=SUM(B31:AB31)', 12, { AB: 'AF' }), '=SUM(B43:AF43)');
  assert.strictEqual(ctx.letraDaColuna_(33), 'AG');
});

teste('controle: Dezembro é montado com 31 dias ligados às abas, uma vez só', () => {
  const { sheet, v, f, pos, formatos } = controleFalso();
  const ctx = carregar();
  const feitos = Array.from(ctx.montarMesesNoControleDeDoses_(sheet));
  assert.strictEqual(feitos.join('|'), 'Dezembro: 31 dias ligados às abas (linha 42)');

  const em = (a1) => { const [i, j] = pos(a1); return { v: v[i][j], f: f[i][j] }; };
  assert.strictEqual(em('A42').v, 'Dia');
  assert.strictEqual(em('A43').v, 'Cachorros:', 'rótulos na ordem do modelo');
  assert.strictEqual(em('A48').v, 'Estoque ao final do mês:');
  assert.strictEqual(em('B42').v, '01/12/2026');
  assert.strictEqual(em('AF42').v, '31/12/2026');
  assert.strictEqual(em('AG42').v, 'Total');
  assert.strictEqual(em('B43').f, NOV.caes.replace(/B\$30/g, 'B$42'));
  assert.strictEqual(em('AF44').f, NOV.gatos.replace(/B\$30/g, 'AF$42'));
  assert.strictEqual(em('C46').f, '=IF(COUNT(C43:C45)=0;"";SUM(C43:C45))');
  assert.ok(em('D47').f.indexOf('IF(D43="";""') !== -1 && em('D47').f.indexOf('RIGHT(D$42;4)') !== -1, em('D47').f);
  assert.strictEqual(em('AG43').f, '=SUM(B43:AF43)');
  assert.strictEqual(em('B48').f, '=$B$40+SUM($B$41)-$AG$46');
  assert.strictEqual(em('C40').v, 'Lote:', 'estoque e lote do mês ficam como estavam');
  assert.strictEqual(formatos.length, 33, 'formato copiado do modelo para A até o Total');

  const segunda = Array.from(ctx.montarMesesNoControleDeDoses_(sheet));
  assert.strictEqual(segunda.join('|'), 'Dezembro: já estava montado');
});

teste('controle: bloco do mês com dados digitados não é tocado', () => {
  const { sheet, v, f, pos } = controleFalso();
  const [i, j] = pos('E44');
  v[i][j] = '12';
  const ctx = carregar();
  const feitos = Array.from(ctx.montarMesesNoControleDeDoses_(sheet));
  assert.ok(/linhas 42 a 48 já têm dados; nada mudou/.test(feitos.join('|')), feitos.join('|'));
  assert.strictEqual(v[41][0], '', 'nada gravado');
  assert.strictEqual(f[42][1], '');
});

teste('links: avisa quando a data da aba não tem coluna no Controle de doses', () => {
  const { sheet: controle } = controleFalso();
  const montar = (nome, dia) => {
    const aba = abaDoDia(nome, [linhaDia('Gabriel Fernando', '16 99327-0368', '', dia, 'Manhã')]);
    const original = aba.stubs.SpreadsheetApp.getActiveSpreadsheet;
    aba.stubs.SpreadsheetApp.getActiveSpreadsheet = () => {
      const ss = original();
      const sheetDaAba = ss.getActiveSheet();
      sheetDaAba.getParent = () => ({
        getSpreadsheetTimeZone: () => 'America/Sao_Paulo',
        getSheetByName: (n) => (n === 'Controle de doses' ? controle : null),
      });
      return ss;
    };
    carregar(aba.stubs).addWhatsAppLinks();
    return aba.alertas.join('|');
  };
  assert.ok(!/Controle de doses/.test(montar('05/11/2026', DIA_05_11)), 'novembro já está no controle');
  assert.ok(/03\/12\/2026 ainda não tem coluna no "Controle de doses"/.test(montar('03/12/2026', new Date(Date.UTC(2026, 11, 3)))));
});

function planilhaComAbas(controle, nomes) {
  return {
    getSheetByName: (n) => (n === 'Controle de doses' ? controle : null),
    getSheets: () => nomes.map(n => ({ getName: () => n })),
  };
}

teste('controle: a linha "Dia" mostra só as datas com aba, em ordem', () => {
  const { sheet, v, pos, escritas } = controleFalso();
  const ctx = carregar();
  const ss = planilhaComAbas(sheet, ['Padrão', '06/11/2026', '04/11/2026', '05/11/2026', '27/10/2026', 'Agendadas']);
  const feitos = Array.from(ctx.organizarDiasNoControleDeDoses_(ss));

  assert.strictEqual(feitos.join('|'), 'Novembro: 04/11/2026, 05/11/2026, 06/11/2026');
  const linha = v[pos('A30')[0]];
  assert.strictEqual(linha.slice(1, 5).join(','), '04/11/2026,05/11/2026,06/11/2026,');
  assert.ok(linha.slice(4, 28).every(c => c === ''), 'as outras colunas do mês ficam vazias');
  assert.strictEqual(linha[28], 'Total', 'a coluna Total fica onde está');

  const antes = escritas.length;
  assert.strictEqual(Array.from(ctx.organizarDiasNoControleDeDoses_(ss)).length, 0, 'sem mudança, nada é gravado');
  assert.strictEqual(escritas.length, antes);

  // Aba nova e aba apagada: o cabeçalho acompanha.
  const depois = planilhaComAbas(sheet, ['04/11/2026', '06/11/2026', '12/11/2026']);
  assert.strictEqual(Array.from(ctx.organizarDiasNoControleDeDoses_(depois)).join('|'),
    'Novembro: 04/11/2026, 06/11/2026, 12/11/2026');
  assert.strictEqual(v[29].slice(1, 4).join(','), '04/11/2026,06/11/2026,12/11/2026');

  // Mês sem nenhuma aba ainda: o ano vem de outra linha "Dia".
  assert.strictEqual(Array.from(ctx.organizarDiasNoControleDeDoses_(planilhaComAbas(sheet, []))).join('|'),
    'Novembro: nenhuma aba de dia');
  assert.strictEqual(Array.from(ctx.organizarDiasNoControleDeDoses_(planilhaComAbas(sheet, ['05/11/2026']))).join('|'),
    'Novembro: 05/11/2026');
});

teste('controle: mês com número digitado à mão não é reorganizado', () => {
  const { sheet, v, pos } = controleFalso();
  const [i, j] = pos('E33');
  v[i][j] = '2';  // perdas digitadas, sem fórmula
  const ctx = carregar();
  const feitos = Array.from(ctx.organizarDiasNoControleDeDoses_(planilhaComAbas(sheet, ['04/11/2026'])));
  assert.strictEqual(feitos.join('|'), 'Novembro: E33 tem número digitado; nada mudou');
  assert.strictEqual(v[29][2], '05/11/2026', 'cabeçalho intacto');
});

teste('controle: Dezembro montado também é organizado, e o acionador só reage a abas', () => {
  const { sheet, v, pos } = controleFalso();
  let chamadas = 0;
  const ss = planilhaComAbas(sheet, ['04/11/2026', '02/12/2026']);
  const ctx = carregar({
    LockService: { getDocumentLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
    SpreadsheetApp: { getActiveSpreadsheet: () => { chamadas++; return ss; } },
  });
  ctx.montarMesesNoControleDeDoses_(sheet);
  ctx.aoMudarPlanilha({ changeType: 'EDIT', source: ss });
  assert.strictEqual(v[pos('B42')[0]][1], '01/12/2026', 'digitar numa célula não reorganiza');
  ctx.aoMudarPlanilha({ changeType: 'INSERT_GRID', source: ss });
  assert.strictEqual(v[pos('A30')[0]].slice(1, 3).join(','), '04/11/2026,');
  assert.strictEqual(v[pos('A42')[0]].slice(1, 3).join(','), '02/12/2026,');
  assert.strictEqual(v[pos('A42')[0]][32], 'Total');
  assert.strictEqual(chamadas, 0, 'usa a planilha do evento');
});

teste('controle: edição na planilha só reorganiza quando a lista de abas de dia muda', () => {
  const { sheet, v, escritas } = controleFalso();
  const guardado = {};
  const props = { getProperty: (k) => guardado[k] || null, setProperty: (k, x) => { guardado[k] = x; } };
  const nomes = ['Padrão', '04/11/2026', '05/11/2026'];
  const ss = planilhaComAbas(sheet, nomes);
  const ctx = carregar({ PropertiesService: { getDocumentProperties: () => props } });
  const editar = () => ctx.onEditInstalado({ source: ss, range: { getSheet: () => ({ getName: () => '04/11/2026' }), getColumn: () => 13 }, value: '1' });

  editar();
  assert.strictEqual(v[29].slice(1, 4).join(','), '04/11/2026,05/11/2026,');
  const depoisDaPrimeira = escritas.length;
  editar();
  editar();
  assert.strictEqual(escritas.length, depoisDaPrimeira, 'sem aba nova, a edição não regrava o Controle');

  nomes.push('06/11/2026');  // aba copiada do Padrão e renomeada
  editar();
  assert.strictEqual(v[29].slice(1, 4).join(','), '04/11/2026,05/11/2026,06/11/2026');
});

// --------------------------------------------------------------------------
// Cobertura do atlas: só rua, número e bairro saem da planilha
// --------------------------------------------------------------------------
teste('cobertura: payload leva só rua, número, bairro e a linha (nunca nome nem telefone)', () => {
  const ctx = carregar();
  const dados = [CABECALHO_MESTRE, LINHA_RAQUEL, LINHA_IRANEIDE];
  const linhas = ctx.montarLinhasCobertura_(dados, ctx.detectarOffset_(dados));
  assert.strictEqual(linhas.length, 2);
  assert.deepStrictEqual(Object.keys(linhas[0]).sort(), ['bairro', 'linha', 'numero', 'rua']);
  assert.strictEqual(linhas[0].rua, 'Rua 4');
  assert.strictEqual(linhas[0].numero, '1299');
  assert.strictEqual(linhas[0].linha, 2);
  const texto = JSON.stringify(linhas);
  ['Raquel', 'Iraneide', '16992510438', 'Pipoca'].forEach(t => assert.ok(texto.indexOf(t) === -1, 'vazou: ' + t));
});

teste('cobertura: linha sem rua não é enviada', () => {
  const ctx = carregar();
  const vazia = LINHA_RAQUEL.slice(); vazia[2] = '';
  assert.strictEqual(ctx.montarLinhasCobertura_([CABECALHO_MESTRE, vazia], 1).length, 0);
});

teste('cobertura: lotes são somados, por bairro e na lista do que ficou de fora', () => {
  const ctx = carregar();
  const a = { total: 2, ponto: 1, rua: 1, nenhum: 0, sem_rua: 0, cortado: false,
    por_bairro: { Centro: { total: 2, ponto: 1, rua: 1, nenhum: 0, sem_rua: 0 } },
    nao_resolvidos: [{ linha: 3, rua: 'Rua 9', numero: '5', situacao: 'rua' }] };
  const b = { total: 2, ponto: 0, rua: 0, nenhum: 2, sem_rua: 0, cortado: false,
    por_bairro: { Centro: { total: 1, ponto: 0, rua: 0, nenhum: 1, sem_rua: 0 }, 'Jardim Siena': { total: 1, ponto: 0, rua: 0, nenhum: 1, sem_rua: 0 } },
    nao_resolvidos: [{ linha: 8, rua: 'Rua X', numero: '1', situacao: 'nenhum' }, { linha: 9, rua: 'Rua Y', numero: '2', situacao: 'nenhum' }] };
  const c = ctx.consolidarCobertura_([a, b]);
  assert.strictEqual(c.total, 4); assert.strictEqual(c.ponto, 1); assert.strictEqual(c.rua, 1); assert.strictEqual(c.nenhum, 2);
  assert.strictEqual(c.por_bairro.Centro.total, 3); assert.strictEqual(c.por_bairro['Jardim Siena'].nenhum, 1);
  assert.strictEqual(c.nao_resolvidos.length, 3);
  const texto = ctx.textoCobertura_(c);
  assert.match(texto, /Casa com ponto conferido: 1 \(25%\)/);
  assert.match(texto, /Não encontrado: 2 \(50%\)/);
});

teste('cobertura: chama o PetOrlândia com o token e em lotes, e escreve na aba própria', () => {
  const chamadas = [];
  let aba = null;
  const dados = [CABECALHO_MESTRE];
  for (let i = 0; i < 320; i++) { const l = LINHA_RAQUEL.slice(); l[3] = String(i + 1); dados.push(l); }
  const abaDados = { getDataRange: () => ({ getValues: () => dados }) };
  const planilha = {
    getActiveSheet: () => abaDados,
    getSheetByName: () => aba,
    insertSheet: () => { aba = { clear() {}, escrito: null, getRange(r, c, nl, nc) { return { setValues: v => { aba.escrito = v; } }; } }; return aba; }
  };
  const alertas = [];
  const stubs = {
    SpreadsheetApp: { getActiveSpreadsheet: () => planilha, getUi: () => ({ alert: (...a) => alertas.push(a.join(' ')), ButtonSet: { OK: 'OK' } }) },
    PropertiesService: { getScriptProperties: () => ({ getProperty: () => 'segredo' }) },
    UrlFetchApp: { fetch: (url, opts) => {
      const linhas = JSON.parse(opts.payload).rows;
      chamadas.push({ url, token: opts.headers['X-PMO-Token'], n: linhas.length });
      return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ total: linhas.length, ponto: linhas.length, rua: 0, nenhum: 0, sem_rua: 0, por_bairro: { 'Jardim Siena': { total: linhas.length, ponto: linhas.length, rua: 0, nenhum: 0, sem_rua: 0 } }, nao_resolvidos: [] }) };
    } },
  };
  carregar(stubs).medirCoberturaAtlas();
  assert.deepStrictEqual(chamadas.map(c => c.n), [150, 150, 20], 'três lotes');
  assert.ok(chamadas.every(c => c.token === 'segredo' && /vacina-pmo\/webhook\/cobertura-atlas$/.test(c.url)));
  assert.ok(aba && aba.escrito, 'escreveu na aba "Cobertura do Atlas"');
  assert.strictEqual(aba.escrito[0][0], 'Cobertura do atlas');
  assert.ok(alertas.some(a => /320 endereços/.test(a)), alertas.join('|'));
  assert.strictEqual(abaDados.escrito, undefined, 'a aba de dados não é alterada');
});

teste('cobertura: erro do servidor avisa e não escreve nada', () => {
  let escreveu = false;
  const planilha = { getActiveSheet: () => ({ getDataRange: () => ({ getValues: () => [CABECALHO_MESTRE, LINHA_RAQUEL] }) }),
    getSheetByName: () => null, insertSheet: () => { escreveu = true; return {}; } };
  const alertas = [];
  const stubs = {
    SpreadsheetApp: { getActiveSpreadsheet: () => planilha, getUi: () => ({ alert: (...a) => alertas.push(a.join(' ')), ButtonSet: { OK: 'OK' } }) },
    PropertiesService: { getScriptProperties: () => ({ getProperty: () => 'segredo' }) },
    UrlFetchApp: { fetch: () => ({ getResponseCode: () => 503, getContentText: () => 'timeout' }) },
  };
  carregar(stubs).medirCoberturaAtlas();
  assert.ok(alertas.some(a => /503/.test(a)));
  assert.strictEqual(escreveu, false);
});

// --------------------------------------------------------------------------
// Quadro "Status PMO": a planilha confere sozinha para onde cada link aponta
// --------------------------------------------------------------------------
const ID_PLANILHA = 'planilha-1';
const CABECALHO_FILA = ['Nome completo', 'Endereço', 'Número', 'Complemento', 'Bairro', 'Telefone', 'Telefone 2'];

function linhaFila(nome, rua, numero, telefone) {
  return [nome, rua, numero, '', 'Centro', telefone || '', ''];
}

function linkPara(gid, linha) {
  return 'https://docs.google.com/spreadsheets/d/' + ID_PLANILHA + '/edit#gid=' + gid + '&range=A' + linha;
}

// Texto com link, no formato que o Sheets devolve: um trecho por link.
function ricoFalso(texto, links) {
  const trechos = (links || []).slice().sort((a, b) => a.inicio - b.inicio);
  return {
    getText: () => texto,
    getRuns: () => trechos.map(l => ({ getLinkUrl: () => l.url })),
    links: trechos,
  };
}

function quadroAntigo(texto, gid, linha, aba) {
  const inicio = texto.indexOf(aba);
  return ricoFalso(texto, [{ inicio, fim: inicio + aba.length, url: linkPara(gid, linha) }]);
}

// Planilha em memória: aba mestre + abas de fila/dia. ``status`` são os
// RichText da coluna M (linha 2 em diante) e ``notas`` as notas da coluna A.
function planilhaDoQuadro({ mestre, status, notas, abas, props }) {
  const gravados = {};
  const cores = {};
  const propriedades = Object.assign({}, props || {});
  const folhas = [];
  const folhaMestre = {
    getName: () => 'Vacinação 2026',
    getSheetId: () => 0,
    getLastRow: () => mestre.length + 1,
    getMaxColumns: () => 26,
    getRange: (r, c, nr, nc) => ({
      getValues: () => [CABECALHO_MESTRE.slice(0, nc)].concat(mestre.map(l => l.slice(0, nc))).slice(r - 1, r - 1 + nr),
      getNotes: () => Array.from({ length: nr }, (_, i) => [(notas || [])[r - 2 + i] || '']),
      getRichTextValues: () => Array.from({ length: nr }, (_, i) => [(status || [])[r - 2 + i] || ricoFalso('')]),
      setRichTextValues: (valores) => valores.forEach((v, i) => { gravados[r + i] = v[0]; }),
      setBackground: (cor) => { cores[r + ':' + c] = cor; },
    }),
  };
  folhas.push(folhaMestre);
  Object.keys(abas || {}).forEach((nome, i) => {
    const valores = [CABECALHO_FILA].concat(abas[nome]);
    folhas.push({
      getName: () => nome,
      getSheetId: () => 100 + i,
      getLastRow: () => valores.length,
      getMaxColumns: () => 26,
      getRange: (r, c, nr, nc) => ({ getValues: () => valores.slice(r - 1, r - 1 + nr).map(l => l.slice(0, nc)) }),
    });
  });
  const ss = {
    getId: () => ID_PLANILHA,
    getSheets: () => folhas,
    getSheetByName: (n) => folhas.find(f => f.getName() === n) || null,
    getSpreadsheetTimeZone: () => 'America/Sao_Paulo',
    toast: () => {},
  };
  const stubs = {
    Utilities: UTILITIES_FALSO,
    LockService: { getDocumentLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
    PropertiesService: {
      getDocumentProperties: () => ({
        getProperty: (k) => (k in propriedades ? propriedades[k] : null),
        setProperty: (k, v) => { propriedades[k] = v; },
        deleteProperty: (k) => { delete propriedades[k]; },
      }),
    },
    SpreadsheetApp: {
      getActiveSpreadsheet: () => ss,
      newRichTextValue: () => {
        const rt = { texto: '', links: [] };
        const b = {
          setText: (t) => { rt.texto = t; return b; },
          setLinkUrl: (inicio, fim, url) => { rt.links.push({ inicio, fim, url }); return b; },
          build: () => ricoFalso(rt.texto, rt.links),
        };
        return b;
      },
    },
  };
  // Para cada linha gravada: o texto e, por trecho com link, "trecho -> url".
  const lido = (linha) => {
    const v = gravados[linha];
    if (!v) return null;
    return { texto: v.getText(), links: v.links.map(l => v.getText().slice(l.inicio, l.fim) + ' -> ' + l.url) };
  };
  return { stubs, gravados, cores, propriedades, lido, gidDe: (nome) => 100 + Object.keys(abas || {}).indexOf(nome) };
}

const MARIA = ['20/10/2026 10:00:00', 'Maria das Graças Brandão', 'Rua 7', '210', '', 'Centro',
  '16991112222', '', '2', '0', 'Mel, Bob', ''];

teste('quadro: inscrição que mudou de linha volta a abrir a linha certa', () => {
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    status: [quadroAntigo('Fluxo ativo\nInscrição a agendar (linha 84): Fluxo ativo', 100, 84, 'Inscrição a agendar')],
    abas: { 'Inscrição a agendar': [linhaFila('Joana Lima', 'Rua 1', '5', '16990000000'),
      linhaFila('Maria das Graças Brandão', 'Rua 7', '210', '16 99111-2222')] },
  });
  const resumo = carregar(p.stubs).conferirQuadroStatusPMO();

  assert.strictEqual(resumo.atualizadas, 1);
  const q = p.lido(2);
  assert.strictEqual(q.texto, 'Fluxo ativo\nInscrição a agendar (linha 3): Fluxo ativo');
  assert.deepStrictEqual(q.links, ['Inscrição a agendar -> ' + linkPara(p.gidDe('Inscrição a agendar'), 3)]);
});

teste('quadro: quem foi agendado num dia aparece na hora, sem a linha velha da fila', () => {
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    status: [quadroAntigo('Fluxo ativo\nInscrição a agendar (linha 52): Fluxo ativo', 100, 52, 'Inscrição a agendar')],
    abas: {
      'Inscrição a agendar': [linhaFila('Joana Lima', 'Rua 1', '5', '16990000000')],
      '10/11/2099': [linhaFila('Maria das Graças Brandão', 'Rua 7', '210', '16991112222')],
    },
  });
  carregar(p.stubs).conferirQuadroStatusPMO();

  const q = p.lido(2);
  assert.strictEqual(q.texto, 'Agendado\n10/11/2099 (linha 2): Pendente');
  assert.deepStrictEqual(q.links, ['10/11/2099 -> ' + linkPara(p.gidDe('10/11/2099'), 2)]);
  assert.strictEqual(p.cores['2:13'], '#c9daf8');
});

teste('quadro: homônimo com outro telefone não recebe o link', () => {
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    status: [quadroAntigo('Fluxo ativo\nInscrição a agendar (linha 2): Fluxo ativo', 100, 2, 'Inscrição a agendar')],
    abas: { 'Inscrição a agendar': [linhaFila('Maria das Graças Brandão', 'Rua 9', '40', '16998887777')] },
  });
  carregar(p.stubs).conferirQuadroStatusPMO();

  const q = p.lido(2);
  assert.strictEqual(q.texto, 'Pendente');
  assert.deepStrictEqual(q.links, []);
});

teste('quadro: nome abreviado e telefone igual é a mesma pessoa', () => {
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    abas: { 'Inscrição a agendar': [linhaFila('Maria G. Brandão', 'R. 7', '210', '(16) 99111-2222')] },
  });
  carregar(p.stubs).conferirQuadroStatusPMO();

  assert.strictEqual(p.lido(2).texto, 'Fluxo ativo\nInscrição a agendar (linha 2): Fluxo ativo');
});

teste('quadro: aparece duas vezes na fila, as duas linhas ficam visíveis', () => {
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    abas: { 'Inscrição a agendar': [
      linhaFila('Maria das Graças Brandão', 'Rua 7', '210', '16991112222'),
      linhaFila('Joana Lima', 'Rua 1', '5', '16990000000'),
      linhaFila('Maria das Graças Brandão', 'Rua 7', '210', '16991112222'),
    ] },
  });
  carregar(p.stubs).conferirQuadroStatusPMO();

  assert.strictEqual(p.lido(2).texto,
    'Fluxo ativo\nInscrição a agendar (linha 2): Fluxo ativo\nInscrição a agendar (linha 4): Fluxo ativo');
  assert.strictEqual(p.lido(2).links.length, 2);
});

teste('quadro: dia antigo onde a pessoa sumiu fica sem link e o Vacinado é mantido', () => {
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    status: [quadroAntigo('Vacinado\n01/09/2026 (linha 7): Vacinado - 01/09/2026', 100, 7, '01/09/2026')],
    abas: { '01/09/2026': [linhaFila('Joana Lima', 'Rua 1', '5', '16990000000')] },
  });
  carregar(p.stubs).conferirQuadroStatusPMO();

  assert.strictEqual(p.lido(2).texto, 'Vacinado\n01/09/2026 (não encontrado): Vacinado - 01/09/2026');
  assert.deepStrictEqual(p.lido(2).links, []);
  assert.strictEqual(p.cores['2:13'], undefined);
});

teste('quadro: status do PetOrlândia é reaproveitado e quadro certo não é regravado', () => {
  const texto = 'Agendado\n10/11/2099 (linha 2): Pendente';
  const inicio = texto.indexOf('10/11/2099');
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    status: [ricoFalso(texto, [{ inicio, fim: inicio + 10, url: linkPara(100, 2) }])],
    abas: { '10/11/2099': [linhaFila('Maria das Graças Brandão', 'Rua 7', '210', '16991112222')] },
  });
  const resumo = carregar(p.stubs).conferirQuadroStatusPMO();

  assert.strictEqual(resumo.atualizadas, 0);
  assert.deepStrictEqual(p.gravados, {});
});

teste('quadro: texto digitado por alguém na coluna M não é tocado', () => {
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    status: [ricoFalso('ligar antes, portão quebrado')],
    abas: { 'Inscrição a agendar': [linhaFila('Maria das Graças Brandão', 'Rua 7', '210', '16991112222')] },
  });
  carregar(p.stubs).conferirQuadroStatusPMO();
  assert.deepStrictEqual(p.gravados, {});
});

teste('quadro: status de outro tutor que ficou na linha não é herdado', () => {
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    status: [quadroAntigo('Vacinado\n01/09/2026 (linha 7): Vacinado - 01/09/2026', 100, 7, '01/09/2026')],
    notas: ['PetOrlandia PMO\nTutor: Joana Lima\nStatus geral: Vacinado'],
    abas: { 'Inscrição a agendar': [linhaFila('Maria das Graças Brandão', 'Rua 7', '210', '16991112222')] },
  });
  carregar(p.stubs).conferirQuadroStatusPMO();

  assert.strictEqual(p.lido(2).texto, 'Fluxo ativo\nInscrição a agendar (linha 2): Fluxo ativo');
});

teste('quadro: aba de dia com nome digitado fora do padrão continua contando', () => {
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    status: [quadroAntigo('Vacinado\n18/06/2026  (linha 9): Vacinado - 18/06/2026', 100, 9, '18/06/2026 ')],
    abas: { '18/06/2026 ': [linhaFila('Joana Lima', 'Rua 1', '5', '16990000000'),
      linhaFila('Maria das Graças Brandão', 'Rua 7', '210', '16991112222')] },
  });
  carregar(p.stubs).conferirQuadroStatusPMO();

  assert.strictEqual(p.lido(2).texto, 'Vacinado\n18/06/2026  (linha 3): Vacinado - 18/06/2026');
  const ctx = carregar(p.stubs);
  assert.strictEqual(ctx.diaDaAba_('27/03/26'), '2026-03-27');
  assert.strictEqual(ctx.diaDaAba_('1/06/2026'), '2026-06-01');
  assert.strictEqual(ctx.diaDaAba_('Encaixes'), '');
});

teste('quadro: telefone trocado vale quando nome e endereço confirmam', () => {
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    abas: { 'Inscrição a agendar': [linhaFila('Maria das Graças Brandão', 'Rua 7', '210', '16955554444')] },
  });
  carregar(p.stubs).conferirQuadroStatusPMO();
  assert.strictEqual(p.lido(2).texto, 'Fluxo ativo\nInscrição a agendar (linha 2): Fluxo ativo');
});

teste('quadro: simulação conta as mudanças por tipo e não grava nada', () => {
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    status: [quadroAntigo('Fluxo ativo\nInscrição a agendar (linha 84): Fluxo ativo', 100, 84, 'Inscrição a agendar')],
    abas: { 'Inscrição a agendar': [linhaFila('Maria das Graças Brandão', 'Rua 7', '210', '16991112222')] },
  });
  const resumo = carregar(p.stubs).conferirQuadro_(p.stubs.SpreadsheetApp.getActiveSpreadsheet(), true);

  assert.deepStrictEqual(p.gravados, {});
  assert.strictEqual(resumo.atualizadas, 1);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(resumo.tipos)), { 'linha corrigida na mesma aba': 1 });
});

teste('quadro: edição confere na hora, no máximo uma vez a cada 3 minutos', () => {
  const p = planilhaDoQuadro({
    mestre: [MARIA],
    abas: { 'Inscrição a agendar': [linhaFila('Maria das Graças Brandão', 'Rua 7', '210', '16991112222')] },
  });
  const ctx = carregar(p.stubs);
  const edicao = (aba) => ({ range: { getSheet: () => ({ getName: () => aba }) } });

  ctx.conferirQuadroAposEdicao_(edicao('Controle de doses'));
  assert.deepStrictEqual(p.gravados, {}, 'aba fora do quadro não dispara');
  assert.strictEqual(p.propriedades.QUADRO_STATUS_PENDENTE, undefined);

  ctx.conferirQuadroAposEdicao_(edicao('Inscrição a agendar'));
  assert.ok(p.lido(2), 'edição numa aba de fila confere na hora');
  delete p.gravados[2];

  ctx.conferirQuadroAposEdicao_(edicao('Inscrição a agendar'));
  assert.deepStrictEqual(p.gravados, {}, 'segunda edição logo em seguida espera');
  assert.strictEqual(p.propriedades.QUADRO_STATUS_PENDENTE, '1');

  ctx.conferirQuadroPeriodico();
  assert.strictEqual(p.propriedades.QUADRO_STATUS_PENDENTE, '1', 'o acionador respeita o intervalo');
  p.propriedades.QUADRO_STATUS_ULTIMA = String(Date.now() - 181 * 1000);
  ctx.conferirQuadroPeriodico();
  assert.strictEqual(p.propriedades.QUADRO_STATUS_PENDENTE, undefined, 'e confere o que ficou pendente');
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
