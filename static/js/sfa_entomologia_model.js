/* Shared pure calculations: browser and Node regression tests use the same model. */
(function (root) {
  'use strict';
  const metrics = ['worked','closed','vacant','temporary','partial','refused','positive','aegypti','albopictus','mechanical','alternative','focal','containers','water','positive_containers','aegypti_containers','albopictus_containers','aegypti_larvae','albopictus_larvae'];
  function sumKnown(rows, key) {
    const values = rows.map(row => row[key]).filter(value => typeof value === 'number' && Number.isFinite(value));
    return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
  }
  function filter(rows, filters, mapped) {
    return rows.filter(row => (!filters.start || row.date >= filters.start) && (!filters.end || row.date <= filters.end)
      && (!filters.sector || row.sector === filters.sector) && (!filters.block || row.block === filters.block)
      && (!filters.species || row[filters.species] > 0)
      && (!filters.mapping || (filters.mapping === 'mapped' ? mapped.has(row.sector) : !mapped.has(row.sector)))
      && (!filters.result || (filters.result === 'positive' && row.positive > 0)
        || (filters.result === 'zero' && row.positive === 0) || (filters.result === 'missing' && row.positive === null)));
  }
  function aggregate(rows) {
    const result = Object.fromEntries(metrics.map(key => [key, sumKnown(rows, key)]));
    result.count = rows.length;
    result.informed = rows.filter(row => row.positive !== null).length;
    result.missing = rows.length - result.informed;
    result.coverage = rows.length ? 100 * result.informed / rows.length : null;
    result.sectors = new Set(rows.map(row => row.sector)).size;
    return result;
  }
  function grouped(rows, key) {
    const groups = new Map();
    rows.forEach(row => { const id = row[key]; if (!groups.has(id)) groups.set(id, []); groups.get(id).push(row); });
    return new Map([...groups].map(([id, values]) => [id, aggregate(values)]));
  }
  function timeline(rows, start, end, metric) {
    if (!start || !end || start > end) return [];
    const byMonth = new Map();
    rows.forEach(row => { const month = row.date.slice(0, 7); if (!byMonth.has(month)) byMonth.set(month, []); byMonth.get(month).push(row); });
    const result = [];
    let [year, month] = start.slice(0, 7).split('-').map(Number);
    while (`${year}-${String(month).padStart(2,'0')}` <= end.slice(0,7) && result.length < 1200) {
      const key = `${year}-${String(month).padStart(2,'0')}`;
      const values = byMonth.get(key) || [];
      result.push({month:key, value:sumKnown(values, metric), count:values.length});
      if (++month > 12) { month = 1; year++; }
    }
    return result;
  }
  function density(row) { return row.population !== null && row.area_km2 > 0 ? row.population / row.area_km2 : null; }
  function shiftDate(iso, days) {
    const date = new Date(iso + 'T12:00:00Z');
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0,10) !== iso) throw new Error('Data inválida');
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0,10);
  }
  function planning(rows, end, days, sector='', scale='sector') {
    if (![7,14,28].includes(days)) throw new Error('Janela inválida');
    const start = shiftDate(end, 1-days), previousEnd = shiftDate(start,-1), previousStart = shiftDate(start,-days);
    const current = rows.filter(r => r.date >= start && r.date <= end && (!sector || r.sector === sector));
    const previous = rows.filter(r => r.date >= previousStart && r.date <= previousEnd && (!sector || r.sector === sector));
    const key = r => JSON.stringify(scale === 'block' ? [r.area,r.sector,r.block] : [r.sector]);
    const partition = values => {
      const groups = new Map();
      values.forEach(r => { const id=key(r); if(!groups.has(id))groups.set(id,[]); groups.get(id).push(r); });
      return groups;
    };
    const before = partition(previous);
    const groups = [...partition(current)].map(([id, values]) => {
      const positive = values.filter(r=>r.positive>0 || r.aegypti>0 || r.albopictus>0);
      return {sector:values[0].sector, area:scale==='block'?values[0].area:'', block:scale==='block'?values[0].block:'',
        ...aggregate(values), previous_positive:sumKnown(before.get(id)||[],'positive'),
        positive_days:new Set(positive.map(r=>r.date)).size,
        last_positive:positive.map(r=>r.date).sort().at(-1)||'', last_visit:values.map(r=>r.date).sort().at(-1)};
    });
    return {start,end,previousStart,previousEnd,current:aggregate(current),previous:aggregate(previous),groups};
  }
  function workQueue(groups, kind) {
    const tie = (a,b) => a.sector.localeCompare(b.sector) || a.area.localeCompare(b.area) || a.block.localeCompare(b.block,undefined,{numeric:true});
    if (kind==='access') return groups.filter(r=>r.closed>0||r.refused>0).sort((a,b)=>(b.closed||0)-(a.closed||0)||(b.refused||0)-(a.refused||0)||tie(a,b));
    if (kind==='quality') return groups.filter(r=>r.missing>0).sort((a,b)=>b.missing-a.missing||tie(a,b));
    return groups.filter(r=>r.positive>0||r.aegypti>0||r.albopictus>0).sort((a,b)=>(b.aegypti||0)-(a.aegypti||0)||(b.positive||0)-(a.positive||0)||b.last_positive.localeCompare(a.last_positive)||tie(a,b));
  }
  function csv(rows, columns) {
    const escape = value => {
      let text = value == null ? '' : String(value);
      if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
      return '"' + text.replace(/"/g, '""') + '"';
    };
    return '\ufeff' + [columns.map(c => escape(c[1])).join(';'), ...rows.map(row => columns.map(c => escape(row[c[0]])).join(';'))].join('\r\n');
  }
  const model = {metrics, sumKnown, filter, aggregate, grouped, timeline, density, shiftDate, planning, workQueue, csv};
  if (typeof module !== 'undefined' && module.exports) module.exports = model;
  else root.EntomologiaModel = model;
})(typeof window === 'undefined' ? globalThis : window);
