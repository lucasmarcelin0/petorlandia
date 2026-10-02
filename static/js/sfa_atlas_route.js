/*
 * Rota de campo no atlas: o caminho é calculado aqui, pelas ruas do OpenStreetMap que o atlas
 * já carrega. Nenhum endereço, paciente ou ponto da rota é enviado a serviço externo de rotas.
 * O Google Maps só recebe coordenadas se a pessoa tocar no link de navegação.
 */
(function(){
  'use strict';
  const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const STORAGE='sfa-atlas-route-v1', MAX_STOPS=25;

  window.SfaAtlasRoute={attach(map,dataset){
    const panel=$('atlas-route'),Model=window.SfaAtlasRouteModel,urls=dataset.editor_urls;
    if(!panel||!Model||!urls.street_network)return {addStop(){}};
    const list=$('atlas-route-list'),empty=$('atlas-route-empty'),summary=$('atlas-route-summary'),notice=$('atlas-route-notice'),links=$('atlas-route-links');
    const buttons={here:$('atlas-route-here'),optimize:$('atlas-route-optimize'),fit:$('atlas-route-fit'),copy:$('atlas-route-copy'),clear:$('atlas-route-clear'),foot:$('atlas-route-foot'),motor:$('atlas-route-motor'),nav:$('atlas-route-nav'),sim:$('atlas-route-sim')};
    let stops=[],plan=null,mode='foot',graphPromise=null,run=0,focusAfter=null,computing=null;
    map.createPane('atlas-route').style.zIndex=640;
    const layer=L.layerGroup().addTo(map);

    // ---- Persistência só na aba (some ao fechar): endereços não ficam no aparelho ----
    function save(){try{sessionStorage.setItem(STORAGE,JSON.stringify({mode,stops:stops.filter(s=>!s.gps)}));}catch(e){/* sem armazenamento: segue sem salvar */}}
    function restore(){
      try{
        const data=JSON.parse(sessionStorage.getItem(STORAGE)||'null');
        if(data&&Array.isArray(data.stops)){
          stops=data.stops.filter(s=>s&&Number.isFinite(s.lat)&&Number.isFinite(s.lng)).slice(0,MAX_STOPS);
          if(data.mode==='motor')mode='motor';
        }
      }catch(e){stops=[];}
    }

    function say(text,error){notice.textContent=text||'';notice.hidden=!text;notice.classList.toggle('is-error',!!error);}
    function flash(button,text){
      if(!button)return;
      const original=button.dataset.label||button.textContent;button.dataset.label=original;
      button.textContent=text;button.disabled=true;
      setTimeout(()=>{button.textContent=original;button.disabled=false;},1400);
    }

    // ---- Malha de ruas (baixada uma vez, só quando a rota é usada) ----
    function graph(){
      if(!graphPromise){
        graphPromise=fetch(urls.street_network,{credentials:'same-origin'}).then(r=>{
          if(!r.ok)throw Error('A malha de ruas não está disponível agora.');
          return r.json();
        }).then(Model.createGraph).catch(e=>{graphPromise=null;throw e;});
      }
      return graphPromise;
    }

    // ---- Do resultado da busca a um ponto no mapa ----
    function flatten(coords,out){
      if(typeof coords[0]==='number'){out.push(coords);return out;}
      coords.forEach(c=>flatten(c,out));return out;
    }
    function geometryPoints(geometry,out){
      if(!geometry)return out;
      if(geometry.type==='GeometryCollection')geometry.geometries.forEach(g=>geometryPoints(g,out));
      else flatten(geometry.coordinates,out);
      return out;
    }
    async function resolvePoint(d){
      if(d.feature){const c=L.geoJSON(d.feature).getBounds().getCenter();return {lat:c.lat,lng:c.lng};}
      if(d.kind===1)return {lat:d.y,lng:d.x};
      if(d.kind===2){
        // Um ponto que está de fato sobre a rua: o vértice mais próximo do centro do trecho.
        const target={lat:d.y,lng:d.x};
        try{
          const r=await fetch(urls.search_place+(urls.search_place.includes('?')?'&':'?')+'layer='+encodeURIComponent(d.layerId)+'&feature='+encodeURIComponent(d.featureId),{credentials:'same-origin',cache:'no-store'});
          if(r.ok){
            const item=await r.json(),points=geometryPoints(item.feature.geometry,[]);
            let best=null;
            points.forEach(p=>{const dist=Model.distance(target.lat,target.lng,p[1],p[0]);if(!best||dist<best.dist)best={dist,lat:p[1],lng:p[0]};});
            if(best)return {lat:best.lat,lng:best.lng};
          }
        }catch(e){/* usa o centro do trecho */}
        return target;
      }
      return null;
    }

    // ---- Cálculo e desenho ----
    function compute(opts){
      const mine=++run;opts=opts||{};
      layer.clearLayers();plan=null;
      if(stops.length<2){render();drawPins();return Promise.resolve();}
      computing=graph().then(g=>{
        if(mine!==run)return;
        plan=Model.plan(g,stops);drawRoute();render();
        if(opts.fit)fitRoute();
      }).catch(e=>{if(mine===run){say(e.message||'Não foi possível calcular a rota.',true);render();drawPins();}});
      render();drawPins();
      return computing;
    }
    function pin(stop,index){
      const icon=L.divIcon({className:'atlas-route-pin'+(stop.gps?' is-gps':''),html:'<span>'+(stop.gps?'●':index+1)+'</span>',iconSize:[30,30],iconAnchor:[15,15]});
      return L.marker([stop.lat,stop.lng],{icon,pane:'atlas-route',title:(index+1)+'. '+stop.name,keyboard:false}).bindTooltip(esc((index+1)+'. '+stop.name),{direction:'top',offset:[0,-12]});
    }
    function drawPins(){stops.forEach((s,i)=>pin(s,i).addTo(layer));}
    function drawRoute(){
      layer.clearLayers();
      plan.legs.forEach(leg=>{
        if(leg.connected){
          L.polyline(leg.path,{color:'#fff',weight:9,opacity:.95,pane:'atlas-route',interactive:false,lineCap:'round',lineJoin:'round'}).addTo(layer);
          L.polyline(leg.path,{color:'#0b7285',weight:5,opacity:1,pane:'atlas-route',interactive:false,lineCap:'round',lineJoin:'round'}).addTo(layer);
        }else{
          L.polyline(leg.path,{color:'#d9480f',weight:4,dashArray:'8 8',opacity:.95,pane:'atlas-route',interactive:false}).addTo(layer);
        }
      });
      drawPins();
    }
    function fitRoute(){
      if(!stops.length)return;
      const points=plan?plan.legs.flatMap(l=>l.path):stops.map(s=>[s.lat,s.lng]);
      const bounds=L.latLngBounds(points);
      if(bounds.isValid())map.fitBounds(bounds,{padding:[60,60],maxZoom:18});
    }

    // ---- Lista, resumo e links ----
    const speedLabel=m=>m==='motor'?'de moto ou carro':'a pé';
    function render(){
      // A lista é refeita quando o cálculo termina; o foco volta para o mesmo botão.
      const active=list.contains(document.activeElement)?document.activeElement.dataset.tool:null;
      list.replaceChildren();empty.hidden=stops.length>0;
      stops.forEach((s,i)=>{
        const li=document.createElement('li');li.className='atlas-route-stop'+(s.gps?' is-gps':'');
        const leg=plan&&plan.legs[i];
        li.innerHTML='<span class="atlas-route-number" aria-hidden="true">'+(s.gps?'●':i+1)+'</span>'
          +'<div class="atlas-route-text"><strong>'+esc(s.name)+'</strong>'+(s.note?'<small>'+esc(s.note)+'</small>':'')
          +(leg?'<small class="atlas-route-leg'+(leg.connected?'':' is-straight')+'">'+(leg.connected?'→ ':'⚠ linha reta · ')+esc(Model.formatDistance(leg.distance))+' · '+esc(Model.formatDuration(Model.minutes(leg.distance,mode)))+' '+speedLabel(mode)+'</small>':'')+'</div>'
          +'<div class="atlas-route-tools"></div>';
        const tools=li.querySelector('.atlas-route-tools');
        const tool=(label,text,action,disabled,name)=>{
          const b=document.createElement('button');b.type='button';b.textContent=text;b.title=label;b.setAttribute('aria-label',label+': '+s.name);b.disabled=!!disabled;b.dataset.tool=name+'-'+i;b.onclick=action;tools.append(b);
        };
        tool('Mostrar no mapa','◎',()=>map.setView([s.lat,s.lng],Math.max(map.getZoom(),17)),false,'see');
        tool('Subir','↑',()=>move(i,-1),i===0,'up');
        tool('Descer','↓',()=>move(i,1),i===stops.length-1,'down');
        tool('Remover da rota','✕',()=>remove(i),false,'del');
        list.append(li);
      });
      const wanted=focusAfter||active;
      if(wanted){const b=list.querySelector('[data-tool="'+wanted+'"]');(b&&!b.disabled?b:list.querySelector('button:not([disabled])'))?.focus();focusAfter=null;}

      const has=stops.length>0,two=stops.length>=2;
      buttons.optimize.disabled=stops.length<3;buttons.fit.disabled=!has;buttons.copy.disabled=!has;buttons.clear.disabled=!has;
      const places=stops.filter(s=>!s.gps).length;                       // a posição de partida vem do GPS na hora de navegar
      buttons.nav.disabled=places<1;buttons.sim.disabled=places<2;
      ['foot','motor'].forEach(m=>{buttons[m].setAttribute('aria-pressed',String(mode===m));buttons[m].classList.toggle('is-on',mode===m);});
      renderSummary(two);renderLinks(two);renderChip();
    }
    function renderSummary(two){
      if(!two||!plan){summary.hidden=true;summary.textContent='';return;}
      const straight=plan.legs.filter(l=>!l.connected).length;
      summary.hidden=false;
      summary.innerHTML='<strong>'+esc(Model.formatDistance(plan.total))+'</strong> no total · <span>'+esc(Model.formatDuration(Model.minutes(plan.total,'foot')))+' a pé</span> · <span>'+esc(Model.formatDuration(Model.minutes(plan.total,'motor')))+' de moto ou carro</span>'
        +(straight?'<em>'+straight+(straight>1?' trechos ficaram':' trecho ficou')+' em linha reta: não há ligação pelas ruas mapeadas. Confira no mapa.</em>':'');
    }
    function renderLinks(two){
      links.replaceChildren();links.hidden=!two;
      if(!two)return;
      const head=document.createElement('p');head.className='atlas-route-linkhead';head.textContent='Navegar com o Google Maps';links.append(head);
      Model.googleMapsLinks(stops,mode).forEach(l=>{
        const a=document.createElement('a');a.href=l.url;a.target='_blank';a.rel='noopener noreferrer';
        a.textContent='Paradas '+l.from+(l.to>l.from?'–'+l.to:'')+' ↗';a.className='atlas-route-link';links.append(a);
      });
      const note=document.createElement('small');note.textContent='Abre o Google Maps no seu aparelho. Só as coordenadas das paradas são enviadas, e apenas quando você toca no link.';links.append(note);
    }
    // Atalho sobre o mapa: no celular o painel fica abaixo dele.
    const Chip=L.Control.extend({options:{position:'topright'},onAdd(){
      const b=L.DomUtil.create('button','atlas-route-chip');b.type='button';b.hidden=true;
      L.DomEvent.disableClickPropagation(b);
      b.onclick=()=>{panel.scrollIntoView({behavior:'smooth',block:'start'});};
      this._button=b;return b;
    }});
    const chip=new Chip().addTo(map);
    function renderChip(){
      const b=chip._button;b.hidden=!stops.length;
      b.textContent='Rota · '+stops.length+(stops.length===1?' parada':' paradas')+(plan?' · '+Model.formatDistance(plan.total):'');
      b.setAttribute('aria-label',b.textContent+'. Ir ao painel da rota.');
    }

    // ---- Ações ----
    function changed(opts){save();compute(opts);}
    function move(i,delta){
      const j=i+delta;if(j<0||j>=stops.length)return;
      [stops[i],stops[j]]=[stops[j],stops[i]];focusAfter=(delta<0?'up-':'down-')+j;changed();
    }
    function remove(i){const[name]=stops.splice(i,1).map(s=>s.name);focusAfter='del-'+Math.min(i,stops.length-1);changed();say('“'+name+'” removida da rota.');}
    async function addStop(d,button){
      try{
        const dup=stops.find(s=>d.layerId?(s.layerId===d.layerId&&s.featureId===d.featureId):(!s.layerId&&s.name===d.name&&s.note===d.note));
        if(dup){flash(button,'Já está na rota');return;}
        if(stops.length>=MAX_STOPS){say('Uma rota aceita até '+MAX_STOPS+' paradas.',true);return;}
        if(button){button.disabled=true;}
        const point=await resolvePoint(d);
        if(button)button.disabled=false;
        if(!point){say('Este local não tem posição no mapa. Confira o cadastro.',true);return;}
        stops.push({name:d.name,note:d.note||'',lat:point.lat,lng:point.lng,layerId:d.layerId,featureId:d.featureId});
        changed({fit:stops.length>=2});
        say('“'+d.name+'” é a parada '+stops.length+'.');flash(button,'✓ Na rota');
        graph().catch(()=>{});
      }catch(e){if(button)button.disabled=false;say(e.message||'Não foi possível adicionar à rota.',true);}
    }
    function here(){
      if(!navigator.geolocation){say('Este aparelho não informa a localização.',true);return;}
      buttons.here.disabled=true;say('Obtendo sua localização…');
      navigator.geolocation.getCurrentPosition(pos=>{
        buttons.here.disabled=false;
        stops=stops.filter(s=>!s.gps);
        stops.unshift({gps:true,name:'Minha localização',note:'Posição do aparelho agora',lat:pos.coords.latitude,lng:pos.coords.longitude});
        changed({fit:stops.length>=2});say('Rota começando na sua localização.');
      },err=>{
        buttons.here.disabled=false;
        say(err.code===1?'Localização bloqueada. Libere no navegador para começar da sua posição.':err.code===3?'Demorou demais para obter a posição. Tente ao ar livre.':'Não foi possível obter a posição agora.',true);
      },{enableHighAccuracy:true,timeout:15000,maximumAge:30000});
    }
    async function optimize(){
      if(stops.length<3)return;
      try{
        const g=await graph(),result=Model.optimizeOrder(g,stops);
        if(result.order.every((v,i)=>v===i)){say('A ordem atual já é a mais curta que encontrei.');return;}
        const gain=Math.round((1-result.after/result.before)*100);
        stops=result.order.map(i=>stops[i]);changed({fit:true});
        say('Nova ordem: de '+Model.formatDistance(result.before)+' para '+Model.formatDistance(result.after)+(gain>0?' ('+gain+'% menos)':'')+'. A primeira parada continua sendo a partida.');
      }catch(e){say(e.message||'Não foi possível reordenar.',true);}
    }
    function roteiro(){
      const lines=['Rota de campo · '+stops.length+' paradas'];
      stops.forEach((s,i)=>{
        lines.push((i+1)+'. '+s.name+(s.note?' — '+s.note:''));
        const leg=plan&&plan.legs[i];
        if(leg)lines.push('   → '+Model.formatDistance(leg.distance)+' · '+Model.formatDuration(Model.minutes(leg.distance,mode))+' '+speedLabel(mode)+(leg.connected?'':' (linha reta)'));
      });
      if(plan)lines.push('Total: '+Model.formatDistance(plan.total)+' · '+Model.formatDuration(Model.minutes(plan.total,mode))+' '+speedLabel(mode));
      return lines.join('\n');
    }
    async function copy(){
      const text=roteiro();
      try{
        if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(text);
        else{const t=document.createElement('textarea');t.value=text;t.style.position='fixed';t.style.opacity='0';document.body.append(t);t.select();document.execCommand('copy');t.remove();}
        flash(buttons.copy,'✓ Copiado');
      }catch(e){say('Não foi possível copiar. Selecione o texto da lista manualmente.',true);}
    }
    function clearAll(){
      if(stops.length>2&&!window.confirm('Remover as '+stops.length+' paradas da rota?'))return;
      stops=[];changed();say('Rota limpa.');
    }

    buttons.here.onclick=here;buttons.optimize.onclick=optimize;buttons.fit.onclick=fitRoute;buttons.copy.onclick=copy;buttons.clear.onclick=clearAll;
    ['foot','motor'].forEach(m=>buttons[m].onclick=()=>{mode=m;save();render();});

    // Navegação em tela cheia (mapa girando, voz). A partida é a posição do aparelho; na simulação, a 1ª parada.
    const navigation=window.SfaAtlasNav?window.SfaAtlasNav.attach(map,{graph,stops:()=>stops.filter(s=>!s.gps),mode:()=>mode,onExit:()=>render()}):null;
    buttons.nav.onclick=()=>{if(navigation)navigation.start({simulate:false});};
    buttons.sim.onclick=()=>{if(navigation)navigation.start({simulate:true});};

    restore();render();
    if(stops.length)compute();
    return {addStop,get stops(){return stops.slice();},get plan(){return plan;},ready:()=>computing,navigation};
  }};
})();
