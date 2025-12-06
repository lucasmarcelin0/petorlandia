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

  function renderTutorPanelMessage(root, message, category = 'success') {
    const container = root instanceof Element ? root : document.getElementById('tutores-adicionados');
    if (!container || !message) return;

    let alert = container.querySelector('[data-tutor-panel-message]');
    if (!alert) {
      alert = document.createElement('div');
      alert.dataset.tutorPanelMessage = 'true';
      container.prepend(alert);
    }

    alert.className = `alert alert-${category} d-flex align-items-center gap-2 mt-0 mb-3`;
    alert.textContent = message;

    window.clearTimeout(Number(alert.dataset.timerId || 0));
    const timerId = window.setTimeout(() => {
      alert.remove();
    }, 5000);
    alert.dataset.timerId = timerId;
  }

  async function refreshTutorListingPanel(panelContainer, panelElement, panelParams = {}) {
    const container = panelContainer || document.getElementById('tutores-adicionados');
    const panel = panelElement || (container ? container.querySelector('[data-listing-panel="tutors"]') : null) || document.querySelector('[data-listing-panel="tutors"]');
    if (!container || !panel) return false;

    const scopeParam = panel.dataset.scopeParam || 'scope';
    const searchParam = panel.dataset.searchParam || 'tutor_search';
    const sortParam = panel.dataset.sortParam || 'tutor_sort';
    const pageParam = panel.dataset.pageParam || 'page';
    const filterInput = panel.querySelector('#tutor-filter');
    const sortSelect = panel.querySelector('#tutor-sort');

    const fetchUrl = new URL(panel.dataset.fetchUrl || window.location.pathname, window.location.origin);
    const scopeValue = panelParams.scope || panel.dataset.scope || 'all';
    const pageValue = panelParams.page || panel.dataset.page || '1';
    const searchValue = panelParams.search ?? (filterInput ? filterInput.value.trim() : '');
    const sortValue = panelParams.sort || (sortSelect ? sortSelect.value : panel.dataset.defaultSort || 'name_asc');

    if (scopeValue) fetchUrl.searchParams.set(scopeParam, scopeValue);
    if (pageValue) fetchUrl.searchParams.set(pageParam, pageValue);
    if (searchValue) fetchUrl.searchParams.set(searchParam, searchValue);
    if (sortValue) fetchUrl.searchParams.set(sortParam, sortValue);

    try {
      const resp = await fetch(fetchUrl.toString(), {
        headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      });
      if (!resp.ok) return false;
      const payload = await resp.json();
      if (payload && payload.html) {
        container.innerHTML = payload.html;
        return true;
      }
    } catch (error) {
      console.error('Não foi possível atualizar o painel de tutores.', error);
    }

    return false;
  }

  function insertTutorCardFromData(panelContainer, tutor) {
    const container = panelContainer || document.getElementById('tutores-adicionados') || document;
    const cardsContainer = container.querySelector('#tutor-cards');
    if (!cardsContainer || !tutor) return false;

    const col = document.createElement('div');
    col.className = 'col-md-6 d-flex';
    col.dataset.name = (tutor.name || '').toLowerCase();
    col.dataset.status = 'internal';
    col.dataset.cpf = tutor.cpf || '';
    col.dataset.phone = tutor.phone || '';
    if (tutor.date_of_birth) col.dataset.dob = tutor.date_of_birth;

    const card = document.createElement('div');
    card.className = 'card shadow-sm rounded-4 h-100 flex-fill position-relative overflow-hidden profile-card profile-card--internal';

    const media = document.createElement('div');
    media.className = 'profile-card-media profile-card-media--tutor';
    media.style.setProperty('--offset-x', `${tutor.photo_offset_x || 0}px`);
    media.style.setProperty('--offset-y', `${tutor.photo_offset_y || 0}px`);
    media.style.setProperty('--rotation', `${tutor.photo_rotation || 0}deg`);
    media.style.setProperty('--zoom', `${tutor.photo_zoom || 1}`);

    if (tutor.profile_photo) {
      const img = document.createElement('img');
      img.src = tutor.profile_photo;
      img.alt = `Foto de ${tutor.name || tutor.display_name || 'tutor'}`;
      img.className = 'profile-card-photo';
      img.loading = 'lazy';
      media.appendChild(img);
    } else {
      const placeholder = document.createElement('div');
      placeholder.className = 'profile-card-placeholder';
      const initial = document.createElement('span');
      initial.textContent = (tutor.name || '?').trim().charAt(0).toUpperCase();
      placeholder.appendChild(initial);
      media.appendChild(placeholder);
    }

    const cardBody = document.createElement('div');
    cardBody.className = 'card-body d-flex flex-column gap-3';
    const titleWrapper = document.createElement('div');
    const titleRow = document.createElement('div');
    titleRow.className = 'd-flex justify-content-between align-items-start mb-2';
    const title = document.createElement('h5');
    title.className = 'card-title mb-0';
    title.textContent = tutor.name || tutor.display_name || `Tutor #${tutor.id}`;
    titleRow.appendChild(title);

    if (tutor.created_at) {
      const badge = document.createElement('span');
      badge.className = 'badge text-bg-light border text-muted';
      const created = new Date(tutor.created_at);
      badge.textContent = `Desde ${created.toLocaleDateString('pt-BR')}`;
      titleRow.appendChild(badge);
    }

    titleWrapper.appendChild(titleRow);
    const chipRow = document.createElement('div');
    chipRow.className = 'status-chip-group d-flex flex-wrap gap-2';
    const chip = document.createElement('span');
    chip.className = 'status-chip status-chip--internal';
    chip.innerHTML = '<i class="fa-solid fa-building"></i><span>Interno da clínica</span>';
    chipRow.appendChild(chip);
    titleWrapper.appendChild(chipRow);
    cardBody.appendChild(titleWrapper);

    const footer = document.createElement('div');
    footer.className = 'card-footer bg-white border-0 pt-0 pb-4 px-4 mt-auto';
    const actions = document.createElement('div');
    actions.className = 'd-flex flex-wrap gap-2';
    const detailLink = document.createElement('a');
    detailLink.href = (tutor.urls && tutor.urls.detail) || '#';
    detailLink.className = 'btn btn-sm btn-outline-dark flex-fill';
    detailLink.textContent = '📋 Ver Ficha';
    actions.appendChild(detailLink);
    footer.appendChild(actions);

    card.appendChild(media);
    card.appendChild(cardBody);
    card.appendChild(footer);
    col.appendChild(card);
    cardsContainer.prepend(col);
    return true;
  }

  document.addEventListener('form-sync-success', async ev => {
    const detail = ev.detail || {};
    const form = detail.form;
    const data = detail.data || {};
    if(!form) return;

    if(form.classList.contains('js-tutor-form')){
      ev.preventDefault();
      const cont=document.getElementById('tutores-adicionados');
      const successMessage = data.message || 'Tutor criado com sucesso!';
      if(data.html){
        if(cont) cont.innerHTML=data.html;
      } else {
        const refreshed = await refreshTutorListingPanel(cont, cont ? cont.querySelector('[data-listing-panel="tutors"]') : null, data.panel_params);
        if(!refreshed && data.tutor){
          insertTutorCardFromData(cont, data.tutor);
        }
      }
      renderTutorPanelMessage(cont, successMessage, data.category || 'success');
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
