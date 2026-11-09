'use strict';
(() => {
  const dateFormatterCache = new Map();
  function dateFormatter(locale, options) {
    const key = locale + JSON.stringify(options);
    if (!dateFormatterCache.has(key)) dateFormatterCache.set(key, new Intl.DateTimeFormat(locale, options));
    return dateFormatterCache.get(key);
  }
  const $ = id => document.getElementById(id);
  const platformNames = { windows: 'Windows', macos: 'macOS', ios: 'iPhone / iOS', android: 'Android', linux: 'Linux' };
  const clientNames = { clash: 'Clash', shadowrocket: 'Shadowrocket', uri: '节点 URI' };
  const clientsByPlatform = { windows: ['clash', 'uri'], macos: ['clash', 'shadowrocket', 'uri'], ios: ['shadowrocket', 'uri'], android: ['clash', 'uri'], linux: ['clash', 'uri'] };
  let lastRenderedUsage = {};
  let bootstrap, user = null, admin = false, enabled = false, targetUser = null, targetEnabled = false;
  let users = [], devices = [], currentDetail = null, selectedId = null, listMeter = null;
  let targetGeneration = 0, detailGeneration = 0, listRequestGeneration = null, listRequestToken = 0;
  let mutationBusy = false, sessionExpired = false, editingDevice = null, editingAccount = null, decision = null, globalMessageKind = '';
  let menuDevice = null, menuTargetVersion = null;
  const deviceMenu = $('device-actions-popover');
  function closeDeviceMenu(){if(typeof deviceMenu?.hidePopover==='function'&&deviceMenu.matches(':popover-open'))deviceMenu.hidePopover();}
  function showDeviceMenu(device, source){
    if(isBusy()||typeof deviceMenu?.showPopover!=='function')return;
    closeDeviceMenu();menuDevice=device;menuTargetVersion=targetGeneration;
    $('device-actions-name').textContent=`${device.remark||'未命名设备'} · ${platformNames[device.platform]||device.platform}`;
    const r=source.getBoundingClientRect(),width=Math.min(272,window.innerWidth-28);
    deviceMenu.style.width=`${width}px`;
    deviceMenu.style.left=`${Math.max(14,Math.min(r.right-width,window.innerWidth-width-14))}px`;
    deviceMenu.style.top='14px';deviceMenu.showPopover({source});
    const height=deviceMenu.getBoundingClientRect().height;
    deviceMenu.style.top=`${Math.max(14,Math.min(r.bottom+8,window.innerHeight-height-14))}px`;
    $('device-action-open').focus();
  }
  for(const [id,action] of [['device-action-open','open'],['device-action-edit','edit'],['device-action-rotate','rotate'],['device-action-remove','delete']]){
    $(id)?.addEventListener('click',()=>{
      closeDeviceMenu();
      if(isBusy()||!menuDevice||menuTargetVersion!==targetGeneration)return;
      const device=menuDevice;
      if(action==='open')selectDevice(device.id);
      else if(action==='edit')openDeviceForm(device);
      else confirmAction(action,device);
    });
  }
  window.addEventListener('resize',closeDeviceMenu);
  document.addEventListener('scroll',e=>{if(!deviceMenu?.contains(e.target))closeDeviceMenu();},true);

  function emit(name, detail) { document.dispatchEvent(new CustomEvent(name, { detail })); }
  function safeFields(value, keys) {
    const result = {};
    for (const key of keys) {
      const field = value && value[key];
      if (field === null || ['string', 'number', 'boolean'].includes(typeof field)) result[key] = field;
    }
    return result;
  }
  function safeUser(value) { return value ? safeFields(value, ['id', 'name', 'username', 'role', 'quant_enabled']) : null; }
  function isBusy() { return mutationBusy || sessionExpired || ['device-dialog', 'account-dialog', 'decision-dialog', 'policy-dialog', 'grant-dialog'].some(key => $(key)?.open); }

  function message(text, kind = 'notice', withLogin = false) {
    const box = $('global-message'); box.replaceChildren();
    if (!text) { box.hidden = true; globalMessageKind = ''; return; }
    const copy = document.createElement('span'); copy.textContent = text; box.append(copy);
    if (withLogin) {
      const link = document.createElement('a'); link.href = '/login?next=%2Fvpn%2F'; link.textContent = '重新登录'; link.className = 'login-link'; box.append(' ', link);
    }
    box.className = `notice ${kind}`; box.hidden = false; globalMessageKind = kind;
  }
  function setStatus(id, text, isError = false) {
    const node = $(id); if (!node) return;
    node.textContent = text || ''; node.classList.toggle('error', Boolean(isError));
  }
  function readBootstrap() {
    try { bootstrap = JSON.parse($('vpn-bootstrap').textContent); }
    catch (_) { message('页面初始化数据无法读取，请刷新页面或重新登录。', 'error'); throw new Error('invalid bootstrap'); }
    if (!bootstrap || typeof bootstrap !== 'object') throw new Error('invalid bootstrap');
    const csrfField = $('logout-csrf');
    if (csrfField) csrfField.value = String(bootstrap.csrf_token || '');
  }
  function formatBytes(value) { return window.VPNViewModel.gb(value) + (window.VPNViewModel.known(value) ? ' GB' : ''); }
  function dateTime(epoch) {
    if (epoch === null || epoch === undefined || !Number.isFinite(Number(epoch))) return '暂无记录';
    return dateFormatter('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(Number(epoch) * 1000));
  }
  function dayLabel(epoch) {
    return dateFormatter('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' }).format(new Date(Number(epoch) * 1000));
  }
  function node(tag, className, text) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined && text !== null) result.textContent = String(text);
    return result;
  }
  function errorText(error, fallback = '请求失败，请稍后重试。') { return error && error.message ? error.message : fallback; }
  function apiPath(path) { return `/vpn/api/${path.replace(/^\//, '')}`; }
  async function api(path, options = {}) {
    if (sessionExpired) throw new Error('登录已过期，请重新登录。');
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 10000);
    const method = String(options.method || 'GET').toUpperCase();
    const headers = new Headers(options.headers || {});
    if (['POST', 'PATCH', 'DELETE'].includes(method)) {
      headers.set('X-CSRF-Token', String(bootstrap.csrf_token || ''));
      headers.set('Content-Type', 'application/json');
    }
    try {
      const response = await fetch(apiPath(path), { credentials: 'same-origin', cache: 'no-store', ...options, method, headers, signal: controller.signal });
      if (response.status === 401) {
        sessionExpired = true;
        closeDeviceMenu();
        emit('vpn:session-expired');
        clearDetail(); devices = []; users = []; $('device-list').replaceChildren(); $('admin-users').replaceChildren();
        $('workspace').hidden = true; $('admin-target-panel').hidden = true; $('admin-users-panel').hidden = true;
        if ($('device-dialog').open) $('device-dialog').close();
        if ($('decision-dialog').open) $('decision-dialog').close();
        if ($('account-dialog').open) $('account-dialog').close();
        message('登录状态已过期，重新登录后可继续管理 VPN。', 'error', true);
        throw new Error('登录状态已过期。');
      }
      if (response.status === 403) {
        message('当前账户没有执行此操作的权限。', 'error');
        throw new Error('没有权限执行此操作。');
      }
      let payload = null;
      try { payload = await response.json(); } catch (_) { payload = null; }
      if (!response.ok) {
        const reason = payload && (payload.message || payload.error || payload.detail);
        throw new Error(typeof reason === 'string' ? reason : `请求失败（${response.status}）。`);
      }
      return payload || {};
    } catch (error) {
      if (error && error.name === 'AbortError') throw new Error('请求超时，请检查网络后重试。');
      if (error instanceof TypeError) throw new Error('网络暂不可用，请稍后重试。');
      throw error;
    } finally { clearTimeout(timer); }
  }
  function identityName(value) { return value && (value.name || value.username) || '—'; }
  function renderIdentity() {
    $('account-name').textContent = user ? `${identityName(user)}${user.username && user.name ? ` · @${user.username}` : ''}` : '账户';
    $('account-role').textContent = admin ? '管理员' : '会员';
    const showQuantLink = admin || Boolean(user && user.quant_enabled);
    $('quant-backtest-link').hidden = !showQuantLink;
    $('quant-backtest-link').style.display = showQuantLink ? 'flex' : 'none';
    emit('vpn:identity', { user: safeUser(user), admin, enabled });
  }
  function showWorkspace() { $('access-gate').hidden = true; $('workspace').hidden = false; }
  function showGate() { $('access-gate').hidden = false; $('workspace').hidden = true; }
  function focusWorkspace(scroll = true) {
    const heading = $('workspace-heading');
    heading.textContent = admin ? `正在管理 ${identityName(targetUser)} 的设备` : '我的 VPN 设备';
    if (scroll) {
      $('workspace').scrollIntoView({ behavior: 'smooth', block: 'start' });
      heading.focus({ preventScroll: true });
    }
  }
  function clearDetail() {
    detailGeneration++; currentDetail = null; selectedId = null;
    const panel = $('device-detail'); if (panel) panel.hidden = true;
    const qr = $('device-qr'); if (qr) { qr.removeAttribute('src'); qr.hidden = true; qr.alt = '所选设备的专属二维码'; }
    if ($('detail-title')) $('detail-title').textContent = '设备详情';
    if ($('detail-summary')) $('detail-summary').textContent = '';
    if ($('detail-actions')) $('detail-actions').replaceChildren();
    if ($('format-switch')) $('format-switch').replaceChildren();
    if ($('danger-actions')) $('danger-actions').replaceChildren();
    if ($('manual-copy')) { $('manual-copy').value = ''; $('manual-copy').hidden = true; }
    if ($('copy-recommended')) $('copy-recommended').disabled = true;
    if ($('copy-recommended')) $('copy-recommended').onclick = null;
    if ($('copy-uri')) $('copy-uri').disabled = true;
    if ($('copy-uri')) $('copy-uri').onclick = null;
    if ($('recommended-label')) $('recommended-label').textContent = '—';
    for (const id of ['clash-deeplink', 'shadowrocket-deeplink', 'shadowrocket-rules-deeplink']) {
      const link = $(id); if (link) { link.href = '#'; link.setAttribute('aria-disabled', 'true'); }
    }
    setStatus('copy-status', ''); setStatus('detail-status', '');
    if (devices.length) renderDevices();
  }
  function setTarget(nextTarget, focus = true) {
    closeDeviceMenu();menuDevice=null;menuTargetVersion=null;
    targetGeneration++; listRequestGeneration = null; listRequestToken++;
    targetUser = nextTarget || user;
    targetEnabled = targetUser && typeof targetUser.enabled === 'boolean' ? targetUser.enabled : Boolean(targetUser && user && String(targetUser.id) === String(user.id) && enabled);
    devices = []; listMeter = null;
    clearDetail();
    $('device-list').replaceChildren(node('p', 'loading', '正在读取设备…'));
    $('target-name').textContent = identityName(targetUser);
    $('target-username').textContent = targetUser && targetUser.username ? `@${targetUser.username}` : '—';
    $('target-label').textContent = `当前管理：${identityName(targetUser)}${targetUser && targetUser.username ? ` · @${targetUser.username}` : ''}`;
    $('device-count').textContent = '—';
    $('list-updated').textContent = '正在读取'; $('list-updated').classList.remove('error');
    renderUsage({});
    $('usage-chart-empty').textContent = '正在读取当前管理对象的用量记录…'; $('usage-chart-empty').hidden = false;
    $('add-device').disabled = (!admin && !enabled) || (admin && !targetEnabled);
    const accessNotice = $('target-access-notice');
    accessNotice.hidden = !(admin && !targetEnabled);
    accessNotice.textContent = admin && !targetEnabled ? `${identityName(targetUser)} 尚未开通 VPN。请先在上方“用户管理”中开通 VPN 权限，再添加或管理设备。` : '';
    message('');
    emit('vpn:target', { user: safeUser(targetUser), enabled: targetEnabled, generation: targetGeneration, focus });
    if (!admin && !enabled) { showGate(); return; }
    showWorkspace(); focusWorkspace(focus); loadDevices(targetGeneration);
  }
  function clientChoices(platform) { return clientsByPlatform[platform] || ['uri']; }
  function fillClientSelect(select, platform, preferred) {
    select.replaceChildren();
    const choices = clientChoices(platform);
    choices.forEach(key => {
      const option = node('option', '', clientNames[key] || key); option.value = key; select.append(option);
    });
    select.value = choices.includes(preferred) ? preferred : choices[0];
  }
  function renderUsage(usage) {
    lastRenderedUsage = usage || {};
    $('download-total').textContent = formatBytes(usage && usage.download_bytes);
    $('upload-total').textContent = formatBytes(usage && usage.upload_bytes);
    $('usage-started').textContent = usage && usage.started_at ? `累计记录自 ${dateTime(usage.started_at)}（UTC+8）；之前的用量无法追溯。` : '历史记录从采集启用后开始，之前的用量无法追溯。';
    const svg = $('usage-chart'); svg.replaceChildren();
    const series = usage && Array.isArray(usage.series) ? usage.series : [];
    const known = series.filter(point => point.total_bytes !== null && point.total_bytes !== undefined && Number.isFinite(Number(point.total_bytes)));
    const width = Math.max(280, Math.round(svg.parentElement.getBoundingClientRect().width) || Math.min(760, window.innerWidth - 64)), height = 190, left = 64, right = 12, top = 12, bottom = 33, plotH = height - top - bottom, plotW = width - left - right;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('preserveAspectRatio', 'none');
    const max = Math.max(1, ...known.map(point => Number(point.total_bytes)));
    const appendSvg = (tag, attrs, text) => {
      const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
      Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, String(value)));
      if (text !== undefined) element.textContent = text; svg.append(element); return element;
    };
    for (let i = 0; i <= 3; i++) {
      const value = max * i / 3, y = top + plotH - plotH * i / 3;
      appendSvg('line', { x1: left, y1: y, x2: width - right, y2: y, stroke: 'var(--app-line-soft)', 'stroke-dasharray': i ? '3 4' : '0' });
      appendSvg('text', { x: left - 7, y: y + 3, 'text-anchor': 'end', fill: 'var(--app-muted)', 'font-size': 9 }, formatBytes(value));
    }
    const stride = series.length ? plotW / series.length : plotW;
    const barW = Math.min(42, Math.max(8, stride * .48));
    series.forEach((point, index) => {
      const x = left + stride * index + stride / 2;
      const isKnown = point.total_bytes !== null && point.total_bytes !== undefined && Number.isFinite(Number(point.total_bytes));
      if (isKnown) {
        const download = Number(point.download_bytes || 0), upload = Number(point.upload_bytes || 0);
        const downloadH = plotH * download / max, uploadH = plotH * upload / max;
        if (downloadH > 0) appendSvg('rect', { x: x - barW / 2, y: top + plotH - downloadH, width: barW, height: downloadH, rx: 3, fill: 'var(--app-accent)' });
        if (uploadH > 0) appendSvg('rect', { x: x - barW / 2, y: top + plotH - downloadH - uploadH, width: barW, height: uploadH, rx: 3, fill: 'var(--app-upload)' });
        if (Number(point.total_bytes) === 0) appendSvg('circle', { cx: x, cy: top + plotH - 1, r: 2, fill: '#a9a3e8' });
      }
      if (index % Math.max(1, Math.ceil(series.length / Math.max(2, Math.floor(plotW / 66)))) === 0 || index === series.length - 1) appendSvg('text', { x, y: height - 8, 'text-anchor': 'middle', fill: 'var(--app-muted)', 'font-size': 9 }, point.start ? dayLabel(point.start) : `第 ${index + 1} 天`);
    });
    svg.setAttribute('aria-label', `近 ${series.length} 天用量图，${known.length} 个已记录时段；未知历史不会按零显示`);
    const empty = $('usage-chart-empty');
    if (!series.length || !known.length) {
      empty.textContent = series.length ? '尚无可确认的记录；未知历史不会显示为 0。' : '尚无用量历史记录。'; empty.hidden = false;
    } else if (known.every(point => Number(point.total_bytes) === 0)) {
      empty.textContent = '已采集时段的用量为 0；未知时段仍保留为空。'; empty.hidden = false;
    } else empty.hidden = true;
  }
  function renderDevices() {
    const list = $('device-list'); list.replaceChildren();
    $('device-count').textContent = String(devices.length);
    if (!devices.length) {
      const empty = node('div', 'empty-state');
      empty.append(node('strong', '', '还没有设备'), node('p', '', admin ? '为当前管理的用户添加第一台设备。' : '添加一台设备，为它生成专属 VPN 配置。'));
      list.append(empty); return;
    }
    devices.forEach(device => {
      const card = node('article', `device-card${String(device.id) === String(selectedId) ? ' selected' : ''}`);
      card.dataset.deviceId = String(device.id);
      card.dataset.search = [device.id, device.remark, device.platform, device.client].filter(value => value !== null && value !== undefined).join(' ').toLowerCase();
      const top = node('div', 'device-card-top');
      const open = node('button', 'device-open'); open.type = 'button'; open.setAttribute('aria-label', `查看 ${device.remark || '未命名设备'} 的订阅详情`);
      open.append(node('strong', '', device.remark || '未命名设备'), node('small', '', `${platformNames[device.platform] || device.platform || '未知平台'} · ${clientNames[device.client] || device.client || '未知客户端'}`));
      open.addEventListener('click', () => selectDevice(device.id));
      const meterHealthy = Boolean(listMeter && listMeter.healthy);
      const onlineKnown = device.online !== null && device.online !== undefined && Number.isFinite(Number(device.online));
      const onlineCount = onlineKnown ? Number(device.online) : null;
      const onlineNow = Boolean(device.enabled && meterHealthy && onlineKnown && onlineCount > 0);
      const stateText = !device.enabled ? '已停用' : !meterHealthy || !onlineKnown ? '状态未知' : onlineCount > 0 ? `${onlineCount} 在线` : '当前离线';
      const status = node('span', `device-state${onlineNow ? ' online' : ''}${!device.enabled ? ' disabled' : ''}${device.enabled && (!meterHealthy || !onlineKnown) ? ' stale' : ''}`, stateText);
      top.append(open, status); card.append(top);
      const meta = node('div', 'device-meta');
      const meterTime = listMeter && listMeter.last_success ? dateTime(listMeter.last_success) : '暂无成功记录';
      meta.append(node('span', '', `下载 ${formatBytes(device.download_bytes)}`), node('span', '', `上传 ${formatBytes(device.upload_bytes)}`), node('span', '', `最近活动 ${dateTime(device.last_seen)}`), node('span', 'meter-source', `HY2 节点计量 · 最近采集 ${meterTime}`));
      card.append(meta);
      const bottom = node('div', 'device-bottom');
      const toggleLabel = node('label', 'toggle-label');
      const toggle = document.createElement('input'); toggle.type = 'checkbox'; toggle.checked = Boolean(device.enabled); toggle.disabled = mutationBusy || sessionExpired;
      toggle.setAttribute('aria-label', `${device.remark || '设备'}启用状态`);
      toggle.addEventListener('click', event => event.stopPropagation());
      toggle.addEventListener('change', () => updateDeviceEnabled(device, toggle.checked));
      toggleLabel.append(toggle, node('span', '', device.enabled ? '已启用' : '已停用'));
      const edit = node('button', 'quiet-button device-edit', '编辑设备'); edit.type = 'button'; edit.disabled = mutationBusy || sessionExpired;
      edit.addEventListener('click', () => openDeviceForm(device));
      const actions = node('div', 'device-actions');
      const config = node('button', 'primary-button device-config', '订阅与二维码'); config.type = 'button'; config.disabled = sessionExpired;
      config.setAttribute('aria-label', `查看 ${device.remark || '未命名设备'} 的订阅与二维码`);
      config.addEventListener('click', () => selectDevice(device.id));
      actions.append(config, edit);
      if(typeof deviceMenu?.showPopover==='function'){
        const more=node('button','quiet-button device-more','更多操作');more.type='button';more.disabled=mutationBusy||sessionExpired;
        more.setAttribute('aria-label',`更多操作：${device.remark||'未命名设备'}`);more.setAttribute('aria-haspopup','dialog');more.setAttribute('aria-controls','device-actions-popover');
        more.addEventListener('click',()=>showDeviceMenu(device,more));actions.append(more);
      }
      bottom.append(toggleLabel, actions); card.append(bottom); list.append(card);
    });
  }
  function listQuery() {
    if (!admin) return '';
    const params = new URLSearchParams({ user_id: String(targetUser.id) }); return `?${params}`;
  }
  async function loadDevices(generation = targetGeneration, force = false) {
    if (sessionExpired || (!force && (listRequestGeneration === generation || mutationBusy))) return;
    if (!admin && !enabled) return;
    const requestToken = ++listRequestToken; listRequestGeneration = generation;
    try {
      const payload = await api(`devices${listQuery()}`);
      if (generation !== targetGeneration || requestToken !== listRequestToken || sessionExpired) return;
      devices = Array.isArray(payload.devices) ? payload.devices : [];
      listMeter = payload.meter || null;
      if (payload.target_user) targetUser = payload.target_user;
      if (typeof payload.enabled === 'boolean') {
        targetEnabled = payload.enabled;
        if (targetUser) targetUser = { ...targetUser, enabled: payload.enabled };
        if (admin && targetUser) {
          users = users.map(item => String(item.id) === String(targetUser.id) ? { ...item, enabled: payload.enabled } : item);
          renderAdminUsers(); populateTargetSelector();
        }
        $('add-device').disabled = mutationBusy || (!admin && !enabled) || (admin && !targetEnabled) || sessionExpired;
        const accessNotice = $('target-access-notice');
        accessNotice.hidden = !(admin && !targetEnabled);
        accessNotice.textContent = admin && !targetEnabled ? `${identityName(targetUser)} 尚未开通 VPN。请先在上方“用户管理”中开通 VPN 权限，再添加或管理设备。` : '';
      }
      $('target-name').textContent = identityName(payload.target_user || targetUser);
      $('target-username').textContent = payload.target_user && payload.target_user.username ? `@${payload.target_user.username}` : targetUser && targetUser.username ? `@${targetUser.username}` : '—';
      $('device-count').textContent = String(devices.length);
      $('download-total').textContent = formatBytes(payload.usage && payload.usage.download_bytes);
      $('upload-total').textContent = formatBytes(payload.usage && payload.usage.upload_bytes);
      renderUsage(payload.usage || {}); renderDevices();
      $('list-updated').textContent = `更新于 ${dateTime(Date.now() / 1000)}`;
      if (selectedId && devices.some(device => String(device.id) === String(selectedId))) {
        // Leave the visible detail intact; its own request is guarded by the target generation.
      } else if (selectedId) clearDetail();
      if (globalMessageKind === 'error') message('');
      emit('vpn:devices', {
        devices: devices.map(device => safeFields(device, ['id', 'remark', 'platform', 'client', 'enabled', 'online', 'download_bytes', 'upload_bytes', 'last_seen'])),
        usage: payload.usage, meter: listMeter, target: safeUser(targetUser), enabled: targetEnabled,
      });
    } catch (error) {
      if (generation !== targetGeneration || requestToken !== listRequestToken || sessionExpired) return;
      $('device-list').replaceChildren(node('p', 'empty-state', errorText(error, '设备列表暂时无法读取。')));
      setStatus('list-updated', '读取失败', true);
      emit('vpn:devices-error', { targetId: targetUser && targetUser.id, message: errorText(error, '设备列表暂时无法读取。') });
    } finally { if (requestToken === listRequestToken) listRequestGeneration = null; }
  }
  function setMutationBusy(value) {
    mutationBusy = value;
    $('add-device').disabled = value || (!admin && !enabled) || (admin && !targetEnabled) || sessionExpired;
    $('refresh-devices').disabled = value || sessionExpired;
    if ($('add-account')) $('add-account').disabled = value || sessionExpired;
    if ($('account-save')) $('account-save').disabled = value || sessionExpired;
    if ($('account-form')) {
      document.querySelectorAll('#account-form input, #account-form select, #account-form button').forEach(control => {
        if (control.id === 'account-save') return;
        if (control.id === 'account-quant-enabled' || control.id === 'account-enabled') return;
        control.disabled = value || (control.id === 'account-role-select' && isSelfAccount(editingAccount)) || sessionExpired;
      });
      syncAccountPermissionControls();
    }
    if ($('target-user')) $('target-user').disabled = value || sessionExpired;
    if (admin && users.length) renderAdminUsers();
    renderDevices();
    document.querySelectorAll('#detail-actions button').forEach(button => { button.disabled = value || sessionExpired; });
    emit('vpn:mutation', { busy: value });
  }
  function unwrapDevice(payload) { return payload && payload.device ? payload.device : payload; }
  const POLICY_PENDING_NOTICE = '服务端策略已更新，约 1 秒内应用；闲置连接会在下一次传输时检查。';
  function enforcementNotice(payload) {
    const data = payload && (payload.device || payload);
    if ((payload && payload.enforcement && payload.enforcement.connections_disconnected === false) || (data && data.enforcement && data.enforcement.connections_disconnected === false)) {
      return '新连接已被阻止，但无法确认现有连接已断开；设备状态已刷新。';
    }
    if (payload?.enforcement?.connections_disconnected === null || data?.enforcement?.connections_disconnected === null) return POLICY_PENDING_NOTICE;
    return '';
  }
  function recommendedURL(detail) {
    if (detail.client === 'clash' && detail.clash_url) return detail.clash_url;
    if (detail.client === 'shadowrocket' && detail.shadowrocket_url) return detail.shadowrocket_url;
    if (detail.uri) return detail.uri;
    return detail.clash_url || detail.shadowrocket_url || detail.uri || '';
  }
  function formatLabel(key) { return key === 'clash_url' ? 'Clash 订阅' : key === 'shadowrocket_url' ? 'Shadowrocket 自动更新' : '节点 URI'; }
  async function copyText(value, label, privateValue = true) {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      $('manual-copy').value = ''; $('manual-copy').hidden = true;
      setStatus('copy-status', `${label}已复制。${privateValue ? '请勿分享给其他人。' : '在 Shadowrocket 的配置页导入即可。'}`);
    } catch (_) {
      $('manual-copy').value = value; $('manual-copy').hidden = false; $('manual-copy').focus(); $('manual-copy').select();
      setStatus('copy-status', '剪贴板不可用，请全选下方内容并手动复制。', true);
    }
  }
  function setExternalLink(id, href) {
    const link = $(id);
    if (href) { link.href = href; link.setAttribute('aria-disabled', 'false'); }
    else { link.href = '#'; link.setAttribute('aria-disabled', 'true'); }
  }
  function renderDetail(payload, generation, targetVersion) {
    if (generation !== detailGeneration || targetVersion !== targetGeneration || !payload) return;
    currentDetail = payload;
    const detail = currentDetail;
    $('device-detail').hidden = false;
    $('detail-title').textContent = detail.remark || '设备详情';
    $('detail-summary').textContent = `${platformNames[detail.platform] || detail.platform || '未知平台'} · ${clientNames[detail.client] || detail.client || '未知客户端'} · ${detail.enabled ? '已启用' : '已停用'} · 最近活动 ${dateTime(detail.last_seen)} · HY2 节点计量，最近采集 ${listMeter && listMeter.last_success ? dateTime(listMeter.last_success) : '暂无成功记录'}`;
    $('detail-actions').replaceChildren();
    const edit = node('button', 'quiet-button', '编辑设备'); edit.type = 'button'; edit.disabled = mutationBusy;
    edit.addEventListener('click', () => openDeviceForm(detail)); $('detail-actions').append(edit);
    const rotate = node('button', 'quiet-button', '重置此设备订阅…'); rotate.type = 'button'; rotate.disabled = mutationBusy;
    rotate.addEventListener('click', () => confirmAction('rotate', detail)); $('detail-actions').append(rotate);
    const remove = node('button', 'quiet-button', '删除此设备…'); remove.type = 'button'; remove.disabled = mutationBusy;
    remove.addEventListener('click', () => confirmAction('delete', detail)); $('detail-actions').append(remove);

    const preferred = recommendedURL(detail);
    $('recommended-label').textContent = detail.client ? (clientNames[detail.client] || detail.client) : '可用配置';
    $('copy-recommended').disabled = !preferred; $('copy-recommended').textContent = detail.client === 'uri' ? '复制推荐节点 URI' : '复制推荐订阅地址';
    $('copy-recommended').onclick = () => copyText(preferred, '推荐配置');
    $('format-switch').replaceChildren();
    const formats = [['clash_url', detail.clash_url], ['shadowrocket_url', detail.shadowrocket_url], ['uri', detail.uri]];
    formats.forEach(([key, value]) => {
      if (!value) return;
      const button = node('button', `quiet-button${((detail.client === 'clash' && key === 'clash_url') || (detail.client === 'shadowrocket' && key === 'shadowrocket_url') || (detail.client === 'uri' && key === 'uri')) ? ' recommended-format' : ''}`, `复制 ${formatLabel(key)}`);
      button.type = 'button'; button.addEventListener('click', () => copyText(value, formatLabel(key))); $('format-switch').append(button);
    });
    const clashLink = detail.clash_url ? `clash://install-config?url=${encodeURIComponent(detail.clash_url)}` : '';
    const shadowrocketLink = detail.shadowrocket_url ? `shadowrocket://add/${encodeURIComponent(detail.shadowrocket_url)}` : '';
    const rulesURL = detail.shadowrocket_rules_url || `${location.origin}/vpn/rules/unified.conf`;
    const rulesLink = `shadowrocket://config/add/${encodeURIComponent(rulesURL)}`;
    setExternalLink('clash-deeplink', clashLink); setExternalLink('shadowrocket-deeplink', shadowrocketLink);
    setExternalLink('shadowrocket-rules-deeplink', rulesLink);
    $('copy-rules-url').onclick = () => copyText(rulesURL, '分流规则链接', false);
    $('copy-uri').disabled = !detail.uri; $('copy-uri').onclick = () => copyText(detail.uri, '节点 URI');
    $('manual-copy').value = ''; $('manual-copy').hidden = true;
    setStatus('copy-status', ''); setStatus('detail-status', '');
    const qr = $('device-qr');
    if (detail.qr_url) { qr.referrerPolicy = 'no-referrer'; qr.alt = `${detail.remark || '设备'}的专属配置二维码`; qr.src = detail.qr_url; qr.hidden = false; }
    else { qr.removeAttribute('src'); qr.hidden = true; }
    $('danger-actions').replaceChildren();
    if(!$('device-sheet')?.open)$('device-detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    emit('vpn:detail', { id: detail.id });
  }
  async function selectDevice(id) {
    if (String(id) === String(selectedId) && currentDetail) { if(!$('device-sheet')?.open)$('device-detail').scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
    const generation = ++detailGeneration, targetVersion = targetGeneration;
    currentDetail = null; selectedId = id;
    $('device-detail').hidden = false; $('detail-title').textContent = '正在读取设备…';
    $('detail-summary').textContent = ''; $('detail-actions').replaceChildren(); $('format-switch').replaceChildren();
    $('danger-actions').replaceChildren(); $('manual-copy').value = ''; $('manual-copy').hidden = true;
    $('device-qr').removeAttribute('src'); $('device-qr').hidden = true;
    $('copy-recommended').disabled = true; $('copy-uri').disabled = true;
    $('copy-recommended').onclick = null; $('copy-uri').onclick = null; $('recommended-label').textContent = '—';
    setExternalLink('clash-deeplink', ''); setExternalLink('shadowrocket-deeplink', ''); setExternalLink('shadowrocket-rules-deeplink', '');
    if ($('copy-rules-url')) $('copy-rules-url').onclick = null;
    $('device-detail').hidden = false;
    emit('vpn:detail-loading',{id});
    try {
      const payload = await api(`devices/${encodeURIComponent(id)}`);
      renderDetail(unwrapDevice(payload), generation, targetVersion);
    } catch (error) {
      if (generation === detailGeneration && targetVersion === targetGeneration) {
        $('detail-title').textContent = '设备详情暂不可用'; setStatus('detail-status', errorText(error), true);
      }
    }
  }
  function openDeviceForm(device = null) {
    if ((!admin && !enabled) || (admin && !targetEnabled)) return;
    editingDevice = device;
    $('device-form').reset();
    $('dialog-title').textContent = device ? '编辑设备' : '添加设备';
    $('device-save').textContent = device ? '保存修改' : '添加设备';
    $('device-remark').value = device ? device.remark || '' : '';
    $('device-platform').value = device ? device.platform : 'windows';
    fillClientSelect($('device-client'), $('device-platform').value, device ? device.client : 'clash');
    $('form-error').textContent = '';
    $('device-dialog').showModal(); $('device-remark').focus();
  }
  function closeForm() { if ($('device-dialog').open) $('device-dialog').close(); }
  $('device-platform').addEventListener('change', () => fillClientSelect($('device-client'), $('device-platform').value, $('device-client').value));
  $('add-device').addEventListener('click', () => openDeviceForm());
  $('dialog-close').addEventListener('click', closeForm); $('dialog-cancel').addEventListener('click', closeForm);
  $('device-dialog').addEventListener('click', event => { if (event.target === $('device-dialog')) closeForm(); });
  $('device-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (mutationBusy || sessionExpired) return;
    const remark = $('device-remark').value.trim(), platform = $('device-platform').value, client = $('device-client').value;
    if (!remark || remark.length > 60) { $('form-error').textContent = '请填写 1 到 60 个字符的设备备注。'; $('device-remark').focus(); return; }
    if (!clientChoices(platform).includes(client)) { $('form-error').textContent = '所选平台与客户端组合不受支持。'; return; }
    const targetVersion = targetGeneration, targetId = targetUser && targetUser.id;
    const body = { remark, platform, client };
    if (!editingDevice && admin) body.user_id = targetId;
    const url = editingDevice ? `devices/${encodeURIComponent(editingDevice.id)}` : 'devices';
    let createdDeviceId = null;
    setMutationBusy(true); $('device-save').disabled = true; $('form-error').textContent = '';
    try {
      const result = await api(url, { method: editingDevice ? 'PATCH' : 'POST', body: JSON.stringify(body) });
      closeForm();
      if (targetVersion === targetGeneration) {
        const enforcement = enforcementNotice(result);
        message(enforcement || (editingDevice ? '设备信息已保存。' : '设备已添加，正在生成专属配置。'), enforcement && enforcement !== POLICY_PENDING_NOTICE ? 'error' : 'success');
        await loadDevices(targetVersion, true);
        if (!editingDevice) createdDeviceId = result.device?.id || null;
        if (editingDevice && String(selectedId) === String(editingDevice.id)) { currentDetail = null; await selectDevice(editingDevice.id); }
      }
    } catch (error) { $('form-error').textContent = errorText(error, '设备保存失败。'); }
    finally { setMutationBusy(false); $('device-save').disabled = false; }
    if (createdDeviceId && targetVersion === targetGeneration) await selectDevice(createdDeviceId);
  });
  async function updateDeviceEnabled(device, nextEnabled) {
    if (mutationBusy || sessionExpired) return;
    const targetVersion = targetGeneration;
    const body = { remark: device.remark, platform: device.platform, client: device.client, enabled: Boolean(nextEnabled) };
    setMutationBusy(true);
    try {
      const result = await api(`devices/${encodeURIComponent(device.id)}`, { method: 'PATCH', body: JSON.stringify(body) });
      if (targetVersion === targetGeneration) { const enforcement = enforcementNotice(result); message(enforcement || (nextEnabled ? '设备已启用。' : '已阻止该设备的新连接。'), enforcement && enforcement !== POLICY_PENDING_NOTICE ? 'error' : 'success'); await loadDevices(targetVersion, true); if (String(selectedId) === String(device.id)) { currentDetail = null; await selectDevice(device.id); } }
    } catch (error) { if (targetVersion === targetGeneration) { message(errorText(error, '设备状态更新失败。'), 'error'); await loadDevices(targetVersion, true); } }
    finally { setMutationBusy(false); }
  }
  function confirmAction(kind, device) {
    decision = { kind, id: device.id, targetVersion: targetGeneration };
    if (kind === 'delete') {
      $('decision-title').textContent = `删除“${device.remark || '此设备'}”？`;
      $('decision-copy').textContent = '删除会停用设备并使旧配置失效。系统会尝试断开现有连接；如果未能确认断开，页面会明确提示。其他设备和 wuyu 网站账户不会受影响。';
      $('decision-confirm').textContent = '确认删除设备';
    } else {
      $('decision-title').textContent = `重置“${device.remark || '此设备'}”的订阅？`;
      $('decision-copy').textContent = '这会轮换此设备的订阅链接并使旧链接失效。请在该设备重新导入或刷新订阅；此操作与启用状态分开。';
      $('decision-confirm').textContent = '确认重置订阅';
    }
    $('decision-error').textContent = ''; $('decision-dialog').showModal(); $('decision-cancel').focus();
  }
  function closeDecision() { decision = null; if ($('decision-dialog').open) $('decision-dialog').close(); }
  $('decision-close').addEventListener('click', closeDecision); $('decision-cancel').addEventListener('click', closeDecision);
  $('decision-dialog').addEventListener('cancel', () => { decision = null; });
  $('decision-dialog').addEventListener('click', event => { if (event.target === $('decision-dialog')) closeDecision(); });
  $('decision-confirm').addEventListener('click', async () => {
    if (!decision || mutationBusy || sessionExpired) return;
    const action = { ...decision }; setMutationBusy(true); $('decision-confirm').disabled = true; $('decision-error').textContent = '';
    try {
      if (action.kind === 'delete') {
        const result = await api(`devices/${encodeURIComponent(action.id)}`, { method: 'DELETE', body: '{}' });
        closeDecision();
        if (action.targetVersion === targetGeneration) { clearDetail();emit('vpn:device-removed',{id:action.id}); const enforcement = enforcementNotice(result); message(enforcement || '设备已删除并停用。', enforcement && enforcement !== POLICY_PENDING_NOTICE ? 'error' : 'success'); await loadDevices(action.targetVersion, true); }
      } else {
        const payload = await api(`devices/${encodeURIComponent(action.id)}/rotate`, { method: 'POST', body: '{}' });
        closeDecision();
        if (action.targetVersion === targetGeneration) {
          if(String(selectedId) === String(action.id)){
            renderDetail(unwrapDevice(payload), detailGeneration, action.targetVersion);
            setStatus('detail-status', '此设备的订阅链接已重置；请在客户端更新配置。');
          }else message('此设备的订阅链接已重置；请重新获取配置并在该设备更新订阅。','success');
          await loadDevices(action.targetVersion, true);
        }
      }
    } catch (error) { $('decision-error').textContent = errorText(error, '操作失败。'); }
    finally { setMutationBusy(false); $('decision-confirm').disabled = false; }
  });
  $('close-detail').addEventListener('click',()=>{if(!$('device-sheet'))clearDetail();});
  $('refresh-devices').addEventListener('click', () => loadDevices(targetGeneration));

  async function loadAdminUsers() {
    if (!admin || sessionExpired) return false;
    try {
      const payload = await api('admin/users'); users = Array.isArray(payload.users) ? payload.users : [];
      renderAdminUsers(); populateTargetSelector();
      return true;
    } catch (error) { setStatus('admin-users-status', errorText(error, '管理员用户列表暂时无法读取。'), true); return false; }
  }
  function populateTargetSelector() {
    const selector = $('target-user'), currentValue = selector.value;
    selector.replaceChildren();
    users.forEach(value => {
      const opt = node('option', '', `${identityName(value)}${value.username ? ` · @${value.username}` : ''} · 量化回测${value.role === 'admin' || value.quant_enabled ? '已开通' : '未开通'} · VPN${value.role === 'admin' || value.enabled ? '已开通' : '未开通'}`);
      opt.value = String(value.id); selector.append(opt);
    });
    const selfId = user && user.id !== undefined ? String(user.id) : '';
    const choose = users.some(value => String(value.id) === currentValue) ? currentValue : users.some(value => String(value.id) === selfId) ? selfId : users.length ? String(users[0].id) : '';
    selector.value = choose;
    if (choose) {
      const selected = users.find(value => String(value.id) === choose);
      if (selected) {
        const sameTarget = targetUser && String(targetUser.id) === choose;
        if (!sameTarget) setTarget(selected, false);
        else if (targetEnabled !== Boolean(selected.enabled)) setTarget(selected, false);
        else {
          targetUser = selected;
          $('target-label').textContent = `当前管理：${identityName(selected)}${selected.username ? ` · @${selected.username}` : ''}`;
          $('target-name').textContent = identityName(selected);
          $('target-username').textContent = selected.username ? `@${selected.username}` : '—';
          $('workspace-heading').textContent = `正在管理 ${identityName(selected)} 的设备`;
        }
      }
    }
  }
  function renderAdminUsers() {
    const host = $('admin-users'); host.replaceChildren();
    if (!users.length) { host.append(node('p', 'empty-state', '没有可管理的网站账户。')); emit('vpn:users', { users: [] }); return; }
    users.forEach(value => {
      const row = node('article', 'admin-user'), identity = node('div', 'admin-user-name');
      row.dataset.userId = String(value.id);
      row.dataset.search = [value.id, value.name, value.username, value.role].filter(item => item !== null && item !== undefined).join(' ').toLowerCase();
      const roleLabel = value.role === 'admin' ? '全站管理员' : '普通用户';
      const quantEnabled = value.role === 'admin' || Boolean(value.quant_enabled);
      const vpnEnabled = value.role === 'admin' || Boolean(value.enabled);
      const subline = `@${value.username || '—'} · ${roleLabel} · 量化回测${quantEnabled ? '已开通' : '未开通'} · VPN${vpnEnabled ? '已开通' : '未开通'}${value.email ? ` · ${value.email}` : ''}`;
      identity.append(node('strong', '', identityName(value)), node('small', '', subline));
      const actions = node('div', 'admin-user-actions');
      const targetButton = node('button', 'quiet-button', '管理设备'); targetButton.type = 'button'; targetButton.disabled = mutationBusy || sessionExpired;
      targetButton.addEventListener('click', () => { emit('vpn:manage-user', { id: value.id }); $('target-user').value = String(value.id); setTarget(value); });
      const editButton = node('button', 'quiet-button', '编辑用户'); editButton.type = 'button'; editButton.disabled = mutationBusy || sessionExpired;
      editButton.addEventListener('click', () => openAccountForm(value));
      const accessButton = node('button', `quiet-button${vpnEnabled ? ' permission-on' : ''}`, vpnEnabled ? '停用 VPN' : '开通 VPN');
      accessButton.type = 'button'; accessButton.disabled = mutationBusy || sessionExpired || value.role === 'admin';
      if (value.role !== 'admin') accessButton.addEventListener('click', () => toggleUserAccess(value, accessButton));
      actions.append(targetButton, editButton, accessButton); row.append(identity, actions); host.append(row);
    });
    emit('vpn:users', { users: users.map(value => ({ ...safeUser(value), quant_enabled: Boolean(value.quant_enabled), enabled: Boolean(value.enabled) })) });
  }
  async function toggleUserAccess(value, button) {
    if (mutationBusy || sessionExpired) return;
    const expected = targetGeneration; setMutationBusy(true); button.disabled = true;
    try {
      const payload = await api(`admin/users/${encodeURIComponent(value.id)}`, { method: 'POST', body: JSON.stringify({ enabled: !value.enabled }) });
      const updated = { ...value, ...(payload.user || {}), enabled: payload.user && typeof payload.user.enabled === 'boolean' ? payload.user.enabled : !value.enabled };
      users = users.map(item => String(item.id) === String(updated.id) ? updated : item);
      if (targetUser && String(targetUser.id) === String(updated.id)) targetUser = updated;
      renderAdminUsers(); populateTargetSelector();
      if (expected === targetGeneration) { const enforcement = enforcementNotice(payload); message(enforcement || (updated.enabled ? '已开通该账户的 VPN 权限。' : '已停用该账户的 VPN 权限。'), enforcement && enforcement !== POLICY_PENDING_NOTICE ? 'error' : 'success'); }
      setStatus('admin-users-status', `${identityName(updated)}：${updated.enabled ? 'VPN 已开通' : 'VPN 已停用'}。`);
    } catch (error) { setStatus('admin-users-status', errorText(error, 'VPN 权限更新失败。'), true); }
    finally { setMutationBusy(false); if (admin && !sessionExpired) await loadDevices(targetGeneration, true); }
  }
  $('target-user').addEventListener('change', () => {
    const found = users.find(value => String(value.id) === $('target-user').value);
    if (found) setTarget(found);
  });

  function isSelfAccount(value) { return Boolean(user && value && String(user.id) === String(value.id)); }
  function syncAccountPermissionControls() {
    const forced = $('account-role-select').value === 'admin' || isSelfAccount(editingAccount);
    ['account-quant-enabled', 'account-enabled'].forEach(id => {
      const control = $(id);
      if (forced) control.checked = true;
      control.disabled = forced || mutationBusy || sessionExpired;
    });
  }
  function openAccountForm(value = null) {
    if (!admin || mutationBusy || sessionExpired) return;
    editingAccount = value;
    $('account-form').reset();
    $('account-dialog-title').textContent = value ? `编辑用户 · ${value.username}` : '新增用户';
    $('account-save').textContent = value ? '保存修改' : '创建用户';
    $('account-username').value = value ? value.username || '' : '';
    $('account-name-input').value = value ? value.name || '' : '';
    $('account-email').value = value ? value.email || '' : '';
    $('account-password').value = '';
    $('account-password').required = !value;
    $('account-password-hint').textContent = value ? '留空保持当前密码不变；如需修改，填写 8–128 位。' : '新增用户必填，8–128 位。';
    $('account-role-select').value = value ? value.role || 'user' : 'user';
    $('account-role-select').disabled = isSelfAccount(value);
    $('account-quant-enabled').checked = value ? Boolean(value.quant_enabled) : false;
    $('account-enabled').checked = value ? Boolean(value.enabled) : false;
    syncAccountPermissionControls();
    $('account-form-error').textContent = '';
    $('account-save').disabled = false;
    $('account-dialog').showModal(); $('account-username').focus();
  }
  function clearAccountForm() {
    editingAccount = null;
    if (!$('account-form')) return;
    $('account-form').reset(); $('account-password').value = '';
    $('account-password').required = false; $('account-role-select').disabled = false;
    $('account-form-error').textContent = '';
  }
  function closeAccountForm() {
    if ($('account-dialog').open) $('account-dialog').close();
    else clearAccountForm();
  }
  $('add-account').addEventListener('click', () => openAccountForm());
  $('account-role-select').addEventListener('change', syncAccountPermissionControls);
  $('account-dialog-close').addEventListener('click', closeAccountForm);
  $('account-cancel').addEventListener('click', closeAccountForm);
  $('account-dialog').addEventListener('close', clearAccountForm);
  $('account-dialog').addEventListener('click', event => { if (event.target === $('account-dialog')) closeAccountForm(); });
  $('account-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (mutationBusy || sessionExpired) return;
    const editing = editingAccount;
    const username = $('account-username').value.trim();
    const name = $('account-name-input').value.trim();
    const email = $('account-email').value.trim();
    const password = $('account-password').value;
    const self = isSelfAccount(editing);
    const formError = $('account-form-error');
    formError.textContent = '';
    if (!/^[A-Za-z0-9_.-]{3,32}$/.test(username)) {
      formError.textContent = '用户名须为 3–32 位 ASCII 字母、数字、点、下划线或连字符。'; $('account-username').focus(); return;
    }
    if (!name || name.length > 64) { formError.textContent = '显示名称须为 1–64 个字符。'; $('account-name-input').focus(); return; }
    if (email && $('account-email').validity.typeMismatch) { formError.textContent = '请输入有效邮箱，或将邮箱留空。'; $('account-email').focus(); return; }
    if ((!editing && (password.length < 8 || password.length > 128)) || (editing && password && (password.length < 8 || password.length > 128))) {
      formError.textContent = '密码长度须为 8–128 位。'; $('account-password').focus(); return;
    }
    const role = self ? editing.role : $('account-role-select').value;
    const forced = role === 'admin' || self;
    const body = { username, name, email, role, quant_enabled: forced || $('account-quant-enabled').checked, enabled: forced || $('account-enabled').checked };
    if (password) body.password = password;
    const targetId = targetUser && targetUser.id;
    setMutationBusy(true); $('account-save').disabled = true;
    let shouldReloadDevices = false;
    try {
      const result = await api(editing ? `admin/accounts/${encodeURIComponent(editing.id)}` : 'admin/accounts', {
        method: editing ? 'PATCH' : 'POST', body: JSON.stringify(body),
      });
      if (result.reauth_required) { $('account-password').value = ''; closeAccountForm(); window.location.assign('/login?next=%2Fvpn%2F'); return; }
      const saved = result.user;
      if (!saved) throw new Error('服务器未返回已保存用户信息，请刷新用户列表确认结果。');
      if(window.VPNQuotaUI) {
        await window.VPNQuotaUI.refreshUsers();
        if(!editing)await window.VPNQuotaUI.selectUser(saved.id);
      }
      $('account-password').value = '';
      closeAccountForm();
      if (user && String(saved.id) === String(user.id)) { user = saved; renderIdentity(); }
      const refreshed = await loadAdminUsers(); shouldReloadDevices = refreshed;
      if (targetId !== undefined && targetId !== null && users.some(item => String(item.id) === String(targetId))) {
        $('target-user').value = String(targetId);
        const refreshedTarget = users.find(item => String(item.id) === String(targetId));
        if (refreshedTarget && (!targetUser || String(refreshedTarget.id) !== String(targetUser.id))) setTarget(refreshedTarget, false);
      }
      setStatus('admin-users-status', `${editing ? `${identityName(saved)} 的账户信息已更新。` : `用户 ${saved.username} 已创建；普通用户初始额度为 0 GB，请在额度管理中分配流量和限速。`}${refreshed ? '' : '但用户列表刷新失败，请手动刷新页面确认。'}`, !refreshed);
    } catch (error) {
      formError.textContent = errorText(error, '用户保存失败。');
      if ($('account-dialog').open) $('account-password').value = '';
      setStatus('admin-users-status', errorText(error, '用户保存失败。'), true);
    } finally {
      setMutationBusy(false); $('account-save').disabled = false;
      if (shouldReloadDevices && admin && !sessionExpired) await loadDevices(targetGeneration, true);
    }
  });

  async function initialize() {
    try {
      readBootstrap(); user = bootstrap.user || null; enabled = Boolean(bootstrap.enabled); renderIdentity();
      const payload = await api('me');
      user = payload.user || user; admin = Boolean(payload.admin || (user && user.role === 'admin')); enabled = Boolean(payload.enabled);
      renderIdentity();
      $('admin-target-panel').hidden = !admin; $('admin-users-panel').hidden = !admin;
      if (admin) {
        showWorkspace();
        await loadAdminUsers();
        if (!targetUser) setTarget(user, false);
      } else if (enabled) {
        targetUser = user; setTarget(user, false);
      } else {
        $('target-name').textContent = identityName(user); $('target-username').textContent = user && user.username ? `@${user.username}` : '—';
        showGate();
      }
    } catch (error) {
      if (!sessionExpired) {
        showGate();
        message(errorText(error, '无法读取账户权限，请重新登录后再试。'), 'error', /登录/.test(error.message || ''));
      }
    }
  }
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !sessionExpired && listRequestGeneration === null && !mutationBusy && (admin || enabled)) loadDevices(targetGeneration);
  });
  setInterval(() => {
    if (!document.hidden && !sessionExpired && listRequestGeneration === null && !mutationBusy && (admin || enabled)) loadDevices(targetGeneration);
  }, 30000);
  window.VPNPortal = {
    selectUser(id) {
      if (isBusy()) return false;
      const found = admin ? users.find(value => String(value.id) === String(id)) : user && String(user.id) === String(id) ? user : null;
      if (!found) return false;
      if (targetUser && String(targetUser.id) === String(found.id)) return true;
      if (admin) $('target-user').value = String(found.id);
      setTarget(found, false);
      return true;
    },
    refresh: () => loadDevices(targetGeneration),
    openDevice: selectDevice,
    cancelDetail: keepId => { if (!keepId || String(currentDetail?.id) !== String(keepId)) clearDetail(); },
    isBusy,
    self: () => safeUser(user),
  };
  document.addEventListener('vpn:layout', () => renderUsage(lastRenderedUsage));
  window.addEventListener('resize', () => renderUsage(lastRenderedUsage));
  initialize();
})();
