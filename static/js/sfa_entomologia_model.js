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
  /* Equipe: semanas de domingo a sábado, como na comparação semanal do SFA. */
  function weekStart(iso) {
    const date = new Date(shiftDate(iso, 0) + 'T12:00:00Z');
    return shiftDate(iso, -date.getUTCDay());
  }
  const blockKey = r => `${r.area}|${r.sector}|${r.block}`;
  function weekSummary(rows, start, end) {
    const a = aggregate(rows);
    const attempts = (a.worked || 0) + (a.closed || 0) + (a.refused || 0);
    return {start, end, count:a.count, worked:a.worked, closed:a.closed, refused:a.refused, mechanical:a.mechanical,
      positive:a.positive, informed:a.informed, coverage:a.coverage, sectors:a.sectors,
      blocks:new Set(rows.map(blockKey)).size,
      accessLoss: attempts ? 100 * ((a.closed || 0) + (a.refused || 0)) / attempts : null};
  }
  function teamWeeks(rows, end, count) {
    const last = weekStart(end), first = shiftDate(last, -7 * (count - 1));
    const buckets = new Map();
    rows.forEach(r => { if (r.date >= first && r.date <= end) { const k = weekStart(r.date); if (!buckets.has(k)) buckets.set(k, []); buckets.get(k).push(r); } });
    return Array.from({length: count}, (_, i) => {
      const start = shiftDate(first, 7 * i), finish = shiftDate(start, 6);
      return {...weekSummary(buckets.get(start) || [], start, finish), partial: finish > end};
    });
  }
  function mean(values) {
    const known = values.filter(v => typeof v === 'number' && Number.isFinite(v));
    return known.length ? known.reduce((s, v) => s + v, 0) / known.length : null;
  }
  function baseline(weeks, key) {
    return mean(weeks.slice(0, -1).filter(w => w.count > 0).slice(-4).map(w => w[key]));
  }
  function streak(weeks) {
    let i = weeks.length - 1;
    if (i >= 0 && weeks[i].count === 0 && weeks[i].partial) i--;
    let n = 0;
    while (i >= 0 && weeks[i].count > 0) { n++; i--; }
    return n;
  }
  function achievements(weeks, actions, today) {
    const w = weeks[weeks.length - 1] || weekSummary([], '', '');
    const inWeek = iso => iso && iso >= w.start && iso <= w.end;
    const verified = (actions || []).filter(a => a.status === 'VERIFICADA' && inWeek(a.verificado_em)).length;
    const overdue = (actions || []).filter(a => !['VERIFICADA', 'EXECUTADA'].includes(a.status) && a.prazo && a.prazo < today).length;
    const goal = (id, icon, title, value, target, better, describe) => {
      const earned = value != null && target != null && (better === 'lower' ? value <= target : value >= target) && w.count > 0;
      return {id, icon, title, value, target, earned, noBase: target == null, text: describe};
    };
    const cover = baseline(weeks, 'coverage'), blocks = baseline(weeks, 'blocks'), loss = baseline(weeks, 'accessLoss'), mech = baseline(weeks, 'mechanical');
    const seq = streak(weeks);
    return [
      goal('territory', 'fa-route', 'Território em movimento', w.blocks, blocks, 'higher', 'Quarteirões diferentes na semana, contra a média das últimas 4 semanas com registro.'),
      goal('quality', 'fa-clipboard-check', 'Registro que orienta', w.coverage, cover, 'higher', 'Visitas com resultado de larvas preenchido. Vazio não é zero: completar o registro vale ponto.'),
      goal('access', 'fa-door-open', 'Portas abertas', w.accessLoss, loss, 'lower', 'Fechados e recusas sobre o total de tentativas. Quanto menor, mais casas foram inspecionadas.'),
      goal('breeding', 'fa-bucket', 'Criadouro fora', w.mechanical, mech, 'higher', 'Imóveis com controle mecânico (retirada ou eliminação de recipientes).'),
      {id:'verified', icon:'fa-circle-check', title:'Ciclo fechado', value:verified, target:1, earned:verified >= 1, noBase:false, overdue,
        text:'Ações territoriais verificadas nesta semana: executar e conferir o resultado fecha o ciclo.'},
      {id:'streak', icon:'fa-fire', title:'Sequência', value:seq, target:4, earned:seq >= 4, noBase:false,
        text:'Semanas seguidas com registros enviados. A semana atual ainda sem envio não quebra a sequência.'}
    ];
  }
  function cycle(rows, end) {
    const [year, month] = end.split('-').map(Number);
    const firstMonth = month % 2 === 0 ? month - 1 : month;
    const start = `${year}-${String(firstMonth).padStart(2, '0')}-01`;
    const known = new Map(), visited = new Map();
    rows.forEach(r => {
      if (!known.has(r.sector)) { known.set(r.sector, new Set()); visited.set(r.sector, new Set()); }
      known.get(r.sector).add(`${r.area}|${r.block}`);
      if (r.date >= start && r.date <= end) visited.get(r.sector).add(`${r.area}|${r.block}`);
    });
    const sectors = [...known].map(([sector, blocks]) => ({sector, known:blocks.size, visited:visited.get(sector).size,
      pct:100 * visited.get(sector).size / blocks.size}))
      .sort((a, b) => a.pct - b.pct || b.known - a.known || a.sector.localeCompare(b.sector));
    const sum = key => sectors.reduce((s, r) => s + r[key], 0);
    return {number:Math.ceil(month / 2), start, end, sectors, done:sectors.filter(r => r.visited === r.known).length,
      blocksVisited:sum('visited'), blocksKnown:sum('known')};
  }
  function nextSteps(rows, actions, end, today) {
    const steps = [];
    const age = Math.round((new Date(today + 'T12:00:00Z') - new Date(end + 'T12:00:00Z')) / 86400000);
    if (age > 2) steps.push({kind:'data', days:age});
    const open = new Set((actions || []).filter(a => a.status !== 'VERIFICADA').map(a => a.sector));
    const plan = planning(rows, end, 14);
    const foci = workQueue(plan.groups, 'focus').filter(r => !open.has(r.sector));
    if (foci.length) steps.push({kind:'focus', sectors:foci.slice(0, 5).map(r => r.sector), total:foci.length});
    const overdue = (actions || []).filter(a => a.status !== 'VERIFICADA' && a.status !== 'EXECUTADA' && a.prazo && a.prazo < today);
    if (overdue.length) steps.push({kind:'overdue', total:overdue.length});
    const toVerify = (actions || []).filter(a => a.status === 'EXECUTADA');
    if (toVerify.length) steps.push({kind:'verify', total:toVerify.length});
    return steps;
  }
  const model = {metrics, sumKnown, filter, aggregate, grouped, timeline, density, shiftDate, planning, workQueue, csv,
    weekStart, teamWeeks, baseline, streak, achievements, cycle, nextSteps};
  if (typeof module !== 'undefined' && module.exports) module.exports = model;
  else root.EntomologiaModel = model;
})(typeof window === 'undefined' ? globalThis : window);
