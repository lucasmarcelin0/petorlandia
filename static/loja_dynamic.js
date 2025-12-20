// Dynamic interactions for loja page
function initQuantitySelectors(root=document){
  root.querySelectorAll('.quantity-selector').forEach(box => {
    const input = box.querySelector('.quantity-input');
    box.querySelector('.minus')?.addEventListener('click', () => {
      const v = parseInt(input.value || '1', 10);
      input.value = Math.max(1, v - 1);
    });
    box.querySelector('.plus')?.addEventListener('click', () => {
      const v = parseInt(input.value || '1', 10);
      input.value = v + 1;
    });
  });
}

function initAddToCartButtons(root=document){
  root.querySelectorAll('.js-cart-form').forEach(form => {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      
      const btn = form.querySelector('.js-add-to-cart');
      const quantityInput = form.querySelector('.quantity-input');
      const quantity = parseInt(quantityInput?.value || '1', 10);
      
      // Mostra animação de carregamento
      const originalHTML = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Adicionando...';
      
      // Submete via AJAX
      const formData = new FormData(form);
      fetch(form.action, {
        method: 'POST',
        body: formData,
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        }
      })
      .then(response => {
        // Verifica o Content-Type para saber se é JSON
        const contentType = response.headers.get('content-type');
        if(contentType && contentType.includes('application/json')) {
          return response.json().then(data => ({ data, isJson: true, ok: response.ok }));
        } else {
          // Se não for JSON, não é sucesso (foi redirecionado)
          return { data: null, isJson: false, ok: false };
        }
      })
      .then(({ data, isJson, ok }) => {
        if(isJson && ok && data) {
          // Sucesso! Mostrar mensagem
          const messageHTML = `
            <div class="d-flex flex-column align-items-center justify-content-center" style="gap: 0.5rem;">
              <div class="text-success" style="font-size: 1.5rem;">
                <i class="fa-solid fa-circle-check"></i>
              </div>
              <div class="fw-semibold text-success" style="font-size: 0.95rem;">
                Adicionado!
              </div>
            </div>
          `;
          btn.innerHTML = messageHTML;
          btn.className = 'add-to-cart-btn js-add-to-cart';
          
          // Restaura o botão após 2 segundos
          setTimeout(() => {
            btn.innerHTML = originalHTML;
            btn.disabled = false;
            quantityInput.value = '1';
          }, 2000);
        } else {
          // Erro
          btn.innerHTML = '<i class="fa-solid fa-triangle-exclamation me-1"></i> Erro!';
          btn.classList.add('btn-danger');
          setTimeout(() => {
            btn.innerHTML = originalHTML;
            btn.disabled = false;
            btn.classList.remove('btn-danger');
          }, 2000);
        }
      })
      .catch(error => {
        console.error('Erro ao adicionar ao carrinho:', error);
        btn.innerHTML = '<i class="fa-solid fa-triangle-exclamation me-1"></i> Erro!';
        btn.classList.add('btn-danger');
        setTimeout(() => {
          btn.innerHTML = originalHTML;
          btn.disabled = false;
          btn.classList.remove('btn-danger');
        }, 2000);
      });
    });
  });
}

function initChipScroll(){
  const sc = document.getElementById('chipsScroll');
  if(!sc) return;
  sc.addEventListener('wheel', e => {
    if(Math.abs(e.deltaY) > Math.abs(e.deltaX)){
      sc.scrollLeft += e.deltaY;
      e.preventDefault();
    }
  }, {passive:false});
}

function initDynamicProducts(){
  const container = document.getElementById('products-container');
  const form = document.getElementById('search-form');
  if(!container || !form) return;

  const fetchProducts = (params, push=true) => {
    fetch('/loja/data?' + params.toString(), {headers:{'X-Requested-With':'XMLHttpRequest'}})
      .then(r => r.text())
      .then(html => {
        container.innerHTML = html;
        initQuantitySelectors(container);
        initAddToCartButtons(container);
        if(push){
          history.pushState(null, '', '/loja?' + params.toString());
        }
      });
  };

  form.addEventListener('submit', e => {
    e.preventDefault();
    const params = new URLSearchParams(new FormData(form));
    params.set('page', 1);
    fetchProducts(params);
  });

  form.querySelector('select[name="filter"]').addEventListener('change', () => {
    const params = new URLSearchParams(new FormData(form));
    params.set('page', 1);
    fetchProducts(params);
  });

  document.querySelectorAll('.chip[data-category]').forEach(chip => {
    chip.addEventListener('click', e => {
      e.preventDefault();
      const params = new URLSearchParams(new FormData(form));
      params.set('category', chip.dataset.category);
      params.set('page', 1);
      fetchProducts(params);
    });
  });
  document.querySelectorAll('.js-clear-category').forEach(btn => {
    btn.addEventListener('click', e => {
      e.preventDefault();
      const params = new URLSearchParams(new FormData(form));
      params.delete('category');
      params.set('page', 1);
      fetchProducts(params);
    });
  });

  container.addEventListener('click', e => {
    const link = e.target.closest('.pagination a.page-link');
    if(link){
      e.preventDefault();
      const url = new URL(link.href);
      fetchProducts(url.searchParams);
    }
  });

  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(window.location.search);
    fetchProducts(params, false);
  });

  // initialize on first load
  initQuantitySelectors();
  initAddToCartButtons();
  initChipScroll();
}

document.addEventListener('DOMContentLoaded', initDynamicProducts);
