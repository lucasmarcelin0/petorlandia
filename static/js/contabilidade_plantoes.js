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
  const modalEl = document.getElementById('plantaoAgendarModal');
  const modalDayButtons = document.querySelectorAll('[data-plantao-agendar-dia]');

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

  function formatDayLabel(value) {
    if (!value) {
      return '';
    }
    const date = new Date(value);
    return date.toLocaleDateString('pt-BR', {
      weekday: 'long',
      day: '2-digit',
      month: 'long'
    });
  }

  function renderQuickModeloOptions(selectEl, clinicId) {
    if (!selectEl) {
      return;
    }
    const modelos = Array.isArray(window.PLANTAO_MODELOS) ? window.PLANTAO_MODELOS : [];
    const filtered = modelos.filter((modelo) => !clinicId || Number(modelo.clinic_id) === Number(clinicId));
    selectEl.innerHTML = '';
    const placeholder = new Option('Selecione um modelo ou crie manualmente', '');
    selectEl.appendChild(placeholder);
    filtered.forEach((modelo) => {
      const option = new Option(`${modelo.nome} — ${modelo.duracao_horas}h`, modelo.id);
      selectEl.appendChild(option);
    });
  }

  function renderQuickMedicos(selectEl) {
    if (!selectEl) {
      return;
    }
    const medicos = Array.isArray(window.PLANTAO_MEDICOS) ? window.PLANTAO_MEDICOS : [];
    selectEl.innerHTML = '';
    selectEl.appendChild(new Option('Escolha quem irá cobrir o plantão', ''));
    medicos.forEach(([id, nome]) => {
      selectEl.appendChild(new Option(nome, id));
    });
  }

  function renderQuickChips(container, clinicId, targetSelect) {
    if (!container || !targetSelect) {
      return;
    }
    const modelos = Array.isArray(window.PLANTAO_MODELOS) ? window.PLANTAO_MODELOS : [];
    const filtered = modelos.filter((modelo) => !clinicId || Number(modelo.clinic_id) === Number(clinicId));
    container.innerHTML = '';
    filtered.slice(0, 4).forEach((modelo) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'btn btn-outline-secondary btn-sm plantao-quick-chip';
      chip.textContent = modelo.nome;
      chip.addEventListener('click', () => {
        targetSelect.value = String(modelo.id);
      });
      container.appendChild(chip);
    });
  }

  if (modalEl && modalDayButtons.length) {
    const modal = new bootstrap.Modal(modalEl);
    const dayLabel = modalEl.querySelector('[data-plantao-dia-label]');
    const dayInput = modalEl.querySelector('[data-plantao-dia-input]');
    const quickForm = modalEl.querySelector('[data-plantao-quick-form]');
    const modeloQuickSelect = modalEl.querySelector('[data-plantao-modal-modelo]');
    const medicoQuickSelect = modalEl.querySelector('[data-plantao-modal-medico]');
    const chipsContainer = modalEl.querySelector('[data-plantao-modal-chips]');
    const quickOptions = modalEl.querySelectorAll('[data-plantao-quick-option]');
    const clinicId = window.PLANTAO_DEFAULTS ? window.PLANTAO_DEFAULTS.clinicaId : null;

    renderQuickModeloOptions(modeloQuickSelect, clinicId);
    renderQuickMedicos(medicoQuickSelect);
    renderQuickChips(chipsContainer, clinicId, modeloQuickSelect);

    modalDayButtons.forEach((button) => {
      button.addEventListener('click', () => {
        const dia = button.dataset.dia;
        if (dayInput) {
          dayInput.value = dia;
        }
        if (dayLabel) {
          dayLabel.textContent = formatDayLabel(dia);
        }
        modal.show();
      });
    });

    quickOptions.forEach((option) => {
      option.addEventListener('click', () => {
        const action = option.dataset.plantaoQuickOption;
        if (action === 'limpar') {
          if (modeloQuickSelect) {
            modeloQuickSelect.value = '';
          }
          if (medicoQuickSelect) {
            medicoQuickSelect.value = '';
          }
        }
        if (action === 'modelo' && modeloQuickSelect && modeloQuickSelect.options.length > 1) {
          modeloQuickSelect.selectedIndex = 1;
        }
      });
    });

    if (quickForm) {
      quickForm.addEventListener('submit', async (event) => {
        const modeloId = modeloQuickSelect ? modeloQuickSelect.value : '';
        const medicoId = medicoQuickSelect ? medicoQuickSelect.value : '';
        const shouldQuickCreate = Boolean(modeloId && medicoId);

        if (!shouldQuickCreate) {
          if (modeloQuickSelect && !modeloQuickSelect.value) {
            modeloQuickSelect.name = '';
          }
          if (medicoQuickSelect && !medicoQuickSelect.value) {
            medicoQuickSelect.name = '';
          }
          return;
        }

        event.preventDefault();
        const submitBtn = quickForm.querySelector('button[type="submit"]');
        const originalText = submitBtn ? submitBtn.innerHTML : '';
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Agendando...';
        }

        try {
          const endpoint = quickForm.dataset.plantaoQuickEndpoint || '/contabilidade/pagamentos/plantonistas/quick-create';
          const payload = {
            clinica_id: clinicId,
            modelo_id: Number(modeloId),
            medico_id: Number(medicoId),
            dia: dayInput ? dayInput.value : null,
          };

          const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(quickForm.dataset.plantaoCsrf ? { 'X-CSRFToken': quickForm.dataset.plantaoCsrf } : {}),
            },
            body: JSON.stringify(payload),
          });

          const result = await response.json();
          if (!response.ok) {
            throw new Error(result.error || 'Não foi possível criar o plantão.');
          }

          if (result.redirect) {
            window.location.href = result.redirect;
          } else {
            window.location.reload();
          }
        } catch (error) {
          alert(error.message || 'Erro ao agendar o plantão.');
        } finally {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalText || 'Agendar direto';
          }
        }
      });
    }
  }

  const sidebar = document.querySelector('[data-plantao-sidebar]');
  const sidebarToggle = document.querySelector('[data-plantao-sidebar-toggle]');
  const sidebarClose = document.querySelector('[data-plantao-sidebar-close]');

  if (sidebar && sidebarToggle) {
    function setSidebar(open) {
      sidebar.classList.toggle('d-none', !open);
      sidebarToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      sidebarToggle.innerHTML = `<i class="fas fa-lightbulb me-1"></i>${open ? 'Esconder dicas' : 'Mostrar dicas'}`;
      sidebarToggle.classList.toggle('btn-outline-secondary', !open);
      sidebarToggle.classList.toggle('btn-secondary', open);
    }

    let sidebarOpen = false;
    setSidebar(false);

    sidebarToggle.addEventListener('click', () => {
      sidebarOpen = !sidebarOpen;
      setSidebar(sidebarOpen);
    });

    if (sidebarClose) {
      sidebarClose.addEventListener('click', () => {
        sidebarOpen = false;
        setSidebar(sidebarOpen);
      });
    }
  }
})();
