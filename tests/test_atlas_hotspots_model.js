const assert=require('node:assert/strict');
const M=require('../static/js/sfa_atlas_hotspots_model.js');
const box=(id,x=0)=>({type:'Feature',id,properties:{block:id},geometry:{type:'Polygon',coordinates:[[[x,0],[x+1,0],[x+1,1],[x,1],[x,0]]]}});
const point=(id,x,y,props={})=>({type:'Feature',id,properties:props,geometry:{type:'Point',coordinates:[x,y]}});
assert.equal(M.kind('Casos Dengue'),'cases');assert.equal(M.kind('Larvas'),'larvae');assert.equal(M.kind('Atendimentos'),null);
assert(M.qualifies(point('p',.5,.5,{folder_status:'Positivo'}),'cases'));
for(const status of ['Negativo','Negativos','Suspeito','', 'Positivo suspeito'])assert(!M.qualifies(point('n',.5,.5,{folder_status:status}),'cases'));
assert(!M.qualifies(point('n',.5,.5,{folder_status:'Positivo',final_result:'Negativo'}),'cases'));
assert(!M.qualifies({geometry:{type:'Polygon'}},'larvae'));
const rows=[{feature:point('a',.5,.5),kind:'larvae',key:'a'},{feature:point('a',.5,.5),kind:'larvae',key:'a'},{feature:point('b',.5,.5),kind:'cases',key:'b'},{feature:point('outside',4,4),kind:'larvae',key:'outside'}];
const result=M.aggregate(rows,M.index([box('1')]));assert.equal(result.located,2);assert.equal(result.outside,1);assert.equal(result.blocks[0].larvae,1);assert.equal(result.blocks[0].cases,1);
// Adjacent boundaries and overlaps are ambiguous and must never double-count an event.
assert.equal(M.aggregate([{feature:point('b',1,.5),kind:'larvae',key:'b'}],M.index([box('1'),box('2',1)])).outside,1);
const hole=box('h');hole.geometry.coordinates.push([[.2,.2],[.8,.2],[.8,.8],[.2,.8],[.2,.2]]);assert(!M.contains([.5,.5],hole.geometry));
assert(M.contains([.1,.1],hole.geometry));
console.log('Hotspot model passed: exclusions, deduplication, boundaries, overlaps and holes.');
