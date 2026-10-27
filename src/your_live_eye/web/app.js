'use strict';
const $ = selector => document.querySelector(selector);
const number = value => Number(value).toLocaleString('zh-CN');
const percent = (count, total) => !total ? '—' : count>0 && count/total*100<.1 ? '<0.1%' : `${(count / total * 100).toFixed(1)}%`;
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clock = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false});
const memeClock = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
const updateClock = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
const time = ts => clock.format(new Date(ts));
const windowNames = {day:'当日',month:'近一个月',year:'近一年',decade:'近十年'};
const dayMs = 86400000, interval = 5;
let snapshot, date, dayData = null, dayStatus = 'loading', scope = 'day', selected = null, buckets = [];
let requestVersion = 0, highlightedTopic = null;
const cache = new Map(), insightCache = new Map();
let insightData = null, insightStatus = 'loading';
let historyStatus = 'loading', historyRequest = null, pendingScope = null;
let observedDates = new Set();
let overviewDate, inDrill = false;
const unknownId = () => 6;
const order = () => [0,1,2,7,3,4,5,6].filter(id=>id<snapshot.topics.length);
const labels = () => snapshot.topics.map((label,id)=>id===5?'攻击':label);
const color = id => `var(--topic-${['translation','greeting','support','meme','chat','criticism','unknown','care'][id]})`;
const blank = () => ({topic:Array(snapshot?.topics?.length || 8).fill(0),total:0});
const isoDay = value => new Date(value).toISOString().slice(0,10);
const current = () => scope === 'day' ? snapshot.calendar[date] : { ...periodRange(scope,date), series:{all:sumRows(buckets)} };
const currentSeries = () => current().series.all;
const selectedLabel = () => `${viewLabel(scope,date)}话题构成`;
const dateText = value => value.replaceAll('-', '.');
const validDate = value => /^\d{4}-\d{2}-\d{2}$/.test(value || '') && value>=snapshot.min_date && value<=snapshot.as_of && Number.isFinite(Date.parse(value)) && isoDay(Date.parse(value))===value;
function ensureDay(value) {
  // During the background history request, only the selected day's summary is needed.
  snapshot.calendar[value] ||= {observed:observedDates.has(value),series:{all:blank()},interrupts:0};
}

function sourceSearchLink(row) {
  // Danmakus interprets spaces/quotes/wildcards as search syntax. Use one literal
  // phrase (at most 120 code points), and constrain it to this room and minute.
  const phrases=String(row.text || '').split(/["'＊*?？\r\n]+/u).map(s=>s.trim().replace(/^-+/,''));
  const phrase=phrases.sort((a,b)=>[...b].length-[...a].length)[0] || '';
  const text=[...phrase].slice(0,120).join('');
  if([...text].length<2 || !Number.isFinite(row.ts))return row.source_url;
  const url=new URL('https://danmakus.com/search/content');
  url.searchParams.set('q',/\s/u.test(text)?`"${text}"`:text);
  url.searchParams.set('channelUid',String(snapshot.channel.uid));
  url.searchParams.set('start',String(Math.max(0,row.ts-60000)));
  url.searchParams.set('end',String(row.ts+60000));
  return url.href;
}

function attackScore(row) {
  const value=row.severity_score ?? row.score;
  return value!==null && value!==undefined && value!=='' && Number.isFinite(Number(value))?Number(value):null;
}

function legendItems(compact=false) {
  const shortLabels=['翻译','招呼','赞美','玩梗','闲聊','攻击','待判','关心'];
  return order().map(id=>`<button class="legend-item" data-legend-topic="${id}" aria-pressed="${highlightedTopic===String(id)}" title="高亮${escapeHTML(labels()[id])}，再点恢复全部"><i class="swatch ${id===unknownId()?'unknown':''}" style="--topic-color:${color(id)}" aria-hidden="true"></i>${compact?`<span class="legend-full-label">${escapeHTML(labels()[id])}</span><span class="legend-short-label">${shortLabels[id]}</span>`:escapeHTML(labels()[id])}</button>`).join('');
}
function applyHighlight() {
  document.querySelectorAll('.bar-segment').forEach(el=>el.classList.toggle('is-muted',highlightedTopic!==null&&el.dataset.topic!==highlightedTopic));
  document.querySelectorAll('[data-legend-topic]').forEach(el=>{
    el.setAttribute('aria-pressed',String(el.dataset.legendTopic===highlightedTopic));
    el.classList.toggle('is-muted',highlightedTopic!==null&&el.dataset.legendTopic!==highlightedTopic);
  });
}
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-legend-topic]');if(!button)return;
  highlightedTopic=highlightedTopic===button.dataset.legendTopic?null:button.dataset.legendTopic;
  applyHighlight();
});
function viewLabel(level,value) {
  return level==='year'?`${value.slice(0,4)} 年`:level==='month'?`${value.slice(0,4)} 年 ${Number(value.slice(5,7))} 月`:dateText(value);
}
function inputValue() {return scope==='year'?date.slice(0,4):scope==='month'?date.slice(0,7):date;}
function viewURL() {
  const url=new URL(location.href);
  url.searchParams.set('date',date);url.searchParams.set('window',pendingScope || scope);
  if(inDrill){url.searchParams.set('anchor',overviewDate);url.searchParams.set('drill','1');}
  else {url.searchParams.delete('anchor');url.searchParams.delete('drill');}
  for(const key of ['kind','metric'])url.searchParams.delete(key);
  url.hash='';return url;
}
function saveView({push=false}={}) {
  const url=viewURL();
  if(push && url.href!==location.href)history.pushState(null,'',url);
  else history.replaceState(null,'',url);
}
function periodRange(level,value) {
  const year=Number(value.slice(0,4)),month=Number(value.slice(5,7));
  return level==='year'?{start:`${year}-01-01`,end:`${year}-12-31`}
    :{start:`${value.slice(0,7)}-01`,end:isoDay(Date.UTC(year,month,0))};
}
function sumRows(rows) {
  const result=blank();
  for(const row of rows){row.topic.forEach((n,i)=>result.topic[i]+=n);result.total+=row.total;}
  return result;
}
function rangeHasDate(level,value) {
  const range=level==='day'?{start:value,end:value}:periodRange(level,value);
  return range.end>=snapshot.min_date && range.start<=snapshot.as_of;
}
function navigateView(level,value,{drill=true,anchor=overviewDate,push=true}={}) {
  if(!rangeHasDate(level,value))return;
  const target=value<snapshot.min_date?snapshot.min_date:value>snapshot.as_of?snapshot.as_of:value;
  scope=level;date=target;inDrill=drill;overviewDate=anchor || target;selected=null;
  pendingScope=level!=='day' && historyStatus!=='ready'?level:null;
  if(pendingScope)scope='day';
  $('#timeline').scrollLeft=0;setDateError('');saveView({push});
  if(level==='day' || pendingScope)loadDay(target,{keepWindow:true});
  else {++requestVersion;dayData=null;insightData=null;render();}
  if(pendingScope)loadHistory();
}
function drillInto(level,row) {
  if(!row || row.disabled)return;
  navigateView(level==='decade'?'year':level==='year'?'month':'day',row.key.length===4?`${row.key}-01-01`:row.key.length===7?`${row.key}-01`:row.key,
    {anchor:overviewDate});
}
function breadcrumbViews() {
  if(!inDrill)return [];
  const views=[{label:'概览',level:'day',value:overviewDate,root:true},
    {label:`${date.slice(0,4)} 年`,level:'year',value:`${date.slice(0,4)}-01-01`}];
  if(scope!=='year')views.push({label:`${Number(date.slice(5,7))} 月`,level:'month',value:`${date.slice(0,7)}-01`});
  if(scope==='day')views.push({label:`${Number(date.slice(8))} 日`,level:'day',value:date});
  return views;
}
function renderBreadcrumbs() {
  const views=breadcrumbViews(),box=$('#time-path');
  box.hidden=!views.length;
  box.innerHTML=views.map((view,index)=>`${index?'<span aria-hidden="true">›</span>':''}<button class="text-button" data-path="${index}" ${index===views.length-1?'aria-current="page" disabled':''}>${escapeHTML(view.label)}</button>`).join('');
  box.querySelectorAll('[data-path]').forEach(button=>button.addEventListener('click',()=>{
    const view=views[Number(button.dataset.path)];navigateView(view.level,view.value,{drill:!view.root});
  }));
  $('#up-level').hidden=!inDrill;
  $('#up-level').onclick=()=>{const view=views.at(-2);if(view)navigateView(view.level,view.value,{drill:!view.root});};
}
function adjacentView(step) {
  if(scope==='day') {
    const days=[...observedDates].filter(day=>step<0?day<date:day>date).sort();
    return step<0?days.at(-1):days[0];
  }
  if(scope==='year')return `${Number(date.slice(0,4))+step}-01-01`;
  const month=monthNumber(date)+step;return `${monthText(month)}-01`;
}
function moveView(step) {
  const target=adjacentView(step);if(!target)return;
  navigateView(scope,target,{drill:inDrill,anchor:inDrill?overviewDate:target});
}
function restoreView() {
  const params=new URL(location.href).searchParams;
  const requested=['year','month'].includes(params.get('window'))?params.get('window'):'day';
  const target=validDate(params.get('date'))?params.get('date'):snapshot.default_date;
  const anchor=validDate(params.get('anchor'))?params.get('anchor'):target;
  navigateView(requested,target,{drill:requested!=='day'||params.get('drill')==='1',anchor,push:false});
}
window.addEventListener('popstate',()=>{if(snapshot)restoreView();});
function countsFromVector(vector) {
  const n=snapshot.topics.length,topic=vector.slice(0,n).map((count,i)=>count+vector[n+i]);
  return {topic,total:topic.reduce((a,b)=>a+b,0)};
}
function dayBuckets() {
  if (!dayData?.minutes.length) return [];
  const minutes = new Map(dayData.minutes.map(row=>[row[0],row.slice(1)]));
  const ranges=(dayData.live_ranges || []).map(r=>({start:r.start,end:r.end})).sort((a,b)=>a.start-b.start);
  if (!ranges.length) return [];
  // A minute can straddle adjacent sessions; merge these ranges so each count appears once.
  const merged=[];
  for(const range of ranges){const last=merged.at(-1);if(last && Math.floor(range.start/60000)<=Math.floor(last.end/60000)){last.end=Math.max(last.end,range.end);}else merged.push({...range});}
  const result = [];
  for (const range of merged) for (let start=Math.floor(range.start/60000)*60000;start<=range.end;start+=interval*60000) {
    const end=Math.min(start+interval*60000,range.end+1), vector=Array(2*snapshot.topics.length+9).fill(0);
    for (let ts=start;ts<end;ts+=60000) {
      const row=minutes.get(ts);
      if (row) row.forEach((n,i)=>vector[i]+=n);
    }
    result.push({start:Math.max(start,range.start),end,label:`${time(Math.max(start,range.start))}–${time(end)}`,axis:time(start),...countsFromVector(vector),interrupted:vector.at(-1)>0});
  }
  return result;
}
function groupRange(range,level) {
  const groups=new Map();
  for(let ts=Date.parse(range.start);ts<=Date.parse(range.end);ts+=dayMs) {
    const day=isoDay(ts),key=level==='month'?day:level==='year'?day.slice(0,7):day.slice(0,4);
    if(!groups.has(key))groups.set(key,{key,start:day,end:day,axis:level==='month'?day.slice(5).replace('-','/'):level==='year'?`${Number(day.slice(5,7))}月`:key,...blank(),interrupted:false,observed:0});
    const row=groups.get(key),data=snapshot.calendar[day];row.end=day;
    if(!data)continue;
    const values=data.series.all;values.topic.forEach((n,i)=>row.topic[i]+=n);
    row.total+=values.total;row.observed+=Number(data.observed);row.interrupted ||= data.interrupts>0;
  }
  return [...groups.values()].filter(row=>row.total>0).map(row=>({...row,
    disabled:row.end<snapshot.min_date || row.start>snapshot.as_of,
    label:level==='decade'?`${row.key} 年`:level==='year'?`${row.key.replace('-',' 年 ')} 月`:dateText(row.key)}));
}
function windowBuckets(name) {
  return groupRange(snapshot.calendar[overviewDate].windows[name],name).map(row=>({...row,axis:name==='year'?row.key.slice(2).replace('-','/'):row.axis}));
}
function mainBuckets() {return scope==='day'?dayBuckets():groupRange(periodRange(scope,date),scope);}
function setPeriod(value) {
  selected=value==='all'?null:Number(value);
  if (selected!==null && !buckets[selected]) selected=null;
  document.querySelectorAll('.time-bin').forEach((el,i)=>el.setAttribute('aria-pressed',String(i===selected)));
  $('#all-day').hidden=scope!=='day'||selected===null;
  const row=selected===null?null:buckets[selected];
  $('#selected-bin-note').textContent=row?`${row.label} · ${number(row.total)} 条 · `+order().filter(i=>row.topic[i]).map(i=>`${labels()[i]} ${percent(row.topic[i],row.total)}`).join(' / '):'';
  renderInsights();
}
function fitMemeText() {
  document.querySelectorAll('.meme-sc-toggle').forEach(button=>{
    const text=document.getElementById(button.getAttribute('aria-controls'));
    button.hidden=button.getAttribute('aria-expanded')!=='true' && text.scrollHeight<=text.clientHeight+1;
  });
}
function renderInsights() {
  const reactions=$('#reaction-content'),criticals=$('#critical-content');
  const period=scope==='day' && selected!==null?buckets[selected]:null;
  const scopeText=scope!=='day'?'':period?period.label:'全天';
  document.querySelectorAll('[data-insight-period]').forEach(el=>el.textContent=scopeText);
  if(scope!=='day'){reactions.innerHTML='<p class="insight-empty">选择具体日期后查看高频互动</p>';criticals.innerHTML='<p class="insight-empty">选择具体日期后查看攻击原文</p>';return;}
  let visible=insightData;
  if(insightStatus!=='ready'){
    reactions.innerHTML=insightStatus==='loading'?'<p class="insight-empty">正在读取当天话题…</p>':'<p class="insight-empty">当天话题暂时无法读取 <button class="text-button" id="retry-insights">重试</button></p>';
    criticals.innerHTML='<p class="insight-empty">等待当天分析结果</p>';
    $('#retry-insights')?.addEventListener('click',()=>loadInsights(date,requestVersion));return;
  }
  if(!insightData){reactions.innerHTML='<p class="insight-empty">这一天暂无可分析的收录</p>';criticals.innerHTML='<p class="insight-empty">无可展示原文</p>';return;}
  if(period){
    visible=insightData.period_insights?.find(row=>row.start===period.start && row.end===period.end);
    if(!visible){
      reactions.innerHTML='<p class="insight-empty">该时段的互动片段尚未更新。</p>';
      criticals.innerHTML='<p class="insight-empty">该时段的原文尚未更新。</p>';return;
    }
  }
  reactions.innerHTML=(visible.reaction_topics || []).slice(0,period?1:2).map((story,index)=>{
    const replies=(story.audience_replies || story.reaction_examples || []).slice(0,5);
    const occurredAt=(period?story.period_reaction:story.first_reaction)?.ts;
    const occurrence=Number.isFinite(occurredAt)?new Date(occurredAt):null;
    const occurrenceLabel=occurrence?memeClock.format(occurrence):'';
    const occurrenceIndex=occurrence?buckets.findIndex(row=>row.start<=occurredAt && occurredAt<row.end):-1;
    const occurrenceHTML=occurrence?`<time datetime="${occurrence.toISOString()}">${occurrenceLabel}</time>`:'';
    const occurrenceControl=occurrenceIndex>=0?`<button class="meme-time" data-meme-period="${occurrenceIndex}" title="北京时间 · 本片段首次接话，点击定位五分钟时段" aria-label="${occurrenceLabel}，北京时间，定位到对应五分钟时段">${occurrenceHTML}</button>`:occurrence?`<span class="meme-time" title="北京时间 · 本片段首次接话">${occurrenceHTML}</span>`:'';
    const sc=story.related_sc;
    const scId=`meme-sc-${index}`;
    const context=sc?.text?`<section class="meme-sc-block" aria-label="SC 原文"><div class="meme-section-heading"><a class="meme-section-label" href="${escapeHTML(sourceSearchLink(sc))}" target="_blank" rel="noopener noreferrer" title="在 Danmakus 查看这条 SC">SC 原文 ↗</a><button class="meme-sc-toggle" aria-expanded="false" aria-controls="${scId}" hidden>展开</button></div><p id="${scId}" class="meme-sc-text" data-expanded="false">${escapeHTML(sc.text)}</p></section>`:'';
    const responses=replies.length?`<section class="meme-reply-block" aria-label="观众接话"><span class="meme-section-label">观众接话</span><ul class="meme-replies">${replies.map(row=>`<li><q>${escapeHTML(row.text)}</q></li>`).join('')}</ul></section>`:'';
    return `<article class="reaction-story"><div class="story-top"><strong>${escapeHTML(story.title)}</strong>${occurrenceControl}</div>${context}${responses}</article>`;
  }).join('') || `<p class="insight-empty">${period?'该时段':'当天'}暂无精选片段。</p>`;
  reactions.querySelectorAll('[data-meme-period]').forEach(button=>button.addEventListener('click',()=>{
    const index=Number(button.dataset.memePeriod);
    setPeriod(index);
    const bin=document.querySelectorAll('.time-bin')[index];
    bin?.focus({preventScroll:true});
    bin?.scrollIntoView({block:'nearest',inline:'nearest'});
  }));
  reactions.querySelectorAll('.meme-sc-toggle').forEach(button=>button.addEventListener('click',()=>{
    const open=button.getAttribute('aria-expanded')!=='true';
    button.setAttribute('aria-expanded',String(open));button.textContent=open?'收起':'展开';
    document.getElementById(button.getAttribute('aria-controls')).dataset.expanded=String(open);
  }));
  fitMemeText();
  if(period && !Array.isArray(visible.critical_quotes)){
    criticals.innerHTML='<p class="insight-empty">该时段的原文尚未更新。</p>';return;
  }
  // All-day includes each five-minute selection, preserving its own Top 10.
  const criticalQuotes=period || !Array.isArray(insightData.period_insights)
    ? (visible.critical_quotes || []).slice(0,10)
    : [...insightData.period_insights].sort((a,b)=>a.start-b.start)
      .flatMap(row=>(row.critical_quotes || []).slice(0,10));
  const criticalTotal=visible.critical_total_count ?? (period?period.topic[5]:dayData?.series?.all?.topic?.[5]);
  const quoteHTML=criticalQuotes.map((row,index)=>{
    const long=row.text.length>12 || /[\r\n]/.test(row.text);
    const fullId=`quote-full-${index}`;
    const score=attackScore(row);
    return `<article class="critical-quote${score!==null&&score<50?' critical-quote-low':''}"><div class="critical-row"><span class="severity-badge" title="措辞评分 ${score??'未评分'} / 100" aria-label="措辞强度 ${score??'未评分'}">${score??'—'}</span><time>${time(row.ts)}</time><a class="quote-source" href="${escapeHTML(sourceSearchLink(row))}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(row.text)} · 在 Danmakus 按内容与时间查看出处"><span class="quote-preview">${escapeHTML(row.text)}</span><span aria-hidden="true">↗</span></a>${long?`<button class="quote-toggle" aria-expanded="false" aria-controls="${fullId}">展开</button>`:''}</div>${long?`<p id="${fullId}" class="quote-full" hidden>${escapeHTML(row.text)}</p>`:''}</article>`;
  }).join('');
  criticals.innerHTML=quoteHTML || (criticalTotal>0
    ? '<p class="insight-empty">暂无可展示原文。</p>'
    : `<p class="insight-empty">${period?'该时段':'当天'}暂无攻击摘录。</p>`);
  criticals.querySelectorAll('.quote-toggle').forEach(button=>button.addEventListener('click',()=>{
    const open=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(open));button.textContent=open?'收起':'展开';document.getElementById(button.getAttribute('aria-controls')).hidden=!open;
  }));
}
async function loadInsights(value,version) {
  insightData=null;insightStatus='loading';
  if(!snapshot.calendar[value].observed){insightStatus='ready';renderInsights();return;}
  if(insightCache.has(value)){insightData=insightCache.get(value);insightStatus='ready';renderInsights();return;}
  renderInsights();
  try{
    const response=await fetch(`insights/${value}.json?v=${encodeURIComponent(snapshot.insights_generated_at)}`);
    if(!response.ok)throw new Error('Insights unavailable');
    const data=await response.json();if(data.day!==value)throw new Error('Wrong date');
    insightCache.set(value,data);if(insightCache.size>12)insightCache.delete(insightCache.keys().next().value);
    if(version!==requestVersion)return;insightData=data;insightStatus='ready';renderInsights();
  }catch(_){if(version===requestVersion){insightStatus='error';renderInsights();}}
}
function renderTimeline() {
  if (!snapshot) return;
  const box=$('#timeline');
  if (scope==='day' && dayStatus!=='ready') {
    box.innerHTML=dayStatus==='loading'?'<div class="chart-empty" role="status"><strong>正在读取当天统计</strong></div>':'<div class="chart-empty" role="alert"><strong>当天统计暂时无法读取</strong><button id="retry-day">重新读取</button></div>';
    $('#retry-day')?.addEventListener('click',()=>loadDay(date,{keepWindow:true}));return;
  }
  if (!buckets.length || (scope==='day' && !currentSeries().total)) {
    box.innerHTML=`<div class="chart-empty"><strong>${scope==='day'?'这一天':'这个窗口'}暂无收录</strong></div>`;return;
  }
  drawStackedChart(box,buckets,{id:'main',title:selectedLabel(),selectedIndex:selected,onSelect:index=>scope==='day'?setPeriod(selected===index?'all':index):drillInto(scope,buckets[index])});
}
function drawStackedChart(box, rows, {id,title,compact=false,selectedIndex=null,onSelect}) {
  const viewport=Math.max(250,box.clientWidth),scrollable=!compact&&(scope==='day'||(scope==='month'&&viewport<600));
  const width=scrollable?Math.max(viewport,rows.length*(viewport<500?25:30)+56):viewport;
  const height=Math.max(compact?72:130,box.clientHeight);
  const left=compact?31:(width<500?34:44),right=compact?8:12,top=compact?11:14,bottom=compact?22:28;
  const plotWidth=width-left-right,plotHeight=height-top-bottom,columnWidth=plotWidth/rows.length;
  const gap=Math.min(compact?8:12,columnWidth*.2),labelEvery=Math.max(1,Math.ceil((compact?42:65)/columnWidth));
  const pattern=`uncertain-fill-${id}`;
  let svg=`<defs><pattern id="${pattern}" width="6" height="6" patternUnits="userSpaceOnUse"><rect width="6" height="6" fill="var(--unknown)"/><path d="M-1 1L1 -1M0 6L6 0M5 7L7 5" stroke="var(--unknown-line)" stroke-width=".6" opacity=".65"/></pattern></defs>`;
  for(const tick of compact?[0,50,100]:[0,25,50,75,100]) {
    const y=top+plotHeight*(1-tick/100);
    svg+=`<line class="gridline" x1="${left}" x2="${width-right}" y1="${y}" y2="${y}"/><text class="axis-label" x="${left-6}" y="${y+4}" text-anchor="end">${tick}%</text>`;
  }
  rows.forEach((bucket,index)=>{
    const x=left+index*columnWidth+gap/2,barWidth=columnWidth-gap;
    const description=`${bucket.label}，${bucket.disabled?'不在可选范围':bucket.total?'全部消息 '+number(bucket.total)+' 条':'暂无收录'}`;
    const details=bucket.total?order().map(topic=>`${labels()[topic]} ${percent(bucket.topic[topic],bucket.total)}（${number(bucket.topic[topic])} 条）`).join('\n'):'无收录，不代表无人发言';
    svg+=`<g class="chart-bin ${compact?'history-bin':'time-bin'}" role="button" tabindex="${bucket.disabled?-1:0}" aria-disabled="${Boolean(bucket.disabled)}" data-bin="${index}" data-key="${bucket.key || bucket.start}" ${compact?`data-history-window="${id}"`:''} aria-pressed="${index===selectedIndex}" aria-label="${escapeHTML(description)}"><title>${escapeHTML(description+'\n'+details)}</title>`;
    let running=0;
    if(bucket.total) for(const topic of order()) {
      const fraction=bucket.topic[topic]/bucket.total,y=top+plotHeight*(1-running-fraction);
      svg+=`<rect class="bar-segment" data-topic="${topic}" data-count="${bucket.topic[topic]}" x="${x}" y="${y}" width="${barWidth}" height="${plotHeight*fraction}" fill="${topic===unknownId()?`url(#${pattern})`:color(topic)}"/>`;
      running+=fraction;
    } else svg+=`<text class="empty-marker" x="${x+barWidth/2}" y="${top+plotHeight-6}">·</text>`;
    svg+=`<rect x="${x}" y="${top}" width="${barWidth}" height="${plotHeight}" fill="transparent"/><rect class="selection-outline" x="${x-1}" y="${top-2}" width="${barWidth+2}" height="${plotHeight+4}" rx="2"/></g>`;
    if(index%labelEvery===0)svg+=`<text class="axis-label" x="${x+barWidth/2}" y="${height-8}" text-anchor="middle">${escapeHTML(bucket.axis)}</text>`;
  });
  box.innerHTML=`<svg style="width:${scrollable?width+'px':'100%'}" viewBox="0 0 ${width} ${height}" aria-label="${escapeHTML(title)}，百分比从 0 到 100" role="group">${svg}</svg>`;
  applyHighlight();
  box.querySelectorAll('.chart-bin').forEach((element,index)=>{
    const activate=()=>{if(!rows[index].disabled)onSelect(index);};
    element.addEventListener('click',activate);
    element.addEventListener('keydown',event=>{
      if(event.key==='Enter'||event.key===' '){event.preventDefault();activate();}
    });
  });
}
function renderWindowCharts() {
  if(!snapshot || historyStatus!=='ready')return;
  for(const name of ['month','year','decade']) {
    const box=$(`#history-${name}`);if(!box)continue;
    const rows=windowBuckets(name);
    if(!snapshot.calendar[overviewDate].windows[name].series.all.total){
      box.innerHTML='<div class="chart-empty"><strong>该窗口暂无收录</strong></div>';continue;
    }
    drawStackedChart(box,rows,{id:name,title:`${windowNames[name]} · 按${name==='month'?'日':name==='year'?'月':'年'}话题构成`,compact:true,onSelect:index=>drillInto(name,rows[index])});
  }
}
const chartFootnotes={day:'5 分钟内各话题占全部收录消息的比例。',month:'每日话题占比，观察最近一个月的变化。',year:'各月按消息量汇总，观察话题的月度变化。',decade:'各年按消息量汇总，回看历年的话题变化。'};
function renderWindows() {
  if(historyStatus!=='ready') {
    $('#history-windows').innerHTML=['month','year','decade'].map((name,index)=>`<article class="window-card"><div class="window-heading"><h3>${windowNames[name]}<span>按${name==='month'?'日':name==='year'?'月':'年'}</span></h3></div><div class="legend window-legend" aria-label="${windowNames[name]}分类图例">${legendItems(true)}</div><div class="window-chart"><div class="chart-empty" role="status"><p>${historyStatus==='error'?'历史图表暂时无法读取':'历史图表正在后台加载…'}</p>${historyStatus==='error'&&index===0?'<button id="retry-history">重新读取</button>':''}</div></div></article>`).join('');
    $('#retry-history')?.addEventListener('click',loadHistory);applyHighlight();return;
  }
  $('#history-windows').innerHTML=['month','year','decade'].map(name=>{
    const window=snapshot.calendar[overviewDate].windows[name],total=window.series.all.total;
    const unit=name==='month'?'日':name==='year'?'月':'年';
    return `<article class="window-card" aria-labelledby="heading-${name}"><div class="window-heading"><h3 id="heading-${name}">${windowNames[name]}<span>按${unit}</span></h3><span class="window-range">${window.start.replaceAll('-','')} 到 ${window.end.replaceAll('-','')}</span><span class="window-total">${total?`<b>${total}</b> 条收录`:'无收录'}</span></div><div class="legend window-legend" aria-label="${windowNames[name]}分类图例">${legendItems(true)}</div><div id="history-${name}" class="window-chart" aria-label="${windowNames[name]}按${unit}百分比柱状图"></div><p class="chart-footnote">${chartFootnotes[name]}</p></article>`;
  }).join('');
  renderWindowCharts();
  applyHighlight();
}
function render() {
  if (!snapshot) return;
  buckets=mainBuckets();
  const data=current(),values=data.series,all=values.all,total=all.total;
  const range=scope==='day'?dateText(date):`${dateText(data.start)} — ${dateText(data.end)}`;
  $('#session-range').textContent=scope==='day'&&dayData
    ? `直播时段 ${dayData.live_ranges.map(r=>time(r.start)+'–'+time(r.end)).join(' / ')}`
    : `${range}${scope==='day'&&!snapshot.calendar[date].observed?' · 暂无收录':''}`;
  $('#message-count').textContent=total?String(total):'—';
  const unit=scope==='year'?'年':scope==='month'?'个月':'天';
  for(const [id,step,direction] of [['#prev-day',-1,'上'],['#next-day',1,'下']]) {
    const target=adjacentView(step),button=$(id);
    button.disabled=!target||!rangeHasDate(scope,target);
    const label=scope==='day'?`${direction}一个有收录的日期`:`${direction}一${unit}`;
    button.setAttribute('aria-label',label);button.title=`${label}（${step<0?'←':'→'}）`;
  }
  $('#latest-day').disabled=scope==='day'&&date===snapshot.default_date&&!inDrill;
  $('#date').value=inputValue();$('#date').placeholder=scope==='year'?'YYYY':scope==='month'?'YYYY-MM':'YYYY-MM-DD';
  $('#date').setAttribute('aria-label',scope==='year'?'观察年份':scope==='month'?'观察月份':'观察日期');
  $('#chart-title').textContent=scope==='day'?'这一天，都在聊什么':`${viewLabel(scope,date)}的话题构成`;
  $('#chart-footnote').textContent=scope==='day'?chartFootnotes.day:scope==='year'?'按自然年汇总各月的话题构成。':'按自然月查看每天的话题构成。';
  $('#fixed-interval').textContent=scope==='day'?'5 分钟':scope==='year'?'按月':'按日';
  renderBreadcrumbs();
  $('#legend').innerHTML=legendItems();
  if (selected!==null&&selected>=buckets.length) selected=null;
  const updatedAt=new Date(snapshot.generated_at);
  $('#snapshot-note').textContent=`更新于 ${Number.isNaN(updatedAt.getTime())?'时间未记录':updateClock.format(updatedAt)}`;
  $('#coverage-note').textContent=`${snapshot.classification_status?.unreadable_events??'—'} 条图片或缺失正文待判断 · 收录不等于完整`;
  $('#snapshot-note').title=`北京时间 · 数据截至 ${snapshot.as_of}`;
  setPeriod(selected===null?'all':selected);renderTimeline();renderWindows();saveView();
}
async function loadDay(value,{keepWindow=false}={}) {
  if (!validDate(value)) return;
  if(!keepWindow){navigateView('day',value,{drill:false,anchor:value});return;}
  ensureDay(value);
  const version=++requestVersion;date=value;$('#date').value=date;setDateError('');$('#timeline').scrollLeft=0;selected=null;dayData=null;dayStatus='loading';
  loadInsights(value,version);
  if (!snapshot.calendar[date].observed) {dayStatus='ready';render();return;}
  if (cache.has(date)) {dayData=cache.get(date);snapshot.calendar[date].series=dayData.series;dayStatus='ready';render();return;}
  render();
  try {
    const response=await fetch(`days/${value}.json?v=${encodeURIComponent(snapshot.generated_at)}`);
    if (!response.ok) throw new Error('Daily snapshot unavailable');
    const data=await response.json();
    if (data.day!==value || (historyStatus==='ready' && data.series.all.total!==snapshot.calendar[value].series.all.total)) throw new Error('Daily snapshot inconsistent');
    cache.set(value,data);if(cache.size>12)cache.delete(cache.keys().next().value);
    if(version!==requestVersion) return;
    dayData=data;snapshot.calendar[value].series=data.series;dayStatus='ready';render();
  } catch (_) {if(version===requestVersion){dayStatus='error';render();}}
}
document.documentElement.dataset.theme='dark';
$('#about-button').addEventListener('click',()=>$('#about-dialog').showModal());
$('#about-close').addEventListener('click',()=>$('#about-dialog').close());
$('#about-dialog').addEventListener('click',event=>{
  const rect=event.currentTarget.getBoundingClientRect();
  if(event.target===event.currentTarget&&(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom))event.currentTarget.close();
});
$('#changelog-button').addEventListener('click',()=>$('#changelog-dialog').showModal());
$('#changelog-close').addEventListener('click',()=>$('#changelog-dialog').close());
$('#changelog-dialog').addEventListener('close',()=>$('#changelog-button').focus({preventScroll:true}));
$('#changelog-dialog').addEventListener('click',event=>{
  const rect=event.currentTarget.getBoundingClientRect();
  if(event.target===event.currentTarget&&(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom))event.currentTarget.close();
});
$('#all-day').addEventListener('click',()=>setPeriod('all'));
function setDateError(message) {
  $('#date-error').textContent=message;$('#date-error').hidden=!message;
  $('#date').setAttribute('aria-invalid',String(Boolean(message)));
}
function commitDate() {
  if(!snapshot)return;
  const match=$('#date').value.trim().match(/^(\d{4})(?:[-/.](\d{1,2}))?(?:[-/.](\d{1,2}))?$/);
  if(!match){setDateError('请输入年份、年月或完整日期');return;}
  const value=`${match[1]}-${(match[2]||'1').padStart(2,'0')}-${(match[3]||'1').padStart(2,'0')}`;
  const level=match[3]?'day':match[2]?'month':'year';
  if(!Number.isFinite(Date.parse(value))||isoDay(Date.parse(value))!==value||!rangeHasDate(level,value)){
    setDateError(`请选择有效时间：${snapshot.min_date} 至 ${snapshot.as_of}`);return;
  }
  if(level===scope&&value===date){$('#date').value=inputValue();setDateError('');return;}
  navigateView(level,value,{drill:level!=='day',anchor:level==='day'?value:overviewDate});
}
$('#date').addEventListener('input',()=>setDateError(''));
$('#date').addEventListener('keydown',event=>{
  if(event.key==='Enter'){event.preventDefault();commitDate();}
  if(event.key==='Escape'){$('#date').value=inputValue();setDateError('');$('#date').blur();}
});
let calendarMonth, calendarView = 'days', calendarFocus, calendarTarget = 'day';
const monthNumber = value => Number(value.slice(0,4))*12+Number(value.slice(5,7))-1;
const monthText = value => `${Math.floor(value/12)}-${String(value%12+1).padStart(2,'0')}`;
const hasRecords = value => snapshot.calendar[value]?.observed ?? observedDates.has(value);
function positionCalendar() {
  const dialog=$('#calendar-dialog');if(!dialog.open)return;
  // Bounding rectangles use visible pixels; fixed offsets use the page's zoomed CSS coordinates.
  const scale=Number(getComputedStyle(document.documentElement).zoom)||1;
  const box=$('.date-field').getBoundingClientRect(),width=dialog.offsetWidth,height=dialog.offsetHeight;
  const viewportWidth=innerWidth/scale,viewportHeight=innerHeight/scale;
  const left=viewportWidth<=600?(viewportWidth-width)/2:Math.max(12,Math.min(box.right/scale-width,viewportWidth-width-12));
  const top=viewportWidth<=600?Math.max(12,(viewportHeight-height)/2):Math.max(12,Math.min(box.bottom/scale+12,viewportHeight-height-12));
  dialog.style.left=`${left}px`;dialog.style.top=`${top}px`;
}
function renderCalendar({focus=false}={}) {
  const grid=$('#calendar-grid'),year=Math.floor(calendarMonth/12),month=calendarMonth%12;
  const min=monthNumber(snapshot.min_date),max=monthNumber(snapshot.as_of);
  const period=$('#calendar-period'),prev=$('#calendar-prev'),next=$('#calendar-next');
  $('#calendar-weekdays').hidden=calendarView!=='days';
  grid.classList.toggle('is-periods',calendarView!=='days');
  period.innerHTML=calendarView==='days'?`${year} 年 ${month+1} 月 <span aria-hidden="true">⌄</span>`:calendarView==='months'?`${year} 年 <span aria-hidden="true">⌄</span>`:'选择年份';
  period.setAttribute('aria-label',calendarView==='days'?'选择年月':calendarView==='months'?'选择年份':'返回日期日历');
  prev.hidden=next.hidden=calendarView==='years';
  prev.disabled=calendarView==='days'?calendarMonth<=min:year<=Math.floor(min/12);
  next.disabled=calendarView==='days'?calendarMonth>=max:year>=Math.floor(max/12);
  prev.setAttribute('aria-label',calendarView==='days'?'上个月':'上一年');
  next.setAttribute('aria-label',calendarView==='days'?'下个月':'下一年');
  if(calendarView==='days') {
    const prefix=monthText(calendarMonth),first=Date.parse(`${prefix}-01`),offset=(new Date(first).getUTCDay()+6)%7;
    if(!calendarFocus?.startsWith(prefix)||!validDate(calendarFocus))calendarFocus=date.startsWith(prefix)?date:isoDay(Math.max(first,Date.parse(snapshot.min_date)));
    grid.setAttribute('aria-label',`${year}年${month+1}月的日期`);
    grid.innerHTML=Array.from({length:42},(_,i)=>{
      const value=isoDay(first+(i-offset)*dayMs),observed=hasRecords(value),outside=!value.startsWith(prefix),enabled=validDate(value);
      return `<button class="calendar-day${observed?' has-records':''}${outside?' is-outside':''}" data-calendar-day="${value}" aria-label="${value}，${enabled?(observed?'有收录':'暂无收录'):'不在可选范围'}" aria-pressed="${value===date}" tabindex="${value===calendarFocus?0:-1}" ${enabled?'':'disabled'}>${Number(value.slice(-2))}</button>`;
    }).join('');
    const count=Array.from({length:new Date(Date.UTC(year,month+1,0)).getUTCDate()},(_,i)=>`${prefix}-${String(i+1).padStart(2,'0')}`).filter(hasRecords).length;
    $('#calendar-status').textContent=count?`本月收录 ${count} 天`:'本月暂无收录';
  } else {
    const years=calendarView==='years';
    const values=years?Array.from({length:Math.floor(max/12)-Math.floor(min/12)+1},(_,i)=>Math.floor(min/12)+i):Array.from({length:12},(_,i)=>year*12+i);
    grid.setAttribute('aria-label',years?'选择年份':'选择月份');
    grid.innerHTML=values.map(value=>`<button class="calendar-choice" data-calendar-${years?'year':'month'}="${value}" aria-pressed="${years?value===year:value===calendarMonth}" ${!years&&(value<min||value>max)?'disabled':''}>${years?value+' 年':value%12+1+' 月'}</button>`).join('');
    $('#calendar-status').textContent=years?(calendarTarget==='year'?'选择年份查看每月分布':'选择年份后选择月份'):(calendarTarget==='month'?'选择月份查看每日分布':'选择月份后选择日期');
  }
  $('#calendar-selected').textContent=`已选 ${viewLabel(scope,date)}`;
  positionCalendar();
  if(focus)grid.querySelector(calendarView==='days'?'[tabindex="0"]':'[aria-pressed="true"]')?.focus();
}
function openCalendar() {
  if(!snapshot)return;
  calendarMonth=monthNumber(date);calendarTarget=scope;calendarView=scope==='year'?'years':scope==='month'?'months':'days';calendarFocus=date;
  $('#calendar-title').textContent=scope==='year'?'选择年份':scope==='month'?'选择月份':'选择日期';
  $('#calendar-subtitle').textContent=scope==='year'?'查看这一年的每月分布':scope==='month'?'查看这个月的每日分布':'回看这一天的直播间';
  renderCalendar();$('#calendar-dialog').showModal();$('#open-calendar').setAttribute('aria-expanded','true');
  positionCalendar();$('#calendar-grid [tabindex="0"]')?.focus();
}
function chooseCalendarDay(value) {
  if(!validDate(value))return;
  $('#calendar-dialog').close();navigateView('day',value,{drill:false,anchor:value});
}
$('#open-calendar').addEventListener('click',openCalendar);
$('#calendar-close').addEventListener('click',()=>$('#calendar-dialog').close());
$('#calendar-dialog').addEventListener('close',()=>{
  $('#open-calendar').setAttribute('aria-expanded','false');$('#open-calendar').focus({preventScroll:true});
});
$('#calendar-dialog').addEventListener('click',event=>{
  const dialog=event.currentTarget,rect=dialog.getBoundingClientRect();
  if(event.target===dialog&&(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom))dialog.close();
});
$('#calendar-period').addEventListener('click',()=>{
  calendarView=calendarView==='days'?'months':calendarView==='months'?'years':'days';renderCalendar({focus:true});
});
for(const [id,step] of [['#calendar-prev',-1],['#calendar-next',1]])$(id).addEventListener('click',()=>{
  calendarMonth=Math.max(monthNumber(snapshot.min_date),Math.min(monthNumber(snapshot.as_of),calendarMonth+step*(calendarView==='days'?1:12)));
  calendarFocus=null;renderCalendar();
});
$('#calendar-grid').addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button||button.disabled)return;
  if(button.dataset.calendarDay)chooseCalendarDay(button.dataset.calendarDay);
  else if(button.dataset.calendarMonth){
    calendarMonth=Number(button.dataset.calendarMonth);
    if(calendarTarget==='month'){$('#calendar-dialog').close();navigateView('month',`${monthText(calendarMonth)}-01`);}
    else {calendarView='days';calendarFocus=null;renderCalendar({focus:true});}
  } else if(button.dataset.calendarYear){
    if(calendarTarget==='year'){$('#calendar-dialog').close();navigateView('year',`${button.dataset.calendarYear}-01-01`);}
    else {calendarMonth=Math.max(monthNumber(snapshot.min_date),Math.min(monthNumber(snapshot.as_of),Number(button.dataset.calendarYear)*12+calendarMonth%12));calendarView='months';renderCalendar({focus:true});}
  }
});
$('#calendar-grid').addEventListener('keydown',event=>{
  const button=event.target.closest('[data-calendar-day]');if(!button)return;
  const value=button.dataset.calendarDay,ts=Date.parse(value),weekday=(new Date(ts).getUTCDay()+6)%7;
  let target;
  const steps={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7,Home:-weekday,End:6-weekday};
  if(Object.hasOwn(steps,event.key))target=isoDay(ts+steps[event.key]*dayMs);
  else if(event.key==='PageUp'||event.key==='PageDown'){
    const month=monthNumber(value)+(event.key==='PageUp'?-1:1)*(event.shiftKey?12:1);
    const last=new Date(Date.UTC(Math.floor(month/12),month%12+1,0)).getUTCDate();
    target=`${monthText(month)}-${String(Math.min(Number(value.slice(-2)),last)).padStart(2,'0')}`;
  } else return;
  event.preventDefault();
  target=target<snapshot.min_date?snapshot.min_date:target>snapshot.as_of?snapshot.as_of:target;
  calendarFocus=target;calendarMonth=monthNumber(target);renderCalendar({focus:true});
});
$('#calendar-latest').addEventListener('click',()=>chooseCalendarDay(snapshot.default_date));
window.addEventListener('resize',positionCalendar);
$('#prev-day').addEventListener('click',()=>moveView(-1));
$('#next-day').addEventListener('click',()=>moveView(1));
document.addEventListener('keydown',event=>{
  if(!snapshot || event.defaultPrevented || event.isComposing || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)return;
  if(event.key!=='ArrowLeft' && event.key!=='ArrowRight')return;
  // Text editing and an open dialog keep their own arrow-key behavior.
  if(event.target.closest('input,textarea,select') || event.target.isContentEditable || document.querySelector('dialog[open]'))return;
  event.preventDefault();
  const button=$(event.key==='ArrowLeft'?'#prev-day':'#next-day');
  if(!button.disabled)button.click();
});
$('#latest-day').addEventListener('click',()=>loadDay(snapshot.default_date));
async function fetchHistory() {
  const response=await fetch('data.json',{cache:'no-cache',priority:'low',signal:AbortSignal.timeout(20000)});
  if(!response.ok)throw new Error('History unavailable');
  const data=await response.json();if(data.schema_version!==4)throw new Error('Version mismatch');
  return data;
}
async function loadHistory() {
  if(historyRequest)return historyRequest;
  historyStatus='loading';renderWindows();
  historyRequest=(async()=>{
    try {
      const data=await fetchHistory();
      const changed=data.generated_at!==snapshot.generated_at || data.insights_generated_at!==snapshot.insights_generated_at;
      snapshot=data;historyStatus='ready';
      observedDates=new Set(Object.keys(snapshot.calendar).filter(day=>snapshot.calendar[day].observed));
      if($('#calendar-dialog').open)renderCalendar();
      if(pendingScope){scope=pendingScope;pendingScope=null;}
      if(changed){cache.clear();insightCache.clear();await loadDay(validDate(date)?date:snapshot.default_date,{keepWindow:true});}
      else render();
    } catch (_) {historyStatus='error';renderWindows();}
    finally {historyRequest=null;}
  })();
  return historyRequest;
}
async function loadSnapshot() {
  try {
    const embedded=$('#first-screen');
    let first;
    try {first=embedded&&JSON.parse(embedded.textContent);} catch (_) {first=null;}
    if(first?.snapshot?.schema_version===4 && first.day?.day===first.snapshot.default_date) {
      snapshot=first.snapshot;historyStatus='loading';
      observedDates=new Set(snapshot.observed_dates);
      cache.set(first.day.day,first.day);
      if(first.insights)insightCache.set(first.day.day,first.insights);
    } else {snapshot=await fetchHistory();historyStatus='ready';}
    const params=new URL(location.href).searchParams;
    const requestedScope=['year','month'].includes(params.get('window'))?params.get('window'):'day';
    pendingScope=historyStatus!=='ready'&&requestedScope!=='day'?requestedScope:null;
    scope=historyStatus==='ready'?requestedScope:'day';
    date=validDate(params.get('date'))?params.get('date'):snapshot.default_date;
    overviewDate=validDate(params.get('anchor'))?params.get('anchor'):date;
    inDrill=requestedScope!=='day'||params.get('drill')==='1';
    if(historyStatus==='ready')observedDates=new Set(Object.keys(snapshot.calendar).filter(day=>snapshot.calendar[day].observed));
    $('#loading').hidden=true;for(const selector of ['#summary','#charts','#history-windows','#source-footer'])$(selector).hidden=false;
    const resize=new ResizeObserver(()=>{renderTimeline();renderWindowCharts();fitMemeText();});
    resize.observe($('#timeline'));resize.observe($('#history-windows'));
    await loadDay(date,{keepWindow:true});
    // Give the day's chart and excerpts a paint before starting the large request.
    if(historyStatus!=='ready')requestAnimationFrame(()=>setTimeout(loadHistory,0));
  } catch (_) {
    $('#loading').hidden=false;$('#loading').innerHTML='<p>暂时无法读取页面内容，请稍后重试。</p><button id="retry">重新读取</button>';
    $('#retry').addEventListener('click',loadSnapshot);
  }
}
loadSnapshot();
