(function () {
  async function postJSON(url, payload) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    };
    if (csrfToken) {
      headers['X-CSRFToken'] = csrfToken;
    }
    const resp = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload || {})
    });
    let data = {};
    try {
      data = await resp.json();
    } catch (err) {
      data = {};
    }
    if (!resp.ok || data.success === false) {
      throw new Error(data.message || 'Não foi possível concluir a operação.');
    }
    return data;
  }

  async function handleShareRequest(button) {
    const tutorId = button.dataset.tutorId;
    if (!tutorId) {
      alert('Não foi possível identificar o tutor.');
      return;
    }
    const defaultReason = button.dataset.shareReason || 'Solicitar acesso aos dados do tutor';
    const message = prompt('Descreva rapidamente o motivo do acesso:', defaultReason);
    if (message === null) {
      return;
    }
    const payload = {
      tutor_id: Number(tutorId),
      message: message.trim()
    };
    if (button.dataset.animalId) {
      payload.animal_id = Number(button.dataset.animalId);
    }
    try {
      await postJSON('/api/shares', payload);
      alert('Pedido enviado ao tutor! Você será notificado quando for respondido.');
    } catch (error) {
      alert(error.message || 'Não foi possível enviar o pedido.');
    }
  }

  async function handleDecision(button, decision) {
    const requestId = button.dataset.requestId;
    if (!requestId) {
      return;
    }
    let payload = {};
    if (decision === 'deny') {
      const reason = prompt('Deseja informar o motivo da recusa? (opcional)');
      payload.reason = reason ? reason.trim() : '';
    }
    try {
      await postJSON(`/api/shares/${requestId}/${decision}`, payload);
      window.location.reload();
    } catch (error) {
      alert(error.message || 'Falha ao processar pedido.');
    }
  }

  document.addEventListener('click', function (event) {
    const requestButton = event.target.closest('[data-share-request-button]');
    if (requestButton) {
      event.preventDefault();
      handleShareRequest(requestButton);
      return;
    }
    const approveButton = event.target.closest('[data-share-approve]');
    if (approveButton) {
      event.preventDefault();
      handleDecision(approveButton, 'approve');
      return;
    }
    const denyButton = event.target.closest('[data-share-deny]');
    if (denyButton) {
      event.preventDefault();
      handleDecision(denyButton, 'deny');
    }
  });

  async function handleTokenFlow() {
    const container = document.querySelector('[data-share-dashboard]');
    if (!container) {
      return;
    }
    const token = container.dataset.shareToken;
    if (!token) {
      return;
    }
    let requestInfo = null;
    if (container.dataset.tokenRequest) {
      try {
        requestInfo = JSON.parse(container.dataset.tokenRequest);
      } catch (err) {
        requestInfo = null;
      }
    }
    if (!requestInfo) {
      try {
        const resp = await fetch(`/api/share-requests/${token}`, { headers: { 'Accept': 'application/json' } });
        if (!resp.ok) {
          return;
        }
        requestInfo = await resp.json();
      } catch (error) {
        return;
      }
    }
    if (!requestInfo) {
      return;
    }
    const clinicName = requestInfo.clinic || 'uma clínica parceira';
    const animalName = requestInfo.animal ? ` para o animal ${requestInfo.animal}` : '';
    const approve = confirm(`A clínica ${clinicName} solicitou acesso${animalName}. Deseja aprovar agora?`);
    if (approve) {
      try {
        await postJSON('/api/shares/confirm', { token: token, decision: 'approve' });
        window.location.reload();
      } catch (error) {
        alert(error.message || 'Não foi possível aprovar o pedido.');
      }
      return;
    }
    if (confirm('Deseja negar este pedido?')) {
      try {
        await postJSON('/api/shares/confirm', { token: token, decision: 'deny' });
        window.location.reload();
      } catch (error) {
        alert(error.message || 'Não foi possível negar o pedido.');
      }
    }
  }

  handleTokenFlow();
})();
