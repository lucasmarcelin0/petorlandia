(function(){
  const KEY = 'offline-queue';
  const BUTTON_RESET_DELAY = 2000;

  function getSubmitButton(form){
    if(!form) return null;
    return form.querySelector('button[type="submit"], button:not([type])');
  }

  function clearButtonTimer(button){
    if(!button || !button.dataset.resetTimer) return;
    clearTimeout(Number(button.dataset.resetTimer));
    delete button.dataset.resetTimer;
  }

  function ensureOriginalLabel(button){
    if(!button) return;
    if(!button.dataset.original){
      button.dataset.original = button.innerHTML;
    }
  }

  function setButtonLoading(button){
    if(!button) return;
    ensureOriginalLabel(button);
    clearButtonTimer(button);
    if(button.dataset.loadingText){
      button.innerHTML = button.dataset.loadingText;
    }
    button.disabled = true;
    button.classList.add('is-loading');
  }

  function setButtonIdle(button){
    if(!button) return;
    clearButtonTimer(button);
    button.disabled = false;
    button.classList.remove('is-loading');
    if(button.dataset.original){
      button.innerHTML = button.dataset.original;
    }
  }

  function setButtonSuccess(button){
    if(!button) return;
    ensureOriginalLabel(button);
    clearButtonTimer(button);
    button.disabled = false;
    button.classList.remove('is-loading');
    const successText = button.dataset.successText;
    if(successText){
      button.innerHTML = successText;
      const delay = Number(button.dataset.successDelay || BUTTON_RESET_DELAY);
      const timer = setTimeout(() => {
        if(button.dataset.original){
          button.innerHTML = button.dataset.original;
        }
        delete button.dataset.resetTimer;
      }, Number.isFinite(delay) ? delay : BUTTON_RESET_DELAY);
      button.dataset.resetTimer = String(timer);
    } else if(button.dataset.original){
      button.innerHTML = button.dataset.original;
    }
  }

  function cacheBust(url){
    if(!url) return url;
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}_=${Date.now()}`;
  }

  function coalesce(value, fallback){
    return value == null ? fallback : value;
  }

  // Abort fetch requests if no response within given timeout (ms)
  async function fetchWithTimeout(url, opts={}, timeout=2000){
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
    const headers = opts.headers || {};
    let bodyData = null;
    if(opts.body instanceof FormData){
      bodyData = {form:[...opts.body.entries()]};
    } else if(typeof opts.body === 'string'){
      bodyData = {text: opts.body};
    } else if(opts.body){
      bodyData = {json: opts.body};
    }
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
  document.addEventListener('DOMContentLoaded', sendQueued);

  function normalizeCategory(category){
    if (!category) return 'success';
    const normalized = category.toLowerCase();
    if (normalized === 'error') return 'danger';
    const allowed = ['success','danger','warning','info','primary','secondary','dark','light'];
    return allowed.includes(normalized) ? normalized : 'info';
  }

  function showToast(message, category='success'){
    const toastEl = document.getElementById('actionToast');
    if(!toastEl) return;
    toastEl.querySelector('.toast-body').textContent = message;
    toastEl.classList.remove('bg-danger','bg-info','bg-success','bg-warning','bg-primary','bg-secondary','bg-dark');
    toastEl.classList.add('bg-' + normalizeCategory(category));
    bootstrap.Toast.getOrCreateInstance(toastEl).show();
  }

  document.addEventListener('submit', async ev => {
    if (ev.defaultPrevented) return;
    const form = ev.target;
    if (!form.matches('form[data-sync]')) return;

    const submitButton = getSubmitButton(form);

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
    setButtonLoading(submitButton);
    const data = new FormData(form);
    let resp = null;
    try {
      resp = await window.fetchOrQueue(form.action, {method: form.method || 'POST', headers: {'Accept': 'application/json'}, body: data});
    } catch (error) {
      console.error('Erro ao enviar formulário:', error);
      setButtonIdle(submitButton);
      showToast('Não foi possível enviar o formulário. Tente novamente.', 'danger');
      return;
    }

    if (!resp) {
      setButtonIdle(submitButton);
      showToast('Formulário salvo para sincronização quando voltar a ficar online.', 'info');
      return;
    }

    let json = null;
    try { json = await resp.json(); } catch(e) {}
    if (json && json.message) {
      const category = json.category || (json.success === false || !resp.ok ? 'danger' : 'success');
      showToast(json.message, category);
    }
    if (json && Array.isArray(json.messages)) {
      json.messages.forEach(entry => {
        if (!entry) return;
        if (typeof entry === 'string') {
          showToast(entry, 'info');
        } else if (entry.message) {
          showToast(entry.message, entry.category || 'info');
        }
      });
    }
    const isSuccess = resp.ok && !(json && json.success === false);
    if (isSuccess) {
      setButtonSuccess(submitButton);
    } else {
      setButtonIdle(submitButton);
    }
    const evt = new CustomEvent('form-sync-success', {detail: {form, data: json, response: resp}, cancelable: true});
    document.dispatchEvent(evt);
    if (!evt.defaultPrevented) {
      location.reload();
    }
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
      if (data.redirect_url) {
        window.location.assign(data.redirect_url);
        return;
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
    } else if(form.id === 'tutor-form'){
      const resp = detail.response;
      if(!(resp && resp.ok) || (data && data.success === false)){
        setButtonIdle(getSubmitButton(form));
        return;
      }
      ev.preventDefault();
      setButtonSuccess(getSubmitButton(form));
      const tutor = data ? data.tutor : null;
      if(tutor){
        const preview = document.getElementById('preview-tutor');
        if(preview){
          if(tutor.profile_photo){
            preview.src = cacheBust(tutor.profile_photo);
            preview.classList.remove('d-none');
          } else {
            preview.classList.add('d-none');
          }
          if(typeof tutor.photo_offset_x !== 'undefined') preview.dataset.offsetX = coalesce(tutor.photo_offset_x, 0);
          if(typeof tutor.photo_offset_y !== 'undefined') preview.dataset.offsetY = coalesce(tutor.photo_offset_y, 0);
          if(typeof tutor.photo_rotation !== 'undefined') preview.dataset.rotation = coalesce(tutor.photo_rotation, 0);
          if(typeof tutor.photo_zoom !== 'undefined') preview.dataset.zoom = coalesce(tutor.photo_zoom, 1);
          if(typeof updateAvatarTransform === 'function'){
            const offsetX = parseFloat(preview.dataset.offsetX) || 0;
            const offsetY = parseFloat(preview.dataset.offsetY) || 0;
            const rotation = parseFloat(preview.dataset.rotation) || 0;
            const zoom = parseFloat(preview.dataset.zoom) || 1;
            updateAvatarTransform(preview, offsetX, offsetY, rotation, zoom);
          }
        }
        const cropperPreview = document.querySelector('#profile_photo-preview img');
        if(cropperPreview && tutor.profile_photo){
          cropperPreview.src = cacheBust(tutor.profile_photo);
        }
        const animalsHeading = document.getElementById('animais-heading');
        if(animalsHeading && tutor.name){
          const firstName = tutor.name.trim().split(/\s+/)[0] || tutor.name.trim();
          animalsHeading.textContent = `🐾 Animais de ${firstName}`;
        }
      }
    } else if(form.classList.contains('js-animal-form')){
      ev.preventDefault();
      if(data.html){
        const cont=document.getElementById('animais-adicionados');
        if(cont) cont.innerHTML=data.html;
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
      }
    }
  });
})();
