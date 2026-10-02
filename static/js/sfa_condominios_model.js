(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.SfaCondominiosModel=factory();
})(typeof self!=='undefined'?self:this,function(){
  'use strict';
  function isHouse(f){return ['condominium_house','cadastre_house','cnefe_house'].includes(f.properties?.kind)||(f.properties?.position_status==='verified'&&['101','102'].includes(f.properties?.cnefe_building_type)&&!!f.properties?.house_number)||f.atlasEntry?.origin?.type==='condominium';}
  function number(f){
    const p=f.properties||{}, edited=String(p.name||p.label||'').match(/^(?:Casa|N[ºo.]?)\s+(\d+[A-Za-z]?)(?:\s+·.*)?$/i);
    return p.number_edited||p.kind==='cnefe_house'?String(p.house_number||''):edited?edited[1]:String(p.house_number||'');
  }
  function shortLabel(f){const value=number(f);return value?(f.properties?.kind==='condominium_house'?value.padStart(2,'0'):value):'•';}
  function street(f){return String(f.properties?.address||'').match(/\bAlameda\s+(\d+)/i)?.[0]||f.properties?.category||'';}
  function overview(features){
    const groups=new Map();
    features.forEach(f=>{
      const key=f.atlasEntry?.id||f.properties?.condominium||'cadastro';
      if(!groups.has(key))groups.set(key,{name:f.properties?.condominium||f.atlasEntry?.title||'Casas',items:[],color:f.atlasEntry?.color||'#147f8c'});
      groups.get(key).items.push(f);
    });
    return [...groups.values()].map(g=>({...g,coordinates:g.items.reduce((a,f)=>a.map((v,k)=>v+f.geometry.coordinates[k]/g.items.length),[0,0])}));
  }
  function candidates(features,project){
    return features.map(f=>{const p=project(f.geometry.coordinates),label=shortLabel(f);return {feature:f,text:label,x:p.x,y:p.y,width:Math.max(22,label.length*7+8),height:20,priority:1};});
  }
  function streets(features,project){
    const groups=new Map();
    features.forEach(f=>{const name=street(f);if(!/^Alameda\s+\d+$/i.test(name))return;const key=(f.atlasEntry?.id||f.properties.condominium)+'-'+name;
      if(!groups.has(key))groups.set(key,{name,items:[]});groups.get(key).items.push(f);});
    return [...groups.values()].map(g=>{const coordinates=g.items.reduce((a,f)=>a.map((v,k)=>v+f.geometry.coordinates[k]/g.items.length),[0,0]),p=project(coordinates);
      return {text:g.name,coordinates,x:p.x,y:p.y,width:78,height:16,priority:0};});
  }
  return {isHouse,number,shortLabel,street,overview,candidates,streets};
});
