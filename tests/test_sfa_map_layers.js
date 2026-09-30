const assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs');
const layers=[], removed=[], events=[], statuses=[];
const map = {removeLayer:l=>removed.push(l),fire:(name,data)=>events.push(data.mode)};
const L = {tileLayer:(url,options)=>{
  const layer = {url,options,on:(event,callback)=>{layer.error=callback;return layer;},addTo:()=>layer};
  layers.push(layer); return layer;
},control:{scale:()=>({addTo:()=>{}})}};
const window = {};
vm.runInNewContext(fs.readFileSync('static/js/sfa_map_layers.js','utf8'),{window,L});
const control = window.SfaMapLayers.attach(map,{status:t=>statuses.push(t)});
assert.equal(control.getMode(),'satellite');
layers[0].error();layers[0].error();assert.equal(control.getMode(),'satellite');
layers[0].error();assert.equal(control.getMode(),'streets');
assert.equal(removed[0],layers[0]);assert.ok(layers[1].url.includes('World_Street_Map'));
layers[0].error();assert.equal(control.getMode(),'streets'); // Late failed tiles cannot replace the new background.
layers[1].error();layers[1].error();layers[1].error();assert.equal(control.getMode(),'none');
assert.equal(removed[1],layers[1]);assert.ok(statuses.at(-1).includes('Quadras e números'));
control.setMode('satellite');assert.equal(control.getMode(),'satellite');
assert.ok(layers.every(l=>l.options.attribution && l.options.errorTileUrl.startsWith('data:image/')));
assert.deepEqual(events,['satellite','streets','none','satellite']);
console.log('Map backgrounds: automatic fallback, removal, retry and late errors passed.');
