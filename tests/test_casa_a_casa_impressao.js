'use strict';
const assert = require('node:assert/strict');
const { desenhoDoBloco } = require('../static/js/casa_a_casa_impressao.js');
const centro = [-47.882, -20.722];
const ponto = (x, y) => [centro[0] + x / 104000, centro[1] + y / 110540];
const bloco = { c: centro, g: [[[ponto(-50, -50), ponto(50, -50), ponto(50, 50), ponto(-50, 50), ponto(-50, -50)]]] };
const vias = { nomes: ['Rua Sul', 'Avenida Leste', 'Rua Norte', 'Rua Oeste', 'Rua Paralela Distante'], linhas: [
  [0, [ponto(-80, -60), ponto(80, -60)]], [1, [ponto(60, -80), ponto(60, 80)]],
  [2, [ponto(-80, 60), ponto(80, 60)]], [3, [ponto(-60, -80), ponto(-60, 80)]],
  [4, [ponto(-80, 100), ponto(80, 100)]],
] };
const casas = Array.from({ length: 14 }, (_, i) => ({ id: 'casa-' + i, x: ponto(-49, 49)[0], y: ponto(-49, 49)[1], rua: 'Rua Oeste' }));
function conferir(desenho, quantidade, inicio) {
  assert.equal(desenho.marcadores.length, quantidade);
  assert.deepEqual(desenho.marcadores.map(m => m.numero).sort((a, b) => a - b), Array.from({ length: quantidade }, (_, i) => inicio + i + 1));
  for (const [i, m] of desenho.marcadores.entries()) {
    assert(m.x >= 12 && m.x <= 708 && m.y >= 12 && m.y <= 328, 'número dentro da área imprimível');
    for (const outro of desenho.marcadores.slice(i + 1)) assert(Math.hypot(m.x - outro.x, m.y - outro.y) >= 26, 'círculos separados, inclusive imóveis na mesma coordenada');
  }
}
const desenho = desenhoDoBloco(bloco, casas, casas, 14, vias);
conferir(desenho, 14, 14);
assert.deepEqual(desenho.lados.map(l => l.nome), vias.nomes.slice(0, 4));
const segundaFolha = desenhoDoBloco(bloco, casas, casas.slice(0, 2), 28, vias);
assert.deepEqual(segundaFolha.lados.map(l => l.nome), desenho.lados.map(l => l.nome), 'ruas sem casas nesta folha continuam presentes');
conferir(segundaFolha, 2, 28);
const vazia = desenhoDoBloco(bloco, [], [], 0, vias);
assert.equal(vazia.lados.length, 4);
assert(vazia.lados.every(l => l.nome));
const semVias = desenhoDoBloco(bloco, [], [], 0);
assert(semVias.lados.every(l => !l.nome && l.texto.join(' ').includes('não identificada')), 'não inventa nomes');
// Mesma rua dos dois lados: cada lateral precisa de sua identificação.
const iguais = desenhoDoBloco(bloco, [], [], 0, { ...vias, nomes: ['Rua Única', 'Rua Única', 'Rua Única', 'Rua Única', 'Distante'] });
assert.equal(iguais.lados.filter(l => l.nome === 'Rua Única').length, 4);
// Rotação conserva a atribuição das vias e a leitura dos textos.
const girar = p => {
  const x = (p[0] - centro[0]) * 104000, y = (p[1] - centro[1]) * 110540, a = Math.PI / 6;
  return ponto(x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a));
};
const girado = desenhoDoBloco({ ...bloco, g: bloco.g.map(p => p.map(r => r.map(girar))) }, [], [], 0,
  { ...vias, linhas: vias.linhas.map(([n, linha]) => [n, linha.map(girar)]) });
assert.deepEqual(girado.lados.map(l => l.nome), vias.nomes.slice(0, 4));
assert(girado.lados.every(l => l.giro >= -90 && l.giro <= 90));
console.log('Impressão: ruas de todas as laterais, orientação e números separados OK');
