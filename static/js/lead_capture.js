(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var modalElement = document.getElementById('leadCaptureModal');
    var form = document.getElementById('leadCaptureForm');
    if (!modalElement || !form) return;

    var title = document.getElementById('leadCaptureTitle');
    var description = document.getElementById('leadCaptureDescription');
    var featureInput = form.querySelector('[name="feature"]');
    var contactInput = form.querySelector('[name="contact"]');
    var cityInput = form.querySelector('[name="city"]');
    var feedback = form.querySelector('.lead-capture__feedback');
    var button = form.querySelector('button[type="submit"]');
    var defaultButtonLabel = button.textContent.trim();

    document.querySelectorAll('[data-lead-capture]').forEach(function (trigger) {
      trigger.addEventListener('click', function () {
        featureInput.value = trigger.dataset.leadFeature || 'demo_clinica';
        title.textContent = trigger.dataset.leadTitle || 'Ver uma demonstração';
        description.textContent = trigger.dataset.leadDescription ||
          'Deixe seu contato. A gente combina um horário e mostra o fluxo da PetOrlândia aplicado à sua rotina.';
        feedback.className = 'lead-capture__feedback alert d-none';
        feedback.textContent = '';
        form.querySelectorAll('input:not([type="hidden"]), button').forEach(function (element) {
          element.disabled = false;
        });
        button.disabled = false;
        button.textContent = defaultButtonLabel;
      });
    });

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var contact = (contactInput.value || '').trim();
      if (contact.length < 6) {
        feedback.textContent = 'Informe um e-mail ou celular para conseguirmos responder.';
        feedback.className = 'lead-capture__feedback alert alert-danger';
        contactInput.focus();
        return;
      }

      button.disabled = true;
      button.textContent = 'Enviando...';
      feedback.className = 'lead-capture__feedback alert d-none';

      var csrfMeta = document.querySelector('meta[name="csrf-token"]');
      fetch(form.dataset.endpoint, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfMeta ? csrfMeta.content : ''
        },
        body: JSON.stringify({
          feature: featureInput.value,
          contact: contact,
          city: (cityInput.value || '').trim()
        })
      })
        .then(function (response) {
          return response.json().then(function (data) {
            return { ok: response.ok, data: data };
          });
        })
        .then(function (result) {
          feedback.textContent = result.data.message || 'Pedido recebido.';
          feedback.className = 'lead-capture__feedback alert ' +
            (result.ok && result.data.success ? 'alert-success' : 'alert-danger');
          if (result.ok && result.data.success) {
            form.querySelectorAll('input:not([type="hidden"]), button').forEach(function (element) {
              element.disabled = true;
            });
            button.textContent = 'Pedido recebido ✓';
            return;
          }
          button.disabled = false;
          button.textContent = defaultButtonLabel;
        })
        .catch(function () {
          feedback.textContent = 'Não conseguimos registrar agora. Tente novamente em instantes.';
          feedback.className = 'lead-capture__feedback alert alert-danger';
          button.disabled = false;
          button.textContent = defaultButtonLabel;
        });
    });
  });
})();
