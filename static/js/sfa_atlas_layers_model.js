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
        && (!filters.year || (filters.year==='unknown' ? !date : date && date.slice(0,4)===filters.year))
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
  function automationSummary(a) {
    // Resumo da camada Dengue Automatizados: quantos entraram no mapa, como, e a distância para a marcação manual.
    if(!a)return '';
    const m=a.methods||{}, exact=(m.exato||0)+(m.exato_sufixo||0), plural=(n,one,many)=>`${n} ${n===1?one:many}`;
    const how=[[exact,'pelo número exato'],[m.interpolado||0,'entre vizinhos'],[m.vizinho||0,'pelo vizinho mais próximo'],[m.condominio||0,'em condomínio'],[m.equipe||0,'pela equipe']]
      .filter(p=>p[0]).map(p=>p[0]+' '+p[1]).join(', ');
    const parts=[`${plural(a.rows,'notificação','notificações')} · ${a.located} no mapa · ${a.unlocated} sem posição.`];
    if(how)parts.push('Posição: '+how+'.');
    const c=a.manual;
    if(c&&c.compared)parts.push(`Comparação com Casos Dengue: ${plural(c.compared,'par','pares')}, mediana de ${c.median_m} m; ${c.within_25m} a até 25 m, ${c.within_50m} a até 50 m, ${c.over_100m} a mais de 100 m.`);
    else if(c)parts.push('Nenhum marcador de Casos Dengue pôde ser pareado por SINAN ou endereço: compare ligando as duas camadas.');
    if(a.read_at&&!Number.isNaN(Date.parse(a.read_at)))parts.push('Planilha lida em '+new Date(a.read_at).toLocaleString('pt-BR')+'.');
    return parts.join(' ');
  }
  const api={earthFilter,sheetFilter,clusters,automationSummary};
  if(typeof module!=='undefined')module.exports=api; else root.SfaAtlasLayersModel=api;
})(typeof window==='undefined'?globalThis:window);
