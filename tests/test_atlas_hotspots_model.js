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

// Notificações posicionadas automaticamente ficam na calçada: contam na quadra que o servidor atribuiu ao registro.
const U=.001, named=(id,x,sector,block)=>({type:'Feature',id,properties:{sector,block},geometry:{type:'Polygon',coordinates:[[[x*U,0],[(x+1)*U,0],[(x+1)*U,U],[x*U,U],[x*U,0]]]}});
const notice=(id,x,props)=>({feature:point(id,x*U,.5*U,props),kind:'notifications',key:id});
const town=M.index([named('q1',0,'010','100'),named('q2',3,'010','200'),named('dup-a',6,'020','300'),named('dup-b',9,'020','300')]);
assert(M.qualifies(point('n',.5,.5,{exam_result:'Negativo'}),'notifications'));
const notified=M.aggregate([
  notice('inside',.5,{sector:'010',block:'200'}),      // dentro da q1: a geometria vence a atribuição
  notice('sidewalk',1.4,{sector:'010',block:'100'}),   // fora de todas: vale a quadra atribuída
  notice('other',2.6,{sector:'010',block:'200'}),
  notice('unknown',5,{sector:'099',block:'1'}),        // quadra que não existe no território
  notice('ambiguous',8,{sector:'020',block:'300'}),    // chave repetida no território
  notice('bare',5)],town);
assert.equal(notified.located,3);assert.equal(notified.outside,3);
const count=id=>notified.blocks.find(b=>b.block.id===id)?.notifications;
assert.equal(count('q1'),2);assert.equal(count('q2'),1);
assert.deepEqual(notified.blocks.map(b=>[b.larvae,b.cases]),[[0,0],[0,0]]);
console.log('Hotspot model passed: automatic notifications use the assigned block only as a fallback.');
