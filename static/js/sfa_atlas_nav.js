/*
 * Navegação em tela cheia no atlas (estilo Waze/Google Maps): o mapa gira para o sentido da
 * viagem, a seta fica fixa no terço de baixo, o banner mostra a próxima manobra e a voz avisa.
 * Roda no aparelho, sobre as ruas do OpenStreetMap que o atlas já carrega: nenhuma posição ou
 * endereço sai para serviço externo de rotas. O mapa de fundo usa os mesmos blocos do atlas.
 *
 * O mapa é um Leaflet comum dentro de um quadrado maior que a tela, girado por CSS; assim o
 * traçado, a rota e os pinos giram juntos e os pinos se contragiram para o texto ficar de pé.
 */
(function(){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const VOICE_KEY='sfa-nav-voice', SIM_SPEEDS=[null,10,25];             // m/s; null = velocidade do modo escolhido
  const ATTRIB={streets:'Mapa © Esri, HERE, Garmin, OpenStreetMap e comunidade GIS',satellite:'Imagens © Esri, Maxar, Earthstar Geographics e comunidade GIS'};

  // ---- Ícones das manobras (SVG simples, traço branco) ----
  const ICONS={
    straight:'<path d="M32 54V16"/><path d="M20 28 32 14l12 14"/>',
    right:'<path d="M20 54V34a8 8 0 0 1 8-8h18"/><path d="M36 14l12 12-12 12"/>',
    left:'<path d="M44 54V34a8 8 0 0 0-8-8H18"/><path d="M28 14 16 26l12 12"/>',
    'slight-right':'<path d="M22 54V40c0-8 6-12 12-16l8-6"/><path d="M30 16h14v14"/>',
    'slight-left':'<path d="M42 54V40c0-8-6-12-12-16l-8-6"/><path d="M34 16H20v14"/>',
    'sharp-right':'<path d="M18 16h14a10 10 0 0 1 10 10v26"/><path d="M30 42l12 12 12-12" transform="translate(-10 -6)"/>',
    'sharp-left':'<path d="M46 16H32a10 10 0 0 0-10 10v26"/><path d="M10 42l12 12 12-12" transform="translate(10 -6)"/>',
    uturn:'<path d="M22 54V26a10 10 0 0 1 20 0v10"/><path d="M32 28l10 12 10-12" transform="translate(-10 0)"/>',
    arrive:'<path d="M22 56V12"/><path d="M22 14h26l-6 9 6 9H22" fill="#fff" stroke-linejoin="round"/>',
  };
  const icon=type=>'<svg viewBox="0 0 64 64" width="100%" height="100%" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(ICONS[type]||ICONS.straight)+'</svg>';
  const ME='<svg viewBox="0 0 48 48" width="100%" height="100%" aria-hidden="true"><path d="M24 4 40 42 24 34 8 42Z" fill="#1c7ed6" stroke="#fff" stroke-width="3.5" stroke-linejoin="round"/></svg>';

  window.SfaAtlasNav={attach(map,{graph,stops,mode,onExit}){
    const Route=window.SfaAtlasRouteModel,Nav=window.SfaAtlasNavModel;
    if(!Route||!Nav||!window.L)return {start(){},get active(){return false;}};
    let ui=null,nav=null,active=false;

    const clock=ms=>new Date(Date.now()+ms).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
    const mpp=(zoom,lat)=>156543.03392*Math.cos(lat*Math.PI/180)/Math.pow(2,zoom);

    // ---------------------------------------------------------------- construção da tela
    function build(){
      const root=document.createElement('div');root.className='atlas-nav';root.setAttribute('role','dialog');root.setAttribute('aria-modal','true');root.setAttribute('aria-label','Navegação');
      root.innerHTML=
        '<div class="nav-stage"><div class="nav-rot"><div class="nav-map"></div></div>'
        +'<div class="nav-me" aria-hidden="true">'+ME+'</div></div>'
        +'<header class="nav-banner" aria-live="off"><span class="nav-banner-icon"></span><div class="nav-banner-text"><strong class="nav-dist"></strong><span class="nav-instr"></span><small class="nav-then"></small></div></header>'
        +'<p class="nav-toast" role="status" hidden></p>'
        +'<div class="nav-tools" role="group" aria-label="Controles do mapa">'
        +'<button type="button" data-act="voice" aria-label="Voz ligada" title="Voz"></button>'
        +'<button type="button" data-act="orient" title="Girar o mapa ou manter o norte para cima"></button>'
        +'<button type="button" data-act="base" title="Mapa de ruas ou satélite"></button>'
        +'<button type="button" data-act="overview" aria-label="Ver a rota inteira" title="Ver a rota inteira">🧭</button>'
        +'<button type="button" data-act="zoom-in" aria-label="Aproximar">＋</button><button type="button" data-act="zoom-out" aria-label="Afastar">－</button>'
        +'<button type="button" data-act="speed" hidden title="Velocidade da simulação"></button></div>'
        +'<footer class="nav-bar"><div class="nav-stats"><strong class="nav-eta"></strong><span class="nav-left"></span></div>'
        +'<div class="nav-bar-actions"><button type="button" data-act="skip" title="Pular esta parada e recalcular">Pular</button><button type="button" class="nav-exit" data-act="exit">Sair</button></div>'
        +'<div class="nav-next"><small class="nav-stoplabel"></small><span class="nav-stopname"></span></div></footer>'
        +'<p class="nav-attrib"></p><p class="nav-gps" hidden>Sinal de GPS fraco</p>'
        +'<section class="nav-card" role="alertdialog" aria-live="assertive" hidden><div class="nav-card-icon"></div><h2 class="nav-card-title"></h2><p class="nav-card-note"></p><div class="nav-card-actions"></div></section>';
      document.body.append(root);
      const $=s=>root.querySelector(s);
      ui={root,stage:$('.nav-stage'),rot:$('.nav-rot'),mapEl:$('.nav-map'),me:$('.nav-me'),icon:$('.nav-banner-icon'),dist:$('.nav-dist'),instr:$('.nav-instr'),then:$('.nav-then'),
        toast:$('.nav-toast'),eta:$('.nav-eta'),left:$('.nav-left'),stopLabel:$('.nav-stoplabel'),stopName:$('.nav-stopname'),attrib:$('.nav-attrib'),gps:$('.nav-gps'),
        card:$('.nav-card'),cardIcon:$('.nav-card-icon'),cardTitle:$('.nav-card-title'),cardNote:$('.nav-card-note'),cardActions:$('.nav-card-actions'),
        buttons:{voice:$('[data-act="voice"]'),orient:$('[data-act="orient"]'),base:$('[data-act="base"]'),speed:$('[data-act="speed"]'),skip:$('[data-act="skip"]'),overview:$('[data-act="overview"]')}};
      root.addEventListener('click',e=>{const b=e.target.closest('[data-act]');if(b)act(b.dataset.act);});
      return ui;
    }

    // ---------------------------------------------------------------- estado da navegação
    function createState(opts){
      return {simulate:!!opts.simulate,stops:[],route:null,leg:1,along:0,minAlong:0,reachedAlong:-1,heading:0,rotation:0,fix:null,lastFix:null,speed:0,
        followNorth:false,overview:false,voice:safeGet(VOICE_KEY)!=='0',zoomBias:0,said:{},deviation:{since:null},rerouting:false,lastReroute:0,finished:false,
        watch:null,timers:[],wake:null,navMap:null,layers:{},basemap:null,arrived:false,simSpeed:0,simAlong:0,simPause:false,token:0,pins:[]};
    }
    function safeGet(k){try{return localStorage.getItem(k);}catch(e){return null;}}
    function safeSet(k,v){try{localStorage.setItem(k,v);}catch(e){/* sem armazenamento */}}
    const later=(fn,ms)=>{const t=setTimeout(fn,ms);nav&&nav.timers.push(t);return t;};

    // ---------------------------------------------------------------- iniciar
    async function start(opts){
      if(active)return;
      const wanted=stops();
      if(!wanted.length)return;
      if(opts.simulate&&wanted.length<2){toast('Para simular, adicione pelo menos duas paradas.',4000,true);return;}
      active=true;nav=createState(opts);nav.stops=wanted.slice();
      build();paintStatic();
      document.documentElement.classList.add('atlas-nav-open');ui.root.classList.add('is-open');
      pushGuard();enterFullscreen();holdScreen();
      setupMap();layout();
      status('Preparando a rota…');
      try{
        const here=nav.simulate?{lat:wanted[0].lat,lng:wanted[0].lng,name:wanted[0].name}:await firstFix();
        if(!active)return;
        const destinations=nav.simulate?wanted.slice(1):wanted;
        await plan(here,destinations,true);
        if(!active)return;
        toast(nav.simulate?'Simulação: a rota é percorrida sozinha.':'Mantenha os olhos na via. Use com o veículo parado ao mexer na tela.',4500);
        begin();
      }catch(e){
        if(!active)return;
        showCard({title:e&&e.denied?'Sem acesso à localização':'Não foi possível iniciar',note:(e&&e.message)||'Tente novamente.',
          actions:[['Tentar de novo',()=>{const s=nav.simulate;exit(true);setTimeout(()=>start({simulate:s}),50);},true],['Simular',()=>{exit(true);setTimeout(()=>start({simulate:true}),50);}],['Sair',()=>exit()]]});
      }
    }

    function firstFix(){
      return new Promise((resolve,reject)=>{
        if(!navigator.geolocation){reject(Object.assign(new Error('Este aparelho não informa a localização. Use a simulação para testar.'),{denied:true}));return;}
        navigator.geolocation.getCurrentPosition(p=>resolve({lat:p.coords.latitude,lng:p.coords.longitude,name:'Você',accuracy:p.coords.accuracy}),err=>{
          reject(Object.assign(new Error(err.code===1?'A localização está bloqueada. Libere no navegador e tente de novo, ou use a simulação.':err.code===3?'O GPS demorou para responder. Tente ao ar livre.':'Não foi possível obter a posição agora.'),{denied:err.code===1}));
        },{enableHighAccuracy:true,timeout:20000,maximumAge:5000});
      });
    }

    // Calcula a rota a partir de `from` até as paradas restantes e monta as manobras.
    async function plan(from,destinations,first){
      const g=await graph();
      const places=[{lat:from.lat,lng:from.lng,name:from.name||'Você'},...destinations];
      const result=Route.plan(g,places);
      const route=Nav.buildRoute(g,result.legs,places.map((p,k)=>({lat:p.lat,lng:p.lng,name:k===0?(from.name||'Você'):p.name})));
      nav.route=route;nav.stopsLeft=destinations;nav.leg=1;nav.along=0;nav.minAlong=0;nav.said={};nav.deviation={since:null};nav.arrived=false;
      nav.heading=route.maneuvers[0]?route.maneuvers[0].heading:0;
      if(first||!nav.rotationSet){nav.rotation=Nav.unwrap(nav.rotation||0,nav.heading);nav.rotationSet=true;}
      nav.simAlong=0;
      drawRoute();
      if(!result.connected)toast('Parte da rota não segue ruas mapeadas e aparece em linha reta.',5000,true);
    }

    function begin(){
      status('');
      if(nav.simulate){ui.buttons.speed.hidden=false;paintSpeed();nav.timers.push(setInterval(simTick,500));simTick();}
      else if(navigator.geolocation){
        nav.watch=navigator.geolocation.watchPosition(p=>onFix({lat:p.coords.latitude,lng:p.coords.longitude,accuracy:p.coords.accuracy,speed:p.coords.speed,heading:p.coords.heading,t:Date.now()}),
          err=>{ui.gps.hidden=false;ui.gps.textContent=err.code===1?'Localização bloqueada':'Sinal de GPS fraco';},{enableHighAccuracy:true,maximumAge:1000,timeout:30000});
        // Primeira posição imediata (a que já temos), antes do primeiro aviso do watch.
        if(nav.route)onFix({lat:nav.route.points[0][0],lng:nav.route.points[0][1],accuracy:10,speed:0,heading:null,t:Date.now()});
      }
      speak('Navegação iniciada. '+Nav.describe(nav.route.maneuvers[0]||{type:'depart'})+'.');
    }

    // ---------------------------------------------------------------- simulação
    function simTick(){
      if(!nav||!nav.route||nav.finished||nav.simPause)return;
      const route=nav.route,speed=SIM_SPEEDS[nav.simSpeed]||Route.SPEEDS[mode()==='motor'?'motor':'foot']/3.6;
      let next=nav.simAlong+speed*0.5;
      const stopAt=route.stopAlong[nav.leg];
      if(stopAt!==undefined&&next>=stopAt){next=stopAt;}
      nav.simAlong=Math.min(next,route.total);
      const p=Nav.walkAlong(route,nav.simAlong);
      onFix({lat:p.lat,lng:p.lng,accuracy:5,speed,heading:p.heading,t:Date.now()});
    }

    // ---------------------------------------------------------------- a cada posição
    function onFix(fix){
      if(!active||!nav||!nav.route||nav.finished)return;
      if(fix.accuracy>120&&nav.fix){ui.gps.hidden=false;ui.gps.textContent='Sinal de GPS fraco';return;}
      ui.gps.hidden=fix.accuracy<=60;if(fix.accuracy>60)ui.gps.textContent='Sinal de GPS fraco';
      // Direção: a do aparelho quando está andando; senão, a do deslocamento entre posições.
      const moving=nav.simulate||(Number.isFinite(fix.speed)&&fix.speed>=1.2);
      let heading=null;
      if(moving&&Number.isFinite(fix.heading))heading=fix.heading;
      else if(moving||!Number.isFinite(fix.speed))heading=Nav.headingFromFixes(nav.lastFix,fix,5);   // sem rumo do aparelho: pelo deslocamento
      if(heading!==null){nav.heading=Nav.smoothAngle(nav.heading,heading,nav.simulate?0.6:0.4);nav.lastFix=fix;}
      else if(!nav.lastFix)nav.lastFix=fix;                                                           // parado: o mapa não gira
      nav.fix=fix;nav.speed=Number.isFinite(fix.speed)?fix.speed:nav.speed;

      const here=Nav.locate(nav.route,fix.lat,fix.lng,nav.along,{minAlong:nav.minAlong,heading:moving?nav.heading:null});
      const dev=Nav.trackDeviation(nav.deviation,here.offRoute,fix.t);
      nav.deviation=dev.state;
      if(dev.reroute&&!nav.simulate&&!nav.rerouting){reroute();return;}
      clearTimeout(nav.devTimer);
      if(dev.off&&!nav.simulate){
        // Fora da rota: reavalia depois do prazo mesmo que o GPS não mande outra leitura (sinal fraco).
        const wait=Math.max(300,Nav.OFF_SECONDS*1000-(fix.t-nav.deviation.since)+50);
        nav.devTimer=later(()=>{if(active&&nav&&nav.fix&&!nav.rerouting)onFix({...nav.fix,t:Date.now()});},wait);
      }
      if(!dev.off)nav.along=here.along;

      // Chegada à parada atual.
      const stopPlace=nav.route.stops[nav.leg];
      const toStop=Route.distance(fix.lat,fix.lng,stopPlace.lat,stopPlace.lng);
      const remainingToStop=nav.route.stopAlong[nav.leg]-nav.along;
      if(!nav.arrived&&(toStop<=Nav.ARRIVE_METERS||(remainingToStop<=8&&here.offRoute<=Nav.OFF_METERS&&toStop<=60)))return arrive();
      if(nav.arrived)return;
      render(dev.off);
    }

    // ---------------------------------------------------------------- chegada às paradas
    function arrive(){
      const route=nav.route,k=nav.leg,place=route.stops[k],final=k===route.stopAlong.length-1;
      nav.arrived=true;nav.along=Math.max(nav.along,route.stopAlong[k]-Nav.ARRIVE_METERS);
      nav.minAlong=route.stopAlong[k]-(Nav.ARRIVE_METERS+5);          // não volta para antes da parada
      nav.simPause=true;
      speak(Nav.spoken({type:'arrive',name:place.name,final},0,'near'));
      render(false);
      if(final){
        nav.finished=true;stopSources();
        const total=Math.round(route.total);
        showCard({type:'arrive',title:'Rota concluída',note:(place.name?place.name+'. ':'')+'Distância percorrida: '+Route.formatDistance(total)+'.',
          actions:[['Fechar',()=>exit(),true]]});
      }else{
        const following=route.stops[k+1];
        showCard({type:'arrive',title:'Você chegou',note:(place.name||'Parada '+k)+(following?' · próxima: '+(following.name||'parada '+(k+1)):''),
          actions:[['Seguir para a próxima parada',goNext,true],['Encerrar',()=>exit()]]});
        if(nav.simulate)later(()=>{if(active&&nav&&nav.arrived&&!nav.finished)goNext();},3500);
      }
    }
    function goNext(){
      if(!nav||nav.finished||!nav.arrived)return;
      hideCard();nav.arrived=false;nav.simPause=false;nav.leg++;nav.said={};
      speak('Seguindo para '+(nav.route.stops[nav.leg].name||'a próxima parada')+'.');
      render(false);
    }

    // ---------------------------------------------------------------- recálculo e pular parada
    async function reroute(skip){
      if(nav.rerouting||!nav.fix||Date.now()-nav.lastReroute<8000&&!skip)return;
      nav.rerouting=true;nav.lastReroute=Date.now();
      toast('Recalculando a rota…',0);speak('Recalculando.');
      const mine=++nav.token;
      try{
        const route=nav.route;
        let remaining=route.stops.slice(nav.leg).filter(Boolean);
        if(skip)remaining=remaining.slice(1);
        if(!remaining.length){exit();return;}
        const spot={lat:nav.fix.lat,lng:nav.fix.lng,name:'Você'};
        await plan(spot,remaining.map(s=>({lat:s.lat,lng:s.lng,name:s.name})),false);
        if(mine!==nav.token||!active)return;
        hideToast();
      }catch(e){toast('Não foi possível recalcular agora.',4000,true);}
      finally{if(nav)nav.rerouting=false;}
    }

    // ---------------------------------------------------------------- mapa
    function setupMap(){
      nav.navMap=L.map(ui.mapEl,{zoomControl:false,attributionControl:false,dragging:false,touchZoom:false,doubleClickZoom:false,scrollWheelZoom:false,boxZoom:false,keyboard:false,
        zoomSnap:0.25,zoomAnimation:true,fadeAnimation:true,markerZoomAnimation:true,minZoom:12,maxZoom:21,inertia:false});
      nav.basemap=window.SfaMapLayers.attach(nav.navMap,{mode:'streets'});
      nav.navMap.setView(map.getCenter(),17,{animate:false});
      nav.layers.route=L.layerGroup().addTo(nav.navMap);nav.layers.pins=L.layerGroup().addTo(nav.navMap);
      paintBase();
    }
    function drawRoute(){
      const L_=nav.layers,route=nav.route;
      L_.route.clearLayers();L_.pins.clearLayers();
      nav.casing=L.polyline(route.points,{color:'#fff',weight:15,opacity:1,lineCap:'round',lineJoin:'round',interactive:false}).addTo(L_.route);
      nav.done=L.polyline([],{color:'#9aa9ad',weight:9,opacity:.9,lineCap:'round',lineJoin:'round',interactive:false}).addTo(L_.route);
      nav.line=L.polyline(route.points,{color:'#1c7ed6',weight:9,opacity:1,lineCap:'round',lineJoin:'round',interactive:false}).addTo(L_.route);
      route.stops.forEach((s,k)=>{
        if(k===0)return;
        const div=L.divIcon({className:'nav-pin',html:'<span class="nav-pin-in"><b>'+k+'</b></span>',iconSize:[34,34],iconAnchor:[17,17]});
        L.marker([s.lat,s.lng],{icon:div,interactive:false,keyboard:false}).addTo(L_.pins);
      });
      nav.pinEls=null;
    }
    // Pinos e rótulos se contragiram: o texto fica de pé mesmo com o mapa girado.
    function setRotation(deg){ui.root.style.setProperty('--nav-rot',deg+'deg');ui.rot.style.transform='rotate('+(-deg)+'deg)';}

    function layout(){
      if(!ui)return;
      const w=ui.stage.clientWidth||window.innerWidth,h=ui.stage.clientHeight||window.innerHeight,d=Math.ceil(Math.hypot(w,h))+160;
      Object.assign(ui.rot.style,{width:d+'px',height:d+'px',left:((w-d)/2)+'px',top:((h-d)/2)+'px'});
      // Quanto a seta fica abaixo do centro: no terço de baixo, mas sempre acima da barra de chegada
      // (em paisagem a tela é baixa e a barra ocuparia o lugar da seta).
      const bar=ui.root.querySelector('.nav-bar'),barHeight=bar?bar.offsetHeight:110;
      nav.shift=Math.max(0,Math.min(Math.round(h*0.22),Math.round(h/2-barHeight-38)));
      ui.me.style.top='calc(50% + '+nav.shift+'px)';
      nav.navMap&&nav.navMap.invalidateSize({animate:false});
      if(nav.fix)follow(true);
    }

    function zoomFor(){
      const speed=nav.speed||0,near=nav.route&&Nav.progress(nav.route,nav.along).nextDistance;
      let z=speed<2.5?18.5:speed<9?17.75:speed<18?17:16.5;
      if(near!==undefined&&near<90)z+=0.5;
      return Math.max(13,Math.min(20,z+nav.zoomBias));
    }
    // Centraliza adiante da posição, para a seta ficar no terço de baixo. Gira o mapa para o rumo.
    function follow(force){
      if(!nav.navMap||!nav.fix||nav.overview)return;
      const zoom=zoomFor(),lat=nav.fix.lat,lng=nav.fix.lng;
      const ahead=nav.followNorth?{lat,lng}:Nav.offset(lat,lng,nav.heading,nav.shift*mpp(zoom,lat));
      const target=nav.followNorth?Nav.unwrap(nav.rotation,0):Nav.unwrap(nav.rotation,nav.heading);
      nav.rotation=target;setRotation(nav.followNorth?0:target);
      ui.me.style.transform=nav.followNorth?'translate(-50%,-50%) rotate('+Math.round(nav.heading)+'deg)':'translate(-50%,-50%)';
      if(force||Math.abs(nav.navMap.getZoom()-zoom)>0.2)nav.navMap.setView([ahead.lat,ahead.lng],zoom,{animate:!force,duration:0.8});
      else nav.navMap.panTo([ahead.lat,ahead.lng],{animate:true,duration:0.9,easeLinearity:1,noMoveStart:true});
    }

    // ---------------------------------------------------------------- painel
    function render(off){
      if(!nav||!nav.route)return;
      const route=nav.route,p=Nav.progress(route,nav.along),m=p.next,k=nav.leg,place=route.stops[k];
      // Linha percorrida em cinza; o resto, em azul.
      let idx=route.cum.findIndex(c=>c>nav.along);
      if(idx<0)idx=route.points.length;
      nav.done.setLatLngs(route.points.slice(0,Math.max(1,idx)).concat([[nav.fix.lat,nav.fix.lng]]));
      nav.line.setLatLngs([[nav.fix.lat,nav.fix.lng]].concat(route.points.slice(idx)));
      if(nav.arrived){setBanner('arrive','Chegou',Nav.describe({type:'arrive',final:k===route.stopAlong.length-1,name:place&&place.name}),'');}
      else if(off){setBanner('straight','—','Fora da rota',''); }
      else if(m){
        const text=Nav.describe(m);
        setBanner(m.type==='depart'?'straight':m.type,Route.formatDistance(p.nextDistance),text,(function(){const after=route.maneuvers[p.nextIndex+1];return after&&after.type!=='arrive'&&after.along-m.along<150?'Depois: '+Nav.describe(after).replace(/^./,c=>c.toLowerCase()):'';})());
        voice(m,p.nextDistance,'m'+Math.round(m.along)+'-'+nav.token);
      }else setBanner('arrive','',Nav.describe({type:'arrive',final:true,name:place&&place.name}),'');
      const left=p.remaining,minutes=Route.minutes(left,mode());
      ui.eta.textContent=clock(minutes*60000)+' · '+Route.formatDuration(minutes);
      ui.left.textContent=Route.formatDistance(left);
      ui.stopLabel.textContent='Parada '+k+' de '+(route.stopAlong.length-1)+(nav.arrived?' · chegou':' · '+Route.formatDistance(p.toStop));
      ui.stopName.textContent=place&&place.name||'';
      ui.buttons.skip.hidden=k===route.stopAlong.length-1;
      follow(false);
    }
    function setBanner(type,dist,text,then){
      ui.icon.innerHTML=icon(type);ui.dist.textContent=dist;ui.instr.textContent=text;ui.then.textContent=then||'';ui.then.hidden=!then;
    }
    function voice(m,distance,key){
      const phase=Nav.shouldSpeak(nav.said,key,distance,nav.speed||(mode()==='motor'?6:1.4));
      if(phase)speak(Nav.spoken(m,distance,phase));
    }
    function paintStatic(){paintVoice();paintOrient();paintAttrib();ui.stopLabel.textContent='';}
    function paintVoice(){const on=nav.voice;ui.buttons.voice.textContent=on?'🔊':'🔇';ui.buttons.voice.setAttribute('aria-label',on?'Voz ligada':'Voz desligada');ui.buttons.voice.setAttribute('aria-pressed',String(on));}
    function paintOrient(){ui.buttons.orient.textContent=nav.followNorth?'N↑':'↑';ui.buttons.orient.setAttribute('aria-label',nav.followNorth?'Norte para cima':'Mapa gira com a direção');ui.buttons.orient.setAttribute('aria-pressed',String(!nav.followNorth));}
    function paintBase(){
      const mode_=nav.basemap&&nav.basemap.getMode(),sat=mode_==='satellite';
      ui.buttons.base.textContent=sat?'🗺️':'🛰️';                       // mostra o que o toque vai ativar
      ui.buttons.base.setAttribute('aria-label',sat?'Mudar para mapa de ruas':'Mudar para satélite');ui.buttons.base.title=sat?'Mapa de ruas':'Satélite';
      ui.attrib.textContent=ATTRIB[mode_]||ATTRIB.streets;
    }
    function paintAttrib(){ui.attrib.textContent=ATTRIB.streets;}
    function paintSpeed(){const v=SIM_SPEEDS[nav.simSpeed];ui.buttons.speed.textContent=v?Math.round(v*3.6)+' km/h':'×1';}

    // ---------------------------------------------------------------- avisos, cartões, voz
    let toastTimer=null;
    function toast(text,ms,error){ui.toast.textContent=text;ui.toast.hidden=false;ui.toast.classList.toggle('is-error',!!error);clearTimeout(toastTimer);if(ms)toastTimer=setTimeout(hideToast,ms);}
    function hideToast(){if(ui)ui.toast.hidden=true;}
    function status(text){if(text)toast(text,0);else hideToast();}
    function showCard({type,title,note,actions}){
      ui.cardIcon.innerHTML=type==='arrive'?'<span>'+icon('arrive')+'</span>':'';ui.cardIcon.hidden=type!=='arrive';
      ui.cardTitle.textContent=title;ui.cardNote.textContent=note||'';ui.cardActions.replaceChildren();
      actions.forEach(([label,fn,primary])=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.className=primary?'is-primary':'';b.onclick=fn;ui.cardActions.append(b);});
      ui.card.hidden=false;const first=ui.cardActions.querySelector('button');first&&first.focus({preventScroll:true});
    }
    function hideCard(){ui.card.hidden=true;}
    function speak(text){
      if(!nav||!nav.voice||!('speechSynthesis' in window)||!text)return;
      try{window.speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);u.lang='pt-BR';u.rate=1;window.speechSynthesis.speak(u);}catch(e){/* voz indisponível */}
    }

    // ---------------------------------------------------------------- botões
    function act(name){
      if(!nav)return;
      switch(name){
        case 'voice':nav.voice=!nav.voice;safeSet(VOICE_KEY,nav.voice?'1':'0');paintVoice();if(!nav.voice&&'speechSynthesis' in window)window.speechSynthesis.cancel();else speak('Voz ligada.');break;
        case 'orient':nav.followNorth=!nav.followNorth;paintOrient();follow(true);break;
        case 'base':nav.basemap.setMode(nav.basemap.getMode()==='satellite'?'streets':'satellite');paintBase();break;
        case 'zoom-in':nav.zoomBias=Math.min(3,nav.zoomBias+0.5);follow(true);break;
        case 'zoom-out':nav.zoomBias=Math.max(-3,nav.zoomBias-0.5);follow(true);break;
        case 'speed':nav.simSpeed=(nav.simSpeed+1)%SIM_SPEEDS.length;paintSpeed();break;
        case 'overview':overview();break;
        case 'skip':reroute(true);break;
        case 'exit':askExit();break;
      }
    }
    function overview(){
      nav.overview=!nav.overview;ui.buttons.overview.classList.toggle('is-on',nav.overview);
      if(nav.overview){setRotation(0);nav.navMap.fitBounds(L.latLngBounds(nav.route.points),{padding:[70,70],animate:true});}
      else follow(true);
    }
    function askExit(){
      if(!ui.card.hidden&&nav.finished){exit();return;}
      showCard({title:'Encerrar a navegação?',note:'A rota continua salva no painel.',actions:[['Continuar',()=>{hideCard();if(nav.arrived&&!nav.finished)showArrivalAgain();},true],['Encerrar',()=>exit()]]});
    }
    function showArrivalAgain(){const route=nav.route,k=nav.leg,place=route.stops[k];showCard({type:'arrive',title:'Você chegou',note:place.name||'',actions:[['Seguir para a próxima parada',goNext,true],['Encerrar',()=>exit()]]});}

    // ---------------------------------------------------------------- tela cheia, tela ligada, botão voltar
    function enterFullscreen(){
      const el=ui.root;
      try{const r=el.requestFullscreen||el.webkitRequestFullscreen;if(r)Promise.resolve(r.call(el,{navigationUI:'hide'})).catch(()=>{});}catch(e){/* sem tela cheia: a sobreposição já cobre a tela */}
    }
    function leaveFullscreen(){
      try{if(document.fullscreenElement&&document.exitFullscreen)Promise.resolve(document.exitFullscreen()).catch(()=>{});}catch(e){/* nada */}
    }
    async function holdScreen(){
      try{if('wakeLock' in navigator&&nav&&!nav.wake)nav.wake=await navigator.wakeLock.request('screen');}catch(e){/* sem bloqueio de tela: segue */}
    }
    let guarded=false;
    function pushGuard(){try{history.pushState({atlasNav:1},'');guarded=true;}catch(e){guarded=false;}}
    window.addEventListener('popstate',()=>{
      if(!active)return;
      guarded=false;pushGuard();                      // o "voltar" do celular pergunta, em vez de sair
      if(ui.card.hidden)askExit();
    });
    document.addEventListener('visibilitychange',()=>{if(active&&document.visibilityState==='visible'){if(nav.wake){try{nav.wake.release();}catch(e){/* já liberado */}nav.wake=null;}holdScreen();}});
    window.addEventListener('resize',()=>{if(active)setTimeout(layout,120);});
    window.addEventListener('orientationchange',()=>{if(active)setTimeout(layout,350);});
    document.addEventListener('keydown',e=>{if(active&&e.key==='Escape'){e.preventDefault();askExit();}});

    // ---------------------------------------------------------------- encerrar
    function stopSources(){
      if(!nav)return;
      if(nav.watch!==null&&navigator.geolocation){try{navigator.geolocation.clearWatch(nav.watch);}catch(e){/* nada */}nav.watch=null;}
      nav.timers.forEach(t=>{clearTimeout(t);clearInterval(t);});nav.timers=[];
    }
    function exit(silent){
      if(!active)return;
      active=false;stopSources();
      if(nav.wake){try{nav.wake.release();}catch(e){/* nada */}}
      if('speechSynthesis' in window){try{window.speechSynthesis.cancel();}catch(e){/* nada */}}
      leaveFullscreen();
      try{nav.navMap&&nav.navMap.remove();}catch(e){/* mapa já removido */}
      ui.root.remove();document.documentElement.classList.remove('atlas-nav-open');
      if(guarded){guarded=false;try{history.back();}catch(e){/* nada */}}
      const done=nav&&nav.finished;
      nav=null;ui=null;
      if(!silent&&onExit)onExit({finished:!!done});
    }

    const api={start,exit,get active(){return active;},
      // Só para testes e depuração: estado interno e uma posição simulada.
      _state:()=>nav,_fix:onFix};
    window.SfaAtlasNav.last=api;
    return api;
  }};
})();
