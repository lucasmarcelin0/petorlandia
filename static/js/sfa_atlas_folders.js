(function(){
  'use strict';const M=window.SfaAtlasFoldersModel;
  window.SfaAtlasFolders={attach(entry,wrapper,{change,focus}){
    const model=M.tree(entry.folders||[]),inputs=[];
    entry.selectedFolders=entry.selectedFolders||new Set(['',...(entry.folders||[]).map(n=>n.id)]);
    const container=document.createElement('div');container.className='atlas-folder-tree';wrapper.append(container);
    function add(node,parent){
      const box=document.createElement('div'),row=document.createElement('div'),children=document.createElement('div'),expand=document.createElement('button');
      row.className='atlas-folder-row';box.className='atlas-folder-node';box.dataset.folder=node.id;
      children.className='atlas-folder-children';children.hidden=!entry.openFolders?.has(node.id);
      expand.type='button';expand.className='atlas-folder-expand';expand.textContent=children.hidden?'▸':'▾';expand.setAttribute('aria-expanded',String(!children.hidden));expand.setAttribute('aria-label','Subpastas de '+entry.title+' / '+node.path.join(' / '));expand.disabled=entry.input.disabled;
      expand.onclick=()=>{children.hidden=!children.hidden;expand.textContent=children.hidden?'▸':'▾';expand.setAttribute('aria-expanded',String(!children.hidden));entry.openFolders=entry.openFolders||new Set();if(children.hidden)entry.openFolders.delete(node.id);else entry.openFolders.add(node.id);};
      if(node.children.length)row.append(expand);
      const label=document.createElement('label'),toggle=document.createElement('input'),name=document.createElement('span'),count=document.createElement('small'),button=document.createElement('button');
      toggle.type='checkbox';toggle.disabled=entry.input.disabled;toggle.setAttribute('aria-label',entry.title+' / '+node.path.join(' / '));
      name.textContent=node.name;count.textContent=String(node.count);label.append(toggle,name,count);
      button.type='button';button.className='atlas-folder-focus';button.textContent='↗';button.title='Enquadrar '+node.path.join(' / ');button.setAttribute('aria-label',button.title);button.disabled=entry.input.disabled;
      button.onclick=()=>focus(node);
      toggle.onclick=e=>e.stopPropagation();toggle.onchange=()=>{
        if(!entry.enabled)entry.selectedFolders=new Set(toggle.checked?node.ids:[]);
        else node.ids.forEach(id=>{if(toggle.checked)entry.selectedFolders.add(id);else entry.selectedFolders.delete(id);});
        entry.input.checked=true;entry.enabled=true;change();
      };
      inputs.push({node,toggle,count});row.append(label,button);
      if(node.children.length){box.append(row,children);node.children.forEach(c=>add(c,children));parent.append(box);}
      else{row.classList.add('atlas-folder-leaf');parent.append(row);}
    }
    model.roots.forEach(n=>add(n,container));
    if((entry.count||0)-(entry.folders||[]).reduce((a,n)=>a+(n.direct_count||0),0)>0&&model.roots.length){
      const root={id:'',name:'Direto na camada',path:['Direto na camada'],ids:new Set(['']),count:(entry.count||0)-(entry.folders||[]).reduce((a,n)=>a+(n.direct_count||0),0),children:[]};add(root,container);
    }
    return {refresh(rows=[]){inputs.forEach(({node,toggle,count})=>{const state=M.selection(node,entry.selectedFolders,entry.enabled);toggle.checked=state.checked;toggle.indeterminate=state.indeterminate;
      count.textContent=entry.enabled?rows.filter(f=>node.ids.has(f.properties.folder_id||'')).length+' / '+node.count:String(node.count);});}};
  }};
})();
