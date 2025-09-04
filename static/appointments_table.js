function bindAppointmentRowClicks() {
  const modalEl = document.getElementById('appointmentEditModal');
  const modalBody = modalEl ? modalEl.querySelector('.modal-body') : null;
  const bsModal = modalEl ? new bootstrap.Modal(modalEl) : null;

  document.querySelectorAll('.appointment-row').forEach(function(row) {
    row.addEventListener('click', function(e) {
      if (e.target.closest('.btn')) {
        return;
      }
      const url = this.dataset.href;
      if (!url) return;
      if (modalEl && modalBody && bsModal) {
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
          .then(resp => resp.text())
          .then(html => {
            modalBody.innerHTML = html;
            const form = modalBody.querySelector('#edit-appointment-form');
            if (form) {
              form.addEventListener('submit', async function(ev) {
                ev.preventDefault();
                const payload = {
                  date: modalBody.querySelector('#edit-date').value,
                  time: modalBody.querySelector('#edit-time').value,
                  veterinario_id: modalBody.querySelector('#edit-vet').value
                };
                const tokenEl = modalBody.querySelector('#csrf_token');
                const token = tokenEl ? tokenEl.value : '';
                const resp = await fetch(url, {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': token
                  },
                  body: JSON.stringify(payload)
                });
                if (resp.ok) {
                  bsModal.hide();
                  window.location.reload();
                } else {
                  let err = 'Erro ao salvar';
                  try {
                    const data = await resp.json();
                    if (data.message) err = data.message;
                  } catch (e) {}
                  alert(err);
                }
              });
            }
            bsModal.show();
          });
      } else {
        window.location = url;
      }
    });
  });
}

document.addEventListener('DOMContentLoaded', bindAppointmentRowClicks);

function activateAnimalTabs() {
  document.querySelectorAll('#animalTabs button[data-bs-toggle="tab"]').forEach(function (triggerEl) {
    triggerEl.addEventListener('click', function (e) {
      e.preventDefault();
      bootstrap.Tab.getOrCreateInstance(triggerEl).show();
    });
  });
}

document.addEventListener('DOMContentLoaded', activateAnimalTabs);
