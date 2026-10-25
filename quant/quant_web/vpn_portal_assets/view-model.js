'use strict';
(function (root) {
  const routes = {
    overview: ['账户总览', '查看可用流量，管理设备与订阅。'],
    devices: ['我的设备', '每台设备使用独立配置，可单独更新和停用。'],
    devicedetail: ['设备订阅', '复制或扫码导入该设备的独立配置。'],
    usage: ['套餐与用量', '查看余额组成、有效期与已记录的上下行用量。'],
    help: ['下载与帮助', '选择适用的客户端，按步骤导入设备配置。'],
    admin: ['管理总览', '查看服务器运行摘要，快速进入用户管理。'],
    users: ['用户管理', '管理网站账号、VPN 权限和用户套餐。'],
    userdetail: ['用户详情', '在明确的管理对象下调整套餐、管理设备与查阅记录。'],
    server: ['服务器运行', '全机用量、历史记录与节点维护状态。'],
    audit: ['操作记录', '查看所选用户的额度变更、操作者与时间。']
  };
  const adminRoutes = {admin:'admin', 'admin/users':'users', 'admin/server':'server', 'admin/audit':'audit'};
  function resolveRoute(hash, isAdmin) {
    const path = String(hash || '').replace(/^#\/?/, '').replace(/\/$/, '');
    const detail = /^admin\/user\/([1-9]\d*)(?:\/device\/([a-f0-9]{32}))?$/.exec(path);
    const device = /^devices\/([a-f0-9]{32})$/.exec(path);
    const adminOnly = path === 'admin' || path.startsWith('admin/');
    const denied = adminOnly && !isAdmin;
    let key = ['overview','devices','usage','help'].includes(path) ? path : adminRoutes[path] || (detail ? 'userdetail' : device ? 'devicedetail' : 'overview');
    if (denied) key = 'overview';
    return {key, adminOnly:!denied && adminOnly && key!=='overview', denied, targetId:!denied && detail ? detail[1] : null, deviceId:!denied ? detail?.[2] || device?.[1] || null : null, title:routes[key][0], description:routes[key][1]};
  }
  function known(value) { return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)); }
  function gb(value) {
    if (!known(value)) return '未知';
    const n = Math.max(0,Number(value))/1e9;
    if (n > 0 && n < .01) return '不足 0.01';
    return new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(n);
  }
  function date(value, time=false) {
    if (!known(value)) return '暂无记录';
    const options={timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'};
    if(time) Object.assign(options,{hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
    return new Intl.DateTimeFormat('zh-CN',options).format(new Date(Number(value)*1000));
  }
  const speed = value => value === null || value === undefined || value === '' ? '不限速' : known(value) ? `${Number(value)} Mbps` : '未知';
  function quotaSummary(q) {
    q=q || {};
    const unlimited = q.is_admin === true || q.unlimited === true;
    let status='正在读取', tone='neutral';
    if (q.vpn_enabled === false) {status='VPN 未开通或已停用';tone='danger';}
    else if(unlimited){status=q.is_admin?'管理员 · 无限量 · 不限速':'无限量';tone='success';}
    else if(!known(q.remaining_bytes)){status='额度状态未知';}
    else if(Number(q.remaining_bytes)<=0){status=q.subscription_expired?'套餐已到期，暂无可用额度':'额度已用尽，VPN 已暂停';tone='danger';}
    else if(q.subscription_expired && Number(q.permanent_remaining_bytes)>0){status='月套餐已到期，永久额度仍可用';tone='warning';}
    else {status='可用';tone='success';}
    const monthly=q.mode==='monthly'&&!q.subscription_expired&&known(q.monthly_bytes)&&Number(q.monthly_bytes)>0&&known(q.monthly_remaining_bytes);
    const used=monthly?Math.max(0,Number(q.monthly_bytes)-Number(q.monthly_remaining_bytes)):null;
    return {remaining:unlimited?'无限量':gb(q.remaining_bytes), unit:unlimited?'':known(q.remaining_bytes)?'GB':'',status,tone,
      ratio:!unlimited&&monthly?Math.round(Math.min(100,used/Number(q.monthly_bytes)*100)*100)/100:null,
      used:gb(used),monthly:gb(q.monthly_bytes),monthlyLeft:gb(q.monthly_remaining_bytes),extra:gb(q.period_extra_remaining_bytes),permanent:gb(q.permanent_remaining_bytes),
      speedDown:q.is_admin?'不限速':speed(q.download_mbps),speedUp:q.is_admin?'不限速':speed(q.upload_mbps),unlimited};
  }
  function sidebarQuota(q,context={}) {
    if(context.expired)return {remaining:'登录失效',unit:'',expiry:'重新登录后查看',status:'需重新登录',tone:'warning'};
    if(context.admin)return {remaining:'无限量',unit:'',expiry:'无个人到期限制',status:'管理员',tone:'neutral'};
    if(context.enabled===false||q?.vpn_enabled===false)return {remaining:'暂未启用',unit:'',expiry:'请联系管理员',status:'未开通或已停用',tone:'warning'};
    if(!q)return {remaining:context.error?'暂不可用':'读取中…',unit:'',expiry:context.error?'进入详情后可重试':'正在获取套餐信息',status:context.error?'读取失败':'我的套餐',tone:'neutral'};
    const s=quotaSummary(q);
    const expiry=q.mode==='permanent'?'永久有效':q.subscription_expired?known(q.expires_at)?`${date(q.expires_at)} 已到期`:'月套餐已到期':known(q.expires_at)?`${date(q.expires_at)} 到期`:'到期时间未知';
    const status=q.subscription_expired?Number(q.permanent_remaining_bytes)>0?'永久额度仍可用':'套餐已到期':null;
    return {remaining:s.remaining,unit:s.unit,expiry,status:status||s.status,tone:s.tone};
  }
  function deviceStatus(device,meter) {
    if(!device.enabled) return {label:'已停用',tone:'neutral'};
    if(!meter?.healthy||!known(device.online)) return {label:'状态未知',tone:'warning'};
    return Number(device.online)>0?{label:'在线',tone:'success'}:{label:'当前离线',tone:'neutral'};
  }
  const api={resolveRoute,gb,date,speed,quotaSummary,sidebarQuota,deviceStatus,known};
  if(typeof module==='object'&&module.exports) module.exports=api;
  if(root) root.VPNViewModel=api;
})(typeof window!=='undefined'?window:null);
