(function () {
  const table = document.querySelector('[data-plantao-table]');
  const rows = table ? Array.from(table.querySelectorAll('tbody tr')) : [];
  const filterSelect = document.querySelector('[data-plantao-filter]');
  const sortSelect = document.querySelector('[data-plantao-sort]');
  const searchInput = document.querySelector('[data-plantao-search]');

  if (table) {
    function highlightLateRows() {
      rows.forEach((row) => {
        if (row.dataset.atrasado === '1') {
          row.classList.add('table-warning');
        } else {
          row.classList.remove('table-warning');
        }
      });
    }

    function applyFilter() {
      const medicoId = filterSelect ? filterSelect.value : '';
      const term = searchInput ? searchInput.value.toLowerCase().trim() : '';
      rows.forEach((row) => {
        const matchesMedico = !medicoId || row.dataset.medico === medicoId;
        const matchesTerm = !term || row.textContent.toLowerCase().includes(term);
        row.style.display = matchesMedico && matchesTerm ? '' : 'none';
      });
    }

    function compareRows(a, b, key, direction) {
      const multiplier = direction === 'desc' ? -1 : 1;
      if (key === 'turno') {
        return a.dataset.turno.localeCompare(b.dataset.turno) * multiplier;
      }
      const dateA = new Date(a.dataset.inicio);
      const dateB = new Date(b.dataset.inicio);
      return (dateA - dateB) * multiplier;
    }

    function applySort() {
      if (!sortSelect) {
        return;
      }
      const value = sortSelect.value || 'inicio:asc';
      const [key, direction] = value.split(':');
      const sorted = rows.slice().sort((a, b) => compareRows(a, b, key, direction));
      const tbody = table.querySelector('tbody');
      sorted.forEach((row) => tbody.appendChild(row));
    }

    filterSelect && filterSelect.addEventListener('change', applyFilter);
    searchInput && searchInput.addEventListener('input', applyFilter);
    sortSelect && sortSelect.addEventListener('change', () => {
      applySort();
      highlightLateRows();
    });

    applySort();
    applyFilter();
    highlightLateRows();
  }

  const modelosData = Array.isArray(window.PLANTAO_MODELOS) ? window.PLANTAO_MODELOS : [];
  const modeloSelect = document.querySelector('[data-plantao-modelo-select]');
  const aplicarModeloBtn = document.querySelector('[data-plantao-modelo-aplicar]');
  const clinicSelect = document.querySelector('[data-plantao-clinic]');
  const turnoInput = document.querySelector('[data-plantao-turno]');
  const horaInicioInput = document.querySelector('[data-plantao-hora-inicio]');
  const horaFimInput = document.querySelector('[data-plantao-hora-fim]');
  const medicoSelect = document.querySelector('[data-plantao-medico]');
  const medicoNomeInput = document.querySelector('[data-plantao-medico-nome]');
  const medicoCnpjInput = document.querySelector('[data-plantao-medico-cnpj]');

  function renderModeloOptions() {
    if (!modeloSelect) {
      return;
    }
    const selectedClinic = clinicSelect ? Number(clinicSelect.value) : null;
    const currentValue = Number(modeloSelect.value || 0);
    modeloSelect.innerHTML = '';
    const placeholder = new Option('Sem modelo salvo', 0, true, false);
    modeloSelect.appendChild(placeholder);

    modelosData
      .filter((modelo) => !selectedClinic || modelo.clinic_id === selectedClinic)
      .forEach((modelo) => {
        const option = new Option(`${modelo.nome} — ${modelo.duracao_horas}h`, modelo.id);
        if (modelo.id === currentValue) {
          option.selected = true;
        }
        modeloSelect.appendChild(option);
      });
  }

  function formatEndTime(startValue, durationHours) {
    if (!startValue || !durationHours) {
      return null;
    }
    const [hours, minutes] = startValue.split(':').map((v) => parseInt(v, 10));
    if (Number.isNaN(hours) || Number.isNaN(minutes)) {
        return null;
    }
    const start = new Date();
    start.setHours(hours, minutes, 0, 0);
    const end = new Date(start.getTime() + durationHours * 60 * 60 * 1000);
    const hh = String(end.getHours()).padStart(2, '0');
    const mm = String(end.getMinutes()).padStart(2, '0');
    return `${hh}:${mm}`;
  }

  function applyModelo() {
    if (!modeloSelect) {
      return;
    }
    const modeloId = Number(modeloSelect.value || 0);
    if (!modeloId) {
      return;
    }
    const modelo = modelosData.find((item) => item.id === modeloId);
    if (!modelo) {
      return;
    }
    if (turnoInput) {
      turnoInput.value = modelo.nome || '';
    }
    if (horaInicioInput && modelo.hora_inicio) {
      horaInicioInput.value = modelo.hora_inicio;
      const end = formatEndTime(modelo.hora_inicio, modelo.duracao_horas);
      if (horaFimInput && end) {
        horaFimInput.value = end;
      }
    }
    if (medicoSelect && modelo.medico_id) {
      medicoSelect.value = String(modelo.medico_id);
    }
    if (medicoNomeInput && modelo.medico_nome) {
      medicoNomeInput.value = modelo.medico_nome;
    }
    if (medicoCnpjInput && modelo.medico_cnpj) {
      medicoCnpjInput.value = modelo.medico_cnpj;
    }
  }

  if (modeloSelect) {
    renderModeloOptions();
    aplicarModeloBtn && aplicarModeloBtn.addEventListener('click', applyModelo);
    clinicSelect && clinicSelect.addEventListener('change', () => {
      renderModeloOptions();
      modeloSelect.value = '0';
    });
  }
})();
