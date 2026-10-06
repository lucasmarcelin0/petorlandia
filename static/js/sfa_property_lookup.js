(function (root) {
  'use strict';
  const text = value => value == null ? '' : String(value);
  const display = value => text(value).trim() || 'Não informado na coleta';
  const normalize = value => text(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const isDocument = label => /cpf|cnpj|documento|\brg\b|identidade|registro geral/.test(normalize(label));
  const maskDocument = value => text(value).replace(/[A-Za-z0-9]/g, '•');
  function queryForSearch(value) {
    const model = root.SfaAtlasSearchModel;
    const query = model && typeof model.searchText === 'function' ? model.searchText(text(value)) : text(value);
    return query.replace(/,/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function init(dataset, options) {
    const doc = root.document, panel = doc && doc.getElementById('cadastre-panel');
    if (!panel || panel.dataset.initialized) return null;
    const $ = id => doc.getElementById(id);
    const form = $('cadastre-search-form'), input = $('cadastre-query');
    const submit = $('cadastre-search-submit'), clear = $('cadastre-clear');
    const results = $('cadastre-results'), detail = $('cadastre-detail');
    const status = $('cadastre-status'), metadata = $('cadastre-metadata');
    const node = (tag, value, className) => {
      const element = doc.createElement(tag);
      if (value !== undefined) element.textContent = text(value);
      if (className) element.className = className;
      return element;
    };
    let searchURL, detailBase;
    try {
      searchURL = new URL(dataset.cadastre_search_url, root.location.href);
      detailBase = new URL(dataset.cadastre_detail_base_url, root.location.href);
      if (!dataset.cadastre_search_url || !dataset.cadastre_detail_base_url ||
          searchURL.origin !== root.location.origin || detailBase.origin !== root.location.origin) {
        throw new Error('Invalid cadastral endpoint');
      }
    } catch (_) {
      status.textContent = 'A consulta cadastral ainda não está disponível nesta página.';
      submit.disabled = true; clear.disabled = true; input.disabled = true;
      return null;
    }
    panel.dataset.initialized = 'true';
    let searchSequence = 0, detailSequence = 0;
    let searchAbort = null, detailAbort = null, revoked = false, selectedButton = null, locatingMap = false;
    function setStatus(message, error) {
      status.textContent = message;
      status.classList.toggle('is-error', Boolean(error));
    }
    function emptyDetail(message) {
      detail.replaceChildren(node('h4', 'Selecione um imóvel'), node('p', message || 'Abra uma ficha para conferir o endereço do imóvel e os dados do proprietário.'));
    }
    function clearPersonalData() {
      detailSequence += 1;
      if (detailAbort) detailAbort.abort();
      detailAbort = null; selectedButton = null;
      results.replaceChildren(); emptyDetail(); detail.removeAttribute('aria-busy');
    }
    function deny(code) {
      revoked = true;
      clearPersonalData();
      metadata.textContent = 'Consulta exclusiva para administrador autenticado.';
      setStatus(code === 401 ? 'Sua sessão expirou. Entre novamente com a conta de administrador para consultar o cadastro.' : 'Esta conta não tem acesso ao cadastro. A consulta é exclusiva para administrador.', true);
      input.disabled = true; submit.disabled = true; clear.disabled = true;
    }
    async function request(url, signal) {
      const response = await root.fetch(url.toString(), {
        credentials:'same-origin', cache:'no-store', signal,
        headers:{Accept:'application/json'}
      });
      if (response.status === 401 || response.status === 403) {
        const error = new Error('Access denied'); error.status = response.status; throw error;
      }
      if (!response.ok) throw new Error('Cadastral request failed');
      return response.json();
    }
    function renderMetadata(data) {
      const meta = data.metadata || {};
      const count = Number(meta.records_count) || 0, owners = Number(meta.owners_count) || 0;
      let value = `Amostra de ${count} imóveis e ${owners} proprietários. Sem sincronização automática.`;
      if (meta.collected_at) {
        const date = new Date(meta.collected_at);
        value += Number.isNaN(date.getTime()) ? '' : ` Coleta em ${date.toLocaleDateString('pt-BR', {timeZone:'America/Sao_Paulo'})}.`;
      }
      metadata.textContent = value;
    }
    function field(list, label, value) {
      const group = node('div'); group.append(node('dt', label));
      group.append(node('dd', display(value))); list.append(group);
    }
    function ownerField(list, item) {
      const group = node('div'), label = text(item.label), value = text(item.value);
      group.append(node('dt', label || 'Campo cadastral'));
      const definition = node('dd');
      if (isDocument(label) && value.trim()) {
        const masked = node('span', maskDocument(value), 'cadastre-document-value');
        const reveal = node('button', 'Revelar documento', 'cadastre-reveal');
        reveal.type = 'button'; reveal.setAttribute('aria-pressed', 'false');
        let visible = false;
        reveal.addEventListener('click', () => {
          visible = !visible;
          masked.textContent = visible ? value : maskDocument(value);
          reveal.textContent = visible ? 'Ocultar documento' : 'Revelar documento';
          reveal.setAttribute('aria-pressed', String(visible));
        });
        definition.append(masked, reveal);
      } else definition.textContent = display(value);
      group.append(definition); list.append(group);
    }
    function renderDetail(data) {
      const property = data.property || {}, owner = data.owner || {};
      const title = node('h4', display(property.address)), list = node('dl');
      field(list, 'Inscrição imobiliária', property.registration);
      field(list, 'Código do imóvel', property.property_code);
      field(list, 'Matrícula', property.registry_number);
      field(list, 'Código do proprietário', property.owner_code);
      detail.replaceChildren(title, list);
      if (options && typeof options.locateAddress === 'function') {
        const locate = node('button', 'Consultar endereço no mapa', 'field-tool-button cadastre-locate');
        const note = node('p', '', 'cadastre-locate-status');
        locate.type = 'button';
        locate.addEventListener('click', async () => {
          locate.disabled = true; locatingMap = true;
          try {
            const outcome = await options.locateAddress(property);
            note.textContent = typeof outcome === 'string' ? outcome : text(outcome && outcome.message) || 'Consulte as referências do endereço no mapa. A posição exata do imóvel não está cadastrada.';
          } catch (_) {
            note.textContent = 'Não foi possível consultar as referências deste endereço no mapa.';
          } finally { locate.disabled = false; locatingMap = false; }
        });
        detail.append(locate, note);
      }
      detail.append(node('h5', 'Dados do proprietário'), node('p', display(owner.owner_name || property.owner_name)));
      if (owner.status !== 'consultado') {
        detail.append(node('p', 'A ficha deste proprietário não foi consultada na amostra.'));
      } else {
        const fields = node('dl', undefined, 'cadastre-owner-fields');
        (Array.isArray(owner.fields) ? owner.fields : []).forEach(item => ownerField(fields, item));
        if (fields.children.length) detail.append(fields);
        else detail.append(node('p', 'Nenhum campo adicional informado na coleta.'));
      }
      detail.append(node('p', 'Endereços e contatos acima pertencem ao cadastro do proprietário e podem diferir do endereço do imóvel.'));
      if (owner.collected_at) {
        const collected = new Date(owner.collected_at);
        if (!Number.isNaN(collected.getTime())) detail.append(node('p', `Ficha consultada em ${collected.toLocaleString('pt-BR', {timeZone:'America/Sao_Paulo'})}. A data de atualização do cadastro não foi informada.`));
      }
    }
    async function select(property, button) {
      if (revoked) return;
      const sequence = ++detailSequence;
      if (detailAbort) detailAbort.abort();
      detailAbort = new AbortController();
      if (selectedButton) selectedButton.setAttribute('aria-pressed', 'false');
      selectedButton = button; button.setAttribute('aria-pressed', 'true');
      detail.replaceChildren(node('p', 'Carregando ficha cadastral…'));
      detail.setAttribute('aria-busy', 'true');
      const url = new URL(detailBase.href);
      const code = encodeURIComponent(text(property.property_code));
      url.pathname = /\/CODE(?:\/|$)/.test(url.pathname)
        ? url.pathname.replace(/\/CODE(?=\/|$)/, '/' + code)
        : url.pathname.replace(/\/$/, '') + '/' + code;
      try {
        const data = await request(url, detailAbort.signal);
        if (sequence !== detailSequence || revoked) return;
        renderDetail(data);
      } catch (error) {
        if (sequence !== detailSequence || error.name === 'AbortError') return;
        if (error.status) deny(error.status);
        else detail.replaceChildren(node('p', 'Não foi possível carregar a ficha. Selecione o imóvel novamente para tentar.'));
      } finally {
        if (sequence === detailSequence || revoked) detail.removeAttribute('aria-busy');
      }
    }
    function renderResults(items) {
      results.replaceChildren();
      items.forEach(property => {
        const button = node('button', undefined, 'cadastre-result');
        button.type = 'button'; button.setAttribute('aria-pressed', 'false');
        button.append(node('span', display(property.address), 'cadastre-result-address'));
        button.append(node('span', `Proprietário: ${display(property.owner_name)}`, 'cadastre-result-owner'));
        button.append(node('span', `Imóvel ${display(property.property_code)} · Inscrição ${display(property.registration)} · Ver ficha`, 'cadastre-result-code'));
        button.addEventListener('click', () => select(property, button)); results.append(button);
      });
      if (!items.length) results.append(node('p', 'Nenhum imóvel encontrado nesta amostra. Isso não significa ausência no cadastro municipal.', 'cadastre-empty'));
    }
    async function search(query) {
      if (revoked) return;
      if (typeof query === 'string') input.value = query.slice(0, 200);
      const sequence = ++searchSequence;
      if (searchAbort) searchAbort.abort();
      searchAbort = new AbortController(); clearPersonalData();
      const term = input.value.trim();
      if (term.length === 1) {
        setStatus('Digite ao menos dois caracteres para pesquisar endereço, proprietário ou inscrição.');
        results.removeAttribute('aria-busy'); submit.disabled = false; clear.disabled = false;
        return;
      }
      submit.disabled = true; clear.disabled = true; results.setAttribute('aria-busy', 'true');
      setStatus('Pesquisando na amostra cadastral…');
      const url = new URL(searchURL.href);
      url.searchParams.set('q', queryForSearch(term)); url.searchParams.set('limit', '20');
      try {
        const data = await request(url, searchAbort.signal);
        if (sequence !== searchSequence || revoked) return;
        renderMetadata(data);
        if (!data.available) {
          setStatus('A amostra cadastral ainda não está disponível no servidor.', true); return;
        }
        if (!term) {
          setStatus('Digite um endereço, nome do proprietário ou inscrição para pesquisar na amostra.');
          return;
        }
        const items = Array.isArray(data.results) ? data.results : [];
        renderResults(items);
        setStatus(items.length >= 20
          ? 'Exibindo os primeiros 20 imóveis encontrados. Refine o endereço, proprietário ou inscrição para consultar os demais.'
          : `${items.length} ${items.length === 1 ? 'imóvel encontrado' : 'imóveis encontrados'} na amostra. Selecione uma ficha para consultar o proprietário.`);
      } catch (error) {
        if (sequence !== searchSequence || error.name === 'AbortError') return;
        if (error.status) deny(error.status);
        else setStatus('Não foi possível pesquisar agora. Tente novamente.', true);
      } finally {
        if (sequence === searchSequence) {
          results.removeAttribute('aria-busy');
          if (!revoked) { submit.disabled = false; clear.disabled = false; }
        }
      }
    }
    form.addEventListener('submit', event => { event.preventDefault(); search(); });
    clear.addEventListener('click', () => { search(''); input.focus(); });
    // Keep the public atlas search handlers intact. Only the private endpoint
    // receives this administrator query; owner names never go to a geocoder.
    const territoryInput = $('field-search'), territoryForm = $('field-filters');
    let territoryTimer;
    if (territoryInput) territoryInput.addEventListener('input', () => {
      if (locatingMap) return;
      root.clearTimeout(territoryTimer);
      const query = territoryInput.value;
      territoryTimer = root.setTimeout(() => search(query), 350);
    });
    if (territoryForm) territoryForm.addEventListener('submit', () => {
      if (locatingMap || !territoryInput) return;
      root.clearTimeout(territoryTimer); search(territoryInput.value);
    });
    if (doc.addEventListener) doc.addEventListener('sfa:atlas-address-selected', event => {
      const address = event.detail && event.detail.address;
      if (typeof address !== 'string' || !address.trim() || locatingMap) return;
      root.clearTimeout(territoryTimer); search(address);
    });
    search('');
    return {search, setQuery(query, settings) {
      input.value = text(query).slice(0, 200);
      if (settings && settings.search) return search();
    }};
  }
  const api = {init};
  if (typeof module === 'object' && module.exports) module.exports = {init, isDocument, maskDocument, queryForSearch};
  root.SfaPropertyLookup = api;
})(typeof window !== 'undefined' ? window : globalThis);
