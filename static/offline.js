(function(){
  const KEY = 'offline-queue';
  const DEFAULT_FETCH_TIMEOUT = 10000;

  function getSubmitButton(form){
    if (window.FormFeedback && typeof window.FormFeedback.getButton === 'function') {
      return window.FormFeedback.getButton(form);
    }
    if(!form) return null;
    return form.querySelector('button[type="submit"], button:not([type])');
  }

  function setFeedbackLoading(button, options = {}) {
    const feedback = window.FormFeedback;
    if (feedback && typeof feedback.setLoading === 'function') {
      feedback.setLoading(button, options);
    }
  }

  function setFeedbackIdle(button) {
    const feedback = window.FormFeedback;
    if (feedback && typeof feedback.setIdle === 'function') {
      feedback.setIdle(button);
    }
  }

  function setFeedbackSuccess(button, options) {
    const feedback = window.FormFeedback;
    if (feedback && typeof feedback.setSuccess === 'function') {
      feedback.setSuccess(button, options);
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

  function resolveFetchTimeout(form){
    if(!form) return DEFAULT_FETCH_TIMEOUT;
    const value = parseTimeout(form.dataset.fetchTimeout || form.dataset.requestTimeout || form.dataset.syncTimeout);
    return typeof value !== 'undefined' ? value : DEFAULT_FETCH_TIMEOUT;
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
  async function fetchWithTimeout(url, opts={}, timeout=DEFAULT_FETCH_TIMEOUT){
    if(!Number.isFinite(timeout) || timeout <= 0){
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

  function isAuthUrl(url){
    if(!url) return false;
    try {
      const normalized = new URL(url, window.location.origin);
      return ['login', 'register', 'logout'].some(segment => normalized.pathname.endsWith(`/${segment}`));
    } catch(err){
      return false;
    }
  }

  function loadQueue(){
    try {
      const raw = JSON.parse(localStorage.getItem(KEY)) || [];
      // Evita replays infinitos de ações de autenticação (ex: /login) que sempre
      // falham offline e retornam 400 quando reenviadas.
      const filtered = raw.filter(item => item && item.url && !isAuthUrl(item.url));
      if(filtered.length !== raw.length){
        saveQueue(filtered);
      }
      return filtered;
    }
    catch(e){ return []; }
  }
  function saveQueue(q){
    localStorage.setItem(KEY, JSON.stringify(q));
  }

  let offlineNoticeShown = false;
  function notifyOfflineQueued(form){
    if(offlineNoticeShown) return;
    offlineNoticeShown = true;
    // Intentionally silent: avoid showing popups/toasts when a request is queued offline.
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
        if(resp && resp.status >= 400 && resp.status < 500){
          // Requests que sempre retornam 4xx (ex.: /login sem credenciais) não devem
          // ficar em loop. Descarta e segue com a fila.
          q.shift();
          continue;
        }
        if(!resp || !resp.ok) throw new Error('fail');
        q.shift();
      } catch(err){
        break;
      }
    }
    saveQueue(q);
  }

  window.fetchOrQueue = async function(url, opts={}){
    const { timeout, ...fetchOpts } = opts;
    const method = fetchOpts.method || 'POST';
    const headers = fetchOpts.headers || {};
    let bodyData = null;
    if(fetchOpts.body instanceof FormData){
      bodyData = {form:[...fetchOpts.body.entries()]};
    } else if(typeof fetchOpts.body === 'string'){
      bodyData = {text: fetchOpts.body};
    } else if(fetchOpts.body){
      bodyData = {json: fetchOpts.body};
    }
    const effectiveTimeout = Number.isFinite(timeout) ? timeout : DEFAULT_FETCH_TIMEOUT;
    const online = navigator.onLine !== false;

    if(online){
      try {
        const resp = await fetchWithTimeout(url, fetchOpts, effectiveTimeout);
        return { response: resp, queued: false };
      } catch(e){
        if (e && e.name === 'AbortError') {
          const timeoutError = new Error('Tempo limite ao enviar a requisição.');
          timeoutError.name = 'FetchTimeoutError';
          timeoutError.cause = e;
          throw timeoutError;
        }

        // Se a conexão caiu entre o clique e o envio, trate como offline
        const q = loadQueue();
        q.push({url, method, headers, body:bodyData});
        saveQueue(q);
        notifyOfflineQueued();
        return { response: null, queued: true };
      }
    }

    const q = loadQueue();
    q.push({url, method, headers, body:bodyData});
    saveQueue(q);
    notifyOfflineQueued();
    return { response: null, queued: true };
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
    const feedback = window.FormFeedback;

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
    const performSync = async () => {
      const data = new FormData(form);
      const fetchTimeout = resolveFetchTimeout(form);
      let resp = null;
      let offlineQueued = false;

      const result = await window.fetchOrQueue(form.action, {method: form.method || 'POST', headers: {'Accept': 'application/json'}, body: data, timeout: fetchTimeout});
      resp = result ? result.response : null;
      offlineQueued = Boolean(result && result.queued);

      if (offlineQueued) {
        notifyOfflineQueued(form);
      }

      let json = null;
      if (resp) {
        try { json = await resp.json(); } catch(e) {}
      }
      const mainMessage = json && json.message ? json.message : undefined;
      const category = json && json.category
        ? json.category
        : (json && json.success === false || (resp && !resp.ok) ? 'danger' : 'success');
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

      const evt = new CustomEvent('form-sync-success', {detail: {form, data: json, response: resp, offlineQueued, success: isSuccess}, cancelable: true});
      if (offlineQueued) {
        evt.preventDefault();
      }
      document.dispatchEvent(evt);
      const isTutorForm = form.classList && (form.classList.contains('js-tutor-form') || form.id === 'tutor-form');
      if (!evt.defaultPrevented && !isTutorForm && !form.hasAttribute('data-sync')) {
        location.reload();
      }

      return { success: isSuccess, message: mainMessage, level: category, offlineQueued };
    };

    const errorMessage = 'Não foi possível enviar o formulário. Tente novamente.';
    try {
      if (feedback && typeof feedback.withSavingState === 'function' && submitButton) {
        await feedback.withSavingState(submitButton, performSync, { form, errorMessage });
      } else {
        setFeedbackLoading(submitButton, { form });
        const result = await performSync();
        if (result && result.offlineQueued) {
          setFeedbackSuccess(submitButton, { offlineQueued: true });
        } else if (result && result.success) {
          setFeedbackSuccess(submitButton);
        } else {
          setFeedbackIdle(submitButton);
        }
      }
    } catch (error) {
      console.error('Erro ao enviar formulário:', error);
      showToast(errorMessage, 'danger');
      setFeedbackIdle(submitButton);
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
        ? null
        : (data && data.message) || 'Tutor salvo com sucesso.';
      if (message) {
        showFormMessage(form, message, 'success');
      }

      function showTutorPanelMessage(text, category){
        const container = document.getElementById('tutores-adicionados');
        if(!container || !text) return;
        const alert = document.createElement('div');
        alert.className = `alert alert-${category || 'success'} alert-dismissible fade show mb-3`;
        alert.setAttribute('role', 'alert');
        alert.innerHTML = `
          <div class="d-flex align-items-center gap-2">
            <i class="fa-solid fa-circle-check text-success"></i>
            <span>${text}</span>
          </div>
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        container.prepend(alert);
      }

      async function refreshTutorPanel(){
        const panel = document.querySelector('[data-listing-panel="tutors"]');
        if(!panel) return false;

        const fetchUrl = panel.dataset.fetchUrl || window.location.pathname;
        const scopeParam = panel.dataset.scopeParam || 'scope';
        const searchParam = panel.dataset.searchParam || 'tutor_search';
        const sortParam = panel.dataset.sortParam || 'tutor_sort';
        const pageParam = panel.dataset.pageParam || 'page';
        const params = new URLSearchParams();

        const scope = panel.dataset.scope || 'all';
        if(scope) params.set(scopeParam, scope);

        const page = parseInt(panel.dataset.page || '1', 10);
        if(page && page > 1) params.set(pageParam, page);

        const filterInput = panel.querySelector('#tutor-filter');
        const searchValue = filterInput ? filterInput.value.trim() : '';
        if(searchValue) params.set(searchParam, searchValue);

        const sortSelect = panel.querySelector('#tutor-sort');
        const sortValue = sortSelect ? sortSelect.value : (panel.dataset.defaultSort || 'name_asc');
        if(sortValue) params.set(sortParam, sortValue);

        const requestUrl = new URL(fetchUrl, window.location.origin);
        params.forEach((value, key) => requestUrl.searchParams.set(key, value));

        try {
          const response = await fetch(requestUrl, {
            headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            credentials: 'same-origin',
          });
          if(!response.ok) return false;
          const payload = await response.json();
          if(payload && payload.html){
            const container = document.getElementById('tutores-adicionados');
            if(container){
              container.innerHTML = payload.html;
              if(window.PetorlandiaPanels && typeof window.PetorlandiaPanels.refreshListings === 'function'){
                window.PetorlandiaPanels.refreshListings();
              }
              return true;
            }
          }
        } catch (error) {
          console.error('Erro ao recarregar painel de tutores:', error);
        }
        return false;
      }

      function normalizeStatus(tutor){
        const statuses = ['internal'];
        if(tutor && typeof tutor.worker === 'string' && tutor.worker.toLowerCase() === 'veterinario'){
          statuses.push('professional');
        }
        return statuses.join(' ');
      }

      function createTutorCard(tutor){
        if(!tutor) return null;
        const col = document.createElement('div');
        const cardStatus = normalizeStatus(tutor);
        col.className = 'col-md-6 d-flex';
        col.dataset.name = (tutor.name || '').toLowerCase();
        col.dataset.date = tutor.created_at || '';
        col.dataset.cpf = tutor.cpf || '';
        col.dataset.phone = tutor.phone || '';
        if(tutor.date_of_birth) col.dataset.dob = tutor.date_of_birth;
        col.dataset.status = cardStatus;

        const detailUrl = tutor.detail_url || (tutor.id ? `/tutor/${tutor.id}` : '#');
        const createdAt = tutor.created_at ? new Date(tutor.created_at).toLocaleDateString('pt-BR') : '';
        const professionalBadge = cardStatus.includes('professional') ? '<span class="badge bg-success position-absolute top-0 end-0 m-2">Veterinário</span>' : '';
        const placeholderInitial = (tutor.name || '?').trim().charAt(0).toUpperCase();

        col.innerHTML = `
          <div class="card shadow-sm rounded-4 h-100 flex-fill position-relative overflow-hidden profile-card profile-card--internal">
            ${professionalBadge}
            <div class="profile-card-media profile-card-media--tutor" style="--offset-x: ${tutor.photo_offset_x || 0}px; --offset-y: ${tutor.photo_offset_y || 0}px; --rotation: ${tutor.photo_rotation || 0}deg; --zoom: ${tutor.photo_zoom || 1};">
              ${tutor.profile_photo ? `<img src="${tutor.profile_photo}" alt="Foto de ${tutor.name || ''}" class="profile-card-photo" loading="lazy">` : `
              <div class="profile-card-placeholder">
                <span>${placeholderInitial}</span>
              </div>`}
            </div>
            <div class="card-body d-flex flex-column gap-3">
              <div>
                <div class="d-flex justify-content-between align-items-start mb-2">
                  <h5 class="card-title mb-0">${tutor.name || `Tutor #${tutor.id}`}</h5>
                  ${createdAt ? `<span class="badge text-bg-light border text-muted">Desde ${createdAt}</span>` : ''}
                </div>
              </div>
              <div class="profile-card-contact-grid">
                ${(tutor.email || tutor.phone) ? `
                <div class="contact-item contact-item--actions-only u-pill u-pill--subtle u-hover-lift">
                  <div class="contact-actions contact-actions--standalone">
                    ${tutor.email ? `<a href="mailto:${tutor.email}" class="contact-action-btn contact-action-btn--email contact-action-btn--xl" title="Enviar e-mail"><i class="fa-solid fa-envelope"></i></a>` : ''}
                    ${tutor.phone ? `<a href="https://wa.me/${(tutor.phone || '').replace(/[^\d]/g, '')}" target="_blank" rel="noopener" class="contact-action-btn contact-action-btn--whatsapp contact-action-btn--xl" title="Conversar no WhatsApp"><i class="fa-brands fa-whatsapp"></i></a>` : ''}
                  </div>
                </div>` : ''}
                ${tutor.cpf ? `
                <div class="contact-item u-pill u-pill--subtle u-hover-lift">
                  <div class="contact-icon u-icon-circle">
                    <i class="fa-solid fa-id-card"></i>
                  </div>
                  <div class="contact-content u-stack-sm">
                    <span class="contact-label u-text-subtle">CPF</span>
                    <span class="contact-value u-text-strong" title="${tutor.cpf}">${tutor.cpf}</span>
                  </div>
                </div>` : ''}
              </div>
            </div>
            <div class="card-footer bg-white border-0 pt-0 pb-4 px-4 mt-auto">
              <div class="d-flex flex-wrap gap-2">
                <a href="${detailUrl}" class="btn btn-sm btn-outline-dark flex-fill">📋 Ver Ficha</a>
              </div>
            </div>
          </div>
        `;
        return col;
      }

      function tutorSortComparator(sortOption, a, b){
        const nameA = (a.dataset.name || '').toLowerCase();
        const nameB = (b.dataset.name || '').toLowerCase();
        const dateA = Date.parse(a.dataset.date || '') || 0;
        const dateB = Date.parse(b.dataset.date || '') || 0;
        const dobA = Date.parse(a.dataset.dob || '') || Infinity;
        const dobB = Date.parse(b.dataset.dob || '') || Infinity;

        switch(sortOption){
          case 'name_desc':
            return nameB.localeCompare(nameA);
          case 'date_desc':
            return dateB - dateA;
          case 'date_asc':
            return dateA - dateB;
          case 'age_desc':
            return dobA - dobB;
          case 'age_asc':
            return dobB - dobA;
          default:
            return nameA.localeCompare(nameB);
        }
      }

      function insertTutorCard(tutor){
        const cardsContainer = document.getElementById('tutor-cards');
        if(!cardsContainer) return false;
        const card = createTutorCard(tutor);
        if(!card) return false;
        cardsContainer.appendChild(card);
        const sortSelect = document.querySelector('#tutor-sort');
        const sortOption = sortSelect ? sortSelect.value : 'name_asc';
        const cards = Array.from(cardsContainer.children);
        cards.sort((a,b) => tutorSortComparator(sortOption, a, b));
        cards.forEach(c => cardsContainer.appendChild(c));
        if(window.PetorlandiaPanels && typeof window.PetorlandiaPanels.refreshListings === 'function'){
          const panel = document.querySelector('[data-listing-panel="tutors"]');
          if(panel){
            delete panel.dataset.listingInitialized;
          }
          window.PetorlandiaPanels.refreshListings();
        }
        return true;
      }

      (async () => {
        let updated = false;
        if(data.html){
          const cont=document.getElementById('tutores-adicionados');
          if(cont) {
            cont.innerHTML=data.html;
            if(window.PetorlandiaPanels && typeof window.PetorlandiaPanels.refreshListings === 'function'){
              window.PetorlandiaPanels.refreshListings();
            }
            updated = true;
          }
        }

        if(!updated){
          updated = await refreshTutorPanel();
        }

        if(!updated && data && data.tutor){
          updated = insertTutorCard(data.tutor);
        }

        showTutorPanelMessage(message, isQueued ? 'info' : 'success');
      })();

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
      setFeedbackIdle(btn);
    } else if(form.id === 'tutor-form'){
      const resp = detail.response;
      if(!(resp && resp.ok) || (data && data.success === false)){
        const message = (data && data.message) || 'Não foi possível salvar o tutor.';
        showFormMessage(form, message, 'danger');
        setFeedbackIdle(getSubmitButton(form));
        return;
      }
      ev.preventDefault();
      const successMessage = isQueued
        ? null
        : (data && data.message) || 'Tutor salvo com sucesso.';
      if (successMessage) {
        showFormMessage(form, successMessage, 'success');
      }
      setFeedbackSuccess(getSubmitButton(form), { offlineQueued: isQueued });
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
      setFeedbackIdle(form.querySelector('button[type="submit"]'));
    }
  });

  function resolveTargetElement(target) {
    if (!target) return null;
    const selector = target.trim();
    if (!selector) return null;

    try {
      const bySelector = document.querySelector(selector);
      if (bySelector) return bySelector;
    } catch (error) {
      // Ignore selector errors and fallback to ID lookup
    }

    const normalizedId = selector.startsWith('#') ? selector.slice(1) : selector;
    return document.getElementById(normalizedId);
  }

  function formatBrazilTimestampsSafe(root = document) {
    if (typeof window.formatBrazilTimestamps === 'function') {
      window.formatBrazilTimestamps(root);
      return;
    }

    const brazilDateFormatter = new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Sao_Paulo',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
    const brazilTimeFormatter = new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Sao_Paulo',
      hour: '2-digit',
      minute: '2-digit',
    });

    root.querySelectorAll('.js-br-time').forEach((el) => {
      const iso = el.dataset.timestamp;
      if (!iso) return;
      const dateObj = new Date(iso);
      if (Number.isNaN(dateObj.getTime())) return;

      const dateTarget = el.querySelector('.js-br-date');
      const timeTarget = el.querySelector('.js-br-time-only');
      if (dateTarget) dateTarget.textContent = brazilDateFormatter.format(dateObj);
      if (timeTarget) timeTarget.textContent = brazilTimeFormatter.format(dateObj);
    });
  }

  // Atualiza automaticamente contêineres retornados em respostas JSON (ex.: históricos via AJAX)
  document.addEventListener('form-sync-success', ev => {
    const detail = ev.detail || {};
    const form = detail.form;
    const data = detail.data;
    const target = form && form.dataset ? form.dataset.target : null;
    if (!form || !target || !(data && data.html)) return;

    const container = resolveTargetElement(target);
    if (!container) return;

    ev.preventDefault();
    container.innerHTML = data.html;

    if (typeof bindSyncForms === 'function') {
      bindSyncForms(container);
    }

    formatBrazilTimestampsSafe(container);
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
      setFeedbackIdle(getSubmitButton(form));
      return;
    }

    ev.preventDefault();

    if (!detail.offlineQueued) {
      const toastMessage = (data && data.message) || 'Animal removido.';
      showToast(toastMessage, 'success');
    }

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
