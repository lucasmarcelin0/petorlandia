(function(){
  const KEY = 'offline-queue';

  function loadQueue(){
    try { return JSON.parse(localStorage.getItem(KEY)) || []; }
    catch(e){ return []; }
  }
  function saveQueue(q){
    localStorage.setItem(KEY, JSON.stringify(q));
  }

  async function sendQueued(){
    if(!navigator.onLine) return;
    const q = loadQueue();
    while(q.length){
      const item = q[0];
      let body;
      if(item.body && item.body.form){
        body = new FormData();
        item.body.form.forEach(([k,v])=>body.append(k,v));
      } else if(item.body && item.body.json){
        body = JSON.stringify(item.body.json);
      } else if(item.body && item.body.text){
        body = item.body.text;
      }
      try {
        const resp = await fetch(item.url, {method:item.method, headers:item.headers, body});
        if(!resp.ok) throw new Error('fail');
        q.shift();
      } catch(err){
        break;
      }
    }
    saveQueue(q);
  }

  window.fetchOrQueue = async function(url, opts={}){
    const method = opts.method || 'POST';
    const headers = opts.headers || {};
    let bodyData = null;
    if(opts.body instanceof FormData){
      bodyData = {form:[...opts.body.entries()]};
    } else if(typeof opts.body === 'string'){
      bodyData = {text: opts.body};
    } else if(opts.body){
      bodyData = {json: opts.body};
    }
    if(navigator.onLine){
      try {
        const resp = await fetch(url, opts);
        if(resp.ok) return resp;
      } catch(e){ /* fallthrough */ }
    }
    const q = loadQueue();
    q.push({url, method, headers, body:bodyData});
    saveQueue(q);
    return null;
  };

  window.addEventListener('online', sendQueued);
  document.addEventListener('DOMContentLoaded', sendQueued);

  document.addEventListener('submit', async ev => {
    const form = ev.target;
    if (!form.matches('form[data-sync]')) return;
    ev.preventDefault();
    const data = new FormData(form);
    const resp = await window.fetchOrQueue(form.action, {
      method: form.method || 'POST',
      headers: {'Accept': 'application/json'},
      body: data
    });
    if (resp) {
      try { await resp.json(); } catch(e) {}
      if (!form.hasAttribute('data-no-reload')) {
        location.reload();
      }
    } else {
      alert('Ação salva offline e será sincronizada quando possível.');
    }
  });
})();
