// Activity uses measured/calibrated cell-day contributions, independent of FIRMS.
function clearActivityMap() {
  (state.activityLayers || []).forEach(layer => layer.remove());
  state.activityLayers = [];
}

function renderActivityMap(payload) {
  clearActivityMap();
  if (state.panelTab === "forecast") return;
  state.activityLayers = (payload.cells || []).flatMap(cell => {
    const b=cell.bounds;
    const active=cell.activity_value > 0;
    const area=globe.addArea([[b.west,b.south],[b.east,b.south],[b.east,b.north],[b.west,b.north]], {
      stroke:active ? HEAT_FILL : "#8e9a91",weight:active?2:1,
      fill:active?HEAT_FILL:"#8e9a91",fillOpacity:active ? .3 : .035,
    });
    const marker=document.createElement("button");
    marker.type="button";marker.className=`activity-map-marker${active?" active":" zero"}`;
    marker.title=`${cell.platform}: ${active?"activity observed":"usable observed zero"} · ${payload.date}`;
    marker.setAttribute("aria-label",`Activity square ${cell.cell_id}: ${active?"active":"measured zero"} from ${cell.platform} on ${payload.date}. Show activity.`);
    marker.addEventListener("click",event=>{
      event.stopPropagation();
      state.selectedArea=null;
      revealCellDetail(b,[],{state:"checking"});
      state.summarySquare.cellId=cell.cell_id;
      state.currentActivity={...payload,cells:[cell],activity_rate:cell.activity_value,activity_numerator:cell.activity_value,
        activity_denominator:1,aqua_contributions:cell.platform==="Aqua"?1:0,suomi_contributions:cell.platform==="Suomi-NPP"?1:0,
        method_counts:{[cell.method]:1},source_products:[cell.fire_file,cell.geo_file],observation_times_utc:[cell.pass_time_utc]};
      applyLandActivity(state.currentActivity);
      renderObservedAnswer({status:"loading"},{square:true,date:payload.date});
      updateSelectionBanner();guardMapClick();
      // Retain the actual contributing mask source beside any point-feed evidence.
      document.querySelector("#observed-heat-summary").textContent=`Supplying Aqua fire mask: ${cell.qualifying_detection_count} qualifying fire pixel${cell.qualifying_detection_count===1?"":"s"} in this square. FIRMS readings are a separate measurement.`;
      document.querySelector("#observed-headline").textContent=active?"Heat detected by Aqua fire mask":"Aqua observed this square · no activity";
      document.querySelector("#observed-square-count").textContent=active?"1":"0";
      document.querySelector("#observed-latest").textContent=`Supplying pass · ${philippinePass(cell.pass_time_utc)}`;
    });
    return [area,globe.addOverlay(cell.center_lat,cell.center_lon,marker)];
  });
}

document.querySelector("#activity-retry")?.addEventListener("click",()=>loadWeeklyActivity());
document.querySelector(".conditions-card")?.addEventListener("toggle",event=>{
  if(event.target.open) loadDayOutlook();
});
