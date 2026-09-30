(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SfaFieldMapModel = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  const normalize = text => String(text).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  function filter(features, {district = '', sector = '', search = ''}) {
    const q = normalize(search), numbered = q.match(/^(?:(?:q|quadra|quarteirao|sc|setor)\s*)?(\d+)([a-z]?)$/);
    return features.filter(f => {
      const p = f.properties;
      if ((district && p.district !== district) || (sector && p.sector !== sector)) return false;
      if (!q) return true;
      if (numbered) {
        const n = Number(numbered[1]);
        return /^(sc|setor)/.test(q) ? !numbered[2] && Number(p.sector) === n : normalize(p.block) === String(n) + numbered[2];
      }
      return normalize(`${p.district} SC ${p.sector} quadra ${p.block}`).includes(q);
    });
  }
  // Screen-space rectangles keep labels readable at every zoom and viewport.
  function placeLabels(candidates, width, height, gap = 5, reserved = []) {
    const placed = [], cells = new Map(), size = 64;
    const keys = r => {
      const output = [];
      for (let x = Math.floor(r.left / size); x <= Math.floor(r.right / size); x++)
        for (let y = Math.floor(r.top / size); y <= Math.floor(r.bottom / size); y++) output.push(`${x}:${y}`);
      return output;
    };
    reserved.forEach(r => keys(r).forEach(k => {if (!cells.has(k)) cells.set(k, []); cells.get(k).push(r);}));
    for (const c of [...candidates].sort((a, b) => (b.priority || 0) - (a.priority || 0))) {
      const r = {left:c.x-c.width/2-gap, right:c.x+c.width/2+gap, top:c.y-c.height/2-gap, bottom:c.y+c.height/2+gap};
      if (r.left < 0 || r.top < 0 || r.right > width || r.bottom > height) continue;
      const slots = keys(r), nearby = new Set(slots.flatMap(k => cells.get(k) || []));
      if ([...nearby].some(o => r.left < o.right && r.right > o.left && r.top < o.bottom && r.bottom > o.top)) continue;
      placed.push(c);
      slots.forEach(k => {if (!cells.has(k)) cells.set(k, []); cells.get(k).push(r);});
    }
    return placed;
  }
  return {filter, placeLabels};
});
