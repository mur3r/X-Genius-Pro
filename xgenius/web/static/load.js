/* X-Genius web UI — Load tab: CPU per core, RAM, Chrome processes per account, Selenium thread pool,
   event-loop lag. Data: {type:'sysmon'} WebSocket messages (one sample) and GET /api/sysmon (history).
   Uses $, esc, api, toast from app.js and I() from icons.js (all called at runtime, after those scripts load). */
'use strict';

const Load = (() => {
  const L = { info: {}, latest: null, history: [], enabled: true, active: false, loaded: false, sort: 'cpu' };

  const PHASE_COLOR = { mailing: 'info', parsing: 'violet', paused: 'warn', relogin: 'violet', idle: 'ok', browser: 'muted', webui: 'muted', driver: 'muted', unknown: 'muted', inactive: 'muted' };
  const PHASE_LABEL = { mailing: 'MAILING', parsing: 'PARSING', paused: 'PAUSED', relogin: 'RELOGIN', idle: 'IDLE', browser: 'BROWSER', webui: 'UI WINDOW', driver: 'DRIVERS', unknown: 'UNKNOWN', inactive: 'INACTIVE' };

  const pct = (v) => (v == null ? '—' : `${Math.round(v)}%`);
  const ms = (v) => (v == null ? '—' : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`);
  const gb = (v) => (v == null ? '—' : `${v.toFixed(v < 10 ? 1 : 0)} GB`);
  const level = (v, warn, err) => (v == null ? null : v >= err ? 'err' : v >= warn ? 'warn' : null);
  const capacity = () => Math.max(20, Math.round(((L.info.history_minutes || 60) * 60) / (L.info.interval || 5)));

  /* ---------------------------------------------------------------- tiles */
  function renderTiles(s) {
    const tile = (label, value, sub, color) => `<div class="tile" ${color ? `style="--tc:var(--${color})"` : ''}>
      <span class="l">${label}</span><span class="v">${value}</span><span class="s">${sub}</span></div>`;
    const c = s.cpu, m = s.mem, ch = s.chrome, py = s.python, ex = s.executor, en = s.engine;
    const exFull = ex.max && ex.inflight != null && ex.inflight >= ex.max;
    $('#load-tiles').innerHTML = [
      tile('CPU', pct(c.total), `${c.busy_cores} of ${c.count} threads over 90%`, level(c.total, 75, 90)),
      tile('Chrome', pct(ch.cpu), `${ch.procs} processes · ${gb(ch.rss_gb)}`, level(ch.cpu, 60, 80)),
      tile('RAM', gb(m.used_gb), `of ${gb(m.total_gb)} · ${pct(m.pct)}`, level(m.pct, 80, 90)),
      tile('Selenium', `${ex.inflight ?? '—'}<span class="dim"> / ${ex.max ?? '—'}</span>`,
        `avg ${ms(ex.avg_ms)} · max ${ms(ex.max_ms)} · ${ex.calls ?? 0} calls`, exFull ? 'err' : level(ex.avg_ms, 1500, 4000)),
      tile('Loop lag', ms(s.loop_lag_ms), 'event loop, worst in interval', level(s.loop_lag_ms, 300, 1000)),
      tile('Python', pct(py.cpu), `${py.threads} threads · ${py.rss_mb} MB`),
      tile('Browsers', en.browsers, `${en.mailing} mailing · ${en.parsing} parsing · ${en.idle} idle`),
    ].join('');
  }

  /* ---------------------------------------------------------------- cores */
  function renderCores(s) {
    const cores = s.cpu.cores || [];
    $('#cores').innerHTML = cores.map((v, i) => {
      const lv = v >= 90 ? 'err' : v >= 70 ? 'warn' : v >= 40 ? 'info' : 'ok';
      return `<div class="core" title="core ${i}: ${v}%"><div class="bar"><i style="height:${Math.max(2, v)}%;background:var(--${lv})"></i></div><span>${i}</span></div>`;
    }).join('');
    $('#cores-sub').textContent = `${s.cpu.physical} cores / ${s.cpu.count} threads · max core ${pct(s.cpu.max_core)}`
      + (s.cpu.load1 != null ? ` · load ${s.cpu.load1}` : '');
  }

  /* ---------------------------------------------------------------- charts (inline SVG, no libs) */
  function polyline(values, W, H, pad, maxY, cap) {
    const n = values.length;
    if (!n) return '';
    const step = (W - pad.l - pad.r) / Math.max(1, cap - 1);
    return values.map((v, i) => {
      const x = pad.l + i * step;
      const y = pad.t + (H - pad.t - pad.b) * (1 - Math.min(1, Math.max(0, (v ?? 0) / maxY)));
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
  }
  function chart(svgId, series, maxY, unit) {
    const svg = $(svgId);
    const W = 600, H = 170, pad = { l: 34, r: 8, t: 8, b: 18 };
    const cap = capacity();
    const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => {
      const y = pad.t + (H - pad.t - pad.b) * (1 - f);
      const label = unit === '%' ? `${Math.round(maxY * f)}%` : ms(maxY * f);
      return `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}" class="grid"/><text x="${pad.l - 5}" y="${y + 3.5}" class="axis">${label}</text>`;
    }).join('');
    const lines = series.map((sr) => `<polyline points="${polyline(sr.values, W, H, pad, maxY, cap)}" style="stroke:var(--${sr.color})" ${sr.dashed ? 'stroke-dasharray="4 3"' : ''}/>`).join('');
    const minutes = Math.round((cap * (L.info.interval || 5)) / 60);
    const xl = `<text x="${pad.l}" y="${H - 4}" class="axis start">-${minutes} min</text><text x="${W - pad.r}" y="${H - 4}" class="axis">now</text>`;
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.innerHTML = grid + xl + lines;
  }
  function renderCharts() {
    const h = L.history;
    chart('#chart-cpu', [
      { values: h.map((p) => p.cpu), color: 'accent' },
      { values: h.map((p) => p.chrome), color: 'info' },
      { values: h.map((p) => p.mem), color: 'violet', dashed: true },
    ], 100, '%');
    const lat = h.map((p) => p.sel_avg ?? 0), lmax = h.map((p) => p.sel_max ?? 0), lag = h.map((p) => p.lag ?? 0);
    const top = Math.max(500, ...lat, ...lag, ...lmax.map((v) => v / 2));
    const nice = top <= 1000 ? 1000 : top <= 2500 ? 2500 : top <= 5000 ? 5000 : top <= 10000 ? 10000 : Math.ceil(top / 10000) * 10000;
    chart('#chart-lat', [
      { values: lat, color: 'accent' },
      { values: lmax, color: 'warn', dashed: true },
      { values: lag, color: 'err' },
    ], nice, 'ms');
  }

  /* ---------------------------------------------------------------- accounts */
  function accountName(a) {
    if (a.username === '_webui') return '<span class="dim">X-Genius UI window</span>';
    if (a.username === '_driver') return '<span class="dim">chromedriver processes</span>';
    if (a.username === '_other') return '<span class="dim">chrome in profiles folder, no account</span>';
    return `<span class="handle">@${esc(a.username)}</span>`;
  }
  function renderAccounts(s) {
    const rows = (s.accounts || []).slice();
    const key = L.sort;
    rows.sort((a, b) => (key === 'name' ? a.username.localeCompare(b.username) : (b[key] ?? 0) - (a[key] ?? 0)));
    const maxCpu = Math.max(1, ...rows.map((a) => a.cpu_raw || 0));
    const withProcs = rows.filter((a) => a.procs).length;
    $('#acc-sub').textContent = `${withProcs} with browsers · CPU share is of the whole machine; raw = sum over cores (100% = one full thread)`;
    $('#load-accounts tbody').innerHTML = rows.map((a) => {
      const color = PHASE_COLOR[a.phase] || 'muted';
      return `<tr>
        <td>${accountName(a)}</td>
        <td><span class="pill" style="--st:var(--${color})">${esc(PHASE_LABEL[a.phase] || a.phase.toUpperCase())}</span></td>
        <td>${a.procs}</td><td>${a.threads}</td>
        <td><div class="cpubar"><i style="width:${Math.round(((a.cpu_raw || 0) / maxCpu) * 100)}%"></i><span>${a.cpu == null ? '—' : `${a.cpu.toFixed(1)}%`}</span></div></td>
        <td>${a.cpu_raw == null ? '—' : `${Math.round(a.cpu_raw)}%`}</td>
        <td>${a.rss_mb}</td></tr>`;
    }).join('') || '<tr><td colspan="7" class="muted">No Chrome processes yet — log in an account.</td></tr>';
  }

  /* ---------------------------------------------------------------- render */
  function renderAll() {
    const s = L.latest;
    $('#load-disabled').classList.toggle('hidden', L.enabled);
    $('#load-body').classList.toggle('hidden', !L.enabled || !s);
    $('#load-waiting').classList.toggle('hidden', !L.enabled || !!s);
    if (!L.enabled || !s) return;
    renderTiles(s);
    renderCores(s);
    renderCharts();
    renderAccounts(s);
    $('#load-status').textContent = `updated ${s.ts} · every ${L.info.interval || '?'} s · ${L.info.csv || ''}`;
  }
  function badge(s) {
    const b = $('#tab-load-badge');
    if (!b) return;
    if (!s || !L.enabled) { b.textContent = ''; b.className = 'tab-badge'; return; }
    b.textContent = pct(s.cpu.total);
    b.className = `tab-badge ${level(s.cpu.total, 75, 90) || ''}`;
  }

  /* ---------------------------------------------------------------- data in */
  function onSample(s) {
    L.latest = s;
    L.history.push({ t: s.t, cpu: s.cpu.total, chrome: s.chrome.cpu, mem: s.mem.pct, lag: s.loop_lag_ms,
      sel_avg: s.executor.avg_ms, sel_max: s.executor.max_ms, inflight: s.executor.inflight, browsers: s.engine.browsers });
    const cap = capacity();
    if (L.history.length > cap) L.history.splice(0, L.history.length - cap);
    badge(s);
    if (L.active) renderAll();
  }
  async function fetchHistory() {
    try {
      const r = await api('GET', '/api/sysmon');
      L.info = r.info || L.info;
      L.enabled = r.enabled !== false;
      L.history = r.history || [];
      if (r.latest && r.latest.seq) L.latest = r.latest;
      L.loaded = true;
    } catch (e) { /* offline / demo: keep what we have */ }
  }
  async function activate() {
    L.active = true;
    if (!L.loaded && !S.demo) await fetchHistory();
    badge(L.latest);
    renderAll();
  }
  function deactivate() { L.active = false; }
  function setEnabled(on) {
    if (L.enabled === on) return;
    L.enabled = on;
    if (L.active) renderAll();
    badge(L.latest);
  }
  function setSort(key) { L.sort = key; if (L.latest && L.active) renderAccounts(L.latest); }

  /* ---------------------------------------------------------------- demo (page opened without the service) */
  function demo() {
    const cores = 32, cap = 120;
    L.info = { cpu_count: cores, cpu_physical: 16, mem_total_gb: 128, interval: 5, history_minutes: 10, csv: 'D:\\SoftTwitter\\logs\\sysmon_20260914.csv' };
    L.history = [];
    let cpu = 55;
    for (let i = 0; i < cap; i++) {
      cpu = Math.min(99, Math.max(30, cpu + (Math.random() - 0.45) * 6 + (i > 70 ? 0.6 : 0)));
      L.history.push({ t: i, cpu, chrome: cpu * 0.78, mem: 28 + i * 0.05, lag: 5 + Math.random() * 30 + (cpu > 90 ? 400 : 0),
        sel_avg: 200 + cpu * 9 + Math.random() * 100, sel_max: 900 + cpu * 40, inflight: Math.round(cpu / 3), browsers: 50 });
    }
    const last = L.history[L.history.length - 1];
    const coreVals = Array.from({ length: cores }, () => Math.round(Math.min(100, Math.max(5, last.cpu + (Math.random() - 0.5) * 50))));
    const names = ['crypto_ann', 'max_trades', 'lena_nft', 'dm_bot_44', 'tina', 'sultana_hotgirl', 'sultana_hotsex', 'fresh_one'];
    const phases = ['mailing', 'mailing', 'paused', 'relogin', 'mailing', 'parsing', 'parsing', 'idle'];
    const accounts = names.map((u, i) => {
      const raw = Math.round(20 + Math.random() * 90);
      return { username: u, phase: phases[i], procs: 8 + (i % 3), threads: 240 + i * 17, cpu_raw: raw, cpu: +(raw / cores).toFixed(2), rss_mb: 600 + i * 90 };
    });
    accounts.push({ username: '_webui', phase: 'webui', procs: 6, threads: 120, cpu_raw: 3, cpu: 0.09, rss_mb: 210 });
    L.latest = {
      seq: cap, t: Date.now() / 1000, ts: new Date().toTimeString().slice(0, 8),
      cpu: { total: Math.round(last.cpu), user: 70, system: 22, cores: coreVals, max_core: Math.max(...coreVals), busy_cores: coreVals.filter((v) => v >= 90).length, count: cores, physical: 16, load1: 41.3 },
      mem: { total_gb: 128, used_gb: 41.2, avail_gb: 86.8, pct: 32.2 },
      chrome: { procs: 412, threads: 14870, cpu_raw: Math.round(last.chrome * cores), cpu: Math.round(last.chrome), rss_gb: 38.1, other_procs: 0, other_cpu: 0 },
      python: { cpu: 1.2, cpu_raw: 38, rss_mb: 310, threads: 140 },
      executor: { max: 128, threads: 90, inflight: last.inflight, calls: 812, avg_ms: Math.round(last.sel_avg), max_ms: Math.round(last.sel_max) },
      loop_lag_ms: Math.round(last.lag),
      engine: { browsers: 50, mailing: 30, parsing: 5, idle: 15 },
      accounts,
    };
    L.enabled = true;
    badge(L.latest);
    if (L.active) renderAll();
  }
  function reset() { L.history = []; L.latest = null; L.loaded = false; badge(null); if (L.active) renderAll(); }

  return { onSample, activate, deactivate, setEnabled, setSort, demo, reset, state: L };
})();
