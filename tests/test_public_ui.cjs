const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const history = fs.readFileSync('app/static/js/history.js', 'utf8');
const land = fs.readFileSync('app/static/js/land.js', 'utf8');
const seriesSource = history.slice(history.indexOf('function historyChartSeries('), history.indexOf('function renderHistoryChart('));

test('chart measures stay separate; checked zero and coverage gap differ', () => {
  const context = vm.createContext({document:{querySelector:()=>({value:'heat'})}, state:{}, Number,
    historyPercent:x=>`${x*100}%`, historyHotspotForDay:()=>null});
  vm.runInContext(seriesSource, context);
  const series = context.historyChartSeries([{heat_count:12}], false);
  assert.equal(series.kind, 'heat');
  assert.equal(series.valueOf({heat_status:'readings',heat_count:12}),1);
  assert.equal(series.valueOf({heat_status:'checked_empty',heat_count:0}),0);
  assert.equal(series.valueOf({heat_status:'not_checked',heat_count:0}),null);
  context.document.querySelector = ()=>({value:'activity'});
  const activity = context.historyChartSeries([],false);
  assert.equal(activity.valueOf({activity_rate:0,activity_status:'partial'}),0);
  assert.equal(activity.valueOf({activity_rate:0,activity_status:'unavailable'}),null);
  context.document.querySelector = ()=>({value:'hotspot'});
  context.state.hotspotMonthCellId='2393:174';
  context.historyHotspotForDay=()=>({probability_percent:99,issuance_kind:'historical_reconstruction',historical_simulation:true});
  assert.equal(context.historyChartSeries([],false).valueOf({date:'2026-11-07'}),null);
});

test('heat renders while weather remains pending; obsolete weather is ignored', async () => {
  let heatPaints=0, weatherPaints=0;
  const pendingWeather=[];
  const nodes = new Map();
  const context=vm.createContext({
    state:{polygon:[[0,0],[1,0],[1,1],[0,0]],box:[0,0,1,1],landRequestId:0,requestId:0,mapMode:'live',phToday:'2026-11-15'},
    document:{querySelector:s=>{if(!nodes.has(s)) nodes.set(s,{});return nodes.get(s);}},
    dayInput:{value:'2026-11-15'}, DEFAULT_PLATFORMS:['Aqua'], AbortController, AbortSignal,
    selectedPlatforms:()=>['Aqua'], setDefaultPlatforms:()=>{}, resetLandResult:()=>{},refreshLandSummary:()=>{},
    setChecking:()=>{},formatObservationDay:x=>x,renderDaySummary:()=>{},openLandPanel:()=>{},
    beginHotspotSearch:()=>()=>{},weatherSelectors:()=>({}),applyLandActivity:()=>{},
    renderLandCheck:()=>heatPaints++, renderOutlook:()=>weatherPaints++, renderWeatherSummary:()=>{},
    fetch:(url)=>url.startsWith('/api/preparedness') ? new Promise(resolve=>pendingWeather.push(resolve))
      : Promise.resolve({ok:true,json:async()=>({heat:{inside_count:12}})}),
  });
  vm.runInContext(land.slice(land.indexOf('async function checkLand('), land.indexOf('function setResultLead(')),context);
  await context.checkLand();
  assert.equal(heatPaints,1);
  assert.equal(weatherPaints,0);
  await context.checkLand();
  pendingWeather[0]({ok:true,json:async()=>({ok:true,days:[],version:'stale'})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(weatherPaints,0);
  pendingWeather[1]({ok:true,json:async()=>({ok:true,days:[],version:'current'})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(weatherPaints,1);
  assert.equal(context.state.forecast.version,'current');
  assert.equal(heatPaints,2);
});

test('month switching deduplicates pending requests and rejects obsolete responses', async () => {
  const requests=[];
  const context=vm.createContext({state:{hotspotMonthCellId:'2393:174'}, URLSearchParams,
    todayIso:()=> '2026-11-15', dayInput:{value:'2026-11-07'}, renderObservationCalendar:()=>{},
    renderDaySummary:()=>{},loadMonthlyHistory:()=>{},
    fetch: url=>new Promise(resolve=>requests.push({url,resolve}))});
  const loader=history.slice(history.indexOf('async function loadHotspotMonthForSquare('),history.indexOf('// Stored daily estimates'));
  const switcher=history.slice(history.indexOf('function setHistoryMonth('),history.indexOf('function chooseHistoryMonth('));
  vm.runInContext(loader+switcher,context);
  const first=context.loadHotspotMonthForSquare('2393:174','2026-11');
  await context.loadHotspotMonthForSquare('2393:174','2026-11');
  assert.equal(requests.length,1);
  context.setHistoryMonth('2026-10');
  assert.equal(requests.length,2);
  requests[0].resolve({json:async()=>({year_month:'2026-11'})});
  await first;
  assert.equal(context.state.hotspotMonth,null);
  // Re-selecting the same pending month must start a usable replacement request.
  context.setHistoryMonth('2026-10');
  assert.equal(requests.length,3);
  requests[1].resolve({json:async()=>({year_month:'2026-10',version:'obsolete'})});
  requests[2].resolve({json:async()=>({year_month:'2026-10',version:'latest'})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(context.state.hotspotMonth.version,'latest');
  assert.equal(context.state.hotspotMonthPendingKey,null);
});
