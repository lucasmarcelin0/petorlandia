/*
 * Navegação do atlas: o que acontece com cada parada (concluída, não encontrada, pulada), o
 * progresso que sobrevive a um recarregamento e as regras de zoom e de tema. Sem DOM: o mesmo
 * código roda no navegador e nos testes (tests/test_atlas_nav_session.js).
 *
 * Privacidade: o progresso fica só na aba (sessionStorage), junto com a rota que o atlas já
 * guarda assim. Fechar a aba apaga tudo. Só coordenadas e nomes que a pessoa já adicionou.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SfaAtlasNavSession = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  const STORE = 'sfa-atlas-nav-progress-v1';
  const MAX_AGE = 12 * 3600 * 1000;               // um turno de campo; depois disso o progresso não é oferecido
  const STATUSES = ['done', 'notfound', 'skipped'];
  const BIAS_MIN = -4, BIAS_MAX = 3;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  /** Identidade de uma parada: as coordenadas (cinco casas ≈ 1 m). Sobrevive a reordenar e a recalcular. */
  const stopKey = s => Number(s.lat).toFixed(5) + ',' + Number(s.lng).toFixed(5);

  function create(now) {
    return {v: 1, startedAt: now, savedAt: now, traveled: 0, paused: false, results: {}, log: []};
  }

  function sanitize(raw, now) {
    if (!raw || raw.v !== 1 || !raw.results || typeof raw.results !== 'object') return null;
    const savedAt = Number(raw.savedAt);
    if (!Number.isFinite(savedAt) || now - savedAt > MAX_AGE || now < savedAt - 3600 * 1000) return null;
    const results = {};
    Object.keys(raw.results).forEach(k => { if (STATUSES.indexOf(raw.results[k]) >= 0) results[k] = raw.results[k]; });
    const log = (Array.isArray(raw.log) ? raw.log : []).filter(e => e && typeof e.key === 'string' && STATUSES.indexOf(e.status) >= 0).slice(-50)
      .map(e => ({key: e.key, status: e.status, prev: STATUSES.indexOf(e.prev) >= 0 ? e.prev : null, t: Number(e.t) || 0}));
    return {v: 1, startedAt: Number(raw.startedAt) || savedAt, savedAt, traveled: Math.max(0, Number(raw.traveled) || 0), paused: !!raw.paused, results, log};
  }

  function load(storage, now) {
    try { return sanitize(JSON.parse(storage.getItem(STORE) || 'null'), now); } catch (e) { return null; }
  }
  function save(storage, session, now) {
    try { storage.setItem(STORE, JSON.stringify({...session, savedAt: now})); return true; } catch (e) { return false; }
  }
  function clear(storage) { try { storage.removeItem(STORE); } catch (e) { /* sem armazenamento */ } }

  /** Registra o resultado de uma parada; o último registro pode ser desfeito. */
  function record(session, key, status, now) {
    if (STATUSES.indexOf(status) < 0) throw new Error('Situação inválida: ' + status);
    session.log.push({key, status, prev: session.results[key] || null, t: now});
    if (session.log.length > 50) session.log.shift();
    session.results[key] = status;
    return session;
  }
  function undo(session) {
    const entry = session.log.pop();
    if (!entry) return null;
    if (entry.prev) session.results[entry.key] = entry.prev; else delete session.results[entry.key];
    return entry;
  }

  const statusOf = (session, stop) => (session && session.results[stopKey(stop)]) || null;
  /** O que ainda falta visitar: sem resultado, ou pulada (a pessoa decide voltar a ela). */
  const pending = (stops, session) => stops.filter(s => { const r = statusOf(session, s); return r !== 'done' && r !== 'notfound'; });

  function counts(stops, session) {
    const c = {total: stops.length, done: 0, notfound: 0, skipped: 0, pending: 0};
    stops.forEach(s => { const r = statusOf(session, s); if (r) c[r]++; else c.pending++; });
    return c;
  }
  /** "2 de 5 atendidas" (concluídas ou não encontradas: a pessoa já passou por elas). */
  function progressLabel(stops, session) {
    const c = counts(stops, session), seen = c.done + c.notfound;
    return seen + ' de ' + c.total + (seen === 1 ? ' atendida' : ' atendidas');
  }
  /** Há algo a retomar? Só se a pessoa já registrou paradas ou saiu pedindo para continuar depois, e ainda falta visitar. */
  function resumable(stops, session) {
    if (!session || !stops.length) return false;
    const c = counts(stops, session);
    return (c.done + c.notfound > 0 || c.skipped > 0 || session.paused) && pending(stops, session).length > 0;
  }

  const MARK = {done: '✓', notfound: '✕', skipped: '↷', pending: '…'};
  const WORD = {done: 'concluída', notfound: 'não encontrada', skipped: 'pulada', pending: 'pendente'};
  function summaryText(stops, session, meta) {
    const c = counts(stops, session), lines = ['Rota de campo · resumo'];
    lines.push(c.done + ' de ' + c.total + ' concluídas' + (c.notfound ? ' · ' + c.notfound + ' não encontradas' : '') + (c.skipped ? ' · ' + c.skipped + ' puladas' : '') + (c.pending ? ' · ' + c.pending + ' pendentes' : ''));
    if (meta && (meta.distance || meta.duration)) lines.push([meta.distance && 'Percurso: ' + meta.distance, meta.duration && 'Tempo: ' + meta.duration].filter(Boolean).join(' · '));
    stops.forEach((s, i) => {
      const r = statusOf(session, s) || 'pending';
      lines.push((i + 1) + '. ' + MARK[r] + ' ' + s.name + (r === 'done' ? '' : ' — ' + WORD[r]) + (s.note ? ' (' + s.note + ')' : ''));
    });
    return lines.join('\n');
  }

  // ---- Zoom -------------------------------------------------------------------------
  /** Zoom automático: mais perto parado e perto de manobra, mais longe em velocidade. `bias` é o ajuste manual. */
  function zoomFor(speed, nextDistance, bias) {
    const v = Number.isFinite(speed) ? speed : 0;
    let z = v < 2.5 ? 18.5 : v < 9 ? 17.75 : v < 18 ? 17 : 16.5;
    if (nextDistance !== undefined && nextDistance < 90) z += 0.5;
    return clamp(z + (bias || 0), 13, 20);
  }
  const stepBias = (bias, delta) => clamp(Math.round((bias + delta) * 4) / 4, BIAS_MIN, BIAS_MAX);
  /** Pinça: dedos 2× mais afastados = um nível de zoom a mais. */
  const pinchBias = (start, ratio) => ratio > 0 ? clamp(start + Math.log2(ratio), BIAS_MIN, BIAS_MAX) : start;

  // ---- Tema e aproximação -----------------------------------------------------------
  /** `mode`: 'night' | 'day' | 'auto'. No automático, noite das 18h às 5h30. */
  function isNight(date, mode) {
    if (mode === 'night') return true;
    if (mode === 'day') return false;
    const minutes = date.getHours() * 60 + date.getMinutes();
    return minutes >= 18 * 60 || minutes < 5 * 60 + 30;
  }
  const nextTheme = mode => mode === 'auto' ? 'night' : mode === 'night' ? 'day' : 'auto';
  /** 0 = longe da manobra, 1 = nela. O trecho que enche a barra cresce com a velocidade (mais tempo de aviso). */
  function approach(distance, speed) {
    if (!Number.isFinite(distance)) return 0;
    const span = clamp((Number.isFinite(speed) ? speed : 0) * 14, 150, 500);
    return clamp(1 - distance / span, 0, 1);
  }

  return {STORE, MAX_AGE, STATUSES, BIAS_MIN, BIAS_MAX, stopKey, create, sanitize, load, save, clear, record, undo, statusOf, pending, counts,
    progressLabel, resumable, summaryText, zoomFor, stepBias, pinchBias, isNight, nextTheme, approach};
});
