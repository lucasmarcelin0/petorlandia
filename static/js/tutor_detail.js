// Filter animal rows by name in tutor detail page
window.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('animal-search');
  const table = document.getElementById('animais-table');
  if (!searchInput || !table) return;
  searchInput.addEventListener('input', () => {
    const query = searchInput.value.toLowerCase();
    table.querySelectorAll('tbody tr').forEach(row => {
      const nameEl = row.querySelector('.animal-name');
      if (!nameEl) return;
      const matches = nameEl.textContent.toLowerCase().includes(query);
      row.style.display = matches ? '' : 'none';
    });
  });
});
