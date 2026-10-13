// Conversões de static/js/campos_br.js (CPF, telefone e RG), rodando no Node.
// Executado por tests/test_campos_br_guard.py::test_funcoes_passam_no_node.
'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');

const campos = require(path.join(__dirname, '..', 'static', 'js', 'campos_br.js'));

let total = 0;
function caso(nome, fn) {
  total += 1;
  try {
    fn();
  } catch (erro) {
    console.error(`FALHOU: ${nome}\n${erro.stack || erro}`);
    process.exitCode = 1;
  }
}

// --- CPF --------------------------------------------------------------------

caso('CPF gravado sem máscara aparece formatado', () => {
  assert.equal(campos.formatCpf('36243026809'), '362.430.268-09');
});

caso('CPF gravado com máscara continua igual', () => {
  assert.equal(campos.formatCpf('362.430.268-09'), '362.430.268-09');
});

caso('CPF fora do padrão não é mexido', () => {
  assert.equal(campos.formatCpf('99999'), '99999');
  assert.equal(campos.formatCpf(''), '');
  assert.equal(campos.formatCpf(null), '');
});

caso('CPF é formatado enquanto digita, com ou sem pontuação', () => {
  assert.equal(campos.maskCpf('3'), '3');
  assert.equal(campos.maskCpf('3624'), '362.4');
  assert.equal(campos.maskCpf('3624302'), '362.430.2');
  assert.equal(campos.maskCpf('3624302680'), '362.430.268-0');
  assert.equal(campos.maskCpf('362.430.268-09'), '362.430.268-09');
  assert.equal(campos.maskCpf('362430268091234'), '362.430.268-09');
});

// --- Telefone ---------------------------------------------------------------

caso('telefone aparece igual em todas as formas em que o banco o guarda', () => {
  // As formas abaixo existem em produção para o mesmo número.
  ['16992690405', '(16) 99269-0405', '(16)992690405', '+5516992690405', '5516992690405',
    '16 99269-0405', '016992690405'].forEach((gravado) => {
    assert.equal(campos.formatPhone(gravado), '(16) 99269-0405', gravado);
  });
});

caso('telefone fixo tem 10 dígitos', () => {
  assert.equal(campos.formatPhone('1638261234'), '(16) 3826-1234');
  assert.equal(campos.formatPhone('(16)38261234'), '(16) 3826-1234');
  assert.equal(campos.formatPhone('+551638261234'), '(16) 3826-1234');
});

caso('telefone de outro país ou incompleto não é mexido', () => {
  assert.equal(campos.formatPhone('+351912345678'), '+351912345678');
  assert.equal(campos.formatPhone('999999999'), '999999999');
  assert.equal(campos.formatPhone(''), '');
});

caso('+55 não vira DDD (a máscara antiga transformava +5516... em (55) 16...)', () => {
  assert.equal(campos.phoneNationalDigits('+5516992690405'), '16992690405');
  assert.equal(campos.maskPhoneTyping('+5516992690405'), '(16) 99269-0405');
});

caso('telefone é formatado enquanto digita', () => {
  assert.equal(campos.maskPhoneTyping('1'), '(1');
  assert.equal(campos.maskPhoneTyping('16'), '(16');
  assert.equal(campos.maskPhoneTyping('169'), '(16) 9');
  assert.equal(campos.maskPhoneTyping('169926'), '(16) 9926');
  assert.equal(campos.maskPhoneTyping('1699269'), '(16) 9926-9');
  assert.equal(campos.maskPhoneTyping('1699269040'), '(16) 9926-9040');
  assert.equal(campos.maskPhoneTyping('16992690405'), '(16) 99269-0405');
  assert.equal(campos.maskPhoneTyping('(16) 99269-0405'), '(16) 99269-0405');
  assert.equal(campos.maskPhoneTyping('01699269'), '(16) 9926-9');
  assert.equal(campos.maskPhoneTyping('+351 912 345 678'), '+351 912 345 678');
});

// --- Validação --------------------------------------------------------------

caso('campo vazio é válido (obrigatoriedade é com o required)', () => {
  ['cpf', 'telefone', 'rg'].forEach((tipo) => {
    assert.equal(campos.validityMessage(tipo, '', ''), '');
    assert.equal(campos.validityMessage(tipo, '   ', 'x'), '');
  });
});

caso('o que já está gravado nunca é recusado', () => {
  // Formas reais do banco, inclusive as fora do padrão.
  [['cpf', '36243026809'], ['cpf', '362.430.268-09'], ['cpf', '99999'],
    ['telefone', '16992690405'], ['telefone', '(16) 99269-0405'], ['telefone', '+5516992690405'],
    ['telefone', '(16)992690405'], ['telefone', '999999999'], ['telefone', '(16)9999'],
    ['rg', '12.345.678-9'], ['rg', 'MG1234567'], ['rg', '12345678X']].forEach(([tipo, gravado]) => {
    const naTela = campos.KINDS[tipo].format(gravado);
    assert.equal(campos.validityMessage(tipo, naTela, gravado), '', `${tipo} ${gravado}`);
    assert.equal(campos.validityMessage(tipo, gravado, gravado), '', `${tipo} ${gravado} cru`);
  });
});

caso('CPF novo precisa de 11 dígitos, com ou sem máscara', () => {
  assert.equal(campos.validityMessage('cpf', '362.430.268-09', ''), '');
  assert.equal(campos.validityMessage('cpf', '36243026809', ''), '');
  assert.match(campos.validityMessage('cpf', '362.430.268', ''), /11 dígitos/);
  assert.match(campos.validityMessage('cpf', '3624302680', '36243026809'), /11 dígitos/);
});

caso('telefone novo precisa de DDD', () => {
  assert.equal(campos.validityMessage('telefone', '(16) 99269-0405', ''), '');
  assert.equal(campos.validityMessage('telefone', '16992690405', ''), '');
  assert.equal(campos.validityMessage('telefone', '(16) 3826-1234', ''), '');
  assert.equal(campos.validityMessage('telefone', '+351912345678', ''), '');
  assert.match(campos.validityMessage('telefone', '99269-0405', ''), /DDD/);
  assert.match(campos.validityMessage('telefone', '(16) 9926', '16992690405'), /DDD/);
});

caso('RG aceita pontuação, letra e dígito verificador X', () => {
  assert.equal(campos.validityMessage('rg', '12.345.678-9', ''), '');
  assert.equal(campos.validityMessage('rg', '12.345.678-X', ''), '');
  assert.equal(campos.validityMessage('rg', 'MG-12.345.678', ''), '');
  assert.equal(campos.validityMessage('rg', 'MG1234567', ''), '');
  assert.match(campos.validityMessage('rg', 'ab', ''), /RG/);
});

caso('cursor acompanha os dígitos depois da formatação', () => {
  assert.equal(campos.caretAfterDigits('(16) 99269-0405', 2), 3);
  assert.equal(campos.caretAfterDigits('(16) 99269-0405', 7), 10);
  assert.equal(campos.caretAfterDigits('362.430.268-09', 0), 0);
  assert.equal(campos.caretAfterDigits('362.430.268-09', 99), 14);
});

if (!process.exitCode) {
  console.log(`${total} casos de campos_br.js passaram`);
}
