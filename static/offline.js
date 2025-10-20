(function(){
  const KEY = 'offline-queue';

  const IDEMPOTENCY_FIELD = '_idempotency_key';

  function createIdempotencyKey(){
    if(typeof crypto !== 'undefined' && crypto.randomUUID){
      return crypto.randomUUID();
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }

  function ensureFormToken(form){
    if(!(form instanceof HTMLFormElement)) return null;
    let input = form.querySelector(`input[name="${IDEMPOTENCY_FIELD}"]`);
    if(!input){
      input = document.createElement('input');
      input.type = 'hidden';
      input.name = IDEMPOTENCY_FIELD;
      form.appendChild(input);
    }
    if(!input.value){
      input.value = createIdempotencyKey();
    }
    return input.value;
  }

  function rotateFormToken(form){
    if(!(form instanceof HTMLFormElement)) return;
    const input = form.querySelector(`input[name="${IDEMPOTENCY_FIELD}"]`);
    if(input){
      input.value = createIdempotencyKey();
    }
  }

  // Abort fetch requests only after a generous timeout (ms)
  async function fetchWithTimeout(url, opts={}, timeout=60000){
    if(!timeout){
      return fetch(url, opts);
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    try {
      return await fetch(url, {...opts, signal: ctrl.signal});
    } finally {
      clearTimeout(timer);
    }
  }

  function loadQueue(){
    try { return JSON.parse(localStorage.getItem(KEY)) || []; }
    catch(e){ return []; }
  }
  function saveQueue(q){
    localStorage.setItem(KEY, JSON.stringify(q));
  }

  async function sendQueued(){
    if(!navigator.onLine) return;
    const q = loadQueue();
    while(q.length){
      const item = q[0];
      let body;
      if(item.body && item.body.form){
        body = new FormData();
        item.body.form.forEach(([k,v])=>body.append(k,v));
      } else if(item.body && item.body.json){
        body = JSON.stringify(item.body.json);
      } else if(item.body && item.body.text){
        body = item.body.text;
      }
      try {
        const resp = await fetchWithTimeout(item.url, {method:item.method, headers:item.headers, body});
        if(!resp.ok) throw new Error('fail');
        q.shift();
      } catch(err){
        break;
      }
    }
    saveQueue(q);
  }

  window.fetchOrQueue = async function(url, opts={}){
    const method = opts.method || 'POST';
    const headers = {...(opts.headers || {})};
    let idempotencyKey = headers['X-Idempotency-Key'] || headers['x-idempotency-key'];
    let bodyData = null;
    if(opts.body instanceof FormData){
      if(!opts.body.has(IDEMPOTENCY_FIELD)){
        if(!idempotencyKey){
          idempotencyKey = createIdempotencyKey();
        }
        opts.body.append(IDEMPOTENCY_FIELD, idempotencyKey);
      } else if(!idempotencyKey){
        idempotencyKey = opts.body.get(IDEMPOTENCY_FIELD);
      }
      bodyData = {form:[...opts.body.entries()]};
    } else if(typeof opts.body === 'string'){
      bodyData = {text: opts.body};
    } else if(opts.body){
      if(typeof opts.body === 'object' && opts.body !== null){
        if(!('_idempotency_key' in opts.body)){
          if(!idempotencyKey){
            idempotencyKey = createIdempotencyKey();
          }
          opts.body._idempotency_key = idempotencyKey;
        } else if(!idempotencyKey){
          idempotencyKey = opts.body._idempotency_key;
        }
      }
      bodyData = {json: opts.body};
    }
    if(!idempotencyKey){
      idempotencyKey = createIdempotencyKey();
    }
    headers['X-Idempotency-Key'] = idempotencyKey;
    opts = {...opts, headers};
    if(navigator.onLine){
      try {
        const resp = await fetchWithTimeout(url, opts);
        // Retorna a resposta mesmo que contenha erro de validação
        if (resp) return resp;
      } catch(e){ /* fallthrough */ }
    }
    const q = loadQueue();
    q.push({url, method, headers, body:bodyData});
    saveQueue(q);
    return null;
  };

  window.addEventListener('online', sendQueued);
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('form[data-sync]').forEach(ensureFormToken);
    sendQueued();
  });

  function showToast(message, category='success'){
    const toastEl = document.getElementById('actionToast');
    if(!toastEl) return;
    toastEl.querySelector('.toast-body').textContent = message;
    toastEl.classList.remove('bg-danger','bg-info','bg-success');
    toastEl.classList.add('bg-' + category);
    bootstrap.Toast.getOrCreateInstance(toastEl).show();
  }

  document.addEventListener('submit', async ev => {
    if (ev.defaultPrevented) return;
    const form = ev.target;
    if (!form.matches('form[data-sync]')) return;

    // Mensagem de confirmação para formulários de histórico
    if (form.classList.contains('delete-history-form')) {
      const msg = form.dataset.confirm || 'Excluir este registro?';
      if (!window.confirm(msg)) {
        ev.preventDefault();
        ev.stopPropagation();
        return;
      }
    }

    if (!form.checkValidity()) {
      ev.preventDefault();
      ev.stopPropagation();
      form.classList.add('was-validated');
      return;
    }

    ev.preventDefault();
    const token = ensureFormToken(form);
    const data = new FormData(form);
    if(token && !data.has(IDEMPOTENCY_FIELD)){
      data.append(IDEMPOTENCY_FIELD, token);
    }
    const resp = await window.fetchOrQueue(form.action, {method: form.method || 'POST', headers: {'Accept': 'application/json'}, body: data});
    if (resp) {
      let json = null;
      try { json = await resp.json(); } catch(e) {}
      if (json && json.message) {
        const category = json.category || (json.success === false || !resp.ok ? 'danger' : 'success');
        showToast(json.message, category);
      }
      const evt = new CustomEvent('form-sync-success', {detail: {form, data: json, response: resp}, cancelable: true});
      document.dispatchEvent(evt);
      if (!evt.defaultPrevented) {
        location.reload();
      }
    }
    rotateFormToken(form);
  });

  document.addEventListener('form-sync-success', ev => {
    const detail = ev.detail || {};
    const form = detail.form;
    const data = detail.data || {};
    if(!form) return;

    if(form.classList.contains('js-tutor-form')){
      ev.preventDefault();
      if(data.html){
        const cont=document.getElementById('tutores-adicionados');
        if(cont) cont.innerHTML=data.html;
      }
      if (data && data.tutor && typeof document !== 'undefined') {
        const tutorId = String(data.tutor.id);
        const tutorLabel = data.tutor.display_name || data.tutor.name || `Tutor #${tutorId}`;
        const selects = document.querySelectorAll('[data-appointment-tutor-select]');
        selects.forEach((select) => {
          if (!(select instanceof HTMLSelectElement)) return;
          let option = Array.from(select.options).find((opt) => opt.value === tutorId);
          if (!option) {
            option = document.createElement('option');
            option.value = tutorId;
            select.appendChild(option);
          }
          option.textContent = tutorLabel;
          option.dataset.tutorId = tutorId;
          option.dataset.tutorName = tutorLabel;
          select.value = tutorId;
          select.dispatchEvent(new Event('change', { bubbles: true }));
        });
      }
      form.reset();
      const btn=form.querySelector('button[type="submit"]');
      if(btn && btn.dataset.original){
        btn.disabled=false;
        btn.innerHTML=btn.dataset.original;
      }
    } else if(form.classList.contains('js-animal-form')){
      ev.preventDefault();
      if(data.html){
        const cont=document.getElementById('animais-adicionados');
        if(cont) {
          cont.innerHTML=data.html;
          if (typeof window.initBootstrapDropdowns === 'function') {
            window.initBootstrapDropdowns(cont);
          }
        }
      }
      form.reset();
      const btn=form.querySelector('button[type="submit"]');
      if(btn && btn.dataset.original){
        btn.disabled=false;
        btn.innerHTML=btn.dataset.original;
      }
    }
  });

  // Atualiza automaticamente o contêiner do histórico após exclusões
  document.addEventListener('form-sync-success', ev => {
    const detail = ev.detail || {};
    const form = detail.form;
    const data = detail.data;
    if (!form || !form.classList.contains('delete-history-form')) return;

    ev.preventDefault();
    if (data && data.html && form.dataset.target) {
      const container = document.getElementById(form.dataset.target);
      if (container) {
        container.innerHTML = data.html;
        if (typeof window.initBootstrapDropdowns === 'function') {
          window.initBootstrapDropdowns(container);
        }
      }
    }
  });
})();
