/*
 * Conferência da entrada por XML: mostra os campos da ação escolhida,
 * busca o produto da loja para vincular e recalcula quantidade e custo
 * quando o fator da embalagem muda.
 */
(function () {
  'use strict';

  var form = document.getElementById('entrada-form');
  if (!form) return;
  var URL_BUSCA = form.dataset.buscaUrl;

  function numero(texto) {
    var limpo = String(texto || '').replace(/\s/g, '');
    if (limpo.indexOf(',') >= 0) limpo = limpo.replace(/\./g, '').replace(',', '.');
    var valor = parseFloat(limpo);
    return isFinite(valor) ? valor : 0;
  }
  function br(valor, casas) {
    return valor.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas });
  }

  function atualizarResumo(linha) {
    var fator = numero(linha.querySelector('[data-fator]').value) || 0;
    var quantidade = numero(linha.dataset.quantidade) * fator;
    var total = numero(linha.dataset.total);
    var resumo = linha.querySelector('[data-resumo]');
    if (!resumo) return;
    if (quantidade <= 0) {
      resumo.textContent = 'fator inválido';
      return;
    }
    var custo = total / quantidade;
    resumo.innerHTML = '';
    resumo.appendChild(document.createTextNode(br(quantidade, quantidade % 1 ? 3 : 0) + ' un.'));
    resumo.appendChild(document.createElement('br'));
    resumo.appendChild(document.createTextNode('custo R$ ' + br(custo, 2) + '/un.'));
    var preco = linha.querySelector('[data-preco]');
    if (preco && preco.value === preco.dataset.sugerido) {
      // Preço ainda é a sugestão: acompanha o novo custo (custo + 50%).
      var sugerido = br(Math.round(custo * 1.5 * 100) / 100, 2).replace(/\./g, '');
      preco.value = sugerido;
      preco.dataset.sugerido = sugerido;
    }
    conferirPreco(linha);
  }

  function conferirPreco(linha) {
    var preco = linha.querySelector('[data-preco]');
    var aviso = linha.querySelector('[data-abaixo]');
    if (!preco || !aviso) return;
    var fator = numero(linha.querySelector('[data-fator]').value) || 0;
    var quantidade = numero(linha.dataset.quantidade) * fator;
    var custo = quantidade > 0 ? numero(linha.dataset.total) / quantidade : 0;
    var valor = numero(preco.value);
    var abaixo = valor > 0 && custo > 0 && valor < custo;
    aviso.classList.toggle('d-none', !abaixo);
    if (abaixo) aviso.textContent = 'Preço abaixo do custo (R$ ' + br(custo, 2) + ').';
  }

  function mostrarCampos(linha) {
    var acao = linha.querySelector('[data-acao]').value;
    linha.querySelectorAll('[data-campos]').forEach(function (bloco) {
      bloco.classList.toggle('d-none', bloco.dataset.campos !== acao);
    });
  }

  var temporizadores = new WeakMap();

  function buscar(linha, termo) {
    var lista = linha.querySelector('[data-resultados]');
    if (termo.length < 2) { lista.classList.add('d-none'); return; }
    fetch(URL_BUSCA + '?q=' + encodeURIComponent(termo), { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(function (resposta) { return resposta.ok ? resposta.json() : { itens: [] }; })
      .then(function (dados) {
        lista.innerHTML = '';
        (dados.itens || []).forEach(function (item) {
          var opcao = document.createElement('button');
          opcao.type = 'button';
          opcao.className = 'list-group-item list-group-item-action small';
          opcao.textContent = item.descricao + ' · R$ ' + String(item.preco).replace('.', ',') + ' · estoque ' + item.estoque;
          opcao.addEventListener('click', function () {
            linha.querySelector('[data-product]').value = item.product_id;
            linha.querySelector('[data-variant]').value = item.variant_id || '';
            var escolhido = linha.querySelector('[data-escolhido]');
            escolhido.innerHTML = '';
            var marca = document.createElement('span');
            marca.className = 'text-success';
            marca.textContent = '✓ ' + item.descricao;
            escolhido.appendChild(marca);
            lista.classList.add('d-none');
            linha.querySelector('[data-busca]').value = '';
          });
          lista.appendChild(opcao);
        });
        if (!lista.children.length) {
          var vazio = document.createElement('div');
          vazio.className = 'list-group-item small text-muted';
          vazio.textContent = 'Nenhum produto encontrado. Use "Criar produto novo".';
          lista.appendChild(vazio);
        }
        lista.classList.remove('d-none');
      })
      .catch(function () { lista.classList.add('d-none'); });
  }

  form.querySelectorAll('tr[data-item]').forEach(function (linha) {
    var acao = linha.querySelector('[data-acao]');
    if (acao) acao.addEventListener('change', function () { mostrarCampos(linha); });
    var fator = linha.querySelector('[data-fator]');
    if (fator) fator.addEventListener('input', function () { atualizarResumo(linha); });
    var preco = linha.querySelector('[data-preco]');
    if (preco) preco.addEventListener('input', function () { conferirPreco(linha); });
    conferirPreco(linha);
    var campoBusca = linha.querySelector('[data-busca]');
    if (campoBusca) {
      campoBusca.addEventListener('input', function () {
        clearTimeout(temporizadores.get(linha));
        temporizadores.set(linha, setTimeout(function () { buscar(linha, campoBusca.value.trim()); }, 250));
      });
      campoBusca.addEventListener('keydown', function (evento) {
        if (evento.key === 'Enter') evento.preventDefault();
      });
    }
  });
})();
