/*
 * Caixa (PDV) da loja.
 *
 * - O leitor de código de barras funciona como teclado: digita e envia Enter.
 * - "3*7891000315507" soma 3 unidades de uma vez.
 * - A venda em andamento fica guardada no navegador: recarregar a página não
 *   perde o carrinho. Cada venda leva uma chave única; reenviar a mesma chave
 *   (rede caiu, clique duplo) devolve a venda já gravada, sem cobrar de novo.
 */
(function () {
  'use strict';

  var raiz = document.getElementById('pdv');
  if (!raiz) return;

  var URL_BUSCA = raiz.dataset.buscaUrl;
  var URL_VENDA = raiz.dataset.vendaUrl;
  var URL_VINCULAR = raiz.dataset.vincularUrl;
  var CHAVE_LOCAL = 'pdv:' + raiz.dataset.casa;
  var NFCE = raiz.dataset.nfce === '1';

  var busca = document.getElementById('pdv-busca');
  var resultados = document.getElementById('pdv-resultados');
  var corpo = document.getElementById('pdv-itens');
  var vazio = document.getElementById('pdv-vazio');
  var campoDesconto = document.getElementById('pdv-desconto');
  var listaPagamentos = document.getElementById('pdv-pagamentos');
  var botaoFinalizar = document.getElementById('pdv-finalizar');
  var caixaErro = document.getElementById('pdv-erro');
  var avisoCodigo = document.getElementById('pdv-aviso-codigo');
  var campoEmitir = document.getElementById('pdv-emitir');
  var campoCpf = document.getElementById('pdv-cpf');

  var estado = { itens: [], pagamentos: [], desconto: '', chave: null };
  var encontrados = [];
  var termoEncontrados = null; // termo que gerou a lista; Enter só escolhe nela se o termo for o mesmo
  var destaque = -1;
  var codigoPendente = null;
  var temporizador = null;
  var enviando = false;
  var ultimaBusca = 0;

  // ------------------------------------------------------------ números
  function numero(texto) {
    if (texto === null || texto === undefined) return 0;
    var limpo = String(texto).replace(/[R$\s]/g, '');
    if (limpo.indexOf(',') >= 0) limpo = limpo.replace(/\./g, '').replace(',', '.');
    var valor = parseFloat(limpo);
    return isFinite(valor) ? valor : 0;
  }
  function centavos(valor) { return Math.round((valor + Number.EPSILON) * 100); }
  function moeda(cents) {
    var negativo = cents < 0;
    var abs = Math.abs(cents);
    var inteiro = Math.floor(abs / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    var resto = String(abs % 100).padStart(2, '0');
    return (negativo ? '-' : '') + 'R$ ' + inteiro + ',' + resto;
  }
  function decimalTexto(cents) { return (cents / 100).toFixed(2); }
  function novaChave() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    return 'v' + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
  }

  // ------------------------------------------------------- armazenamento
  function salvar() {
    try { window.localStorage.setItem(CHAVE_LOCAL, JSON.stringify(estado)); } catch (e) { /* sem armazenamento */ }
  }
  function restaurar() {
    try {
      var bruto = window.localStorage.getItem(CHAVE_LOCAL);
      if (!bruto) return;
      var salvo = JSON.parse(bruto);
      if (salvo && Array.isArray(salvo.itens)) {
        estado.itens = salvo.itens;
        estado.pagamentos = Array.isArray(salvo.pagamentos) ? salvo.pagamentos : [];
        estado.desconto = salvo.desconto || '';
        estado.chave = salvo.chave || null;
      }
    } catch (e) { /* ignora estado corrompido */ }
  }
  function limparEstado() {
    estado = { itens: [], pagamentos: [], desconto: '', chave: null };
    try { window.localStorage.removeItem(CHAVE_LOCAL); } catch (e) { /* sem armazenamento */ }
  }

  // ---------------------------------------------------------------- totais
  function totais() {
    var subtotal = 0;
    var descontoItens = 0;
    estado.itens.forEach(function (item) {
      var bruto = centavos(numero(item.quantidade) * numero(item.preco));
      item._bruto = bruto;
      item._desconto = centavos(numero(item.desconto));
      subtotal += bruto;
      descontoItens += item._desconto;
    });
    var descontoVenda = centavos(numero(estado.desconto));
    var total = subtotal - descontoItens - descontoVenda;
    var recebido = estado.pagamentos.reduce(function (soma, p) { return soma + centavos(numero(p.valor)); }, 0);
    var dinheiro = estado.pagamentos.reduce(function (soma, p) { return soma + (p.t_pag === '01' ? centavos(numero(p.valor)) : 0); }, 0);
    return { subtotal: subtotal, total: total, recebido: recebido, troco: recebido - total, dinheiro: dinheiro };
  }

  function atualizarTotais() {
    var t = totais();
    document.getElementById('pdv-subtotal').textContent = moeda(t.subtotal);
    document.getElementById('pdv-total').textContent = moeda(Math.max(t.total, 0));
    document.getElementById('pdv-recebido').textContent = moeda(t.recebido);
    var rotuloTroco = document.getElementById('pdv-troco-rotulo');
    var troco = document.getElementById('pdv-troco');
    if (t.troco >= 0) {
      rotuloTroco.textContent = 'Troco';
      troco.textContent = moeda(t.troco);
      troco.classList.remove('text-danger');
    } else {
      rotuloTroco.textContent = 'Falta';
      troco.textContent = moeda(-t.troco);
      troco.classList.add('text-danger');
    }
    estado.itens.forEach(function (item, indice) {
      var celula = corpo.querySelector('[data-total="' + indice + '"]');
      if (celula) celula.textContent = moeda(item._bruto - item._desconto);
    });
    var trocoSemDinheiro = t.troco > 0 && t.troco > t.dinheiro;
    botaoFinalizar.disabled = enviando || !estado.itens.length || t.total <= 0 || t.troco < 0 || trocoSemDinheiro;
    botaoFinalizar.title = trocoSemDinheiro ? 'Só pagamento em dinheiro pode gerar troco' : '';
    salvar();
  }

  // --------------------------------------------------------------- carrinho
  function el(tag, attrs, texto) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (chave) { node.setAttribute(chave, attrs[chave]); });
    if (texto !== undefined) node.textContent = texto;
    return node;
  }

  function campo(indice, nome, valor, rotulo, modo) {
    var input = el('input', {
      class: 'form-control form-control-sm text-end ms-auto',
      inputmode: modo || 'decimal',
      'aria-label': rotulo,
      'data-indice': String(indice),
      'data-campo': nome,
    });
    input.value = valor;
    return input;
  }

  function desenharItens() {
    corpo.innerHTML = '';
    vazio.classList.toggle('d-none', estado.itens.length > 0);
    estado.itens.forEach(function (item, indice) {
      var linha = el('tr');
      var nome = el('td');
      nome.appendChild(el('div', { class: 'fw-semibold' }, item.descricao));
      var detalhe = item.unidade + ' · estoque ' + item.estoque;
      if (item.sem_ncm && NFCE) detalhe += ' · sem NCM';
      nome.appendChild(el('div', { class: 'small ' + (item.sem_ncm && NFCE ? 'text-danger' : 'text-muted') }, detalhe));
      linha.appendChild(nome);
      var qtd = el('td', { class: 'text-end' });
      qtd.appendChild(campo(indice, 'quantidade', item.quantidade, 'Quantidade de ' + item.descricao));
      linha.appendChild(qtd);
      var preco = el('td', { class: 'text-end' });
      preco.appendChild(campo(indice, 'preco', item.preco, 'Preço de ' + item.descricao));
      linha.appendChild(preco);
      var desconto = el('td', { class: 'text-end' });
      desconto.appendChild(campo(indice, 'desconto', item.desconto, 'Desconto em ' + item.descricao));
      linha.appendChild(desconto);
      linha.appendChild(el('td', { class: 'text-end fw-semibold', 'data-total': String(indice) }, ''));
      var remover = el('td', { class: 'text-end' });
      var botao = el('button', { type: 'button', class: 'btn btn-sm btn-outline-danger', 'data-remover': String(indice), 'aria-label': 'Remover ' + item.descricao }, '×');
      remover.appendChild(botao);
      linha.appendChild(remover);
      corpo.appendChild(linha);
    });
    atualizarTotais();
  }

  function adicionar(produto, quantidade) {
    var qtd = quantidade || 1;
    var existente = null;
    estado.itens.forEach(function (item) {
      if (item.product_id === produto.product_id && item.variant_id === produto.variant_id && !produto.fracionado) existente = item;
    });
    if (existente) {
      existente.quantidade = String(numero(existente.quantidade) + qtd);
    } else {
      estado.itens.push({
        product_id: produto.product_id,
        variant_id: produto.variant_id,
        descricao: produto.descricao,
        unidade: produto.unidade,
        fracionado: produto.fracionado,
        estoque: produto.estoque,
        sem_ncm: produto.sem_ncm,
        preco: String(produto.preco).replace('.', ','),
        quantidade: String(qtd).replace('.', ','),
        desconto: '',
      });
    }
    desenharItens();
    fecharResultados();
    busca.value = '';
    if (produto.fracionado && !existente) {
      var indice = estado.itens.length - 1;
      var input = corpo.querySelector('input[data-indice="' + indice + '"][data-campo="quantidade"]');
      if (input) { input.focus(); input.select(); return; }
    }
    busca.focus();
  }

  corpo.addEventListener('input', function (evento) {
    var alvo = evento.target;
    if (!alvo.dataset || alvo.dataset.indice === undefined) return;
    var item = estado.itens[Number(alvo.dataset.indice)];
    if (!item) return;
    item[alvo.dataset.campo] = alvo.value;
    atualizarTotais();
  });
  corpo.addEventListener('keydown', function (evento) {
    if (evento.key === 'Enter' && evento.target.dataset && evento.target.dataset.campo) {
      evento.preventDefault();
      busca.focus();
    }
  });
  corpo.addEventListener('click', function (evento) {
    var botao = evento.target.closest('[data-remover]');
    if (!botao) return;
    estado.itens.splice(Number(botao.dataset.remover), 1);
    desenharItens();
    busca.focus();
  });

  // ------------------------------------------------------------- pagamentos
  function desenharPagamentos() {
    listaPagamentos.innerHTML = '';
    estado.pagamentos.forEach(function (pagamento, indice) {
      var linha = el('div', { class: 'd-flex gap-2 align-items-center mb-1' });
      linha.appendChild(el('span', { class: 'small flex-grow-1' }, pagamento.rotulo));
      var input = el('input', {
        class: 'form-control form-control-sm text-end',
        style: 'max-width: 7.5rem',
        inputmode: 'decimal',
        'aria-label': 'Valor em ' + pagamento.rotulo,
        'data-pagamento': String(indice),
      });
      input.value = pagamento.valor;
      linha.appendChild(input);
      linha.appendChild(el('button', { type: 'button', class: 'btn btn-sm btn-outline-secondary', 'data-remover-pagamento': String(indice), 'aria-label': 'Remover pagamento' }, '×'));
      listaPagamentos.appendChild(linha);
    });
    atualizarTotais();
  }

  document.querySelectorAll('[data-forma]').forEach(function (botao) {
    botao.addEventListener('click', function () {
      var t = totais();
      var falta = Math.max(t.total - t.recebido, 0);
      estado.pagamentos.push({
        t_pag: botao.dataset.forma,
        rotulo: botao.textContent.trim(),
        valor: falta ? decimalTexto(falta).replace('.', ',') : '',
      });
      desenharPagamentos();
      var inputs = listaPagamentos.querySelectorAll('input[data-pagamento]');
      var ultimo = inputs[inputs.length - 1];
      if (ultimo) { ultimo.focus(); ultimo.select(); }
    });
  });
  listaPagamentos.addEventListener('input', function (evento) {
    var indice = evento.target.dataset ? evento.target.dataset.pagamento : undefined;
    if (indice === undefined) return;
    estado.pagamentos[Number(indice)].valor = evento.target.value;
    atualizarTotais();
  });
  listaPagamentos.addEventListener('click', function (evento) {
    var botao = evento.target.closest('[data-remover-pagamento]');
    if (!botao) return;
    estado.pagamentos.splice(Number(botao.dataset.removerPagamento), 1);
    desenharPagamentos();
  });
  listaPagamentos.addEventListener('keydown', function (evento) {
    if (evento.key === 'Enter') {
      evento.preventDefault();
      if (!botaoFinalizar.disabled) finalizar();
    }
  });
  campoDesconto.addEventListener('input', function () { estado.desconto = campoDesconto.value; atualizarTotais(); });

  // ------------------------------------------------------------------ busca
  function fecharResultados() {
    resultados.classList.add('d-none');
    resultados.innerHTML = '';
    encontrados = [];
    termoEncontrados = null;
    destaque = -1;
  }

  function mostrarResultados(itens, termo) {
    encontrados = itens;
    termoEncontrados = termo;
    destaque = itens.length ? 0 : -1;
    resultados.innerHTML = '';
    if (!itens.length) {
      resultados.appendChild(el('div', { class: 'list-group-item text-muted' }, 'Nenhum produto encontrado.'));
      resultados.classList.remove('d-none');
      return;
    }
    itens.forEach(function (item, indice) {
      var linha = el('div', { class: 'list-group-item d-flex align-items-center gap-2' + (indice === 0 ? ' active-item' : ''), role: 'option', 'data-indice': String(indice) });
      var texto = el('div', { class: 'flex-grow-1' });
      texto.appendChild(el('div', { class: 'fw-semibold' }, item.descricao));
      var extras = item.unidade + ' · estoque ' + item.estoque + (item.codigo_barras ? ' · ' + item.codigo_barras : '');
      texto.appendChild(el('div', { class: 'small text-muted' }, extras));
      linha.appendChild(texto);
      linha.appendChild(el('strong', {}, 'R$ ' + String(item.preco).replace('.', ',')));
      if (codigoPendente) {
        linha.appendChild(el('button', { type: 'button', class: 'btn btn-sm btn-warning', 'data-vincular': String(indice) }, 'Vincular'));
      }
      resultados.appendChild(linha);
    });
    resultados.classList.remove('d-none');
  }

  function marcar(indice) {
    var linhas = resultados.querySelectorAll('[data-indice]');
    linhas.forEach(function (linha) { linha.classList.remove('active-item'); });
    if (linhas[indice]) {
      linhas[indice].classList.add('active-item');
      linhas[indice].scrollIntoView({ block: 'nearest' });
    }
    destaque = indice;
  }

  function interpretar(texto) {
    var match = /^(\d+(?:[.,]\d+)?)\s*\*\s*(.+)$/.exec(texto);
    if (match) return { quantidade: numero(match[1]), termo: match[2].trim() };
    return { quantidade: 1, termo: texto };
  }

  function pareceCodigo(termo) { return /^\d{6,14}$/.test(termo); }

  function pesquisar(termo) {
    var pedido = ++ultimaBusca;
    return fetch(URL_BUSCA + '?q=' + encodeURIComponent(termo), {
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    }).then(function (resposta) {
      if (!resposta.ok) throw new Error('busca');
      return resposta.json();
    }).then(function (dados) {
      return pedido === ultimaBusca ? (dados.itens || []) : null;
    });
  }

  function enviarBusca() {
    var lido = interpretar(busca.value.trim());
    if (!lido.termo) return;
    // A lista na tela pode ser de um termo anterior (o Enter cancela a busca
    // que estava aguardando): nesse caso busca de novo em vez de escolher nela.
    if (!pareceCodigo(lido.termo) && destaque >= 0 && encontrados[destaque] && termoEncontrados === lido.termo) {
      adicionar(encontrados[destaque], lido.quantidade);
      return;
    }
    pesquisar(lido.termo).then(function (itens) {
      if (itens === null) return;
      if (pareceCodigo(lido.termo)) {
        if (itens.length === 1 && itens[0].codigo_barras === lido.termo) {
          adicionar(itens[0], lido.quantidade);
          return;
        }
        if (!itens.length) {
          codigoPendente = lido.termo;
          document.getElementById('pdv-codigo-lido').textContent = lido.termo;
          avisoCodigo.classList.remove('d-none');
          busca.value = '';
          fecharResultados();
          busca.focus();
          return;
        }
      }
      if (itens.length === 1) {
        adicionar(itens[0], lido.quantidade);
        return;
      }
      mostrarResultados(itens, lido.termo);
    }).catch(function () {
      mostrarErro('Não foi possível buscar os produtos. Confira a internet.');
    });
  }

  busca.addEventListener('keydown', function (evento) {
    if (evento.key === 'Enter') {
      evento.preventDefault();
      clearTimeout(temporizador);
      enviarBusca();
    } else if (evento.key === 'ArrowDown' && encontrados.length) {
      evento.preventDefault();
      marcar(Math.min(destaque + 1, encontrados.length - 1));
    } else if (evento.key === 'ArrowUp' && encontrados.length) {
      evento.preventDefault();
      marcar(Math.max(destaque - 1, 0));
    } else if (evento.key === 'Escape') {
      fecharResultados();
    }
  });
  busca.addEventListener('input', function () {
    clearTimeout(temporizador);
    var lido = interpretar(busca.value.trim());
    if (lido.termo.length < 2 || pareceCodigo(lido.termo)) {
      if (!lido.termo) fecharResultados();
      return;
    }
    temporizador = setTimeout(function () {
      pesquisar(lido.termo).then(function (itens) { if (itens !== null) mostrarResultados(itens, lido.termo); }).catch(function () {});
    }, 250);
  });
  resultados.addEventListener('click', function (evento) {
    var vincular = evento.target.closest('[data-vincular]');
    if (vincular) {
      vincularCodigo(encontrados[Number(vincular.dataset.vincular)]);
      return;
    }
    var linha = evento.target.closest('[data-indice]');
    if (linha && encontrados[Number(linha.dataset.indice)]) {
      adicionar(encontrados[Number(linha.dataset.indice)], interpretar(busca.value.trim()).quantidade);
    }
  });
  document.getElementById('pdv-cancelar-vinculo').addEventListener('click', function () {
    codigoPendente = null;
    avisoCodigo.classList.add('d-none');
    busca.focus();
  });

  function vincularCodigo(produto) {
    if (!produto || !codigoPendente) return;
    fetch(URL_VINCULAR, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ product_id: produto.product_id, variant_id: produto.variant_id, codigo: codigoPendente }),
    }).then(function (resposta) {
      return resposta.json().then(function (dados) { return { ok: resposta.ok, dados: dados }; });
    }).then(function (retorno) {
      if (!retorno.ok || !retorno.dados.ok) {
        mostrarErro((retorno.dados && retorno.dados.erro) || 'Não foi possível vincular o código.');
        return;
      }
      codigoPendente = null;
      avisoCodigo.classList.add('d-none');
      adicionar(retorno.dados.item, 1);
    }).catch(function () {
      mostrarErro('Não foi possível vincular o código. Confira a internet.');
    });
  }

  // ---------------------------------------------------------------- venda
  function mostrarErro(mensagem) {
    caixaErro.textContent = mensagem;
    caixaErro.classList.remove('d-none');
  }
  function limparErro() { caixaErro.classList.add('d-none'); caixaErro.textContent = ''; }

  function payload() {
    if (!estado.chave) { estado.chave = novaChave(); salvar(); }
    return {
      chave: estado.chave,
      itens: estado.itens.map(function (item) {
        return {
          product_id: item.product_id,
          variant_id: item.variant_id,
          quantidade: item.quantidade,
          preco_unitario: item.preco,
          desconto: item.desconto || '0',
        };
      }),
      pagamentos: estado.pagamentos.map(function (p) { return { t_pag: p.t_pag, valor: p.valor }; }),
      desconto: estado.desconto || '0',
      emitir_nfce: Boolean(campoEmitir && campoEmitir.checked),
      cpf: campoCpf ? campoCpf.value : '',
    };
  }

  function finalizar() {
    if (enviando || botaoFinalizar.disabled) return;
    limparErro();
    enviando = true;
    botaoFinalizar.disabled = true;
    botaoFinalizar.textContent = (campoEmitir && campoEmitir.checked) ? 'Registrando e emitindo NFC-e…' : 'Registrando…';
    fetch(URL_VENDA, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload()),
    }).then(function (resposta) {
      return resposta.json().then(function (dados) { return { ok: resposta.ok, dados: dados }; }, function () {
        return { ok: false, dados: { erro: 'Resposta inesperada do servidor (' + resposta.status + ').' } };
      });
    }).then(function (retorno) {
      if (!retorno.ok || !retorno.dados.ok) {
        // Erro de validação: a venda não foi gravada; a mesma chave pode ser reusada.
        mostrarErro((retorno.dados && (retorno.dados.erro || retorno.dados.message)) || 'Não foi possível registrar a venda.');
        return;
      }
      concluir(retorno.dados);
    }).catch(function () {
      mostrarErro('Sem resposta do servidor. Confira em "Vendas" se a venda foi registrada antes de tentar de novo — tentar de novo aqui não cobra duas vezes.');
    }).then(function () {
      enviando = false;
      botaoFinalizar.innerHTML = 'Finalizar venda <span class="pdv-atalho">F9</span>';
      atualizarTotais();
    });
  }

  var modal = null;
  function concluir(dados) {
    limparEstado();
    document.getElementById('pdv-modal-titulo').textContent = 'Venda #' + dados.venda_id + ' registrada';
    document.getElementById('pdv-modal-total').textContent = 'Total ' + moeda(centavos(numero(dados.total)));
    var troco = centavos(numero(dados.troco));
    document.getElementById('pdv-modal-troco').textContent = troco > 0 ? 'Troco ' + moeda(troco) : 'Sem troco';
    var caixaNfce = document.getElementById('pdv-modal-nfce');
    var cupom = document.getElementById('pdv-modal-cupom');
    caixaNfce.className = 'alert d-none mb-0';
    cupom.classList.add('d-none');
    if (dados.nfce) {
      caixaNfce.classList.remove('d-none');
      if (dados.nfce.autorizada) {
        caixaNfce.classList.add('alert-success');
        caixaNfce.textContent = 'NFC-e autorizada.';
        cupom.href = dados.nfce.cupom_url;
        cupom.classList.remove('d-none');
      } else if (dados.nfce.contingencia) {
        caixaNfce.classList.add('alert-info');
        caixaNfce.textContent = 'SEFAZ sem resposta: NFC-e emitida em contingência. Imprima o cupom — o envio à SEFAZ é automático.';
        cupom.href = dados.nfce.cupom_url;
        cupom.classList.remove('d-none');
      } else {
        caixaNfce.classList.add('alert-warning');
        caixaNfce.textContent = 'NFC-e não autorizada: ' + (dados.nfce.mensagem || dados.nfce.rotulo) + '. A venda está registrada; emita a nota de novo em "Ver venda".';
      }
    }
    document.getElementById('pdv-modal-comprovante').href = dados.comprovante_url;
    document.getElementById('pdv-modal-venda').href = dados.venda_url;
    if (window.bootstrap && window.bootstrap.Modal) {
      modal = window.bootstrap.Modal.getOrCreateInstance(document.getElementById('pdv-modal'), { backdrop: 'static', keyboard: false });
      modal.show();
      setTimeout(function () { document.getElementById('pdv-nova').focus(); }, 300);
    } else {
      window.location.reload();
    }
  }

  document.getElementById('pdv-nova').addEventListener('click', function () { window.location.reload(); });
  document.getElementById('pdv-limpar').addEventListener('click', function () {
    if (!estado.itens.length && !estado.pagamentos.length) return;
    if (!window.confirm('Limpar todos os itens desta venda?')) return;
    limparEstado();
    campoDesconto.value = '';
    desenharItens();
    desenharPagamentos();
    busca.focus();
  });
  botaoFinalizar.addEventListener('click', finalizar);

  document.addEventListener('keydown', function (evento) {
    if (evento.key === 'F9') { evento.preventDefault(); finalizar(); }
    if (evento.key === 'F2') { evento.preventDefault(); busca.focus(); busca.select(); }
  });

  restaurar();
  campoDesconto.value = estado.desconto || '';
  desenharItens();
  desenharPagamentos();
})();
