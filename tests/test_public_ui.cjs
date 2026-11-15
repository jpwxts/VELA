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
  const series = context.historyChartSeries([{heat_count:12,heat_area_count:11}], false);
  assert.equal(series.kind, 'heat');
  assert.equal(series.valueOf({heat_status:'readings',heat_count:12,heat_area_count:11}),1);
  assert.equal(series.valueOf({heat_status:'checked_empty',heat_count:0}),null);
  assert.equal(series.valueOf({heat_status:'checked_empty',heat_count:0,heat_coverage:'observed'}),0);
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
    renderLandCheck:()=>heatPaints++, renderOutlook:()=>weatherPaints++, renderWeatherSummary:()=>{}, renderObservedAnswer:()=>{},
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

const answers = fs.readFileSync('app/static/js/answers.js','utf8');
test('forecast marker opens its square before suppressing the underlying map click', () => {
  let button, opened=0;
  const context=vm.createContext({state:{ignoreMapClick:false,lastPayload:{hotspot_areas:{areas:[{cell_id:'2393:174'}]}}},
    clearProbabilitySurface:()=>{},document:{querySelector:()=>null,createElement:tag=>{
      const node={append:()=>{},setAttribute:()=>{},addEventListener:(_,fn)=>node.click=fn};
      if(tag==='button') button=node;
      return node;
    }},globe:{addOverlay:()=>({})},
    askAboutPoint:()=>{if(!context.state.ignoreMapClick) opened++;},guardMapClick:()=>context.state.ignoreMapClick=true});
  const markers=fs.readFileSync('app/static/js/markers.js','utf8');
  vm.runInContext(markers.slice(markers.indexOf('function renderProbabilityOverlay('),markers.indexOf('async function loadProbabilityOverlay(')),context);
  context.renderProbabilityOverlay({status:'ok',extent:{},cells:[{cell_id:'2393:174',center:{lat:6.85,lon:124.05},probability_percent:20.2,issuance_kind:'preserved_archive'}]});
  button.click({stopPropagation:()=>{}});
  assert.equal(opened,1);
  assert.equal(context.state.ignoreMapClick,true);
  assert.match(button.className,/has-observed/);
});
test('methods report the displayed model evaluation rather than another winner', () => {
  const nodes=new Map();
  const querySelector=id=>{
    if(!nodes.has(id)) nodes.set(id,{dataset:{},classList:{toggle:()=>{}},textContent:''});
    return nodes.get(id);
  };
  const context=vm.createContext({document:{querySelector},state:{},Number,
    philippinePass:x=>x,renderPredictionExplanation:()=>{},loadHotspotMonthForSquare:()=>{}});
  const source=fs.readFileSync('app/static/js/square.js','utf8');
  vm.runInContext(source.slice(source.indexOf('function renderHotspotForecast('),source.indexOf('async function loadHotspotForecast(')),context);
  context.renderHotspotForecast({status:'issued',probability_percent:20.2,model_version:'regional_seasonal_detection_rate',
    evaluation:{test:{f1:0,n:1808},validation:{f1:0,n:1001},threshold:0.5,run_id:'ph_national_prior_audit_v1'}});
  assert.equal(nodes.get('#hotspot-forecast-value').textContent,'20.2%');
  assert.match(nodes.get('#model-f1').textContent,/Model F1: 0\.0000 \(test n=1808\)/);
  assert.match(nodes.get('#model-f1').textContent,/ph_national_prior_audit_v1/);
  assert.doesNotMatch(nodes.get('#model-f1').textContent,/0\.5890|0\.6062/);
});
test('complete chart renders on startup and suppresses future observations', () => {
  const nodes = new Map();
  const querySelector = id => {
    if (!nodes.has(id)) nodes.set(id, {value:id==='#history-chart-range'?'month':'heat'});
    return nodes.get(id);
  };
  const context = vm.createContext({document:{querySelector},state:{calendarMonth:'2026-11'},Intl,Date,Number,
    currentMonthHistory:()=>({days:[{date:'2026-11-07',heat_status:'readings',heat_count:12,heat_area_count:11},
      {date:'2026-11-20',heat_status:'readings',heat_count:50,heat_area_count:49}]}),
    todayIso:()=> '2026-11-15',historyHotspotForDay:()=>null,dayInput:{value:'2026-11-07'},
    historyPercent:x=>`${x*100}%`,formatObservationDay:x=>x,historyStatusWords:()=> 'Missing',escapeHtml:x=>x});
  vm.runInContext(history.slice(history.indexOf('function historyChartSeries('),history.indexOf('function openForecastDay(')),context);
  context.renderHistoryChart();
  const svg=nodes.get('#history-chart').innerHTML;
  assert.equal((svg.match(/class="history-chart-value heat"/g)||[]).length,1);
  assert.match(svg,/2026-11-20: Not yet observed/);
  assert.match(svg,/history-chart-missing/);
});
test('panel language preserves observed counts, local times and missing evidence', () => {
  const context = vm.createContext({document:{querySelector:()=>null},Intl, Date, Number, manilaTodayIso:()=> '2026-11-15'});
  vm.runInContext(answers, context);
  const observation = context.observationPresentation({inside:[
    {platform:'NOAA-21',acq_date:'2026-11-07',acq_time:'04:33'}],hotspot_areas:{area_count:1}}, {square:true,date:'2026-11-07'});
  assert.equal(observation.total,'1');
  assert.match(observation.countLine,/1 satellite reading · NOAA-21/);
  assert.match(observation.latest,/12:33/);
  assert.match(observation.latest,/PH/);
  const empty = context.observationPresentation({inside:[],coverage:'unknown'},{});
  assert.equal(empty.total,'—');
  assert.match(empty.countLine,/coverage is unknown/);
  const failed = context.observationPresentation({status:'unavailable'},{});
  assert.match(failed.title,/unavailable/);
  assert.match(failed.countLine,/not an observed zero/);
});
test('each calendar day keeps observations, genuine issues and activity separate', () => {
  const context=vm.createContext({document:{querySelector:()=>null}}); vm.runInContext(answers,context);
  const issue={issuance_kind:'preserved_archive',probability_percent:18};
  const record={heat_status:'readings',heat_count:3,heat_area_count:2,activity_status:'partial',activity_rate:0.5};
  const row=context.calendarEvidence(record,issue,false);
  assert.equal(row.heat,'2'); assert.equal(row.forecast,'18%'); assert.equal(row.activity,'50.0%');
  const future=context.calendarEvidence(record,issue,true);
  assert.equal(future.heat,'—'); assert.equal(future.activity,'—');
  const reconstructed=context.calendarEvidence(record,{...issue,historical_simulation:true},false);
  assert.equal(reconstructed.forecast,'—');
  const unknown=context.calendarEvidence({heat_status:'checked_empty'},null,false);
  assert.equal(unknown.heat,'No returns');
});
test('a future selection cannot present returned points as observed activity', () => {
  const context=vm.createContext({document:{querySelector:()=>null},Intl, Date, Number, manilaTodayIso:()=> '2026-11-15'});
  vm.runInContext(answers,context);
  const value=context.observationPresentation({inside_count:3,hotspot_areas:{area_count:2}}, {date:'2026-11-20'});
  assert.equal(value.total,'—'); assert.match(value.title,/not yet observed/); assert.equal(value.latest,'');
});
