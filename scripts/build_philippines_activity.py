"""Reprocess cached Philippine Aqua pairs and persist eligible activity rows.

No download, retraining, FIRMS-derived labels, or synthetic coverage. Frozen
platform selection gives eligible Aqua precedence; Suomi needs its native mask
features and the existing frozen model. This local pilot has Aqua inputs only.
"""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pandas as pd
from shapely.geometry import Point, shape
from shapely.prepared import prep

from vela.boundaries import geometry_from_preset
from vela.contributions import select_one, activity_value
from vela.hotspot_coverage import process_fire_geo_pass
from vela.hotspot_forecast import MAGUINDANAO_EVALUATED
from vela.observation_store import ObservationStore, _connect
from vela.settings import DATA_DIR
from vela import serving
from vela.activity_store import PACKAGE, ensure_packaged_activity


def build():
    previous=pd.read_parquet(DATA_DIR/'processed/philippines_hotspot_coverage_passes.parquet')
    pairs=previous[['fire_file','geo_file','pass_time_utc','platform']].drop_duplicates().sort_values('pass_time_utc')
    land=prep(shape(geometry_from_preset('philippines')))
    raw=DATA_DIR/'raw/mindanao_hotspot'
    all_rows=[];sources=[];failures=[]
    cache=DATA_DIR/'processed/philippines_activity_reprocessed_passes.parquet'
    for i,pair in enumerate(pairs.itertuples(),1):
        when=datetime.fromisoformat(pair.pass_time_utc)
        fire=raw/when.date().isoformat()/pair.fire_file
        geo=raw/when.date().isoformat()/pair.geo_file
        if not fire.is_file() or not geo.is_file():
            failures.append({'fire_file':pair.fire_file,'geo_file':pair.geo_file,'reason':'Missing cached pair'})
            continue
        result=process_fire_geo_pass(fire_path=fire,geo_path=geo,platform=pair.platform,when=when,bbox=MAGUINDANAO_EVALUATED['bbox'])
        if not result['ok']:
            failures.append({k:v for k,v in result.items() if k!='rows'});continue
        rows=[r for r in result['rows'] if land.covers(Point(r['center_lon'],r['center_lat']))]
        all_rows.extend(rows)
        sources.append({'fire_file':fire.name,'geo_file':geo.name,'pass_time_utc':pair.pass_time_utc,
                        'bytes_reused':fire.stat().st_size+geo.stat().st_size,
                        'fire_sha256':hashlib.sha256(fire.read_bytes()).hexdigest(),
                        'geo_sha256':hashlib.sha256(geo.read_bytes()).hexdigest()})
        if i%4==0 or i==len(pairs):pd.DataFrame(all_rows).to_parquet(cache,index=False)
        print(f'Processed cached pair {i}/{len(pairs)}: {fire.name}',flush=True)
    observations=defaultdict(list)
    for index,row in enumerate(all_rows):
        counts=json.loads(row['counts_json'])
        detected=sum(counts.get(k,0) for k in ['fire_low','fire_nominal','fire_high'])>0
        observations[(row['cell_id'],row['ph_date'])].append({
            'cell_id':row['cell_id'],'local_date':row['ph_date'],'platform':row['platform'],
            'eligible':row['visible_land_km2']>=12.5,'detected':detected,
            'visible_km2':row['visible_land_km2'],'hours_from_aqua':abs(row['local_hour']-13.5),
            'hotspot_pixel_count':row['qualifying_detection_count'],'source_index':index,
        })
    contributions=[]
    for group in observations.values():
        chosen=select_one(group)
        if not chosen:continue
        value=activity_value(chosen)
        if value is None:continue
        source=all_rows[chosen['source_index']]
        contributions.append({**source,'activity_value':value,'numerator':value,'denominator':1,
            'coverage_status':'usable','method':chosen['method'],'model_version':'aqua_observed_activity_v1',
            'selection_rule':chosen['rule'],'selected_method_context':serving.selected_method(),
            'model_applied':False,'date_basis':'Asia/Manila'})
    frame=pd.DataFrame(contributions).sort_values(['ph_date','cell_id'])
    frame.to_parquet(PACKAGE,index=False)
    # Preserve the legacy store payloads before replacing those cell-day keys.
    store=ObservationStore()
    backup=DATA_DIR/'observations/activity_before_coverage_repair.json'
    if not backup.exists():
        with _connect(store.path) as c:old=[dict(r) for r in c.execute('SELECT * FROM activity_cell_days')]
        backup.write_text(json.dumps(old,default=str))
    ensure_packaged_activity(store)
    report={'processed_at_utc':datetime.now(timezone.utc).isoformat(),'bbox':MAGUINDANAO_EVALUATED['bbox'],
        'cached_pairs_reprocessed':len(sources),'bytes_transferred':0,'bytes_reused':sum(x['bytes_reused'] for x in sources),
        'pass_rows':len(all_rows),'considered_cell_days':len(observations),'usable_square_days':len(frame),
        'aqua_active_square_days':int(frame.activity_value.sum()),'aqua_zero_square_days':int((frame.activity_value==0).sum()),
        'suomi_calibrated_square_days':0,'suomi_missing_inputs':'No Philippine VNP14IMG/VNP03IMG native mask/geolocation feature rows are processed. FIRMS points cannot replace them.',
        'frozen_harmonization_model':serving.selected_method(),'frozen_model_sha256':hashlib.sha256(serving.MODEL_PATH.read_bytes()).hexdigest(),
        'model_use':'Eligible Aqua supplies observed 0/1 under the frozen platform-selection rule; no model inference is needed for these rows. Suomi model was not applied without native features.',
        'processed_dates':sorted(frame.ph_date.unique().tolist()),'processed_cells':int(frame.cell_id.nunique()),
        'per_date':frame.groupby('ph_date').agg(numerator=('activity_value','sum'),denominator=('activity_value','size')).reset_index().to_dict('records'),
        'sources':sources,'failures':failures,'package_sha256':hashlib.sha256(PACKAGE.read_bytes()).hexdigest()}
    path=DATA_DIR/'metrics/philippines_burning_activity_processing.json'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['sources','per_date']},indent=2))
    return report


if __name__=='__main__':build()
