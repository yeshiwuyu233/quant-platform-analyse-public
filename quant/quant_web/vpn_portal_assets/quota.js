'use strict';
(() => {
  const root = document.getElementById('quota-root');
  if (!root) return;
  root.hidden = true;
  const $ = name => root.querySelector(`[data-quota="${name}"]`);
    const state = { boot: null, user: null, admin: false, enabled: false, users: [], targetId: null, dialogTargetId: null, policyOriginal: null, policyInitialDisplay: null, policyDirty: new Set(), policyBaseDirty: new Set(), policyExplicit: new Set(), policyDuration: null, policyComputedStart: null, policyDraftExpiry: null, policyBaseStart: null, policyBaseExpiry: null, policyComputedDisplay: null, sequence: 0, busy: false, stopped: false, quota: null, usage: null, audit: [], refreshTimer: null };

  const el = (tag, cls, label) => { const n = tag === 'svg' ? document.createElementNS('http://www.w3.org/2000/svg', tag) : document.createElement(tag); if (cls) n.className = cls; if (label !== undefined) n.textContent = label; return n; };
  function emit(name, detail) { document.dispatchEvent(new CustomEvent(name, { detail })); }
  function safeUser(value) {
    if (!value) return null;
    const result = {};
    for (const key of ['id', 'name', 'username', 'role']) {
      const field = value[key];
      if (field === null || ['string', 'number', 'boolean'].includes(typeof field)) result[key] = field;
    }
    return result;
  }
  function make(tag, attrs = {}, text) { const n = el(tag, attrs.class || '', text); Object.entries(attrs).forEach(([k,v]) => { if (k !== 'class') n.setAttribute(k, String(v)); }); return n; }
  function buildUI() {
    root.classList.add('quota-root'); root.setAttribute('aria-labelledby', 'quota-heading'); root.replaceChildren();
    const header = el('div', 'quota-heading');
    const intro = el('div'); intro.append(el('p', 'quota-eyebrow', 'ACCOUNT QUOTA'), make('h2', { id: 'quota-heading' }, '额度与用量'), make('p', { class: 'quota-muted', 'data-quota': 'target-title' }, '我的额度'));
    const actions = el('div', 'quota-heading-actions');
    const pickerWrap = el('label', 'quota-picker-wrap', '管理对象'); pickerWrap.dataset.quota = 'target-picker-wrap'; const picker = make('select', { 'data-quota': 'target-picker', 'aria-label': '选择额度管理对象' }); pickerWrap.append(picker);
    const refresh = make('button', { type: 'button', class: 'quota-button', 'data-quota': 'refresh' }, '刷新');
    actions.append(pickerWrap, refresh); header.append(intro, actions);
    const note = make('p', { class: 'quota-note', 'data-quota': 'self-admin-note', hidden: '' }, '管理员账户显示无限量、不限速，并继续记录实际上下行用量。');
    const stateRow = el('div', 'quota-state-row'); stateRow.append(make('strong', { 'data-quota': 'quota-state' }, '读取中…'), make('span', { 'data-quota': 'quota-expiry' }, ''));
    const content = make('div', { 'data-quota': 'quota-content', hidden: '' });
    const summary = make('div', { class: 'quota-summary', 'data-quota': 'summary' });
    const speeds = el('div', 'quota-speeds'); speeds.append(el('span', '', '下载限速'), make('strong', { 'data-quota': 'speed-down' }, '未知'), el('span', '', '上传限速'), make('strong', { 'data-quota': 'speed-up' }, '未知'));
    const chartPanel = el('section', 'quota-chart-panel'); const chartHead = el('div', 'quota-subhead'); chartHead.append(make('h3', {}, '近期用量'), make('small', { 'data-quota': 'last-refresh' }, ''));
    const legend = el('div', 'quota-legend'); legend.append(el('span', 'down-key', '下载'), el('span', 'up-key', '上传'));
    const chartWrap = el('div', 'quota-chart-wrap'); chartWrap.append(make('svg', { 'data-quota': 'chart', role: 'img', 'aria-label': '近七天上传与下载用量' }), make('p', { class: 'quota-chart-empty', 'data-quota': 'chart-empty', hidden: '' }, ''));
    const totals = el('p', 'quota-totals'); totals.append(make('span', { 'data-quota': 'usage-down' }, '下载 未知'), make('span', { 'data-quota': 'usage-up' }, '上传 未知'));
    chartPanel.append(chartHead, legend, chartWrap, totals, make('p', { class: 'quota-footnote', 'data-quota': 'usage-start' }, ''));
    const admin = make('section', { class: 'quota-admin-tools', 'data-quota': 'admin-tools', hidden: '' });
    const adminHead = el('div', 'quota-subhead'); adminHead.append(make('h3', {}, '额度管理'), make('span', { class: 'quota-admin-buttons' }, ''));
    const buttons = adminHead.querySelector('.quota-admin-buttons'); buttons.append(make('button', { type: 'button', class: 'quota-button', 'data-quota': 'edit-policy' }, '调整套餐与限速'), make('button', { type: 'button', class: 'quota-button quota-button-primary', 'data-quota': 'add-grant' }, '追加流量'));
    const audit = make('ol', { class: 'quota-audit', 'data-quota': 'audit', 'aria-label': '额度变更记录' });
    admin.append(adminHead, make('p', { class: 'quota-muted' }, '变更会记录操作者与时间。追加永久流量不会随月套餐到期。'), audit);
    content.append(summary, speeds, chartPanel, admin);
    const statusBox = make('p', { class: 'quota-status', 'data-quota': 'status', role: 'status', 'aria-live': 'polite' }, '正在识别账户…');
    root.append(header, note, stateRow, statusBox, content, policyDialog(), grantDialog());
  }
  function closeButton(id) {
    const button=make('button',{type:'button',class:'quota-icon-button','data-close-dialog':id,'aria-label':'关闭'});
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');
    svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.7');svg.setAttribute('stroke-linecap','round');svg.setAttribute('aria-hidden','true');
    path.setAttribute('d','M6 6l12 12M18 6L6 18');svg.append(path);button.append(svg);return button;
  }
  function policyDialog() {
    const d = make('dialog', { id: 'policy-dialog', class: 'quota-dialog', 'aria-labelledby': 'policy-title' });
    const form = make('form', { 'data-quota': 'policy-form', novalidate: '' });
    const head = el('div', 'quota-dialog-heading'); head.append(make('h3', { id: 'policy-title' }, '调整套餐与限速'), closeButton('policy-dialog'));
    const current = make('p', { class: 'quota-current-state', 'data-quota': 'policy-current-status' }, '');
    const duration = el('fieldset', 'quota-choice-group'); duration.append(make('legend', { 'data-quota':'duration-title' }, '开通时长'));
    [['1w','一周'],['1m','一个月'],['3m','一个季度'],['6m','半年'],['12m','一年']].forEach(([v,t]) => duration.append(make('button', { type: 'button', class: 'quota-choice', 'data-quota-duration': v, 'aria-pressed': 'false' }, t)));
    duration.append(make('small', { class: 'quota-field-hint', 'data-quota':'duration-hint' }, '每月按开通日重置；季度 100 GB 表示每月 100 GB。'));
    const amount = el('fieldset', 'quota-choice-group'); amount.append(make('legend', {}, '每月额度（GB）'));
    [['20','20 GB'],['50','50 GB'],['100','100 GB'],['200','200 GB'],['500','500 GB']].forEach(([v,t]) => amount.append(make('button', { type: 'button', class: 'quota-choice', 'data-quota-amount': v, 'aria-pressed': 'false' }, t)));
    amount.append(field('自定义每月额度（GB）', input('number','monthly_gb', '0')));
    const speedGroup = el('fieldset', 'quota-choice-group'); speedGroup.append(make('legend', {}, '下载 / 上传（Mbps）'));
    [['10/5','10/5'],['20/5','20/5'],['50/10','50/10'],['100/20','100/20']].forEach(([v,t]) => speedGroup.append(make('button', { type: 'button', class: 'quota-choice', 'data-quota-speed': v, 'aria-pressed': 'false' }, t)));
    const speeds = el('div', 'quota-form-grid'); const down = input('number','download_mbps'); down.min = '0.001'; down.placeholder = '留空表示不限速'; const up = input('number','upload_mbps'); up.min = '0.001'; up.placeholder = '留空表示不限速'; speeds.append(field('下载（Mbps）',down), field('上传（Mbps）',up));
    const advanced = make('details', { class: 'quota-advanced' }); advanced.append(make('summary', {}, '高级设置'));
    const mode = make('select', { name: 'mode' }); [['monthly','月套餐'],['permanent','永久额度'],['unlimited','无限量']].forEach(([v,t]) => { const o = el('option','',t); o.value = v; mode.append(o); });
    const advancedFields = el('div', 'quota-form-grid'); advancedFields.append(field('套餐类型', mode), field('永久余额（GB）', input('number','permanent_gb', '0')), field('开通日期（北京时间）', input('datetime-local','start_at')), field('套餐到期（北京时间）', input('datetime-local','expires_at'))); advanced.append(advancedFields, make('p', { class: 'quota-warning', 'data-quota': 'policy-warning' }, ''));
    const preview = make('p', { class: 'quota-policy-preview', 'data-quota': 'policy-preview', 'aria-live': 'polite' }, '');
    form.append(head,make('p',{class:'quota-dialog-target','data-quota':'policy-target'}), current, duration, amount, speedGroup, speeds, advanced, preview, dialogActions('policy-dialog', 'policy-save', '保存调整'));
    d.append(form); return d;
  }
  function dialogActions(closeId, saveKey, saveText) { const actions = el('div', 'quota-dialog-actions'); actions.append(make('p', {class:'quota-form-error','data-quota':saveKey.replace('save','error'),role:'alert'},''), make('button', { type: 'button', class: 'quota-button', 'data-close-dialog': closeId }, '取消'), make('button', { type: 'submit', class: 'quota-button quota-button-primary', 'data-quota': saveKey }, saveText)); return actions; }
  function grantDialog() {
    const d = make('dialog', { id: 'grant-dialog', class: 'quota-dialog', 'aria-labelledby': 'grant-title' }); const form = make('form', { 'data-quota': 'grant-form', novalidate: '' });
    const head = el('div', 'quota-dialog-heading'); head.append(make('h3', { id: 'grant-title' }, '追加流量'), closeButton('grant-dialog'));
    const amount = input('number','amount_gb'); const validity = make('select', { name: 'validity' }); [['period','当期有效'],['permanent','永久有效']].forEach(([v,t]) => { const o = el('option','',t); o.value=v; validity.append(o); }); const remark = input('text','remark'); remark.maxLength = 200; remark.placeholder = '可选';
    const presets = el('div', 'quota-choice-group quota-grant-presets'); presets.append(make('span', { class: 'quota-choice-label' }, '快捷追加'));
    ['10','50','100'].forEach(v => presets.append(make('button', { type: 'button', class: 'quota-choice', 'data-quota-grant-amount': v }, `${v} GB`)));
    form.append(head,make('p',{class:'quota-dialog-target','data-quota':'grant-target'}), presets, field('追加流量（GB）', amount), field('有效期', validity), field('备注（可选）', remark),make('p',{class:'quota-policy-preview','data-quota':'grant-preview','aria-live':'polite'}), dialogActions('grant-dialog','grant-save','确认追加'));
    d.append(form); return d;
  }
  const gb = (bytes, remaining = false) => {
    if (bytes === null || bytes === undefined || bytes === '' || !Number.isFinite(Number(bytes))) return '未知';
    const n = Math.max(0, Number(bytes));
    if (n === 0) return remaining ? '0 GB（已用尽）' : '0 GB';
    if (n < 1e7) return '< 0.01 GB';
    return `${(n / 1e9).toFixed(2)} GB`;
  };
  const date = value => {
    if (value === null || value === undefined || value === '') return '未设置';
    let n = typeof value === 'string' && !/^\d+(\.\d+)?$/.test(value) ? Date.parse(value) / 1000 : Number(value);
    if (!Number.isFinite(n)) return '未设置';
    return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(n * 1000));
  };
  const localInput = value => {
    if (value === null || value === undefined || value === '') return '';
    let n = typeof value === 'string' && !/^\d+(\.\d+)?$/.test(value) ? Date.parse(value) / 1000 : Number(value);
    if (!Number.isFinite(n)) return '';
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(n * 1000));
    const p = Object.fromEntries(parts.map(x => [x.type, x.value])); return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
  };
  const escapeError = e => e && e.message ? e.message : '请求失败，请稍后重试。';
  function status(text, kind = '') { const n = $('status'); n.textContent = text || ''; n.className = `quota-status${kind ? ` ${kind}` : ''}`; }
  function apiUrl(path) { return `/vpn/api/${path.replace(/^\//, '')}`; }
  async function api(path, options = {}) {
    if (state.stopped) throw new Error('登录状态已过期，请重新登录。');
    const method = String(options.method || 'GET').toUpperCase(), headers = new Headers(options.headers || {});
    if (['POST', 'PATCH', 'DELETE'].includes(method)) { headers.set('X-CSRF-Token', String(state.boot?.csrf_token || '')); headers.set('Content-Type', 'application/json'); }
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(apiUrl(path), { credentials: 'same-origin', cache: 'no-store', ...options, method, headers, signal: controller.signal });
      let payload; try { payload = await response.json(); } catch (_) { payload = null; }
      if (response.status === 401) { state.stopped = true; clearInterval(state.refreshTimer); root.hidden = false; emit('vpn:session-expired'); throw new Error('登录状态已过期，请重新登录后查看额度。'); }
      if (!response.ok) throw new Error(payload?.message || payload?.error || `请求失败（${response.status}）。`);
      return payload || {};
    } catch (e) { if (e.name === 'AbortError') throw new Error('请求超时，请稍后重试。'); if (e instanceof TypeError) throw new Error('网络暂不可用，请稍后重试。'); throw e; }
    finally { clearTimeout(timer); }
  }
  function field(labelText, control) { const l = el('label', 'quota-field', labelText); l.append(control); return l; }
  function input(type, name, value = '') { const n = document.createElement('input'); n.type = type; n.name = name; if (value !== undefined && value !== null) n.value = String(value); if (type === 'number') { n.min = '0'; n.max = name.endsWith('_gb') ? String(Number.MAX_SAFE_INTEGER / 1e9) : '1000000'; n.step = 'any'; inputMode(n, 'decimal'); } return n; }
  function inputMode(n, mode) { n.inputMode = mode; }
  function formatSpeed(value) { return value === null || value === undefined || value === '' || Number(value) <= 0 ? '不限速' : `${Number(value)} Mbps`; }
  function bucket(label, value, detail) { const card = el('article', 'quota-card'); card.append(el('span', 'quota-card-label', label), el('strong', 'quota-card-value', value), el('small', '', detail || '')); return card; }
  function drawChart(usage) {
    const svg = $('chart'); svg.replaceChildren(); const series = Array.isArray(usage?.series) ? usage.series : [];
    const width = Math.max(280, Math.round(svg.parentElement.getBoundingClientRect().width) || Math.min(680, window.innerWidth - 64)), height = 172, pad = { l: 10, r: 10, t: 10, b: 28 }, plotH = height - pad.t - pad.b, plotW = width - pad.l - pad.r;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('preserveAspectRatio', 'none');
    const points = series.filter(p => p.total_bytes !== null && p.total_bytes !== undefined && Number.isFinite(Number(p.total_bytes)));
    const max = Math.max(1, ...points.map(p => Number(p.total_bytes)));
    const add = (tag, attrs, text) => { const n = document.createElementNS('http://www.w3.org/2000/svg', tag); Object.entries(attrs).forEach(([k,v]) => n.setAttribute(k, String(v))); if (text !== undefined) n.textContent = text; svg.append(n); };
    for (let y = 0; y < 3; y++) add('line', { x1: pad.l, y1: pad.t + plotH * y / 2, x2: width - pad.r, y2: pad.t + plotH * y / 2, stroke: 'var(--app-line-soft)', 'stroke-dasharray': y ? '3 4' : '0' });
    const stride = series.length ? plotW / series.length : plotW, barW = Math.min(38, Math.max(8, stride * .46));
    series.forEach((p, i) => {
      const x = pad.l + stride * (i + .5), known = p.total_bytes !== null && p.total_bytes !== undefined && Number.isFinite(Number(p.total_bytes));
      if (known) {
        const down = Number(p.download_bytes || 0), up = Number(p.upload_bytes || 0), dh = plotH * down / max, uh = plotH * up / max;
        if (dh) add('rect', { x: x - barW/2, y: pad.t + plotH - dh, width: barW, height: dh, rx: 3, fill: 'var(--app-accent)' });
        if (uh) add('rect', { x: x - barW/2, y: pad.t + plotH - dh - uh, width: barW, height: uh, rx: 3, fill: 'var(--app-upload)' });
      }
      const stamp = Number(p.start), label = Number.isFinite(stamp) ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' }).format(new Date(stamp * 1000)) : `${i+1}日`;
      if (i % Math.max(1, Math.ceil(series.length / Math.max(2, Math.floor(plotW / 66)))) === 0 || i === series.length - 1) add('text', { x, y: height - 7, 'text-anchor': 'middle', fill: 'var(--app-muted)', 'font-size': 10 }, label);
    });
    svg.setAttribute('aria-label', `用量趋势，${series.length} 个时段，${points.length} 个已记录`);
    const empty = $('chart-empty'); empty.hidden = Boolean(series.length && points.length); empty.textContent = series.length ? '此范围尚无可确认的用量记录；未知时段不会按零显示。' : '尚无用量历史记录。';
    $('usage-down').textContent = '下载 '+gb(usage?.download_bytes); $('usage-up').textContent = '上传 '+gb(usage?.upload_bytes);
    $('usage-start').textContent = usage?.started_at ? `统计自 ${date(usage.started_at)}；此前的用量无法追溯。` : '历史记录从采集启用后开始。';
  }
  function renderAudit(items) {
    const wrap = $('audit'); wrap.replaceChildren();
    if (!items.length) { wrap.append(el('p', 'quota-muted', '暂无变更记录。')); return; }
    items.slice(0, 12).forEach(item => {
      const li = el('li', 'quota-audit-row'), top = el('div', 'quota-audit-top');
      top.append(el('strong', '', item.event || item.action || '额度变更'), el('time', '', date(item.timestamp || item.created_at)));
      const actor = item.actor && typeof item.actor === 'object' ? (item.actor.name || item.actor.username || item.actor.id || '系统') : (item.actor || '系统');
      li.append(top, el('small', '', `操作者：${actor}`));
      const changes = item.changes;
      if (changes && typeof changes === 'object') {
        const details = el('p', 'quota-audit-changes');
        details.textContent = Object.entries(changes).map(([key, val]) => `${key}：${typeof val === 'object' ? JSON.stringify(val) : String(val)}`).join('；'); li.append(details);
      } else if (typeof changes === 'string') li.append(el('p', 'quota-audit-changes', changes));
      wrap.append(li);
    });
  }
  function render() {
    const q = state.quota, user = state.users.find(u => String(u.id) === String(state.targetId)) || state.user;
    root.hidden = false; $('target-title').textContent = user ? `${user.name || user.username || '用户'}${user.username && user.name ? ` · @${user.username}` : ''}` : '我的额度';
    const targetIsAdmin = Boolean(user && user.role === 'admin') || q?.is_admin === true;
    const quotaExempt = targetIsAdmin || (state.admin && String(state.targetId) === String(state.user?.id));
    $('admin-tools').hidden = !state.admin; $('target-picker-wrap').hidden = !state.admin;
    $('target-picker').value = String(state.targetId ?? '');
    updatePickerState();
    $('edit-policy').disabled = !state.admin || quotaExempt; $('add-grant').disabled = !state.admin || quotaExempt;
    $('self-admin-note').hidden = !quotaExempt;
    if (quotaExempt) $('self-admin-note').textContent = targetIsAdmin ? '管理员账户不设置个人配额和限速，并继续记录实际用量。' : '管理员本人显示无限量、不限速，并继续记录实际用量。';
    $('quota-content').hidden = !q;
    if (!q) return;
    if (targetIsAdmin) {
      const used = q.used_bytes === null || q.used_bytes === undefined || q.used_bytes === '' || !Number.isFinite(Number(q.used_bytes)) ? '未知' : gb(q.used_bytes);
      $('summary').replaceChildren(bucket('可用额度', '无限量', '管理员账户免个人额度'), bucket('账本已用', used, '仍持续记录实际流量'));
      $('quota-state').textContent = '管理员 · 无限量 · 不限速'; $('quota-expiry').textContent = '无个人套餐到期或重置时间'; $('speed-down').textContent = '不限速'; $('speed-up').textContent = '不限速';
    } else if (q.unlimited || q.mode === 'unlimited') {
      const used = q.used_bytes === null || q.used_bytes === undefined || q.used_bytes === '' || !Number.isFinite(Number(q.used_bytes)) ? '未知' : gb(q.used_bytes);
      $('summary').replaceChildren(bucket('可用额度', '无限量', '个人流量额度不限量'), bucket('账本已用', used, '')); 
      $('quota-state').textContent = '无限量'; $('quota-expiry').textContent = `套餐到期 ${date(q.expires_at)} · 下次重置 ${date(q.next_reset_at || q.period_end)}`;
      $('speed-down').textContent = formatSpeed(q.download_mbps); $('speed-up').textContent = formatSpeed(q.upload_mbps);
    } else {
      const total = gb(q.remaining_bytes, true);
      const used = q.used_bytes === null || q.used_bytes === undefined || q.used_bytes === '' || !Number.isFinite(Number(q.used_bytes)) ? '未知' : gb(q.used_bytes);
      const permanentLeft = Number(q.permanent_remaining_bytes || 0);
      const remainingKnown = q.remaining_bytes !== null && q.remaining_bytes !== undefined && Number.isFinite(Number(q.remaining_bytes));
      const allowed = q.vpn_enabled === false ? '管理员已停用 VPN' : remainingKnown && Number(q.remaining_bytes) <= 0 ? '额度已用尽，VPN 已暂停' : q.subscription_expired && permanentLeft > 0 ? '月套餐已到期，永久额度仍可用' : q.subscription_expired ? '月套餐已到期' : '可用';
      const usedLabel = q.mode === 'monthly' && !q.subscription_expired ? `本周期已用 ${gb(q.period_used_bytes)} · 账本累计 ${used}` : `账本累计已用 ${used}`;
      $('summary').replaceChildren(bucket('可用总余额', total, usedLabel), bucket('本期套餐剩余', gb(q.monthly_remaining_bytes, true), `套餐 ${gb(q.monthly_bytes)}`), bucket('当期追加剩余', gb(q.period_extra_remaining_bytes, true), '本周期结束或套餐到期时失效'), bucket('永久额度余额', gb(q.permanent_remaining_bytes, true), '独立于月套餐有效期'));
      $('quota-state').textContent = allowed;
      $('quota-expiry').textContent = `套餐到期 ${date(q.expires_at)} · 下次重置 ${date(q.next_reset_at || q.period_end)}`;
      $('speed-down').textContent = formatSpeed(q.download_mbps); $('speed-up').textContent = formatSpeed(q.upload_mbps);
    }
    $('last-refresh').textContent = `最近刷新 ${new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date())}`;
    drawChart(state.usage || {}); renderAudit(state.audit);
  }
  async function fetchQuota(targetId = state.targetId) {
    const version = ++state.sequence, id = targetId;
    status('正在读取额度与用量…'); $('quota-content').hidden = true;
    try {
      const path = state.admin ? `admin/quota/${encodeURIComponent(id)}` : 'quota';
      const payload = await api(path);
      if (version !== state.sequence || String(id) !== String(state.targetId)) return;
      if (!payload.quota) throw new Error('额度接口返回的数据格式无法识别。');
      state.quota = payload.quota; state.usage = payload.usage || {}; state.audit = Array.isArray(payload.audit) ? payload.audit : [];
      render(); status('额度和用量已更新。', 'success');
      emit('vpn:quota', { quota: state.quota, usage: state.usage, audit: state.audit, targetId: String(id), target: safeUser(payload.target_user), meter: payload.meter });
    } catch (e) { if (version === state.sequence) { state.quota = null; $('quota-content').hidden = true; status(escapeError(e), 'error'); emit('vpn:quota-error', { targetId: String(id), message: escapeError(e) }); } }
  }
  async function loadUsers() {
    const payload = await api('admin/users'); state.users = Array.isArray(payload.users) ? payload.users : [];
    const select = $('target-picker'); select.replaceChildren();
    state.users.forEach(u => { const o = document.createElement('option'); o.value = String(u.id); o.textContent = `${u.name || u.username || u.id}${u.username ? ` · @${u.username}` : ''}${u.enabled ? '' : ' · VPN 未开通'}`; select.append(o); });
    if (!state.targetId || !state.users.some(u => String(u.id) === String(state.targetId))) state.targetId = String(state.user.id);
    select.value = String(state.targetId);
  }
  const dialog = id => root.querySelector(`#${id}`);
  function isBusy() { return Boolean(state.busy || state.dialogTargetId || ['policy-dialog', 'grant-dialog'].some(id => dialog(id)?.open)); }
  function updatePickerState() { const selector = $('target-picker'); if (selector) selector.disabled = state.busy || ['policy-dialog','grant-dialog'].some(id => dialog(id)?.open); }
  function modeOf(q) { return q.mode === 'monthly' ? 'monthly' : q.mode === 'permanent' ? 'permanent' : 'unlimited'; }
  function sameNumeric(a, b) { return a === null || a === undefined || a === '' ? b === null || b === undefined || b === '' : Number(a) === Number(b); }
  function setPolicyValue(name, value, { dirty = true, explicit = false } = {}) {
    const form = $('policy-form'); form.elements[name].value = String(value ?? '');
    if (dirty) state.policyDirty.add(name);
    if (explicit) state.policyExplicit.add(name);
    else if (state.policyBaseDirty.has(name) || state.policyInitialDisplay?.[name] !== form.elements[name].value) state.policyDirty.add(name);
    else state.policyDirty.delete(name);
  }
  function updatePolicyPreview() {
    const form = $('policy-form'); if (!form || !state.policyOriginal) return;
    const mode = form.elements.mode.value, monthly = Number(form.elements.monthly_gb.value || 0);
    const speed = `下载 ${formatSpeed(form.elements.download_mbps.value)} · 上传 ${formatSpeed(form.elements.upload_mbps.value)}`;
    const startValue = state.policyExplicit.has('start_at') ? localEpoch(form.elements.start_at.value) : (state.policyComputedStart ?? state.policyOriginal.start_at);
    const expiryValue = state.policyExplicit.has('expires_at') ? localEpoch(form.elements.expires_at.value, true) : (state.policyDraftExpiry ?? state.policyOriginal.expires_at);
    const current = state.policyOriginal.mode === 'monthly' ? `当前状态：月套餐 ${gb(state.policyOriginal.monthly_bytes)}，到期 ${date(state.policyOriginal.expires_at)}。` : state.policyOriginal.mode === 'permanent' ? `当前状态：永久余额 ${gb(state.policyOriginal.permanent_bytes)}。` : '当前状态：无限量。';
    const proposed = mode === 'monthly' ? `方案：每月 ${monthly} GB，${date(startValue)} 开通，${date(expiryValue)} 到期；每个北京时间月度周期重置。` : mode === 'permanent' ? `方案：永久余额 ${form.elements.permanent_gb.value || '0'} GB。` : '方案：无限量。';
    $('duration-title').textContent = state.policyOriginal.mode === 'monthly' ? '续期时长' : '开通时长';
    $('duration-hint').textContent = state.policyOriginal.mode === 'monthly' ? '从现有到期日续期；已到期则从现在延长。保留原重置日与已用流量。' : '从现在开通，每月重置所选额度；季度 100 GB 表示每月 100 GB，一周套餐仅发放一次。';
    $('policy-current-status').textContent = current;
    $('policy-preview').textContent = `管理对象：${state.dialogTargetLabel}。${proposed} ${speed}。保存才生效。`;
  }
  function monthAddBJ(epoch, months) {
    const dateValue = new Date(Number(epoch) * 1000);
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).formatToParts(dateValue).map(p => [p.type, p.value]));
    const y = Number(parts.year), m = Number(parts.month) - 1, day = Number(parts.day), h = Number(parts.hour), min = Number(parts.minute), sec = Number(parts.second);
    const targetMonth = m + months, lastDay = new Date(Date.UTC(y, targetMonth + 1, 0)).getUTCDate();
    return Math.floor((Date.UTC(y, targetMonth, Math.min(day, lastDay), h, min, sec) - 8 * 3600 * 1000) / 1000);
  }
  function addDurationBJ(epoch, key) { return key === '1w' ? Number(epoch) + 7 * 86400 : monthAddBJ(epoch, ({ '1m':1, '3m':3, '6m':6, '12m':12 })[key] || 1); }
  function setPresetPressed(selector, value) {
    const attr = selector === '[data-quota-duration]' ? 'data-quota-duration' : selector === '[data-quota-amount]' ? 'data-quota-amount' : 'data-quota-speed';
    root.querySelectorAll(selector).forEach(button => button.setAttribute('aria-pressed', value !== null && value !== undefined && button.getAttribute(attr) === String(value) ? 'true' : 'false'));
  }
  function prepareMonthlyDraft(durationKey = '1m') {
    const form = $('policy-form'), original = state.policyOriginal, now = Math.floor(Date.now() / 1000);
    const start = now;
    const existingAmount = Number(form.elements.monthly_gb.value);
    const amount = Number.isFinite(existingAmount) && existingAmount > 0 ? existingAmount : 100;
    const down = form.elements.download_mbps.value || 20, up = form.elements.upload_mbps.value || 5;
    const expiry = addDurationBJ(now, durationKey);
    form.elements.mode.value = 'monthly';
    setPolicyValue('mode', 'monthly'); setPolicyValue('monthly_gb', amount); setPolicyValue('start_at', localInput(start)); setPolicyValue('expires_at', localInput(expiry));
    setPolicyValue('download_mbps', down); setPolicyValue('upload_mbps', up);
    state.policyComputedStart = start; state.policyDraftExpiry = expiry; state.policyDuration = durationKey;
    state.policyBaseStart = start; state.policyBaseExpiry = expiry; state.policyComputedDisplay = { start_at: form.elements.start_at.value, expires_at: form.elements.expires_at.value };
    setPresetPressed('[data-quota-duration]', durationKey); setPresetPressed('[data-quota-amount]', String(amount)); setPresetPressed('[data-quota-speed]', `${down}/${up}`);
    updatePolicyPreview();
  }
  function chooseDuration(key) {
    const form = $('policy-form'), original = state.policyOriginal;
    if (!form || !original) return;
    // A quick duration pick takes precedence over a manually typed date. Its exact
    // computed seconds must survive the datetime-local minute display.
    state.policyExplicit.delete('start_at'); state.policyExplicit.delete('expires_at');
    if (original.mode === 'monthly') {
      const now = Math.floor(Date.now() / 1000), oldExpiry = epochValue(original.expires_at) || 0;
      const expiry = addDurationBJ(Math.max(now, oldExpiry), key);
      state.policyComputedStart = null; state.policyDraftExpiry = expiry; state.policyDuration = key;
      state.policyBaseExpiry = expiry; state.policyComputedDisplay = { start_at: form.elements.start_at.value, expires_at: localInput(expiry) };
      setPolicyValue('expires_at', localInput(expiry), { dirty: true });
      form.elements.mode.value = 'monthly';
      setPresetPressed('[data-quota-duration]', key);
      updatePolicyPreview(); return;
    }
    prepareMonthlyDraft(key);
  }
  function onPolicyFieldEdit(event) {
    const name = event.target.name;
    if (!name) return;
    if (name === 'mode') {
      if (event.target.value === 'monthly' && state.policyOriginal?.mode !== 'monthly' && state.policyDuration === null) prepareMonthlyDraft('1m');
      else if (event.target.value !== 'monthly') { state.policyDuration = null; state.policyDraftExpiry = null; state.policyComputedStart = null; setPresetPressed('[data-quota-duration]', null); }
    }
    if (name === 'start_at') state.policyComputedStart = event.target.value === state.policyComputedDisplay?.start_at ? state.policyBaseStart : null;
    if (name === 'expires_at') {
      const resetToComputed = event.target.value === state.policyComputedDisplay?.expires_at;
      state.policyDraftExpiry = resetToComputed ? state.policyBaseExpiry : null;
      if (!resetToComputed) { state.policyDuration = null; setPresetPressed('[data-quota-duration]', null); }
    }
    if (state.policyInitialDisplay?.[name] === event.target.value) {
      if (state.policyBaseDirty.has(name)) state.policyDirty.add(name); else state.policyDirty.delete(name);
      state.policyExplicit.delete(name);
    } else {
      state.policyDirty.add(name); state.policyExplicit.add(name);
    }
    updatePolicyPreview();
  }
  function openPolicy() {
    const target = state.users.find(u => String(u.id) === String(state.targetId)) || state.user;
    if (!state.admin || target?.role === 'admin' || String(state.targetId) === String(state.user?.id) || state.busy) return;
    freezeDialogTarget('policy');
    const q = state.quota || {}, form = $('policy-form'); form.reset();
    const currentMode = modeOf(q);
    state.policyOriginal = {
      mode: currentMode,
      monthly_bytes: Number.isFinite(Number(q.monthly_bytes)) ? Number(q.monthly_bytes) : 0,
      permanent_bytes: Number.isFinite(Number(q.permanent_remaining_bytes)) ? Number(q.permanent_remaining_bytes) : 0,
      start_at: q.start_at ?? q.period_start ?? null,
      expires_at: q.expires_at ?? null,
      download_mbps: q.download_mbps ?? null,
      upload_mbps: q.upload_mbps ?? null
    };
    form.elements.mode.value = currentMode;
    form.elements.monthly_gb.value = Number(q.monthly_bytes || 0) / 1e9;
    form.elements.permanent_gb.value = Number(q.permanent_remaining_bytes || 0) / 1e9;
    form.elements.start_at.value = localInput(q.start_at || q.period_start);
    form.elements.expires_at.value = localInput(q.expires_at);
    form.elements.download_mbps.value = q.download_mbps ?? ''; form.elements.upload_mbps.value = q.upload_mbps ?? '';
    state.policyComputedStart = null; state.policyDraftExpiry = null; state.policyDuration = null; state.policyBaseStart = null; state.policyBaseExpiry = null; state.policyComputedDisplay = null;
    state.policyDirty = new Set(); state.policyBaseDirty = new Set(); state.policyExplicit = new Set();
    const unused = currentMode !== 'monthly' && Number(q.used_bytes || 0) === 0 && Number(q.remaining_bytes || 0) === 0 && Number(q.monthly_bytes || 0) === 0 && Number(q.permanent_remaining_bytes || 0) === 0;
    const suggested = currentMode === 'unlimited' || unused;
    if (suggested) {
      form.elements.mode.value = 'monthly'; form.elements.monthly_gb.value = '100';
      form.elements.download_mbps.value = q.download_mbps !== null && q.download_mbps !== undefined && Number(q.download_mbps) > 0 ? String(q.download_mbps) : '20';
      form.elements.upload_mbps.value = q.upload_mbps !== null && q.upload_mbps !== undefined && Number(q.upload_mbps) > 0 ? String(q.upload_mbps) : '5';
    }
    if (suggested) {
      const now = Math.floor(Date.now() / 1000), expiry = addDurationBJ(now, '1m');
      form.elements.start_at.value = localInput(now); form.elements.expires_at.value = localInput(expiry);
      state.policyComputedStart = now; state.policyDraftExpiry = expiry; state.policyDuration = '1m';
      state.policyBaseStart = now; state.policyBaseExpiry = expiry; state.policyComputedDisplay = { start_at: form.elements.start_at.value, expires_at: form.elements.expires_at.value };
      const next = { mode:'monthly', monthly_bytes:100e9, start_at:now, expires_at:expiry, download_mbps:Number(form.elements.download_mbps.value), upload_mbps:Number(form.elements.upload_mbps.value) };
      if (state.policyOriginal.mode !== next.mode) state.policyBaseDirty.add('mode');
      if (state.policyOriginal.monthly_bytes !== next.monthly_bytes) state.policyBaseDirty.add('monthly_gb');
      if (epochValue(state.policyOriginal.start_at) !== next.start_at) state.policyBaseDirty.add('start_at');
      if (epochValue(state.policyOriginal.expires_at) !== next.expires_at) state.policyBaseDirty.add('expires_at');
      if (!sameNumeric(state.policyOriginal.download_mbps, next.download_mbps)) state.policyBaseDirty.add('download_mbps');
      if (!sameNumeric(state.policyOriginal.upload_mbps, next.upload_mbps)) state.policyBaseDirty.add('upload_mbps');
      state.policyDirty = new Set(state.policyBaseDirty);
    }
    state.policyInitialDisplay = Object.fromEntries(['mode','monthly_gb','permanent_gb','start_at','expires_at','download_mbps','upload_mbps'].map(name => [name, form.elements[name].value]));
    setPresetPressed('[data-quota-duration]', state.policyDuration);
    setPresetPressed('[data-quota-amount]', form.elements.monthly_gb.value);
    setPresetPressed('[data-quota-speed]', `${form.elements.download_mbps.value}/${form.elements.upload_mbps.value}`);
    $('policy-warning').textContent = '调整永久额度会直接修改永久余额，请核对变更前后值。';
    root.querySelector('#policy-dialog details').open = false;
    $('policy-error').textContent = ''; updatePolicyPreview(); state.dialogTargetId = String(state.targetId); dialog('policy-dialog').showModal(); updatePickerState();
  }
  function freezeDialogTarget(kind) {
    state.dialogTargetId=String(state.targetId);
    const target=state.users.find(u=>String(u.id)===state.dialogTargetId)||{};
    state.dialogTargetLabel=`${target.name||target.username||'用户'}${target.username?' · @'+target.username:''}（ID ${state.dialogTargetId}）`;
    $(kind+'-target').textContent='管理对象：'+state.dialogTargetLabel;
  }
  function updateGrantPreview(){
    const form=$('grant-form'),amount=form.elements.amount_gb.value;
    $('grant-preview').textContent=`向 ${state.dialogTargetLabel} 追加 ${amount||'待填写'} GB，${form.elements.validity.value==='permanent'?'永久有效':'本周期结束或套餐到期时失效'}。确认追加后才生效。`;
  }
  function openGrant() { if (!state.admin || String(state.targetId) === String(state.user?.id) || state.busy) return; $('grant-form').reset(); $('grant-error').textContent = ''; freezeDialogTarget('grant');updateGrantPreview();dialog('grant-dialog').showModal(); updatePickerState(); }
  function localEpoch(value, end = false) { if (!value) return null; const time = value.length === 10 ? `${value}T${end ? '23:59' : '00:00'}` : value; const d = new Date(`${time}:00+08:00`); return Number.isFinite(d.getTime()) ? Math.floor(d.getTime() / 1000) : null; }
  function epochValue(value) {
    if (value === null || value === undefined || value === '') return null;
    const n = typeof value === 'string' && !/^\d+(\.\d+)?$/.test(value) ? Date.parse(value) / 1000 : Number(value);
    return Number.isFinite(n) ? n : null;
  }
  function trackPolicyEdit(event) { onPolicyFieldEdit(event); }
  async function submitPolicy(event) {
    event.preventDefault(); if (state.busy) return;
    const f = event.currentTarget, dirty = state.policyDirty, original = state.policyOriginal;
    if (!original || dirty.size === 0) { $('policy-error').textContent = '没有需要保存的调整。'; return; }
    const mode = f.elements.mode.value;
    const monthly = Number(f.elements.monthly_gb.value), permanent = Number(f.elements.permanent_gb.value);
    const monthlyBytes = dirty.has('monthly_gb') ? monthly * 1e9 : original.monthly_bytes;
    const permanentBytes = dirty.has('permanent_gb') ? permanent * 1e9 : original.permanent_bytes;
    const down = f.elements.download_mbps.value === '' ? null : Number(f.elements.download_mbps.value), up = f.elements.upload_mbps.value === '' ? null : Number(f.elements.upload_mbps.value);
    if ((dirty.has('monthly_gb') && (!Number.isFinite(monthly) || monthly < 0 || !Number.isSafeInteger(Math.round(monthlyBytes)))) || (dirty.has('permanent_gb') && (!Number.isFinite(permanent) || permanent < 0 || !Number.isSafeInteger(Math.round(permanentBytes))))) { $('policy-error').textContent = '额度必须是有效的非负 GB 数值。'; return; }
    if ((dirty.has('download_mbps') && down !== null && (!Number.isFinite(down) || down < 0.001 || down > 1000000)) || (dirty.has('upload_mbps') && up !== null && (!Number.isFinite(up) || up < 0.001 || up > 1000000))) { $('policy-error').textContent = '限速必须在 0.001 到 1,000,000 Mbps 之间；留空表示不限速。'; return; }
    const startValue = state.policyExplicit.has('start_at') ? localEpoch(f.elements.start_at.value) : (state.policyComputedStart ?? original.start_at);
    const expiryValue = state.policyExplicit.has('expires_at') ? localEpoch(f.elements.expires_at.value, true) : (state.policyDraftExpiry ?? original.expires_at);
    const startEpoch = epochValue(startValue), expiryEpoch = epochValue(expiryValue);
    const periodChanged = dirty.has('start_at') || dirty.has('expires_at');
    const modeChangedToMonthly = mode === 'monthly' && original.mode !== 'monthly';
    if (mode === 'monthly' && (modeChangedToMonthly || periodChanged) && (!(monthlyBytes > 0) || startEpoch === null || expiryEpoch === null || expiryEpoch < startEpoch)) { $('policy-error').textContent = '月套餐请填写有效额度、开通日期和不早于开通日的到期日期。'; return; }
    const payload = {};
    if (dirty.has('mode')) payload.mode = mode;
    if (mode === 'monthly') {
      if (dirty.has('monthly_gb') || modeChangedToMonthly) payload.monthly_bytes = Math.round(monthlyBytes);
      if ((dirty.has('start_at') || modeChangedToMonthly) && startValue !== null) payload.start_at = startValue;
      if ((dirty.has('expires_at') || modeChangedToMonthly) && expiryValue !== null) payload.expires_at = expiryValue;
    }
    if (dirty.has('permanent_gb') && mode !== 'unlimited') payload.permanent_bytes = Math.round(permanentBytes);
    if (dirty.has('download_mbps')) payload.download_mbps = down;
    if (dirty.has('upload_mbps')) payload.upload_mbps = up;
    if (!Object.keys(payload).length) {
      $('policy-error').textContent = '没有需要保存的调整。'; return;
    }
    const id = state.dialogTargetId; await mutate('PATCH', `admin/quota/${encodeURIComponent(id)}`, payload, 'policy-error', 'policy-save', id);
  }
  async function submitGrant(event) {
    event.preventDefault(); if (state.busy) return;
    const f = event.currentTarget, amount = Number(f.elements.amount_gb.value), validity = f.elements.validity.value;
    const bytes = amount * 1e9;
    if (!(amount > 0) || !Number.isSafeInteger(Math.round(bytes))) { $('grant-error').textContent = '请输入大于 0 且处于可表示范围内的 GB 数值。'; return; }
    const id = state.dialogTargetId; await mutate('POST', `admin/quota/${encodeURIComponent(id)}/grants`, { amount_bytes: Math.round(bytes), validity, remark: f.elements.remark.value.trim() }, 'grant-error', 'grant-save', id);
  }
  async function mutate(method, path, body, errorKey, buttonKey, targetId) {
    state.busy = true; updatePickerState(); const button = $(buttonKey); button.disabled = true; $(errorKey).textContent = '';
    try { await api(path, { method, body: JSON.stringify(body) }); dialog(errorKey.startsWith('policy') ? 'policy-dialog' : 'grant-dialog').close(); status('变更已保存，正在刷新额度…'); await fetchQuota(targetId); }
    catch (e) { $(errorKey).textContent = escapeError(e); }
    finally { state.busy = false; button.disabled = false; state.dialogTargetId = null; updatePickerState(); }
  }
  function initEvents() {
    $('refresh').addEventListener('click', () => fetchQuota());
    $('target-picker').addEventListener('change', () => { if (state.busy || state.dialogTargetId) return; state.targetId = $('target-picker').value; state.quota = null; fetchQuota(); });
    $('edit-policy').addEventListener('click', openPolicy); $('add-grant').addEventListener('click', openGrant);
    $('policy-form').addEventListener('submit', submitPolicy); $('grant-form').addEventListener('submit', submitGrant);
    $('grant-form').addEventListener('input',updateGrantPreview);$('grant-form').addEventListener('change',updateGrantPreview);
    $('policy-form').addEventListener('input', trackPolicyEdit); $('policy-form').addEventListener('change', trackPolicyEdit);
    root.querySelectorAll('[data-quota-duration]').forEach(button => button.addEventListener('click', () => chooseDuration(button.dataset.quotaDuration)));
    root.querySelectorAll('[data-quota-amount]').forEach(button => button.addEventListener('click', () => {
      const form = $('policy-form');
      if (form.elements.mode.value !== 'monthly') {
        if (state.policyOriginal?.mode === 'monthly') {
          // Returning to the original monthly plan and editing its allowance is
          // a policy adjustment, not a new subscription or a quota refill.
          form.elements.mode.value = 'monthly';
          state.policyDraftExpiry = null; state.policyComputedStart = null; state.policyDuration = null;
          setPolicyValue('mode', 'monthly');
          setPolicyValue('start_at', localInput(state.policyOriginal.start_at), { dirty: false });
          setPolicyValue('expires_at', localInput(state.policyOriginal.expires_at), { dirty: false });
          state.policyInitialDisplay.start_at = form.elements.start_at.value;
          state.policyInitialDisplay.expires_at = form.elements.expires_at.value;
          for (const name of ['start_at','expires_at']) {
            if (state.policyBaseDirty.has(name)) state.policyDirty.add(name); else state.policyDirty.delete(name);
            state.policyExplicit.delete(name);
          }
          setPresetPressed('[data-quota-duration]', null);
        } else prepareMonthlyDraft('1m');
      }
      const field = form.elements.monthly_gb; field.value = button.dataset.quotaAmount;
      state.policyExplicit.add('monthly_gb'); state.policyDirty.add('monthly_gb');
      setPresetPressed('[data-quota-amount]', button.dataset.quotaAmount); updatePolicyPreview();
    }));
    root.querySelectorAll('[data-quota-speed]').forEach(button => button.addEventListener('click', () => {
      const [down, up] = button.dataset.quotaSpeed.split('/'), form = $('policy-form');
      form.elements.download_mbps.value = down; form.elements.upload_mbps.value = up;
      state.policyExplicit.add('download_mbps'); state.policyExplicit.add('upload_mbps');
      state.policyDirty.add('download_mbps'); state.policyDirty.add('upload_mbps');
      setPresetPressed('[data-quota-speed]', button.dataset.quotaSpeed); updatePolicyPreview();
    }));
    root.querySelectorAll('[data-quota-grant-amount]').forEach(button => button.addEventListener('click', () => { $('grant-form').elements.amount_gb.value = button.dataset.quotaGrantAmount;updateGrantPreview(); }));
    root.querySelectorAll('[data-close-dialog]').forEach(b => b.addEventListener('click', () => dialog(b.dataset.closeDialog).close()));
    for (const d of ['policy-dialog', 'grant-dialog']) {
      dialog(d).addEventListener('click', e => { if (e.target === dialog(d)) dialog(d).close(); });
      dialog(d).addEventListener('close', () => { if (!state.busy) state.dialogTargetId = null; updatePickerState(); });
    }
    document.addEventListener('visibilitychange', () => { if (!document.hidden && !state.stopped) fetchQuota(); });
  }
  async function initialize() {
    try {
      buildUI();
      const bootNode = document.getElementById('vpn-bootstrap'); if (bootNode) state.boot = JSON.parse(bootNode.textContent);
      const me = await api('me'); state.user = me.user || state.boot?.user || null; state.admin = Boolean(me.admin || state.user?.role === 'admin'); state.enabled = Boolean(me.enabled);
      if (!state.user) throw new Error('无法识别当前账户，请重新登录。');
      root.hidden = false;
      state.targetId = String(state.user.id); initEvents();
      if (state.admin) await loadUsers();
      await fetchQuota();
      state.refreshTimer = setInterval(() => { if (!document.hidden && !state.busy && !state.stopped) fetchQuota(); }, 30000);
    } catch (e) { status(escapeError(e), 'error'); root.hidden = false; $('quota-content').hidden = true; }
  }
  window.VPNQuotaUI = {
    refreshUsers: async () => { if (state.admin && !state.stopped) { await loadUsers(); render(); } },
    selectUser: async id => { if (isBusy() || state.stopped || !state.admin || !state.users.some(u => String(u.id) === String(id))) return false; state.targetId = String(id); $('target-picker').value = state.targetId; state.quota = null; render(); await fetchQuota(); return true; },
    refresh: fetchQuota,
    isBusy
  };
  document.addEventListener('vpn:layout', () => { if ($('chart')) drawChart(state.usage || {}); });
  window.addEventListener('resize', () => { if ($('chart')) drawChart(state.usage || {}); });
  initialize();
})();
