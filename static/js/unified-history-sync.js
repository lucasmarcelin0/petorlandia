/**
 * UNIFIED HISTORY SYNCHRONIZATION SYSTEM
 *
 * Centralized, reliable solution for updating history after form saves.
 * Prevents duplicate saves by disabling buttons and provides guaranteed feedback.
 *
 * Features:
 * - Single source of truth for all history updates
 * - Automatic form disable after successful save
 * - Guaranteed history refresh with fallback paths
 * - Clear user feedback at every step
 */

if (!window.HistorySyncManagerClass) {
  class HistorySyncManager {
  constructor() {
    this.isProcessing = false;
    this.lastSyncTime = {};
    this.syncRetries = 3;
    this.retryDelayMs = 500;
  }

  /**
   * Unified entry point for all history saves and updates.
   * 
   * @param {string} endpoint - API endpoint to POST data to (e.g., '/consulta/123/bloco_prescricao')
   * @param {object} data - JSON data to send to endpoint
   * @param {string} historyContainerId - DOM element ID to update with new history (e.g., 'historico-prescricoes')
   * @param {HTMLElement} submitButton - Button element to disable after success
   * @param {object} options - Optional configuration
   * @returns {Promise<{success: boolean, message: string, retried: boolean}>}
   */
  async saveAndUpdateHistory(endpoint, data, historyContainerId, submitButton, options = {}) {
    const {
      successMessage = 'Salvo com sucesso!',
      errorMessage = 'Erro ao salvar',
      timeoutMs = 10000,
      showOfflineNotice = false,
      disableFormAfterSuccess = true,
      onSuccess = null,
      onError = null,
    } = options;

    // Prevent concurrent saves
    if (this.isProcessing) {
      console.warn('[HistorySyncManager] Save already in progress');
      return { success: false, message: 'Salvamento em andamento...', retried: false };
    }

    this.isProcessing = true;
    let retried = false;

    try {
      // Disable button immediately
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.classList.add('disabled');
        const originalText = submitButton.textContent;
        submitButton.textContent = 'Salvando...';
        submitButton.dataset.originalText = originalText;
      }

      // Show loading feedback
      this._showFeedback('Salvando...', 'info');

      // Attempt save with retry logic
      let response;
      let lastError;

      for (let attempt = 0; attempt <= this.syncRetries; attempt++) {
        try {
          response = await this._performSave(endpoint, data, timeoutMs);
          
          if (response && response.ok) {
            break; // Success on this attempt
          }
          
          lastError = new Error(`HTTP ${response?.status || 'unknown'}`);
          
          // Only retry on network-like errors or specific status codes
          if (attempt < this.syncRetries && this._shouldRetry(response)) {
            retried = true;
            await this._delay(this.retryDelayMs * (attempt + 1));
            continue;
          }
          break;
        } catch (err) {
          lastError = err;
          if (attempt < this.syncRetries) {
            retried = true;
            await this._delay(this.retryDelayMs * (attempt + 1));
            continue;
          }
        }
      }

      if (!response || !response.ok) {
        throw lastError || new Error('No response from server');
      }

      // Parse response
      const result = await response.json();

      if (!result.success) {
        throw new Error(result.message || errorMessage);
      }

      // Update history with guaranteed fallback
      await this._updateHistoryWithFallback(historyContainerId, result.html);

      // Disable form after success to prevent accidental duplicates
      if (disableFormAfterSuccess) {
        this._disableForm(submitButton);
      }

      // Show success
      this._showFeedback(successMessage, 'success', 4000);

      if (onSuccess) {
        await onSuccess(result);
      }

      // Re-enable the button when we are not locking the entire form
      if (submitButton && !disableFormAfterSuccess) {
        submitButton.disabled = false;
        submitButton.classList.remove('disabled');
        submitButton.textContent = submitButton.dataset.originalText || 'Salvar';
      }

      return { success: true, message: successMessage, retried };

    } catch (error) {
      console.error('[HistorySyncManager] Error:', error);
      
      // Show error feedback
      const errorMsg = error.message || errorMessage;
      this._showFeedback(errorMsg, 'danger', 5000);

      if (onError) {
        await onError(error);
      }

      // Re-enable button on error so user can retry
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.classList.remove('disabled');
      }

      return { success: false, message: errorMsg, retried };

    } finally {
      this.isProcessing = false;
    }
  }

  /**
   * Perform the actual POST request with timeout
   */
  async _performSave(endpoint, data, timeoutMs) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify(data),
        signal: controller.signal,
      });
      return response;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  /**
   * Determine if we should retry this error
   */
  _shouldRetry(response) {
    if (!response) return true; // Network error
    
    // Retry on timeout (0) or server errors (5xx), but not on client errors (4xx)
    const status = response.status;
    return status === 0 || status >= 500;
  }

  /**
   * Update history container with guaranteed fallback
   * 
   * Try direct DOM update first, then fetch fresh HTML as fallback
   */
  async _updateHistoryWithFallback(containerId, responseHtml) {
    const container = document.getElementById(containerId);
    
    if (!container) {
      console.warn(`[HistorySyncManager] Container #${containerId} not found`);
      return false;
    }

    // Try direct update first (fastest path)
    if (responseHtml) {
      try {
        container.innerHTML = responseHtml;
        if (typeof formatBrazilTimestamps === 'function') {
          formatBrazilTimestamps(container);
        }
        return true;
      } catch (err) {
        console.warn(`[HistorySyncManager] Failed to update container directly:`, err);
      }
    }

    // Fallback: return false and let caller handle (they may fetch fresh data)
    return false;
  }

  /**
   * Disable the entire form to prevent accidental resubmission
   */
  _disableForm(submitButton) {
    if (!submitButton) return;

    // Find the form
    const form = submitButton.closest('form');
    if (!form) return;

    // Disable all inputs and buttons in the form
    const inputs = form.querySelectorAll('input, textarea, select, button');
    inputs.forEach(input => {
      input.disabled = true;
      input.classList.add('disabled');
    });

    // Show message that form is submitted
    submitButton.textContent = '✅ ' + (submitButton.dataset.originalText || 'Salvo');
  }

  /**
   * Show user feedback message
   */
  _showFeedback(message, level = 'info', durationMs = null) {
    const feedbackDiv = document.getElementById('feedback-message') || 
                        this._createFeedbackElement();
    
    feedbackDiv.textContent = message;
    feedbackDiv.className = `alert alert-${level} position-fixed`;
    feedbackDiv.style.cssText = 'top: 20px; right: 20px; z-index: 1050; min-width: 300px;';
    feedbackDiv.classList.remove('d-none');

    if (durationMs) {
      setTimeout(() => {
        feedbackDiv.classList.add('d-none');
      }, durationMs);
    }
  }

  /**
   * Create feedback element if it doesn't exist
   */
  _createFeedbackElement() {
    const div = document.createElement('div');
    div.id = 'feedback-message';
    document.body.appendChild(div);
    return div;
  }

  /**
   * Simple delay utility
   */
  _delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
  }

  // Expose the constructor to avoid redeclaration errors on repeated script loads
  window.HistorySyncManagerClass = HistorySyncManager;
}

const HistorySyncManagerClass = window.HistorySyncManagerClass;

// Global instance
window.HistorySyncManager = window.HistorySyncManager || new HistorySyncManagerClass();

/**
 * LEGACY COMPATIBILITY WRAPPER
 * 
 * For existing code that expects old function names, we provide wrappers
 * that use the new unified system internally.
 */

/**
 * Universal function for reloading any history section
 * 
 * @param {string} historyType - 'prescricoes', 'exames', 'vacinas', or 'orcamentos'
 * @param {number} animalOrConsultaId - Animal ID or Consulta ID depending on type
 * @param {object} options - Optional configuration
 * @returns {Promise<boolean>} - true if successfully updated, false otherwise
 */
if (!window.recarregarHistorico) {
  async function recarregarHistorico(historyType, animalOrConsultaId, options = {}) {
    const endpoints = {
      prescricoes: `/consulta/${animalOrConsultaId}/historico_prescricoes`,
      exames: `/animal/${animalOrConsultaId}/historico_exames`,
      vacinas: `/animal/${animalOrConsultaId}/historico_vacinas`,
      orcamentos: `/consulta/${animalOrConsultaId}/historico_orcamentos`,
    };

    const containerIds = {
      prescricoes: 'historico-prescricoes',
      exames: 'historico-exames',
      vacinas: 'historico-vacinas',
      orcamentos: 'historico-orcamentos',
    };

    const endpoint = endpoints[historyType];
    const containerId = containerIds[historyType];

    if (!endpoint || !containerId) {
      console.error(`[recarregarHistorico] Unknown history type: ${historyType}`);
      return false;
    }

    try {
      const response = await fetch(endpoint);
      if (!response.ok) return false;

      const data = await response.json();
      if (!data.html) return false;

      const container = document.getElementById(containerId);
      if (!container) {
        console.warn(`[recarregarHistorico] Container #${containerId} not found`);
        return false;
      }

      container.innerHTML = data.html;
      if (typeof formatBrazilTimestamps === 'function') {
        formatBrazilTimestamps(container);
      }
      return true;
    } catch (err) {
      console.error(`[recarregarHistorico] Error reloading ${historyType}:`, err);
      return false;
    }
  }
  window.recarregarHistorico = recarregarHistorico;
}

/**
 * LEGACY: recarregarHistoricoPrescricoes - for backward compatibility
 */
if (!window.recarregarHistoricoPrescricoes) {
  async function recarregarHistoricoPrescricoes(options = {}) {
    const showFailureNotice = options.showFailureNotice !== false;
    const success = await recarregarHistorico('prescricoes', document.querySelector('[data-consulta-id]')?.dataset.consultaId);

    if (!success && showFailureNotice) {
      console.warn('[recarregarHistoricoPrescricoes] Failed to reload');
    }

    return success;
  }
  window.recarregarHistoricoPrescricoes = recarregarHistoricoPrescricoes;
}

/**
 * LEGACY: recarregarHistoricoExames - for backward compatibility
 */
if (!window.recarregarHistoricoExames) {
  async function recarregarHistoricoExames(options = {}) {
    const showFailureNotice = options.showFailureNotice !== false;
    const success = await recarregarHistorico('exames', document.querySelector('[data-animal-id]')?.dataset.animalId);

    if (!success && showFailureNotice) {
      console.warn('[recarregarHistoricoExames] Failed to reload');
    }

    return success;
  }
  window.recarregarHistoricoExames = recarregarHistoricoExames;
}

/**
 * LEGACY: recarregarHistoricoVacinas - for backward compatibility
 */
if (!window.recarregarHistoricoVacinas) {
  async function recarregarHistoricoVacinas(options = {}) {
    const showFailureNotice = options.showFailureNotice !== false;
    const success = await recarregarHistorico('vacinas', document.querySelector('[data-animal-id]')?.dataset.animalId);

    if (!success && showFailureNotice) {
      console.warn('[recarregarHistoricoVacinas] Failed to reload');
    }

    return success;
  }
  window.recarregarHistoricoVacinas = recarregarHistoricoVacinas;
}
