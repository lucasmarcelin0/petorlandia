// Dynamic interactions for loja page
function initQuantitySelectors(root=document){
  root.querySelectorAll('.quantity-selector').forEach(box => {
    if (box.dataset.quantityListenerAttached === 'true') {
      return;
    }
    const input = box.querySelector('.quantity-input');
    if (!input) {
      return;
    }

    const step = Number.parseInt(input.step || '1', 10) || 1;
    const minValue = Number.parseInt(input.min || '1', 10) || 1;

    const getSanitisedValue = () => {
      const cleaned = input.value.replace(/[^\d]/g, '');
      if (cleaned !== input.value) {
        input.value = cleaned;
      }
      if (cleaned === '') {
        return null;
      }
      return Math.max(minValue, Number.parseInt(cleaned, 10));
    };

    const commitValue = value => {
      const next = Math.max(minValue, Number.parseInt(String(value), 10) || minValue);
      input.value = String(next);
      return next;
    };

    const update = delta => {
      const current = getSanitisedValue();
      const base = current === null ? minValue : current;
      const nextValue = Math.max(minValue, base + delta);
      commitValue(nextValue);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    };

    const minusBtn = box.querySelector('.quantity-btn.minus');
    const plusBtn = box.querySelector('.quantity-btn.plus');

    minusBtn?.addEventListener('click', ev => {
      ev.preventDefault();
      update(-step);
    });

    plusBtn?.addEventListener('click', ev => {
      ev.preventDefault();
      update(step);
    });

    const handleInput = force => {
      const current = getSanitisedValue();
      if (current === null) {
        if (force) {
          commitValue(minValue);
        }
        return;
      }
      if (force) {
        commitValue(current);
      }
    };

    input.addEventListener('input', () => handleInput(false));
    input.addEventListener('change', () => handleInput(true));
    input.addEventListener('blur', () => handleInput(true));

    handleInput(true);
    box.dataset.quantityListenerAttached = 'true';
  });
}

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
