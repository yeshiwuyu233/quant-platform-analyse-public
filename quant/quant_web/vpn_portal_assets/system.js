'use strict';
(() => {
  const bootstrapNode = document.getElementById('vpn-bootstrap');
  let bootstrap;
  try { bootstrap = JSON.parse(bootstrapNode ? bootstrapNode.textContent : '{}'); } catch (_) { return; }
  if (!bootstrap || !bootstrap.user || bootstrap.user.role !== 'admin') return;

  const mount = document.getElementById('system-overview-mount');
  const template = document.getElementById('system-overview-template');
  if (!mount || !template) return;
  mount.append(template.content.cloneNode(true));

  const $ = id => document.getElementById(id);
  const UTC8 = 8 * 60 * 60 * 1000;
  const names = { day: '今日', week: '近 7 天', month: '近 30 天' };
  let selectedPeriod = 'day', shownReport = null, shownKind = null, activeView = 'period';
  let viewRequest = 0, healthRequest = 0;

  const bytes = value => window.VPNViewModel.gb(value) + (window.VPNViewModel.known(value) ? ' GB' : '');
  const localDate = (epoch, dateOnly = false) => {
    if (epoch === null || epoch === undefined || !Number.isFinite(Number(epoch))) return '未知';
    const options = dateOnly ? { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' } :
      { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };
    return new Intl.DateTimeFormat('zh-CN', options).format(new Date(Number(epoch) * 1000));
  };
  const todayText = () => new Date(Date.now() + UTC8).toISOString().slice(0, 10);
  const dateEpoch = text => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text || '');
    if (!match) throw new Error('请选择有效的起止日期。');
    const value = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) - UTC8;
    if (new Date(value + UTC8).toISOString().slice(0, 10) !== text) throw new Error('请选择有效的起止日期。');
    return Math.floor(value / 1000);
  };
  const element = (tag, className, text) => {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined && text !== null) result.textContent = String(text);
    return result;
  };
  function setError(text) {
    const box = $('system-error');
    box.textContent = text || '';
    box.hidden = !text;
  }
  async function api(path, signal) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    if (signal) signal.addEventListener('abort', () => controller.abort(), { once: true });
    try {
      for (let attempt = 0; attempt < 2; attempt++) {
        const response = await fetch(`/vpn/api/admin/system/${path}`, {
          credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
          headers: { Accept: 'application/json' },
        });
        let payload = null;
        try { payload = await response.json(); } catch (_) { payload = null; }
        if (response.ok) return payload || {};

        const code = payload && (payload.code || payload.error || payload.message);
        const temporary = [502, 503, 504].includes(response.status);
        if (temporary && attempt === 0 && !controller.signal.aborted) {
          await new Promise((resolve, reject) => {
            const retryTimer = setTimeout(resolve, 300);
            controller.signal.addEventListener('abort', () => {
              clearTimeout(retryTimer);
              const aborted = new Error('Aborted'); aborted.name = 'AbortError'; reject(aborted);
            }, { once: true });
          });
          continue;
        }
        if (code === 'vpn_service_unavailable' || temporary) {
          throw new Error('服务器总览读取暂时失败；这不表示 VPN 节点已停止。可刷新重试。');
        }
        if (response.status === 401) throw new Error('登录状态已过期，请重新登录后刷新总览。');
        if (response.status === 403) throw new Error('当前账户没有读取服务器总览的管理员权限。');
        const detail = payload && (payload.message || payload.error || payload.detail);
        throw new Error(typeof detail === 'string' ? detail : `服务器总览读取失败（HTTP ${response.status}）。`);
      }
      throw new Error('服务器总览读取暂时失败；可刷新重试。');
    } catch (error) {
      if (error && error.name === 'AbortError') throw new Error('服务器总览请求超时，读取暂时失败；可刷新重试。');
      if (error instanceof TypeError) throw new Error('服务器总览网络读取暂时失败，可刷新重试。');
      throw error;
    } finally { clearTimeout(timer); }
  }
  function historyUrl(query) {
    const params = new URLSearchParams({ start: String(query.start), end: String(query.end), step: String(query.step) });
    return `history?${params}`;
  }
  function setPeriodButtons(period) {
    document.querySelectorAll('[data-system-period]').forEach(button => {
      const active = button.dataset.systemPeriod === period;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }
  function valueSummary(report) {
    if (!report || !report.initialized || !report.period_total) return '未知 · 尚未初始化';
    const total = report.period_total;
    const points = Array.isArray(report.series) ? report.series : [];
    const known = points.filter(point => point.total_bytes !== null && point.total_bytes !== undefined && Number.isFinite(Number(point.total_bytes))).length;
    if (!known) return '未知 · 所选范围没有已知时段';
    const unknown = points.length - known;
    return `${bytes(total.total_bytes)}${unknown ? ` · ${unknown} 个时段未知` : ''}${total.incomplete ? ' · 含未知区间' : total.has_gaps ? ' · 含采集中断' : ''}`;
  }
  function renderTotals(report, label) {
    const total = report && report.period_total;
    const points = report && Array.isArray(report.series) ? report.series : [];
    const hasKnownBucket = points.some(point => point.total_bytes !== null && point.total_bytes !== undefined && Number.isFinite(Number(point.total_bytes)));
    $('system-period-down').textContent = total && hasKnownBucket ? bytes(total.download_bytes) : '未知';
    $('system-period-up').textContent = total && hasKnownBucket ? bytes(total.upload_bytes) : '未知';
    $('system-period-down-label').textContent = label;
    $('system-period-up-label').textContent = label;
    if (report && report.lifetime) {
      $('system-life-down').textContent = bytes(report.lifetime.download_bytes);
      $('system-life-up').textContent = bytes(report.lifetime.upload_bytes);
    } else if (report && !report.initialized) {
      $('system-life-down').textContent = '未知'; $('system-life-up').textContent = '未知';
    }
  }
  function drawChart(report) {
    const svg = $('system-usage-chart');
    svg.replaceChildren();
    const points = report && Array.isArray(report.series) ? report.series : [];
    const width = Math.max(280, Math.round(svg.parentElement.getBoundingClientRect().width) || Math.min(850, window.innerWidth - 64)), height = 245, left = 72, right = 14, top = 15, bottom = 40;
    const plotWidth = width - left - right, plotHeight = height - top - bottom;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    const known = points.filter(point => point.total_bytes !== null && point.total_bytes !== undefined && Number.isFinite(Number(point.total_bytes)));
    const maximum = Math.max(1024, ...known.map(point => Number(point.total_bytes)));
    const y = value => top + plotHeight - plotHeight * value / maximum;
    const svgNode = (tag, attrs = {}, text) => {
      const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
      Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
      if (text !== undefined) node.textContent = text;
      svg.append(node); return node;
    };
    const defs = svgNode('defs');
    const pattern = document.createElementNS('http://www.w3.org/2000/svg', 'pattern');
    pattern.setAttribute('id', 'system-unknown-hatch'); pattern.setAttribute('width', '6'); pattern.setAttribute('height', '6'); pattern.setAttribute('patternUnits', 'userSpaceOnUse'); pattern.setAttribute('patternTransform', 'rotate(45)');
    const hatch = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    hatch.setAttribute('x1', '0'); hatch.setAttribute('y1', '0'); hatch.setAttribute('x2', '0'); hatch.setAttribute('y2', '6'); hatch.setAttribute('stroke', '#d9dce6'); hatch.setAttribute('stroke-width', '2'); pattern.append(hatch); defs.append(pattern);
    for (let i = 0; i <= 4; i++) {
      const value = maximum * i / 4, yy = y(value);
      svgNode('line', { x1: left, y1: yy, x2: width - right, y2: yy, stroke: 'var(--app-line-soft)', 'stroke-dasharray': i ? '3 4' : '0' });
      svgNode('text', { x: left - 10, y: yy + 3, 'text-anchor': 'end', fill: 'var(--app-muted)', 'font-size': 10 }, bytes(value));
    }
    const stride = points.length ? plotWidth / points.length : plotWidth;
    const barWidth = Math.max(2, Math.min(30, stride * .52));
    points.forEach((point, index) => {
      const x = left + stride * index + stride / 2;
      const label = point.label || point.full_label || localDate(point.start);
      if (point.total_bytes === null || point.total_bytes === undefined || !Number.isFinite(Number(point.total_bytes))) {
        svgNode('rect', { x: x - barWidth / 2, y: top, width: barWidth, height: plotHeight, fill: 'url(#system-unknown-hatch)', opacity: .45, rx: 2, 'aria-label': `${label}：未知时段，状态 ${point.state || 'unknown'}` });
      } else {
        const down = Number(point.download_bytes || 0), up = Number(point.upload_bytes || 0);
        const downHeight = plotHeight * down / maximum, upHeight = plotHeight * up / maximum;
        if (downHeight > 0) svgNode('rect', { x: x - barWidth / 2, y: top + plotHeight - downHeight, width: barWidth, height: downHeight, fill: 'var(--app-accent)', rx: 2 });
        if (upHeight > 0) svgNode('rect', { x: x - barWidth / 2, y: top + plotHeight - downHeight - upHeight, width: barWidth, height: upHeight, fill: 'var(--app-upload)', rx: 2 });
        if (Number(point.total_bytes) === 0) svgNode('circle', { cx: x, cy: top + plotHeight - 1, r: 2, fill: '#a9a3e8' });
        const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
        title.textContent = `${label} · 下载 ${bytes(point.download_bytes)} · 上传 ${bytes(point.upload_bytes)} · ${point.state || 'recorded'}`;
        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        const hit = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        hit.setAttribute('x', String(x - stride / 2)); hit.setAttribute('y', String(top)); hit.setAttribute('width', String(stride)); hit.setAttribute('height', String(plotHeight)); hit.setAttribute('fill', 'transparent'); g.append(hit, title); svg.append(g);
      }
      const slots = Math.max(2, Math.floor(plotWidth / 90));
      const xLabel = index % Math.max(1, Math.ceil(points.length / slots)) === 0 || index === points.length - 1 ? label : '';
      svgNode('text', { x, y: height - 10, 'text-anchor': 'middle', fill: 'var(--app-muted)', 'font-size': 9 }, xLabel);
    });
    svg.setAttribute('aria-label', `全机用量图：${known.length} 个已知时段，${points.length - known.length} 个未知时段；未知未按零计算`);
    const empty = $('system-chart-empty');
    if (!points.length || !known.length) {
      empty.textContent = points.length ? '当前范围没有已知时段；未知历史不会显示为 0。' : '当前范围没有统计记录。'; empty.hidden = false;
    } else empty.hidden = true;
  }
  function renderUsage(report, kind, label) {
    renderTotals(report, label);
    drawChart(report);
    const gaps = Boolean(report && ((report.coverage && report.coverage.has_gaps) || (report.period_total && (report.period_total.incomplete || report.period_total.has_gaps))));
    const start = report && report.started_at ? localDate(report.started_at) : '未知';
    const last = report && report.last_sample_at ? localDate(report.last_sample_at) : '未知';
    $('system-usage-note').textContent = `计量范围：${report && report.scope ? report.scope : '服务器全机计量'} · 记录开始 ${start} · 最近采样 ${last}${gaps ? ' · 存在采集间断，未知区间保留为空' : ''}`;
    shownReport = report; shownKind = kind;
    $('system-export').disabled = !report || !Array.isArray(report.series) || !report.series.length;
  }
  function csvExport() {
    if (!shownReport || !Array.isArray(shownReport.series)) return;
    const rows = [['时段开始（Asia/Shanghai）', '下载字节', '上传字节', '合计字节', '记录状态']];
    shownReport.series.forEach(point => rows.push([
      point.full_label || (point.start ? localDate(point.start) : ''),
      point.download_bytes ?? '', point.upload_bytes ?? '', point.total_bytes ?? '', point.state || '',
    ]));
    if (shownReport.series_unallocated_bytes) rows.push(['中断范围内已知但无法分桶', '', '', shownReport.series_unallocated_bytes, 'unallocated']);
    const csv = '\uFEFF' + rows.map(row => row.map(value => `"${String(value).replaceAll('"', '""')}"`).join(',')).join('\r\n');
    const blobUrl = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a'); link.href = blobUrl;
    const date = todayText(); link.download = `vpn-server-${shownKind || 'history'}-${date}.csv`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  }
  function previousQuery(start, end, step) {
    const duration = end - start;
    return { start: start - duration, end: start, step };
  }
  async function showComparison(current, query, requestId) {
    const result = $('system-comparison').querySelector('span');
    result.textContent = '正在读取前一周期…';
    try {
      const prev = await api(historyUrl(previousQuery(query.start, query.end, query.step)));
      if (requestId !== viewRequest) return;
      result.textContent = `${localDate(query.start, true)} 至 ${localDate(query.end - 1, true)}：${valueSummary(current)}；前一周期 ${localDate(query.start - (query.end - query.start), true)} 至 ${localDate(query.start - 1, true)}：${valueSummary(prev)}。均为 API 记录值，含未知/中断标记。`;
    } catch (_) {
      if (requestId !== viewRequest) return;
      result.textContent = '当前数据已读取；前一周期暂不可用，未作零值比较。';
    }
  }
  function rangeFromSeries(report, step) {
    const series = report && Array.isArray(report.series) ? report.series : [];
    if (!series.length) throw new Error('服务器尚无可查询时段。');
    return { start: Number(series[0].start), end: Number(series[series.length - 1].end), step };
  }
  async function loadPreset(period) {
    const requestId = ++viewRequest;
    const button = $('system-refresh'); button.disabled = true;
    $('system-history-run').disabled = true;
    $('system-history-status').textContent = '正在读取服务器统计…';
    try {
      const report = await api(`usage?period=${encodeURIComponent(period)}`);
      if (requestId !== viewRequest) return;
      if (!report || !Array.isArray(report.series)) throw new Error('统计接口返回的数据格式无法识别。');
      selectedPeriod = period;
      activeView = 'period';
      setPeriodButtons(period);
      renderUsage(report, period, names[period]);
      $('system-history-status').textContent = `已显示${names[period]}数据。可选择日期查询更长历史。`;
      $('system-history-start').value = todayText();
      $('system-history-end').value = todayText();
      const query = rangeFromSeries(report, period === 'day' ? 3600 : 86400);
      $('system-comparison').querySelector('span').textContent = '正在读取前一周期…';
      showComparison(report, query, requestId);
      setError('');
    } catch (error) {
      if (requestId !== viewRequest) return;
      setError(error.message || '暂时无法读取服务器用量；当前仍保留最后一次成功数据。');
      $('system-history-status').textContent = `读取暂时失败，可刷新重试。图表、摘要和导出仍保留最后一次成功结果。${error.message ? ` ${error.message}` : ''}`;
    } finally {
      if (requestId === viewRequest) { button.disabled = false; $('system-history-run').disabled = false; }
    }
  }
  async function runHistory() {
    let start, end, requestId = null;
    try {
      start = dateEpoch($('system-history-start').value);
      end = dateEpoch($('system-history-end').value) + 86400;
      if (end <= start) throw new Error('结束日期必须不早于开始日期。');
      const duration = end - start;
      if (duration > 366 * 86400) throw new Error('一次最多查询 366 天。');
      const step = duration > 31 * 86400 ? 86400 : 3600;
      if (step === 3600 && Math.ceil(duration / step) > 1440) throw new Error('所选范围过长，请缩短日期范围。');
      const query = { start, end, step };
      requestId = ++viewRequest;
      $('system-refresh').disabled = true;
      $('system-history-run').disabled = true;
      $('system-history-status').textContent = '正在查询所选范围…';
      $('system-history-status').classList.remove('error');
      const report = await api(historyUrl(query));
      if (requestId !== viewRequest) return;
      if (!report || !Array.isArray(report.series)) throw new Error('历史接口返回的数据格式无法识别。');
      renderUsage(report, 'custom', '自选范围');
      activeView = 'custom';
      setPeriodButtons(null);
      $('system-history-status').textContent = `查询范围 ${localDate(start, true)} 至 ${localDate(end - 1, true)}，${step === 3600 ? '按小时' : '按天'}聚合；未知时段保留为空。`;
      setError('');
      await showComparison(report, query, requestId);
    } catch (error) {
      if (requestId !== null && requestId !== viewRequest) return;
      $('system-history-status').textContent = `${error.message || '历史查询读取暂时失败，可刷新重试。'} 当前图表、摘要和 CSV 保留最后一次成功数据。`;
      $('system-history-status').classList.add('error');
      if (start !== undefined && end !== undefined && end > start) $('system-comparison').querySelector('span').textContent = '范围查询失败，未生成前一周期对比。';
    } finally {
      if (requestId !== null && requestId === viewRequest) { $('system-refresh').disabled = false; $('system-history-run').disabled = false; }
    }
  }
  function stateBadge(text, state) {
    return element('span', `system-state ${state}`, text);
  }
  function healthCard(title, stateText, stateClass, lines) {
    const card = element('article', 'system-health-card');
    const heading = element('div', 'system-health-heading');
    heading.append(element('strong', '', title), stateBadge(stateText, stateClass));
    card.append(heading);
    lines.forEach(text => card.append(element('p', '', text)));
    return card;
  }
  function renderHealth(report) {
    const host = $('system-health-cards'); host.replaceChildren();
    (Array.isArray(report.nodes) ? report.nodes : []).forEach(node => {
      let stateText = '状态未知', stateClass = 'unknown';
      const inventoryFresh = node.inventory_fresh === true;
      const notConfigured = inventoryFresh && node.configured === false;
      const ambiguous = inventoryFresh && node.configured === null;
      if (node.retired === true) { stateText = '已停用'; stateClass = 'unknown'; }
      else if (notConfigured) { stateText = '本机未配置'; stateClass = 'unknown'; }
      else if (ambiguous) { stateText = '检测节点不明确'; stateClass = 'unknown'; }
      else if (!node.fresh) { stateText = '数据过期'; stateClass = 'unknown'; }
      else if (node.success === true) { stateText = '检查成功'; stateClass = 'ok'; }
      else if (node.success === false) { stateText = '最近检查失败'; stateClass = 'bad'; }
      const ms = value => value === null || value === undefined ? '未知' : `${Math.round(Number(value))} ms`;
      let details;
      if (node.retired === true) {
        details = ['旧共享入口已停用，防止绕过账号额度与限速。', '请使用“我的设备”中生成的独立 HY2 订阅；历史探测结果不代表当前服务故障。'];
      } else if (notConfigured) {
        details = [
          '当前订阅未配置该协议，未执行本轮探测。',
          `24 小时历史检查失败：${node.failures ?? '未知'} · 历史样本：${node.samples ?? '未知'}`,
          `配置清单更新时间：${node.inventory_at ? localDate(node.inventory_at) : '未知'} · 来源：此 Windows 客户端`,
        ];
      } else if (ambiguous) {
        details = [
          '当前订阅中的节点无法明确对应此协议探测目标。',
          `最近检查：${node.last_check ? localDate(node.last_check) : '暂无记录'} · 来源：此 Windows 客户端`,
        ];
      } else {
        details = [
          `最近 HTTPS 请求延迟：${ms(node.latency_ms)} · 中位数 ${ms(node.median_ms)} · P95 ${ms(node.p95_ms)}`,
          `24 小时失败：${node.failures ?? '未知'} · 样本：${node.samples ?? '未知'}`,
          `最近检查：${node.last_check ? localDate(node.last_check) : '暂无记录'} · 来源：此 Windows 客户端`,
        ];
      }
      host.append(healthCard(node.node || '节点', stateText, stateClass, details));
    });
    const cert = report.certificate || {};
    const certState = cert.state === 'ok' ? ['有效', 'ok'] : cert.state === 'expired' ? ['已过期', 'bad'] : cert.state === 'warning' ? ['需关注', 'bad'] : ['未知', 'unknown'];
    host.append(healthCard('HTTPS 证书', certState[0], certState[1], [
      `到期时间：${cert.expires_at ? localDate(cert.expires_at) : '未知'}`,
      `剩余天数：${cert.days_remaining ?? '未知'} · 自动续期配置/钩子状态不代表实际续期演练`,
    ]));
    const backup = report.backup || {};
    const age = backup.last_success ? (Date.now() - Date.parse(backup.last_success)) / 3600000 : Infinity;
    const backupWarn = !backup.last_success || !Number.isFinite(age) || age > 36 || backup.integrity !== 'ok' || Boolean(backup.error);
    host.append(healthCard('本机备份', backupWarn ? '需关注' : '最近成功', backupWarn ? 'bad' : 'ok', [
      `最近成功：${backup.last_success ? new Date(backup.last_success).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '暂无成功记录'}`,
      `完整性：${backup.integrity === 'ok' ? '通过' : '未知'} · 大小：${bytes(backup.bytes)}`,
      backup.error ? `最近错误：${backup.error}` : '备份与面板位于同一台 VPS。',
    ]));
    const renewal = report.renewal || {};
    const renewalOk = Boolean(renewal.configured && renewal.hook_checks_passed);
    host.append(healthCard('续期钩子', renewalOk ? '配置检查通过' : '配置待检查', renewalOk ? 'ok' : 'unknown', [
      `已配置：${renewal.configured ? '是' : '否'} · 钩子检查：${renewal.hook_checks_passed ? '通过' : '未通过或未知'}`,
      `真实续期：${renewal.renewal_executed === false ? '本接口未执行' : '未知'}`,
    ]));
    $('system-health-updated').textContent = `更新于 ${localDate(Date.now() / 1000)}`;
  }
  async function loadHealth() {
    const requestId = ++healthRequest;
    try {
      const report = await api('health');
      if (requestId !== healthRequest) return;
      renderHealth(report);
    } catch (error) {
      if (requestId !== healthRequest) return;
      const host = $('system-health-cards'); host.replaceChildren(element('p', 'system-health-error', error.message || '健康信息暂不可用；节点状态未知。'));
    }
  }

  $('system-export').addEventListener('click', csvExport);
  document.querySelectorAll('[data-system-period]').forEach(button => button.addEventListener('click', () => loadPreset(button.dataset.systemPeriod)));
  const refreshUsage = () => activeView === 'custom' ? runHistory() : loadPreset(selectedPeriod);
  $('system-refresh').addEventListener('click', () => { refreshUsage(); loadHealth(); });
  $('system-history-run').addEventListener('click', runHistory);
  $('system-history-reset').addEventListener('click', () => loadPreset(selectedPeriod));
  $('system-history-start').value = todayText(); $('system-history-end').value = todayText();
  document.addEventListener('vpn:layout', () => { if (shownReport) drawChart(shownReport); });
  window.addEventListener('resize', () => { if (shownReport) drawChart(shownReport); });
  loadPreset(selectedPeriod); loadHealth();
  setInterval(() => { if (!document.hidden) { refreshUsage(); loadHealth(); } }, 60000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { refreshUsage(); loadHealth(); } });
})();
