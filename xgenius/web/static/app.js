/* X-Genius web UI — state, WebSocket, board/table/console rendering, command bar actions.
   Icons: icons.js (I, injectIcons). Dialog forms: dialogs.js (Dialogs). */
'use strict';

const S = {
  phase: null, data: null, selected: new Set(),
  q: '', group: '', status: '',
  logs: [], logFilter: '', autoscroll: true, ws: null, connected: false,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}K` : String(n ?? 0));

/* ------------------------------------------------------------------ api / toast */
async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const res = await fetch(path, opt);
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-json */ }
  if (!res.ok) throw new Error((data && data.error) || `${res.status} ${res.statusText}`);
  return data;
}
function toast(msg, kind = 'info', ms = 4500) {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), ms);
}
async function run(fn, okMsg) {
  try {
    const r = await fn();
    if (okMsg) toast(typeof okMsg === 'function' ? okMsg(r) : okMsg, 'ok');
    return r;
  } catch (e) {
    toast(e.message || String(e), 'error', 7000);
    return null;
  }
}

/* ------------------------------------------------------------------ selection / filters */
function accounts() { return (S.data && S.data.accounts) || []; }
function selectedNames() {
  const known = new Set(accounts().map((a) => a.username));
  return Array.from(S.selected).filter((u) => known.has(u));
}
function requireSelection() {
  const names = selectedNames();
  if (!names.length) { toast('Select at least one account first.', 'warn'); return null; }
  return names;
}
function renderSelectionCount() { $('#sel-count').textContent = `${selectedNames().length} selected`; }

function statusCategory(a) {
  if (a.is_paused) return 'paused';
  if (a.need_relogin || /RELOGIN/.test(a.status)) return 'relogin';
  if (a.status_reason && !/^(RECOVERING|DM LIMIT|SEND STALL)/i.test(a.status_reason)) return 'error';
  if (a.is_mailing) return 'mailing';
  if (a.is_active) return 'active';
  return 'inactive';
}
function filteredRows() {
  const q = S.q.trim().toLowerCase();
  return accounts().filter((a) => {
    if (S.group && a.group !== S.group) return false;
    if (S.status && statusCategory(a) !== S.status) return false;
    if (q && !(`${a.username} ${a.group} ${a.proxy}`.toLowerCase().includes(q))) return false;
    return true;
  });
}

/* ------------------------------------------------------------------ rendering */
function renderBoard() {
  const s = S.data.summary || {};
  const tile = (label, value, sub, color) => `<div class="tile" ${color ? `style="--tc:var(--${color})"` : ''}>
    <span class="l">${label}</span><span class="v">${value ?? 0}</span><span class="s">${sub}</span></div>`;
  $('#summary').innerHTML = [
    tile('Accounts', s.all, `${s.browsers ?? 0} browsers open`),
    tile('Ready', s.ready, 'logged in, idle', 'ok'),
    tile('Mailing', s.mailing, `${s.paused ?? 0} paused`, 'info'),
    tile('Errors', s.error, 'need attention', s.error ? 'err' : null),
    tile('Inactive', s.inactive, 'no browser'),
    tile('Sent', s.messages, `RT ${s.retweets ?? 0} · Comm ${s.comments ?? 0}`),
    tile('Groups', s.groups, 'in caches'),
  ].join('');
  $('#version').textContent = S.data.version ? `v${S.data.version}` : '';
  $('#base-dir').textContent = S.data.base_dir || '';
}

function renderGroupFilter() {
  const sel = $('#f-group');
  const groups = S.data.groups || [];
  const have = Array.from(sel.options).map((o) => o.value);
  if (JSON.stringify(['', ...groups]) !== JSON.stringify(have)) {
    sel.innerHTML = `<option value="">All groups</option>` + groups.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join('');
    sel.value = groups.includes(S.group) ? S.group : '';
    S.group = sel.value;
  }
}

const AV = ['#5B8DEF', '#E07A5F', '#3D9970', '#8E6BD9', '#D48F1E', '#2AA5A0', '#C75B8A', '#6C8B3C'];
function avatarColor(u) { let h = 0; for (const c of u) h = (h * 31 + c.charCodeAt(0)) >>> 0; return AV[h % AV.length]; }
function shortProxy(p) {
  if (!p) return '<span class="dim">—</span>';
  const parts = p.split(':');
  return `<span class="mono">${esc(parts.length >= 2 ? `${parts[0]}:${parts[1]}` : p)}</span>`;
}
function statusPill(a) {
  const cat = statusCategory(a);
  const color = { active: 'ok', mailing: 'info', paused: 'warn', relogin: 'violet', error: 'err', inactive: 'muted' }[cat];
  const label = a.status || (cat === 'active' ? 'ACTIVE' : 'INACTIVE');
  return `<span class="pill ${cat === 'mailing' ? 'pulse' : ''}" style="--st:var(--${color})">${esc(label)}</span>`;
}
function act(name, icon, title, opts = {}) {
  return `<button class="row-act ${opts.cls || ''}" data-act="${name}" title="${title}" ${opts.disabled ? 'disabled' : ''}>${I(icon, 14)}</button>`;
}
function rowHtml(a) {
  const sel = S.selected.has(a.username);
  const notes = [
    a.has_token ? '' : '<span class="tag" title="no auth token">no token</span>',
    a.has_messages ? '' : '<span class="tag" title="no mailing messages">no messages</span>',
    a.disabled_groups ? `<span class="tag" title="groups disabled after strikes">${a.disabled_groups} off</span>` : '',
  ].join('');
  const pause = a.is_mailing
    ? act('pause', a.is_paused ? 'play' : 'pause', a.is_paused ? 'Resume' : 'Pause', { cls: a.is_paused ? 'ok' : 'warn' })
    : act('pause', 'pause', 'Not mailing', { disabled: true });
  return `<tr data-u="${esc(a.username)}" class="${sel ? 'selected' : ''}">
    <td class="c-chk"><input type="checkbox" data-chk ${sel ? 'checked' : ''}></td>
    <td class="c-idx">${a.index}</td>
    <td><div class="acct"><span class="avatar" style="--av:${avatarColor(a.username)}">${esc(a.username.slice(0, 2).toUpperCase())}</span>
      <div><div class="handle">@${esc(a.username)}</div><div class="sub-row sub">${a.group ? `<span class="tag">${esc(a.group)}</span>` : ''}${notes}</div></div></div></td>
    <td class="c-status">${statusPill(a)}</td>
    <td class="sub">${shortProxy(a.proxy)}</td>
    <td class="num">${a.groups_count}</td>
    <td class="num">${a.queue_len}</td>
    <td class="num">${a.messages_sent} <span class="dim">/ ${a.msg_24h}</span></td>
    <td class="num">${a.retweets}</td>
    <td class="num">${fmt(a.followers)}</td>
    <td class="sub mono">${esc(a.last_launch)}</td>
    <td class="c-actions"><div class="acts">
      ${act('login', 'log-in', 'Login')}${act('view', 'eye', 'Bring browser to front', { disabled: !a.has_browser })}
      ${act('parse', 'layers', 'Parse groups', { disabled: !a.is_active })}
      ${act('mailing', 'send', 'Start mailing', { cls: 'primary', disabled: !(a.is_active && !a.is_mailing) })}${pause}
      <span class="sep"></span>
      ${act('settings', 'sliders', 'Settings')}${act('comments', 'message-circle', 'Comments')}${act('edit', 'edit-2', 'Edit account')}${act('stat', 'bar-chart-2', '24h stats')}
      <span class="sep"></span>
      ${act('close', 'x', 'Close browser', { disabled: !a.has_browser && !a.is_active })}${act('delete', 'trash-2', 'Delete account', { cls: 'err' })}
    </div></td>
  </tr>`;
}
function renderTable() {
  const rows = filteredRows();
  $('#rows').innerHTML = rows.map(rowHtml).join('');
  $('#empty').classList.toggle('hidden', accounts().length > 0);
  $('#f-count').textContent = `${rows.length} of ${accounts().length}`;
  $('#chk-all').checked = rows.length > 0 && rows.every((a) => S.selected.has(a.username));
  renderSelectionCount();
}
function showScreen(phase) {
  $('#screen-offline').classList.toggle('hidden', phase !== 'offline');
  $('#screen-setup').classList.toggle('hidden', phase !== 'setup');
  $('#screen-main').classList.toggle('hidden', phase !== 'ready');
}
function showOffline(reason) {
  if (S.data) return; // real or demo state is on screen; the websocket keeps retrying quietly
  $('#offline-url').textContent = location.origin.startsWith('http') ? location.origin : 'http://127.0.0.1:8765';
  $('#offline-status').textContent = reason || 'waiting for connection…';
  showScreen('offline');
}
function applyState(data) {
  if (S.demo && !data.demo) leaveDemo();
  S.data = data;
  const first = S.phase !== data.phase;
  S.phase = data.phase;
  showScreen(data.phase);
  if (data.phase === 'setup') {
    if (first) $('#setup-dir').value = data.base_dir || data.suggested_base_dir || '';
    $('#setup-msg').textContent = data.setup_message || '';
  } else {
    renderBoard();
    renderGroupFilter();
    renderTable();
  }
}

/* ------------------------------------------------------------------ console */
function logLevel(line) {
  const low = line.toLowerCase();
  if (low.includes('login failed') || low.includes('error') || low.includes('ошибка') || line.includes('❌') || line.includes('⛔')) return 'error';
  if (low.includes('skipping retweet') || low.includes('warning') || line.includes('⚠️') || low.includes('не удал')) return 'warning';
  return 'info';
}
function logHtml(line) {
  const m = line.match(/^(\[[^\]]+\])\s*(@\S+)?\s*-\s*(.*)$/s);
  const body = m ? `<span class="ts">${esc(m[1])}</span> ${m[2] ? `<span class="acc">${esc(m[2])}</span> ` : ''}${esc(m[3])}` : esc(line);
  return `<div class="log ${logLevel(line)}">${body}</div>`;
}
function logMatches(line) { const f = S.logFilter.trim().toLowerCase(); return !f || line.toLowerCase().includes(f); }
function appendLogs(lines) {
  const box = $('#logs');
  S.logs.push(...lines);
  if (S.logs.length > 3000) S.logs.splice(0, S.logs.length - 3000);
  const html = lines.filter(logMatches).map(logHtml).join('');
  if (html) box.insertAdjacentHTML('beforeend', html);
  while (box.children.length > 3000) box.firstChild.remove();
  if (S.autoscroll) box.scrollTop = box.scrollHeight;
}
function rerenderLogs() {
  const box = $('#logs');
  box.innerHTML = S.logs.filter(logMatches).map(logHtml).join('');
  if (S.autoscroll) box.scrollTop = box.scrollHeight;
}

/* ------------------------------------------------------------------ websocket */
function setConnected(on) {
  S.connected = on;
  const c = $('#conn');
  c.classList.toggle('on', on);
  c.querySelector('span').textContent = on ? 'live' : 'reconnecting…';
}
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  S.ws = ws;
  ws.onopen = () => setConnected(true);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'state') applyState(msg.data);
    else if (msg.type === 'logs') appendLogs(msg.lines || []);
  };
  ws.onclose = () => { setConnected(false); showOffline('service unreachable — retrying every 2 s'); setTimeout(connect, 2000); };
  ws.onerror = () => ws.close();
}

/* ------------------------------------------------------------------ actions */
const ROW_ACTIONS = {
  login: (u) => run(() => api('POST', '/api/actions/login', { usernames: [u] }), `Login started for @${u}`),
  view: (u) => run(() => api('POST', '/api/actions/view', { username: u })),
  parse: (u) => run(() => api('POST', '/api/actions/parse', { usernames: [u] }), `Parsing groups for @${u}`),
  mailing: (u) => run(() => api('POST', '/api/actions/mailing', { usernames: [u] }), (r) => (r.errors && r.errors.length ? r.errors.join('\n') : `Mailing started for @${u}`)),
  pause: (u) => run(() => api('POST', '/api/actions/pause', { usernames: [u] })),
  settings: (u) => Dialogs.settings(u),
  comments: (u) => Dialogs.comments(u),
  edit: (u) => Dialogs.editAccount(u),
  stat: (u) => Dialogs.dailyStats(u),
  close: (u) => run(() => api('POST', '/api/actions/close', { usernames: [u] }), `Session closed for @${u}`),
  delete: async (u) => {
    if (!await Dialogs.confirm('Delete account', `Delete @${u} permanently? Its browser will be closed.`, 'Delete', 'danger')) return;
    run(() => api('POST', '/api/accounts/delete', { usernames: [u] }), `Deleted @${u}`);
    S.selected.delete(u);
  },
};

const TOOL_ACTIONS = {
  login: async () => {
    const names = requireSelection(); if (!names) return;
    if (names.length > 1 && !await Dialogs.confirm('Login', `Log in ${names.length} accounts one by one, 40 seconds apart?`, 'Start')) return;
    run(() => api('POST', '/api/actions/login', { usernames: names }), (r) => `Login started for ${r.started} account(s). Watch the monitor.`);
  },
  close: () => { const n = requireSelection(); if (n) run(() => api('POST', '/api/actions/close', { usernames: n }), (r) => `Closed ${r.closed} session(s)`); },
  close_all: async () => {
    if (!await Dialogs.confirm('Close all', 'Close every browser and stop all mailing?', 'Close all', 'danger')) return;
    run(() => api('POST', '/api/actions/close', { all: true }), (r) => `All sessions closed (${r.closed})`);
  },
  pause: () => { const n = requireSelection(); if (n) run(() => api('POST', '/api/actions/pause', { usernames: n }), (r) => `Paused ${r.paused}, resumed ${r.resumed}`); },
  reset_errors: () => run(() => api('POST', '/api/actions/reset_errors', {}), (r) => `Error statuses reset: ${r.reset}`),
  mailing: () => { const n = requireSelection(); if (n) run(() => api('POST', '/api/actions/mailing', { usernames: n }), (r) => `Mailing started for ${r.started} of ${n.length}` + (r.errors.length ? `\n${r.errors.join('\n')}` : '')); },
  mail_ready: async () => {
    if (!await Dialogs.confirm('Start all ready', 'Start mailing on every ready account (logged in, has messages, not mailing)?', 'Start')) return;
    run(() => api('POST', '/api/actions/mailing', { ready: true }), (r) => `Mailing started for ${r.started} account(s)`);
  },
  auto_parse: async () => {
    const names = requireSelection(); if (!names) return;
    if (!await Dialogs.confirm('Parse groups', `Collect iChat groups for ${names.length} account(s)? Runs 5 at a time.`, 'Start')) return;
    run(() => api('POST', '/api/actions/parse', { usernames: names }), (r) => `Parsing started for ${r.started} active account(s)`);
  },
  add: () => Dialogs.addAccount(),
  import: () => Dialogs.importAccounts(),
  bulk_edit: () => { const n = requireSelection(); if (n) Dialogs.bulkEdit(n); },
  mass_msg: () => { const n = requireSelection(); if (n) Dialogs.massSettings(n); },
  export_chats: async () => {
    const names = requireSelection(); if (!names) return;
    const r = await run(() => api('POST', '/api/actions/export_chats', { usernames: names }));
    if (r) Dialogs.exportResult(r.path, r.content);
  },
  delete: async () => {
    const names = requireSelection(); if (!names) return;
    const list = names.slice(0, 10).map((u) => `@${u}`).join('\n') + (names.length > 10 ? '\n…' : '');
    if (!await Dialogs.confirm('Delete accounts', `Delete ${names.length} account(s)?\n\n${list}`, 'Delete', 'danger')) return;
    run(() => api('POST', '/api/accounts/delete', { usernames: names }), (r) => `${r.deleted} account(s) deleted`);
    names.forEach((u) => S.selected.delete(u));
  },
  history: () => Dialogs.history(),
};

/* ------------------------------------------------------------------ theme */
function effectiveTheme() {
  const t = document.documentElement.dataset.theme;
  if (t) return t;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
function paintThemeButton() { $('#btn-theme').innerHTML = I(effectiveTheme() === 'dark' ? 'sun' : 'moon'); }

/* ------------------------------------------------------------------ init */
function bindEvents() {
  $('#rows').addEventListener('click', (ev) => {
    const tr = ev.target.closest('tr[data-u]');
    if (!tr) return;
    const u = tr.dataset.u;
    const btn = ev.target.closest('[data-act]');
    if (btn) { ROW_ACTIONS[btn.dataset.act](u); return; }
    if (ev.target.matches('[data-chk]')) {
      if (ev.target.checked) S.selected.add(u); else S.selected.delete(u);
      tr.classList.toggle('selected', ev.target.checked);
      renderSelectionCount();
      $('#chk-all').checked = filteredRows().every((a) => S.selected.has(a.username));
    }
  });
  $('#chk-all').addEventListener('change', (ev) => {
    filteredRows().forEach((a) => (ev.target.checked ? S.selected.add(a.username) : S.selected.delete(a.username)));
    renderTable();
  });
  $('#sel-clear').addEventListener('click', () => { S.selected.clear(); renderTable(); });
  $('#f-search').addEventListener('input', (ev) => { S.q = ev.target.value; renderTable(); });
  $('#f-group').addEventListener('change', (ev) => { S.group = ev.target.value; renderTable(); });
  $('#f-status').addEventListener('change', (ev) => { S.status = ev.target.value; renderTable(); });
  $$('[data-tool]').forEach((b) => b.addEventListener('click', () => TOOL_ACTIONS[b.dataset.tool]()));

  $('#log-filter').addEventListener('input', (ev) => { S.logFilter = ev.target.value; rerenderLogs(); });
  $('#log-autoscroll').addEventListener('change', (ev) => { S.autoscroll = ev.target.checked; });
  $('#log-copy').addEventListener('click', () => {
    navigator.clipboard.writeText(S.logs.filter(logMatches).join('\n')).then(() => toast('Log copied', 'ok'), () => toast('Clipboard unavailable', 'warn'));
  });
  $('#log-clear').addEventListener('click', () => { S.logs = []; rerenderLogs(); });
  $('#log-toggle').addEventListener('click', () => {
    const p = $('#logpanel'); p.classList.toggle('collapsed');
    $('#log-toggle').innerHTML = I(p.classList.contains('collapsed') ? 'chevron-up' : 'chevron-down');
  });
  $('#btn-theme').addEventListener('click', () => {
    const next = effectiveTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('xg-theme', next); } catch (e) { /* ignore */ }
    paintThemeButton();
  });
  $('#btn-help').addEventListener('click', () => Dialogs.help());
  $('#btn-shutdown').addEventListener('click', async () => {
    if (!await Dialogs.confirm('Exit', 'Close every browser and stop X-Genius?', 'Exit', 'danger')) return;
    run(() => api('POST', '/api/shutdown', {}), 'Shutting down…');
  });
  $('#setup-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const r = await run(() => api('POST', '/api/setup', { base_dir: $('#setup-dir').value, create: $('#setup-create').checked }));
    if (r && r.warnings && r.warnings.length) toast(r.warnings.join('\n'), 'warn', 9000);
    if (r) refreshState();
  });
}
async function refreshState() {
  try { applyState(await api('GET', '/api/state')); } catch (e) { if (!S.data) enterDemo(); }
}

document.addEventListener('DOMContentLoaded', () => {
  let saved = '';
  try { saved = localStorage.getItem('xg-theme') || ''; } catch (e) { /* ignore */ }
  if (saved) document.documentElement.dataset.theme = saved;
  injectIcons();
  $('#btn-help').innerHTML = I('help-circle');
  $('#log-toggle').innerHTML = I('chevron-down');
  paintThemeButton();
  bindEvents();
  refreshState();
  connect();
});
