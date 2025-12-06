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

  function showFormMessage(form, message, category = 'info'){
    if(!message) return;
    if (window.FormFeedback && typeof window.FormFeedback.showStatus === 'function') {
      window.FormFeedback.showStatus(form, message, category);
    } else {
      showToast(message, category);
    }
  }

  document.addEventListener('submit', async ev => {
    if (ev.defaultPrevented) return;
    const form = ev.target;
    if (!form.matches('form[data-sync]')) return;

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
    let offlineQueued = false;
    try {
      resp = await window.fetchOrQueue(form.action, {method: form.method || 'POST', headers: {'Accept': 'application/json'}, body: data});
    } catch (error) {
      console.error('Erro ao enviar formulário:', error);
      setButtonIdle(submitButton);
      showToast('Não foi possível enviar o formulário. Tente novamente.', 'danger');
      return;
    }

    if (!resp) {
      offlineQueued = true;
      setButtonIdle(submitButton);
    }

    let json = null;
    if (resp) {
      try { json = await resp.json(); } catch(e) {}
    }
    const mainMessage = json && json.message ? json.message : (offlineQueued ? 'Formulário enfileirado para sincronização quando voltar a ficar online.' : undefined);
    const category = json && json.category
      ? json.category
      : (offlineQueued ? 'warning' : (json && json.success === false || (resp && !resp.ok) ? 'danger' : 'success'));
    if (mainMessage) {
      showFormMessage(form, mainMessage, category);
    }
    if (json && Array.isArray(json.messages)) {
      json.messages.forEach(entry => {
        if (!entry) return;
        if (typeof entry === 'string') {
          showFormMessage(form, entry, 'info');
        } else if (entry.message) {
          showFormMessage(form, entry.message, entry.category || 'info');
        }
      });
    }
    const isSuccess = offlineQueued || (resp && resp.ok && !(json && json.success === false));
    if (!isSuccess && !mainMessage && resp && !resp.ok) {
      const fallback = resp.statusText || 'Falha ao processar o formulário.';
      showFormMessage(form, fallback, 'danger');
    }
    if (isSuccess && !offlineQueued) {
      setButtonSuccess(submitButton);
    } else if (!isSuccess || offlineQueued) {
      setButtonIdle(submitButton);
    }
    const evt = new CustomEvent('form-sync-success', {detail: {form, data: json, response: resp, offlineQueued, success: isSuccess}, cancelable: true});
    if (offlineQueued) {
      evt.preventDefault();
    }
    document.dispatchEvent(evt);
    if (!evt.defaultPrevented && !(form.classList && (form.classList.contains('js-tutor-form') || form.id === 'tutor-form'))) {
      location.reload();
    }
  });

  document.addEventListener('form-sync-success', ev => {
    const detail = ev.detail || {};
    const form = detail.form;
    const data = detail.data || {};
    const isQueued = detail.offlineQueued;
    if(!form) return;

    if(form.classList.contains('js-tutor-form')){
      ev.preventDefault();
      const btn=form.querySelector('button[type="submit"]');
      const message = isQueued
        ? 'Cadastro de tutor enfileirado para sincronizar quando estiver online.'
        : (data && data.message) || 'Tutor salvo com sucesso.';
      showFormMessage(form, message, isQueued ? 'info' : 'success');
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
      setButtonIdle(btn);
    } else if(form.id === 'tutor-form'){
      const resp = detail.response;
      if(!(resp && resp.ok) || (data && data.success === false)){
        const message = (data && data.message) || 'Não foi possível salvar o tutor.';
        showFormMessage(form, message, 'danger');
        setButtonIdle(getSubmitButton(form));
        return;
      }
      ev.preventDefault();
      const successMessage = isQueued
        ? 'Alterações do tutor enfileiradas para sincronização offline.'
        : (data && data.message) || 'Tutor salvo com sucesso.';
      showFormMessage(form, successMessage, isQueued ? 'info' : 'success');
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
      setButtonIdle(form.querySelector('button[type="submit"]'));
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

  function buildRemovedStatusBadge(options = {}) {
    const badge = document.createElement('span');
    badge.dataset.removedStatus = 'true';
    badge.classList.add('badge', 'ms-2', 'align-middle');
    const queued = Boolean(options.queued);
    if (queued) {
      badge.classList.add('bg-warning', 'text-dark');
      badge.innerHTML = '<i class="fas fa-cloud-slash me-1"></i>Aguardando sincronização';
      badge.title = 'Remoção pendente de sincronização.';
    } else {
      badge.classList.add('bg-danger-subtle', 'text-danger');
      badge.innerHTML = '<i class="fas fa-trash-alt me-1"></i>Excluído';
      badge.title = 'Remoção concluída.';
    }
    return badge;
  }

  function addRemovedAnimalToList(form, detail = {}){
    const removedWrapper = document.getElementById('removidos-wrapper');
    const removedList = removedWrapper ? removedWrapper.querySelector('.list-group') : null;
    if(!removedList){
      return;
    }

    const animalId = form.dataset.animalId || '';
    const existing = animalId ? removedList.querySelector(`li[data-animal-id="${animalId}"]`) : null;
    const li = existing || document.createElement('li');
    li.className = 'list-group-item d-flex justify-content-between align-items-center';
    if (animalId) li.dataset.animalId = animalId;
    if (existing) li.innerHTML = '';

    const infoSpan = document.createElement('span');
    const nameStrong = document.createElement('strong');
    const animalName = form.dataset.animalName || '';
    const animalSpecies = form.dataset.animalSpecies || '';
    const animalBreed = form.dataset.animalBreed || '';
    nameStrong.textContent = animalName;
    infoSpan.appendChild(nameStrong);
    infoSpan.appendChild(document.createTextNode(` — ${animalSpecies} / ${animalBreed}`));
    infoSpan.appendChild(buildRemovedStatusBadge({queued: detail.offlineQueued}));

    const deleteForm = document.createElement('form');
    deleteForm.action = form.getAttribute('action');
    deleteForm.method = 'POST';
    deleteForm.className = 'js-animal-delete-form d-inline';
    deleteForm.dataset.sync = '';
    deleteForm.dataset.confirm = `Excluir permanentemente ${animalName}?`;
    deleteForm.dataset.animalId = form.dataset.animalId || '';
    deleteForm.dataset.animalName = animalName;
    deleteForm.dataset.animalSpecies = animalSpecies;
    deleteForm.dataset.animalBreed = animalBreed;
    deleteForm.dataset.removedItem = 'true';

    const deleteButton = document.createElement('button');
    deleteButton.type = 'submit';
    deleteButton.className = 'btn btn-sm btn-danger';
    deleteButton.textContent = '❌ Excluir Definitivamente';
    deleteForm.appendChild(deleteButton);

    li.appendChild(infoSpan);
    li.appendChild(deleteForm);
    if (!existing) {
      removedList.appendChild(li);
    }
    removedWrapper.classList.remove('d-none');
  }

  document.addEventListener('form-sync-success', ev => {
    const detail = ev.detail || {};
    const form = detail.form;
    const data = detail.data || {};
    const response = detail.response;
    if(!form || !form.classList.contains('js-animal-delete-form')) return;
    if(ev.defaultPrevented) return;

    if((!response || !response.ok || (data && data.success === false)) && !detail.offlineQueued){
      setButtonIdle(getSubmitButton(form));
      return;
    }

    ev.preventDefault();

    const toastMessage = (data && data.message) || (detail.offlineQueued ? 'Remoção enfileirada para sincronização.' : 'Animal removido.');
    showToast(toastMessage, detail.offlineQueued ? 'warning' : 'success');

    const animalId = form.dataset.animalId;
    const isRemovedItem = form.dataset.removedItem === 'true';
    const rowId = animalId ? `animal-row-${animalId}` : null;
    if (isRemovedItem) {
      const listItem = form.closest('li');
      if (listItem) listItem.remove();
      return;
    }
    if(rowId){
      const row = document.getElementById(rowId);
      if(row) row.remove();
    }

    const tableBody = document.querySelector('#animals-table tbody');
    updateAnimalsEmptyState(tableBody);

    addRemovedAnimalToList(form, detail);
  });
})();
