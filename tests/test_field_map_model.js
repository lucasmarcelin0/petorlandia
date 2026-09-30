const assert = require('node:assert/strict');
const {filter, placeLabels} = require('../static/js/sfa_field_map_model.js');
const f = (block, sector = '023', district = 'TEIXEIRA') => ({properties:{block,sector,district}});
const features = [f('436'), f('436','024'), f('1436'), f('899A'), f('899B'), f('12','001','Brazão')];
assert.equal(filter(features,{search:'quadra 436'}).length,2);
assert.equal(filter(features,{search:'436',sector:'023'}).length,1);
assert.equal(filter(features,{search:'Q899A'})[0].properties.block,'899A');
assert.equal(filter(features,{search:'SC 001'})[0].properties.block,'12');
assert.equal(filter(features,{search:'brazao'}).length,1);
assert.equal(filter(features,{search:'sem resultado'}).length,0);
const c = (id,x,y,priority=0) => ({id,x,y,width:40,height:24,priority});
const placed = placeLabels([c('hidden',50,50),c('selected',52,50,100),c('other',150,50),c('offscreen',5,5)],200,100);
assert.deepEqual(placed.map(p=>p.id),['selected','other']);
assert.deepEqual(placeLabels([c('under-control',50,50),c('clear',150,50)],200,100,5,[{left:20,right:80,top:20,bottom:80}]).map(p=>p.id),['clear']);
// Dense city view: every retained rectangle is fully visible and disjoint.
const grid = Array.from({length:1000},(_,i)=>c(i,(i*29)%790+5,(i*47)%590+5));
const output = placeLabels(grid,800,600);
assert.ok(output.length>50 && output.length<1000);
output.forEach((a,i)=>{
  assert.ok(a.x>=25 && a.x<=775 && a.y>=17 && a.y<=583);
  output.slice(i+1).forEach(b=>assert.ok(Math.abs(a.x-b.x)>=50 || Math.abs(a.y-b.y)>=34));
});
console.log('Field map: exact identifiers, suffixes, district search and non-overlapping visible labels passed.');
