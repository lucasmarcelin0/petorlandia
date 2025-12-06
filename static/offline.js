(function(){
  const KEY = 'offline-queue';
  const BUTTON_RESET_DELAY = 2000;
  const DEFAULT_LOADING_TIMEOUT = 5000;
  const DEFAULT_TIMEOUT_MESSAGE = 'O tempo limite foi atingido. Reativamos o botão para que você possa tentar novamente.';

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

  function parseTimeout(value){
    if(value == null) return undefined;
    if(typeof value === 'string'){
      const trimmed = value.trim();
      if(trimmed === '') return undefined;
      const lowered = trimmed.toLowerCase();
      if(['false','off','no','none','disabled','disable','0'].includes(lowered)){
        return 0;
      }
    }
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : undefined;
  }

  function resolveLoadingTimeout(button, form){
    const fromButton = button ? parseTimeout(button.dataset.loadingTimeout) : undefined;
    if(typeof fromButton !== 'undefined') return fromButton;
    const fromForm = form ? parseTimeout(form.dataset.loadingTimeout) : undefined;
    if(typeof fromForm !== 'undefined') return fromForm;
    return DEFAULT_LOADING_TIMEOUT;
  }

  function resolveTimeoutMessage(button, form){
    if(button && typeof button.hasAttribute === 'function' && button.hasAttribute('data-timeout-message')){
      return button.dataset.timeoutMessage || '';
    }
    if(form && typeof form.hasAttribute === 'function' && form.hasAttribute('data-timeout-message')){
      return form.dataset.timeoutMessage || '';
    }
    return DEFAULT_TIMEOUT_MESSAGE;
  }

  function clearLoadingWatchdog(button){
    if(!button || !button.dataset.loadingWatchdog) return;
    clearTimeout(Number(button.dataset.loadingWatchdog));
    delete button.dataset.loadingWatchdog;
  }

  function setButtonLoading(button, form){
    if(!button) return;
    if (window.FormFeedback && typeof window.FormFeedback.setLoading === 'function') {
      const options = { form };
      const timeout = resolveLoadingTimeout(button, form);
      if (typeof timeout !== 'undefined') {
        options.loadingTimeout = timeout;
      }
      const message = resolveTimeoutMessage(button, form);
      if (typeof message !== 'undefined') {
        options.timeoutMessage = message;
      }
      window.FormFeedback.setLoading(button, options);
      return;
    }
    ensureOriginalLabel(button);
    clearButtonTimer(button);
    clearLoadingWatchdog(button);
    if(button.dataset.loadingText){
      button.innerHTML = button.dataset.loadingText;
    }
    button.disabled = true;
    button.classList.add('is-loading');
    const timeout = resolveLoadingTimeout(button, form);
    if(Number.isFinite(timeout) && timeout > 0){
      const timer = setTimeout(() => {
        delete button.dataset.loadingWatchdog;
        button.disabled = false;
        button.classList.remove('is-loading');
        if(button.dataset.original){
          button.innerHTML = button.dataset.original;
        }
        const message = resolveTimeoutMessage(button, form);
        if(message){
          showToast(message, 'warning');
        }
        const detail = { button, form, message, reason: 'loading-timeout' };
        const evt = new CustomEvent('form-feedback-timeout', { detail, bubbles: true });
        button.dispatchEvent(evt);
      }, timeout);
      button.dataset.loadingWatchdog = String(timer);
    }
  }

  function buildTutorPayloadFromForm(form){
    if(!form || form.id !== 'tutor-form') return null;
    const nameInput = form.querySelector('input[name="name"]');
    const emailInput = form.querySelector('input[name="email"]');
    const photoPreview = document.querySelector('#profile_photo-preview img') || document.getElementById('preview-tutor');
    const payload = {
      id: form.dataset.tutorId ? Number(form.dataset.tutorId) : undefined,
      name: nameInput ? nameInput.value.trim() : undefined,
      email: emailInput ? emailInput.value.trim() : undefined,
    };
    if(photoPreview){
      payload.profile_photo = photoPreview.getAttribute('src') || undefined;
      payload.photo_offset_x = photoPreview.dataset.offsetX ? Number(photoPreview.dataset.offsetX) : undefined;
      payload.photo_offset_y = photoPreview.dataset.offsetY ? Number(photoPreview.dataset.offsetY) : undefined;
      payload.photo_rotation = photoPreview.dataset.rotation ? Number(photoPreview.dataset.rotation) : undefined;
      payload.photo_zoom = photoPreview.dataset.zoom ? Number(photoPreview.dataset.zoom) : undefined;
    }
    return payload;
  }

  function setButtonIdle(button){
    if(!button) return;
    if (window.FormFeedback && typeof window.FormFeedback.setIdle === 'function') {
      window.FormFeedback.setIdle(button);
      return;
    }
    clearButtonTimer(button);
    clearLoadingWatchdog(button);
    button.disabled = false;
    button.classList.remove('is-loading');
    if(button.dataset.original){
      button.innerHTML = button.dataset.original;
    }
  }

  function setButtonSuccess(button){
    if(!button) return;
    if (window.FormFeedback && typeof window.FormFeedback.setSuccess === 'function') {
      window.FormFeedback.setSuccess(button);
      return;
    }
    ensureOriginalLabel(button);
    clearButtonTimer(button);
    clearLoadingWatchdog(button);
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

    if (window.FormFeedback && typeof window.FormFeedback.clearFieldErrors === 'function') {
      window.FormFeedback.clearFieldErrors(form);
    }

    const submitButton = getSubmitButton(form);

    const confirmationMessage = form.dataset.confirm || (form.classList.contains('delete-history-form') ? 'Excluir este registro?' : null);
    if (confirmationMessage && !window.confirm(confirmationMessage)) {
      ev.preventDefault();
      ev.stopPropagation();
      return;
    }

    if (!form.checkValidity()) {
      ev.preventDefault();
      ev.stopPropagation();
      form.classList.add('was-validated');
      return;
    }

    ev.preventDefault();
    setButtonLoading(submitButton, form);
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

    let json = null;
    let queued = false;
    if (!resp) {
      queued = true;
    }

    try { json = resp ? await resp.json() : null; } catch(e) {}
    if (!json) { json = {}; }

    if (json.errors && window.FormFeedback && typeof window.FormFeedback.applyFieldErrors === 'function') {
      window.FormFeedback.applyFieldErrors(form, json.errors);
    }
    const responseOk = resp ? resp.ok : true;
    let toastShown = false;
    if (json && json.message) {
      const category = json.category || (json.success === false || !responseOk ? 'danger' : 'success');
      showToast(json.message, category);
      toastShown = true;
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
    const isSuccess = responseOk && !(json && json.success === false);
    if (isSuccess) {
      setButtonSuccess(submitButton);
    } else {
      setButtonIdle(submitButton);
    }
    const evt = new CustomEvent('form-sync-success', {detail: {form, data: json, response: resp, queued, toastShown}, cancelable: true});
    document.dispatchEvent(evt);
  });

  document.addEventListener('form-sync-success', ev => {
    const detail = ev.detail || {};
    const form = detail.form;
    const data = detail.data || {};
    const toastAlreadyShown = Boolean(detail.toastShown);
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
      const isQueued = detail.queued;
      const success = (isQueued || (resp && resp.ok)) && !(data && data.success === false);
      if(!success){
        setButtonIdle(getSubmitButton(form));
        return;
      }
      ev.preventDefault();
      setButtonSuccess(getSubmitButton(form));
      const tutor = data && data.tutor ? data.tutor : buildTutorPayloadFromForm(form);
      if(tutor){
        const preview = document.getElementById('preview-tutor');
        if(preview){
          if(tutor.profile_photo){
            const previewSrc = tutor.profile_photo && typeof cacheBust === 'function' && !String(tutor.profile_photo).startsWith('data:')
              ? cacheBust(tutor.profile_photo)
              : tutor.profile_photo;
            preview.src = previewSrc;
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
          const cropperSrc = tutor.profile_photo && typeof cacheBust === 'function' && !String(tutor.profile_photo).startsWith('data:')
            ? cacheBust(tutor.profile_photo)
            : tutor.profile_photo;
          cropperPreview.src = cropperSrc;
        }
        const animalsHeading = document.getElementById('animais-heading');
        if(animalsHeading && tutor.name){
          const firstName = tutor.name.trim().split(/\s+/)[0] || tutor.name.trim();
          animalsHeading.textContent = `🐾 Animais de ${firstName}`;
        }
      }
      const headingMessage = data && data.message
        ? data.message
        : (isQueued ? 'Alterações serão sincronizadas' : 'Alterações aplicadas');
      if(!toastAlreadyShown || isQueued){
        showToast(headingMessage, isQueued ? 'info' : 'success');
      }
      if(!isQueued && window.FormFeedback && typeof window.FormFeedback.clearFieldErrors === 'function'){
        window.FormFeedback.clearFieldErrors(form);
      }
    } else if(form.id === 'consulta-form'){
      ev.preventDefault();
      const container = document.getElementById('historico-consultas');
      const isQueued = detail.queued;
      if(container && data && data.html){
        container.innerHTML = data.html;
      }
      if(container){
        let badge = container.querySelector('[data-sync-alert="consulta"]');
        if(isQueued){
          if(!badge){
            badge = document.createElement('div');
            badge.className = 'alert alert-warning mt-3';
            badge.dataset.syncAlert = 'consulta';
            container.appendChild(badge);
          }
          badge.textContent = 'Consulta salva offline. Será sincronizada quando a conexão voltar.';
        } else if(badge){
          badge.remove();
        }
      }
      const message = (data && (data.message || data.error)) || (detail.queued ? 'Consulta salva offline.' : 'Consulta salva com sucesso!');
      if(!toastAlreadyShown || detail.queued){
        showToast(message, detail.queued ? 'info' : 'success');
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

  function updateAnimalsEmptyState(tableBody){
    if(!tableBody) return;
    const hasAnimalRows = tableBody.querySelector('tr[id^="animal-row-"]');
    let emptyStateRow = tableBody.querySelector('tr[data-empty-state]');
    if(hasAnimalRows){
      if(emptyStateRow) emptyStateRow.remove();
      return;
    }
    if(!emptyStateRow){
      emptyStateRow = document.createElement('tr');
      emptyStateRow.dataset.emptyState = 'true';
      const cell = document.createElement('td');
      cell.colSpan = 4;
      cell.className = 'text-muted text-center';
      cell.textContent = 'Nenhum animal cadastrado.';
      emptyStateRow.appendChild(cell);
      tableBody.appendChild(emptyStateRow);
    }
  }

  document.addEventListener('form-sync-success', ev => {
    const detail = ev.detail || {};
    const form = detail.form;
    const data = detail.data || {};
    const response = detail.response;
    if(!form || !form.classList.contains('js-animal-delete-form')) return;
    if(ev.defaultPrevented) return;

    if(!response || !response.ok || (data && data.success === false)){
      setButtonIdle(getSubmitButton(form));
      return;
    }

    ev.preventDefault();

    const animalId = form.dataset.animalId;
    const rowId = animalId ? `animal-row-${animalId}` : null;
    if(rowId){
      const row = document.getElementById(rowId);
      if(row) row.remove();
    }

    const tableBody = document.querySelector('#animals-table tbody');
    updateAnimalsEmptyState(tableBody);

    const removedWrapper = document.getElementById('removidos-wrapper');
    const removedList = removedWrapper ? removedWrapper.querySelector('.list-group') : null;
    if(removedList){
      const li = document.createElement('li');
      li.className = 'list-group-item d-flex justify-content-between align-items-center';

      const infoSpan = document.createElement('span');
      const nameStrong = document.createElement('strong');
      const animalName = form.dataset.animalName || '';
      const animalSpecies = form.dataset.animalSpecies || '';
      const animalBreed = form.dataset.animalBreed || '';
      nameStrong.textContent = animalName;
      infoSpan.appendChild(nameStrong);
      infoSpan.appendChild(document.createTextNode(` — ${animalSpecies} / ${animalBreed}`));

      const deleteForm = document.createElement('form');
      deleteForm.action = form.getAttribute('action');
      deleteForm.method = 'POST';
      deleteForm.className = 'd-inline';
      deleteForm.addEventListener('submit', evt => {
        if(!window.confirm(`Excluir permanentemente ${animalName}?`)){
          evt.preventDefault();
        }
      });

      const deleteButton = document.createElement('button');
      deleteButton.type = 'submit';
      deleteButton.className = 'btn btn-sm btn-danger';
      deleteButton.textContent = '❌ Excluir Definitivamente';
      deleteForm.appendChild(deleteButton);

      li.appendChild(infoSpan);
      li.appendChild(deleteForm);
      removedList.appendChild(li);
      removedWrapper.classList.remove('d-none');
    }
  });
})();
