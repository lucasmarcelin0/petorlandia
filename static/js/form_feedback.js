(function() {
  const DEFAULT_LOADING_TEXT = 'Salvando...';
  const DEFAULT_SUCCESS_TEXT = 'Salvo!';
  const DEFAULT_ERROR_TEXT = 'Não foi possível salvar as alterações.';
  const DEFAULT_SUCCESS_DELAY = 2000;
  const DEFAULT_LOADING_TIMEOUT = 5000;
  const DEFAULT_TIMEOUT_MESSAGE = 'Tempo excedido, tente novamente.';
  const STATUS_VARIANTS = ['success', 'danger', 'warning', 'info'];

  function getButton(target) {
    if (!target) return null;
    if (target instanceof HTMLButtonElement) return target;
    if (target instanceof HTMLFormElement) {
      return target.querySelector('button[type="submit"], button:not([type])');
    }
    if (target.closest) {
      const formAncestor = target.closest('form');
      if (formAncestor) {
        return getButton(formAncestor);
      }
    }
    return null;
  }

  function ensureOriginal(button) {
    if (!button) return;
    if (!button.dataset.originalHtml) {
      button.dataset.originalHtml = button.innerHTML;
    }
  }

  function clearResetTimer(button) {
    if (!button || !button.dataset.resetTimeout) return;
    clearTimeout(Number(button.dataset.resetTimeout));
    delete button.dataset.resetTimeout;
  }

  function clearLoadingTimer(button) {
    if (!button || !button.dataset.loadingTimeoutId) return;
    clearTimeout(Number(button.dataset.loadingTimeoutId));
    delete button.dataset.loadingTimeoutId;
  }

  function parseTimeout(value) {
    if (value == null) return undefined;
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (trimmed === '') return undefined;
      const lowered = trimmed.toLowerCase();
      if (['false', 'off', 'no', 'none', 'disabled', 'disable', '0'].includes(lowered)) {
        return 0;
      }
    }
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : undefined;
  }

  function resolveLoadingTimeout(button, options = {}) {
    const fromOptions = parseTimeout(options.loadingTimeout);
    if (typeof fromOptions !== 'undefined') {
      return fromOptions;
    }
    if (button && typeof button.dataset !== 'undefined') {
      const fromButton = parseTimeout(button.dataset.loadingTimeout);
      if (typeof fromButton !== 'undefined') {
        return fromButton;
      }
    }
    const form = options.form || (button && button.form instanceof HTMLFormElement ? button.form : null);
    if (form && form.dataset) {
      const fromForm = parseTimeout(form.dataset.loadingTimeout);
      if (typeof fromForm !== 'undefined') {
        return fromForm;
      }
    }
    return DEFAULT_LOADING_TIMEOUT;
  }

  function resolveTimeoutMessage(button, form, options = {}) {
    if (Object.prototype.hasOwnProperty.call(options, 'timeoutMessage')) {
      return options.timeoutMessage;
    }
    if (button && typeof button.hasAttribute === 'function' && button.hasAttribute('data-timeout-message')) {
      return button.dataset.timeoutMessage || '';
    }
    if (form && typeof form.hasAttribute === 'function' && form.hasAttribute('data-timeout-message')) {
      return form.dataset.timeoutMessage || '';
    }
    return DEFAULT_TIMEOUT_MESSAGE;
  }

  function setLoading(button, loadingTextOrOptions, maybeOptions) {
    if (!button) return;
    let options = maybeOptions || {};
    let loadingText = loadingTextOrOptions;

    if (loadingTextOrOptions && typeof loadingTextOrOptions === 'object' && !Array.isArray(loadingTextOrOptions)) {
      options = loadingTextOrOptions;
      loadingText = options.loadingText;
    }

    ensureOriginal(button);
    clearResetTimer(button);
    clearLoadingTimer(button);
    const form = options.form || (button.form instanceof HTMLFormElement ? button.form : null);
    const text = loadingText || (options && options.loadingText) || button.dataset.loadingText || DEFAULT_LOADING_TEXT;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.innerHTML = `
      <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
      <span>${text}</span>
    `;

    const timeout = resolveLoadingTimeout(button, { ...options, form });
    if (Number.isFinite(timeout) && timeout > 0) {
      const timerId = window.setTimeout(() => {
        delete button.dataset.loadingTimeoutId;
        setIdle(button);
        const message = resolveTimeoutMessage(button, form, options);
        const detail = { button, form, message, reason: 'loading-timeout' };
        if (form && message) {
          showStatus(form, message, 'warning');
        }
        const event = new CustomEvent('form-feedback-timeout', { detail, bubbles: true });
        button.dispatchEvent(event);
      }, timeout);
      button.dataset.loadingTimeoutId = String(timerId);
    }
  }

  function setIdle(button) {
    if (!button) return;
    clearLoadingTimer(button);
    clearResetTimer(button);
    button.disabled = false;
    button.removeAttribute('aria-busy');
    if (button.dataset.originalHtml) {
      button.innerHTML = button.dataset.originalHtml;
    }
  }

  function setSuccess(button, successText, delay) {
    if (!button) return;
    ensureOriginal(button);
    clearLoadingTimer(button);
    clearResetTimer(button);
    const text = successText || button.dataset.successText || DEFAULT_SUCCESS_TEXT;
    const timeout = Number.isFinite(delay)
      ? Number(delay)
      : Number(button.dataset.successDelay) || DEFAULT_SUCCESS_DELAY;
    button.disabled = false;
    button.removeAttribute('aria-busy');
    button.innerHTML = `
      <span class="me-2">✅</span>
      <span>${text}</span>
    `;
    const timerId = window.setTimeout(() => {
      if (button.dataset.originalHtml) {
        button.innerHTML = button.dataset.originalHtml;
      }
      delete button.dataset.resetTimeout;
    }, timeout);
    button.dataset.resetTimeout = String(timerId);
  }

  function clearStatus(form) {
    if (!form) return;
    const status = form.querySelector('.form-status-message');
    if (!status) return;
    status.textContent = '';
    status.classList.add('d-none');
    STATUS_VARIANTS.forEach(variant => {
      status.classList.remove(`alert-${variant}`);
    });
  }

  function showStatus(form, message, variant = 'success') {
    if (!form) return;
    const status = form.querySelector('.form-status-message');
    if (!status) return;
    status.textContent = message || '';
    status.classList.remove('d-none');
    STATUS_VARIANTS.forEach(v => {
      status.classList.remove(`alert-${v}`);
    });
    const normalized = STATUS_VARIANTS.includes(variant) ? variant : 'info';
    status.classList.add(`alert-${normalized}`);
  }

  function normalizeResult(result, options = {}) {
    const normalized = {
      success: true,
      message: undefined,
      level: undefined,
      keepButton: false,
      successText: undefined,
      resetDelay: undefined,
    };

    if (typeof result === 'boolean') {
      normalized.success = result;
    } else if (result instanceof Response) {
      normalized.success = result.ok;
      normalized.response = result;
    } else if (result && typeof result === 'object') {
      if ('success' in result) normalized.success = Boolean(result.success);
      if ('message' in result && typeof result.message === 'string') {
        normalized.message = result.message;
      }
      if ('level' in result && typeof result.level === 'string') {
        normalized.level = result.level;
      }
      if ('keepButton' in result) normalized.keepButton = Boolean(result.keepButton);
      if ('successText' in result && typeof result.successText === 'string') {
        normalized.successText = result.successText;
      }
      if ('resetDelay' in result && Number.isFinite(result.resetDelay)) {
        normalized.resetDelay = Number(result.resetDelay);
      }
    }

    if (typeof options.success === 'boolean') {
      normalized.success = options.success;
    }
    if (typeof options.message === 'string') {
      normalized.message = options.message;
    }
    if (typeof options.level === 'string') {
      normalized.level = options.level;
    }
    if (typeof options.keepButton === 'boolean') {
      normalized.keepButton = options.keepButton;
    }

    return normalized;
  }

  async function withSavingState(target, action, options = {}) {
    const button = getButton(target);
    if (!button) {
      return action();
    }

    const form = options.form || (target instanceof HTMLFormElement ? target : null);
    if (form) {
      clearStatus(form);
    }

    const loadingOptions = { form };
    if (typeof options.loadingText !== 'undefined') {
      loadingOptions.loadingText = options.loadingText;
    }
    if (typeof options.loadingTimeout !== 'undefined') {
      loadingOptions.loadingTimeout = options.loadingTimeout;
    }
    if (Object.prototype.hasOwnProperty.call(options, 'timeoutMessage')) {
      loadingOptions.timeoutMessage = options.timeoutMessage;
    }
    setLoading(button, loadingOptions);

    const timeoutMs = Number(options.loadingTimeout);
    const hasTimeout = Number.isFinite(timeoutMs) && timeoutMs > 0;
    const timeoutMessage = options.timeoutMessage || DEFAULT_TIMEOUT_MESSAGE;
    const timeoutLevel = options.timeoutLevel || 'warning';
    const actionPromise = Promise.resolve().then(() => action());
    let timeoutId;
    let timedOut = false;
    let result;

    let racePromise = actionPromise;
    if (hasTimeout) {
      const timeoutError = new Error(timeoutMessage);
      timeoutError.name = 'SavingStateTimeoutError';
      racePromise = Promise.race([
        actionPromise,
        new Promise((_, reject) => {
          timeoutId = window.setTimeout(() => {
            timedOut = true;
            reject(timeoutError);
          }, timeoutMs);
        })
      ]);
    }

    try {
      result = await racePromise;
      if (hasTimeout && timeoutId) {
        window.clearTimeout(timeoutId);
      }
    } catch (error) {
      if (hasTimeout && timeoutId) {
        window.clearTimeout(timeoutId);
      }
      if (timedOut && actionPromise && typeof actionPromise.catch === 'function') {
        actionPromise.catch(() => {});
      }
      if (timedOut && typeof options.onTimeout === 'function') {
        try {
          options.onTimeout(error);
        } catch (callbackError) {
          console.error('Erro no callback onTimeout', callbackError);
        }
      }
      setIdle(button);
      if (form) {
        if (timedOut) {
          showStatus(form, timeoutMessage || DEFAULT_TIMEOUT_MESSAGE, timeoutLevel);
        } else {
          showStatus(form, options.errorMessage || DEFAULT_ERROR_TEXT, 'danger');
        }
      }
      throw error;
    }

    const normalized = normalizeResult(result, options);

    if (form && normalized.message) {
      const level = normalized.level || (normalized.success ? 'success' : 'danger');
      showStatus(form, normalized.message, level);
    } else if (!normalized.success && form && options.errorMessage) {
      showStatus(form, options.errorMessage, 'danger');
    }

    if (!normalized.keepButton) {
      if (normalized.success) {
        const successText = options.successText || normalized.successText;
        setSuccess(button, successText, options.successDelay ?? normalized.resetDelay);
      } else {
        setIdle(button);
      }
    }

    return result;
  }

  function handleDataSyncForm(form) {
    form.addEventListener('submit', () => {
      const button = getButton(form);
      if (!button) return;
      setLoading(button, { form });
      clearStatus(form);
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('form[data-sync]').forEach(handleDataSyncForm);
  });

  document.addEventListener('form-sync-success', (ev) => {
    const detail = ev.detail || {};
    const form = detail.form;
    if (!form) return;
    const button = getButton(form);
    if (!button) return;

    const hadError = Boolean((detail.data && detail.data.success === false) || (detail.response && !detail.response.ok));
    if (hadError) {
      setIdle(button);
      const errorMessage = detail.data && (detail.data.message || detail.data.error) || DEFAULT_ERROR_TEXT;
      showStatus(form, errorMessage, 'danger');
      return;
    }

    const message = detail.data && detail.data.message;
    setSuccess(button);
    if (message) {
      showStatus(form, message, 'success');
    } else {
      clearStatus(form);
    }
  });

  window.FormFeedback = {
    getButton,
    setLoading,
    setIdle,
    setSuccess,
    showStatus,
    clearStatus,
    withSavingState,
  };
})();
