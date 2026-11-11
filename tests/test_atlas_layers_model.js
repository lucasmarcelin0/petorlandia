const assert=require('node:assert/strict'), M=require('../static/js/sfa_atlas_layers_model.js');
const rows=[{notification_date:'2026-09-30',symptoms_date:'2026-08-28',result_group:'positive',classification:'Importado'},
  {notification_date:'',result_group:'unknown',classification:''},{notification_date:'2026-09-10',result_group:'negative',classification:'Autóctone'}];
assert.equal(M.sheetFilter(rows,{start:'2026-09-01'}).length,2);
assert.equal(M.sheetFilter(rows,{month:'08',dateField:'symptoms_date'}).length,1);
assert.equal(M.sheetFilter(rows,{month:'unknown'}).length,1);
assert.equal(M.sheetFilter(rows,{result:'positive',classification:'Importado'}).length,1);
const features=Array.from({length:8},(_,i)=>({geometry:{type:'Point',coordinates:[i,i]},properties:{month:i<4?'01':''}}));
assert.equal(M.earthFilter(features,'01').length,4);
assert.equal(M.earthFilter(features,'unknown').length,4);
const groups=M.clusters(features,coords=>({x:coords[0]*20,y:coords[1]*20}));
assert.equal(groups.reduce((n,g)=>n+g.items.length,0),8);
assert(groups.every(g=>g.items.some(f=>f.geometry.coordinates===g.coordinates)));
console.log('Atlas layers: month, source dates, missing dates, classification and cluster membership passed.');

const adjacent=[0,20,48,49,100,148].map(x=>({geometry:{type:'Point',coordinates:[x,0]},properties:{category:x<50?'A':'B'}}));
const shared=M.clusters(adjacent,coords=>({x:coords[0],y:coords[1]}),48);
assert.equal(shared.reduce((sum,g)=>sum+g.items.length,0),adjacent.length);
shared.forEach((g,i)=>shared.slice(i+1).forEach(other=>assert(Math.abs(g.coordinates[0]-other.coordinates[0])>48)));
assert.equal(M.earthFilter(adjacent,'',new Set(['A'])).length,4);
assert.equal(M.earthFilter(adjacent,'',new Set()).length,0);
assert.equal(M.sheetFilter([{final_result:''},{final_result:'Negativo'}],{finalResult:'missing'}).length,1);
assert.equal(M.sheetFilter([{final_result:''},{final_result:'Negativo'}],{finalResult:'Negativo'}).length,1);
console.log('Cross-layer anchor spacing, category toggles and final-result filters passed.');

const automation={rows:171,located:158,unlocated:13,methods:{exato:123,exato_sufixo:20,interpolado:12,condominio:3,sem_posicao:13},read_at:'2026-10-05T12:00:00+00:00',
  manual:{markers:154,compared:120,median_m:14,within_25m:96,within_50m:110,within_100m:116,over_100m:4}};
const text=M.automationSummary(automation);
assert(text.startsWith('171 notificações · 158 no mapa · 13 sem posição.'));
assert(text.includes('143 pelo número exato, 12 entre vizinhos, 3 em condomínio.'));
assert(text.includes('120 pares, mediana de 14 m; 96 a até 25 m, 110 a até 50 m, 4 a mais de 100 m.'));
assert(!text.includes('sem_posicao')&&text.includes('Planilha lida em'));
assert(M.automationSummary({...automation,manual:{markers:154,compared:0}}).includes('Nenhum marcador de Casos Dengue pôde ser pareado'));
assert(!M.automationSummary({...automation,manual:null,read_at:''}).includes('Casos Dengue'));
assert.equal(M.automationSummary({rows:1,located:1,unlocated:0,methods:{equipe:1}}),'1 notificação · 1 no mapa · 0 sem posição. Posição: 1 pela equipe.');
assert.equal(M.automationSummary(null),'');
assert(M.automationSummary({rows:171,located:166,unlocated:5,methods:{exato:143,interpolado:12,numeracao:2,condominio:8,localidade:1,memoria:1}})
  .includes('143 pelo número exato, 12 entre vizinhos, 2 pela numeração da rua, 8 em condomínio, 1 por localidade rural, 1 por endereço já marcado pela equipe.'));
console.log('Automatic dengue layer summary passed.');
