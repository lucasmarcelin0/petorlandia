/* iReverse · interface do protótipo. As regras ficam em ireverse-core.js. */
(function () {
  'use strict';
  const C = window.IReverseCore;
  const CHAVE_STORAGE = 'ireverse.prototipo.v1';
  const CHAVE_ATOR = 'ireverse.prototipo.ator';

  const $ = (sel, raiz) => (raiz || document).querySelector(sel);
  const $$ = (sel, raiz) => Array.from((raiz || document).querySelectorAll(sel));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const kg = (g) => (Number(g || 0) / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 3 }) + ' kg';
  const hoje = () => new Date().toISOString().slice(0, 10);
  const diasAtras = (n) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);

  // ── Persistência (só neste navegador) ──────────────────────────────────
  function lerStorage(chave) {
    try { return window.localStorage.getItem(chave); } catch (e) { return null; }
  }
  function gravarStorage(chave, valor) {
    try { window.localStorage.setItem(chave, valor); return true; } catch (e) { return false; }
  }

  let reg = new C.Registro();
  let falhaCarga = null;

  function carregar() {
    const bruto = lerStorage(CHAVE_STORAGE);
    if (!bruto) return;
    try {
      const dados = JSON.parse(bruto);
      const r = C.Registro.deEventos(dados.eventos || []);
      if (!r.integridade.ok) {
        falhaCarga = r.integridade;
        return;
      }
      reg = r.registro;
    } catch (e) {
      falhaCarga = { quebraEm: '?', motivo: 'Arquivo local ilegível.' };
    }
  }

  function salvar() {
    if (falhaCarga) return; // nunca sobrescreve uma cadeia adulterada sem o usuário decidir
    gravarStorage(CHAVE_STORAGE, JSON.stringify({ versao: 1, eventos: reg.eventos }));
  }

  // ── Avisos ───────────────────────────────────────────────────────────
  function aviso(tipo, titulo, itens) {
    const el = document.createElement('div');
    el.className = 'aviso ' + tipo;
    el.innerHTML = '<b>' + esc(titulo) + '</b>' + (itens && itens.length ? '<ul>' + itens.map((i) => '<li>' + esc(i) + '</li>').join('') + '</ul>' : '');
    $('#avisos').appendChild(el);
    setTimeout(() => el.remove(), tipo === 'erro' ? 9000 : 5000);
  }

  function resultado(r, sucesso) {
    if (!r.ok) { aviso('erro', 'Bloqueado', r.erros); return false; }
    salvar();
    aviso('ok', sucesso);
    if (r.alertas && r.alertas.length) aviso('alerta', 'Alertas para auditoria', r.alertas);
    renderizar();
    return true;
  }

  // ── Ator atual ──────────────────────────────────────────────────────
  function atorId() { return $('#ator').value || null; }
  function ator() { return reg.participante(atorId()); }

  function nomeP(id) {
    const p = reg.participante(id);
    return p ? p.nome : '—';
  }

  function opcoes(lista, vazio) {
    return (vazio ? '<option value="">' + esc(vazio) + '</option>' : '') +
      lista.map((p) => '<option value="' + esc(p.id) + '">' + esc(p.nome) + ' · ' + esc(C.TIPOS[p.tipo].rotulo) + '</option>').join('');
  }

  function manterValor(sel, html) {
    const el = $(sel);
    const atual = el.value;
    el.innerHTML = html;
    if (atual && $$('option', el).some((o) => o.value === atual)) el.value = atual;
  }

  // ── Renderização ─────────────────────────────────────────────────────
  function renderizar() {
    const todos = reg.participantesPorTipo();
    const atorSalvo = $('#ator').value || lerStorage(CHAVE_ATOR) || '';
    $('#ator').innerHTML = '<option value="">— escolha quem você é —</option>' +
      Object.keys(C.TIPOS).map((tipo) => {
        const doTipo = todos.filter((p) => p.tipo === tipo);
        if (!doTipo.length) return '';
        return '<optgroup label="' + esc(C.TIPOS[tipo].rotulo) + '">' + doTipo.map((p) => '<option value="' + esc(p.id) + '">' + esc(p.nome) + '</option>').join('') + '</optgroup>';
      }).join('');
    if (atorSalvo && reg.participante(atorSalvo)) $('#ator').value = atorSalvo;

    renderBanner();
    renderKpis();
    renderParticipantes();
    renderFormNfe();
    renderNfes();
    renderFormCert();
    renderCerts();
    renderEventos();
  }

  function renderBanner() {
    if (falhaCarga) {
      $('#banner').innerHTML = '<div class="banner erro"><b>Livro-razão local adulterado.</b> O evento #' + esc(falhaCarga.quebraEm) + ' não confere: ' + esc(falhaCarga.motivo) + ' Nada foi carregado nem será gravado por cima. Use "Apagar tudo" para recomeçar ou importe uma cópia íntegra.</div>';
    } else if (!reg.eventos.length) {
      $('#banner').innerHTML = '<div class="banner info">Comece pelo <b>cenário de exemplo</b> no painel, ou cadastre os elos da cadeia à mão.</div>';
    } else {
      $('#banner').innerHTML = '';
    }
  }

  function renderKpis() {
    const r = reg.resumo();
    const integ = reg.verificarIntegridade();
    const itens = [
      [r.participantes, 'participantes'],
      [r.notas + ' (' + r.notasHomologadas + ' homolog.)', 'notas fiscais'],
      [kg(r.faturadoG), 'massa faturada'],
      [kg(r.elegivelG), 'massa elegível (recebida e homologada)'],
      [kg(r.alocadoG), 'em certificados'],
      [kg(r.saldoG), 'saldo livre para emitir'],
      [r.certificadosAtivos + ' / ' + r.certificadosAposentados, 'certificados ativos / baixados'],
      [integ.ok ? '✔ íntegro' : '✖ quebrado', integ.ok ? integ.total + ' eventos encadeados' : 'no evento #' + integ.quebraEm],
    ];
    $('#kpis').innerHTML = itens.map(([v, t]) => '<div class="kpi"><b>' + esc(v) + '</b><span>' + esc(t) + '</span></div>').join('');
  }

  function renderParticipantes() {
    const lista = reg.participantesPorTipo();
    $('#lista-participantes').innerHTML = lista.length ? lista.map((p) =>
      '<tr><td class="mono">' + esc(p.id) + '</td><td>' + esc(C.TIPOS[p.tipo].rotulo) + '</td><td>' + esc(p.nome) +
      (p.capacidadeG ? '<br><small class="alerta-txt" style="color:var(--muted)">capacidade ' + kg(p.capacidadeG) + '/mês</small>' : '') +
      '</td><td class="mono">' + esc(C.formatarDoc(p.doc)) + '</td><td>' + esc(p.uf) + (p.municipio ? ' · ' + esc(p.municipio) : '') + '</td></tr>'
    ).join('') : '<tr><td colspan="5" class="vazio">Nenhum participante ainda.</td></tr>';
  }

  function renderFormNfe() {
    const emissores = reg.participantesPorTipo().filter((p) => C.TIPOS[p.tipo].emite);
    const receptores = reg.participantesPorTipo().filter((p) => C.TIPOS[p.tipo].recebe);
    manterValor('#n-emitente', opcoes(emissores, emissores.length ? null : 'cadastre um emitente'));
    const a = ator();
    if (a && C.TIPOS[a.tipo].emite && !$('#n-emitente').dataset.tocado) $('#n-emitente').value = a.id;
    manterValor('#n-destinatario', opcoes(receptores, receptores.length ? null : 'cadastre uma recicladora'));
    atualizarOrigens();
  }

  function atualizarOrigens() {
    const emit = reg.participante($('#n-emitente').value);
    $('#n-avulsa-campo').hidden = !(emit && emit.tipo === 'catador');
    if (!emit || emit.tipo !== 'catador') $('#n-avulsa').checked = false;
    const caixa = $('#n-origens');
    if (!emit || emit.tipo !== 'atacadista') { caixa.hidden = true; $('#n-origens-lista').innerHTML = ''; return; }
    caixa.hidden = false;
    const disp = reg.origensDisponiveis(emit.id, $('#n-material').value);
    $('#n-origens-lista').innerHTML = disp.length ? '<div class="tabela"><table><thead><tr><th>Nota de compra</th><th>Vendida por</th><th class="num">Livre</th><th class="num">Nesta revenda (kg)</th></tr></thead><tbody>' +
      disp.map((x) => '<tr><td class="mono">' + esc(x.nf.chave) + '</td><td>' + esc(nomeP(x.nf.emitenteId)) + '</td><td class="num">' + kg(x.livreG) +
        '</td><td class="num"><input data-origem="' + esc(x.nf.chave) + '" inputmode="decimal" style="width:110px" placeholder="0"></td></tr>').join('') + '</tbody></table></div>'
      : '<p class="vazio">Nenhuma nota de compra deste material pendente para este atacadista. Toda a massa será tratada como origem própria (e gera alerta de auditoria).</p>';
  }

  function chipStatus(s) {
    const rot = { registrada: 'registrada', recebida: 'CDF recebido', homologada: 'homologada', rejeitada: 'rejeitada', emitido: 'ativo', aposentado: 'baixado', cancelado: 'cancelado' }[s] || s;
    return '<span class="chip s-' + esc(s) + '">' + esc(rot) + '</span>';
  }

  function renderNfes() {
    const m = reg.massas();
    const a = ator();
    const linhas = reg.estado.ordemNfes.slice().reverse().map((ch) => {
      const nf = reg.estado.nfes[ch];
      const x = m[ch];
      const dest = reg.participante(nf.destinatarioId);
      const btns = [];
      if (a && a.tipo === 'reciclador' && nf.destinatarioId === a.id && !nf.recebimento && nf.status !== 'rejeitada') btns.push('<button class="btn mini" data-acao="receber" data-chave="' + esc(ch) + '">Confirmar recebimento</button>');
      if (a && a.tipo === 'verificador' && nf.status !== 'homologada' && nf.status !== 'rejeitada') {
        btns.push('<button class="btn mini" data-acao="homologar" data-chave="' + esc(ch) + '">Homologar</button>');
      }
      if (a && a.tipo === 'verificador' && nf.status !== 'rejeitada') btns.push('<button class="btn mini perigo" data-acao="rejeitar" data-chave="' + esc(ch) + '">Rejeitar</button>');
      const extras = [];
      if (nf.origens && nf.origens.length) extras.push('repassa ' + nf.origens.length + ' nota(s) de origem (' + kg(nf.origens.reduce((s, o) => s + o.massaG, 0)) + ')');
      if (dest.tipo === 'atacadista') extras.push('crédito só via revenda do atacadista à recicladora');
      if (x.pendenteG) extras.push(kg(x.pendenteG) + ' aguardando a homologação desta nota');
      if (nf.recebimento) extras.push('MTR ' + nf.recebimento.mtr + ' · CDF ' + nf.recebimento.cdf + ' · recebido ' + kg(nf.recebimento.massaG));
      if (nf.rejeicao) extras.push('rejeitada: ' + nf.rejeicao.motivo);
      return '<tr><td><span class="mono">' + esc(ch) + '</span><br><small>' + esc(nomeP(nf.emitenteId)) + ' → ' + esc(dest.nome) + ' · ' + esc(nf.dataEmissao.split('-').reverse().join('/')) + (nf.avulsa ? ' · avulsa' : '') + '</small>' +
        (extras.length ? '<br><small style="color:var(--muted)">' + extras.map(esc).join(' · ') + '</small>' : '') +
        ((nf.alertas || []).length ? '<br><span class="alerta-txt">⚠ ' + nf.alertas.map(esc).join('<br>⚠ ') + '</span>' : '') +
        '</td><td>' + esc(C.MATERIAIS[nf.material]) + '</td><td class="num">' + kg(nf.massaG) + '</td><td class="num">' + kg(x.elegivelG) + '</td><td class="num">' + kg(x.saldoG) +
        '</td><td>' + chipStatus(nf.status) + '</td><td>' + (btns.join(' ') || '<small style="color:var(--muted)">—</small>') + '</td></tr>';
    });
    $('#lista-nfes').innerHTML = linhas.join('') || '<tr><td colspan="7" class="vazio">Nenhuma nota registrada.</td></tr>';
  }

  function renderFormCert() {
    manterValor('#c-empresa', opcoes(reg.participantesPorTipo('empresa'), reg.participantesPorTipo('empresa').length ? null : 'cadastre uma empresa aderente'));
    if (!$('#c-ano').value) $('#c-ano').value = new Date().getFullYear();
  }

  function renderCerts() {
    const a = ator();
    const linhas = reg.estado.ordemCertificados.slice().reverse().map((cod) => {
      const c = reg.estado.certificados[cod];
      const btns = ['<button class="btn mini sec" data-acao="ver" data-codigo="' + esc(cod) + '">Ver</button>'];
      if (c.status === 'emitido' && a && (a.id === c.empresaId || a.tipo === 'entidade')) btns.push('<button class="btn mini" data-acao="baixar" data-codigo="' + esc(cod) + '">Dar baixa na meta</button>');
      if (c.status === 'emitido' && a && a.tipo === 'entidade') btns.push('<button class="btn mini perigo" data-acao="cancelar" data-codigo="' + esc(cod) + '">Cancelar</button>');
      return '<tr><td class="mono">' + esc(cod) + '</td><td>' + esc(nomeP(c.empresaId)) + '</td><td>' + esc(C.MATERIAIS[c.material]) + ' · ' + esc(c.anoMeta) +
        '</td><td class="num">' + kg(c.massaG) + '</td><td>' + chipStatus(c.status) + (c.aposentadoria ? '<br><small>' + esc(c.aposentadoria.sistema) + '</small>' : '') + '</td><td>' + btns.join(' ') + '</td></tr>';
    });
    $('#lista-certs').innerHTML = linhas.join('') || '<tr><td colspan="6" class="vazio">Nenhum certificado emitido.</td></tr>';
  }

  const ROTULO_EVENTO = {
    PARTICIPANTE_CADASTRADO: 'Participante cadastrado',
    NFE_REGISTRADA: 'NF-e registrada',
    NFE_RECEBIMENTO_CONFIRMADO: 'Recebimento (MTR/CDF)',
    NFE_HOMOLOGADA: 'NF-e homologada',
    NFE_REJEITADA: 'NF-e rejeitada',
    CERTIFICADO_EMITIDO: 'Certificado emitido',
    CERTIFICADO_APOSENTADO: 'Baixa do certificado',
    CERTIFICADO_CANCELADO: 'Certificado cancelado',
  };

  function resumoEvento(ev) {
    const d = ev.dados;
    if (d.chave) return d.chave;
    if (d.codigo) return d.codigo;
    if (d.nome) return d.nome;
    return '';
  }

  function renderEventos() {
    $('#lista-eventos').innerHTML = reg.eventos.slice().reverse().map((ev) =>
      '<tr><td>' + ev.seq + '</td><td><small>' + esc(new Date(ev.ts).toLocaleString('pt-BR')) + '</small></td><td>' + esc(ROTULO_EVENTO[ev.tipo] || ev.tipo) +
      '<br><small class="mono">' + esc(resumoEvento(ev)) + '</small></td><td>' + esc(ev.ator ? nomeP(ev.ator) : 'cadastro') +
      '</td><td class="mono">' + esc(ev.hash.slice(0, 16)) + '…<br><span style="color:var(--muted)">↳ ' + esc(ev.anterior.slice(0, 16)) + '…</span></td></tr>'
    ).join('') || '<tr><td colspan="5" class="vazio">Livro-razão vazio.</td></tr>';
  }

  function htmlCertificado(c) {
    const ev = reg.eventos.find((e) => e.tipo === 'CERTIFICADO_EMITIDO' && e.dados.codigo === c.codigo);
    const emp = reg.participante(c.empresaId);
    const lastro = c.lastro.map((l) => {
      const nf = reg.estado.nfes[l.chave];
      const emit = reg.participante(nf.emitenteId);
      // A massa da nota de origem chega à recicladora pela revenda do atacadista.
      const revenda = reg.estado.ordemNfes.map((k) => reg.estado.nfes[k]).find((n) => (n.origens || []).some((o) => o.chave === nf.chave) && n.status === 'homologada');
      const comprovante = revenda || nf;
      const rec = comprovante.recebimento;
      return '<tr><td class="mono">' + esc(l.chave) + '</td><td>' + esc(emit.nome) + '<br><small class="mono">' + esc(C.mascararDoc(emit.doc)) + '</small></td><td>' +
        (revenda ? 'via ' + esc(nomeP(revenda.emitenteId)) + '<br>' : '') + (rec ? 'MTR ' + esc(rec.mtr) + ' · CDF ' + esc(rec.cdf) : '—') +
        '</td><td>' + esc(nf.homologacao ? nomeP(nf.homologacao.verificadorId) : '—') + '</td><td class="num">' + kg(l.massaG) + '</td></tr>';
    }).join('');
    const pct = c.massaG ? Math.round((c.catadoresG / c.massaG) * 100) : 0;
    return '<div class="certificado"><h3>Certificado de Crédito de Reciclagem de Logística Reversa</h3>' +
      '<div class="mono">' + esc(c.codigo) + '</div>' + chipStatus(c.status) +
      '<dl><dt>Titular</dt><dd>' + esc(emp.nome) + ' · ' + esc(C.formatarDoc(emp.doc)) + '</dd>' +
      '<dt>Material</dt><dd>' + esc(C.MATERIAIS[c.material]) + '</dd>' +
      '<dt>Massa</dt><dd><b>' + kg(c.massaG) + '</b> · ' + pct + '% de organizações de catadores</dd>' +
      '<dt>Meta</dt><dd>' + esc(c.anoMeta) + '</dd>' +
      '<dt>Emitido por</dt><dd>' + esc(nomeP(c.emitidoPor)) + ' em ' + esc(new Date(c.emitidoEm).toLocaleString('pt-BR')) + '</dd>' +
      (c.aposentadoria ? '<dt>Baixa</dt><dd>' + esc(c.aposentadoria.sistema) + (c.aposentadoria.protocolo ? ' · protocolo ' + esc(c.aposentadoria.protocolo) : '') + '</dd>' : '') +
      (c.cancelamento ? '<dt>Cancelado</dt><dd>' + esc(c.cancelamento.motivo) + '</dd>' : '') +
      '<dt>Finalidade</dt><dd>' + esc(c.finalidade) + '</dd>' +
      '<dt>Hash do evento</dt><dd class="mono">' + esc(ev ? ev.hash : '—') + '</dd></dl>' +
      '<h3 style="font-size:.95rem;color:var(--text)">Cadeia de custódia do lastro</h3><div class="tabela"><table><thead><tr><th>NF-e</th><th>Origem</th><th>Destinação final</th><th>Homologada por</th><th class="num">Massa</th></tr></thead><tbody>' + lastro + '</tbody></table></div></div>';
  }

  // ── Diálogo genérico ─────────────────────────────────────────────────
  function dialogo(titulo, campos, confirmar) {
    const dlg = $('#dlg');
    $('#dlg-titulo').textContent = titulo;
    $('#dlg-corpo').innerHTML = campos.map((c) => c.tipo === 'checkbox'
      ? '<label class="chk"><input type="checkbox" name="' + c.nome + '"> ' + esc(c.rotulo) + '</label>'
      : '<label class="campo">' + esc(c.rotulo) + '<input name="' + c.nome + '" type="' + (c.tipo || 'text') + '" value="' + esc(c.valor || '') + '"' + (c.modo ? ' inputmode="' + c.modo + '"' : '') + '></label>').join('');
    dlg.onclose = () => {
      if (dlg.returnValue !== 'ok') return;
      const dados = {};
      campos.forEach((c) => {
        const el = $('[name="' + c.nome + '"]', dlg);
        dados[c.nome] = c.tipo === 'checkbox' ? el.checked : el.value;
      });
      confirmar(dados);
    };
    dlg.returnValue = '';
    dlg.showModal();
  }

  // ── Cenário de exemplo e roteiro de fraudes ──────────────────────────
  function montarExemplo(r) {
    const cnpj = (base) => C.gerarCNPJ(base + '0001');
    const cad = (d) => r.cadastrarParticipante(d).id;
    const ids = {
      coop: cad({ tipo: 'cooperativa', nome: 'Cooperativa Mãos que Reciclam', doc: cnpj('31111111'), uf: 'SP', municipio: 'Orlândia' }),
      catadora: cad({ tipo: 'catador', nome: 'Ana Catadora', doc: C.gerarCPF('316254987'), uf: 'SP', municipio: 'Orlândia' }),
      ferro: cad({ tipo: 'atacadista', nome: 'Ferro-Velho Boa Vista', doc: cnpj('32222222'), uf: 'SP', municipio: 'Orlândia' }),
      recic: cad({ tipo: 'reciclador', nome: 'Recicladora Alta Mogiana', doc: cnpj('33333333'), uf: 'SP', municipio: 'Ribeirão Preto', capacidadeKgMes: 80000 }),
      entidade: cad({ tipo: 'entidade', nome: 'iReverse Gestora (exemplo)', doc: cnpj('34444444'), uf: 'SP', municipio: 'São Paulo' }),
      verif: cad({ tipo: 'verificador', nome: 'Verifica Independente (exemplo)', doc: cnpj('35555555'), uf: 'SP', municipio: 'Campinas' }),
      empresa: cad({ tipo: 'empresa', nome: 'Bebidas do Interior (exemplo)', doc: cnpj('36666666'), uf: 'SP', municipio: 'Franca' }),
    };
    const doc = (id) => r.participante(id).doc;
    const ch = (id, data, numero) => C.gerarChave({ uf: 'SP', ano: Number(data.slice(0, 4)), mes: Number(data.slice(5, 7)), cnpj: doc(id), numero, codigo: 40000000 + numero });
    const d1 = diasAtras(60), d2 = diasAtras(45), d3 = diasAtras(44), d4 = diasAtras(30), d5 = diasAtras(29);
    const k = {
      coopFerro: ch(ids.coop, d1, 101),
      ferroRecic: ch(ids.ferro, d2, 501),
      coopRecic: ch(ids.coop, d4, 102),
    };
    r.registrarNFe(ids.coop, { chave: k.coopFerro, emitenteId: ids.coop, destinatarioId: ids.ferro, material: 'plastico', massaKg: 1000, dataEmissao: d1 });
    r.registrarNFe(ids.ferro, { chave: k.ferroRecic, emitenteId: ids.ferro, destinatarioId: ids.recic, material: 'plastico', massaKg: 1200, dataEmissao: d2, origens: [{ chave: k.coopFerro, massaKg: 1000 }] });
    r.confirmarRecebimento(ids.recic, k.ferroRecic, { mtr: 'MTR-EX-0001', cdf: 'CDF-EX-0001', massaRecebidaKg: 1140, data: d3 });
    r.registrarNFe(ids.coop, { chave: k.coopRecic, emitenteId: ids.coop, destinatarioId: ids.recic, material: 'plastico', massaKg: 500, dataEmissao: d4 });
    r.confirmarRecebimento(ids.recic, k.coopRecic, { mtr: 'MTR-EX-0002', cdf: 'CDF-EX-0002', massaRecebidaKg: 500, data: d5 });
    [k.coopFerro, k.ferroRecic, k.coopRecic].forEach((x) => r.homologarNFe(ids.verif, x, 'autorizada'));
    const cert = r.emitirCertificado(ids.entidade, { empresaId: ids.empresa, material: 'plastico', anoMeta: new Date().getFullYear(), massaKg: 1200 });
    return { ids, k, codigo: cert.codigo };
  }

  function roteiroFraudes() {
    const r = new C.Registro();
    const { ids, k, codigo } = montarExemplo(r);
    const doc = (id) => r.participante(id).doc;
    const hojeStr = hoje();
    const ano = Number(hojeStr.slice(0, 4));
    const mes = Number(hojeStr.slice(5, 7));
    const tentativas = [
      ['Registrar de novo a mesma NF-e para gerar crédito em dobro', () => r.registrarNFe(ids.coop, { chave: k.coopRecic, emitenteId: ids.coop, destinatarioId: ids.recic, material: 'plastico', massaKg: 500, dataEmissao: r.estado.nfes[k.coopRecic].dataEmissao })],
      ['Inventar uma chave de acesso (dígito verificador forjado)', () => r.registrarNFe(ids.coop, { chave: k.coopRecic.slice(0, 43) + ((Number(k.coopRecic[43]) + 3) % 10), emitenteId: ids.coop, destinatarioId: ids.recic, material: 'plastico', massaKg: 500, dataEmissao: hojeStr })],
      ['Ferro-velho apresentar como sua uma nota emitida pela cooperativa', () => r.registrarNFe(ids.ferro, { chave: C.gerarChave({ uf: 'SP', ano, mes, cnpj: doc(ids.coop), numero: 777 }), emitenteId: ids.ferro, destinatarioId: ids.recic, material: 'plastico', massaKg: 300, dataEmissao: hojeStr })],
      ['Ferro-velho revender outra vez a massa já repassada da cooperativa', () => r.registrarNFe(ids.ferro, { chave: C.gerarChave({ uf: 'SP', ano, mes, cnpj: doc(ids.ferro), numero: 778 }), emitenteId: ids.ferro, destinatarioId: ids.recic, material: 'plastico', massaKg: 400, dataEmissao: hojeStr, origens: [{ chave: k.coopFerro, massaKg: 400 }] })],
      ['Usar o mesmo MTR para comprovar outra nota', () => {
        const nova = C.gerarChave({ uf: 'SP', ano, mes, cnpj: doc(ids.coop), numero: 779 });
        r.registrarNFe(ids.coop, { chave: nova, emitenteId: ids.coop, destinatarioId: ids.recic, material: 'plastico', massaKg: 200, dataEmissao: hojeStr });
        return r.confirmarRecebimento(ids.recic, nova, { mtr: 'MTR-EX-0001', cdf: 'CDF-NOVO-1', massaRecebidaKg: 200, data: hojeStr });
      }],
      ['O verificador emitir e vender um certificado', () => r.emitirCertificado(ids.verif, { empresaId: ids.empresa, material: 'plastico', anoMeta: ano, massaKg: 100 })],
      ['Emitir certificado acima do lastro disponível', () => r.emitirCertificado(ids.entidade, { empresaId: ids.empresa, material: 'plastico', anoMeta: ano, massaKg: 1000 })],
      ['Usar o mesmo certificado no SINIR e depois no sistema estadual', () => {
        r.aposentarCertificado(ids.empresa, codigo, { sistema: 'SINIR / Sisrev-BR', protocolo: 'REL-' + ano });
        return r.aposentarCertificado(ids.empresa, codigo, { sistema: 'Sistema estadual (CETESB)' });
      }],
    ];
    const linhas = tentativas.map(([desc, fn]) => {
      const res = fn();
      return '<tr><td>' + (res.ok ? '⚠️' : '🛡️') + '</td><td>' + esc(desc) + '<br><small style="color:var(--muted)">' + esc(res.ok ? 'PASSOU — revisar regra' : res.erros[0]) + '</small></td></tr>';
    });
    $('#fraudes').innerHTML = '<div class="tabela"><table><tbody>' + linhas.join('') + '</tbody></table></div><p class="vazio">Simulado numa cópia em memória: seus dados não mudaram.</p>';
  }

  // ── Eventos de tela ─────────────────────────────────────────────────
  function abrirAba(nome) {
    $$('nav.tabs button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === nome)));
    $$('section.tab').forEach((s) => s.classList.toggle('ativa', s.id === 'tab-' + nome));
    if (location.hash !== '#' + nome) history.replaceState(null, '', '#' + nome);
  }

  function ligar() {
    $$('nav.tabs button').forEach((b) => b.addEventListener('click', () => abrirAba(b.dataset.tab)));
    $$('[data-tab-link]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); abrirAba(a.dataset.tabLink); }));
    const inicial = (location.hash || '').slice(1);
    if ($('#tab-' + inicial)) abrirAba(inicial);

    $('#ator').addEventListener('change', () => { gravarStorage(CHAVE_ATOR, $('#ator').value); delete $('#n-emitente').dataset.tocado; renderizar(); });

    // Participantes
    $('#p-tipo').innerHTML = Object.entries(C.TIPOS).map(([k, t]) => '<option value="' + k + '">' + esc(t.rotulo) + '</option>').join('');
    $('#p-uf').innerHTML = Object.values(C.UF_POR_CODIGO).sort().map((uf) => '<option' + (uf === 'SP' ? ' selected' : '') + '>' + uf + '</option>').join('');
    const ajustarTipo = () => {
      const t = C.TIPOS[$('#p-tipo').value];
      $('#p-doc-rotulo').textContent = t.doc;
      $('#p-cap-campo').hidden = $('#p-tipo').value !== 'reciclador';
    };
    $('#p-tipo').addEventListener('change', ajustarTipo);
    ajustarTipo();
    $('#p-doc-gerar').addEventListener('click', () => {
      const n = String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
      $('#p-doc').value = C.formatarDoc(C.TIPOS[$('#p-tipo').value].doc === 'CPF' ? C.gerarCPF(n + '1') : C.gerarCNPJ(n + '0001'));
    });
    $('#form-participante').addEventListener('submit', (e) => {
      e.preventDefault();
      const dados = Object.fromEntries(new FormData(e.target));
      if (resultado(reg.cadastrarParticipante(dados), 'Participante cadastrado')) e.target.reset(), ajustarTipo();
    });

    // Notas
    const mats = Object.entries(C.MATERIAIS).map(([k, v]) => '<option value="' + k + '">' + esc(v) + '</option>').join('');
    $('#n-material').innerHTML = mats;
    $('#c-material').innerHTML = mats;
    $('#n-material').value = 'plastico';
    $('#c-material').value = 'plastico';
    $('#n-data').value = hoje();
    $('#n-emitente').addEventListener('change', () => { $('#n-emitente').dataset.tocado = '1'; atualizarOrigens(); });
    $('#n-material').addEventListener('change', atualizarOrigens);
    $('#n-chave-gerar').addEventListener('click', () => {
      const emit = reg.participante($('#n-emitente').value);
      if (!emit) return aviso('erro', 'Escolha o emitente primeiro.');
      const data = $('#n-data').value || hoje();
      const avulsa = $('#n-avulsa').checked;
      const cnpj = avulsa ? C.gerarCNPJ('469770890001') : emit.doc; // CNPJ fictício representando a SEFAZ
      $('#n-chave').value = C.gerarChave({ uf: emit.uf, ano: Number(data.slice(0, 4)), mes: Number(data.slice(5, 7)), cnpj, numero: Math.floor(Math.random() * 1e6), codigo: Math.floor(Math.random() * 1e8) });
    });
    $('#form-nfe').addEventListener('submit', (e) => {
      e.preventDefault();
      const f = e.target;
      const origens = $$('[data-origem]', f).map((i) => ({ chave: i.dataset.origem, massaKg: i.value })).filter((o) => o.massaKg);
      const dados = {
        chave: f.chave.value, emitenteId: f.emitenteId.value, destinatarioId: f.destinatarioId.value, material: f.material.value,
        massaKg: f.massaKg.value, dataEmissao: f.dataEmissao.value, avulsa: f.avulsa.checked, origens,
      };
      if (resultado(reg.registrarNFe(atorId(), dados), 'NF-e registrada')) { f.chave.value = ''; f.massaKg.value = ''; }
    });
    $('#lista-nfes').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-acao]');
      if (!b) return;
      const ch = b.dataset.chave;
      const nf = reg.estado.nfes[ch];
      if (b.dataset.acao === 'receber') {
        dialogo('Confirmar recebimento na recicladora', [
          { nome: 'mtr', rotulo: 'Número do MTR (SINIR)' },
          { nome: 'cdf', rotulo: 'Número do CDF (certificado de destinação final)' },
          { nome: 'massaRecebidaKg', rotulo: 'Massa efetivamente recebida (kg)', valor: String(nf.massaG / 1000), modo: 'decimal' },
          { nome: 'data', rotulo: 'Data do recebimento', tipo: 'date', valor: hoje() },
        ], (d) => resultado(reg.confirmarRecebimento(atorId(), ch, d), 'Recebimento confirmado'));
      } else if (b.dataset.acao === 'homologar') {
        dialogo('Homologar NF-e', [
          { nome: 'sefaz', tipo: 'checkbox', rotulo: 'Consultei a SEFAZ/Receita: a NF-e está autorizada, sem cancelamento nem denegação.' },
        ], (d) => resultado(reg.homologarNFe(atorId(), ch, d.sefaz ? 'autorizada' : 'nao-consultada'), 'NF-e homologada'));
      } else if (b.dataset.acao === 'rejeitar') {
        dialogo('Rejeitar NF-e', [{ nome: 'motivo', rotulo: 'Motivo (ex.: cancelada na SEFAZ, massa implausível)' }],
          (d) => resultado(reg.rejeitarNFe(atorId(), ch, d.motivo), 'NF-e rejeitada'));
      }
    });

    // Certificados
    const lerFormCert = () => {
      const f = $('#form-cert');
      return { empresaId: f.empresaId.value, material: f.material.value, anoMeta: f.anoMeta.value, massaKg: f.massaKg.value };
    };
    $('#c-simular').addEventListener('click', () => {
      const d = lerFormCert();
      const g = C.kgParaG(d.massaKg || 0);
      const sim = reg.simularLastro(d.material, Number(d.anoMeta), g > 0 ? g : 0);
      $('#c-previa').innerHTML = 'Disponível para ' + esc(C.MATERIAIS[d.material].toLowerCase()) + ' (notas de ' + (Number(d.anoMeta) - 1) + '/' + esc(d.anoMeta) + '): <b>' + kg(sim.disponivelG) + '</b>.' +
        (g > 0 ? (sim.suficiente ? ' Lastro: ' + sim.lastro.map((l) => esc(nomeP(reg.estado.nfes[l.chave].emitenteId)) + ' ' + kg(l.massaG)).join(' + ') + '.' : ' <span class="alerta-txt">Insuficiente para ' + kg(g) + '.</span>') : '');
    });
    $('#form-cert').addEventListener('submit', (e) => {
      e.preventDefault();
      const r = reg.emitirCertificado(atorId(), lerFormCert());
      if (resultado(r, 'Certificado ' + (r.codigo || '') + ' emitido')) { $('#c-massa').value = ''; $('#c-previa').textContent = ''; }
    });
    $('#lista-certs').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-acao]');
      if (!b) return;
      const cod = b.dataset.codigo;
      if (b.dataset.acao === 'ver') {
        $('#q-codigo').value = cod;
        consultar(cod);
        abrirAba('consulta');
      } else if (b.dataset.acao === 'baixar') {
        dialogo('Dar baixa: usar para comprovar a meta', [
          { nome: 'sistema', rotulo: 'Onde a meta foi comprovada (ex.: SINIR / Sisrev-BR)' },
          { nome: 'protocolo', rotulo: 'Protocolo do relatório (opcional)' },
        ], (d) => resultado(reg.aposentarCertificado(atorId(), cod, d), 'Baixa registrada. O certificado não pode mais ser usado.'));
      } else if (b.dataset.acao === 'cancelar') {
        dialogo('Cancelar certificado', [{ nome: 'motivo', rotulo: 'Motivo' }],
          (d) => resultado(reg.cancelarCertificado(atorId(), cod, d.motivo), 'Certificado cancelado; lastro devolvido às notas.'));
      }
    });

    // Consulta pública
    function consultar(cod) {
      const c = reg.consultarCertificado(cod);
      $('#resultado-consulta').innerHTML = c ? htmlCertificado(c) : '<div class="banner erro">Nenhum certificado com este código neste registro.</div>';
    }
    $('#form-consulta').addEventListener('submit', (e) => { e.preventDefault(); consultar($('#q-codigo').value); });

    // Livro-razão
    $('#btn-integridade').addEventListener('click', () => {
      const r = reg.verificarIntegridade();
      $('#integridade').innerHTML = r.ok
        ? '<div class="banner info">✔ Cadeia íntegra: ' + r.total + ' eventos. Último hash: <span class="mono">' + esc(r.ultimoHash) + '</span></div>'
        : '<div class="banner erro">✖ Quebra no evento #' + esc(r.quebraEm) + ': ' + esc(r.motivo) + '</div>';
    });
    $('#btn-adulterar').addEventListener('click', () => {
      const copia = JSON.parse(JSON.stringify(reg.eventos));
      const alvo = copia.find((ev) => ev.tipo === 'NFE_RECEBIMENTO_CONFIRMADO') || copia[0];
      if (!alvo) return aviso('alerta', 'Carregue dados primeiro.');
      if (alvo.dados.massaG) alvo.dados.massaG = alvo.dados.massaG * 10; else alvo.dados.nome = (alvo.dados.nome || '') + ' (alterado)';
      const r = C.verificarCadeia(copia);
      $('#integridade').innerHTML = '<div class="banner erro">Simulação: alguém editou o evento #' + alvo.seq + ' (' + esc(ROTULO_EVENTO[alvo.tipo]) + ') para inflar a massa. Resultado da verificação: ✖ quebra no evento #' + esc(r.quebraEm) + '. ' + esc(r.motivo) + ' Seus dados reais continuam intactos.</div>';
    });

    // Painel
    $('#btn-exemplo').addEventListener('click', () => {
      if (reg.eventos.length && !window.confirm('Substituir os dados atuais deste navegador pelo cenário de exemplo?')) return;
      falhaCarga = null;
      reg = new C.Registro();
      const ex = montarExemplo(reg);
      salvar();
      gravarStorage(CHAVE_ATOR, ex.ids.verif);
      $('#ator').value = '';
      renderizar();
      aviso('ok', 'Cenário carregado', ['Você está atuando como o verificador. Troque o papel no topo para testar as outras ações.', 'Certificado de exemplo: ' + ex.codigo]);
    });
    $('#btn-fraudes').addEventListener('click', roteiroFraudes);
    $('#btn-exportar').addEventListener('click', () => {
      const blob = new Blob([JSON.stringify({ versao: 1, exportadoEm: new Date().toISOString(), eventos: reg.eventos }, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'ireverse-livro-razao-' + hoje() + '.json';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    });
    $('#btn-importar').addEventListener('change', (e) => {
      const arq = e.target.files[0];
      if (!arq) return;
      arq.text().then((txt) => {
        let dados;
        try { dados = JSON.parse(txt); } catch (err) { return aviso('erro', 'Arquivo não é JSON válido.'); }
        const r = C.Registro.deEventos(dados.eventos || []);
        if (!r.integridade.ok) return aviso('erro', 'Importação recusada', ['Quebra no evento #' + r.integridade.quebraEm + ': ' + r.integridade.motivo]);
        falhaCarga = null;
        reg = r.registro;
        salvar();
        renderizar();
        aviso('ok', 'Livro-razão importado e verificado (' + reg.eventos.length + ' eventos).');
      }).finally(() => { e.target.value = ''; });
    });
    $('#btn-apagar').addEventListener('click', () => {
      if (!window.confirm('Apagar todos os dados do protótipo neste navegador?')) return;
      falhaCarga = null;
      reg = new C.Registro();
      try { window.localStorage.removeItem(CHAVE_STORAGE); } catch (e) { /* sem storage */ }
      renderizar();
      aviso('ok', 'Dados apagados.');
    });
  }

  carregar();
  ligar();
  renderizar();
})();
