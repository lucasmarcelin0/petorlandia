(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.SfaAtlasFoldersModel=factory();})(typeof self!=='undefined'?self:this,function(){
  'use strict';
  function tree(nodes){
    const byId=new Map(nodes.map(n=>[n.id,{...n,children:[]}]));
    const roots=[];
    byId.forEach(n=>{const p=byId.get(n.parent_id);if(p)p.children.push(n);else roots.push(n);});
    function visit(n,parents=[]){
      if(parents.some(p=>p.id===n.id)||parents.length>12)return;
      n.path=[...parents.map(p=>p.name),n.name];n.ids=new Set([n.id]);n.count=n.direct_count||0;
      n.children.forEach(c=>{visit(c,[...parents,n]);c.ids?.forEach(id=>n.ids.add(id));n.count+=c.count||0;});
    }
    roots.forEach(n=>visit(n));return {roots,byId};
  }
  function filter(features,filters={},selected=null,ignoreTime=false){
    return features.filter(f=>{
      const p=f.properties||{},date=p.date||p.notification_date||'',year=date.slice(0,4)||p.period_year||'';
      if(selected&&!selected.has(p.folder_id||''))return false;
      if(ignoreTime)return true;
      return (!filters.month||(filters.month==='unknown'?!p.month:p.month===filters.month))
        &&(!filters.year||(filters.year==='unknown'?!year:year===filters.year))
        &&(!filters.start||date&&date>=filters.start)&&(!filters.end||date&&date<=filters.end);
    });
  }
  function selection(node,selected,enabled){
    const count=[...node.ids].filter(id=>selected.has(id)).length;
    return {checked:enabled&&count===node.ids.size,indeterminate:enabled&&count>0&&count<node.ids.size};
  }
  return {tree,filter,selection};
});
