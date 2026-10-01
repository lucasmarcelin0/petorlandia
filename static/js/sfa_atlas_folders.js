(function(){
  'use strict';const M=window.SfaAtlasFoldersModel;
  window.SfaAtlasFolders={attach(entry,wrapper,{change,focus}){
    const model=M.tree(entry.folders||[]),inputs=[];
    entry.selectedFolders=entry.selectedFolders||new Set(['',...(entry.folders||[]).map(n=>n.id)]);
    const container=document.createElement('div');container.className='atlas-folder-tree';wrapper.append(container);
    function add(node,parent){
      const box=document.createElement('details'),summary=document.createElement('summary'),row=document.createElement('div');
      row.className='atlas-folder-row';box.className='atlas-folder-node';box.dataset.folder=node.id;box.open=entry.openFolders?.has(node.id)||false;
      box.ontoggle=()=>{entry.openFolders=entry.openFolders||new Set();if(box.open)entry.openFolders.add(node.id);else entry.openFolders.delete(node.id);};
      const label=document.createElement('label'),toggle=document.createElement('input'),name=document.createElement('span'),count=document.createElement('small'),button=document.createElement('button');
      toggle.type='checkbox';toggle.disabled=entry.input.disabled;toggle.setAttribute('aria-label',entry.title+' / '+node.path.join(' / '));
      name.textContent=node.name;count.textContent=String(node.count);label.append(toggle,name,count);
      button.type='button';button.className='atlas-folder-focus';button.textContent='↗';button.title='Enquadrar '+node.path.join(' / ');button.setAttribute('aria-label',button.title);button.disabled=entry.input.disabled;
      button.onclick=e=>{e.stopPropagation();focus(node);};
      toggle.onclick=e=>e.stopPropagation();toggle.onchange=()=>{
        if(!entry.enabled)entry.selectedFolders=new Set(toggle.checked?node.ids:[]);
        else node.ids.forEach(id=>{if(toggle.checked)entry.selectedFolders.add(id);else entry.selectedFolders.delete(id);});
        entry.input.checked=true;entry.enabled=true;change();
      };
      inputs.push({node,toggle,count});row.append(label,button);
      if(node.children.length){summary.append(row);box.append(summary);node.children.forEach(c=>add(c,box));parent.append(box);}
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
