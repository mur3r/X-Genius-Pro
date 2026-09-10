/* X-Genius web UI — modal dialogs and forms. Uses api/toast/run/S/esc from app.js and I() from icons.js. */
'use strict';

const Dialogs = (() => {
  /* ---------------------------------------------------------------- modal core */
  function open({ title, icon, body, buttons = [], wide = false }) {
    const root = document.getElementById('modal-root');
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `<div class="modal ${wide ? 'wide' : ''}" role="dialog" aria-label="${esc(title)}">
      <div class="modal-head">${icon ? I(icon, 16) : ''}${esc(title)}<button class="btn icon ghost x" data-x title="Close">${I('x')}</button></div>
      <div class="modal-body">${body}</div>
      <div class="modal-foot"></div></div>`;
    const dlg = { el: overlay, body: overlay.querySelector('.modal-body'), close: () => overlay.remove() };
    const foot = overlay.querySelector('.modal-foot');
    buttons.forEach((b) => {
      const btn = document.createElement('button');
      btn.className = `btn ${b.kind || ''}`;
      btn.textContent = b.label;
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try { if (b.onClick) await b.onClick(dlg); } finally { btn.disabled = false; }
      });
      foot.appendChild(btn);
    });
    overlay.querySelector('[data-x]').addEventListener('click', dlg.close);
    overlay.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') dlg.close(); });
    overlay.addEventListener('click', (ev) => { if (ev.target === overlay) dlg.close(); });
    root.appendChild(overlay);
    const first = overlay.querySelector('input:not([type=checkbox]), textarea, select, button');
    if (first) first.focus();
    return dlg;
  }

  function confirm(title, text, okLabel = 'OK', kind = 'primary') {
    return new Promise((resolve) => {
      const dlg = open({
        title, icon: kind === 'danger' ? 'alert' : undefined, body: `<div style="white-space:pre-wrap;line-height:1.55">${esc(text)}</div>`,
        buttons: [
          { label: 'Cancel', kind: 'ghost', onClick: (d) => { d.close(); resolve(false); } },
          { label: okLabel, kind, onClick: (d) => { d.close(); resolve(true); } },
        ],
      });
      dlg.el.querySelector('[data-x]').addEventListener('click', () => resolve(false));
      dlg.el.addEventListener('click', (ev) => { if (ev.target === dlg.el) resolve(false); });
    });
  }

  const field = (label, name, value = '', opts = {}) => `<label class="field"><span>${esc(label)}</span>
    <input name="${name}" type="${opts.type || 'text'}" value="${esc(value)}" placeholder="${esc(opts.placeholder || '')}" ${opts.mono ? 'class="mono"' : ''} ${opts.attrs || ''}></label>`;
  const formData = (dlg) => Object.fromEntries(Array.from(dlg.body.querySelectorAll('[name]')).map((el) => [el.name, el.type === 'checkbox' ? el.checked : el.value]));
  const accountFields = (a = {}) => `<div class="grid2">
      ${field('Username', 'username', a.username, { mono: true })}${field('Password', 'password', a.password, { type: 'password' })}
      ${field('Proxy (host:port:user:pass)', 'proxy', a.proxy, { mono: true })}${field('User-Agent (optional)', 'user_agent', a.user_agent)}
      ${field('Group', 'group', a.group)}${field('Auth token', 'auth_token', a.auth_token, { mono: true })}
      ${field('CT0 token', 'ct0_token', a.ct0_token, { mono: true })}
    </div>`;

  /* ---------------------------------------------------------------- accounts */
  function addAccount() {
    open({
      title: 'Add account', icon: 'plus', body: accountFields() + '<div class="hint">A password or an auth token is required.</div>',
      buttons: [{ label: 'Cancel', kind: 'ghost', onClick: (d) => d.close() }, {
        label: 'Add account', kind: 'primary',
        onClick: async (d) => { if (await run(() => api('POST', '/api/accounts', formData(d)), 'Account added')) d.close(); },
      }],
    });
  }

  function importAccounts() {
    open({
      title: 'Import accounts', icon: 'upload', wide: true,
      body: `<div class="hint">One account per line: <code>username|auth_token|ct0_token|proxy|group</code>. Only username and auth_token are required;
        existing usernames are skipped. Paste the contents of your accounts file here.</div>
        <textarea name="text" rows="14" placeholder="user1|auth|ct0|host:port:login:pass|group A"></textarea>`,
      buttons: [{ label: 'Cancel', kind: 'ghost', onClick: (d) => d.close() }, {
        label: 'Import', kind: 'primary',
        onClick: async (d) => {
          const r = await run(() => api('POST', '/api/accounts/import', formData(d)), (x) => `Imported ${x.added}, skipped ${x.skipped}`);
          if (r) d.close();
        },
      }],
    });
  }

  async function editAccount(username) {
    const a = await run(() => api('GET', `/api/accounts/${encodeURIComponent(username)}`));
    if (!a) return;
    open({
      title: `Edit @${username}`, icon: 'edit-2', body: accountFields(a),
      buttons: [{ label: 'Cancel', kind: 'ghost', onClick: (d) => d.close() }, {
        label: 'Save changes', kind: 'primary',
        onClick: async (d) => { if (await run(() => api('PUT', `/api/accounts/${encodeURIComponent(username)}`, formData(d)), 'Account saved')) d.close(); },
      }],
    });
  }

  function bulkEdit(usernames) {
    open({
      title: `Bulk edit · ${usernames.length} accounts`, icon: 'edit-3',
      body: `<label class="check"><input name="chg_group" type="checkbox"> Change group</label>
        ${field('New group name', 'group', '')}
        <label class="check"><input name="chg_proxy" type="checkbox"> Change proxy</label>
        <div class="hint">One proxy for all, or one per account on separate lines (${usernames.length} lines, same order as selected).</div>
        <textarea name="proxies" rows="6"></textarea>`,
      buttons: [{ label: 'Cancel', kind: 'ghost', onClick: (d) => d.close() }, {
        label: 'Apply', kind: 'primary',
        onClick: async (d) => {
          const f = formData(d);
          const body = { usernames };
          if (f.chg_group) body.group = f.group;
          if (f.chg_proxy) body.proxies = f.proxies;
          if (await run(() => api('POST', '/api/accounts/bulk_edit', body), (x) => `Updated ${x.updated} account(s)`)) d.close();
        },
      }],
    });
  }

  /* ---------------------------------------------------------------- settings */
  const cycleFields = (c = {}) => `<div class="grid4">
      ${field('Messages per cycle', 'messages_per_cycle', c.messages_per_cycle ?? 16, { type: 'number' })}
      ${field('Rest time, min', 'rest_time_minutes', c.rest_time_minutes ?? 30, { type: 'number' })}
      ${field('Retweets per cycle', 'retweet_count', c.retweet_count ?? 0, { type: 'number' })}
      ${field('Retweet limit / 24h', 'max_total_retweets', c.max_total_retweets ?? 0, { type: 'number' })}
    </div>
    <label class="check"><input name="media_enabled" type="checkbox" ${c.media_enabled ? 'checked' : ''}> Attach a random GIF</label>`;

  function messageBox(m, i) {
    return `<div class="msgbox" data-msg>
      <div class="row"><b>Message ${i + 1}</b><span class="spacer"></span>
        <span class="sub">send</span><input data-count type="number" min="1" value="${m.count ?? 1}" style="width:64px"><span class="sub">times, then next</span>
        <button class="row-act err" data-rm title="Remove">${I('x', 14)}</button></div>
      <textarea data-text placeholder="Message text…">${esc(m.text ?? '')}</textarea></div>`;
  }
  function messagesEditor(list) {
    const items = list && list.length ? list : [{ text: '', count: 1 }];
    return `<div class="section-title">Mailing messages<span class="spacer"></span><button class="btn sm" data-add-msg>${I('plus', 13)} Add variation</button></div>
      <div data-msgs>${items.map(messageBox).join('')}</div>`;
  }
  function wireMessages(dlg) {
    const box = dlg.body.querySelector('[data-msgs]');
    dlg.body.querySelector('[data-add-msg]').addEventListener('click', () => {
      box.insertAdjacentHTML('beforeend', messageBox({ text: '', count: 1 }, box.children.length));
    });
    box.addEventListener('click', (ev) => {
      const rm = ev.target.closest('[data-rm]');
      if (rm && box.children.length > 1) rm.closest('[data-msg]').remove();
    });
  }
  const readMessages = (dlg) => Array.from(dlg.body.querySelectorAll('[data-msg]')).map((m) => ({
    text: m.querySelector('[data-text]').value, count: parseInt(m.querySelector('[data-count]').value, 10) || 1,
  }));
  const readCycle = (dlg) => {
    const f = formData(dlg);
    return { messages_per_cycle: f.messages_per_cycle, rest_time_minutes: f.rest_time_minutes, retweet_count: f.retweet_count,
      max_total_retweets: f.max_total_retweets, media_enabled: !!f.media_enabled };
  };

  async function settings(username) {
    const s = await run(() => api('GET', `/api/accounts/${encodeURIComponent(username)}/settings`));
    if (!s) return;
    const disabled = Object.keys(s.disabled || {});
    const dlg = open({
      title: `Settings · @${username}`, icon: 'sliders', wide: true,
      body: `<div class="section-title">Cycle</div>${cycleFields(s.cycle)}
        ${messagesEditor(s.messages)}
        <div class="section-title">Groups<span class="spacer"></span>
          <button class="btn sm" data-parse>${I('layers', 13)} Parse now</button><button class="btn sm outline-danger" data-clear>${I('trash-2', 13)} Clear</button></div>
        <div class="hint">Saved for this account: <b>${s.groups_count}</b> · in cache: <b>${s.chat_cache}</b> · temporarily disabled: <b>${disabled.length}</b>.
          Groups are collected again from iChat every time mailing starts.
          ${disabled.length ? `<details><summary>disabled groups</summary><pre class="help">${esc(disabled.map((g) => `${g} — ${s.disabled[g].reason || ''}`).join('\n'))}</pre></details>` : ''}</div>`,
      buttons: [{ label: 'Cancel', kind: 'ghost', onClick: (d) => d.close() }, {
        label: 'Save settings', kind: 'primary',
        onClick: async (d) => {
          const body = { cycle: readCycle(d), messages: readMessages(d) };
          if (await run(() => api('PUT', `/api/accounts/${encodeURIComponent(username)}/settings`, body), 'Settings saved and applied')) d.close();
        },
      }],
    });
    wireMessages(dlg);
    dlg.body.querySelector('[data-parse]').addEventListener('click', () => run(() => api('POST', '/api/actions/parse', { usernames: [username] }), 'Parsing started'));
    dlg.body.querySelector('[data-clear]').addEventListener('click', async () => {
      if (await confirm('Clear groups', `Remove all saved groups for @${username}?`, 'Clear', 'danger')) {
        run(() => api('POST', '/api/actions/clear_groups', { username }), 'Groups cleared');
      }
    });
  }

  async function massSettings(usernames) {
    const s = await run(() => api('GET', `/api/accounts/${encodeURIComponent(usernames[0])}/settings`));
    if (!s) return;
    const dlg = open({
      title: `Mass messages · ${usernames.length} accounts`, icon: 'list', wide: true,
      body: `<div class="grid2"><label class="check"><input name="update_settings" type="checkbox" checked> Update cycle settings</label>
        <label class="check"><input name="update_messages" type="checkbox" checked> Update messages</label></div>
        <div class="hint">Cycle values are loaded from @${esc(usernames[0])}. The message list starts empty, so “Append” never copies texts between accounts.</div>
        <div class="section-title">Cycle</div>${cycleFields(s.cycle)}
        ${messagesEditor([{ text: '', count: 1 }])}`,
      buttons: [
        { label: 'Cancel', kind: 'ghost', onClick: (d) => d.close() },
        { label: 'Append to existing', kind: 'ok', onClick: (d) => submitMass(d, 'append') },
        { label: 'Overwrite all', kind: 'danger', onClick: (d) => submitMass(d, 'overwrite') },
      ],
    });
    wireMessages(dlg);
    async function submitMass(d, mode) {
      const f = formData(d);
      const body = { usernames, mode, update_settings: !!f.update_settings, update_messages: !!f.update_messages, cycle: readCycle(d), messages: readMessages(d) };
      const hasText = body.messages.some((m) => m.text.trim());
      if (mode === 'overwrite' && body.update_messages && !hasText) {
        if (!await confirm('Empty message list', 'This will delete all messages on the selected accounts. Continue?', 'Delete messages', 'danger')) return;
      }
      const q = mode === 'append' ? `Append the new messages to ${usernames.length} accounts? Existing messages stay.`
        : `Overwrite settings on ${usernames.length} accounts? Existing messages will be deleted.`;
      if (!await confirm(mode === 'append' ? 'Append' : 'Overwrite', q, mode === 'append' ? 'Append' : 'Overwrite', mode === 'append' ? 'ok' : 'danger')) return;
      if (await run(() => api('POST', '/api/settings/mass', body), (x) => `${mode === 'append' ? 'Appended to' : 'Overwritten on'} ${x.updated} account(s)`)) d.close();
    }
  }

  async function comments(username) {
    const c = await run(() => api('GET', `/api/accounts/${encodeURIComponent(username)}/comments`));
    if (!c) return;
    open({
      title: `Comments · @${username}`, icon: 'message-circle',
      body: `<label class="check"><input name="enabled" type="checkbox" ${c.enabled ? 'checked' : ''}> Comment during rest time</label>
        ${field('Targets file (one username per line)', 'targets_file', c.targets_file, { mono: true, placeholder: 'D:\\targets.txt' })}
        ${field('Comments text file', 'comments_file', c.comments_file, { mono: true, placeholder: 'D:\\comments.txt' })}
        ${field('Photo folder (random image) or single file', 'photo_path', c.photo_path, { mono: true, placeholder: 'D:\\photos' })}
        ${field('Daily limit', 'daily_limit', c.daily_limit ?? 0, { type: 'number' })}
        <div class="hint">Paths are on the machine where X-Genius runs.</div>`,
      buttons: [{ label: 'Cancel', kind: 'ghost', onClick: (d) => d.close() }, {
        label: 'Save', kind: 'primary',
        onClick: async (d) => { if (await run(() => api('PUT', `/api/accounts/${encodeURIComponent(username)}/comments`, formData(d)), 'Comment settings saved')) d.close(); },
      }],
    });
  }

  /* ---------------------------------------------------------------- stats / misc */
  async function dailyStats(username) {
    const s = await run(() => api('GET', `/api/stats/daily/${encodeURIComponent(username)}`));
    if (!s) return;
    open({
      title: `Last 24 hours · @${username}`, icon: 'bar-chart-2',
      body: `<div class="kv"><span>Messages sent, 24 h</span><b>${s.messages_24h}</b><span>Messages this session</span><b>${s.messages_total}</b><span>Comments today</span><b>${s.comments_today}</b></div>`,
      buttons: [{ label: 'Close', kind: 'primary', onClick: (d) => d.close() }],
    });
  }

  function history() {
    const iso = (d) => d.toISOString().slice(0, 10);
    const today = new Date();
    const ago = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d; };
    const dlg = open({
      title: 'History', icon: 'bar-chart-2', wide: true,
      body: `<div class="cgroup" style="flex-wrap:wrap;gap:8px;margin-bottom:12px">
          <button class="btn sm" data-q="0,1">Today</button><button class="btn sm" data-q="1,1">Yesterday</button>
          <button class="btn sm" data-q="7,0">7 days</button><button class="btn sm" data-q="30,0">30 days</button>
          <span class="spacer"></span>
          <label class="check sm">From <input name="from" type="date" value="${iso(ago(30))}"></label>
          <label class="check sm">To <input name="to" type="date" value="${iso(today)}"></label>
          <button class="btn sm primary" data-refresh>Refresh</button>
          <a class="btn sm" data-csv href="#" download>${I('download', 13)} CSV</a></div>
        <div data-table><div class="muted">Loading…</div></div>`,
      buttons: [{ label: 'Close', kind: 'ghost', onClick: (d) => d.close() }],
    });
    const load = async () => {
      const f = formData(dlg);
      dlg.body.querySelector('[data-csv]').href = `/api/stats/history.csv?from=${f.from}&to=${f.to}`;
      const r = await run(() => api('GET', `/api/stats/history?from=${f.from}&to=${f.to}`));
      if (!r) return;
      const rows = r.rows.map((x) => `<tr><td>@${esc(x.username)}</td><td>${x.msg_period}</td><td>${x.rt_period}</td><td>${x.comm_period}</td>
        <td>${x.msg_total}</td><td>${x.rt_total}</td><td>${x.comm_total}</td><td><button class="row-act err" data-del="${esc(x.username)}" title="Delete stats">${I('trash-2', 14)}</button></td></tr>`).join('');
      const t = r.totals;
      dlg.body.querySelector('[data-table]').innerHTML = `<table class="stats-table"><thead><tr><th>Account</th><th>Msg · period</th><th>RT · period</th>
        <th>Comm · period</th><th>Msg · total</th><th>RT · total</th><th>Comm · total</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="8" class="muted">No activity in this period</td></tr>'}
        <tr class="total"><td>Total</td><td>${t.msg_period}</td><td>${t.rt_period}</td><td>${t.comm_period}</td><td>${t.msg_total}</td><td>${t.rt_total}</td><td>${t.comm_total}</td><td></td></tr></tbody></table>`;
    };
    dlg.body.addEventListener('click', async (ev) => {
      const q = ev.target.closest('[data-q]');
      const del = ev.target.closest('[data-del]');
      if (q) {
        const [days, single] = q.dataset.q.split(',').map(Number);
        dlg.body.querySelector('[name=from]').value = iso(ago(days));
        dlg.body.querySelector('[name=to]').value = iso(single ? ago(days) : today);
        load();
      } else if (ev.target.closest('[data-refresh]')) {
        load();
      } else if (del) {
        const u = del.dataset.del;
        if (await confirm('Delete stats', `Permanently delete statistics for @${u}?`, 'Delete', 'danger')) {
          await run(() => api('DELETE', `/api/stats/${encodeURIComponent(u)}`), 'Stats deleted');
          load();
        }
      }
    });
    load();
  }

  function exportResult(path, content) {
    return open({
      title: 'Export chats', icon: 'download', wide: true,
      body: `<div class="hint">Saved to <code>${esc(path)}</code></div><textarea rows="18" readonly>${esc(content)}</textarea>`,
      buttons: [{ label: 'Copy', kind: 'ghost', onClick: () => navigator.clipboard.writeText(content).then(() => toast('Copied', 'ok')) },
        { label: 'Close', kind: 'primary', onClick: (d) => d.close() }],
    });
  }

  async function help() {
    let text = '';
    try { text = await (await fetch('/api/help')).text(); } catch (e) { text = 'Help is unavailable.'; }
    open({ title: 'Help', icon: 'help-circle', wide: true, body: `<pre class="help">${esc(text)}</pre>`,
      buttons: [{ label: 'Close', kind: 'primary', onClick: (d) => d.close() }] });
  }

  return { open, confirm, addAccount, importAccounts, editAccount, bulkEdit, settings, massSettings, comments, dailyStats, history, exportResult, help };
})();
