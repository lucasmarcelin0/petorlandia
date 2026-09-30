(function(root){
  'use strict';
  function earthFilter(features, month, categories) {return features.filter(f=>(!month || (month==='unknown' ? !f.properties.month : f.properties.month===month)) && (!categories || categories.has(f.properties.category || '')));}
  function sheetFilter(rows, filters={}) {
    return rows.filter(r=>{
      const date=r[filters.dateField || 'notification_date'];
      return (!filters.start || date && date>=filters.start) && (!filters.end || date && date<=filters.end)
        && (!filters.result || r.result_group===filters.result)
        && (!filters.finalResult || (filters.finalResult==='missing' ? !r.final_result : r.final_result===filters.finalResult))
        && (!filters.classification || (r.classification || '')===filters.classification)
        && (!filters.month || (filters.month==='unknown' ? !date : date && date.slice(5,7)===filters.month));
    });
  }
  function clusters(features, project, size=52) {
    // One spatial index across every active source. Anchors remain actual points.
    const cells=new Map(), groups=[];
    features.forEach(f=>{
      const p=project(f.geometry.coordinates), x=Math.floor(p.x/size), y=Math.floor(p.y/size);
      let nearest=null, distance=size*size;
      for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++){
        for(const group of cells.get((x+dx)+':'+(y+dy)) || []){
          const d=(p.x-group.point.x)**2+(p.y-group.point.y)**2;
          if(d<=distance){nearest=group;distance=d;}
        }
      }
      if(nearest)nearest.items.push(f);
      else{
        const group={items:[f],coordinates:f.geometry.coordinates,point:p}, key=x+':'+y;
        if(!cells.has(key))cells.set(key,[]);
        cells.get(key).push(group);groups.push(group);
      }
    });
    return groups;
  }
  const api={earthFilter,sheetFilter,clusters};
  if(typeof module!=='undefined')module.exports=api; else root.SfaAtlasLayersModel=api;
})(typeof window==='undefined'?globalThis:window);
