'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const UTC8 = 8 * 60 * 60 * 1000;
  const formatBytes = value => {
    if (value === null || value === undefined || !Number.isFinite(value)) return '未知';
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']; let n = Math.max(0, value), i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (i ? n.toFixed(n >= 100 ? 1 : 2) : String(Math.round(n))) + ' ' + units[i];
  };
  const localDate = epoch => new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(new Date(epoch * 1000));
  const dateInputToday = () => new Date(Date.now() + UTC8).toISOString().slice(0, 10);
  const dayStart = dateText => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateText || '');
    if (!match) throw new Error('请选择有效日期。');
    const ms = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) - UTC8;
    if (new Date(ms + UTC8).toISOString().slice(0, 10) !== dateText) throw new Error('请选择有效日期。');
    return Math.floor(ms / 1000);
  };
  async function api(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal, ...options });
      if (!response.ok) throw new Error('请求暂不可用（' + response.status + '）');
      return await response.json();
    } finally { clearTimeout(timer); }
  }

  const tools = $('history-tools');
  tools.innerHTML = '<div class="history-controls"><label>开始日期<input id="history-start" type="date"></label><label>结束日期（含）<input id="history-end" type="date"></label><button class="ghost" id="history-apply" type="button">查询范围</button><button class="ghost" id="history-back-day" type="button">返回今日</button><button class="ghost" id="history-back-level" type="button" hidden>返回上一级</button></div><p id="history-status" class="small muted" role="status" aria-live="polite">日期按 UTC+8 解释；范围含首尾两天。</p><div class="comparison"><strong>今日与昨日</strong><span id="comparison-result">正在读取…</span></div>';
  $('history-start').value = dateInputToday(); $('history-end').value = dateInputToday();

  let currentQuery = null;
  let parentReport = null;
  async function fetchHistory(query) {
    const params = new URLSearchParams({ start: String(query.start), end: String(query.end), step: String(query.step) });
    const report = await api('/api/history?' + params.toString());
    if (!report.initialized) throw new Error('历史采集尚未初始化。');
    return report;
  }
  function displayHistory(report, query) {
    currentQuery = query;
    window.vpnUsageUI?.showHistory(report);
    document.querySelectorAll('[data-period]').forEach(button => {
      button.classList.remove('active'); button.setAttribute('aria-pressed', 'false');
    });
  }
  async function runHistory(query, successText, ownLock=true) {
    if(ownLock&&!window.vpnUsageUI.beginHistory())return;
    $('history-apply').disabled = true;
    $('history-status').textContent = '正在读取所选范围…';
    $('history-status').classList.remove('error');
    try {
      const report = await fetchHistory(query);
      displayHistory(report, query);
      $('history-status').textContent = successText || `${localDate(query.start)} 至 ${localDate(query.end)} · UTC+8`;
      return report;
    } catch (error) {
      $('history-status').textContent = error.message || '历史范围读取失败；仍显示最后一次成功结果。';
      $('history-status').classList.add('error');
      throw error;
    } finally { $('history-apply').disabled = false;if(ownLock)window.vpnUsageUI.endHistory(); }
  }
  $('history-apply').addEventListener('click', async () => {
    try {
      const start = dayStart($('history-start').value);
      const end = dayStart($('history-end').value) + 86400;
      const days = (end - start) / 86400;
      if (end <= start || days > 366) throw new Error('结束日期需不早于开始日期，最多可查 366 天。');
      await runHistory({ start, end, step: days > 7 ? 86400 : 3600 });
    } catch (error) {
      if (!$('history-status').classList.contains('error')) {
        $('history-status').textContent = error.message || '请选择有效日期范围。';
        $('history-status').classList.add('error');
      }
    }
  });
  $('history-back-day').addEventListener('click', () => document.querySelector('[data-period="day"]').click());
  $('history-back-level').addEventListener('click', () => {
    if(window.vpnUsageUI.isBusy())return;
    if (!parentReport) return;
    const previous = parentReport; parentReport = null;
    displayHistory(previous.report, previous.query);
    $('history-back-level').hidden = true;
    $('history-status').textContent = '已返回上一级历史范围。';
  });
  async function drill(point) {
    const duration = point.end - point.start;
    const step = duration >= 86400 ? 3600 : duration >= 3600 ? 60 : null;
    if (!step) return;
    if(!window.vpnUsageUI.beginHistory())return;
    try {
      const previous = currentQuery ? await fetchHistory(currentQuery) : null;
      const query = { start: point.start, end: point.end, step };
      const report = await fetchHistory(query);
      if (previous && currentQuery) parentReport = { report: previous, query: currentQuery };
      else parentReport = null;
      $('history-back-level').hidden = !parentReport;
      displayHistory(report, query);
      $('history-start').value = new Date(point.start * 1000 + UTC8).toISOString().slice(0, 10);
      $('history-end').value = new Date((point.end - 60) * 1000 + UTC8).toISOString().slice(0, 10);
      $('history-status').textContent = `已展开 ${point.full_label}；点击“返回上一级”或“返回今日”。`;
    } catch (error) {
      $('history-status').textContent = error.message || '展开时段失败；当前图表保持不变。';
      $('history-status').classList.add('error');
    } finally {window.vpnUsageUI.endHistory();}
  }
  const ui = window.vpnUsageUI || {};
  ui.drill = (point, period) => {
    if (period !== 'custom' && currentQuery) return;
    drill(point);
  };
  ui.refresh = async () => { if (currentQuery) await runHistory(currentQuery, '已更新自选历史范围。',false); };
  ui.resetHistory = () => { currentQuery = null; parentReport = null; $('history-back-level').hidden = true; };
  window.vpnUsageUI = ui;

  async function comparison() {
    const today = dayStart(dateInputToday());
    $('comparison-result').textContent = '正在读取…';
    try {
      const [yesterday, todayReport] = await Promise.all([
        fetchHistory({ start: today - 86400, end: today, step: 3600 }),
        fetchHistory({ start: today, end: today + 86400, step: 3600 }),
      ]);
      const summarize = report => {
        const known = report.series.filter(point => point.total_bytes !== null);
        const unknown = report.series.length - known.length;
        if(!known.length)return '未知 · 尚无已采集时段';
        const total = report.period_total.total_bytes;
        return `${formatBytes(total)} 已知${unknown ? ` · ${unknown} 个未知时段` : ''}${report.period_total?.incomplete ? ' · 含中断' : ''}`;
      };
      $('comparison-result').textContent = `今日截至目前：${summarize(todayReport)}；昨日整日：${summarize(yesterday)}。仅并列展示，不做百分比推断。`;
    } catch (error) { $('comparison-result').textContent = '暂时无法读取昨日与今日的历史用量。'; }
  }
  comparison();

  const subscriptionStatus = $('subscription-status');
  let subscription = null;
  function clearSubscription() {
    subscription = null;
    $('copy-subscription').disabled = true;
    $('copy-shadowrocket-subscription').disabled = true;
    $('clash-deeplink').href = '#clash-subscription'; $('clash-deeplink').setAttribute('aria-disabled', 'true');
    $('shadowrocket-subscription-deeplink').href='#clash-subscription';$('shadowrocket-subscription-deeplink').setAttribute('aria-disabled','true');
    $('manual-subscription').value = ''; $('manual-subscription').hidden = true;
  }
  function installSubscription(value) {
    if (!value || !value.clash_url || !value.shadowrocket_url) throw new Error('服务器未返回完整订阅地址。');
    subscription = {
      clash_url: new URL(value.clash_url, location.href).href,
      shadowrocket_url: new URL(value.shadowrocket_url, location.href).href,
    };
    $('copy-subscription').disabled = false; $('copy-shadowrocket-subscription').disabled = false;
    $('clash-deeplink').href = 'clash://install-config?url=' + encodeURIComponent(subscription.clash_url);
    $('clash-deeplink').setAttribute('aria-disabled', 'false');
    $('shadowrocket-subscription-deeplink').href='shadowrocket://add/'+encodeURIComponent(subscription.shadowrocket_url);
    $('shadowrocket-subscription-deeplink').setAttribute('aria-disabled','false');
    $('rotate-subscription').hidden = false;
    subscriptionStatus.textContent = '私有订阅已就绪。此地址只保存在当前页面内存中。';
    subscriptionStatus.classList.remove('error');
  }
  async function readSubscription() {
    try { installSubscription(await api('/api/subscription')); }
    catch (error) { clearSubscription(); subscriptionStatus.textContent = error.message || '暂时无法读取私有订阅。'; subscriptionStatus.classList.add('error'); }
  }
  async function copyValue(value, label) {
    try {
      await navigator.clipboard.writeText(value);
      $('manual-subscription').value = ''; $('manual-subscription').hidden = true;
      subscriptionStatus.textContent = `${label}已复制。请勿转发此私有地址。`;
    } catch (error) {
      $('manual-subscription').value = value; $('manual-subscription').hidden = false;
      $('manual-subscription').focus(); $('manual-subscription').select();
      subscriptionStatus.textContent = '剪贴板不可用，请全选下方私有地址并手动复制。';
    }
  }
  $('copy-subscription').addEventListener('click', () => subscription && copyValue(subscription.clash_url, 'Clash 订阅地址'));
  $('copy-shadowrocket-subscription').addEventListener('click', () => subscription && copyValue(subscription.shadowrocket_url, 'Shadowrocket 自动更新地址'));
  $('rotate-subscription').addEventListener('click', () => { $('rotate-confirm').hidden = false; $('confirm-rotate-subscription').focus(); });
  $('cancel-rotate-subscription').addEventListener('click', () => { $('rotate-confirm').hidden = true; $('rotate-subscription').focus(); });
  $('confirm-rotate-subscription').addEventListener('click', async () => {
    const button = $('confirm-rotate-subscription'); button.disabled = true;
    clearSubscription(); $('rotate-confirm').hidden = true;
    subscriptionStatus.textContent = '正在轮换订阅地址…'; subscriptionStatus.classList.remove('error');
    try {
      const next = await api('/api/subscription/rotate', {
        method: 'POST', headers: { 'X-VPN-Dashboard': '1', 'Content-Type': 'application/json' }, body: '{}',
      });
      installSubscription(next);
      subscriptionStatus.textContent = '订阅地址已轮换，旧链接立即失效；现有节点连接不受影响。';
    } catch (error) {
      clearSubscription(); subscriptionStatus.textContent = error.message || '轮换失败。旧地址已从本页清除，请刷新后重试。';
      subscriptionStatus.classList.add('error');
    } finally { button.disabled = false; }
  });
  readSubscription();

  const oneClick = document.createElement('a');
  oneClick.id = 'shadowrocket-oneclick'; oneClick.className = 'btn'; oneClick.textContent = '一键导入 HY2 节点';
  oneClick.href = 'shadowrocket://add/' + encodeURIComponent($('copy-node').dataset.node);
  oneClick.setAttribute('aria-label', '使用 Shadowrocket 导入 HY2 节点');
  $('copy-node').insertAdjacentElement('beforebegin', oneClick);

  function el(tag, className, text) {
    const node = document.createElement(tag); if (className) node.className = className;
    if (text !== undefined) node.textContent = text; return node;
  }
  function healthMessage(node) {
    if (!node.fresh) return { text: '状态未知 · 检查数据已过期', cls: 'health-unknown' };
    if (node.success === true) return { text: '检查成功', cls: 'health-ok' };
    if (node.success === false) return { text: '最近检查失败', cls: 'health-bad' };
    return { text: '状态未知', cls: 'health-unknown' };
  }
  function healthCard(title, status, lines) {
    const card = el('article', 'health-card');
    const heading = el('div', 'health-heading'); heading.append(el('strong', '', title), el('span', 'health-state ' + status.cls, status.text)); card.append(heading);
    lines.forEach(line => card.append(el('p', '', line)));
    return card;
  }
  function renderHealth(data) {
    const content = $('health-content'); content.replaceChildren();
    (data.nodes || []).forEach(node => {
      const status = healthMessage(node);
      const p95 = node.p95_ms === null ? '未知' : `${Math.round(node.p95_ms)} ms`;
      const median = node.median_ms === null ? '未知' : `${Math.round(node.median_ms)} ms`;
      const latency = node.latency_ms === null ? '未知' : `${Math.round(node.latency_ms)} ms`;
      content.append(healthCard(node.node, status, [
        `最近 HTTPS 请求：${latency} · 中位数 ${median} · P95 ${p95}`,
        `24 小时失败：${node.failures ?? '未知'} · 样本：${node.samples ?? 0}`,
        `最近检查：${node.last_check ? localDate(node.last_check) : '暂无记录'} · 来源：Windows 客户端`,
      ]));
    });
    const cert = data.certificate || {};
    const certState = cert.state === 'ok' ? { text: '有效', cls: 'health-ok' } :
      cert.state === 'expired' ? { text: '已过期', cls: 'health-bad' } :
      cert.state === 'warning' ? { text: '需关注', cls: 'health-bad' } : { text: '未知', cls: 'health-unknown' };
    const expiry = typeof cert.expires_at === 'number' ? localDate(cert.expires_at) :
      cert.expires_at ? new Date(cert.expires_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '未知';
    content.append(healthCard('HTTPS 证书', certState, [
      `到期时间：${expiry}`,
      `剩余天数：${cert.days_remaining ?? '未知'} · 自动续期配置检查，不代表真实续期演练`,
    ]));
    const backup = data.backup || {};
    const backupAgeHours = backup.last_success ? (Date.now() - Date.parse(backup.last_success)) / 3600000 : Infinity;
    const backupWarning = !backup.last_success || !Number.isFinite(backupAgeHours) || backupAgeHours > 36 || backup.integrity !== 'ok' || backup.error;
    const backupState = backupWarning ? { text: '需关注', cls: 'health-bad' } : { text: '最近成功', cls: 'health-ok' };
    content.append(healthCard('本机备份', backupState, [
      `最近成功：${backup.last_success ? new Date(backup.last_success).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '暂无成功记录'}`,
      `完整性：${backup.integrity === 'ok' ? '通过' : '未知'} · 大小：${formatBytes(backup.bytes)}`,
      backup.error ? `最近错误：${backup.error}` : '备份与面板位于同一台 VPS。',
    ]));
    const renewal = data.renewal || {};
    const renewalState = renewal.configured && renewal.hook_checks_passed ?
      { text: '配置检查通过', cls: 'health-ok' } : { text: '配置待检查', cls: 'health-unknown' };
    content.append(healthCard('续期钩子', renewalState, [
      `已配置：${renewal.configured ? '是' : '否'} · 钩子检查：${renewal.hook_checks_passed ? '通过' : '未通过或未知'}`,
      `真实续期：${renewal.renewal_executed === false ? '本接口未执行' : '未知'}`,
    ]));
  }
  async function loadHealth() {
    const content = $('health-content');
    try { renderHealth(await api('/api/health')); }
    catch (error) {
      content.replaceChildren(el('p', 'health-unknown', '健康信息暂不可用；节点状态未知。'));
    }
  }
  loadHealth(); setInterval(() => { if (!document.hidden) loadHealth(); }, 5 * 60 * 1000);
})();
