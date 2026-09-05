/* Camada de comportamento compartilhada por todas as páginas (app shell).
 *
 * Estes blocos viviam inline no fim do <body> de layout.html: 42 KB de
 * JavaScript idêntico reenviados a cada navegação, sem cache possível e
 * exigindo 'unsafe-inline' no CSP. Como arquivo versionado, o navegador baixa
 * uma vez e reusa.
 *
 * A ordem dos blocos é a ordem original e importa: o escopo global é o mesmo
 * de antes. Ao editar, mantenha os blocos na sequência.
 *
 * Carregado de forma síncrona no mesmo ponto do <body> em que os blocos
 * rodavam, para preservar a ordem em relação aos demais scripts da página.
 */

/* ---- bloco 1 (layout.html, linha 587 do original) ---- */
const normalizeFetchResult = (result) => ({
      response: result && result.response ? result.response : null,
      queued: Boolean(result && result.queued),
    });

    document.addEventListener('DOMContentLoaded', () => {

      const parseJsonSafe = async (response) => {
        if (!response) return null;
        const contentType = response.headers.get('Content-Type') || '';

        if (!contentType.includes('application/json')) return null;
        try {
          const clone = response.clone();
          const parsed = await clone.json();
          return parsed;
        } catch (err) {
          return null;
        }
      };

      const isLikelySuccess = (response) => {
        if (!response) return false;
        if (response.ok) return true;
        if (response.type === 'opaqueredirect') return true;
        const status = Number(response.status) || 0;
        return status >= 200 && status < 400;
      };

      const applyDeliveryCounts = (counts) => {
        if (!counts) return;
        const mapping = {
          'available-count': counts.available_total,
          'doing-count': counts.doing,
          'done-count': counts.done,
          'canceled-count': counts.canceled,
        };
        Object.entries(mapping).forEach(([id, value]) => {
          const el = document.getElementById(id);
          if (el) {
            el.textContent = value;
          }
        });
      };

      const getCsrfToken = (form) => {
        const formInput = form?.querySelector('input[name="csrf_token"]');
        if (formInput?.value) return formInput.value;
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta?.content) return meta.content;
        return '';
      };

      // attachDeliveryFormListeners será definido mais adiante,
      // então usamos uma referência que será populada posteriormente
      let attachDeliveryFormListenersRef = () => { };

      const applyDeliveryPayload = (data) => {
        const container = document.getElementById('delivery-sections');
        if (data?.html && container) {
          container.innerHTML = data.html;
        }
        if (data?.counts) {
          applyDeliveryCounts(data.counts);
        }
        if (data?.html) {
          attachDeliveryFormListenersRef();
        }
      };

      const refreshDeliverySections = async () => {
        const container = document.getElementById('delivery-sections');
        if (!container) return;
        try {
          // Add cache-busting parameter to ensure fresh data
          const resp = await fetch('/delivery_requests?_=' + Date.now(), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            cache: 'no-cache'
          });
          if (!resp.ok) return;

          let data = await parseJsonSafe(resp);
          if (!data) {
            const html = await resp.clone().text();
            data = html ? { html } : null;
          }

          applyDeliveryPayload(data);
        } catch (err) {
          console.error('Erro ao atualizar entregas', err);
        }
      };

      // Torna o atualizador acessível para outros scripts (ex: ações do admin)
      window.refreshDeliverySections = refreshDeliverySections;

      const ensureMessageCategory = (payload, fallbackMessage, fallbackCategory) => ({
        ...(payload || {}),
        message: formatUserMessage(payload, fallbackMessage),
        category: (payload && payload.category) || fallbackCategory,
      });

      const emitSyncEvent = (detail) => {
        const event = new CustomEvent('form-sync-success', { detail, cancelable: true });
        document.dispatchEvent(event);
        return event;
      };

      const parseErrorMessage = async (response, fallback = 'Erro ao processar ação') => {
        if (!response) return fallback;
        const data = await parseJsonSafe(response);
        if (data?.message || data?.error || data?.detail || data?.errors) {
          return formatUserMessage(data, fallback);
        }
        try {
          const text = await response.clone().text();
          const cleaned = text.trim();
          if (cleaned) {
            return cleaned.length > 180 ? `${cleaned.slice(0, 180)}…` : cleaned;
          }
        } catch (err) { /* ignore */ }
        return fallback;
      };

      const showToast = (message, category = 'info') => {
        const toastEl = document.getElementById('actionToast');
        if (!toastEl) return;
        toastEl.querySelector('.toast-body').textContent = formatUserMessage(message, category === 'danger' ? 'Não foi possível concluir a ação.' : 'Ação concluída.');
        applyToastTone(toastEl, category);
        bootstrap.Toast.getOrCreateInstance(toastEl).show();
      };

      const attachDeliveryFormListeners = () => {
        document.querySelectorAll('.js-delivery-form').forEach(form => {
          if (form.dataset.deliveryListenerAttached === 'true') return;
          form.dataset.deliveryListenerAttached = 'true';
          form.addEventListener('submit', async ev => {
            const canHandle = typeof fetchOrQueue === 'function';
            if (!canHandle) return;

            ev.preventDefault();
            
            // Prevent double submission
            if (form.dataset.submitting === 'true') {
              return;
            }
            form.dataset.submitting = 'true';
            
            const url = form.action;
            const handle = async () => {
              try {
                const formData = new FormData(form);
                const headers = {
                  'Accept': 'application/json',
                  'X-Requested-With': 'XMLHttpRequest',
                };
                // Get CSRF token from form, but don't add to FormData if already in header
                // Flask-WTF can read from either form data or header, but sending both can cause issues
                const csrfToken = getCsrfToken(form);
                if (csrfToken) {
                  headers['X-CSRFToken'] = csrfToken;
                  // Remove csrf_token from FormData if it exists, since we're sending it in header
                  formData.delete('csrf_token');
                }

                const { response, queued } = normalizeFetchResult(await fetchOrQueue(url, {
                  method: 'POST',
                  body: formData,
                  headers,
                  credentials: 'same-origin',
                }));


                if (queued) {
                  const queuedDetail = { form, data: { message: 'Aguardando conexão para concluir o envio.', category: 'info' }, response: null, offlineQueued: true, success: true };
                  emitSyncEvent(queuedDetail);
                  showToast('Ação salva para sincronização quando estiver online.', 'info');
                  return { success: true, message: formatUserMessage(queuedDetail.data, 'Aguardando conexão para concluir o envio.'), level: queuedDetail.data.category, successText: 'Sincronizando…', resetDelay: 2500, offlineQueued: true };
                }

                const data = await parseJsonSafe(response);
                const contentType = response?.headers?.get('Content-Type') || '';

                const hasDeliverySections = Boolean(document.getElementById('delivery-sections'));
                // Check if response has valid delivery data even if status is not 200
                // This handles cases where backend returns 400 with valid JSON payload (e.g., CSRF errors that still include html/counts)
                const hasValidDeliveryData = data && (data.html || data.counts);
                const successLike = isLikelySuccess(response) || (hasValidDeliveryData && data.category !== 'danger');

                if (successLike) {

                  const successData = ensureMessageCategory(
                    data,
                    (data && (data.message || data.error)) || 'Sucesso',
                    (data && data.category) || 'success',
                  );

                  if (hasDeliverySections && data) {
                    applyDeliveryPayload(data);
                  }

                  if (data?.redirect) {
                    
                    // If we have delivery sections, ALWAYS update UI instead of redirecting
                    // User can navigate manually if needed
                    if (hasDeliverySections) {
                      
                      if (data?.html) {
                        applyDeliveryPayload(data);
                      } else {
                        await refreshDeliverySections();
                      }
                      const eventDetail = {
                        form,
                        data: successData,
                        response,
                        responseOk: successLike,
                        offlineQueued: false,
                        success: true,
                      };
                      emitSyncEvent(eventDetail);
                      showToast(successData.message, successData.category);
                      // Don't redirect - just update UI. User can navigate manually if needed.
                      return { success: true, message: successData.message, level: successData.category };
                    }
                    // Only redirect if we don't have delivery sections
                    if (!form.dataset.forceRedirect) {
                      window.location.href = data.redirect;
                      return { success: true, keepButton: true };
                    }
                  }

                  if (response?.redirected && response.url) {
                    // If we have delivery sections, refresh them instead of redirecting
                    if (hasDeliverySections) {
                      await refreshDeliverySections();
                      emitSyncEvent({
                        form,
                        data: successData,
                        response,
                        responseOk: successLike,
                        offlineQueued: false,
                        success: true,
                      });
                      showToast(successData.message, successData.category);
                      return { success: true, message: successData.message, level: successData.category };
                    }
                    window.location.href = response.url;
                    return { success: true, keepButton: true };
                  }

                  showToast(successData.message, successData.category);
                  await refreshDeliverySections();
                  emitSyncEvent({
                    form,
                    data: successData,
                    response,
                    responseOk: successLike,
                    offlineQueued: false,
                    success: true,
                  });
                  return { success: true, message: successData.message, level: successData.category };
                }


                // Even if response status indicates error, if we have valid delivery data (html/counts),
                // treat it as a success case and update the UI. This handles cases where backend
                // returns error status but still includes updated data (e.g., CSRF errors that include html/counts)
                const shouldTreatAsSuccess = hasValidDeliveryData && data.category !== 'danger';
                
                if (shouldTreatAsSuccess) {
                  
                  // When we have valid delivery data, use a success message instead of the warning/error message
                  const successData = ensureMessageCategory(
                    data,
                    'Ação concluída com sucesso.',
                    'success',
                  );
                  
                  if (hasDeliverySections && data) {
                    applyDeliveryPayload(data);
                  }
                  
                  emitSyncEvent({
                    form,
                    data: successData,
                    response,
                    responseOk: true,
                    offlineQueued: false,
                    success: true,
                  });
                  showToast(successData.message, successData.category);
                  return { success: true, message: successData.message, level: successData.category };
                }

                const errorMessage = formatUserMessage(data, '') || await parseErrorMessage(response);
                const errorCategory = (data && data.category) || 'danger';
                const errorData = ensureMessageCategory(data, errorMessage, errorCategory);

                if (hasDeliverySections) {
                  if (data?.html) {
                    applyDeliveryPayload(data);
                  } else {
                    await refreshDeliverySections();
                  }
                }
                emitSyncEvent({
                  form,
                  data: errorData,
                  response,
                  responseOk: false,
                  offlineQueued: false,
                  success: false,
                });
                showToast(errorData.message, errorData.category);
                if (window.FormFeedback?.showStatus) {
                  window.FormFeedback.showStatus(form, errorData.message, errorData.category);
                }
                if (window.FormFeedback?.setMessage) {
                  const btn = window.FormFeedback.getButton?.(form);
                  if (btn) window.FormFeedback.setMessage(btn, errorData.message, errorData.category);
                }
                return { success: false, message: errorData.message, level: errorData.category };
              } catch (error) {

                console.error('Erro ao enviar formulário de entrega', error);
                emitSyncEvent({
                  form,
                  data: { message: error.message, category: 'danger' },
                  response: null,
                  responseOk: false,
                  offlineQueued: false,
                  success: false,
                });
                const fallback = error?.name === 'FetchTimeoutError'
                  ? 'Tempo limite ao enviar a requisição. Tente novamente.'
                  : 'Erro ao processar ação';
                showToast(fallback, 'danger');
                const restoreButton = () => {
                  const button = window.FormFeedback?.getButton?.(form)
                    || form.querySelector('button[type="submit"], button:not([type])');
                  if (!button) return;
                  if (window.FormFeedback?.setIdle) {
                    window.FormFeedback.setIdle(button);
                  } else {
                    button.disabled = false;
                  }
                };
                restoreButton();
                try {
                  form.submit();
                } catch (submitError) {
                  console.error('Fallback submit falhou', submitError);
                }
                return { success: false, message: fallback, level: 'danger', keepButton: true };
              }
            };

            try {
              if (window.FormFeedback && typeof window.FormFeedback.withSavingState === 'function') {
                await window.FormFeedback.withSavingState(form, handle, { loadingText: form.dataset.loadingText || 'Processando...' });
              } else {
                await handle();
              }
            } catch (error) {
              console.error('Error in delivery form handler:', error);
            } finally {
              // Reset submitting flag after a delay to allow UI updates
              setTimeout(() => {
                form.dataset.submitting = 'false';
              }, 1000);
            }
          });
        });
      };

      // Atribuir a função real à referência usada em applyDeliveryPayload
      attachDeliveryFormListenersRef = attachDeliveryFormListeners;

      attachDeliveryFormListeners();

      document.querySelectorAll('.js-cart-form').forEach(form => {
        if (form.dataset.skipGlobalHandler === 'true') return;
        form.addEventListener('submit', async ev => {
          ev.preventDefault();
          const handle = async () => {
            const { response, queued } = normalizeFetchResult(await fetchOrQueue(form.action, {
              method: form.method,
              body: new FormData(form),
              headers: { 'Accept': 'application/json' }
            }));
            if (queued) {
              const toastEl = document.getElementById('actionToast');
              toastEl.querySelector('.toast-body').textContent = 'Ação salva para sincronização quando estiver online.';
              applyToastTone(toastEl, 'info');
              new bootstrap.Toast(toastEl).show();
              return { success: true, message: 'Aguardando conexão para concluir o envio.', level: 'info', successText: 'Sincronizando…', resetDelay: 2500, offlineQueued: true };
            }
            if (response && response.ok) {
              let data;
              try {
                data = await response.json();
              } catch (err) {
                window.location.reload();
                return { success: false, message: 'Erro ao processar resposta', level: 'danger', keepButton: true };
              }
              if (data.redirect) {
                window.location.href = data.redirect;
                return { success: true, keepButton: true };
              }
              const span = form.parentElement.querySelector('span');
              if (span && data.item_quantity !== undefined) {
                span.textContent = data.item_quantity;
              }
              if (data.item_quantity === 0) {
                const li = form.closest('li');
                li?.remove();
              }
              if (data.order_quantity !== undefined) {
                document.querySelectorAll('[data-cart-count]').forEach(el => {
                  el.textContent = data.order_quantity;
                });
              }
              const totalEl = document.getElementById('cartTotal');
              if (totalEl && data.order_total_formatted) {
                totalEl.textContent = 'Total:\u00A0' + data.order_total_formatted;
              }
              const toastEl = document.getElementById('actionToast');
              toastEl.querySelector('.toast-body').textContent = formatUserMessage(data, 'Sucesso');
              applyToastTone(toastEl, data.category || 'success');
              new bootstrap.Toast(toastEl).show();

              if (typeof window.refreshDeliverySections === 'function') {
                await window.refreshDeliverySections();
              }

              return { success: true, message: formatUserMessage(data, 'Sucesso'), level: data.category };
            }
            const toastEl = document.getElementById('actionToast');
            toastEl.querySelector('.toast-body').textContent = 'Erro ao processar ação';
            applyToastTone(toastEl, 'danger');
            new bootstrap.Toast(toastEl).show();
            return { success: false, message: 'Erro ao processar ação', level: 'danger' };
          };

          if (window.FormFeedback && typeof window.FormFeedback.withSavingState === 'function') {
            await window.FormFeedback.withSavingState(form, handle, { loadingText: form.dataset.loadingText || 'Processando...' });
          } else {
            await handle();
          }
        });
      });
    });

/* ---- bloco 2 (layout.html, linha 1042 do original) ---- */
document.addEventListener('DOMContentLoaded', () => {
      const getCsrfToken = (form) => {
        const formInput = form?.querySelector('input[name="csrf_token"]');
        if (formInput?.value) return formInput.value;
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta?.content) return meta.content;
        return '';
      };

      const statusConfig = {
        pendente: { badgeClass: 'bg-warning text-dark', label: 'Pendente' },
        em_andamento: { badgeClass: 'bg-info text-dark', label: 'Em andamento' },
        concluida: { badgeClass: 'bg-success', label: 'Concluída' },
        cancelada: { badgeClass: 'bg-danger', label: 'Cancelada' },
      };

      const ensurePlaceholderState = (listEl) => {
        if (!listEl) return;
        const hasItems = listEl.querySelectorAll('li.list-group-item:not(.js-empty-placeholder)').length > 0;
        const placeholder = listEl.querySelector('.js-empty-placeholder');
        if (hasItems) {
          placeholder?.remove();
        } else if (!placeholder) {
          const li = document.createElement('li');
          li.className = 'list-group-item text-muted js-empty-placeholder';
          li.textContent = 'Não há registros.';
          listEl.appendChild(li);
        }
      };

      const moveDeliveryCard = (li, status) => {
        if (!li || !statusConfig[status]) return;
        const originList = li.closest('ul');
        const targetList = document.querySelector(`ul[data-delivery-list="${status}"]`);
        if (!targetList) return;

        const badge = li.querySelector('.badge');
        if (badge) {
          badge.className = `badge ${statusConfig[status].badgeClass} ms-2`;
          badge.textContent = statusConfig[status].label;
        }

        li.dataset.deliveryStatus = status;
        targetList.prepend(li);

        ensurePlaceholderState(originList);
        ensurePlaceholderState(targetList);
      };

      document.querySelectorAll('.js-admin-delivery-form').forEach(form => {
        form.addEventListener('submit', async ev => {
          ev.preventDefault();
          const li = form.closest('li');
          const handle = async () => {
            const headers = { 'Accept': 'application/json' };
            const csrfToken = getCsrfToken(form);
            if (csrfToken) headers['X-CSRFToken'] = csrfToken;

            const response = await fetch(form.action, {
              method: 'POST',
              headers,
              body: new FormData(form),
              credentials: 'same-origin',
            });

            if (response && response.ok) {
              let data = {};
              try {
                data = await response.json();
              } catch (err) {
                console.warn('Não foi possível interpretar a resposta como JSON.', err);
              }

              if (data.deleted || data.archived) {
                if (li) {
                  const originList = li.closest('ul');
                  li.remove();
                  ensurePlaceholderState(originList);
                }
              } else if (data.status && li) {
                moveDeliveryCard(li, data.status);
              }

              const toastEl = document.getElementById('actionToast');
              toastEl.querySelector('.toast-body').textContent = formatUserMessage(data, 'Sucesso');
              applyToastTone(toastEl, data.category || 'success');
              new bootstrap.Toast(toastEl).show();

              if (typeof window.refreshDeliverySections === 'function') {
                await window.refreshDeliverySections();
              }

              return { success: true, message: formatUserMessage(data, 'Sucesso'), level: data.category };
            }

            let data = {};
            try { data = response ? await response.json() : {}; } catch (err) { }
            const toastEl = document.getElementById('actionToast');
            toastEl.querySelector('.toast-body').textContent = formatUserMessage(data, 'Erro ao processar ação');
            applyToastTone(toastEl, 'danger');
            new bootstrap.Toast(toastEl).show();
            return { success: false, message: formatUserMessage(data, 'Erro ao processar ação'), level: 'danger' };
          };

          if (window.FormFeedback && typeof window.FormFeedback.withSavingState === 'function') {
            await window.FormFeedback.withSavingState(form, handle, { loadingText: form.dataset.loadingText || 'Processando...' });
          } else {
            await handle();
          }
        });
      });
    });

/* ---- bloco 3 (layout.html, linha 1156 do original) ---- */
document.addEventListener('DOMContentLoaded', () => {
      document.querySelectorAll('.js-animal-status').forEach(form => {
        form.addEventListener('submit', async ev => {
          ev.preventDefault();
          const handle = async () => {
            const response = await fetch(form.action, {
              method: 'POST',
              headers: { 'Accept': 'application/json' },
              body: new FormData(form),
              credentials: 'same-origin',
            });

            if (response && response.ok) {
              const data = await response.json();
              if (data.redirect) {
                window.location.href = data.redirect;
                return { success: true, keepButton: true };
              }
              const toastEl = document.getElementById('actionToast');
              toastEl.querySelector('.toast-body').textContent = formatUserMessage(data, 'Sucesso');
              applyToastTone(toastEl, data.category || 'success');
              new bootstrap.Toast(toastEl).show();
              return { success: true, message: formatUserMessage(data, 'Sucesso'), level: data.category };
            }
            let data = {};
            try { data = response ? await response.json() : {}; } catch (err) { }
            const toastEl = document.getElementById('actionToast');
            toastEl.querySelector('.toast-body').textContent = formatUserMessage(data, 'Erro ao processar ação');
            applyToastTone(toastEl, 'danger');
            new bootstrap.Toast(toastEl).show();
            return { success: false, message: formatUserMessage(data, 'Erro ao processar ação'), level: 'danger' };
          };

          if (window.FormFeedback && typeof window.FormFeedback.withSavingState === 'function') {
            await window.FormFeedback.withSavingState(form, handle, { loadingText: form.dataset.loadingText || 'Processando...' });
          } else {
            await handle();
          }
        });
      });
    });

/* ---- bloco 4 (layout.html, linha 1199 do original) ---- */
document.addEventListener('DOMContentLoaded', () => {
      document.querySelectorAll('.js-auth-form').forEach(form => {
        const ensureGlobalError = () => {
          let alert = form.querySelector('.js-auth-global-error');
          if (!alert) {
            alert = document.createElement('div');
            alert.className = 'alert alert-danger d-none js-auth-global-error';
            alert.setAttribute('role', 'alert');
            form.prepend(alert);
          }
          return alert;
        };

        form.addEventListener('submit', async ev => {
          // Outra validação (ex.: campos obrigatórios do endereço) já bloqueou o envio
          if (ev.defaultPrevented) return;
          ev.preventDefault();
          const handle = async () => {
            form.querySelectorAll('.js-field-error').forEach(el => el.remove());
            form.querySelectorAll('[data-js-auth-invalid]').forEach(el => {
              el.classList.remove('is-invalid');
              el.removeAttribute('aria-invalid');
              el.removeAttribute('data-js-auth-invalid');
            });
            const statusEl = form.querySelector('.form-status-message');
            const globalError = statusEl ? null : ensureGlobalError();
            if (globalError) {
              globalError.textContent = '';
              globalError.classList.add('d-none');
            }
            try {
              // Requisições de autenticação usam fetch direto (não offline queue)
              // pois dependem de CSRF tokens que expiram
              const response = await fetch(form.action, {
                method: form.method || 'POST',
                body: new FormData(form),
                headers: { 'Accept': 'application/json' }
              });

              if (response && response.ok) {
                const data = await response.json().catch(() => null);
                if (data && data.redirect) {
                  // Redireciona para a página indicada após login/registro bem-sucedido
                  window.location.href = data.redirect;
                  return { success: true, keepButton: true };
                }
                // Se não houver redirecionamento explícito, recarrega a página
                window.location.reload();
                return { success: true, keepButton: true };
              }

              // Tenta parsear JSON de erro
              let errorData = null;
              if (response) {
                try {
                  errorData = await response.json();
                } catch (jsonError) {
                  console.error('Erro ao parsear JSON:', jsonError);
                }
              }

              const globalMessages = [];
              let firstInvalid = null;

              if (errorData && errorData.errors) {
                for (const [field, messages] of Object.entries(errorData.errors)) {
                  const input = form.querySelector(`[name="${field}"]`);
                  const text = Array.isArray(messages) ? messages.join(' ') : messages;
                  const shouldRenderGlobal = !input || input.type === 'hidden' || ['csrf_token', 'form', 'endereco'].includes(field);

                  if (!shouldRenderGlobal) {
                    input.classList.add('is-invalid');
                    input.setAttribute('aria-invalid', 'true');
                    input.setAttribute('data-js-auth-invalid', 'true');
                    const div = document.createElement('div');
                    div.className = 'invalid-feedback d-block js-field-error';
                    div.textContent = text;
                    // Campos dentro de input-group (senha com botão de olho) recebem
                    // a mensagem depois do grupo para não quebrar o layout
                    const anchor = input.closest('.input-group') || input;
                    anchor.insertAdjacentElement('afterend', div);
                    if (!firstInvalid) firstInvalid = input;
                  } else if (text) {
                    globalMessages.push(text);
                  }
                }

                if (globalError && globalMessages.length) {
                  globalError.textContent = globalMessages.join(' ');
                  globalError.classList.remove('d-none');
                }
              }

              const fallback = (errorData && (errorData.message || errorData.error)) || 'Não foi possível concluir. Confira os campos e tente novamente.';
              const message = globalMessages.length ? globalMessages.join(' ') : fallback;

              // Leva o usuário até o problema: primeiro campo inválido ou a mensagem geral
              if (firstInvalid) {
                firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
                try { firstInvalid.focus({ preventScroll: true }); } catch (focusError) { }
              } else if (statusEl) {
                const submitBtn = form.querySelector('button[type="submit"], [type="submit"]');
                (submitBtn || statusEl).scrollIntoView({ behavior: 'smooth', block: 'center' });
              } else if (globalError && !globalError.classList.contains('d-none')) {
                globalError.scrollIntoView({ behavior: 'smooth', block: 'center' });
              }

              return { success: false, message, level: 'danger' };
            } catch (error) {
              console.error('Form submission error:', error);
              return { success: false, message: 'Erro de conexão. Verifique sua internet e tente novamente.', level: 'danger' };
            }
          };

          if (window.FormFeedback && typeof window.FormFeedback.withSavingState === 'function') {
            await window.FormFeedback.withSavingState(form, handle, { loadingText: form.dataset.loadingText || 'Enviando...', errorMessage: 'Não foi possível concluir o acesso.' });
          } else {
            await handle();
          }
        });
      });
    });

/* ---- bloco 5 (layout.html, linha 1323 do original) ---- */
const escapeHtml = (str) => {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    };

    document.addEventListener('DOMContentLoaded', () => {
      const getMsgCsrfToken = (form) => {
        const formInput = form?.querySelector('input[name="csrf_token"]');
        if (formInput?.value) return formInput.value;
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta?.content) return meta.content;
        return '';
      };

      document.querySelectorAll('.js-msg-form').forEach(form => {
        form.addEventListener('submit', async ev => {
          ev.preventDefault();
          const textarea = form.querySelector('textarea');
          const rawContent = textarea ? textarea.value : '';
          const content = rawContent.trim();
          if (!content) {
            return;
          }

          const api = form.dataset.api || form.action;
          const formData = new FormData(form);
          if (textarea && textarea.name) {
            formData.set(textarea.name, content);
          }

          let placeholder = null;
          const container = document.getElementById('mensagens-container');
          if (container) {
            placeholder = document.createElement('div');
            placeholder.className = 'mb-2 text-end js-msg-placeholder';
            placeholder.innerHTML = `
              <div class="p-2 rounded bg-info-subtle position-relative">
                <small>Você:</small><br>
                ${escapeHtml(content).replace(/\n/g, '<br>')}
                <div class="text-muted small js-status">Enviando...</div>
              </div>`;
            container.insertAdjacentElement('beforeend', placeholder);
            container.scrollTop = container.scrollHeight;
          }

          if (textarea) {
            textarea.value = '';
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
            textarea.focus();
          }

          const handle = async () => {
            let response;
            let queued = false;
            const timeoutAttr = form.dataset.requestTimeout || form.dataset.fetchTimeout || form.dataset.syncTimeout;
            const timeout = Number.isFinite(Number(timeoutAttr)) ? Number(timeoutAttr) : undefined;

            const fetchHeaders = { 'Accept': 'text/html' };
            const csrfToken = getMsgCsrfToken(form);
            if (csrfToken) fetchHeaders['X-CSRFToken'] = csrfToken;

            try {
              const result = await fetchOrQueue(api, {
                method: 'POST',
                body: formData,
                headers: fetchHeaders,
                timeout
              });
              response = result && result.response ? result.response : null;
              queued = Boolean(result && result.queued);
            } catch (err) {
              console.error('Erro ao enviar mensagem:', err);
              const errText = (err && err.message) || 'Erro de rede. Verifique sua conexão.';
              if (placeholder) {
                const status = placeholder.querySelector('.js-status');
                if (status) {
                  status.textContent = errText;
                }
                placeholder.dataset.status = 'error';
              }
              return { success: false, message: errText, level: 'danger' };
            }

            const isSuccessful = response && (response.ok || (response.status >= 300 && response.status < 400));

            if (isSuccessful) {
              try {
                const html = await response.text();
                if (placeholder) {
                  placeholder.insertAdjacentHTML('afterend', html);
                  placeholder.remove();
                } else if (container) {
                  container.insertAdjacentHTML('beforeend', html);
                  container.scrollTop = container.scrollHeight;
                }
                return { success: true, message: 'Mensagem enviada com sucesso.', level: 'success', successText: 'Enviado!', resetDelay: 1800 };
              } catch (parseErr) {
                console.error('Erro ao processar resposta HTML:', parseErr);
                return { success: false, message: 'Erro ao processar resposta do servidor.', level: 'danger' };
              }
            }

            if (queued) {
              if (placeholder) {
                const status = placeholder.querySelector('.js-status');
                if (status) {
                  status.textContent = 'Mensagem aguardando conexão...';
                }
                placeholder.dataset.status = 'queued';
              }
              return {
                success: true,
                message: 'Mensagem será enviada assim que a conexão voltar.',
                level: 'info',
                successText: 'Sincronizando…',
                resetDelay: 2500,
                offlineQueued: true,
              };
            }

            let errorMessage = 'Falha ao enviar. Tente novamente.';
            try {
              const ct = response && response.headers.get('Content-Type') || '';
              if (ct.includes('application/json')) {
                const errData = await response.json();
                if (errData && (errData.error || errData.message || errData.errors)) {
                  errorMessage = formatUserMessage(errData, errorMessage);
                }
              }
            } catch (_) {}
            if (placeholder) {
              const status = placeholder.querySelector('.js-status');
              if (status) {
                status.textContent = errorMessage;
              }
              placeholder.dataset.status = 'error';
            }
            return { success: false, message: errorMessage, level: 'danger' };
          };

          if (window.FormFeedback && typeof window.FormFeedback.withSavingState === 'function') {
            await window.FormFeedback.withSavingState(form, handle, { loadingText: form.dataset.loadingText || 'Enviando...' });
          } else {
            await handle();
          }
        });
      });
    });

/* ---- bloco 6 (layout.html, linha 1474 do original) ---- */
document.addEventListener('DOMContentLoaded', () => {
      document.querySelectorAll('.js-staff-form').forEach(form => {
        form.addEventListener('submit', async ev => {
          ev.preventDefault();
          const handle = async () => {
            const { response, queued } = normalizeFetchResult(await fetchOrQueue(form.action, {
              method: 'POST',
              headers: { 'Accept': 'application/json' },
              body: new FormData(form)
            }));

            if (queued) {
              if (window.FormFeedback?.setQueued) {
                const btn = window.FormFeedback.getButton?.(form);
                if (btn) {
                  window.FormFeedback.setQueued(btn);
                }
              }
              return { success: true, keepButton: true, offlineQueued: true };
            }

            if (response && response.ok) {
              const data = await response.json();
              if (data.redirect) {
                window.location.href = data.redirect;
                return { success: true, keepButton: true, offlineQueued: queued };
              }
              if (data.html) {
                const target = form.dataset.target;
                if (target) {
                  const el = document.querySelector(target);
                  if (el) {
                    el.innerHTML = data.html;
                  }
                }
              }
              const responseMessage = formatUserMessage(data, '');
              if (responseMessage) {
                const toastEl = document.getElementById('actionToast');
                toastEl.querySelector('.toast-body').textContent = responseMessage;
                applyToastTone(toastEl, data.category || 'success');
                new bootstrap.Toast(toastEl).show();
              }
              return { success: true, message: responseMessage, level: data.category };
            }

            let data = {};
            try { data = response ? await response.json() : {}; } catch (e) { }
            const toastEl = document.getElementById('actionToast');
            toastEl.querySelector('.toast-body').textContent = formatUserMessage(data, 'Erro ao processar ação');
            applyToastTone(toastEl, 'danger');
            new bootstrap.Toast(toastEl).show();
            return { success: false, message: formatUserMessage(data, 'Erro ao processar ação'), level: 'danger' };
          };

          if (window.FormFeedback && typeof window.FormFeedback.withSavingState === 'function') {
            await window.FormFeedback.withSavingState(form, handle, { loadingText: form.dataset.loadingText || 'Processando...' });
          } else {
            await handle();
          }
        });
      });
    });

/* ---- bloco 7 (layout.html, linha 1539 do original) ---- */
(() => {
      const originalAlert = window.alert?.bind(window);
      const suppressedPatterns = [
        /ação\s+salva\s+offline/i,
        /salva\s+offline.*sincronizada/i,
        /sincronizada\s+quando\s+possível/i,
      ];

      window.alert = message => {
        const text = formatUserMessage(message, 'Não foi possível concluir a ação.');
        const shouldSuppress = suppressedPatterns.some(pattern => pattern.test(text));

        if (shouldSuppress) {
          const toastEl = document.getElementById('actionToast');
          if (toastEl) {
            toastEl.querySelector('.toast-body').textContent = formatUserMessage(text, 'Ação salva para sincronização quando estiver online.');
            applyToastTone(toastEl, 'info');
            bootstrap.Toast.getOrCreateInstance(toastEl).show();
          } else {
            console.info('Alerta suprimido:', text);
          }
          return;
        }

        if (originalAlert) {
          return originalAlert(text);
        }
      };
    })();

/* ---- bloco 8 (layout.html, linha 1584 do original) ---- */
(function(){
    var token = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    if (!token) return;
    var mgr = window.HistorySyncManager;
    if (!mgr || !mgr._performSave) return;
    mgr._performSave = async function(endpoint, data, timeoutMs) {
      var controller = new AbortController();
      var tid = setTimeout(function(){ controller.abort(); }, timeoutMs);
      try {
        return await fetch(endpoint, {
          method: 'POST',
          headers: {'Content-Type':'application/json','Accept':'application/json','X-CSRFToken': token},
          body: JSON.stringify(data),
          signal: controller.signal
        });
      } finally { clearTimeout(tid); }
    };
  })();
