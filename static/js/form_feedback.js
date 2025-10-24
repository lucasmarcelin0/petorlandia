(function() {
  const DEFAULT_LOADING_TEXT = 'Salvando...';
  const DEFAULT_SUCCESS_TEXT = 'Salvo!';
  const DEFAULT_ERROR_TEXT = 'Não foi possível salvar as alterações.';
  const DEFAULT_SUCCESS_DELAY = 2000;
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

  function setLoading(button, loadingText) {
    if (!button) return;
    ensureOriginal(button);
    clearResetTimer(button);
    const text = loadingText || button.dataset.loadingText || DEFAULT_LOADING_TEXT;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.innerHTML = `
      <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
      <span>${text}</span>
    `;
  }

  function setIdle(button) {
    if (!button) return;
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

    setLoading(button, options.loadingText);

    let result;
    try {
      result = await action();
    } catch (error) {
      setIdle(button);
      if (form) {
        showStatus(form, options.errorMessage || DEFAULT_ERROR_TEXT, 'danger');
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
      setLoading(button);
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
