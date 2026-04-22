/* numero_extenso.js — utilitários pt-BR para formatar números e unidades
 * por extenso em prescrições veterinárias.
 *
 * Cobre números 0..9999 inteiros e decimais comuns (meio, um e meio, quarto,
 * etc.). Para valores fora desta faixa ou com muitas casas decimais, usa
 * fallback literal ("um vírgula dois cinco").
 *
 * Também expõe utilitários para pluralizar unidades farmacêuticas em pt-BR
 * (cápsula → cápsulas, gota → gotas, mL permanece mL).
 */
(function(global) {
  'use strict';

  const UNIDADES = [
    'zero', 'um', 'dois', 'três', 'quatro', 'cinco',
    'seis', 'sete', 'oito', 'nove'
  ];
  const DEZ_A_DEZENOVE = [
    'dez', 'onze', 'doze', 'treze', 'quatorze',
    'quinze', 'dezesseis', 'dezessete', 'dezoito', 'dezenove'
  ];
  const DEZENAS = [
    '', '', 'vinte', 'trinta', 'quarenta', 'cinquenta',
    'sessenta', 'setenta', 'oitenta', 'noventa'
  ];
  const CENTENAS = [
    '', 'cento', 'duzentos', 'trezentos', 'quatrocentos', 'quinhentos',
    'seiscentos', 'setecentos', 'oitocentos', 'novecentos'
  ];

  function inteiroPorExtenso(n) {
    n = Math.trunc(n);
    if (n === 0) return 'zero';
    if (n < 0) return 'menos ' + inteiroPorExtenso(-n);

    if (n >= 1000) {
      const milhares = Math.trunc(n / 1000);
      const resto = n % 1000;
      const prefixo = (milhares === 1) ? 'mil' : inteiroPorExtenso(milhares) + ' mil';
      if (resto === 0) return prefixo;
      const sep = (resto < 100 || (resto % 100 === 0)) ? ' e ' : ' ';
      return prefixo + sep + inteiroPorExtenso(resto);
    }

    if (n === 100) return 'cem';
    if (n >= 100) {
      const c = Math.trunc(n / 100);
      const resto = n % 100;
      if (resto === 0) return CENTENAS[c];
      return CENTENAS[c] + ' e ' + inteiroPorExtenso(resto);
    }

    if (n >= 20) {
      const d = Math.trunc(n / 10);
      const u = n % 10;
      if (u === 0) return DEZENAS[d];
      return DEZENAS[d] + ' e ' + UNIDADES[u];
    }

    if (n >= 10) return DEZ_A_DEZENOVE[n - 10];
    return UNIDADES[n];
  }

  // Casos decimais bonitos mais comuns em prescrição.
  const DECIMAIS_ESPECIAIS = {
    '0.25': 'um quarto',
    '0.5':  'meio',
    '0.75': 'três quartos',
    '1.25': 'um e um quarto',
    '1.5':  'um e meio',
    '1.75': 'um e três quartos',
    '2.5':  'dois e meio',
    '3.5':  'três e meio',
    '4.5':  'quatro e meio',
    '5.5':  'cinco e meio',
    '0.33': 'um terço',
    '0.66': 'dois terços',
    '0.67': 'dois terços',
  };

  function decimalPorExtenso(valor) {
    // Fallback literal: "um vírgula dois cinco"
    const txt = valor.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
    const [inteiro, dec] = txt.split('.');
    const parteInt = inteiroPorExtenso(parseInt(inteiro, 10));
    if (!dec) return parteInt;
    const digitos = dec.split('').map(d => UNIDADES[parseInt(d, 10)]).join(' ');
    return parteInt + ' vírgula ' + digitos;
  }

  /**
   * Converte um número pt-BR para extenso.
   * Ex: numeroPorExtenso(6)     → "seis"
   *     numeroPorExtenso(1.5)   → "um e meio"
   *     numeroPorExtenso(125)   → "cento e vinte e cinco"
   *     numeroPorExtenso(0.25)  → "um quarto"
   */
  function numeroPorExtenso(n) {
    if (typeof n !== 'number' || !isFinite(n)) return '';
    if (Number.isInteger(n)) return inteiroPorExtenso(n);

    // Normaliza pra 4 casas pra casar com a tabela de casos especiais.
    const chave = n.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
    if (DECIMAIS_ESPECIAIS[chave]) return DECIMAIS_ESPECIAIS[chave];

    // Inteiro + fração simples? (1,5 / 2,5 / ...)
    const inteiro = Math.trunc(n);
    const frac = Math.abs(n - inteiro);
    const chaveFrac = frac.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
    if (inteiro > 0 && DECIMAIS_ESPECIAIS[chaveFrac]) {
      return inteiroPorExtenso(inteiro) + ' e ' + DECIMAIS_ESPECIAIS[chaveFrac];
    }

    return decimalPorExtenso(n);
  }

  // Plurais farmacêuticos comuns em pt-BR.
  const PLURAIS_UNIDADE = {
    'cápsula': 'cápsulas',
    'comprimido': 'comprimidos',
    'drágea': 'drágeas',
    'tablete': 'tabletes',
    'petisco': 'petiscos',
    'supositório': 'supositórios',
    'pipeta': 'pipetas',
    'gota': 'gotas',
    'aplicação': 'aplicações',
    'dose': 'doses',
    'unidade': 'unidades',
    // mL, mg, UI, mcg etc. não flexionam
  };

  /**
   * Pluraliza uma unidade conforme a quantidade.
   * Ex: unidadePorQuantidade('cápsula', 2) → 'cápsulas'
   *     unidadePorQuantidade('mL', 10)      → 'mL'
   *     unidadePorQuantidade('cápsula', 1)  → 'cápsula'
   */
  function unidadePorQuantidade(unidade, quantidade) {
    if (!unidade) return '';
    const u = String(unidade).toLowerCase();
    const plural = Math.abs(quantidade) !== 1;
    if (!plural) return unidade;
    return PLURAIS_UNIDADE[u] || unidade;
  }

  // Versão por extenso da unidade (ex.: "mL" → "mililitros").
  const UNIDADE_POR_EXTENSO_SINGULAR = {
    'ml': 'mililitro', 'mg': 'miligrama', 'g': 'grama', 'mcg': 'micrograma',
    'ui': 'unidade internacional',
    'cápsula': 'cápsula', 'comprimido': 'comprimido',
    'drágea': 'drágea', 'tablete': 'tablete',
    'petisco': 'petisco', 'supositório': 'supositório',
    'pipeta': 'pipeta', 'gota': 'gota',
    'aplicação': 'aplicação', 'dose': 'dose', 'unidade': 'unidade',
  };
  const UNIDADE_POR_EXTENSO_PLURAL = {
    'ml': 'mililitros', 'mg': 'miligramas', 'g': 'gramas', 'mcg': 'microgramas',
    'ui': 'unidades internacionais',
    'cápsula': 'cápsulas', 'comprimido': 'comprimidos',
    'drágea': 'drágeas', 'tablete': 'tabletes',
    'petisco': 'petiscos', 'supositório': 'supositórios',
    'pipeta': 'pipetas', 'gota': 'gotas',
    'aplicação': 'aplicações', 'dose': 'doses', 'unidade': 'unidades',
  };

  function unidadePorExtenso(unidade, quantidade) {
    if (!unidade) return '';
    const u = String(unidade).toLowerCase();
    const plural = Math.abs(quantidade) !== 1;
    const tabela = plural ? UNIDADE_POR_EXTENSO_PLURAL : UNIDADE_POR_EXTENSO_SINGULAR;
    return tabela[u] || unidade;
  }

  /**
   * Formata um número pt-BR (vírgula decimal, sem trailing zeros).
   * Ex: formatarPtBR(1.5)   → '1,5'
   *     formatarPtBR(10)    → '10'
   *     formatarPtBR(0.125) → '0,125'
   */
  function formatarPtBR(n) {
    if (typeof n !== 'number' || !isFinite(n)) return '';
    if (Number.isInteger(n)) return String(n);
    // Até 3 casas, remove zeros no fim.
    let s = n.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
    return s.replace('.', ',');
  }

  /**
   * "6 cápsulas (seis cápsulas)" ou "1,5 mL (um e meio mililitros)".
   * Se for faixa (min != max), devolve "6–12 cápsulas (seis a doze cápsulas)".
   */
  function doseFormatada(quantidadeMin, quantidadeMax, unidade) {
    const qMin = Number(quantidadeMin);
    const qMax = (quantidadeMax == null) ? qMin : Number(quantidadeMax);
    if (!isFinite(qMin)) return '';

    const unidSingNum = unidadePorQuantidade(unidade, qMin);
    const unidSingExt = unidadePorExtenso(unidade, qMin);

    if (qMin === qMax) {
      const numTxt = formatarPtBR(qMin) + ' ' + unidSingNum;
      const extTxt = numeroPorExtenso(qMin) + ' ' + unidSingExt;
      return `${numTxt} (${extTxt})`;
    }

    const unidPlrExt = unidadePorExtenso(unidade, 2);
    const numTxt = `${formatarPtBR(qMin)}–${formatarPtBR(qMax)} ${unidadePorQuantidade(unidade, qMax)}`;
    const extTxt = `${numeroPorExtenso(qMin)} a ${numeroPorExtenso(qMax)} ${unidPlrExt}`;
    return `${numTxt} (${extTxt})`;
  }

  // "a cada 12 horas (doze horas)"
  function frequenciaFormatada(intervaloHoras) {
    const h = Number(intervaloHoras);
    if (!isFinite(h) || h <= 0) return '';
    const num = `a cada ${formatarPtBR(h)} ${h === 1 ? 'hora' : 'horas'}`;
    const ext = `${numeroPorExtenso(h)} ${h === 1 ? 'hora' : 'horas'}`;
    return `${num} (${ext})`;
  }

  // "por 7 dias (sete dias)"  /  "por 5–10 dias (cinco a dez dias)"
  function duracaoFormatada(minDias, maxDias, textoFallback) {
    const m = (minDias != null) ? Number(minDias) : null;
    const M = (maxDias != null) ? Number(maxDias) : null;
    if (m == null && M == null) return textoFallback || '';

    const mostrar = (v) => `${formatarPtBR(v)} ${v === 1 ? 'dia' : 'dias'}`;
    const extensoLabel = (v) => `${numeroPorExtenso(v)} ${v === 1 ? 'dia' : 'dias'}`;

    if (m && M && m !== M) {
      return `por ${formatarPtBR(m)}–${formatarPtBR(M)} dias (${numeroPorExtenso(m)} a ${numeroPorExtenso(M)} dias)`;
    }
    if (M && !m) {
      return `por até ${mostrar(M)} (até ${extensoLabel(M)})`;
    }
    if (m) {
      return `por ${mostrar(m)} (${extensoLabel(m)})`;
    }
    return textoFallback || '';
  }

  global.NumeroExtenso = {
    numeroPorExtenso,
    unidadePorQuantidade,
    unidadePorExtenso,
    formatarPtBR,
    doseFormatada,
    frequenciaFormatada,
    duracaoFormatada,
  };
})(typeof window !== 'undefined' ? window : this);
