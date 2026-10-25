'use strict';
(() => {
  const M=window.VPNViewModel, $=id=>document.getElementById(id);
  if(!M || !$('app-sidebar')) return;
  let boot;
  try {boot=JSON.parse($('vpn-bootstrap').textContent);} catch (_) {return;}
  const state={user:boot.user,admin:boot.user?.role==='admin',enabled:Boolean(boot.enabled),target:boot.user,
    users:[],usersLoaded:false,devices:[],devicesLoaded:false,meter:null,quota:null,quotaTarget:null,audit:[],expired:false,quotaError:'',deviceError:'',personalQuota:null,personalQuotaError:''};
  let route=null, targetTab='quota', navigation=0, lastHash='', wantedDevice=null, selecting=0;
  const sheet=$('device-sheet');
  let sheetOrigin=null, sheetOriginKey=null, sheetFocus=null, sheetDevice=null, removedSheet=false;
  const name=user=>user?.name||user?.username||'未知用户';
  const platform={windows:'Windows',macos:'macOS',ios:'iPhone / iOS',android:'Android',linux:'Linux'};
  const client={clash:'Clash',shadowrocket:'Shadowrocket',uri:'节点 URI'};
  const text=(id,value)=>{const n=$(id);if(n)n.textContent=value;};
  function make(tag,cls,content){const n=document.createElement(tag);if(cls)n.className=cls;if(content!==undefined)n.textContent=content;return n;}
  function hasDialog(){return Boolean(document.querySelector('dialog[open]:not(#device-sheet)'));}
  function busy(){return hasDialog()||window.VPNPortal?.isBusy()||window.VPNQuotaUI?.isBusy();}
  function closeQuick(){const panel=$('quick-panel');if(typeof panel?.hidePopover==='function'&&panel.matches(':popover-open'))panel.hidePopover();}
  function canPeek(){return ['overview','devices','devicedetail'].includes(route?.key)||(route?.key==='userdetail'&&targetTab==='devices');}
  function hideSheet(){if(sheet?.open)sheet.close();document.body.classList.remove('device-sheet-open');}
  function showSheet(id){
    if(!sheet?.showModal||state.expired||!canPeek())return;
    sheetDevice=id;
    if(!sheet.open){
      sheetFocus=document.activeElement;
      if(!route?.deviceId){sheetOrigin=location.hash;sheetOriginKey=route.key;}
      move('device-detail','device-sheet-content');
      text('sheet-target',state.admin?`管理对象：${name(state.target)}${state.target?.username?' · @'+state.target.username:''}`:'此设备的独立订阅与配置，请妥善保管。');
      closeQuick();sheet.showModal();document.body.classList.add('device-sheet-open');
    }
  }
  function dismissSheet(){
    if(busy())return;
    const id=sheetDevice,focus=sheetFocus;
    hideSheet();window.VPNPortal?.cancelDetail();wantedDevice=null;
    if(route?.deviceId){
      const fallback=route.adminOnly?`#/admin/user/${route.targetId}`:'#/devices';
      history.replaceState(null,'',sheetOrigin||fallback);navigate();
    }
    sheetOrigin=null;sheetOriginKey=null;sheetDevice=null;
    requestAnimationFrame(()=>{
      const next=focus?.isConnected?focus:document.querySelector(`.device-card[data-device-id="${id}"] .device-config`);
      (next||$('page-title'))?.focus({preventScroll:true});
    });
  }
  if(sheet?.addEventListener){
    move('device-detail','device-sheet-content');
    sheet.addEventListener('cancel',e=>{e.preventDefault();dismissSheet();});
    sheet.addEventListener('click',e=>{if(e.target===sheet){const r=sheet.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dismissSheet();}});
  }
  const quick=$('quick-panel'),launcher=$('quick-launcher');
  // Native popover supplies light dismiss, Escape and focus restoration. Browsers
  // without it retain all ordinary navigation; no inert custom overlay fallback.
  if(typeof quick?.showPopover==='function'){
    launcher.hidden=false;
    quick.addEventListener('beforetoggle',e=>{
      const open=e.newState==='open';launcher.setAttribute('aria-expanded',String(open));
      launcher.setAttribute('aria-label',open?'收起快捷入口':'打开快捷入口');
    });
    $('quick-theme').addEventListener('click',()=>{$('theme-toggle').click();closeQuick();launcher.focus();});
  }
  function announce(message){const box=$('global-message');box.replaceChildren(make('span','',message));box.className='notice';box.hidden=false;}
  const narrow=window.matchMedia('(max-width: 960px)');
  function menu(open){
    open=Boolean(open&&narrow.matches);
    if(open)closeQuick();
    document.body.classList.toggle('menu-open',open);$('menu-toggle').setAttribute('aria-expanded',String(open));$('menu-toggle').setAttribute('aria-label',open?'关闭导航':'打开导航');$('nav-backdrop').hidden=!open;
    $('app-sidebar').inert=narrow.matches&&!open;
    $('main-content').inert=open;
    document.querySelector('.app-account-tools').inert=open;
    if(open)$('app-sidebar').querySelector('a').focus();
  }
  function setTheme(theme){
    document.documentElement.dataset.theme=theme;
    $('theme-toggle').setAttribute('aria-label',theme==='dark'?'切换到浅色主题':'切换到深色主题');
    try{localStorage.setItem('yeshi-vpn-theme',theme);}catch(_){}
  }
  try{setTheme(localStorage.getItem('yeshi-vpn-theme')==='dark'?'dark':'light');}catch(_){setTheme('light');}
  $('theme-toggle').addEventListener('click',()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'));
  $('menu-toggle').addEventListener('click',()=>menu(!document.body.classList.contains('menu-open')));
  $('nav-backdrop').addEventListener('click',()=>{menu(false);$('menu-toggle').focus();});
  narrow.addEventListener('change',()=>menu(false));
  document.querySelector('.app-skip').addEventListener('click',e=>{e.preventDefault();$('page-title').focus();});
  document.addEventListener('keydown',e=>{
    if(!document.body.classList.contains('menu-open'))return;
    if(e.key==='Escape'){menu(false);$('menu-toggle').focus();}
    if(e.key==='Tab'){
      const links=Array.from($('app-sidebar').querySelectorAll('a,button:not(:disabled)')).filter(a=>a.getClientRects().length);
      if(e.shiftKey&&document.activeElement===links[0]){e.preventDefault();links.at(-1).focus();}
      else if(!e.shiftKey&&document.activeElement===links.at(-1)){e.preventDefault();links[0].focus();}
    }
  });
  if(boot.preview) $('preview-banner').hidden=false;

  function identity(){document.querySelectorAll('[data-admin]').forEach(n=>{n.hidden=!state.admin||state.expired;});renderPersonalPlan();}
  function renderPersonalPlan(){
    const s=M.sidebarQuota(state.personalQuota,{admin:state.admin,enabled:state.enabled,expired:state.expired,error:state.personalQuotaError});
    text('sidebar-remaining',s.remaining);text('sidebar-unit',s.unit);text('sidebar-expiry',s.expiry);text('sidebar-plan-status',s.status);
    $('sidebar-plan-status').dataset.tone=s.tone;
    const link=$('sidebar-plan');
    if(state.expired){link.removeAttribute('href');link.setAttribute('aria-disabled','true');}
    else{link.setAttribute('href','#/usage');link.removeAttribute('aria-disabled');}
  }
  $('sidebar-plan').addEventListener('click',e=>{if(state.expired||busy()){e.preventDefault();if(!state.expired)announce('请先保存或关闭当前编辑，再查看个人套餐。');}});
  function move(id,destination){const child=$(id),parent=$(destination);if(child&&parent&&child.parentElement!==parent)parent.append(child);}
  function sectionState(){
    const quota=$('quota-root');if(!quota)return;
    quota.classList.remove('app-quota-policy-view','app-quota-usage-view');
    if(route?.key==='userdetail'){
      $('user-quota-mount').hidden=!['quota','usage'].includes(targetTab);
      $('user-devices-mount').hidden=targetTab!=='devices';$('user-audit-mount').hidden=targetTab!=='audit';
      if(['quota','usage'].includes(targetTab)){move('quota-root','user-quota-mount');quota.classList.add(targetTab==='quota'?'app-quota-policy-view':'app-quota-usage-view');}
      if(targetTab==='devices')move('workspace','user-devices-mount');
      document.querySelectorAll('[data-target-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.targetTab===targetTab)));
    } else if(route?.key==='usage')move('quota-root','personal-quota-mount');
    if(route?.key==='devices')move('workspace','devices-mount');
    if(route?.key==='devicedetail')move('workspace',sheet?'devices-mount':'device-detail-mount');
    const list=$('device-list')?.closest('.devices-panel');if(list)list.hidden=!sheet&&(route?.key==='devicedetail'||Boolean(route?.deviceId));
    document.body.dataset.targetTab=targetTab;
  }
  async function ensureTarget(id){
    if(!window.VPNPortal||!window.VPNQuotaUI)return false;
    if(!window.VPNPortal.selectUser(id))return false;
    return await window.VPNQuotaUI.selectUser(id);
  }
  async function navigate(){
    if(state.expired)return;
    const next=M.resolveRoute(location.hash,state.admin);
    const nextHash=location.hash||'#/overview';
    if(route&&lastHash!==nextHash&&busy()){
      history.replaceState(null,'',lastHash);announce('请先保存或关闭当前编辑，再切换页面或管理对象。');return;
    }
    if(sheet&&next.deviceId&&!route?.deviceId&&canPeek()){
      sheetOrigin=lastHash;sheetOriginKey=route.key;
    }
    if(route&&lastHash!==nextHash)window.VPNPortal?.cancelDetail(next.deviceId);
    if(!next.deviceId){hideSheet();if(!sheet?.open){sheetOrigin=null;sheetOriginKey=null;}}
    closeQuick();
    const version=++navigation;route=next;lastHash=nextHash;
    if(next.denied)announce('当前账号没有管理员权限，已返回个人总览。');
    const visualKey=sheet&&next.key==='devicedetail'?(sheetOriginKey==='overview'?'overview':'devices'):next.key;
    const visual=visualKey!==next.key?M.resolveRoute('#/'+visualKey,state.admin):next;
    document.querySelectorAll('[data-page]').forEach(n=>{n.hidden=n.dataset.page!==visualKey;});
    text('page-title',visual.title);text('page-description',visual.description);
    text('app-breadcrumb',`${next.adminOnly?'管理中心':'个人中心'} / ${visual.title}`);
    document.title=`${next.title} · wuyu`;
    document.querySelectorAll('[data-route]').forEach(a=>{
      const key=a.dataset.route,active=key===(visualKey==='userdetail'?'admin/users':{'users':'admin/users','server':'admin/server','audit':'admin/audit'}[visualKey]||visualKey);
      a.classList.toggle('is-active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');
    });
    $('target-context-wrapper').hidden=!state.admin||!['userdetail','audit'].includes(next.key);
    $('page-add-device').hidden=!['overview','devices'].includes(visualKey);
    $('page-import-guide').hidden=next.adminOnly||next.key==='help';
    menu(false);
    const desired=next.targetId||(!next.adminOnly?String(state.user.id):next.key==='audit'?String(state.target?.id||state.user.id):null);
    if(desired){
      selecting++;
      try{
        const ok=await ensureTarget(desired);
        if(version!==navigation)return;
        if(!ok&&state.usersLoaded&&next.targetId&&!state.users.some(u=>String(u.id)===desired)){
          $('user-quota-mount').hidden=true;$('user-devices-mount').hidden=true;$('user-audit-mount').hidden=true;
          announce('没有找到该用户。请返回用户管理，重新选择管理对象。');return;
        }
      }finally{selecting--;}
    }
    if(next.deviceId){targetTab='devices';wantedDevice=next.deviceId;}
    else wantedDevice=null;
    sectionState();renderOverview();renderAudit();
    requestAnimationFrame(()=>document.dispatchEvent(new Event('vpn:layout')));
    if(wantedDevice&&state.devices.some(d=>d.id===wantedDevice))window.VPNPortal?.openDevice(wantedDevice);
    if(!sheet?.open)$('page-title').focus({preventScroll:true});
  }
  document.addEventListener('click',e=>{
    const a=e.target.closest('a[data-route]');if(!a)return;
    if(busy()&&a.hash!==location.hash){e.preventDefault();announce('请先保存或关闭当前编辑，再切换页面。');return;}
    closeQuick();
  },true);
  window.addEventListener('hashchange',()=>{const overlay=Boolean(route?.deviceId||sheet?.open||M.resolveRoute(location.hash,state.admin).deviceId);navigate();if(!overlay)window.scrollTo({top:0,behavior:'instant'});});
  $('target-user').addEventListener('change',e=>{
    if(busy()){e.stopImmediatePropagation();e.target.value=String(state.target?.id||state.user.id);announce('请先保存或关闭当前编辑，再切换管理对象。');return;}
    const id=e.target.value;if(route?.key==='userdetail')location.hash=`#/admin/user/${id}`;
    else window.VPNQuotaUI?.selectUser(id);
  },true);
  document.querySelectorAll('[data-target-tab]').forEach(b=>b.addEventListener('click',()=>{
    if(busy()){announce('请先保存或关闭当前编辑，再切换页签。');return;}
    if(targetTab!==b.dataset.targetTab)window.VPNPortal?.cancelDetail();
    targetTab=b.dataset.targetTab;if(route?.deviceId){location.hash=`#/admin/user/${route.targetId}`;wantedDevice=null;}
    sectionState();renderAudit();
  }));
  $('page-add-device').addEventListener('click',()=>{if(!busy())$('add-device').click();});
  $('page-refresh').addEventListener('click',async()=>{
    if(busy())return;
    const b=$('page-refresh');b.disabled=true;b.textContent='刷新中…';
    try{
      if(route?.key==='server'||route?.key==='admin')$('system-refresh')?.click();
      await Promise.all([window.VPNPortal?.refresh(),window.VPNQuotaUI?.refresh()]);
    }finally{b.disabled=false;b.textContent='刷新';}
  });
  $('close-detail').addEventListener('click',()=>{if(sheet)dismissSheet();else location.hash=route?.adminOnly?`#/admin/user/${state.target.id}`:'#/devices';});

  function renderOverview(){
    if(state.expired)return;
    const isSelf=String(state.target?.id)===String(state.user?.id);
    const q=isSelf&&String(state.quotaTarget)===String(state.user.id)?state.quota:null;
    const s=M.quotaSummary(q);
    text('overview-remaining',q?s.remaining:'正在读取');text('overview-unit',q?s.unit:'');
    const badge=$('overview-status');badge.textContent=q?s.status:'正在读取';badge.className=`app-status ${s.tone}`;badge.dataset.tone=s.tone;
    text('overview-plan',q?.vpn_enabled===false?'VPN 使用权限未启用':q?.is_admin?'管理员账户':q?.mode==='monthly'?`月套餐 · ${s.monthly} GB`:q?.mode==='permanent'?'永久额度':q?.unlimited?'无限量账户':'我的套餐');
    text('overview-buckets',q?s.unlimited?'不设个人流量上限，继续记录实际使用情况。':`本期套餐 ${s.monthlyLeft} GB · 当期追加 ${s.extra} GB · 永久 ${s.permanent} GB`:'正在读取套餐、追加与永久余额。');
    text('overview-used',s.ratio===null?'按服务端记录实际用量':`本期已使用 ${s.used} GB`);
    text('overview-monthly',s.ratio===null?'':`每月 ${s.monthly} GB`);
    const progress=$('overview-progress');progress.hidden=s.ratio===null;
    if(s.ratio!==null){progress.firstElementChild.style.width=`${s.ratio}%`;progress.setAttribute('role','progressbar');progress.setAttribute('aria-label','本期套餐已使用比例');progress.setAttribute('aria-valuemin','0');progress.setAttribute('aria-valuemax','100');progress.setAttribute('aria-valuenow',String(s.ratio));}
    text('overview-reset',q?.is_admin||q?.mode==='permanent'?'不适用':q?.subscription_expired?'月套餐已到期':q?M.date(q.next_reset_at||q.period_end):'正在读取');
    text('overview-expiry',q?.vpn_enabled===false?'VPN 使用权限未启用':q?.is_admin?'无个人到期限制':q?.mode==='permanent'?'永久有效':q?M.date(q.expires_at):'正在读取');
    text('overview-down',q?s.speedDown:'正在读取');text('overview-up',q?s.speedUp:'正在读取');
    $('page-add-device').disabled=!state.enabled||Boolean(window.VPNPortal?.isBusy());
    const list=$('overview-device-list');list.replaceChildren();
    const data=isSelf?state.devices:[];
    text('overview-device-count',isSelf&&state.devicesLoaded?`${data.length} 台`:'');
    if(!state.enabled)list.append(make('p','app-empty','VPN 未开通或已停用，请联系管理员启用后再添加设备。'));
    else if(!state.devicesLoaded||!isSelf)list.append(make('p','app-empty',state.deviceError||'正在读取设备…'));
    else if(!data.length)list.append(make('p','app-empty','还没有设备。点击“添加设备”开始使用。'));
    data.slice(0,4).forEach(d=>{
      const row=make('article','app-device-row'),description=make('div','app-device-description'),status=M.deviceStatus(d,state.meter);
      const symbol=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');
      symbol.setAttribute('viewBox','0 0 24 24');symbol.setAttribute('fill','none');symbol.setAttribute('stroke','currentColor');symbol.setAttribute('stroke-width','1.6');symbol.setAttribute('aria-hidden','true');
      path.setAttribute('d',d.platform==='ios'||d.platform==='android'?'M7 2h10v20H7zM11 18h2':'M3 4h18v13H3zM8 21h8M12 17v4');symbol.append(path);
      description.append(make('strong','app-device-name',d.remark||'未命名设备'),make('small','app-device-meta',`${platform[d.platform]||d.platform} · ${client[d.client]||d.client}`));
      const actions=make('div','app-device-status'),tag=make('span',`app-device-state ${status.tone}`,status.label);tag.dataset.tone=status.tone;
      const a=make('a','app-device-config','订阅与二维码');a.href=`#/devices/${d.id}`;actions.append(tag,a);row.append(symbol,description,actions);list.append(row);
    });
    text('overview-meter',state.meter?.last_success?`最近采集 ${M.date(state.meter.last_success,true)} · ${state.meter.healthy?'状态按实际配置统计':'数据已过期，当前在线状态未知'}`:'尚无成功采集记录，不能确定当前在线状态。');
    const error=$('overview-error'),message=state.quotaError||state.deviceError;error.hidden=!message||!isSelf;error.textContent=message?`${message} 可点击上方“刷新”重试。`:'';
  }
  function renderAudit(){
    for(const id of ['audit-log','user-audit-log']){
      const host=$(id);host.replaceChildren();
      if(!state.audit.length){host.append(make('p','app-empty',state.quotaError||'当前用户暂无额度变更记录。'));continue;}
      const list=make('ol','quota-audit');
      state.audit.forEach(item=>{
        const row=make('li','quota-audit-row'),head=make('div','quota-audit-top');head.append(make('strong','',item.event||item.action||'额度变更'),make('time','',M.date(item.timestamp||item.created_at,true)));
        row.append(head,make('small','',`操作者：${name(item.actor)||'系统'}`));
        if(item.changes&&typeof item.changes==='object')Object.entries(item.changes).forEach(([k,v])=>row.append(make('p','quota-audit-changes',`${k}：${v}`)));
        list.append(row);
      });host.append(list);
    }
  }
  function filterDevices(){
    const value=$('device-search').value.trim().toLocaleLowerCase();let matched=0;
    document.querySelectorAll('#device-list .device-card').forEach(card=>{card.hidden=value&&!String(card.dataset.search||card.textContent).toLocaleLowerCase().includes(value);if(!card.hidden)matched++;});
    $('device-search-empty').hidden=!value||matched>0||!state.devices.length;
  }
  function filterUsers(){
    const value=$('user-search').value.trim().toLocaleLowerCase(),filter=$('user-filter').value;let matched=0;
    document.querySelectorAll('#admin-users .admin-user').forEach(card=>{
      const u=state.users.find(u=>String(u.id)===String(card.dataset.userId));
      const visible=(!value||String(card.dataset.search||card.textContent).toLocaleLowerCase().includes(value))&&(filter==='all'||filter==='enabled'&&u?.enabled||filter==='disabled'&&!u?.enabled);
      card.hidden=!visible;if(visible)matched++;
    });$('user-search-empty').hidden=matched>0||!state.usersLoaded;
  }
  $('device-search').addEventListener('input',filterDevices);$('device-search-reset').addEventListener('click',()=>{$('device-search').value='';filterDevices();});
  $('user-search').addEventListener('input',filterUsers);$('user-filter').addEventListener('change',filterUsers);
  function renderAdmin(){
    if(!state.admin||state.expired)return;
    text('admin-user-count',state.usersLoaded?String(state.users.length):'正在读取');text('admin-enabled-count',state.usersLoaded?String(state.users.filter(u=>u.enabled).length):'正在读取');
    text('admin-server-download',$('system-life-down')?.textContent||'正在读取');text('admin-server-period',$('system-period-down')?.textContent||'正在读取');text('admin-server-period-label',$('system-period-down-label')?.textContent||'服务器计量');
  }
  document.addEventListener('vpn:identity',e=>{if(state.expired)return;if(String(state.user?.id)!==String(e.detail.user?.id)||state.admin!==e.detail.admin){state.personalQuota=null;state.personalQuotaError='';}Object.assign(state,{user:e.detail.user,admin:e.detail.admin,enabled:e.detail.enabled});identity();setTimeout(navigate,0);});
  document.addEventListener('vpn:target',e=>{
    if(state.expired)return;
    const changed=String(state.target?.id)!==String(e.detail.user?.id);state.target=e.detail.user;
    if(changed){hideSheet();sheetOrigin=null;sheetOriginKey=null;state.devices=[];state.devicesLoaded=false;state.quota=null;state.quotaTarget=null;state.audit=[];state.quotaError='';state.deviceError='';renderAudit();}
    renderOverview();
  });
  document.addEventListener('vpn:users',e=>{if(state.expired)return;state.users=e.detail.users;state.usersLoaded=true;filterUsers();renderAdmin();if(route?.targetId&&!selecting&&(String(state.target?.id)!==route.targetId||String(state.quotaTarget)!==route.targetId))setTimeout(navigate,0);});
  document.addEventListener('vpn:devices',e=>{
    if(state.expired||String(e.detail.target?.id)!==String(state.target?.id))return;
    state.devices=e.detail.devices;state.meter=e.detail.meter;state.devicesLoaded=true;state.deviceError='';
    if(String(e.detail.target.id)===String(state.user.id)){state.enabled=e.detail.enabled;renderPersonalPlan();}
    renderOverview();filterDevices();
    if(wantedDevice&&state.devices.some(d=>d.id===wantedDevice))window.VPNPortal?.openDevice(wantedDevice);
  });
  document.addEventListener('vpn:quota',e=>{
    if(state.expired)return;
    if(String(e.detail.targetId)===String(state.user.id)){state.personalQuota=e.detail.quota;state.personalQuotaError='';renderPersonalPlan();}
    if(String(e.detail.targetId)!==String(state.target?.id)){if(route?.targetId&&!selecting)setTimeout(navigate,0);return;}
    state.quota=e.detail.quota;state.quotaTarget=e.detail.targetId;state.audit=e.detail.audit||[];state.quotaError='';renderOverview();renderAudit();
    if(route?.targetId&&String(route.targetId)!==String(e.detail.targetId)&&!selecting)setTimeout(navigate,0);
  });
  document.addEventListener('vpn:quota-error',e=>{if(state.expired)return;if(String(e.detail.targetId)===String(state.user.id)){state.personalQuota=null;state.personalQuotaError=e.detail.message;renderPersonalPlan();}if(String(e.detail.targetId)===String(state.target?.id)){state.quota=null;state.quotaError=e.detail.message;renderOverview();}});
  document.addEventListener('vpn:devices-error',e=>{if(String(e.detail.targetId)===String(state.target?.id)){state.devicesLoaded=false;state.deviceError=e.detail.message;renderOverview();}});
  document.addEventListener('vpn:detail',e=>{
    showSheet(e.detail.id);
    if(state.expired||route?.deviceId===e.detail.id)return;
    if(!['overview','devices','devicedetail'].includes(route?.key)&&!(route?.key==='userdetail'&&targetTab==='devices'))return;
    location.hash=route?.adminOnly?`#/admin/user/${state.target.id}/device/${e.detail.id}`:`#/devices/${e.detail.id}`;
  });
  document.addEventListener('vpn:detail-loading',e=>{if(!busy())showSheet(e.detail.id);});
  document.addEventListener('vpn:device-removed',e=>{if(String(sheetDevice)===String(e.detail.id)){hideSheet();removedSheet=true;}});
  document.addEventListener('vpn:manage-user',e=>{targetTab='quota';location.hash=`#/admin/user/${e.detail.id}`;});
  document.addEventListener('vpn:session-expired',()=>{
    state.expired=true;state.quota=null;state.personalQuota=null;state.personalQuotaError='';state.audit=[];state.devices=[];identity();
    closeQuick();hideSheet();if(launcher)launcher.hidden=true;
    document.querySelectorAll('[data-page]').forEach(n=>{n.hidden=true;});$('target-context-wrapper').hidden=true;
    $('overview-device-list').replaceChildren();['audit-log','user-audit-log'].forEach(id=>$(id).replaceChildren());
    text('page-title','登录已失效');text('page-description','重新登录后可继续管理 VPN。');$('page-add-device').disabled=true;
  });
  document.addEventListener('close',()=>{if(!state.expired)renderOverview();},true);
  document.addEventListener('vpn:mutation',()=>{if(!state.expired){renderOverview();if(removedSheet&&!busy()){removedSheet=false;dismissSheet();}}});
  new MutationObserver(renderAdmin).observe($('system-overview-mount'),{childList:true,subtree:true,characterData:true});
  new MutationObserver(()=>{filterDevices();filterUsers();}).observe($('admin-users'),{childList:true});
  if(!location.hash)history.replaceState(null,'',state.admin?'#/admin':'#/overview');
  identity();navigate();
})();
