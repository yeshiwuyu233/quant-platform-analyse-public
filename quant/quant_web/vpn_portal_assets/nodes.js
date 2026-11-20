'use strict';
(() => {
  const host = document.getElementById('managed-nodes');
  if (!host) return;
  let boot;
  try { boot = JSON.parse(document.getElementById('vpn-bootstrap').textContent); } catch (_) { return; }
  if (boot.user?.role !== 'admin') return;
  const labels = {hy2: 'HY2', tuic: 'TUIC', vless: 'VLESS Reality', trojan: 'Trojan'};
  let busy = false, dirty = false;
  const element = (tag, text, cls) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  };
  const date = t => Number.isFinite(Number(t)) && t ? new Date(t * 1000).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false}) : '暂无记录';
  const bytes = n => typeof n === 'number' ? (n / 1073741824).toFixed(3) + ' GiB' : '未知';
  const message = element('p', '', 'system-footnote'); message.setAttribute('role', 'status');
  async function api(path, options = {}) {
    const headers = {'Content-Type': 'application/json'};
    if (options.method) headers['X-CSRF-Token'] = boot.csrf_token;
    const response = await fetch('/vpn/api/' + path, {credentials: 'same-origin', cache: 'no-store', ...options, headers});
    const body = await response.json();
    if (!response.ok) throw new Error(response.status === 401 ? '登录已过期，请重新登录。' : body.message || '节点服务暂不可用。');
    return body;
  }
  function render(data) {
    host.replaceChildren();
    const heading = element('div', undefined, 'section-heading');
    heading.append(element('h2', '节点管理'));
    const refresh = element('button', '刷新状态', 'quiet-button'); refresh.type = 'button';
    refresh.addEventListener('click', load); heading.append(refresh); host.append(heading);
    const taiwan = (data.nodes || []).find(node => node.id === 'bytevirt-tw');
    host.append(element('p', taiwan?.admin_only === false
      ? '台湾节点已向已开通 VPN 的用户开放。普通用户所有节点、协议和设备共用账户额度与限速，台湾节点最终出口均为台湾；优先选择马来西亚中转 HY2，直连入口需要 IPv6。'
      : '原节点继续沿用现有账户额度与限速。台湾节点目前向管理员及验收设备提供；直连需要 IPv6，中转使用马来西亚入口。', 'system-footnote'));
    for (const node of data.nodes || []) {
      const primary = node.id === 'yeshiwuyu';
      const choices = Object.entries(labels).filter(([key]) => (node.available_protocols || node.protocols).includes(key));
      const agent = node.agent;
      const card = element('section', undefined, 'app-panel');
      card.dataset.nodeId = node.id;
      card.append(element('h3', node.name));
      const status = !node.enabled ? '已停用' : node.online === true ? '运行正常' : node.online === false ? '同步或服务异常' : '状态未知';
      card.append(element('p', `${status} · 最近同步 ${date(agent?.last_sync)} · 生效设备 ${agent?.user_count ?? '未知'}`));
      if (agent) {
        const memory = agent.memory?.MemTotal && agent.memory?.MemAvailable != null ? Math.round((agent.memory.MemTotal-agent.memory.MemAvailable)/1048576)+' / '+Math.round(agent.memory.MemTotal/1048576)+' MiB' : '未知';
        card.append(element('p', `内存 ${memory} · 磁盘已用 ${bytes(agent.disk?.used)} · 证书到期 ${date(agent.certificate_expires)}`, 'system-footnote'));
        if (typeof agent.active_connections === 'number') card.append(element('p', `当前连接 ${agent.active_connections} · 计量更新 ${date(node.traffic_last_sample_at || agent.last_sync)}`, 'system-footnote'));
      }
      if (node.status_error) card.append(element('p', node.status_error, 'form-error'));
      const table = element('table', undefined, 'nodes-table');
      const caption = element('caption', '协议可用性与客户端实测'); table.append(caption);
      const head = element('tr');
      for (const text of ['协议', '状态', 'HTTPS 中位数', '成功 / 总样本', '累计上传 / 下载']) head.append(element('th', text));
      const thead = element('thead'); thead.append(head); table.append(thead);
      const tbody = element('tbody');
      for (const [key, label] of choices) {
        const sample = node.benchmark?.protocols?.[key], traffic = agent?.traffic?.[key];
        const row = element('tr');
        const median = typeof sample?.median_ms === 'number' ? `${Math.round(sample.median_ms)} ms` : '尚未实测';
        const values = [label + (key === node.preferred ? ' · 推荐' : ''), node.protocols.includes(key) && node.enabled ? '已启用' : '已停用', median,
          sample ? `${sample.successes} / ${sample.samples}` : '—', traffic ? `${bytes(traffic.upload_bytes)} / ${bytes(traffic.download_bytes)}` : '未知'];
        values.forEach(text => row.append(element('td', text))); tbody.append(row);
      }
      table.append(tbody); const wrap = element('div', undefined, 'nodes-table-wrap'); wrap.append(table); card.append(wrap);
      const bench = node.benchmark;
      card.append(element('p', bench ? `测试来源：${bench.source} · ${date(bench.measured_at)} · ${bench.method || 'HTTPS 请求耗时，非 ping'}；失败样本不计入中位数。` : '协议延迟尚未完成客户端实测。', 'system-footnote'));
      if (primary) {
        if (node.traffic_status) card.append(element('p', node.traffic_status, 'system-footnote'));
        card.append(element('p', '统一账号额度与限速由此节点执行；普通用户的台湾线路也经过该计费服务。上传与下载为 HY2 端口累计 IP 字节，包含协议开销，与台湾节点计数存在重叠，请勿相加。账号、设备及限速请在用户管理中调整。', 'system-footnote'));
        host.append(card);
        continue;
      }
      card.append(element('p', '这里是台湾节点自部署起的协议传输字节，包含协议开销。普通用户的所有节点由统一计费服务扣除，同一笔流量不会再按此面板重复扣费；管理员台湾线路不扣个人额度。控制连接中断超过 90 秒时，台湾节点停止服务。', 'system-footnote'));
      const relay = node.relay;
      if (relay) {
        card.append(element('h3', '马来西亚中转'));
        card.append(element('p', '本机 → 马来西亚（HY2）→ 台湾 → 目标网站。管理员后段使用 Reality；普通用户经过统一额度与限速检查，再接台湾专用出口。最终出口均为台湾。'));
        const status = !relay.enabled ? '已停用' : !relay.available ? '等待启用台湾 Reality' : relay.online ? '运行正常' : '等待同步或检查连接';
        card.append(element('p', status));
        if (relay.runtime) card.append(element('p', `最近更新 ${date(relay.runtime.updated_at)} · 生效设备 ${relay.runtime.user_count ?? '未知'} · 当前连接 ${relay.runtime.active_connections ?? '未知'} · 中转累计上传 / 下载 ${bytes(relay.runtime.upload_bytes)} / ${bytes(relay.runtime.download_bytes)}`, 'system-footnote'));
        if (relay.benchmark) {
          const b=relay.benchmark;
          card.append(element('p', `管理员线路最近测速 ${date(b.measured_at)} · HTTPS 中位数 ${b.https_median_ms ?? '未知'} ms · 下载单连接 ${b.download_single_mbps ?? '未知'} Mbps / 4 并发 ${b.download_parallel_mbps ?? '未知'} Mbps；普通用户另受账号限速影响。`, 'system-footnote'));
        }
        card.append(element('p', '管理员中转与台湾 Reality 的计数存在重叠，请勿相加；普通用户以统一计费记录为准。中转依赖台湾节点及 Reality 启用开关，后段不可用时停止连接，不会改从马来西亚出网。', 'system-footnote'));
      }
      const form = element('form'); const checks = {};
      form.addEventListener('change',()=>{dirty=true;});
      const enabledLabel = element('label', undefined, 'toggle-label'); const enabled = element('input'); enabled.type = 'checkbox'; enabled.checked = node.enabled;
      enabledLabel.append(enabled, element('span', '启用台湾节点')); form.append(enabledLabel);
      const relayEnabled=element('input');relayEnabled.type='checkbox';
      if(relay){relayEnabled.checked=relay.enabled;const label=element('label',undefined,'toggle-label');label.append(relayEnabled,element('span','启用马来西亚中转'));form.append(label);}
      const protocolBox = element('div', undefined, 'nodes-protocols');
      for (const [key, label] of choices) {
        const box = element('input'); box.type = 'checkbox'; box.checked = node.protocols.includes(key); checks[key] = box;
        const labelNode = element('label', undefined, 'toggle-label'); labelNode.append(box, element('span', label)); protocolBox.append(labelNode);
      }
      form.append(protocolBox);
      const preferredLabel = element('label', '推荐协议 '); const preferred = element('select');
      for (const [key, label] of choices) { const option=element('option',label); option.value=key; preferred.append(option); }
      preferred.value=node.preferred; preferredLabel.append(preferred); form.append(preferredLabel);
      form.append(element('p', '设置约 10 秒生效；协议或设备凭据变化时连接可能重连。设备上已保存的订阅需更新。', 'system-footnote'));
      const save = element('button', '保存节点设置', 'primary-button'); save.type = 'submit'; form.append(save);
      const cancel = element('button', '放弃修改', 'quiet-button'); cancel.type='button';
      cancel.addEventListener('click',()=>{dirty=false;render(data);});form.append(cancel);
      form.addEventListener('submit', async event => {
        event.preventDefault(); if (busy) return;
        const protocols=Object.keys(checks).filter(k=>checks[k].checked);
        if (!protocols.length || !protocols.includes(preferred.value)) {message.textContent='请至少启用一个协议，并将推荐协议设为已启用的项目。';return;}
        busy=true; save.disabled=true; message.textContent='正在保存…';
        try {
          await api('admin/nodes/bytevirt-tw',{method:'PATCH',body:JSON.stringify({enabled:enabled.checked,protocols,preferred:preferred.value,...(relay?{relay_enabled:relayEnabled.checked}:{})})});
          message.textContent='已保存，等待台湾节点同步。';dirty=false;
        } catch (error) {message.textContent=error.message;}
        finally {busy=false;save.disabled=false;}
      });
      card.append(form); host.append(card);
    }
    host.append(message);
  }
  async function load() {
    if (busy || dirty || document.hidden || location.hash !== '#/admin/server') return;
    try {const data=await api('admin/nodes');render(data);}
    catch(error){host.replaceChildren(element('h2','节点管理'),element('p',error.message,'form-error'));}
  }
  window.addEventListener('hashchange',load);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
  setInterval(load,15000);load();
})();
