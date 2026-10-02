/*
 * Busca do atlas no navegador: o mesmo casamento do servidor
 * (services/entomologia_atlas_search.py), aplicado a um índice já normalizado.
 * Assim o resultado aparece a cada tecla, sem ida ao servidor.
 *
 * Sem "lookbehind" de regex de propósito: iPhones com Safari anterior ao 16.4
 * não o suportam e o script inteiro deixaria de carregar.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SfaAtlasSearchModel = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  const LIMIT = 80;
  const KINDS = 'rua|avenida|alameda|travessa';
  const PHRASE = new RegExp('\\b(?:' + KINDS + '|casa) \\d+[a-z]?\\b', 'g');
  const ONES = 'um dois tres quatro cinco seis sete oito nove'.split(' ');
  const SMALL = 'um dois tres quatro cinco seis sete oito nove dez onze doze treze quatorze quinze'.split(' ');
  const BIG = [[16, 'dezesseis'], [17, 'dezessete'], [18, 'dezoito'], [19, 'dezenove'], [20, 'vinte'],
               [30, 'trinta'], [100, 'cem'], [102, 'cento e dois']];

  // Mesma ordem de substituições de search_text() no servidor.
  const REPLACEMENTS = [];
  [[20, 'vinte'], [30, 'trinta']].forEach(([ten, prefix]) => ONES.forEach((word, i) => {
    REPLACEMENTS.push([new RegExp('\\b(' + KINDS + ') ' + prefix + ' e ' + word + '\\b', 'g'), (m, kind) => kind + ' ' + (ten + i + 1)]);
  }));
  const ABBREVIATION = [/\bav\.?\s/g, 'avenida '];
  const AFTER_ABBREVIATION = [];
  SMALL.forEach((word, i) => AFTER_ABBREVIATION.push([new RegExp('\\b(' + KINDS + ') ' + word + '\\b', 'g'), (m, kind) => kind + ' ' + (i + 1)]));
  BIG.forEach(([n, word]) => AFTER_ABBREVIATION.push([new RegExp('\\b(' + KINDS + ') ' + word + '\\b', 'g'), (m, kind) => kind + ' ' + n]));
  const ZEROS = [new RegExp('\\b(' + KINDS + '|casa) 0*(\\d+)\\b', 'g'), (m, kind, digits) => kind + ' ' + (digits.replace(/^0+(?=\d)/, '') || '0')];

  function normalize(value) {
    return String(value == null ? '' : value).normalize('NFKD').replace(/[̀-ͯ]/g, '').trim().toLowerCase();
  }

  function searchText(value) {
    let text = normalize(value);
    REPLACEMENTS.forEach(([re, fn]) => { text = text.replace(re, fn); });
    text = text.replace(ABBREVIATION[0], ABBREVIATION[1]);
    AFTER_ABBREVIATION.forEach(([re, fn]) => { text = text.replace(re, fn); });
    return text.replace(ZEROS[0], ZEROS[1]);
  }

  const isDigit = ch => ch !== undefined && ch >= '0' && ch <= '9';
  const isWord = ch => ch !== undefined && (isDigit(ch) || ch === '_' || ch.toLowerCase() !== ch.toUpperCase());

  // Equivale a (?<!X)needle(?!X), onde X é a classe testada por `edge`.
  function containsBounded(hay, needle, edge) {
    let from = 0;
    for (;;) {
      const at = hay.indexOf(needle, from);
      if (at < 0) return false;
      if (!edge(hay[at - 1]) && !edge(hay[at + needle.length])) return true;
      from = at + 1;
    }
  }

  // Interpreta o texto digitado como o servidor: expressões "rua 12" e demais palavras.
  function parse(query) {
    let q = searchText(query);
    if (!q || q.length > 240) return null;
    q = q.replace(ABBREVIATION[0], ABBREVIATION[1]);
    const phrases = q.match(PHRASE) || [];
    const tokens = q.replace(PHRASE, ' ').replace(/,/g, ' ').split(/\s+/).filter(Boolean);
    return {
      phrases,
      words: tokens.filter(t => !/^\d+$/.test(t)),
      digits: tokens.filter(t => /^\d+$/.test(t)),
    };
  }

  function matches(hay, parsed) {
    for (const p of parsed.phrases) if (!containsBounded(hay, p, isWord)) return false;
    for (const t of parsed.digits) if (!containsBounded(hay, t, isDigit)) return false;
    for (const t of parsed.words) if (hay.indexOf(t) < 0) return false;
    return true;
  }

  /*
   * Índice vindo do servidor: {layers:[{id,title}], entries:[[layer, id, name, address, hay,
   * kind, x, y, bbox, cadastreRef, street], ...]}. Devolve as entradas que casam, com os
   * posicionados primeiro e no máximo `limit`, como a busca do servidor. Trechos de uma mesma
   * rua (mesma camada e mesmo nome normalizado, campo `street`) viram um resultado só.
   */
  function search(index, query, limit) {
    const parsed = parse(query);
    if (!parsed) return [];
    const max = limit || LIMIT, placed = [], unplaced = [], streets = new Set();
    for (let i = 0; i < index.entries.length && placed.length < max; i++) {
      const e = index.entries[i];
      if (!matches(e[4], parsed)) continue;
      if (e[10] !== null && e[10] !== undefined) {
        const key = e[0] + '|' + e[10];
        if (streets.has(key)) continue;
        streets.add(key);
      }
      (e[5] ? placed : unplaced).push(e);
    }
    return placed.concat(unplaced).slice(0, max);
  }

  return {LIMIT, normalize, searchText, parse, matches, search, containsBounded};
});
