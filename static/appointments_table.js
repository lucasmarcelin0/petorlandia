function bindAppointmentRowClicks() {
  document.querySelectorAll('.appointment-row').forEach(function(row) {
    row.addEventListener('click', function(e) {
      if (e.target.closest('.btn')) {
        return;
      }
      const url = this.dataset.href;
      if (url) {
        window.location = url;
      }
    });
  });
}

document.addEventListener('DOMContentLoaded', bindAppointmentRowClicks);
