/*
 * Conversoes de static/js/date_br.js (dd/mm/aaaa <-> ISO), sem DOM.
 *
 * Rodado por tests/test_date_br_componente.py::test_conversoes_passam_no_node.
 * O comportamento na tela (espelho, calendario, validacao) fica em
 * tests/test_date_br_browser.py, num Chromium configurado em ingles.
 *
 * Uso direto: node tests/test_date_br.js
 */
'use strict';

const path = require('path');
const dateBr = require(path.join(__dirname, '..', 'static', 'js', 'date_br.js'));

let falhas = 0;
let passes = 0;

function check(nome, obtido, esperado) {
  if (obtido === esperado) {
    passes += 1;
    return;
  }
  falhas += 1;
  console.error(`FALHOU: ${nome} -> ${JSON.stringify(obtido)} (esperado ${JSON.stringify(esperado)})`);
}

// --- ISO para o texto que a pessoa le ---------------------------------------
check('data', dateBr.toDisplay('date', '2026-09-22'), '22/09/2026');
check('data e hora', dateBr.toDisplay('datetime-local', '2026-09-22T08:05'), '22/09/2026 08:05');
check('segundos sao descartados no texto', dateBr.toDisplay('datetime-local', '2026-09-22T08:05:33'), '22/09/2026 08:05');
check('mes', dateBr.toDisplay('month', '2026-09'), '09/2026');
check('data impossivel nao vira texto', dateBr.toDisplay('date', '2026-02-31'), '');
check('vazio', dateBr.toDisplay('date', ''), '');
check('nulo', dateBr.toDisplay('date', null), '');

// --- texto digitado para ISO -------------------------------------------------
check('digitou completo', dateBr.parseTyped('date', '22/09/2026').iso, '2026-09-22');
check('digitou com um digito', dateBr.parseTyped('date', '1/2/2026').iso, '2026-02-01');
check('colou ISO', dateBr.parseTyped('date', '2026-09-22').iso, '2026-09-22');
check('29 de fevereiro em ano bissexto', dateBr.parseTyped('date', '29/02/2028').iso, '2028-02-29');
check(
  '29 de fevereiro fora de ano bissexto',
  dateBr.parseTyped('date', '29/02/2027').error,
  'Dia inválido: fevereiro de 2027 tem 28 dias.'
);
check(
  '31 de fevereiro nao "rola" para marco',
  dateBr.parseTyped('date', '31/02/2026').iso,
  ''
);
check('mes 13', dateBr.parseTyped('date', '01/13/2026').error, 'Mês inválido: use de 01 a 12.');
check(
  'ano com dois digitos',
  dateBr.parseTyped('date', '01/02/26').error,
  'Informe uma data válida no formato dd/mm/aaaa.'
);
check('data e hora', dateBr.parseTyped('datetime-local', '22/09/2026 14:30').iso, '2026-09-22T14:30');
check('hora 24', dateBr.parseTyped('datetime-local', '22/09/2026 24:00').error, 'Hora inválida: use de 00:00 a 23:59.');
check('mes digitado', dateBr.parseTyped('month', '9/2026').iso, '2026-09');
check('campo vazio nao e erro', dateBr.parseTyped('date', '   ').error, null);

// --- mascara enquanto digita -------------------------------------------------
check('so digitos', dateBr.maskTyping('date', '22092026'), '22/09/2026');
check('parcial', dateBr.maskTyping('date', '2209'), '22/09');
check('barra depois do dia', dateBr.maskTyping('date', '22/'), '22/');
check('zero a esquerda quando digita a barra', dateBr.maskTyping('date', '1/'), '01/');
check('dia e mes com um digito', dateBr.maskTyping('date', '1/2/'), '01/02/');
check('nao completa o ano', dateBr.maskTyping('date', '22/09/202'), '22/09/202');
check('ignora excesso', dateBr.maskTyping('date', '2209202699'), '22/09/2026');
check('ignora letras', dateBr.maskTyping('date', 'abc'), '');
check('data e hora', dateBr.maskTyping('datetime-local', '220920261430'), '22/09/2026 14:30');
check('hora com um digito', dateBr.maskTyping('datetime-local', '22/09/2026 9:'), '22/09/2026 09:');
check('mes', dateBr.maskTyping('month', '092026'), '09/2026');

// --- limites (min/max) -------------------------------------------------------
check(
  'antes do minimo',
  dateBr.rangeMessage('date', '2026-09-21', '2026-09-22', ''),
  'Escolha uma data a partir de 22/09/2026.'
);
check(
  'depois do maximo',
  dateBr.rangeMessage('month', '2026-10', '', '2026-09'),
  'Escolha um mês até 09/2026.'
);
check('dentro do intervalo', dateBr.rangeMessage('date', '2026-09-22', '2026-09-01', '2026-09-30'), '');
check(
  'hora entra na comparacao',
  dateBr.rangeMessage('datetime-local', '2026-09-22T07:00', '2026-09-22T08:00', ''),
  'Escolha data e hora a partir de 22/09/2026 08:00.'
);

// --- fuso: a armadilha do new Date('aaaa-mm-dd') -----------------------------
const local = dateBr.parseDateLocal('2026-09-22');
check('dia local', local.getDate(), 22);
check('mes local', local.getMonth(), 8);
check('hora local', local.getHours(), 0);
check('ida e volta', dateBr.dateToIso('date', dateBr.isoToDate('date', '2026-09-22')), '2026-09-22');
check('texto invalido', dateBr.parseDateLocal('nao é data'), null);
check(
  'hoje sai do relogio local',
  dateBr.todayIso(),
  `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}-${String(new Date().getDate()).padStart(2, '0')}`
);

console.log(falhas ? `${falhas} falha(s), ${passes} ok` : `${passes} verificacoes ok`);
process.exit(falhas ? 1 : 0);
