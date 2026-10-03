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
  const VOICE_KEY='sfa-nav-voice', THEME_KEY='sfa-nav-theme', HINT_KEY='sfa-nav-gesture-hint', SIM_SPEEDS=[null,10,25];             // m/s; null = velocidade do modo escolhido
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
    const Route=window.SfaAtlasRouteModel,Nav=window.SfaAtlasNavModel,Session=window.SfaAtlasNavSession;
    if(!Route||!Nav||!Session||!window.L)return {start(){},saved(){return null;},discard(){},statusOf(){return null;},get active(){return false;}};
    let ui=null,nav=null,active=false;
    const store=()=>{try{return window.sessionStorage;}catch(e){return null;}};
    const keyed=list=>list.map(s=>({...s,key:Session.stopKey(s)}));
    // Progresso guardado na aba para as paradas atuais (ou nada).
    function saved(){
      const st=store(),session=st&&Session.load(st,Date.now());
      if(!session)return null;
      const list=keyed(stops());
      return Session.resumable(list,session)?{session,stops:list,label:Session.progressLabel(list,session),pending:Session.pending(list,session).length}:null;
    }
    function discard(){const st=store();if(st)Session.clear(st);}
    function statusOf(stop){const st=store(),session=st&&Session.load(st,Date.now());return session&&stop?Session.statusOf(session,stop):null;}

    const clock=ms=>new Date(Date.now()+ms).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
    const mpp=(zoom,lat)=>156543.03392*Math.cos(lat*Math.PI/180)/Math.pow(2,zoom);

    // ---------------------------------------------------------------- construção da tela
    function build(){
      const root=document.createElement('div');root.className='atlas-nav';root.setAttribute('role','dialog');root.setAttribute('aria-modal','true');root.setAttribute('aria-label','Navegação');
      root.innerHTML=
        '<div class="nav-stage"><div class="nav-rot"><div class="nav-map"></div></div>'
        +'<div class="nav-me" aria-hidden="true">'+ME+'</div></div>'
        +'<header class="nav-banner" aria-live="off"><span class="nav-banner-icon"></span><div class="nav-banner-text"><strong class="nav-dist"></strong><span class="nav-instr"></span><small class="nav-then"></small></div><div class="nav-approach" aria-hidden="true"><i></i></div></header>'
        +'<p class="nav-toast" role="status" hidden></p>'
        +'<div class="nav-tools" role="group" aria-label="Controles do mapa">'
        +'<button type="button" data-act="voice" aria-label="Voz ligada" title="Voz"></button>'
        +'<button type="button" data-act="orient" title="Girar o mapa ou manter o norte para cima"></button>'
        +'<button type="button" data-act="base" title="Mapa de ruas ou satélite"></button>'
        +'<button type="button" data-act="theme" title="Tema do mapa: automático, noite ou dia"></button>'
        +'<button type="button" data-act="overview" aria-label="Ver a rota inteira" title="Ver a rota inteira">🧭</button>'
        +'<button type="button" data-act="speed" hidden title="Velocidade da simulação"></button></div>'
        +'<div class="nav-zoom" role="group" aria-label="Zoom do mapa"><button type="button" class="nav-zoom-auto" data-act="zoom-auto" hidden title="Voltar ao zoom automático">Auto</button>'
        +'<div class="nav-zoom-pair"><button type="button" data-act="zoom-in" aria-label="Aproximar o mapa">＋</button><button type="button" data-act="zoom-out" aria-label="Afastar o mapa">－</button></div></div>'
        +'<button type="button" class="nav-recenter" data-act="recenter" hidden><span aria-hidden="true">◎</span> Recentralizar</button>'
        +'<footer class="nav-bar"><div class="nav-next"><small class="nav-stoplabel"></small><strong class="nav-stopname"></strong><span class="nav-stopnote"></span></div>'
        +'<div class="nav-stats"><strong class="nav-eta"></strong><span class="nav-left"></span></div>'
        +'<div class="nav-bar-actions"><button type="button" class="nav-here" data-act="here" title="Marcar que já chegou a esta parada">Cheguei</button><button type="button" data-act="skip" title="Pular esta parada e recalcular">Pular</button><button type="button" class="nav-exit" data-act="exit">Sair</button></div></footer>'
        +'<p class="nav-attrib"></p><p class="nav-gps" hidden>Sinal de GPS fraco</p>'
        +'<section class="nav-card" role="alertdialog" aria-live="assertive" hidden><div class="nav-card-icon"></div><p class="nav-card-eyebrow" hidden></p><h2 class="nav-card-title"></h2><p class="nav-card-note"></p><div class="nav-dots" aria-hidden="true" hidden></div><div class="nav-card-stats" hidden></div><div class="nav-card-actions"></div></section>';
      document.body.append(root);
      const $=s=>root.querySelector(s);
      ui={root,stage:$('.nav-stage'),rot:$('.nav-rot'),mapEl:$('.nav-map'),me:$('.nav-me'),icon:$('.nav-banner-icon'),dist:$('.nav-dist'),instr:$('.nav-instr'),then:$('.nav-then'),
        toast:$('.nav-toast'),eta:$('.nav-eta'),left:$('.nav-left'),stopLabel:$('.nav-stoplabel'),stopName:$('.nav-stopname'),stopNote:$('.nav-stopnote'),attrib:$('.nav-attrib'),gps:$('.nav-gps'),
        approach:$('.nav-approach i'),bar:$('.nav-bar'),
        card:$('.nav-card'),cardIcon:$('.nav-card-icon'),cardEyebrow:$('.nav-card-eyebrow'),cardTitle:$('.nav-card-title'),cardNote:$('.nav-card-note'),cardDots:$('.nav-dots'),cardStats:$('.nav-card-stats'),cardActions:$('.nav-card-actions'),
        buttons:{voice:$('[data-act="voice"]'),orient:$('[data-act="orient"]'),base:$('[data-act="base"]'),theme:$('[data-act="theme"]'),speed:$('[data-act="speed"]'),skip:$('[data-act="skip"]'),here:$('[data-act="here"]'),overview:$('[data-act="overview"]'),zoomAuto:$('[data-act="zoom-auto"]'),recenter:$('[data-act="recenter"]')}};
      root.addEventListener('click',e=>{const b=e.target.closest('[data-act]');if(b)act(b.dataset.act);});
      gestures(ui.stage);
      return ui;
    }

    // ---------------------------------------------------------------- gestos no mapa
    // Um dedo arrasta; dois dedos aproximam/afastam e giram. Pinça simples só muda o zoom e continua seguindo a posição;
    // arrastar ou girar solta o mapa ("livre") até tocar em Recentralizar (ou 20 s sem tocar).
    const isFree=()=>!!(nav&&(nav.free||nav.overview));
    function gestures(el){
      const pts=new Map();let g=null;
      const at=e=>({x:e.clientX,y:e.clientY}),pair=()=>[...pts.values()];
      const dist=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y)||1,mid=(a,b)=>({x:(a.x+b.x)/2,y:(a.y+b.y)/2});
      function begin(){
        if(!nav||!nav.navMap)return;
        clearTimeout(nav.freeTimer);ui.root.classList.add('is-gesture');
        if(pts.size===1)g={kind:'pan',last:pair()[0],moved:0};
        else if(pts.size>=2){const [a,b]=pair();g={kind:'two',d:dist(a,b),ang:Session.fingerAngle(a,b),prevAng:Session.fingerAngle(a,b),twist:0,mid:mid(a,b),rot:nav.rotation,bias:nav.zoomBias,zoom:nav.navMap.getZoom(),free:isFree()};}
      }
      el.addEventListener('pointerdown',e=>{
        if(!nav)return;pts.set(e.pointerId,at(e));try{el.setPointerCapture(e.pointerId);}catch(err){/* ponteiro sintético ou já solto */}
        begin();
      });
      el.addEventListener('pointermove',e=>{
        if(!pts.has(e.pointerId)||!nav||!g)return;pts.set(e.pointerId,at(e));
        if(g.kind==='pan'&&pts.size===1){
          const p=at(e),dx=p.x-g.last.x,dy=p.y-g.last.y;g.last=p;g.moved+=Math.hypot(dx,dy);
          if(g.moved<8&&!isFree())return;                                   // um toque não solta o mapa
          enterFree();
          const [mx,my]=Session.screenToMap(dx,dy,nav.rotation);nav.navMap.panBy([-mx,-my],{animate:false});
        }else if(g.kind==='two'&&pts.size>=2){
          const [a,b]=pair(),d=dist(a,b),ang=Session.fingerAngle(a,b),m=mid(a,b);
          g.twist+=Session.angleDelta(g.prevAng,ang);g.prevAng=ang;
          if(!g.free&&Math.abs(g.twist)>10){enterFree();g.free=true;g.zoom=nav.navMap.getZoom();g.d=d;g.rot=nav.rotation;g.mid=m;}
          if(g.free){
            nav.rotation=Session.gestureRotation(g.rot,g.twist);setRotation(nav.rotation);
            nav.navMap.setZoom(Session.gestureZoom(g.zoom,d/g.d),{animate:false});
            const [mx,my]=Session.screenToMap(m.x-g.mid.x,m.y-g.mid.y,nav.rotation);g.mid=m;nav.navMap.panBy([-mx,-my],{animate:false});
          }else{
            nav.zoomBias=Session.pinchBias(g.bias,d/g.d);
            if(!nav.pinchRaf)nav.pinchRaf=requestAnimationFrame(()=>{if(!nav)return;nav.pinchRaf=0;follow(true);});
          }
        }
      });
      const end=e=>{
        if(!pts.delete(e.pointerId))return;
        if(pts.size===0){g=null;if(ui)ui.root.classList.remove('is-gesture');if(nav){paintZoom();touched();}}
        else if(pts.size===1)g={kind:'pan',last:pair()[0],moved:isFree()?99:0};   // um dedo levantou: continua arrastando com o outro
      };
      ['pointerup','pointercancel','lostpointercapture'].forEach(t=>el.addEventListener(t,end));
    }
    // Mapa solto: a seta passa a ser um marcador no próprio mapa (a fixa só vale seguindo a posição).
    function syncMe(){
      if(!nav||!ui)return;
      if(isFree()){
        if(!nav.marker&&nav.fix){
          nav.marker=L.marker([nav.fix.lat,nav.fix.lng],{icon:L.divIcon({className:'nav-me-marker',html:'<span class="nav-me-pin">'+ME+'</span>',iconSize:[46,46],iconAnchor:[23,23]}),interactive:false,keyboard:false,zIndexOffset:1000}).addTo(nav.navMap);
        }
        ui.me.hidden=true;placeMarker();
      }else{
        if(nav.marker){nav.marker.remove();nav.marker=null;}
        ui.me.hidden=false;
      }
      ui.buttons.recenter.hidden=!isFree();
      ui.root.classList.toggle('is-free',isFree());
    }
    function placeMarker(){
      if(!nav||!nav.marker||!nav.fix)return;
      nav.marker.setLatLng([nav.fix.lat,nav.fix.lng]);
      const el=nav.marker.getElement(),pin=el&&el.firstChild;
      if(pin)pin.style.transform='rotate('+Math.round(nav.heading)+'deg)';
    }
    function enterFree(){
      if(nav.free)return;
      nav.free=true;nav.navMap.stop();syncMe();
      if(!safeGet(HINT_KEY)){safeSet(HINT_KEY,'1');toast('Arraste e gire com 2 dedos. Toque em Recentralizar para voltar.',4800);}
    }
    // Sem tocar por um tempo, o mapa volta sozinho (útil com o veículo em movimento). A visão geral fica até a pessoa sair dela.
    function touched(){
      clearTimeout(nav.freeTimer);
      if(nav.free&&!nav.overview)nav.freeTimer=setTimeout(()=>{if(active&&nav&&nav.free&&!nav.overview)recenter();},nav.freeIdleMs);
    }
    function recenter(){
      if(!nav||!ui)return;
      clearTimeout(nav.freeTimer);
      const was=isFree();
      nav.free=false;
      if(nav.overview){nav.overview=false;ui.buttons.overview.classList.remove('is-on');}
      syncMe();
      if(was&&nav.fix)follow(false);
    }
    function freeZoom(step){
      nav.navMap.setZoom(Session.gestureZoom(nav.navMap.getZoom(),Math.pow(2,step)),{animate:true});touched();
    }

    // ---------------------------------------------------------------- estado da navegação
    function createState(opts){
      return {simulate:!!opts.simulate,stops:[],route:null,leg:1,along:0,minAlong:0,reachedAlong:-1,heading:0,rotation:0,fix:null,lastFix:null,speed:0,
        followNorth:false,overview:false,voice:safeGet(VOICE_KEY)!=='0',zoomBias:0,said:{},deviation:{since:null},rerouting:false,lastReroute:0,finished:false,
        watch:null,timers:[],wake:null,navMap:null,layers:{},basemap:null,arrived:false,simSpeed:0,simAlong:0,simPause:false,token:0,pins:[],
        session:null,persist:!opts.simulate,order:[],undoInfo:null,lastPos:null,manualArrive:false,theme:safeGet(THEME_KEY)||'auto',pinchRaf:0,
        free:false,freeTimer:null,freeIdleMs:Session.FREE_IDLE_MS,marker:null};
    }
    function safeGet(k){try{return localStorage.getItem(k);}catch(e){return null;}}
    function safeSet(k,v){try{localStorage.setItem(k,v);}catch(e){/* sem armazenamento */}}
    const later=(fn,ms)=>{const t=setTimeout(fn,ms);nav&&nav.timers.push(t);return t;};
    function persist(){if(nav&&nav.persist){const st=store();if(st)Session.save(st,nav.session,Date.now());}}
    const numberOf=stop=>{const i=stop&&stop.key?nav.order.findIndex(o=>o.key===stop.key):-1;return i>=0?i+1:0;};

    // ---------------------------------------------------------------- iniciar
    async function start(opts){
      if(active)return;
      const all=keyed(stops());
      if(!all.length)return;
      if(opts.simulate&&all.length<2){alert('Para simular, adicione pelo menos duas paradas.');return;}
      // Continuar: só o que falta visitar, com o histórico de quem já foi atendido.
      let session=null,wanted=all;
      if(opts.resume&&!opts.simulate){const st=store();session=st&&Session.load(st,Date.now());if(session)wanted=Session.pending(all,session);}
      if(!session){session=Session.create(Date.now());}
      session.paused=false;
      if(!wanted.length)return;
      active=true;nav=createState(opts);nav.stops=wanted.slice();nav.session=session;
      nav.order=opts.simulate?all.slice(1):all;                 // numeração das paradas na rota inteira, mesmo depois de recalcular
      build();paintStatic();persist();
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
        toast(nav.simulate?'Simulação: a rota é percorrida sozinha.':(opts.resume?'Continuando de onde você parou.':'Mantenha os olhos na via. Use com o veículo parado ao mexer na tela.'),4500);
        begin();
      }catch(e){
        if(!active)return;
        showCard({title:e&&e.denied?'Sem acesso à localização':'Não foi possível iniciar',note:(e&&e.message)||'Tente novamente.',
          actions:[['Tentar de novo',()=>{const s=nav.simulate,again=!!opts.resume;exit(true);setTimeout(()=>start({simulate:s,resume:again}),50);},true],['Simular',()=>{exit(true);setTimeout(()=>start({simulate:true}),50);}],['Sair',()=>exit()]]});
      }
    }

    function firstFix(){
      return new Promise((resolve,reject)=>{
        if(!navigator.geolocation){reject(Object.assign(new Error('Este aparelho não informa a localização. Use a simulação para testar.'),{denied:true}));return;}
        // O navegador só conta o tempo depois de a pessoa responder ao pedido de permissão; se ela o ignorar, a tela ficaria presa.
        const guard=setTimeout(()=>reject(Object.assign(new Error('O aparelho não respondeu sobre a localização. Libere o acesso no navegador e tente de novo, ou use a simulação.'),{denied:false})),25000);
        navigator.geolocation.getCurrentPosition(p=>{clearTimeout(guard);resolve({lat:p.coords.latitude,lng:p.coords.longitude,name:'Você',accuracy:p.coords.accuracy});},err=>{
          clearTimeout(guard);
          reject(Object.assign(new Error(err.code===1?'A localização está bloqueada. Libere no navegador e tente de novo, ou use a simulação.':err.code===3?'O GPS demorou para responder. Tente ao ar livre.':'Não foi possível obter a posição agora.'),{denied:err.code===1}));
        },{enableHighAccuracy:true,timeout:20000,maximumAge:5000});
      });
    }

    // Calcula a rota a partir de `from` até as paradas restantes e monta as manobras.
    async function plan(from,destinations,first){
      const g=await graph();
      const places=[{lat:from.lat,lng:from.lng,name:from.name||'Você'},...destinations];
      const result=Route.plan(g,places);
      const route=Nav.buildRoute(g,result.legs,places.map((p,k)=>({lat:p.lat,lng:p.lng,name:k===0?(from.name||'Você'):p.name,note:p.note||'',key:p.key||null})));
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
      if(fix.accuracy<=50){
        if(nav.lastPos){const d=Route.distance(nav.lastPos.lat,nav.lastPos.lng,fix.lat,fix.lng);if(d>=3&&d<400)nav.session.traveled+=d;}
        nav.lastPos={lat:fix.lat,lng:fix.lng};
      }

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
      if(!nav.arrived&&(toStop<=Nav.ARRIVE_METERS||(remainingToStop<=8&&here.offRoute<=Nav.OFF_METERS&&toStop<=60)))return arrive(false);
      if(nav.arrived)return;
      render(dev.off);
    }

    // ---------------------------------------------------------------- chegada às paradas
    function arrive(manual){
      const route=nav.route,k=nav.leg,place=route.stops[k],final=k===route.stopAlong.length-1;
      recenter();
      nav.arrived=true;nav.manualArrive=!!manual;nav.before={along:nav.along,minAlong:nav.minAlong};
      nav.along=Math.max(nav.along,route.stopAlong[k]-Nav.ARRIVE_METERS);
      nav.minAlong=route.stopAlong[k]-(Nav.ARRIVE_METERS+5);          // não volta para antes da parada
      nav.simPause=true;
      speak(Nav.spoken({type:'arrive',name:place.name,final},0,'near'));
      render(false);
      showArrival();
      if(nav.simulate)later(()=>{if(active&&nav&&nav.arrived&&!nav.finished)resolve('done');},3500);
    }
    function dotsFor(current){
      return nav.order.map(o=>{
        const r=Session.statusOf(nav.session,o);
        const cls=o.key===current?'is-current':r==='done'?'is-done':r==='notfound'?'is-notfound':r==='skipped'?'is-skipped':'';
        return '<span class="nav-dot '+cls+'"></span>';
      }).join('');
    }
    function showArrival(){
      const route=nav.route,k=nav.leg,place=route.stops[k],final=k===route.stopAlong.length-1,following=route.stops[k+1];
      const n=numberOf(place)||k,total=nav.order.length||route.stopAlong.length-1;
      showCard({sheet:true,type:'arrive',eyebrow:'Parada '+n+' de '+total,title:place.name||('Parada '+n),
        note:[place.note,following?'Próxima: '+(following.name||'parada '+(n+1)):''].filter(Boolean).join(' · '),dots:dotsFor(place.key),
        actions:[[final?'✓ Concluir a rota':'✓ Concluída · seguir',()=>resolve('done'),true],['Não encontrei / sem acesso',()=>resolve('notfound')]]
          .concat(nav.manualArrive?[['Ainda não cheguei',unarrive,false,'ghost']]:[])});
    }
    // "Cheguei" apertado sem querer: volta ao ponto em que estava.
    function unarrive(){
      if(!nav||!nav.arrived||nav.finished)return;
      hideCard();nav.arrived=false;nav.simPause=false;nav.manualArrive=false;
      if(nav.before){nav.along=nav.before.along;nav.minAlong=nav.before.minAlong;}
      render(false);
    }
    // Resultado da parada atual. Fica registrado na aba (para continuar depois) e dá para desfazer por alguns segundos.
    function resolve(status){
      if(!nav||!nav.arrived||nav.finished)return;
      const route=nav.route,k=nav.leg,place=route.stops[k],final=k===route.stopAlong.length-1;
      Session.record(nav.session,place.key,status,Date.now());
      nav.undoInfo={status,key:place.key,stop:{lat:place.lat,lng:place.lng,name:place.name,note:place.note||'',key:place.key}};
      persist();
      if(final){finish();return;}
      hideCard();goNext();
      offerUndo(status==='done'?'Concluída':'Não encontrada',place.name);
    }
    function goNext(){
      if(!nav||nav.finished||!nav.arrived)return;
      hideCard();nav.arrived=false;nav.manualArrive=false;nav.simPause=false;nav.leg++;nav.said={};
      speak('Seguindo para '+(nav.route.stops[nav.leg].name||'a próxima parada')+'.');
      render(false);
    }
    function offerUndo(label,name){
      toast(label+(name?': '+name:''),8000,false,{label:'Desfazer',fn:undo});
    }
    async function undo(){
      const info=nav&&nav.undoInfo;if(!info||nav.finished)return;
      nav.undoInfo=null;hideToast();
      Session.undo(nav.session);persist();
      const route=nav.route,k=route.stops.findIndex((s,i)=>i>=1&&s&&s.key===info.key);
      if(info.status!=='skipped'&&k>=1&&k===nav.leg-1){
        nav.leg=k;nav.arrived=true;nav.manualArrive=false;nav.simPause=true;nav.said={};render(false);showArrival();return;
      }
      // A rota já foi recalculada sem essa parada: ela volta como a próxima.
      if(!nav.fix)return;
      nav.rerouting=true;toast('Recalculando a rota…',0);
      const mine=++nav.token;
      try{
        const remaining=[info.stop].concat(route.stops.slice(nav.leg).filter(Boolean).map(s=>({lat:s.lat,lng:s.lng,name:s.name,note:s.note||'',key:s.key})));
        await plan({lat:nav.fix.lat,lng:nav.fix.lng,name:'Você'},remaining,false);
        if(mine===nav.token&&active)hideToast();
      }catch(e){toast('Não foi possível desfazer agora.',4000,true);}
      finally{if(nav)nav.rerouting=false;}
    }
    function skipStop(){
      if(!nav||nav.finished||nav.arrived||nav.rerouting)return;
      const route=nav.route,place=route.stops[nav.leg];
      if(!place||nav.leg>=route.stopAlong.length-1)return;
      Session.record(nav.session,place.key,'skipped',Date.now());
      nav.undoInfo={status:'skipped',key:place.key,stop:{lat:place.lat,lng:place.lng,name:place.name,note:place.note||'',key:place.key}};
      persist();
      reroute(true).then(()=>{if(active&&nav&&nav.undoInfo)offerUndo('Pulada',place.name);});
    }
    function elapsedText(){
      const minutes=Math.max(1,Math.round((Date.now()-nav.session.startedAt)/60000));
      return minutes>=60?Math.floor(minutes/60)+' h '+String(minutes%60).padStart(2,'0')+' min':minutes+' min';
    }
    function finish(){
      nav.finished=true;stopSources();persist();hideToast();nav.undoInfo=null;
      const list=nav.order,c=Session.counts(list,nav.session),meta={distance:Route.formatDistance(Math.round(nav.session.traveled)),duration:elapsedText()};
      const open=list.filter(s=>Session.statusOf(nav.session,s)!=='done');
      showCard({sheet:true,type:'arrive',eyebrow:'Rota concluída',title:c.done+' de '+c.total+' paradas concluídas',
        note:open.length?'Ficaram de fora: '+open.slice(0,4).map(s=>s.name).join(', ')+(open.length>4?' e mais '+(open.length-4):'')+'.':'Tudo atendido. Bom trabalho!',
        stats:[['Concluídas',c.done],['Não encontradas',c.notfound],['Puladas',c.skipped],['Percurso',meta.distance],['Tempo',meta.duration]],dots:dotsFor(null),
        actions:[['Copiar resumo',()=>copySummary(meta)],['Fechar',()=>exit(),true]]});
    }
    async function copySummary(meta){
      const text=Session.summaryText(nav.order,nav.session,meta),b=ui.cardActions.querySelector('button');
      try{
        if(navigator.clipboard&&navigator.clipboard.writeText)await navigator.clipboard.writeText(text);
        else{const t=document.createElement('textarea');t.value=text;t.style.cssText='position:fixed;opacity:0';document.body.append(t);t.select();document.execCommand('copy');t.remove();}
        if(b){b.textContent='✓ Copiado';setTimeout(()=>{if(b.isConnected)b.textContent='Copiar resumo';},1600);}
      }catch(e){if(b)b.textContent='Não foi possível copiar';}
    }

    // ---------------------------------------------------------------- recálculo
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
        await plan(spot,remaining.map(s=>({lat:s.lat,lng:s.lng,name:s.name,note:s.note||'',key:s.key})),false);
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
        const n=numberOf(s)||k;
        const div=L.divIcon({className:'nav-pin',html:'<span class="nav-pin-in"><b>'+n+'</b></span>',iconSize:[34,34],iconAnchor:[17,17]});
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
      const barHeight=syncBar();
      nav.shift=Math.max(0,Math.min(Math.round(h*0.22),Math.round(h/2-barHeight-38)));
      ui.me.style.top='calc(50% + '+nav.shift+'px)';
      nav.navMap&&nav.navMap.invalidateSize({animate:false});
      if(nav.fix)follow(true);
    }

    // A barra de baixo muda de altura (nome longo, paisagem); o zoom e a atribuição se apoiam nela.
    function syncBar(){const h=ui.bar?ui.bar.offsetHeight:110;ui.root.style.setProperty('--nav-bar-h',h+'px');return h;}
    function zoomFor(){
      const near=nav.route&&Nav.progress(nav.route,nav.along).nextDistance;
      return Session.zoomFor(nav.speed||0,near,nav.zoomBias);
    }
    // Centraliza adiante da posição, para a seta ficar no terço de baixo. Gira o mapa para o rumo.
    function follow(force){
      if(!nav.navMap||!nav.fix||nav.overview||nav.free)return;
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
      const final=k===route.stopAlong.length-1;
      if(nav.arrived){setBanner('arrive','Chegou',Nav.describe({type:'arrive',final,name:place&&place.name}),'');setApproach(1);}
      else if(off){setBanner('straight','—','Fora da rota','');setApproach(0);}
      else if(m){
        const text=Nav.describe(m),after=route.maneuvers[p.nextIndex+1];
        const then=after&&after.type!=='arrive'&&after.along-m.along<150?{type:after.type,text:'Depois: '+Nav.describe(after).replace(/^./,c=>c.toLowerCase())}:null;
        setBanner(m.type==='depart'?'straight':m.type,Route.formatDistance(p.nextDistance),text,then);
        setApproach(Session.approach(p.nextDistance,nav.speed||(mode()==='motor'?6:1.4)));
        voice(m,p.nextDistance,'m'+Math.round(m.along)+'-'+nav.token);
      }else{setBanner('arrive','',Nav.describe({type:'arrive',final:true,name:place&&place.name}),'');setApproach(1);}
      const left=p.remaining,minutes=Route.minutes(left,mode());
      ui.eta.textContent=clock(minutes*60000)+' · '+Route.formatDuration(minutes);
      ui.left.textContent=Route.formatDistance(left);
      const n=numberOf(place)||k,total=nav.order.length||route.stopAlong.length-1;
      ui.stopLabel.textContent='Parada '+n+' de '+total+(nav.arrived?' · chegou':' · '+Route.formatDistance(p.toStop));
      ui.stopName.textContent=place&&place.name||'';
      ui.stopNote.textContent=place&&place.note||'';ui.stopNote.hidden=!(place&&place.note);
      ui.buttons.skip.hidden=final;ui.buttons.here.hidden=nav.arrived||nav.finished;
      syncBar();
      if(nav.marker)placeMarker();
      follow(false);
    }
    function setBanner(type,dist,text,then){
      ui.icon.innerHTML=icon(type);ui.dist.textContent=dist;ui.instr.textContent=text;
      if(then){ui.then.innerHTML='<span class="nav-then-icon">'+icon(then.type)+'</span>'+esc(then.text);ui.then.hidden=false;}
      else{ui.then.replaceChildren();ui.then.hidden=true;}
    }
    // Faixa sob o banner: enche conforme a manobra se aproxima.
    function setApproach(fraction){ui.approach.style.width=Math.round(fraction*100)+'%';}
    function voice(m,distance,key){
      const phase=Nav.shouldSpeak(nav.said,key,distance,nav.speed||(mode()==='motor'?6:1.4));
      if(phase)speak(Nav.spoken(m,distance,phase));
    }
    function paintStatic(){paintVoice();paintOrient();paintAttrib();paintTheme();paintZoom();applyTheme();ui.stopLabel.textContent='';}
    const THEME_LABEL={auto:'Tema automático',night:'Tema noite',day:'Tema dia'},THEME_ICON={auto:'🌗',night:'🌙',day:'☀️'};
    function paintTheme(){ui.buttons.theme.textContent=THEME_ICON[nav.theme];ui.buttons.theme.setAttribute('aria-label',THEME_LABEL[nav.theme]+'. Toque para mudar.');}
    function applyTheme(){
      if(!ui)return;
      ui.root.classList.toggle('is-night',Session.isNight(new Date(),nav.theme));
      if(!nav.themeTimer&&nav.theme==='auto')nav.themeTimer=setInterval(applyTheme,60000),nav.timers.push(nav.themeTimer);
    }
    function paintZoom(){ui.buttons.zoomAuto.hidden=!nav.zoomBias;}
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
    function toast(text,ms,error,action){
      ui.toast.textContent=text;
      if(action){const b=document.createElement('button');b.type='button';b.textContent=action.label;b.onclick=e=>{e.stopPropagation();action.fn();};ui.toast.append(b);}
      ui.toast.hidden=false;ui.toast.classList.toggle('is-error',!!error);ui.toast.classList.toggle('has-action',!!action);clearTimeout(toastTimer);if(ms)toastTimer=setTimeout(hideToast,ms);
    }
    function hideToast(){if(ui)ui.toast.hidden=true;}
    function status(text){if(text)toast(text,0);else hideToast();}
    function showCard({type,title,note,actions,sheet,eyebrow,dots,stats}){
      ui.card.classList.toggle('is-sheet',!!sheet);
      ui.cardIcon.innerHTML=type==='arrive'?'<span>'+icon('arrive')+'</span>':'';ui.cardIcon.hidden=type!=='arrive';
      ui.cardEyebrow.textContent=eyebrow||'';ui.cardEyebrow.hidden=!eyebrow;
      ui.cardTitle.textContent=title;ui.cardNote.textContent=note||'';ui.cardNote.hidden=!note;
      ui.cardDots.innerHTML=dots||'';ui.cardDots.hidden=!dots;
      ui.cardStats.innerHTML=(stats||[]).map(([label,value])=>'<div><strong>'+esc(value)+'</strong><span>'+esc(label)+'</span></div>').join('');ui.cardStats.hidden=!(stats&&stats.length);
      ui.cardActions.replaceChildren();
      actions.forEach(([label,fn,primary,variant])=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.className=(primary?'is-primary ':'')+(variant==='ghost'?'is-ghost':'');b.onclick=fn;ui.cardActions.append(b);});
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
        case 'zoom-in':if(isFree())freeZoom(0.5);else{nav.zoomBias=Session.stepBias(nav.zoomBias,0.5);paintZoom();follow(true);}break;
        case 'zoom-out':if(isFree())freeZoom(-0.5);else{nav.zoomBias=Session.stepBias(nav.zoomBias,-0.5);paintZoom();follow(true);}break;
        case 'recenter':recenter();break;
        case 'zoom-auto':nav.zoomBias=0;paintZoom();follow(true);break;
        case 'theme':nav.theme=Session.nextTheme(nav.theme);safeSet(THEME_KEY,nav.theme);paintTheme();applyTheme();toast(THEME_LABEL[nav.theme],1800);break;
        case 'here':if(!nav.arrived&&!nav.finished&&nav.fix)arrive(true);break;
        case 'speed':nav.simSpeed=(nav.simSpeed+1)%SIM_SPEEDS.length;paintSpeed();break;
        case 'overview':overview();break;
        case 'skip':skipStop();break;
        case 'exit':askExit();break;
      }
    }
    function overview(){
      clearTimeout(nav.freeTimer);
      nav.overview=!nav.overview;ui.buttons.overview.classList.toggle('is-on',nav.overview);
      if(nav.overview){nav.free=false;nav.rotation=0;setRotation(0);nav.navMap.fitBounds(L.latLngBounds(nav.route.points),{padding:[70,70],animate:true});syncMe();}
      else{syncMe();follow(true);}
    }
    function askExit(){
      if(!ui.card.hidden&&nav.finished){exit();return;}
      const back=()=>{hideCard();if(nav.arrived&&!nav.finished)showArrival();};
      const actions=[['Continuar',back,true]];
      if(nav.persist)actions.push(['Sair e continuar depois',()=>{nav.session.paused=true;persist();exit();}]);
      actions.push([nav.persist?'Encerrar e descartar':'Encerrar',()=>{if(nav.persist)discard();exit();},false,'ghost']);
      showCard({title:'Sair da navegação?',note:nav.persist?'Você pode continuar depois: o progresso fica guardado nesta aba do navegador.':'A rota continua salva no painel.',actions});
    }

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
    document.addEventListener('visibilitychange',()=>{if(active&&document.visibilityState==='hidden')persist();if(active&&document.visibilityState==='visible'){if(nav.wake){try{nav.wake.release();}catch(e){/* já liberado */}nav.wake=null;}holdScreen();}});
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
      const done=nav&&nav.finished,results=nav&&nav.session?{...nav.session.results}:{};
      nav=null;ui=null;
      if(!silent&&onExit)onExit({finished:!!done,results});
    }

    const api={start,exit,saved,discard,statusOf,get active(){return active;},
      // Só para testes e depuração: estado interno e uma posição simulada.
      _state:()=>nav,_fix:onFix};
    window.SfaAtlasNav.last=api;
    return api;
  }};
})();
