/**
 * Seletor de animal com busca por animal E tutor, com miniaturas.
 *
 * Numa base com dezenas de "Nina", um <select> com "Nina — Tutor" obriga a
 * varrer a lista inteira e ainda deixa ambiguidade. Aqui o usuário digita
 * qualquer dado do animal (nome, espécie, raça, microchip) ou do tutor (nome,
 * telefone, e-mail) e vê as fotos dos dois para confirmar.
 *
 * É enhancement progressivo: o <select> original continua sendo a fonte da
 * verdade e o campo enviado no POST. Sem JS, o formulário segue funcionando.
 */

const norm = (valor) => String(valor ?? '')
  .toLowerCase()
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '');

function iniciais(nome) {
  const partes = String(nome || '').trim().split(/\s+/).filter(Boolean);
  if (!partes.length) return '?';
  return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase();
}

function criarAvatar(url, nome, extraClasse) {
  const wrap = document.createElement('span');
  wrap.className = `animal-picker__avatar ${extraClasse || ''}`.trim();
  if (url) {
    const img = document.createElement('img');
    img.src = url;
    img.alt = '';
    img.loading = 'lazy';
    // Foto quebrada não pode deixar um buraco: cai para as iniciais.
    img.addEventListener('error', () => {
      wrap.textContent = iniciais(nome);
      wrap.classList.add('animal-picker__avatar--fallback');
    });
    wrap.appendChild(img);
  } else {
    wrap.textContent = iniciais(nome);
    wrap.classList.add('animal-picker__avatar--fallback');
  }
  return wrap;
}

function lerRegistros(form) {
  const script = form.querySelector('[data-appointment-animal-data]');
  if (!script) return [];
  try {
    return JSON.parse(script.textContent || '[]');
  } catch (err) {
    return [];
  }
}

function montarPicker(form) {
  const select = form.querySelector('[data-appointment-animal-select]');
  if (!select || select.dataset.pickerPronto === 'true') return;
  const registros = lerRegistros(form);
  if (!registros.length) return;
  select.dataset.pickerPronto = 'true';

  const porId = new Map(registros.map((r) => [String(r.id), r]));
  registros.forEach((r) => {
    r._busca = norm([
      r.name, r.tutor_name, r.species, r.breed,
      r.microchip, r.tutor_phone, r.tutor_email,
    ].filter(Boolean).join(' '));
  });

  const container = document.createElement('div');
  container.className = 'animal-picker';

  const campo = document.createElement('input');
  campo.type = 'text';
  campo.className = 'form-control animal-picker__input';
  campo.placeholder = 'Busque por animal ou tutor (nome, telefone, microchip...)';
  campo.autocomplete = 'off';
  campo.setAttribute('role', 'combobox');
  campo.setAttribute('aria-expanded', 'false');
  campo.setAttribute('aria-autocomplete', 'list');

  const lista = document.createElement('ul');
  lista.className = 'animal-picker__list';
  lista.setAttribute('role', 'listbox');
  lista.hidden = true;

  const selecionado = document.createElement('div');
  selecionado.className = 'animal-picker__selected';
  selecionado.hidden = true;

  container.append(campo, lista, selecionado);
  select.classList.add('visually-hidden');
  select.setAttribute('tabindex', '-1');
  select.setAttribute('aria-hidden', 'true');
  select.parentNode.insertBefore(container, select);

  let visiveis = [];
  let ativo = -1;

  function tutorPermitido() {
    const tutorSelect = form.querySelector('[data-appointment-tutor-select]');
    const valor = tutorSelect ? String(tutorSelect.value || '') : '';
    return !valor || valor === '0' ? null : valor;
  }

  function desenharSelecionado() {
    const registro = porId.get(String(select.value));
    if (!registro) {
      selecionado.hidden = true;
      selecionado.textContent = '';
      return;
    }
    selecionado.hidden = false;
    selecionado.textContent = '';
    const linha = document.createElement('div');
    linha.className = 'animal-picker__row';
    linha.append(
      criarAvatar(registro.photo, registro.name),
      criarAvatar(registro.tutor_photo, registro.tutor_name, 'animal-picker__avatar--tutor'),
    );
    const texto = document.createElement('div');
    texto.className = 'animal-picker__text';
    const titulo = document.createElement('strong');
    titulo.textContent = registro.name;
    const sub = document.createElement('small');
    sub.className = 'text-muted d-block';
    sub.textContent = [registro.tutor_name, registro.species, registro.breed]
      .filter(Boolean).join(' · ');
    texto.append(titulo, sub);
    linha.appendChild(texto);
    selecionado.appendChild(linha);
  }

  function desenharLista(termo) {
    const alvo = norm(termo);
    const tutorId = tutorPermitido();
    visiveis = registros.filter((r) => {
      if (tutorId && String(r.tutor_id ?? '') !== tutorId) return false;
      return !alvo || r._busca.includes(alvo);
    }).slice(0, 50);

    lista.textContent = '';
    ativo = -1;
    if (!visiveis.length) {
      const vazio = document.createElement('li');
      vazio.className = 'animal-picker__empty';
      vazio.textContent = 'Nenhum animal encontrado.';
      lista.appendChild(vazio);
      lista.hidden = false;
      campo.setAttribute('aria-expanded', 'true');
      return;
    }

    visiveis.forEach((registro, indice) => {
      const item = document.createElement('li');
      item.className = 'animal-picker__option';
      item.setAttribute('role', 'option');
      item.dataset.valor = String(registro.id);
      item.id = `${select.id}-opt-${registro.id}`;

      item.append(
        criarAvatar(registro.photo, registro.name),
        criarAvatar(registro.tutor_photo, registro.tutor_name, 'animal-picker__avatar--tutor'),
      );
      const texto = document.createElement('div');
      texto.className = 'animal-picker__text';
      const titulo = document.createElement('strong');
      titulo.textContent = registro.name;
      const sub = document.createElement('small');
      sub.className = 'text-muted d-block';
      const detalhes = [registro.species, registro.breed].filter(Boolean).join(' · ');
      sub.textContent = registro.tutor_name + (detalhes ? ` · ${detalhes}` : '');
      texto.append(titulo, sub);
      item.appendChild(texto);

      item.addEventListener('mousedown', (evento) => {
        evento.preventDefault();
        escolher(indice);
      });
      lista.appendChild(item);
    });
    lista.hidden = false;
    campo.setAttribute('aria-expanded', 'true');
  }

  function destacar(indice) {
    Array.from(lista.children).forEach((el, i) => {
      el.classList.toggle('is-active', i === indice);
    });
    const alvo = lista.children[indice];
    if (alvo && alvo.scrollIntoView) {
      alvo.scrollIntoView({ block: 'nearest' });
      campo.setAttribute('aria-activedescendant', alvo.id || '');
    }
  }

  function escolher(indice) {
    const registro = visiveis[indice];
    if (!registro) return;
    select.value = String(registro.id);
    select.dispatchEvent(new Event('change', { bubbles: true }));
    campo.value = '';
    fechar();
    desenharSelecionado();
  }

  function fechar() {
    lista.hidden = true;
    campo.setAttribute('aria-expanded', 'false');
    campo.removeAttribute('aria-activedescendant');
    ativo = -1;
  }

  campo.addEventListener('input', () => desenharLista(campo.value));
  campo.addEventListener('focus', () => desenharLista(campo.value));
  campo.addEventListener('blur', () => window.setTimeout(fechar, 120));
  campo.addEventListener('keydown', (evento) => {
    if (evento.key === 'ArrowDown' || evento.key === 'ArrowUp') {
      evento.preventDefault();
      if (lista.hidden) desenharLista(campo.value);
      if (!visiveis.length) return;
      const passo = evento.key === 'ArrowDown' ? 1 : -1;
      ativo = (ativo + passo + visiveis.length) % visiveis.length;
      destacar(ativo);
    } else if (evento.key === 'Enter') {
      if (!lista.hidden && ativo >= 0) {
        evento.preventDefault();
        escolher(ativo);
      }
    } else if (evento.key === 'Escape') {
      fechar();
    }
  });

  // O filtro por tutor continua vivendo no select original.
  const tutorSelect = form.querySelector('[data-appointment-tutor-select]');
  if (tutorSelect) {
    tutorSelect.addEventListener('change', () => {
      desenharSelecionado();
      if (!lista.hidden) desenharLista(campo.value);
    });
  }
  select.addEventListener('change', desenharSelecionado);

  desenharSelecionado();
}

function iniciar() {
  document.querySelectorAll('[data-appointment-form]').forEach(montarPicker);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', iniciar);
} else {
  iniciar();
}

export { norm, iniciais };
