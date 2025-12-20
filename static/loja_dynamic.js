// Dynamic interactions for loja page

// Sistema de notificações
function getToastContainer() {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    container.style.cssText = 'position: fixed; top: 80px; right: 20px; z-index: 9999; pointer-events: none;';
    document.body.appendChild(container);
  }
  return container;
}

function showToast(message, category = 'success') {
  const container = getToastContainer();
  const toast = document.createElement('div');
  toast.className = `toast-notification ${category}`;
  toast.textContent = message;
  toast.style.cssText = `
    display: flex;
    align-items: center;
    padding: 12px 20px;
    margin-bottom: 10px;
    border-radius: 4px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    animation: slideIn 0.3s ease-out;
    pointer-events: auto;
    min-width: 300px;
  `;
  
  // Estilos baseados na categoria
  const styles = {
    success: { backgroundColor: '#d4edda', color: '#155724', border: '1px solid #c3e6cb' },
    info: { backgroundColor: '#d1ecf1', color: '#0c5460', border: '1px solid #bee5eb' },
    warning: { backgroundColor: '#fff3cd', color: '#856404', border: '1px solid #ffeeba' },
    danger: { backgroundColor: '#f8d7da', color: '#721c24', border: '1px solid #f5c6cb' }
  };
  
  const style = styles[category] || styles.success;
  Object.assign(toast.style, style);
  
  container.appendChild(toast);
  
  const timeout = setTimeout(() => {
    toast.style.animation = 'slideOut 0.3s ease-out forwards';
    setTimeout(() => {
      toast.remove();
    }, 300);
  }, 3000);
  
  toast.addEventListener('click', () => {
    clearTimeout(timeout);
    toast.style.animation = 'slideOut 0.3s ease-out forwards';
    setTimeout(() => {
      toast.remove();
    }, 300);
  });
}

// Injetar estilos de animação se não existirem
if (!document.querySelector('style[data-toast-styles]')) {
  const style = document.createElement('style');
  style.setAttribute('data-toast-styles', '');
  style.textContent = `
    @keyframes slideIn {
      from {
        transform: translateX(400px);
        opacity: 0;
      }
      to {
        transform: translateX(0);
        opacity: 1;
      }
    }
    @keyframes slideOut {
      from {
        transform: translateX(0);
        opacity: 1;
      }
      to {
        transform: translateX(400px);
        opacity: 0;
      }
    }
  `;
  document.head.appendChild(style);
}

function initQuantitySelectors(root=document){
  root.querySelectorAll('.quantity-selector').forEach(box => {
    // Skip if already initialized
    if(box.dataset.initialized === 'true') return;
    box.dataset.initialized = 'true';
    
    const input = box.querySelector('.quantity-input');
    const minusBtn = box.querySelector('.minus');
    const plusBtn = box.querySelector('.plus');
    
    minusBtn?.addEventListener('click', (e) => {
      e.preventDefault();
      const v = parseInt(input.value || '1', 10);
      input.value = Math.max(1, v - 1);
    });
    plusBtn?.addEventListener('click', (e) => {
      e.preventDefault();
      const v = parseInt(input.value || '1', 10);
      input.value = v + 1;
    });
  });
}

function initAddToCartButtons(root=document){
  root.querySelectorAll('.js-cart-form').forEach(form => {
    // Skip if already initialized
    if(form.dataset.initialized === 'true') return;
    form.dataset.initialized = 'true';
    
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      
      const btn = form.querySelector('.js-add-to-cart');
      const quantityInput = form.querySelector('.quantity-input');
      
      // Previne múltiplos envios simultâneos
      if(form._isProcessing) return;
      form._isProcessing = true;
      
      const originalHTML = btn.innerHTML;
      btn.disabled = true;
      
      // Mostra spinner apenas se demorar mais de 200ms (loja pode ser mais lenta)
      let spinnerTimeout;
      spinnerTimeout = setTimeout(() => {
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Adicionando...';
      }, 200);
      
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
        const contentType = response.headers.get('content-type');
        if(contentType && contentType.includes('application/json')) {
          return response.json().then(data => ({ data, isJson: true, ok: response.ok }));
        } else {
          return { data: null, isJson: false, ok: false };
        }
      })
      .then(({ data, isJson, ok }) => {
        clearTimeout(spinnerTimeout);
        btn.innerHTML = originalHTML;
        
        if(isJson && ok && data) {
          // Sucesso - reseta quantidade e mostra notificação
          if(quantityInput) quantityInput.value = '1';
          showToast(data.message || 'Produto adicionado ao carrinho!', 'success');
        } else {
          showToast('Erro ao adicionar ao carrinho', 'danger');
        }
      })
      .catch(error => {
        console.error('Erro ao adicionar ao carrinho:', error);
        clearTimeout(spinnerTimeout);
        btn.innerHTML = originalHTML;
        showToast('Erro ao adicionar ao carrinho', 'danger');
      })
      .finally(() => {
        form._isProcessing = false;
        btn.disabled = false;
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
