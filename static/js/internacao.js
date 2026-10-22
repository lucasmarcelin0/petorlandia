(function () {
  'use strict';

  const dateFormat = new Intl.DateTimeFormat('pt-BR', {
    timeZone: 'America/Sao_Paulo', dateStyle: 'short', timeStyle: 'short'
  });

  document.querySelectorAll('[data-ih-print]').forEach(function (button) {
    button.addEventListener('click', function () { window.print(); });
  });

  function syncPrescriptionFields(form) {
    const mode = form.querySelector('[data-ih-modo]').value;
    form.querySelectorAll('[data-ih-modes]').forEach(function (group) {
      const active = group.dataset.ihModes.split(' ').includes(mode);
      group.hidden = !active;
      group.querySelectorAll('input,select,textarea').forEach(function (field) {
        field.disabled = !active;
        field.required = active && field.hasAttribute('data-ih-required');
      });
    });
  }

  function appendParagraph(container, value, strong) {
    const paragraph = document.createElement('p');
    if (strong) {
      const title = document.createElement('strong');
      title.textContent = value;
      paragraph.appendChild(title);
    } else {
      paragraph.textContent = value;
    }
    container.appendChild(paragraph);
  }

  async function previewPrescription(form) {
    if (form.dataset.ihPreviewPending === 'true') return false;
    const panel = form.querySelector('[data-ih-preview]');
    const button = form.querySelector('[data-ih-preview-button]');
    panel.hidden = false;
    panel.replaceChildren();
    if (!form.reportValidity()) {
      appendParagraph(panel, 'Preencha os campos obrigatórios para conferir a programação.');
      return false;
    }
    button.disabled = true;
    form.dataset.ihPreviewPending = 'true';
    appendParagraph(panel, 'Conferindo os horários…');
    const controller = new AbortController();
    const timeout = window.setTimeout(function () { controller.abort(); }, 15000);
    try {
      const response = await fetch(form.dataset.previewUrl, {
        method: 'POST', body: new FormData(form),
        headers: {Accept: 'application/json', 'X-CSRFToken': form.querySelector('[name="csrf_token"]').value},
        credentials: 'same-origin', signal: controller.signal
      });
      if (!response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('Não foi possível conferir os horários. Atualize a página e tente novamente.');
      }
      const result = await response.json();
      panel.replaceChildren();
      if (!response.ok || !result.ok) {
        throw new Error(result.erro || result.message || 'Não foi possível conferir a programação. Revise os dados.');
      }
      const times = result.horarios || [];
      const mode = form.querySelector('[data-ih-modo]').value;
      if (mode === 'prn') {
        appendParagraph(panel, 'Prescrição se necessário (PRN)', true);
        appendParagraph(panel, 'Não gera doses programadas. A equipe registra a administração quando a condição indicada ocorrer, respeitando o intervalo mínimo e o limite em 24 horas.');
      } else {
        appendParagraph(panel, `${result.total ?? times.length} dose(s) prevista(s) · Horários de Brasília`, true);
        const list = document.createElement('ol');
        times.slice(0, 24).forEach(function (value) {
          const item = document.createElement('li');
          item.textContent = dateFormat.format(new Date(value));
          list.appendChild(item);
        });
        panel.appendChild(list);
        if (times.length > 24) appendParagraph(panel, `Mostrando os primeiros 24 horários de ${times.length}. Os demais seguirão a mesma programação até o término informado.`);
      }
      form.dataset.ihPreviewValid = 'true';
      appendParagraph(panel, 'Confira os horários e clique novamente em “Ativar prescrição” ou “Ativar nova versão” para confirmar.');
      return true;
    } catch (error) {
      panel.replaceChildren();
      appendParagraph(panel, error.name === 'AbortError' ? 'A conexão demorou a responder. A prescrição ainda não foi ativada. Tente conferir novamente.' : (error.message || 'Falha de conexão. A prescrição ainda não foi ativada.'));
      form.dataset.ihPreviewValid = 'false';
      return false;
    } finally {
      button.disabled = false;
      form.dataset.ihPreviewPending = 'false';
      window.clearTimeout(timeout);
    }
  }

  function medicationMeta(item, name) {
    const parts = [];
    const active = typeof item.principio_ativo === 'string' ? item.principio_ativo.trim() : '';
    if (active && active.toLocaleLowerCase('pt-BR') !== name.toLocaleLowerCase('pt-BR')) parts.push(active);
    if (item.tipo_item === 'comercial') {
      parts.push(item.fabricante ? 'Marca comercial · ' + item.fabricante : 'Marca comercial');
    } else if (item.classificacao) {
      parts.push(item.classificacao);
    }
    if (item.via_administracao) parts.push('Via: ' + item.via_administracao);
    return parts.filter(function (part) { return typeof part === 'string' && part.trim(); }).join(' · ');
  }

  function plainText(value) {
    return String(value || '').normalize('NFD').replace(/[̀-ͯ]/g, '').trim().toLowerCase();
  }

  const PRACTICAL_UNITS = {
    ml: 'mL', gota: 'gota', gotas: 'gota', comprimido: 'comprimido', comprimidos: 'comprimido',
    capsula: 'capsula', capsulas: 'capsula', ampola: 'ampola', ampolas: 'ampola', sache: 'sache',
    saches: 'sache', aplicacao: 'aplicacao', g: 'g', mg: 'mg', mcg: 'mcg', ui: 'UI'
  };

  // Quantidade: "Outra" abre a descrição livre; a unidade sugerida pela
  // apresentação só substitui a escolhida pela própria sugestão.
  function setupDoseFields(form) {
    const amount = form.querySelector('[data-ih-dose-valor]');
    const unit = form.querySelector('[data-ih-dose-unidade]');
    const other = form.querySelector('[data-ih-dose-outra]');
    if (!amount || !unit || !other) return null;
    function sync() {
      const isOther = unit.value === 'outra';
      other.hidden = !isOther;
      other.required = isOther;
      amount.required = !isOther;
    }
    unit.addEventListener('change', function () {
      unit.dataset.ihAuto = 'false';
      sync();
      if (unit.value === 'outra') other.focus();
    });
    sync();
    return {
      suggest: function (practical) {
        const key = PRACTICAL_UNITS[plainText(practical)];
        if (!key || (unit.value && unit.dataset.ihAuto !== 'true')) return;
        unit.value = key;
        unit.dataset.ihAuto = 'true';
        sync();
      }
    };
  }

  function setupPresentations(form, dose) {
    const select = form.querySelector('[data-ih-apresentacoes]');
    const input = form.querySelector('[data-ih-apresentacao]');
    const help = form.querySelector('[data-ih-apresentacoes-ajuda]');
    const medication = form.querySelector('[data-ih-medicamento]');
    if (!select || !input || !medication || !medication.dataset.detailUrl) return null;
    const defaultHelp = help ? help.textContent : '';
    let sequence = 0;
    let options = [];

    function setHelp(text) {
      if (help) help.textContent = text || defaultHelp;
    }

    function clear() {
      sequence += 1;
      options = [];
      select.replaceChildren();
      select.hidden = true;
      setHelp('');
    }

    select.addEventListener('change', function () {
      const chosen = options[Number(select.value)];
      if (!chosen) return;
      input.value = chosen.descricao;
      input.dispatchEvent(new Event('input', {bubbles: true}));
      if (dose) dose.suggest(chosen.unidade_pratica);
    });

    async function load(detail) {
      clear();
      const id = Number(detail.id);
      if (!id) return;
      const current = sequence;
      setHelp('Buscando apresentações no catálogo…');
      const url = new URL(medication.dataset.detailUrl.replace(/\/0\/detalhe$/, '/' + id + '/detalhe'), window.location.origin);
      if (detail.nome) url.searchParams.set('nome_exibicao', detail.nome);
      if (detail.comercial) url.searchParams.set('nome_comercial_filtro', detail.comercial);
      const controller = new AbortController();
      const timeout = window.setTimeout(function () { controller.abort(); }, 8000);
      try {
        const response = await fetch(url, {
          headers: {Accept: 'application/json'}, credentials: 'same-origin', signal: controller.signal
        });
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error();
        const result = await response.json();
        if (current !== sequence) return;
        const seen = new Set();
        options = (Array.isArray(result.apresentacoes) ? result.apresentacoes : []).filter(function (item) {
          const label = item && typeof item.descricao === 'string' ? item.descricao.trim() : '';
          if (!label || seen.has(label.toLowerCase())) return false;
          seen.add(label.toLowerCase());
          item.descricao = label.slice(0, input.maxLength > 0 ? input.maxLength : 200);
          return true;
        });
        if (!options.length) {
          setHelp('Este medicamento não tem apresentações cadastradas. Digite a apresentação, se houver.');
          return;
        }
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Escolher do catálogo (' + options.length + ')';
        select.appendChild(placeholder);
        options.forEach(function (item, index) {
          const option = document.createElement('option');
          option.value = String(index);
          option.textContent = item.descricao;
          select.appendChild(option);
        });
        select.hidden = false;
        setHelp('Escolha uma apresentação cadastrada ou digite no campo abaixo.');
      } catch (_error) {
        if (current === sequence) setHelp('Não foi possível carregar as apresentações agora. Digite a apresentação, se houver.');
      } finally {
        window.clearTimeout(timeout);
      }
    }

    return {load: load, clear: clear};
  }

  // Lista própria em vez de <datalist>: navegadores de celular não exibem
  // opções preenchidas depois da digitação, e o resultado do catálogo sumia.
  function setupMedicationSearch(form, presentations) {
    const input = form.querySelector('[data-ih-medicamento]');
    if (!input) return;
    const list = document.getElementById(input.getAttribute('aria-controls'));
    if (!list) return;
    let debounceTimer;
    let blurTimer;
    let controller;
    let sequence = 0;
    let activeIndex = -1;
    let selecting = false;

    function options() {
      return Array.from(list.querySelectorAll('[role="option"]'));
    }

    function close() {
      list.hidden = true;
      list.replaceChildren();
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      activeIndex = -1;
    }

    function cancelSearch() {
      sequence += 1;
      window.clearTimeout(debounceTimer);
      if (controller) controller.abort();
    }

    function showStatus(text) {
      list.replaceChildren();
      const status = document.createElement('li');
      status.className = 'ih-suggestions__status';
      status.setAttribute('role', 'presentation');
      status.textContent = text;
      list.appendChild(status);
      list.hidden = false;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      activeIndex = -1;
    }

    function highlight(index) {
      const items = options();
      if (!items.length) return;
      activeIndex = (index + items.length) % items.length;
      items.forEach(function (option, position) {
        option.setAttribute('aria-selected', position === activeIndex ? 'true' : 'false');
      });
      input.setAttribute('aria-activedescendant', items[activeIndex].id);
      items[activeIndex].scrollIntoView({block: 'nearest'});
    }

    function choose(option) {
      cancelSearch();
      const limit = input.maxLength > 0 ? input.maxLength : 200;
      input.value = option.dataset.value.slice(0, limit);
      close();
      if (presentations) presentations.load(option.dataset);
      // Avisa o formulário (invalida a prévia) sem disparar nova busca.
      selecting = true;
      input.dispatchEvent(new Event('input', {bubbles: true}));
      selecting = false;
    }

    function render(items) {
      list.replaceChildren();
      const seen = new Set();
      items.slice(0, 12).forEach(function (item) {
        if (!item || typeof item !== 'object') return;
        const rawName = item.nome_exibicao || item.nome_exibicao_busca || item.nome;
        if (typeof rawName !== 'string' || !rawName.trim()) return;
        const name = rawName.trim();
        const meta = medicationMeta(item, name);
        const key = (name + '|' + meta).toLocaleLowerCase('pt-BR');
        if (seen.has(key)) return;
        seen.add(key);
        const option = document.createElement('li');
        option.id = list.id + '-opcao-' + seen.size;
        option.className = 'ih-suggestions__option';
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');
        option.dataset.value = name;
        if (item.id) option.dataset.id = String(item.id);
        option.dataset.nome = name;
        if (item.tipo_item === 'comercial' && item.nome_comercial_filtro) option.dataset.comercial = item.nome_comercial_filtro;
        const title = document.createElement('span');
        title.className = 'ih-suggestions__name';
        title.textContent = name;
        option.appendChild(title);
        if (meta) {
          const detail = document.createElement('span');
          detail.className = 'ih-suggestions__meta';
          detail.textContent = meta;
          option.appendChild(detail);
        }
        option.addEventListener('click', function () { choose(option); });
        list.appendChild(option);
      });
      if (!seen.size) {
        showStatus('Nenhum medicamento encontrado no catálogo. Você pode manter o nome digitado.');
        return;
      }
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      activeIndex = -1;
    }

    // Mantém o foco no campo ao tocar numa sugestão, para o clique ser aplicado.
    list.addEventListener('mousedown', function (event) { event.preventDefault(); });

    input.addEventListener('input', function () {
      if (selecting) return;
      if (presentations) presentations.clear();
      cancelSearch();
      const query = input.value.trim();
      const currentSequence = sequence;
      if (query.length < 2) {
        close();
        return;
      }
      debounceTimer = window.setTimeout(async function () {
        controller = new AbortController();
        const searchController = controller;
        const timeout = window.setTimeout(function () { searchController.abort(); }, 8000);
        showStatus('Buscando no catálogo…');
        try {
          const url = new URL(input.dataset.searchUrl, window.location.origin);
          url.searchParams.set('q', query);
          const response = await fetch(url, {
            headers: {Accept: 'application/json'}, credentials: 'same-origin', signal: searchController.signal
          });
          if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
            throw new Error('Resposta inválida do catálogo');
          }
          const items = await response.json();
          if (currentSequence !== sequence) return;
          render(Array.isArray(items) ? items : []);
        } catch (_error) {
          // A busca é auxiliar: o nome digitado continua valendo sem conexão.
          if (currentSequence !== sequence) return;
          showStatus('Não foi possível consultar o catálogo agora. Você pode manter o nome digitado.');
        } finally {
          window.clearTimeout(timeout);
        }
      }, 250);
    });

    input.addEventListener('keydown', function (event) {
      if (list.hidden) return;
      const items = options();
      if (event.key === 'ArrowDown' && items.length) {
        event.preventDefault();
        highlight(activeIndex + 1);
      } else if (event.key === 'ArrowUp' && items.length) {
        event.preventDefault();
        highlight(activeIndex <= 0 ? items.length - 1 : activeIndex - 1);
      } else if (event.key === 'Enter' && items[activeIndex]) {
        event.preventDefault();
        choose(items[activeIndex]);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        cancelSearch();
        close();
      }
    });

    input.addEventListener('focus', function () { window.clearTimeout(blurTimer); });
    input.addEventListener('blur', function () {
      window.clearTimeout(blurTimer);
      blurTimer = window.setTimeout(function () {
        cancelSearch();
        close();
      }, 200);
    });
  }

  document.querySelectorAll('[data-ih-prescricao]').forEach(function (form) {
    setupMedicationSearch(form, setupPresentations(form, setupDoseFields(form)));
    syncPrescriptionFields(form);
    form.addEventListener('input', function () {
      form.dataset.ihPreviewValid = 'false';
      const panel = form.querySelector('[data-ih-preview]');
      if (!panel.hidden) {
        panel.replaceChildren();
        appendParagraph(panel, 'A prescrição foi alterada. Confira os horários novamente antes de ativar.');
      }
    });
    form.querySelector('[data-ih-modo]').addEventListener('change', function () {
      syncPrescriptionFields(form);
    });
    form.querySelector('[data-ih-preview-button]').addEventListener('click', function () {
      previewPrescription(form);
    });
    form.addEventListener('submit', function (event) {
      if (form.dataset.ihPreviewValid !== 'true') {
        event.preventDefault();
        previewPrescription(form).then(function () {
          form.querySelector('[data-ih-preview]').scrollIntoView({behavior: 'smooth', block: 'center'});
        });
        return;
      }
      form.querySelectorAll('button[type="submit"]').forEach(function (button) {
        button.disabled = true;
        button.dataset.ihOriginalLabel = button.textContent;
        button.textContent = 'Salvando…';
      });
    });
  });

  const STATUS_LABELS = {administrada: 'Administrada', omitida: 'Não administrada', pendente: 'Pendente'};

  function newKey() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    return 'k' + Date.now().toString(36) + Math.random().toString(36).slice(2);
  }

  // Janela de tolerância calculada no momento do envio: uma tela aberta há
  // horas continua pedindo justificativa quando a dose passa a ficar fora dela.
  function doseWindow(form) {
    const expected = Date.parse(form.dataset.prevista || '');
    const tolerance = Number(form.dataset.tolerancia || 60) * 60000;
    if (!expected) return 'no_horario';
    const now = Date.now();
    if (now < expected - tolerance) return 'antecipada';
    if (now > expected + tolerance) return 'atrasada';
    return 'no_horario';
  }

  function showMessage(form, text, kind) {
    let box = form.querySelector('[data-ih-msg]');
    if (!box) {
      box = document.createElement('p');
      box.dataset.ihMsg = '';
      const button = form.querySelector('button[type="submit"]');
      form.insertBefore(box, button);
    }
    box.className = 'ih-form-msg' + (kind ? ' ih-form-msg--' + kind : '');
    box.setAttribute('role', kind === 'erro' ? 'alert' : 'status');
    box.setAttribute('aria-live', 'polite');
    box.textContent = text;
    box.hidden = !text;
    return box;
  }

  function setBusy(form, busy) {
    form.querySelectorAll('button[type="submit"]').forEach(function (button) {
      if (busy) {
        button.disabled = true;
        button.dataset.ihOriginalLabel = button.dataset.ihOriginalLabel || button.textContent;
        button.textContent = 'Salvando…';
      } else {
        button.disabled = false;
        if (button.dataset.ihOriginalLabel) button.textContent = button.dataset.ihOriginalLabel;
      }
    });
  }

  function adjustCounter(name, delta) {
    document.querySelectorAll('[data-ih-contador="' + name + '"]').forEach(function (counter) {
      const value = parseInt(counter.textContent, 10);
      if (!Number.isNaN(value)) counter.textContent = String(Math.max(0, value + delta));
    });
  }

  function doseRegistered(form, result) {
    const row = form.closest('[data-ih-dose-card], tr');
    if (row) {
      const status = row.querySelector('[data-ih-dose-status]');
      if (status) {
        const badge = document.createElement('span');
        badge.className = 'ih-status ih-status--' + result.resultado;
        badge.textContent = STATUS_LABELS[result.resultado] || result.resultado;
        status.replaceChildren(badge);
      }
      const info = row.querySelector('[data-ih-dose-info]');
      if (info) {
        info.textContent = [result.executada_em, result.autor].filter(Boolean).join(' · ');
        info.hidden = false;
      }
      if (row.hasAttribute('data-ih-late')) adjustCounter('atrasadas', -1);
      if (row.hasAttribute('data-ih-dose-card')) adjustCounter('pendentes', -1);
      row.classList.remove('ih-dose--late');
      row.classList.add('ih-dose--done');
    }
    const details = form.closest('[data-ih-dose-details]');
    const note = document.createElement('p');
    note.className = 'ih-form-msg ih-form-msg--ok';
    note.setAttribute('role', 'status');
    note.textContent = (result.resultado === 'omitida' ? 'Não administração registrada' : 'Administração registrada')
      + (result.executada_em ? ' em ' + result.executada_em : '') + (result.autor ? ' por ' + result.autor : '') + '.';
    (details || form).replaceWith(note);
  }

  function prnRegistered(form, result) {
    form.reset();
    const key = form.querySelector('[name="idempotency_key"]');
    if (key) key.value = newKey();
    showMessage(form, 'Administração se necessário registrada' + (result.executada_em ? ' em ' + result.executada_em : '')
      + (result.autor ? ' por ' + result.autor : '') + '. Ela aparece no histórico ao atualizar a página.', 'ok');
  }

  async function submitInBackground(form) {
    const controller = new AbortController();
    const timeout = window.setTimeout(function () { controller.abort(); }, 20000);
    setBusy(form, true);
    showMessage(form, 'Enviando…', '');
    let response;
    try {
      const token = form.querySelector('[name="csrf_token"]');
      response = await fetch(form.action, {
        method: 'POST', body: new FormData(form), credentials: 'same-origin', signal: controller.signal,
        headers: Object.assign({Accept: 'application/json'}, token ? {'X-CSRFToken': token.value} : {})
      });
    } catch (_error) {
      setBusy(form, false);
      showMessage(form, 'Sem resposta do servidor. Tente de novo: o sistema não duplica o registro. Se persistir, atualize a página e confira a dose.', 'erro');
      return;
    } finally {
      window.clearTimeout(timeout);
    }
    if (!(response.headers.get('content-type') || '').includes('application/json')) {
      // Sessão expirada ou resposta inesperada: segue o envio tradicional.
      HTMLFormElement.prototype.submit.call(form);
      return;
    }
    const result = await response.json().catch(function () { return {}; });
    if (!response.ok || !result.ok) {
      setBusy(form, false);
      const message = result.erro || result.message || 'Não foi possível salvar. Revise os dados.';
      showMessage(form, message, 'erro');
      const reason = form.querySelector('[data-ih-motivo], [name="motivo"]');
      if (reason && /justificativa|motivo/i.test(message)) {
        reason.required = true;
        reason.focus();
      }
      return;
    }
    if (form.dataset.ihAjax === 'dose') doseRegistered(form, result);
    else prnRegistered(form, result);
  }

  document.querySelectorAll('[data-ih-submit]').forEach(function (form) {
    const result = form.querySelector('[data-ih-resultado]');
    const reason = form.querySelector('[data-ih-motivo]');
    const retrospective = form.querySelector('[data-ih-retrospectivo]');
    const hint = form.querySelector('[data-ih-janela]');
    const mark = form.querySelector('[data-ih-motivo-marca]');
    const tolerance = form.dataset.tolerancia || '60';
    function syncReason() {
      if (!reason) return;
      const window_ = form.dataset.prevista ? doseWindow(form) : 'no_horario';
      const required = form.hasAttribute('data-ih-historico') || window_ !== 'no_horario'
        || Boolean((result && result.value === 'omitida') || (retrospective && retrospective.value));
      reason.required = required;
      if (mark) mark.textContent = required ? ' *' : '';
      if (hint && form.dataset.prevista) {
        hint.textContent = window_ === 'atrasada' ? 'Checagem com mais de ' + tolerance + ' min de atraso: informe a justificativa.'
          : window_ === 'antecipada' ? 'Checagem com mais de ' + tolerance + ' min de antecedência: informe a justificativa.'
          : 'Dentro da janela de ±' + tolerance + ' min do horário previsto, a justificativa é opcional.';
      }
    }
    if (result) result.addEventListener('change', syncReason);
    if (retrospective) retrospective.addEventListener('input', syncReason);
    const details = form.closest('details');
    if (details) details.addEventListener('toggle', syncReason);
    syncReason();
    form.addEventListener('submit', function (event) {
      syncReason();
      if (form.dataset.ihAjax && window.fetch && window.FormData) {
        event.preventDefault();
        if (!form.reportValidity()) return;
        submitInBackground(form);
        return;
      }
      setBusy(form, true);
    });
  });

  document.querySelectorAll('[data-ih-set]').forEach(function (button) {
    button.addEventListener('click', function () {
      const field = button.closest('form').querySelector('[name="' + button.dataset.ihSet + '"]');
      if (!field) return;
      field.value = button.dataset.valor;
      field.dispatchEvent(new Event('input', {bubbles: true}));
    });
  });

  document.querySelectorAll('[data-ih-intervalo]').forEach(function (button) {
    button.addEventListener('click', function () {
      const group = button.closest('[data-ih-modes]');
      const amount = group && group.querySelector('input');
      const unit = group && group.querySelector('select');
      if (!amount || !unit) return;
      amount.value = button.dataset.ihIntervalo;
      unit.value = 'horas';
      amount.dispatchEvent(new Event('input', {bubbles: true}));
    });
  });

  function toInputValue(date) {
    const pad = function (n) { return String(n).padStart(2, '0'); };
    return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + 'T' + pad(date.getHours()) + ':' + pad(date.getMinutes());
  }

  document.querySelectorAll('[data-ih-duracao]').forEach(function (button) {
    button.addEventListener('click', function () {
      const form = button.closest('form');
      const start = form.querySelector('[name="inicio_em"]');
      const end = form.querySelector('[name="fim_em"]');
      const parsed = start && start.value ? new Date(start.value) : null;
      if (!parsed || Number.isNaN(parsed.getTime()) || !end) {
        if (start) start.reportValidity();
        return;
      }
      parsed.setHours(parsed.getHours() + Number(button.dataset.ihDuracao));
      end.value = toInputValue(parsed);
      end.dispatchEvent(new Event('input', {bubbles: true}));
    });
  });

  function reveal(element, scroll) {
    if (!element) return;
    if (element.tagName === 'DETAILS') element.open = true;
    const inner = element.querySelector && element.querySelector('[data-ih-dose-details]');
    if (inner) inner.open = true;
    let parent = element.parentElement && element.parentElement.closest('details');
    while (parent) { parent.open = true; parent = parent.parentElement && parent.parentElement.closest('details'); }
    if (scroll && typeof element.scrollIntoView === 'function') element.scrollIntoView({block: 'center'});
  }

  function openAnchor() {
    const id = window.location.hash.slice(1);
    if (id) reveal(document.getElementById(id), false);
  }

  // Após uma recusa no envio tradicional, a tela volta direto ao formulário.
  const focusTarget = document.querySelector('[data-ih-focus]');
  if (focusTarget && focusTarget.dataset.ihFocus !== 'pagina') {
    const element = document.getElementById(focusTarget.dataset.ihFocus);
    reveal(element, true);
    const message = element && element.querySelector('[data-ih-msg]:not([hidden])');
    if (message) { message.setAttribute('tabindex', '-1'); message.focus({preventScroll: true}); }
  }

  function setupInternacaoTabs() {
    const nav = document.getElementById('internacaoTabs');
    const container = document.getElementById('internacaoTabContent');
    if (!nav || !container) return;

    const STORAGE_KEY = 'abaAtivaInternacao';
    const tabLinks = Array.from(nav.querySelectorAll('[data-bs-target], [href^="#"]'));
    const panes = Array.from(container.querySelectorAll('.tab-pane'));

    function getTargetId(link) {
      if (!link) return '';
      const target = link.getAttribute('data-bs-target') || link.getAttribute('href') || '';
      return target.replace(/^#/, '');
    }

    function activateTab(targetId, updateHash, scrollTarget) {
      if (!targetId) return false;
      const cleanId = targetId.replace(/^#/, '');
      const targetPane = document.getElementById(cleanId);
      if (!targetPane || !panes.includes(targetPane)) return false;

      tabLinks.forEach(function (link) {
        const isCurrent = getTargetId(link) === cleanId;
        link.classList.toggle('active', isCurrent);
        link.setAttribute('aria-selected', isCurrent ? 'true' : 'false');
        link.setAttribute('tabindex', isCurrent ? '0' : '-1');
      });

      panes.forEach(function (pane) {
        const isCurrent = pane === targetPane;
        pane.classList.toggle('active', isCurrent);
        pane.classList.toggle('show', isCurrent);
      });

      try {
        window.localStorage.setItem(STORAGE_KEY, cleanId);
      } catch (_e) {}

      if (updateHash) {
        if (window.history && window.history.replaceState) {
          window.history.replaceState(null, '', '#' + cleanId);
        } else {
          window.location.hash = '#' + cleanId;
        }
      }

      if (scrollTarget) {
        reveal(scrollTarget, true);
      }

      return true;
    }

    nav.addEventListener('click', function (event) {
      const link = event.target.closest('[data-bs-target], [href^="#"]');
      if (!link || !nav.contains(link)) return;
      const targetId = getTargetId(link);
      if (targetId) {
        event.preventDefault();
        activateTab(targetId, true);
      }
    });

    function resolveLocationHash() {
      const hash = window.location.hash ? window.location.hash.slice(1) : '';
      if (!hash) return false;

      if (activateTab(hash, false)) {
        return true;
      }

      const element = document.getElementById(hash);
      if (element) {
        const parentPane = element.closest('.tab-pane');
        if (parentPane && panes.includes(parentPane)) {
          activateTab(parentPane.id, false, element);
          return true;
        }
      }

      return false;
    }

    let initialized = false;
    if (focusTarget && focusTarget.dataset.ihFocus && focusTarget.dataset.ihFocus !== 'pagina') {
      const el = document.getElementById(focusTarget.dataset.ihFocus);
      if (el) {
        const parentPane = el.closest('.tab-pane');
        if (parentPane && panes.includes(parentPane)) {
          activateTab(parentPane.id, false, el);
          initialized = true;
        }
      }
    }

    if (!initialized) {
      initialized = resolveLocationHash();
    }
    if (!initialized) {
      let saved = null;
      try {
        saved = window.localStorage.getItem(STORAGE_KEY);
      } catch (_e) {}
      if (saved && activateTab(saved, false)) {
        initialized = true;
      }
    }
    if (!initialized && panes.length > 0) {
      activateTab(panes[0].id, false);
    }

    window.addEventListener('hashchange', function () {
      resolveLocationHash();
    });

    document.addEventListener('click', function (event) {
      const anchor = event.target.closest('a[href^="#"]');
      if (!anchor || nav.contains(anchor)) return;
      const href = anchor.getAttribute('href');
      if (!href || href === '#') return;
      const hash = href.slice(1);
      if (!hash) return;
      const element = document.getElementById(hash);
      if (!element) return;

      const parentPane = element.closest('.tab-pane');
      if (parentPane && panes.includes(parentPane)) {
        event.preventDefault();
        activateTab(parentPane.id, true, element);
      }
    });
  }

  setupInternacaoTabs();

  window.addEventListener('pageshow', function () {
    document.querySelectorAll('button[data-ih-original-label]').forEach(function (button) {
      button.disabled = false;
      button.textContent = button.dataset.ihOriginalLabel;
    });
  });
})();
