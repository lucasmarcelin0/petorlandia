(function(){
  'use strict';
  const M=window.SfaCondominiosModel, F=window.SfaFieldMapModel;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  window.SfaCondominios={attach(map,{popup}){
    const labels=L.layerGroup().addTo(map), dots=L.layerGroup().addTo(map);
    const pane='field-house-labels',dotPane='field-house-dots';
    map.createPane(pane).style.zIndex=640;
    map.createPane(dotPane).style.zIndex=615;
    const project=c=>map.latLngToContainerPoint([c[1],c[0]]);
    function reserve(){
      const mapRect=document.getElementById('field-map').getBoundingClientRect();
      return [...document.querySelectorAll('#field-map .leaflet-control, .field-map-caption > span, #field-map .atlas-cluster')].map(e=>{
        const r=e.getBoundingClientRect();return {left:r.left-mapRect.left-3,right:r.right-mapRect.left+3,top:r.top-mapRect.top-3,bottom:r.bottom-mapRect.top+3};});
    }
    function focus(items){map.fitBounds(L.geoJSON(items).getBounds(),{padding:[35,35],maxZoom:19});}
    function render(all){
      labels.clearLayers();dots.clearLayers();
      const visible=all.filter(f=>f.geometry?.type==='Point'&&map.getBounds().pad(.1).contains([f.geometry.coordinates[1],f.geometry.coordinates[0]]));
      if(!visible.length)return;
      const zoom=map.getZoom(),size=map.getSize();
      if(zoom<18){
        let groups=M.overview(all), merged=[];
        // Nearby condominiums share one overview card until the map has room.
        groups.forEach(g=>{const p=project(g.coordinates),same=merged.find(m=>Math.abs(project(m.coordinates).x-p.x)<145&&Math.abs(project(m.coordinates).y-p.y)<45);
          if(same){same.names.push(g.name);same.items.push(...g.items);same.coordinates=M.overview(same.items.map(f=>({...f,atlasEntry:{...f.atlasEntry,id:'merged'}})))[0].coordinates;}
          else merged.push({...g,names:[g.name]});});
        const cards=merged.map(g=>{const p=project(g.coordinates);return {...g,x:p.x,y:p.y,width:g.names.length>1?154:128,height:40};});
        F.placeLabels(cards,size.x,size.y,3,reserve()).forEach(g=>{
          const title=g.names.join(' · ');
          L.marker([g.coordinates[1],g.coordinates[0]],{pane,keyboard:true,title:'Aproximar '+title,icon:L.divIcon({className:'atlas-condo-overview',
            iconSize:[g.width,40],iconAnchor:[g.width/2,20],html:`<span style="--condo-color:${g.color}"><b>${esc(title)}</b><small>${g.items.length} casas · aproximar</small></span>`})})
            .on('click',()=>focus(g.items)).addTo(labels);
        });
        return;
      }
      visible.forEach(f=>L.circleMarker([f.geometry.coordinates[1],f.geometry.coordinates[0]],{pane:dotPane,radius:2.5,weight:1,color:'#fff',fillColor:f.atlasEntry.color,fillOpacity:.9})
        .bindTooltip(esc(f.properties.address||f.properties.name),{direction:'top',className:'field-tooltip'})
        .bindPopup(popup(f,f.atlasEntry.title)).addTo(dots));
      const houses=F.placeLabels(M.candidates(visible,project),size.x,size.y,1,reserve());
      houses.forEach(c=>{
        const f=c.feature,title=f.properties.address||f.properties.name;
        L.marker([f.geometry.coordinates[1],f.geometry.coordinates[0]],{pane,keyboard:true,title,icon:L.divIcon({className:'atlas-house-label',
          iconSize:[c.width,20],iconAnchor:[c.width/2,10],html:`<span style="--condo-color:${f.atlasEntry.color}">${esc(c.text)}</span>`})})
          .bindTooltip(esc(title),{direction:'top',className:'field-tooltip'})
          .bindPopup(popup(f,f.atlasEntry.title)).addTo(labels);
      });
      const occupied=houses.map(c=>({left:c.x-c.width/2-4,right:c.x+c.width/2+4,top:c.y-14,bottom:c.y+14}));
      F.placeLabels(M.streets(visible,project),size.x,size.y,3,[...reserve(),...occupied]).forEach(c=>{
        L.marker([c.coordinates[1],c.coordinates[0]],{pane,interactive:false,keyboard:false,icon:L.divIcon({className:'atlas-condo-street',
          iconSize:[78,16],iconAnchor:[39,8],html:`<span>${esc(c.text)}</span>`})}).addTo(labels);
      });
    }
    return {render};
  }};
})();
