// Selected-date activity and weighted history share the authoritative cell-day store.
let workspaceSequence=0, workspaceAbort=null, workspaceHistory=null;
const workspaceHost=document.createElement('section');
workspaceHost.className='activity-workspace';
workspaceHost.innerHTML=`<div class="activity-hero" aria-live="polite"><p class="workspace-kicker">Your land · selected date</p><h3>Estimated burning activity</h3><p id="workspace-date"></p><label class="workspace-date-control">Selected date <input id="workspace-date-input" type="date"></label><strong id="workspace-value">Select land</strong><p id="workspace-ratio"></p><p>Share of adequately observed 5 km squares showing burning activity.</p><p id="workspace-source" class="quiet"></p><button id="workspace-retry" type="button" hidden>Retry activity</button></div><section class="workspace-history"><div class="workspace-chart-head"><h3>Burning activity (%)</h3><label>Period <select id="workspace-period"><option value="day">Daily</option><option value="week">Weekly</option><option value="month">Monthly</option></select></label></div><p id="workspace-chart-date" class="quiet"></p><svg id="workspace-chart" viewBox="0 0 620 200" role="group" aria-label="Burning activity by Philippine date"></svg><p class="workspace-key"><span>● Activity</span>　○ Measured zero　 — Coverage gap</p><p id="workspace-point" aria-live="polite">Select a day to update the map.</p><button id="workspace-history-retry" type="button" hidden>Retry history</button></section><details class="workspace-methods"><summary>How we estimate this</summary><p>Each usable square-day contributes once. Eligible Aqua supplies observed activity; the frozen harmonization model can supply a calibrated Suomi-NPP contribution only when its required inputs exist. Periods divide summed active contributions by summed usable square-days. Missing coverage is excluded. This is not land area burned or wildfire probability.</p><p id="workspace-products"></p></details>`;
document.querySelector('#land-summary').prepend(workspaceHost);
// Preserve the existing detailed views and satellite pass lists.
for(const [selector,label] of [['#land-summary > .activity','Satellite heat readings & detailed methods'],['#hotspot-forecast-block','Forecast · next 24 hours'],['#land-summary > .hours','Weather · conditions and hourly outlook']]) {
 const node=document.querySelector(selector);if(!node)continue;
 const fold=document.createElement('details');fold.className='workspace-support';
 const summary=document.createElement('summary');summary.textContent=label;fold.append(summary);node.before(fold);fold.append(node);
}
const picture=document.querySelector('#land-picture');
if(picture){const fold=document.createElement('details');fold.className='workspace-preview';fold.innerHTML='<summary>View selected land · map, imagery & 3D</summary>';picture.before(fold);fold.append(picture);}
function workspacePercent(rate){return rate==null?'Activity estimate unavailable':`${(rate*100).toFixed(1)}%`;}
function workspaceRows(payload,period){return period==='week'?payload?.weeks||[]:period==='month'?payload?.months||[]:payload?.days||[];}
function renderWorkspaceChart(){
 const period=document.querySelector('#workspace-period').value,rows=workspaceRows(workspaceHistory,period);
 const month=state.calendarMonth||dayInput.value.slice(0,7);
 document.querySelector('#workspace-chart-date').textContent=`${period==='day'?monthLabel(month+'-01'):month.slice(0,4)} · Philippine dates · gaps mean no usable coverage`;
 const max=Math.max(.1,...rows.map(r=>r.activity_rate||0));const ceiling=Math.min(1,Math.ceil(max*10)/10),band=558/Math.max(rows.length,1);
 let markup=[0,.5,1].map(f=>`<path d="M46 ${158-f*130}H610" stroke="var(--line)"/><text x="36" y="${162-f*130}" text-anchor="end">${Math.round(f*ceiling*100)}%</text>`).join('');
 rows.forEach((r,i)=>{
 const stamp=r.date||r.period_start||r.month+'-01',available=r.activity_rate!=null&&stamp<=todayIso();const x=48+i*band;
 const label=`${stamp}: ${available?workspacePercent(r.activity_rate):'Activity unavailable'}${available?` · ${Number(r.activity_numerator??r.activity_rate*r.activity_denominator).toFixed(2)} / ${r.activity_denominator} usable square-days · ${r.usable_days||1} usable days · Aqua ${r.aqua_contributions??r.method_counts?.['observed Aqua activity']??0} · calibrated Suomi ${r.suomi_contributions??r.method_counts?.['calibrated VIIRS estimate']??0}`:''}`;
 const height=available?Math.max(3,r.activity_rate/ceiling*130):0;
 markup+=`<g tabindex="0" role="button" data-workspace-day="${stamp}" aria-label="${escapeHtml(label)}"><title>${escapeHtml(label)}</title><rect x="${x}" y="20" width="${band}" height="145" fill="transparent"/>${available?`<rect x="${x+2}" y="${158-height}" width="${Math.max(2,band-5)}" height="${height}" rx="2" fill="var(--teal)"/>`:`<path d="M${x+2} 165h${Math.max(2,band-5)}" stroke="var(--ink-faint)" stroke-dasharray="3 2"/>`}${i===0||i===rows.length-1||i%(period==='month'?1:period==='week'?8:5)===0?`<text x="${x+band/2}" y="188" text-anchor="middle">${period==='day'?Number(stamp.slice(8)):period==='month'?new Date(stamp+'T00:00:00Z').toLocaleString('en',{month:'short',timeZone:'UTC'}):stamp.slice(5)}</text>`:''}</g>`;
 });
 if(!rows.length)markup+='<text x="310" y="95" text-anchor="middle">No history loaded</text>';
 document.querySelector('#workspace-chart').innerHTML=markup;
}
async function loadActivityWorkspace(){
 const ring=summaryTarget().ring;if(!ring)return;
 const seq=++workspaceSequence,date=dayInput.value,boundary=state.summarySquare?null:state.boundaryPreset||null;
 workspaceAbort?.abort();workspaceAbort=new AbortController();const signal=workspaceAbort.signal;
 const valid=()=>seq===workspaceSequence&&date===dayInput.value&&Boolean(state.polygon);
 const post=async(url,body)=>{const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});if(!res.ok)throw Error('Request failed');return res.json();};
 document.querySelector('#workspace-date-input').value=date;document.querySelector('#workspace-date-input').max=todayIso();
 document.querySelector('#workspace-date').textContent=formatObservationDay(date)+' · Philippine time';
 document.querySelector('#workspace-value').textContent='Loading…';document.querySelector('#workspace-ratio').textContent='';document.querySelector('#workspace-source').textContent='';
 document.querySelector('#workspace-retry').hidden=true;document.querySelector('#workspace-history-retry').hidden=true;
 workspaceHistory=null;renderWorkspaceChart();
 const body={coordinates:ring,boundary_preset:boundary};
 await Promise.allSettled([
 post('/api/activity/selection',{...body,date}).then(p=>{if(!valid())return;
 document.querySelector('#workspace-value').textContent=workspacePercent(p.activity_rate);
 document.querySelector('#workspace-value').classList.toggle('unavailable',p.activity_rate==null);
 document.querySelector('#workspace-ratio').textContent=p.activity_rate==null?'':`${Number(p.activity_numerator).toLocaleString('en-PH',{maximumFractionDigits:2})} estimated active square-days / ${p.activity_denominator.toLocaleString('en-PH')} usable square-days`;
 document.querySelector('#workspace-source').textContent=p.activity_rate==null?p.reason:`Partial coverage · ${(p.satellites||[]).join(', ')}${p.observation_times_utc?.length?' · supplying pass '+philippinePassLabel(p.observation_times_utc.at(-1)):''}`;
 document.querySelector('#workspace-products').textContent='Source products: '+((p.source_products||[]).join(', ')||'No eligible products for this date.');
 document.querySelector('#workspace-retry').hidden=p.activity_rate!=null;
 }).catch(e=>{if(!valid()||e.name==='AbortError')return;document.querySelector('#workspace-value').textContent='Activity request failed';document.querySelector('#workspace-retry').hidden=false;}),
 post('/api/history/month',{...body,year:Number(date.slice(0,4)),month:Number(date.slice(5,7))}).then(p=>{if(!valid())return;workspaceHistory=p;renderWorkspaceChart();}).catch(e=>{if(!valid()||e.name==='AbortError')return;document.querySelector('#workspace-chart-date').textContent='History request failed. Retry to load stored observations.';document.querySelector('#workspace-history-retry').hidden=false;})]);
}
function workspaceChoose(event){const node=event.target.closest('[data-workspace-day]');if(!node)return;document.querySelector('#workspace-point').textContent=node.getAttribute('aria-label');chooseCalendarDay(node.dataset.workspaceDay);}
document.querySelector('#workspace-period').addEventListener('change',renderWorkspaceChart);
document.querySelector('#workspace-chart').addEventListener('click',workspaceChoose);
document.querySelector('#workspace-chart').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();workspaceChoose(e);}});
for(const id of ['#workspace-retry','#workspace-history-retry'])document.querySelector(id).addEventListener('click',loadActivityWorkspace);

document.querySelector("#workspace-date-input").addEventListener("change",e=>chooseCalendarDay(e.target.value));
