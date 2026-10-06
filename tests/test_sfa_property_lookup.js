const assert = require('node:assert/strict');
const {init, isDocument, maskDocument, queryForSearch} = require('../static/js/sfa_property_lookup.js');

class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {};
    this.events = {}; this.value = ''; this.disabled = false; this._text = '';
    this.classList = {toggle() {}};
  }
  set innerHTML(_) { throw new Error('Personal data must not be inserted as HTML'); }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this._text = ''; this.children = items; }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, action) { this.events[name] = action; }
  dispatchEvent(event) {
    if (this['on' + event.type]) this['on' + event.type](event);
    if (this.events[event.type]) this.events[event.type](event);
  }
  focus() {}
  async click() { if (this.events.click) return this.events.click(); }
}
const ids = ['cadastre-panel', 'cadastre-search-form', 'cadastre-query',
  'cadastre-search-submit', 'cadastre-clear', 'cadastre-results', 'cadastre-detail',
  'cadastre-status', 'cadastre-metadata'];
const dataset = {cadastre_search_url:'/sfa/entomologia/cadastro/imoveis',
  cadastre_detail_base_url:'/sfa/entomologia/cadastro/imoveis/CODE'};
const metadata = {records_count:20, owners_count:18, collected_at:'2026-10-05T08:00:00-03:00'};
const property = {property_code:'7', registration:'001.002', address:'<img src=x onerror=alert(1)>',
  owner_code:'8', owner_name:'Pessoa de teste', registry_number:''};
const owner = {owner_code:'8', owner_name:'Pessoa de teste', status:'consultado',
  fields:[{label:'CPF / CNPJ', value:'123.456.789-00'},
    {label:'Endereço do proprietário', value:'Rua diferente, 2'},
    {label:'Telefone', value:''}]};
const success = body => ({ok:true, status:200, json:async () => body});
const denied = status => ({ok:false, status, json:async () => ({})});
const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const flatten = element => [element, ...element.children.flatMap(flatten)];
function setup(handler, omitPanel = false, territory = false) {
  const elements = Object.fromEntries(ids.map(id => [id, new Element('div')]));
  delete global.SfaAtlasSearchModel;
  if (territory) {
    elements['field-search'] = new Element('input');
    elements['field-filters'] = new Element('form');
  }
  const documentEvents = {};
  global.document = {getElementById:id => omitPanel && id === 'cadastre-panel' ? null : elements[id],
    createElement:tag => new Element(tag),
    addEventListener:(name, action) => { documentEvents[name] = action; },
    dispatchEvent:event => documentEvents[event.type] && documentEvents[event.type](event)};
  global.location = {href:'https://test.local/sfa/entomologia', origin:'https://test.local'};
  const calls = [];
  global.fetch = async (url, options) => { calls.push({url, options}); return handler(url, options); };
  return {elements, calls};
}

(async () => {
  assert.ok(isDocument('CPF / CNPJ'));
  assert.ok(isDocument('RG'));
  assert.ok(!isDocument('Endereço do proprietário'));
  assert.equal(maskDocument('123.456.789-00'), '•••.•••.•••-••');
  assert.equal(queryForSearch('Rua 28,2391'), 'Rua 28 2391');
  assert.equal(queryForSearch('010.077.001.00000.0'), '010.077.001.00000.0');
  global.SfaAtlasSearchModel = {searchText:value => value.replace(/^Av\./i, 'Avenida').replace('vinte e oito', '28')};
  assert.equal(queryForSearch('Av. 23,1811'), 'Avenida 23 1811');
  assert.equal(queryForSearch('Rua vinte e oito,2391'), 'Rua 28 2391');

  let state = setup(() => { throw new Error('Public page cannot fetch private data'); }, true);
  assert.equal(init(dataset), null);
  assert.equal(state.calls.length, 0);
  state = setup(() => { throw new Error('External endpoint cannot receive private query'); });
  assert.equal(init({...dataset, cadastre_search_url:'https://external.test/api'}), null);
  assert.equal(state.calls.length, 0);

  let locateCalls = 0;
  state = setup(url => {
    if (url.endsWith('/7')) return success({property, owner});
    const query = new URL(url).searchParams.get('q');
    return success({available:true, metadata, results:query ? [property] : []});
  });
  const api = init(dataset, {locateAddress:async item => {
    locateCalls++; assert.equal(item.property_code, '7');
    return {status:'unmapped', message:'Referência de rua, sem posição exata.'};
  }});
  await settle();
  assert.equal(state.calls.length, 1);
  assert.equal(state.elements['cadastre-results'].children.length, 0);
  assert.ok(state.elements['cadastre-metadata'].textContent.includes('20 imóveis'));
  assert.equal(locateCalls, 0);
  await api.search('r');
  assert.equal(state.calls.length, 1);
  await api.search('Rua & número');
  assert.equal(new URL(state.calls[1].url).searchParams.get('q'), 'Rua & número');
  assert.equal(state.calls[1].options.cache, 'no-store');
  assert.equal(state.calls[1].options.credentials, 'same-origin');
  assert.ok(!state.elements['cadastre-detail'].textContent.includes('123.456'));
  const result = state.elements['cadastre-results'].children[0];
  assert.ok(result.textContent.includes('<img src=x onerror=alert(1)>'));
  await result.click();
  assert.equal(new URL(state.calls.at(-1).url).pathname, '/sfa/entomologia/cadastro/imoveis/7');
  assert.ok(state.elements['cadastre-detail'].textContent.includes('Rua diferente, 2'));
  assert.ok(!state.elements['cadastre-detail'].textContent.includes('123.456'));
  assert.equal(locateCalls, 0);
  const reveal = flatten(state.elements['cadastre-detail']).find(item => item.className === 'cadastre-reveal');
  await reveal.click();
  assert.ok(state.elements['cadastre-detail'].textContent.includes('123.456.789-00'));
  await reveal.click();
  assert.ok(!state.elements['cadastre-detail'].textContent.includes('123.456'));
  const locate = flatten(state.elements['cadastre-detail']).find(item => item.className === 'field-tool-button cadastre-locate');
  await locate.click();
  assert.equal(locateCalls, 1);
  assert.ok(state.elements['cadastre-detail'].textContent.includes('Referência de rua'));

  // A later selection/search must prevent an earlier response replacing its data.
  let finishDetail;
  global.fetch = async url => url.endsWith('/7')
    ? new Promise(resolve => { finishDetail = resolve; })
    : success({available:true, metadata, results:[]});
  const pendingDetail = result.click();
  await api.search('outro endereço');
  finishDetail(success({property, owner}));
  await pendingDetail;
  assert.ok(!state.elements['cadastre-detail'].textContent.includes('Pessoa de teste'));

  // Sidecar hooks preserve the atlas handler and only refine the cadastral list.
  state = setup(() => success({available:true, metadata, results:[]}), false, true);
  let atlasInputCalls = 0;
  const publicInputHandler = () => { atlasInputCalls++; };
  state.elements['field-search'].oninput = publicInputHandler;
  init(dataset); await settle();
  state.elements['field-search'].value = 'Rua 28';
  state.elements['field-search'].dispatchEvent({type:'input'});
  await new Promise(resolve => setTimeout(resolve, 400));
  assert.equal(state.elements['field-search'].oninput, publicInputHandler);
  assert.equal(atlasInputCalls, 1);
  assert.equal(new URL(state.calls.at(-1).url).searchParams.get('q'), 'Rua 28');
  document.dispatchEvent({type:'sfa:atlas-address-selected', detail:{address:'Rua 28, 200'}});
  await settle();
  assert.equal(new URL(state.calls.at(-1).url).searchParams.get('q'), 'Rua 28 200');
  assert.ok(!state.calls.some(call => call.url.endsWith('/7')));

  // Revoked sessions clear already rendered personal data and cannot retry in place.
  for (const status of [401, 403]) {
    state = setup(url => url.endsWith('/7') ? success({property, owner}) :
      success({available:true, metadata, results:new URL(url).searchParams.get('q') ? [property] : []}));
    const handle = init(dataset); await settle(); await handle.search('Rua');
    await state.elements['cadastre-results'].children[0].click();
    assert.ok(state.elements['cadastre-detail'].textContent.includes('Pessoa de teste'));
    global.fetch = async () => denied(status);
    await handle.search('outro');
    assert.equal(state.elements['cadastre-results'].children.length, 0);
    assert.ok(!state.elements['cadastre-detail'].textContent.includes('Pessoa de teste'));
    assert.equal(state.elements['cadastre-query'].disabled, true);
    assert.equal(state.elements['cadastre-search-submit'].disabled, true);
  }
  console.log('Admin property lookup: private fetch, document reveal, text-only data, manual map lookup, stale responses and revoked access passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
