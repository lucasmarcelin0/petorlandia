(function (root) {
  'use strict';
  const transparent = 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
  // A failed background is removed before trying another map service.
  root.SfaMapLayers = {
    attach(map, {status = () => {}, mode = 'satellite'} = {}) {
      const definitions = {
        satellite: ['Satélite', 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
          'Imagens &copy; Esri, Maxar, Earthstar Geographics e comunidade GIS', 19],
        streets: ['Ruas', 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
          'Mapa &copy; Esri, HERE, Garmin, OpenStreetMap e comunidade GIS', 19]
      };
      let active = null, current = '', failures = 0;
      function setMode(next, automatic = false) {
        if (active) map.removeLayer(active);
        active = null; current = next; failures = 0;
        if (definitions[next]) {
          const [name, url, attribution, maxNativeZoom] = definitions[next];
          const layer = L.tileLayer(url, {attribution, maxNativeZoom, maxZoom: 21, errorTileUrl: transparent});
          active = layer;
          layer.on('tileerror', () => {
            if (active !== layer || ++failures < 3) return;
            setMode(next === 'satellite' ? 'streets' : 'none', true);
          });
          layer.addTo(map);
          status(automatic ? 'Satélite indisponível. Base de ruas ativada; as quadras continuam visíveis.' : `Base ${name.toLowerCase()} selecionada.`);
        } else status(automatic ? 'Fundo indisponível. Quadras e números continuam disponíveis.' : 'Base limpa: somente as camadas territoriais.');
        map.fire('sfabasemapchange', {mode: current});
      }
      setMode(mode);
      L.control.scale({imperial: false, position: 'bottomleft'}).addTo(map);
      return {setMode, getMode: () => current};
    }
  };
})(window);
