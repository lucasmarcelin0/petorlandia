/*
 * iReverse · núcleo do protótipo de certificadora de créditos de logística reversa.
 *
 * Tudo aqui é lógica pura (sem DOM), para rodar no navegador e no Node (testes).
 *
 * Modelo: event sourcing. A única fonte de verdade é o livro-razão — uma lista
 * de eventos encadeados por SHA-256 (cada evento carrega o hash do anterior).
 * O estado (participantes, notas, certificados) é sempre reconstruído
 * reaplicando os eventos. Adulterar qualquer evento quebra a cadeia e a
 * reconstrução é recusada.
 *
 * Base legal usada nas regras (redação original consultada; conferir texto
 * consolidado antes de uso real):
 *  - Lei 12.305/2010 (PNRS), arts. 31 e 33 — responsabilidade compartilhada e
 *    logística reversa obrigatória.
 *  - Decreto 10.936/2022 — regulamenta a PNRS (SINIR, MTR).
 *  - Decreto 11.413/2023 — CCRLR, CERE e Certificado de Crédito de Massa Futura:
 *      art. 15 §1º I  veracidade, autenticidade, unicidade e não colidência da NF-e
 *      art. 15 §1º II recebimento confirmado por certificado de destinação final (MTR/SINIR)
 *      art. 15 §4º    só NF-e do ano fiscal corrente ou do imediatamente anterior
 *      art. 15 §6º / art. 17  esgotar primeiro os resultados das organizações de catadores
 *      art. 15 §7º    NF-e de catadores aceita na venda a recicladora ou atacadista
 *      art. 15 §8º    NF-e de atacadista só quando vendida a empresa recicladora
 *      art. 23        a entidade gestora emite os certificados
 *      art. 29 V      verificador preserva unicidade e não colidência das massas
 *      art. 29 §1º    verificador não pode comercializar, emitir, comprar ou vender CCRLR
 *  - Decreto 12.688/2025 — sistema de logística reversa de embalagens plásticas.
 *  - Portaria GM/MMA 1.778/2026 — Sisrev-BR (monitoramento e rastreabilidade no SINIR).
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    root.IReverseCore = api;
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ── SHA-256 síncrono (mesmo resultado no navegador e no Node) ────────────
  const SHA_K = [];
  const SHA_H0 = [];
  (function initSha() {
    let n = 2;
    while (SHA_K.length < 64) {
      let primo = true;
      for (let d = 2; d * d <= n; d++) {
        if (n % d === 0) { primo = false; break; }
      }
      if (primo) {
        if (SHA_H0.length < 8) {
          SHA_H0.push((Math.pow(n, 1 / 2) * 0x100000000) | 0);
        }
        SHA_K.push((Math.pow(n, 1 / 3) * 0x100000000) | 0);
      }
      n++;
    }
  })();

  function utf8(str) {
    if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(str);
    const esc = unescape(encodeURIComponent(str));
    const out = new Uint8Array(esc.length);
    for (let i = 0; i < esc.length; i++) out[i] = esc.charCodeAt(i);
    return out;
  }

  function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }

  function sha256(str) {
    const bytes = utf8(String(str));
    const len = bytes.length;
    const total = ((len + 9 + 63) >> 6) << 6;
    const buf = new Uint8Array(total);
    buf.set(bytes);
    buf[len] = 0x80;
    const dv = new DataView(buf.buffer);
    dv.setUint32(total - 8, Math.floor(len / 0x20000000));
    dv.setUint32(total - 4, (len << 3) >>> 0);
    const h = SHA_H0.slice();
    const w = new Int32Array(64);
    for (let off = 0; off < total; off += 64) {
      for (let i = 0; i < 16; i++) w[i] = dv.getInt32(off + i * 4);
      for (let i = 16; i < 64; i++) {
        const a = w[i - 15];
        const b = w[i - 2];
        const s0 = rotr(a, 7) ^ rotr(a, 18) ^ (a >>> 3);
        const s1 = rotr(b, 17) ^ rotr(b, 19) ^ (b >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      let [a, b, c, d, e, f, g, hh] = h;
      for (let i = 0; i < 64; i++) {
        const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        const ch = (e & f) ^ (~e & g);
        const t1 = (hh + S1 + ch + SHA_K[i] + w[i]) | 0;
        const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        const mj = (a & b) ^ (a & c) ^ (b & c);
        const t2 = (S0 + mj) | 0;
        hh = g; g = f; f = e; e = (d + t1) | 0;
        d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      h[0] = (h[0] + a) | 0; h[1] = (h[1] + b) | 0;
      h[2] = (h[2] + c) | 0; h[3] = (h[3] + d) | 0;
      h[4] = (h[4] + e) | 0; h[5] = (h[5] + f) | 0;
      h[6] = (h[6] + g) | 0; h[7] = (h[7] + hh) | 0;
    }
    return h.map((x) => (x >>> 0).toString(16).padStart(8, '0')).join('');
  }

  // JSON canônico: chaves ordenadas, para o hash não depender da ordem.
  function canonico(valor) {
    if (valor === null || typeof valor !== 'object') return JSON.stringify(valor);
    if (Array.isArray(valor)) return '[' + valor.map(canonico).join(',') + ']';
    const chaves = Object.keys(valor).filter((k) => valor[k] !== undefined).sort();
    return '{' + chaves.map((k) => JSON.stringify(k) + ':' + canonico(valor[k])).join(',') + '}';
  }

  // ── Documentos (CPF, CNPJ numérico e alfanumérico, chave de NF-e) ──────────
  // A partir de julho/2026 a Receita passou a emitir CNPJ alfanumérico
  // (IN RFB 2.229/2024): 12 posições [0-9A-Z] + 2 DVs numéricos, com valor de
  // cada caractere = código ASCII − 48. A mesma regra vale dentro da chave.
  function limparDoc(s) {
    return String(s || '').toUpperCase().replace(/[^0-9A-Z]/g, '');
  }

  function valorChar(c) { return c.charCodeAt(0) - 48; }

  function validarCPF(doc) {
    const s = limparDoc(doc);
    if (!/^\d{11}$/.test(s) || /^(\d)\1{10}$/.test(s)) return false;
    for (let t = 9; t < 11; t++) {
      let soma = 0;
      for (let i = 0; i < t; i++) soma += Number(s[i]) * (t + 1 - i);
      const dv = ((soma * 10) % 11) % 10;
      if (dv !== Number(s[t])) return false;
    }
    return true;
  }

  function dvsCNPJ(base12) {
    const pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
    const pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
    const calc = (txt, pesos) => {
      let soma = 0;
      for (let i = 0; i < pesos.length; i++) soma += valorChar(txt[i]) * pesos[i];
      const r = soma % 11;
      return r < 2 ? 0 : 11 - r;
    };
    const d1 = calc(base12, pesos1);
    const d2 = calc(base12 + d1, pesos2);
    return '' + d1 + d2;
  }

  function validarCNPJ(doc) {
    const s = limparDoc(doc);
    if (!/^[0-9A-Z]{12}\d{2}$/.test(s) || /^(\d)\1{13}$/.test(s)) return false;
    return dvsCNPJ(s.slice(0, 12)) === s.slice(12);
  }

  function gerarCPF(base9) {
    let s = String(base9).replace(/\D/g, '').padStart(9, '0').slice(0, 9);
    for (let t = 9; t < 11; t++) {
      let soma = 0;
      for (let i = 0; i < t; i++) soma += Number(s[i]) * (t + 1 - i);
      s += ((soma * 10) % 11) % 10;
    }
    return s;
  }

  function gerarCNPJ(base12) {
    const b = limparDoc(base12).padStart(12, '0').slice(0, 12);
    return b + dvsCNPJ(b);
  }

  function formatarDoc(doc) {
    const s = limparDoc(doc);
    if (s.length === 11) return s.replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, '$1.$2.$3-$4');
    if (s.length === 14) return s.replace(/^(.{2})(.{3})(.{3})(.{4})(.{2})$/, '$1.$2.$3/$4-$5');
    return s;
  }

  // LGPD: CPF de catador individual não aparece inteiro em telas públicas.
  function mascararDoc(doc) {
    const s = limparDoc(doc);
    if (s.length === 11) return '***.' + s.slice(3, 6) + '.' + s.slice(6, 9) + '-**';
    return formatarDoc(s);
  }

  const UF_POR_CODIGO = {
    11: 'RO', 12: 'AC', 13: 'AM', 14: 'RR', 15: 'PA', 16: 'AP', 17: 'TO',
    21: 'MA', 22: 'PI', 23: 'CE', 24: 'RN', 25: 'PB', 26: 'PE', 27: 'AL', 28: 'SE', 29: 'BA',
    31: 'MG', 32: 'ES', 33: 'RJ', 35: 'SP', 41: 'PR', 42: 'SC', 43: 'RS',
    50: 'MS', 51: 'MT', 52: 'GO', 53: 'DF',
  };
  const CODIGO_POR_UF = Object.fromEntries(
    Object.entries(UF_POR_CODIGO).map(([c, uf]) => [uf, Number(c)])
  );

  function dvChave(base43) {
    let soma = 0;
    let peso = 2;
    for (let i = base43.length - 1; i >= 0; i--) {
      soma += valorChar(base43[i]) * peso;
      peso = peso === 9 ? 2 : peso + 1;
    }
    const r = soma % 11;
    return r < 2 ? 0 : 11 - r;
  }

  // Layout: cUF(2) AAMM(4) CNPJ(14) mod(2) série(3) nNF(9) tpEmis(1) cNF(8) cDV(1)
  function analisarChave(chave) {
    const s = limparDoc(chave);
    const erros = [];
    if (!/^\d{6}[0-9A-Z]{12}\d{26}$/.test(s)) {
      erros.push('A chave de acesso deve ter 44 posições (só números; o CNPJ alfanumérico é aceito).');
      return { valida: false, erros, chave: s };
    }
    const info = {
      chave: s,
      cUF: Number(s.slice(0, 2)),
      ano: 2000 + Number(s.slice(2, 4)),
      mes: Number(s.slice(4, 6)),
      cnpj: s.slice(6, 20),
      modelo: s.slice(20, 22),
      serie: s.slice(22, 25),
      numero: s.slice(25, 34),
      tpEmis: s.slice(34, 35),
      cNF: s.slice(35, 43),
      dv: Number(s.slice(43)),
    };
    info.uf = UF_POR_CODIGO[info.cUF] || null;
    if (!info.uf) erros.push('Código de UF da chave inexistente (' + info.cUF + ').');
    if (info.mes < 1 || info.mes > 12) erros.push('Mês de emissão da chave inválido.');
    if (info.modelo !== '55') erros.push('Só NF-e modelo 55 é aceita (a chave indica modelo ' + info.modelo + ').');
    if (!validarCNPJ(info.cnpj)) erros.push('O CNPJ embutido na chave tem dígito verificador inválido.');
    if (dvChave(s.slice(0, 43)) !== info.dv) erros.push('Dígito verificador da chave não confere (chave digitada errada ou forjada).');
    info.valida = erros.length === 0;
    info.erros = erros;
    return info;
  }

  function gerarChave({ uf, ano, mes, cnpj, serie, numero, codigo, tpEmis }) {
    const cUF = String(CODIGO_POR_UF[uf] || 35).padStart(2, '0');
    const aamm = String(ano % 100).padStart(2, '0') + String(mes).padStart(2, '0');
    const base = cUF + aamm + limparDoc(cnpj).padStart(14, '0') + '55' +
      String(serie || 1).padStart(3, '0') + String(numero || 1).padStart(9, '0') +
      String(tpEmis || 1) + String(codigo || 12345678).padStart(8, '0').slice(0, 8);
    return base + dvChave(base);
  }

  // ── Catálogos ─────────────────────────────────────────────────────────────
  const MATERIAIS = {
    papel: 'Papel e papelão',
    plastico: 'Plástico',
    vidro: 'Vidro',
    metal: 'Metal (aço e alumínio)',
    multicamada: 'Embalagem cartonada / multicamada',
  };

  const TIPOS = {
    catador: { rotulo: 'Catador(a) individual', doc: 'CPF', emite: true, organizacaoCatadores: true },
    cooperativa: { rotulo: 'Cooperativa / associação de catadores', doc: 'CNPJ', emite: true, organizacaoCatadores: true },
    operador: { rotulo: 'Operador / ponto de entrega (PEV)', doc: 'CNPJ', emite: true },
    atacadista: { rotulo: 'Atacadista / ferro-velho', doc: 'CNPJ', emite: true, recebe: true },
    reciclador: { rotulo: 'Indústria recicladora', doc: 'CNPJ', recebe: true },
    entidade: { rotulo: 'Entidade gestora', doc: 'CNPJ' },
    verificador: { rotulo: 'Verificador de resultados', doc: 'CNPJ' },
    empresa: { rotulo: 'Empresa aderente (fabricante, importador, distribuidor, comerciante)', doc: 'CNPJ' },
  };

  // Limites de plausibilidade: não bloqueiam, mas geram alerta para auditoria.
  const LIMITES = {
    catadorKgPorNota: 3000,
    residualAtacadistaAlerta: 0.5,
  };

  // ── Estado ──────────────────────────────────────────────────────────────
  function estadoVazio() {
    return { participantes: {}, ordemParticipantes: [], nfes: {}, ordemNfes: [], certificados: {}, ordemCertificados: [] };
  }

  function kgParaG(kg) {
    const n = Number(String(kg).replace(',', '.'));
    if (!isFinite(n)) return NaN;
    return Math.round(n * 1000);
  }

  function aplicar(estado, ev) {
    const d = ev.dados;
    switch (ev.tipo) {
      case 'PARTICIPANTE_CADASTRADO':
        estado.participantes[d.id] = Object.assign({}, d, { cadastradoEm: ev.ts });
        estado.ordemParticipantes.push(d.id);
        break;
      case 'NFE_REGISTRADA':
        estado.nfes[d.chave] = Object.assign({}, d, {
          status: 'registrada', registradaEm: ev.ts, registradaPor: ev.ator, alertas: d.alertas || [],
        });
        estado.ordemNfes.push(d.chave);
        break;
      case 'NFE_RECEBIMENTO_CONFIRMADO': {
        const nf = estado.nfes[d.chave];
        nf.recebimento = { mtr: d.mtr, cdf: d.cdf, massaG: d.massaG, data: d.data, por: ev.ator };
        if (nf.status === 'registrada') nf.status = 'recebida';
        break;
      }
      case 'NFE_HOMOLOGADA': {
        const nf = estado.nfes[d.chave];
        nf.status = 'homologada';
        nf.homologacao = { verificadorId: ev.ator, consulta: d.consulta, em: ev.ts };
        break;
      }
      case 'NFE_REJEITADA': {
        const nf = estado.nfes[d.chave];
        nf.status = 'rejeitada';
        nf.rejeicao = { motivo: d.motivo, por: ev.ator, em: ev.ts };
        break;
      }
      case 'CERTIFICADO_EMITIDO':
        estado.certificados[d.codigo] = Object.assign({}, d, { status: 'emitido', emitidoEm: ev.ts, emitidoPor: ev.ator });
        estado.ordemCertificados.push(d.codigo);
        break;
      case 'CERTIFICADO_APOSENTADO': {
        const c = estado.certificados[d.codigo];
        c.status = 'aposentado';
        c.aposentadoria = { sistema: d.sistema, protocolo: d.protocolo, em: ev.ts, por: ev.ator };
        break;
      }
      case 'CERTIFICADO_CANCELADO': {
        const c = estado.certificados[d.codigo];
        c.status = 'cancelado';
        c.cancelamento = { motivo: d.motivo, em: ev.ts, por: ev.ator };
        break;
      }
      default:
        throw new Error('Evento desconhecido: ' + ev.tipo);
    }
  }

  function hashEvento(ev) {
    return sha256(canonico({ seq: ev.seq, ts: ev.ts, tipo: ev.tipo, ator: ev.ator, dados: ev.dados, anterior: ev.anterior }));
  }

  const GENESIS = '0'.repeat(64);

  function verificarCadeia(eventos) {
    let anterior = GENESIS;
    for (let i = 0; i < eventos.length; i++) {
      const ev = eventos[i];
      if (!ev || ev.seq !== i + 1) {
        return { ok: false, quebraEm: i + 1, motivo: 'Sequência de eventos fora de ordem ou com lacuna.' };
      }
      if (ev.anterior !== anterior) {
        return { ok: false, quebraEm: ev.seq, motivo: 'O evento não aponta para o hash do evento anterior (elo removido ou inserido).' };
      }
      if (hashEvento(ev) !== ev.hash) {
        return { ok: false, quebraEm: ev.seq, motivo: 'O conteúdo do evento foi alterado depois de gravado (hash não confere).' };
      }
      anterior = ev.hash;
    }
    return { ok: true, total: eventos.length, ultimoHash: anterior };
  }

  function raizCNPJ(doc) {
    const s = limparDoc(doc);
    return s.length === 14 ? s.slice(0, 8) : s;
  }

  function anoDe(dataIso) { return Number(String(dataIso).slice(0, 4)); }

  // Data do dia no fuso de quem usa (mesma regra do PetDateBR.todayIso).
  // Em UTC, das 21h à meia-noite no Brasil, "hoje" já seria amanhã.
  function dataLocalIso(data) {
    const d = data instanceof Date ? data : new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  // ── Registro (comandos validados → eventos) ───────────────────────────────
  class Registro {
    constructor(opcoes) {
      const o = opcoes || {};
      this.agora = o.agora || (() => new Date());
      this.eventos = [];
      this.estado = estadoVazio();
    }

    static deEventos(eventos, opcoes) {
      const lista = Array.isArray(eventos) ? eventos : [];
      const integridade = verificarCadeia(lista);
      const reg = new Registro(opcoes);
      if (!integridade.ok) return { registro: reg, integridade };
      for (const ev of lista) {
        aplicar(reg.estado, ev);
        reg.eventos.push(ev);
      }
      return { registro: reg, integridade };
    }

    _gravar(tipo, ator, dados) {
      const ev = {
        seq: this.eventos.length + 1,
        ts: this.agora().toISOString(),
        tipo,
        ator: ator || null,
        dados: JSON.parse(JSON.stringify(dados)),
        anterior: this.eventos.length ? this.eventos[this.eventos.length - 1].hash : GENESIS,
      };
      ev.hash = hashEvento(ev);
      aplicar(this.estado, ev);
      this.eventos.push(ev);
      return ev;
    }

    verificarIntegridade() { return verificarCadeia(this.eventos); }

    participante(id) { return this.estado.participantes[id] || null; }

    participantesPorTipo(tipo) {
      return this.estado.ordemParticipantes.map((id) => this.estado.participantes[id]).filter((p) => !tipo || p.tipo === tipo);
    }

    _ator(atorId, tiposPermitidos, acao) {
      const p = this.participante(atorId);
      if (!p) return { erro: 'Escolha, no topo da página, quem está fazendo esta ação.' };
      if (tiposPermitidos && !tiposPermitidos.includes(p.tipo)) {
        const nomes = tiposPermitidos.map((t) => TIPOS[t].rotulo.toLowerCase()).join(' ou ');
        return { erro: 'Só ' + nomes + ' pode ' + acao + '. Você está atuando como ' + TIPOS[p.tipo].rotulo.toLowerCase() + '.' };
      }
      return { p };
    }

    // 1. Elos da cadeia ------------------------------------------------------
    cadastrarParticipante(dados) {
      const erros = [];
      const tipo = dados.tipo;
      const def = TIPOS[tipo];
      if (!def) return { ok: false, erros: ['Tipo de participante inválido.'] };
      const nome = String(dados.nome || '').trim();
      if (nome.length < 3) erros.push('Informe o nome ou a razão social.');
      const doc = limparDoc(dados.doc);
      if (def.doc === 'CPF' && !validarCPF(doc)) erros.push('CPF inválido.');
      if (def.doc === 'CNPJ' && !validarCNPJ(doc)) erros.push('CNPJ inválido.');
      const uf = String(dados.uf || '').toUpperCase();
      if (!CODIGO_POR_UF[uf]) erros.push('UF inválida.');
      const existentes = this.participantesPorTipo();
      if (existentes.some((p) => p.doc === doc)) erros.push('Este documento já está cadastrado (um documento, um cadastro).');
      // Art. 29 §1º: o verificador não pode ter interesse comercial nos créditos.
      if (def.doc === 'CNPJ') {
        const raiz = raizCNPJ(doc);
        const mesmoGrupo = existentes.filter((p) => p.doc.length === 14 && raizCNPJ(p.doc) === raiz);
        if (tipo === 'verificador' && mesmoGrupo.some((p) => p.tipo !== 'verificador')) {
          erros.push('Conflito de interesses: este grupo econômico (mesma raiz de CNPJ) já atua na cadeia. O verificador precisa ser independente (Decreto 11.413/2023, art. 29 §1º).');
        }
        if (tipo !== 'verificador' && mesmoGrupo.some((p) => p.tipo === 'verificador')) {
          erros.push('Conflito de interesses: a mesma raiz de CNPJ já é verificador de resultados e não pode atuar em outro elo (art. 29 §1º).');
        }
      }
      let capacidadeG = null;
      if (tipo === 'reciclador' && dados.capacidadeKgMes) {
        capacidadeG = kgParaG(dados.capacidadeKgMes);
        if (!(capacidadeG > 0)) erros.push('Capacidade mensal inválida.');
      }
      if (erros.length) return { ok: false, erros };
      const id = 'P' + String(this.estado.ordemParticipantes.length + 1).padStart(3, '0');
      const ev = this._gravar('PARTICIPANTE_CADASTRADO', null, {
        id, tipo, nome, doc, uf, municipio: String(dados.municipio || '').trim(), capacidadeG,
      });
      return { ok: true, evento: ev, id };
    }

    // 2. Notas fiscais -------------------------------------------------------
    vinculadoG(chaveOrigem, ignorarChave) {
      let total = 0;
      for (const ch of this.estado.ordemNfes) {
        const nf = this.estado.nfes[ch];
        if (ch === ignorarChave || nf.status === 'rejeitada' || !nf.origens) continue;
        for (const o of nf.origens) if (o.chave === chaveOrigem) total += o.massaG;
      }
      return total;
    }

    origensDisponiveis(atacadistaId, material) {
      return this.estado.ordemNfes
        .map((ch) => this.estado.nfes[ch])
        .filter((nf) => nf.destinatarioId === atacadistaId && nf.status !== 'rejeitada' && (!material || nf.material === material))
        .map((nf) => ({ nf, livreG: nf.massaG - this.vinculadoG(nf.chave) }))
        .filter((x) => x.livreG > 0);
    }

    registrarNFe(atorId, dados) {
      const erros = [];
      const alertas = [];
      const info = analisarChave(dados.chave);
      if (!info.valida) return { ok: false, erros: info.erros };
      const chave = info.chave;
      // Unicidade (art. 15 §1º I): a chave só entra uma vez, para sempre.
      // Inclusive notas rejeitadas: uma NF cancelada não "volta" com outra roupa.
      if (this.estado.nfes[chave]) {
        return { ok: false, erros: ['Dupla contagem bloqueada: esta NF-e já está no registro (situação: ' + this.estado.nfes[chave].status + '). Cada chave de acesso só pode lastrear créditos uma única vez.'] };
      }
      const emit = this.participante(dados.emitenteId);
      const dest = this.participante(dados.destinatarioId);
      if (!emit) erros.push('Escolha o emitente da nota.');
      if (!dest) erros.push('Escolha o destinatário da nota.');
      if (erros.length) return { ok: false, erros };

      const atuacao = this._ator(atorId, null, 'registrar notas');
      if (atuacao.erro) return { ok: false, erros: [atuacao.erro] };
      if (atorId !== emit.id && atuacao.p.tipo !== 'entidade') {
        erros.push('A nota deve ser registrada pelo próprio emitente ou pela entidade gestora.');
      }
      if (!TIPOS[emit.tipo].emite) erros.push(TIPOS[emit.tipo].rotulo + ' não emite nota de venda de material reciclável neste sistema.');
      if (!TIPOS[dest.tipo].recebe) erros.push('O destinatário deve ser indústria recicladora ou atacadista.');
      if (emit.id === dest.id) erros.push('Emitente e destinatário não podem ser o mesmo participante.');
      if (emit.tipo === 'atacadista' && dest.tipo !== 'reciclador') {
        erros.push('NF-e de atacadista só vale quando a venda é para indústria recicladora (Decreto 11.413/2023, art. 15 §8º).');
      }
      if (!MATERIAIS[dados.material]) erros.push('Escolha o material.');
      const massaG = kgParaG(dados.massaKg);
      if (!(massaG > 0)) erros.push('Informe a massa em kg (maior que zero).');

      const avulsa = Boolean(dados.avulsa);
      if (avulsa && emit.tipo !== 'catador') erros.push('NF-e avulsa (emitida pela SEFAZ) só se aplica a catador individual.');
      if (!avulsa && info.cnpj !== emit.doc) {
        erros.push('O CNPJ dentro da chave (' + formatarDoc(info.cnpj) + ') não é o do emitente informado. Nota de terceiro não pode ser apropriada.');
      }
      if (info.uf !== emit.uf) erros.push('A UF da chave (' + info.uf + ') não é a UF do emitente (' + emit.uf + ').');

      const data = String(dados.dataEmissao || '');
      if (!/^\d{4}-\d{2}-\d{2}$/.test(data)) {
        erros.push('Informe a data de emissão.');
      } else {
        if (Number(data.slice(0, 4)) !== info.ano || Number(data.slice(5, 7)) !== info.mes) {
          erros.push('A data de emissão não bate com o ano/mês gravado na chave (' + String(info.mes).padStart(2, '0') + '/' + info.ano + ').');
        }
        if (data > dataLocalIso(this.agora())) erros.push('Data de emissão no futuro.');
      }

      // Rastreabilidade atacadista → reciclador: as notas de compra que ele
      // revende ficam vinculadas, e a massa só é contada uma vez.
      let origens = [];
      if (emit.tipo === 'atacadista' && Array.isArray(dados.origens)) {
        const vistas = new Set();
        for (const o of dados.origens) {
          const kg = kgParaG(o.massaKg);
          if (!(kg > 0)) continue;
          const origem = this.estado.nfes[limparDoc(o.chave)];
          if (!origem) { erros.push('Nota de origem ' + o.chave + ' não está no registro.'); continue; }
          if (vistas.has(origem.chave)) { erros.push('A nota de origem ' + origem.chave + ' foi listada duas vezes.'); continue; }
          vistas.add(origem.chave);
          if (origem.status === 'rejeitada') erros.push('A nota de origem ' + origem.chave + ' foi rejeitada.');
          if (origem.destinatarioId !== emit.id) erros.push('A nota de origem ' + origem.chave + ' não foi vendida para este atacadista.');
          if (origem.material !== dados.material) erros.push('A nota de origem ' + origem.chave + ' é de outro material.');
          if (data && origem.dataEmissao > data) erros.push('A nota de origem ' + origem.chave + ' é posterior à revenda.');
          const livre = origem.massaG - this.vinculadoG(origem.chave);
          if (kg > livre) {
            erros.push('Não colidência: a nota de origem ' + origem.chave + ' só tem ' + (livre / 1000).toLocaleString('pt-BR') + ' kg ainda não repassados. A mesma massa não pode sair duas vezes do atacadista.');
          }
          origens.push({ chave: origem.chave, massaG: kg });
        }
        const somaOrigens = origens.reduce((s, o) => s + o.massaG, 0);
        if (somaOrigens > massaG) erros.push('A soma das notas de origem é maior que a massa desta nota.');
        const residual = massaG - somaOrigens;
        if (massaG > 0 && residual / massaG > LIMITES.residualAtacadistaAlerta) {
          alertas.push('Mais da metade da massa (' + Math.round((residual / massaG) * 100) + '%) não tem nota de origem rastreada no sistema. Auditar a procedência.');
        }
        const pendentes = this.origensDisponiveis(emit.id, dados.material).filter((x) => !vistas.has(x.nf.chave));
        if (pendentes.length && residual > 0) {
          alertas.push('Há notas de organizações de catadores vendidas a este atacadista ainda sem vínculo. A lei manda esgotar primeiro esses resultados (art. 15 §6º).');
        }
      }
      if (emit.tipo === 'catador' && massaG > LIMITES.catadorKgPorNota) {
        alertas.push('Massa acima de ' + LIMITES.catadorKgPorNota.toLocaleString('pt-BR') + ' kg em uma nota de catador individual. Conferir a plausibilidade.');
      }
      if (erros.length) return { ok: false, erros };

      const ev = this._gravar('NFE_REGISTRADA', atorId, {
        chave, emitenteId: emit.id, destinatarioId: dest.id, material: dados.material,
        massaG, dataEmissao: data, avulsa, origens, alertas,
      });
      return { ok: true, evento: ev, alertas };
    }

    confirmarRecebimento(atorId, chave, dados) {
      const nf = this.estado.nfes[limparDoc(chave)];
      if (!nf) return { ok: false, erros: ['Nota não encontrada.'] };
      const atuacao = this._ator(atorId, ['reciclador'], 'confirmar o recebimento (certificado de destinação final)');
      if (atuacao.erro) return { ok: false, erros: [atuacao.erro] };
      const erros = [];
      const alertas = [];
      if (nf.destinatarioId !== atorId) erros.push('Só a recicladora destinatária desta nota confirma o recebimento.');
      if (nf.status === 'rejeitada') erros.push('A nota foi rejeitada.');
      if (nf.recebimento) erros.push('O recebimento desta nota já foi confirmado.');
      const mtr = String((dados && dados.mtr) || '').trim();
      const cdf = String((dados && dados.cdf) || '').trim();
      if (mtr.length < 4) erros.push('Informe o número do MTR (Manifesto de Transporte de Resíduos, SINIR).');
      if (cdf.length < 4) erros.push('Informe o número do CDF (certificado de destinação final).');
      const usados = this.estado.ordemNfes.map((c) => this.estado.nfes[c]).filter((n) => n.recebimento);
      if (mtr && usados.some((n) => n.recebimento.mtr === mtr)) erros.push('Este MTR já comprovou outra nota. Um transporte, uma comprovação.');
      if (cdf && usados.some((n) => n.recebimento.cdf === cdf)) erros.push('Este CDF já comprovou outra nota.');
      const massaG = kgParaG(dados && dados.massaRecebidaKg);
      if (!(massaG > 0)) erros.push('Informe a massa efetivamente recebida, em kg.');
      if (massaG > nf.massaG) erros.push('A massa recebida não pode ser maior que a da nota. Diferenças a maior exigem outra nota.');
      const data = String((dados && dados.data) || '');
      if (!/^\d{4}-\d{2}-\d{2}$/.test(data)) erros.push('Informe a data do recebimento.');
      else if (data < nf.dataEmissao) erros.push('O recebimento não pode ser anterior à emissão da nota.');
      if (erros.length) return { ok: false, erros };
      const p = atuacao.p;
      if (p.capacidadeG) {
        const mes = data.slice(0, 7);
        const noMes = usados.filter((n) => n.destinatarioId === p.id && n.recebimento.data.slice(0, 7) === mes)
          .reduce((s, n) => s + n.recebimento.massaG, 0);
        if (noMes + massaG > p.capacidadeG) {
          alertas.push('A recicladora passa da capacidade mensal declarada em ' + mes + '. Sinal clássico de nota "fria": auditar.');
        }
      }
      if (massaG < nf.massaG) alertas.push('Recebido menos que o faturado: só a massa recebida vira crédito.');
      const ev = this._gravar('NFE_RECEBIMENTO_CONFIRMADO', atorId, { chave: nf.chave, mtr, cdf, massaG, data, alertas });
      return { ok: true, evento: ev, alertas };
    }

    homologarNFe(atorId, chave, consulta) {
      const nf = this.estado.nfes[limparDoc(chave)];
      if (!nf) return { ok: false, erros: ['Nota não encontrada.'] };
      const atuacao = this._ator(atorId, ['verificador'], 'homologar notas');
      if (atuacao.erro) return { ok: false, erros: [atuacao.erro] };
      const erros = [];
      if (nf.status === 'homologada') erros.push('A nota já está homologada.');
      if (nf.status === 'rejeitada') erros.push('A nota foi rejeitada.');
      const dest = this.participante(nf.destinatarioId);
      if (dest.tipo === 'reciclador' && !nf.recebimento) {
        erros.push('Falta o certificado de destinação final: a recicladora precisa confirmar o recebimento antes (art. 15 §1º II).');
      }
      const raizV = raizCNPJ(atuacao.p.doc);
      for (const id of [nf.emitenteId, nf.destinatarioId]) {
        const p = this.participante(id);
        if (p.doc.length === 14 && raizCNPJ(p.doc) === raizV) erros.push('Conflito de interesses: o verificador pertence ao grupo de um dos lados da nota.');
      }
      if (consulta !== 'autorizada') {
        erros.push('Confirme que a consulta à SEFAZ/Receita retornou a NF-e como autorizada, sem cancelamento nem denegação (art. 29 II).');
      }
      if (erros.length) return { ok: false, erros };
      const ev = this._gravar('NFE_HOMOLOGADA', atorId, { chave: nf.chave, consulta: 'autorizada' });
      return { ok: true, evento: ev };
    }

    rejeitarNFe(atorId, chave, motivo) {
      const nf = this.estado.nfes[limparDoc(chave)];
      if (!nf) return { ok: false, erros: ['Nota não encontrada.'] };
      const atuacao = this._ator(atorId, ['verificador'], 'rejeitar notas');
      if (atuacao.erro) return { ok: false, erros: [atuacao.erro] };
      if (nf.status === 'rejeitada') return { ok: false, erros: ['A nota já foi rejeitada.'] };
      const m = String(motivo || '').trim();
      if (m.length < 5) return { ok: false, erros: ['Descreva o motivo da rejeição.'] };
      const massas = this.massas();
      const afetadas = [nf.chave].concat((nf.origens || []).map((o) => o.chave));
      const comCredito = afetadas.filter((c) => massas[c] && massas[c].alocadoG > 0);
      if (comCredito.length) {
        return { ok: false, erros: ['Esta nota já lastreia certificados. Cancele-os primeiro, para não deixar crédito sem lastro.'] };
      }
      const ev = this._gravar('NFE_REJEITADA', atorId, { chave: nf.chave, motivo: m });
      return { ok: true, evento: ev };
    }

    // Massa elegível de cada nota, recalculada do zero a partir dos eventos.
    // Uma nota vendida ao atacadista só vira crédito através da revenda dele à
    // recicladora (que tem o CDF); a revenda fica só com o que não veio dessas
    // notas. Assim cada quilo é contado uma única vez na cadeia.
    massas() {
      const nfs = this.estado.nfes;
      const r = {};
      for (const ch of this.estado.ordemNfes) r[ch] = { elegivelG: 0, pendenteG: 0, alocadoG: 0, saldoG: 0 };
      for (const ch of this.estado.ordemNfes) {
        const nf = nfs[ch];
        if (nf.status !== 'homologada' || !nf.recebimento) continue;
        const somaOrigens = (nf.origens || []).reduce((s, o) => s + o.massaG, 0);
        const recebido = Math.min(nf.massaG, nf.recebimento.massaG);
        r[ch].elegivelG += Math.floor(((nf.massaG - somaOrigens) * recebido) / nf.massaG);
        for (const o of nf.origens || []) {
          const origem = nfs[o.chave];
          if (!origem || origem.status === 'rejeitada') continue;
          const parte = Math.floor((o.massaG * recebido) / nf.massaG);
          if (origem.status === 'homologada') r[o.chave].elegivelG += parte;
          else r[o.chave].pendenteG += parte;
        }
      }
      for (const cod of this.estado.ordemCertificados) {
        const c = this.estado.certificados[cod];
        if (c.status === 'cancelado') continue;
        for (const l of c.lastro) r[l.chave].alocadoG += l.massaG;
      }
      for (const ch of Object.keys(r)) r[ch].saldoG = r[ch].elegivelG - r[ch].alocadoG;
      return r;
    }

    // 3. Certificados --------------------------------------------------------
    simularLastro(material, anoMeta, massaG) {
      const massas = this.massas();
      const candidatas = this.estado.ordemNfes
        .map((ch) => this.estado.nfes[ch])
        .filter((nf) => nf.material === material && massas[nf.chave].saldoG > 0)
        .filter((nf) => {
          const ano = anoDe(nf.dataEmissao);
          return ano === anoMeta || ano === anoMeta - 1; // art. 15 §4º
        })
        .map((nf) => ({ nf, catadores: Boolean(TIPOS[this.participante(nf.emitenteId).tipo].organizacaoCatadores) }));
      // Prioridade legal às organizações de catadores (art. 15 §6º e art. 17),
      // depois as notas mais antigas (para não perderem a janela de validade).
      candidatas.sort((a, b) => (b.catadores - a.catadores) || a.nf.dataEmissao.localeCompare(b.nf.dataEmissao) || a.nf.chave.localeCompare(b.nf.chave));
      const disponivelG = candidatas.reduce((s, c) => s + massas[c.nf.chave].saldoG, 0);
      const lastro = [];
      let falta = massaG;
      for (const c of candidatas) {
        if (falta <= 0) break;
        const usa = Math.min(falta, massas[c.nf.chave].saldoG);
        lastro.push({ chave: c.nf.chave, massaG: usa, catadores: c.catadores });
        falta -= usa;
      }
      return { lastro, disponivelG, suficiente: falta <= 0 };
    }

    emitirCertificado(atorId, dados) {
      const atuacao = this._ator(atorId, ['entidade'], 'emitir certificados (art. 23)');
      if (atuacao.erro) return { ok: false, erros: [atuacao.erro] };
      const erros = [];
      const empresa = this.participante(dados.empresaId);
      if (!empresa || empresa.tipo !== 'empresa') erros.push('Escolha a empresa aderente que receberá o certificado.');
      if (!MATERIAIS[dados.material]) erros.push('Escolha o material.');
      const anoMeta = Number(dados.anoMeta);
      const anoAtual = this.agora().getFullYear();
      if (!Number.isInteger(anoMeta) || anoMeta > anoAtual || anoMeta < anoAtual - 2) {
        erros.push('Ano da meta deve estar entre ' + (anoAtual - 2) + ' e ' + anoAtual + '.');
      }
      const massaG = kgParaG(dados.massaKg);
      if (!(massaG > 0)) erros.push('Informe a massa do certificado em kg.');
      if (erros.length) return { ok: false, erros };
      const sim = this.simularLastro(dados.material, anoMeta, massaG);
      if (!sim.suficiente) {
        return { ok: false, erros: ['Lastro insuficiente: há ' + (sim.disponivelG / 1000).toLocaleString('pt-BR') + ' kg de ' + MATERIAIS[dados.material].toLowerCase() + ' homologados e livres em notas de ' + (anoMeta - 1) + '/' + anoMeta + '. Nada é emitido sem lastro integral.'] };
      }
      const lastro = sim.lastro.map((l) => ({ chave: l.chave, massaG: l.massaG }));
      const catadoresG = sim.lastro.filter((l) => l.catadores).reduce((s, l) => s + l.massaG, 0);
      const semente = sha256(canonico({ n: this.eventos.length, empresa: empresa.id, lastro, anoMeta }));
      const codigo = 'CCRLR-' + anoMeta + '-' + semente.slice(0, 10).toUpperCase();
      const ev = this._gravar('CERTIFICADO_EMITIDO', atorId, {
        codigo, tipo: 'CCRLR', empresaId: empresa.id, material: dados.material, anoMeta, massaG, lastro, catadoresG,
        finalidade: 'Comprovação de meta de logística reversa (PNRS). Não é crédito de carbono nem compensação de GEE.',
      });
      return { ok: true, evento: ev, codigo };
    }

    aposentarCertificado(atorId, codigo, dados) {
      const c = this.estado.certificados[String(codigo || '').trim().toUpperCase()];
      if (!c) return { ok: false, erros: ['Certificado não encontrado.'] };
      const atuacao = this._ator(atorId, ['empresa', 'entidade'], 'dar baixa em certificados');
      if (atuacao.erro) return { ok: false, erros: [atuacao.erro] };
      const erros = [];
      if (atuacao.p.tipo === 'empresa' && c.empresaId !== atorId) erros.push('Só a empresa titular pode dar baixa neste certificado.');
      if (c.status === 'aposentado') erros.push('Este certificado já foi usado para comprovar uma meta (' + c.aposentadoria.sistema + '). Não pode ser usado de novo em nenhum outro sistema, federal ou estadual.');
      if (c.status === 'cancelado') erros.push('Este certificado foi cancelado.');
      const sistema = String((dados && dados.sistema) || '').trim();
      if (sistema.length < 3) erros.push('Informe em qual sistema a meta foi comprovada (ex.: SINIR/Sisrev-BR, órgão estadual).');
      if (erros.length) return { ok: false, erros };
      const ev = this._gravar('CERTIFICADO_APOSENTADO', atorId, { codigo: c.codigo, sistema, protocolo: String((dados && dados.protocolo) || '').trim() });
      return { ok: true, evento: ev };
    }

    cancelarCertificado(atorId, codigo, motivo) {
      const c = this.estado.certificados[String(codigo || '').trim().toUpperCase()];
      if (!c) return { ok: false, erros: ['Certificado não encontrado.'] };
      const atuacao = this._ator(atorId, ['entidade'], 'cancelar certificados');
      if (atuacao.erro) return { ok: false, erros: [atuacao.erro] };
      if (c.status !== 'emitido') return { ok: false, erros: ['Só certificados ainda não usados podem ser cancelados.'] };
      const m = String(motivo || '').trim();
      if (m.length < 5) return { ok: false, erros: ['Descreva o motivo do cancelamento.'] };
      const ev = this._gravar('CERTIFICADO_CANCELADO', atorId, { codigo: c.codigo, motivo: m });
      return { ok: true, evento: ev };
    }

    consultarCertificado(codigo) {
      return this.estado.certificados[String(codigo || '').trim().toUpperCase()] || null;
    }

    resumo() {
      const m = this.massas();
      const nfs = this.estado.ordemNfes.map((c) => this.estado.nfes[c]);
      const certs = this.estado.ordemCertificados.map((c) => this.estado.certificados[c]);
      const soma = (arr, f) => arr.reduce((s, x) => s + f(x), 0);
      return {
        participantes: this.estado.ordemParticipantes.length,
        notas: nfs.length,
        notasHomologadas: nfs.filter((n) => n.status === 'homologada').length,
        notasRejeitadas: nfs.filter((n) => n.status === 'rejeitada').length,
        faturadoG: soma(nfs.filter((n) => n.status !== 'rejeitada'), (n) => n.massaG),
        elegivelG: soma(Object.values(m), (x) => x.elegivelG),
        alocadoG: soma(Object.values(m), (x) => x.alocadoG),
        saldoG: soma(Object.values(m), (x) => x.saldoG),
        certificados: certs.length,
        certificadosAtivos: certs.filter((c) => c.status === 'emitido').length,
        certificadosAposentados: certs.filter((c) => c.status === 'aposentado').length,
        alertas: soma(nfs, (n) => (n.alertas || []).length),
      };
    }
  }

  return {
    sha256, canonico, limparDoc, validarCPF, validarCNPJ, gerarCPF, gerarCNPJ, formatarDoc, mascararDoc,
    analisarChave, gerarChave, dvChave, verificarCadeia, Registro, MATERIAIS, TIPOS, LIMITES, UF_POR_CODIGO,
    CODIGO_POR_UF, kgParaG, dataLocalIso,
  };
});
