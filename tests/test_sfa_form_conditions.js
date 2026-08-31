'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');

const conditions = require(path.resolve(__dirname, '..', 'static', 'js', 'sfa_form_conditions.js'));
const reviewConditions = require(path.resolve(__dirname, '..', 'static', 'js', 'sfa_review_conditions.js'));

const answers = {
  houve_gasto: 'Sim',
  diagnostico: 'Dengue',
  exposicao_animal: ['Carrapato', 'Trabalho ou atividade com animais'],
  exposicao_ambiental: ['Nenhuma destas situacoes'],
  vazio: '',
};

const getValue = (key) => answers[key];

assert.equal(
  conditions.evaluateRule(
    {
      all: [
        { field: 'houve_gasto', operator: 'equals', value: 'Sim' },
        { field: 'diagnostico', op: 'eq', value: 'dengue' },
      ],
    },
    getValue,
  ),
  true,
  'all deve exigir que todas as folhas sejam verdadeiras',
);

assert.equal(
  conditions.evaluateRule(
    {
      any: [
        { field: 'houve_gasto', operator: 'equals', value: 'Nao' },
        { field: 'diagnostico', operator: 'equals', value: 'DENGUE' },
      ],
    },
    getValue,
  ),
  true,
  'any deve aceitar uma unica folha verdadeira',
);

assert.equal(
  conditions.evaluateRule(
    { not: { field: 'houve_gasto', operator: 'equals', value: 'Nao' } },
    getValue,
  ),
  true,
  'not deve inverter a regra filha',
);

assert.equal(
  conditions.evaluateRule(
    {
      field: 'exposicao_animal',
      operator: 'selected_any_except',
      values: ['Nenhum evento animal relevante'],
    },
    getValue,
  ),
  true,
  'selected_any_except deve reconhecer uma selecao acionavel',
);

assert.equal(
  conditions.evaluateRule(
    {
      field: 'exposicao_ambiental',
      operator: 'selected_any_except',
      values: ['Nenhuma destas situacoes'],
    },
    getValue,
  ),
  false,
  'selected_any_except deve ocultar quando so a opcao negativa foi marcada',
);

assert.equal(
  conditions.evaluateRule({ const: true }, getValue),
  true,
  'uma condicao anterior resolvida pelo servidor deve aceitar const=true',
);
assert.equal(
  conditions.evaluateRule({ const: false }, getValue),
  false,
  'uma condicao anterior resolvida pelo servidor deve aceitar const=false',
);

assert.equal(
  conditions.evaluateRule(
    {
      all: [
        { field: 'houve_gasto', operator: 'equals', value: 'Nao' },
        { field: 'vazio', operator: 'present' },
      ],
    },
    getValue,
  ),
  false,
  'um campo condicional deve permanecer oculto quando o gatilho nao ocorreu',
);

assert.equal(
  conditions.evaluateRule(
    {
      any: [
        { field: 'vazio', operator: 'present' },
        { field: 'exposicao_ambiental', operator: 'selected_any_except', values: ['Nenhuma destas situacoes'] },
      ],
    },
    getValue,
  ),
  false,
  'any deve ocultar quando nenhum caminho e verdadeiro',
);

assert.equal(
  conditions.evaluateRule(
    {
      all: [
        { field: 'houve_gasto', operator: 'equals', value: 'Sim' },
        {
          any: [
            { field: 'diagnostico', operator: 'equals', value: 'Chikungunya' },
            { not: { field: 'vazio', operator: 'present' } },
          ],
        },
      ],
    },
    getValue,
  ),
  true,
  'combinacoes aninhadas de all/any/not devem ser deterministicas',
);

const proxyDetailRule = {
  all: [
    { field: 'respondent_role', operator: 'nonempty' },
    { field: 'respondent_role', operator: 'not_equals', value: 'A propria pessoa' },
  ],
};
assert.equal(
  conditions.evaluateRule(proxyDetailRule, () => ''),
  false,
  'o detalhe do respondente deve ficar oculto antes da escolha do papel',
);
assert.equal(
  conditions.evaluateRule(proxyDetailRule, () => 'Pai, mae ou responsavel'),
  true,
  'o detalhe do respondente deve abrir somente para um respondente proxy',
);

const reviewDocument = {
  querySelectorAll(selector) {
    if (selector === '[name="answer__gatilho"]') {
      return [{ type: 'radio', checked: true, value: 'Sim' }];
    }
    return [];
  },
};
assert.equal(
  conditions.fieldValues(reviewDocument, 'gatilho'),
  'Sim',
  'a avaliacao deve usar as respostas de teste prefixadas para abrir aprofundamentos',
);

const summaryElement = { textContent: '' };
const reviewQuestions = [
  { hidden: false, hasAttribute: () => false },
  { hidden: false, hasAttribute: (name) => name === 'data-visible-if' },
  { hidden: true, hasAttribute: (name) => name === 'data-visible-if' },
];
reviewConditions.updateSummary({
  querySelector(selector) {
    return selector === '[data-sfa-condition-summary]' ? summaryElement : null;
  },
  querySelectorAll(selector) {
    return selector === '[data-review-question]' ? reviewQuestions : [];
  },
});
assert.equal(
  summaryElement.textContent,
  '2 perguntas agora · 1 aprofundamento aberto · 1 em espera',
  'o contador deve explicar o tamanho atual e os aprofundamentos do percurso',
);

console.log('sfa_form_conditions: ok');
