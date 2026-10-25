'use strict';
(() => {
  let period='day',data=null,busy=false,externalMode=false;
  const $=id=>document.getElementById(id);
  const number=(v,d=1)=>Number(v).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d});
  function bytes(v){
    if(v===null||v===undefined||!Number.isFinite(v))return '—';
    const units=['B','KiB','MiB','GiB','TiB'];let n=Math.max(0,v),i=0;
    while(n>=1024&&i<units.length-1){n/=1024;i++;}
    return (i?number(n,n>=100?1:2):String(Math.round(n)))+' '+units[i];
  }
  function date(ts,withSeconds=false){
    return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',...(withSeconds?{second:'2-digit'}:{}),hourCycle:'h23'}).format(new Date(ts*1000));
  }
  function set(id,text){$(id).textContent=text;}
  function svgEl(name,attrs={},text){
    const el=document.createElementNS('http://www.w3.org/2000/svg',name);
    Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v)));
    if(text!==undefined)el.textContent=text;return el;
  }
  function describe(point){
    const end=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(point.end*1000));
    return `${point.full_label} — ${period==='day'?end:date(point.end)}：下载 ${bytes(point.download_bytes)} · 上传 ${bytes(point.upload_bytes)} · 合计 ${bytes(point.total_bytes)}${point.state==='partial'?'（时段内有采集中断）':''}`;
  }
  function chart(points){
    const svg=$('usage-chart');svg.replaceChildren();
    const viewport=Math.max(300,Math.round(svg.getBoundingClientRect().width||720));
    svg.setAttribute('viewBox',`0 0 ${viewport} 250`);
    const left=59,top=16,width=viewport-left-15,height=185;
    const recorded=points.filter(p=>p.total_bytes!==null);
    const max=Math.max(1024,...recorded.map(p=>p.total_bytes));
    const y=v=>top+height-height*v/max;
    for(let i=0;i<=4;i++){
      const value=max*i/4,yy=y(value);
      svg.append(svgEl('line',{x1:left,y1:yy,x2:left+width,y2:yy,stroke:'#eef0f6','stroke-dasharray':i?'3 4':'0'}));
      svg.append(svgEl('text',{x:left-10,y:yy+3,'text-anchor':'end',fill:'#a7aaba','font-size':10},bytes(value)));
    }
    const stride=width/points.length,barWidth=Math.max(.5,stride*.52);
    points.forEach((p,i)=>{
      const x=left+i*stride+stride/2;
      if(p.total_bytes!==null){
        const g=svgEl('g',{'data-total-bytes':p.total_bytes,'data-label':p.full_label,tabindex:0,role:'button','aria-label':describe(p)});
        const downHeight=height*p.download_bytes/max,upHeight=height*p.upload_bytes/max;
        g.append(svgEl('rect',{x:x-barWidth/2,y:top,width:barWidth,height,fill:'transparent'}));
        if(downHeight)g.append(svgEl('rect',{x:x-barWidth/2,y:top+height-downHeight,width:barWidth,height:downHeight,fill:'#776ae7',rx:2}));
        if(upHeight)g.append(svgEl('rect',{x:x-barWidth/2,y:top+height-downHeight-upHeight,width:barWidth,height:upHeight,fill:'#4dc6ae',rx:2}));
        const show=()=>set('chart-detail',describe(p));
        const activate=()=>{show();if(window.vpnUsageUI?.drill)window.vpnUsageUI.drill(p,period);};
        g.addEventListener('mouseenter',show);g.addEventListener('focus',show);g.addEventListener('click',activate);
        g.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();activate();}});
        svg.append(g);
      }
      const every=Math.max(1,Math.ceil(points.length/Math.max(3,Math.floor(width/50))));
      if(i%every===0||i===points.length-1)svg.append(svgEl('text',{x,y:top+height+24,'text-anchor':'middle',fill:'#a4a7b6','font-size':10},p.label));
    });
    svg.setAttribute('aria-label',`${period==='day'?'今日每小时':period==='custom'?'自选时段':'每日'}用量图，${recorded.length} 个有记录时段，其他时段未填入数据`);
    const empty=$('chart-empty');
    empty.hidden=recorded.some(p=>p.total_bytes>0);
    empty.textContent=recorded.length?'已经开始采集，等待产生流量。':'此范围暂无已采集数据。';
    set('chart-detail',recorded.length?describe(recorded[recorded.length-1]):'此前未记录的用量无法追溯。');
  }
  function table(points){
    const rows=$('usage-rows');rows.replaceChildren();
    const available=points.filter(p=>p.total_bytes!==null).slice().reverse();
    if(!available.length){const tr=document.createElement('tr');tr.className='empty-row';const td=document.createElement('td');td.colSpan=4;td.textContent='此范围暂无记录。';tr.append(td);rows.append(tr);return;}
    available.forEach(p=>{
      const tr=document.createElement('tr');
      [p.full_label+(p.state==='partial'?' · 不完整':''),bytes(p.download_bytes),bytes(p.upload_bytes),bytes(p.total_bytes)].forEach(value=>{const td=document.createElement('td');td.textContent=value;tr.append(td);});rows.append(tr);
    });
  }
  function renderOverview(d){
    if(!d.initialized)throw new Error('collector_initializing');
    set('lifetime-total',bytes(d.lifetime.total_bytes));
    set('started-at','自 '+date(d.started_at)+' 开始记录');
    set('today-total',(d.today.incomplete?'≥ ':'')+bytes(d.today.total_bytes));
    set('today-directions','↓ '+bytes(d.today.download_bytes)+'　↑ '+bytes(d.today.upload_bytes));
    set('month-total',(d.month.incomplete?'≥ ':'')+bytes(d.month.total_bytes));
    set('month-caption',d.month.incomplete?'存在采集中断，显示已知用量':'本月已采集部分 · 非云套餐账单');
    const r=d.last_interval;
    set('current-rate',r?number(r.download_bps/1e6,2)+' Mbps':'—');
    set('upload-rate',r?'↑ '+number(r.upload_bps/1e6,2)+' Mbps · '+number(r.seconds,r.seconds<10?1:0)+' 秒均值 · 非测速上限':'等待下一个有效采样区间');
    set('footer-start','采集始于 '+date(d.started_at));
    set('last-update','更新于 '+date(d.last_sample_at,true));
    for(const proto of d.protocols)set(proto.name==='HY2'?'hy2-bytes':'vless-bytes','累计 ↓ '+bytes(proto.download_bytes)+' / ↑ '+bytes(proto.upload_bytes));
    const healthy=d.collector.healthy;
    $('collector-badge').className='collector-badge '+(healthy?'healthy':'stale');
    set('collector-badge',healthy?'采集正常 · 15 秒':'采集延迟');
    $('error-banner').hidden=healthy;
    if(!healthy)set('error-banner','采集暂时延迟，当前展示最后成功记录；请关注更新时间。');
  }
  function render(d){
    renderOverview(d);
    set('period-total',(d.period_total.incomplete?'≥ ':'')+bytes(d.period_total.total_bytes));
    set('coverage-caption','统计起点：'+date(d.started_at)+'。今日按小时、近 7 / 30 天按自然日汇总，仅显示已记录时段。');
    const gaps=d.coverage.period_gaps;
    $('gap-note').hidden=!gaps.length;
    if(gaps.length)set('gap-note',`本范围有 ${gaps.length} 段采集中断。`+(d.series_unallocated_bytes?`另有 ${bytes(d.series_unallocated_bytes)} 已知用量无法精确归入图中时段，已计入范围合计。`:'部分用量或时段无法确定。'));
    chart(d.series);table(d.series);$('export-csv').disabled=false;
  }
  function showHistory(d){
    period='custom';externalMode=true;data=d;
    set('period-total',(d.period_total?.incomplete?'≥ ':'')+bytes(d.period_total?.total_bytes));
    set('coverage-caption','自选范围 · UTC+8。未知历史、未来及中断时段保留为空值；图中未分配用量计入范围合计。');
    const unallocated=d.series_unallocated_bytes||0;
    $('gap-note').hidden=!unallocated&&!d.period_total?.has_gaps;
    if(!$('gap-note').hidden)set('gap-note',unallocated?`有 ${bytes(unallocated)} 已知用量无法精确归入图中时段，已计入范围合计。`:'此范围含采集中断，时段用量可能不完整。');
    chart(d.series);table(d.series);$('export-csv').disabled=false;
  }
  async function load(requestedPeriod=period){
    if(requestedPeriod==='custom'&&externalMode&&window.vpnUsageUI?.refresh){
      if(busy)return;busy=true;$('refresh-usage').disabled=true;
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
      let overviewUpdated=false;
      try{
        const response=await fetch('api/usage?period=day',{credentials:'same-origin',cache:'no-store',signal:controller.signal});
        if(!response.ok)throw new Error('overview_unavailable');
        renderOverview(await response.json());overviewUpdated=true;
        clearTimeout(timer);await window.vpnUsageUI.refresh();
      }
      catch(error){
        if(!overviewUpdated){$('collector-badge').className='collector-badge stale';set('collector-badge','统计暂不可用');}
        $('error-banner').hidden=false;set('error-banner',overviewUpdated?'获取最新自选范围失败，仍显示最后一次成功记录。':'概览更新失败，当前速率和用量为最后成功记录。');
      }
      finally{clearTimeout(timer);busy=false;$('refresh-usage').disabled=false;}
      return;
    }
    if(busy)return;busy=true;$('refresh-usage').disabled=true;
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
    try{
      const response=await fetch('api/usage?period='+requestedPeriod,{credentials:'same-origin',cache:'no-store',signal:controller.signal});
      if(!response.ok)throw new Error('api_unavailable');
      const next=await response.json();
      if(!next.initialized)throw new Error('collector_initializing');
      period=next.period;externalMode=false;window.vpnUsageUI?.resetHistory?.();render(next);data=next;
      document.querySelectorAll('[data-period]').forEach(b=>{const active=b.dataset.period===period;b.classList.toggle('active',active);b.setAttribute('aria-pressed',active?'true':'false');});
    }catch(error){
      $('collector-badge').className='collector-badge stale';set('collector-badge','统计暂不可用');
      $('error-banner').hidden=false;
      set('error-banner',data?'获取最新数据失败，正在展示最后成功记录。可稍后点击刷新。':'暂时无法读取流量记录，请稍后刷新。');
      if(!data){$('chart-empty').hidden=false;set('chart-empty','暂时无法获取统计。');set('usage-rows','');const tr=document.createElement('tr');tr.className='empty-row';const td=document.createElement('td');td.colSpan=4;td.textContent='尚未获取到真实记录。';tr.append(td);$('usage-rows').append(tr);}
    }finally{clearTimeout(timer);busy=false;$('refresh-usage').disabled=false;}
  }
  document.querySelectorAll('[data-period]').forEach(button=>button.addEventListener('click',()=>{
    if(busy)return;load(button.dataset.period);
  }));
  $('refresh-usage').addEventListener('click',()=>load());
  window.vpnUsageUI={showHistory,
    beginHistory:()=>{if(busy)return false;busy=true;$('refresh-usage').disabled=true;return true;},
    endHistory:()=>{busy=false;$('refresh-usage').disabled=false;},
    isBusy:()=>busy};
  $('export-csv').addEventListener('click',()=>{
    if(!data)return;
    const rows=[['时段开始 UTC+8','下载字节','上传字节','合计字节','记录状态'],...data.series.map(p=>[p.full_label,p.download_bytes??'',p.upload_bytes??'',p.total_bytes??'',p.state])];
    if(data.series_unallocated_bytes)rows.push(['中断区间内未分配到图表的已知用量','','',data.series_unallocated_bytes,'sampling_interruption']);
    const csv='\uFEFF'+rows.map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
    const fileDate=new Date(Date.now()+8*3600*1000).toISOString().slice(0,10);
    const a=document.createElement('a');a.href=url;a.download='vpn-usage-'+data.period+'-'+fileDate+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  document.querySelectorAll('.nav a').forEach(a=>a.addEventListener('click',()=>{document.querySelectorAll('.nav a').forEach(n=>n.classList.toggle('active',n===a));}));
  let chartWidth=0;
  new ResizeObserver(()=>{const width=Math.round($('usage-chart').getBoundingClientRect().width);if(width!==chartWidth&&data){chartWidth=width;chart(data.series);}}).observe($('usage-chart').parentElement);
  setInterval(()=>{if(!document.hidden)load();},15000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
  load();
})();
