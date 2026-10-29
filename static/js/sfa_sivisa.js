(function(){
  'use strict';
  window.SfaSivisa={async attach(map){
    let response;
    try {response=await fetch('/sfa/entomologia/sivisa',{credentials:'same-origin',cache:'no-store'});} catch (_) {return;}
    if(!response.ok || !response.headers.get('content-type')?.includes('application/json')) return;
    const data=await response.json(); if(!data.registros?.length)return;
    const host=document.getElementById('atlas-layer-controls'); if(!host)return;
    const wrap=document.createElement('div'), label=document.createElement('label'), input=document.createElement('input');
    const title=document.createElement('strong');title.textContent=' Inspeções SIVISA · somente administrador';
    label.append(input,title);wrap.append(label);input.type='checkbox';
    const msg=document.createElement('p');const pending=data.registros.filter(r=>!r.coordenadas);
    msg.textContent=`${data.registros.length} inspeções · ${data.registros.length-pending.length} com posição · ${pending.length} sem posição. Última data de validade encontrada por documento e endereço, comparada com ${data.fim}; não comprova situação oficial da licença.`;
    wrap.append(msg);
    const details=document.createElement('details'), summary=document.createElement('summary');summary.textContent='Consultar inspeções sem posição'; details.append(summary);
    const list=document.createElement('ul');pending.forEach(r=>{const li=document.createElement('li');li.textContent=`${r.data} · ${r.nome || 'Inspeção'} · ${r.endereco || 'Endereço não informado'} · ${r.situacao}${r.validade?' · validade '+r.validade:''}`;list.append(li);});details.append(list);wrap.append(details);host.append(wrap);
    const group=L.layerGroup(), colors={'Prazo não vencido na data da extração':'#2b9162','Prazo vencido na data da extração':'#c35b4e','Sem validade identificada':'#a37920'};
    input.addEventListener('change',()=>{
      if(!input.checked){group.remove();return;}
      if(!group.getLayers().length)data.registros.filter(r=>r.coordenadas).forEach(r=>{
        const content=document.createElement('div'), strong=document.createElement('strong'), p=document.createElement('p');
        strong.textContent=r.nome||'Inspeção sanitária';p.textContent=`${r.endereco} · Inspeção ${r.data} · ${r.situacao}${r.validade?' · validade '+r.validade:''}. Posição de referência IBGE 2022; conferir.`;
        content.append(strong,p);L.circleMarker([r.coordenadas[1],r.coordenadas[0]],{radius:5,color:colors[r.situacao],weight:2,fillOpacity:.8}).bindPopup(content).addTo(group);
      });group.addTo(map);
    });
  }};
})();
