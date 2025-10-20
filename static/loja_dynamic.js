// Dynamic interactions for loja page
function initQuantitySelectors(root=document){
  root.querySelectorAll('.quantity-selector').forEach(box => {
    const input = box.querySelector('.quantity-input');
    if (!input) {
      return;
    }
    const current = parseInt(input.value || '1', 10);
    if (Number.isNaN(current) || current < 1) {
      input.value = '1';
    }
  });
}

document.addEventListener('click', event => {
  const btn = event.target.closest('.quantity-btn');
  if (!btn) {
    return;
  }

  const container = btn.closest('.quantity-selector');
  if (!container) {
    return;
  }

  const input = container.querySelector('.quantity-input');
  if (!input) {
    return;
  }

  const value = parseInt(input.value || '1', 10);
  const current = Number.isNaN(value) ? 1 : value;

  if (btn.classList.contains('minus')) {
    input.value = Math.max(1, current - 1);
  } else if (btn.classList.contains('plus')) {
    input.value = current + 1;
  }

  input.dispatchEvent(new Event('change', { bubbles: true }));
});

function initAddToCartButtons(root=document){
  root.querySelectorAll('.js-add-to-cart').forEach(btn => {
    btn.addEventListener('click', () => {
      const original = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Adicionando...';
      setTimeout(() => {
        btn.disabled = false;
        btn.innerHTML = original;
      }, 1200);
    }, { once:false });
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
        if(typeof window.attachCartFormListeners === 'function'){
          window.attachCartFormListeners(container);
        }
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
  if(typeof window.attachCartFormListeners === 'function'){
    window.attachCartFormListeners();
  }
  initChipScroll();
}

document.addEventListener('DOMContentLoaded', initDynamicProducts);
