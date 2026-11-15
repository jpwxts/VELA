"""Explicit experimental Philippine serving; no inferred heat or clear-sky zeros.

The existing HGB is used only with measured local coverage and compatible
seasonal inputs. Otherwise its persisted historical prior supplies an explicitly
experimental estimate. An empty/failed FIRMS pull is never a coverage input.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo
from shapely.geometry import Point, shape
from shapely.prepared import prep

from vela.boundaries import geometry_from_preset, point_in_geometry, load_preset
from vela.grid import center, indices, geographic_bounds
from vela.hotspot_forecast import DATA_DIR, FEATURE_NAMES, load_selection, MAGUINDANAO_EVALUATED, STUDY
from vela.hotspot_forecast_serve import _load_model_bundle, _predict_probability, _eval_set
from vela.hotspot_forecast_dataset import build_feature_row, neighbor_ids, _parse_acq_utc
from vela.observation_store import ObservationStore, _connect

PH = ZoneInfo('Asia/Manila')
ARCHIVE = DATA_DIR / 'observations' / 'philippines_experimental_forecasts.sqlite'
PRIOR_REPORT = DATA_DIR / 'metrics' / 'philippines_national_prior_audit.json'
TARGET = 'At least one qualifying MODIS/VIIRS heat detection in this 5 km square during the next 24 hours.'

@lru_cache(maxsize=4)
def model_artifacts(version: str):
    import joblib
    selection = load_selection() or {}
    winner = comparison = prior = audit = None
    # Each path stands alone: a missing classifier must not disable a valid prior.
    try:
        candidate_path = Path(selection.get('model_artifact', ''))
        if not candidate_path.is_file(): candidate_path = DATA_DIR / 'models' / candidate_path.name
        if not candidate_path.is_file() or hashlib.sha256(candidate_path.read_bytes()).hexdigest()[:16] != selection.get('model_hash'):
            raise ValueError('Candidate artifact does not match its evaluated hash')
        comparison = json.loads((DATA_DIR / 'metrics' / 'philippines_hotspot_model_comparison.json').read_text())
        if comparison['model_hash'] != selection['model_hash'] or comparison['winner']['name'] != selection['chosen_model']:
            raise ValueError('Candidate does not match its evaluation run')
        winner = _load_model_bundle(selection)
    except (OSError, ValueError, KeyError):
        winner = None
    try:
        prior_path=DATA_DIR / 'models' / 'philippines_hotspot_models' / 'baseline_regional_seasonal_detection_rate.joblib'
        audit = json.loads(PRIOR_REPORT.read_text())
        if hashlib.sha256(prior_path.read_bytes()).hexdigest()[:16] != audit['model_hash']:
            raise ValueError('Prior artifact does not match its evaluated hash')
        prior = joblib.load(prior_path)
        if prior['global_rate'] != audit['numerator'] / audit['denominator'] or prior['global_rate'] != audit['probability']:
            raise ValueError('Prior rate does not match its audited historical counts')
    except (OSError, ValueError, KeyError):
        prior = audit = None
    if winner is None and prior is None:
        raise ValueError('Neither versioned classifier nor audited historical prior is usable')
    return selection, winner, prior, audit, comparison


def _archive(path=None):
    path = Path(path or ARCHIVE); path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path); c.row_factory = sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS issues (issue_key TEXT PRIMARY KEY, cell_id TEXT, ph_day TEXT, issued_at TEXT, payload TEXT)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_experimental_cell_day ON issues(cell_id, ph_day)')
    return c


@lru_cache(maxsize=4)
def _snapshot(path: str, signature: tuple):
    with _connect(Path(path)) as c:
        raw = c.execute('SELECT lat,lon,acq_date,acq_time,platform,retrieved_at FROM detections').fetchall()
    by_cell = {}
    for row in raw:
        item = dict(row); stamp = _parse_acq_utc(item)
        if stamp is None: continue
        x,y = indices(item['lon'], item['lat']); cid=f'{int(x)}:{int(y)}'
        item['_cell_id']=cid; item['_acq_utc']=stamp
        by_cell.setdefault(cid,[]).append(item)
    return by_cell


def inputs(store=None):
    store=store or ObservationStore()
    with _connect(store.path) as c:
        state=c.execute('SELECT COUNT(*),MAX(retrieved_at) FROM detections').fetchone()
    signature=(state[0],state[1])
    return _snapshot(str(store.path),signature), signature


@lru_cache(maxsize=2)
def coverage_snapshot(signature):
    import pandas as pd
    path=DATA_DIR / 'processed' / 'philippines_hotspot_coverage_cell_days.parquet'
    if not path.is_file(): return {}
    frame=pd.read_parquet(path)
    return {str(cid):set(group['ph_date'].astype(str).str[:10]) for cid,group in frame.loc[frame['label_support'].isin(['negative_supported','positive_candidate'])].groupby('cell_id')}


@lru_cache(maxsize=2)
def _prepared_preset(name):
    return prep(shape(geometry_from_preset(name)))


@lru_cache(maxsize=32768)
def _supported(cid):
    try:
        x,y=map(int,cid.split(':'));lon,lat=center(x,y)
        return _prepared_preset('philippines').covers(Point(lon,lat))
    except (ValueError,TypeError): return False


def _existing(cid,day,path=None):
    with _archive(path) as c:
        row=c.execute('SELECT payload FROM issues WHERE cell_id=? AND ph_day=? ORDER BY issued_at DESC LIMIT 1',(cid,day)).fetchone()
    return json.loads(row[0]) if row else None


def forecast(cell_id, issue_date=None, *, now=None, store=None, archive_path=None, snapshot=None):
    now=now or datetime.now(timezone.utc); today=now.astimezone(PH).date().isoformat()
    day=str(issue_date or today)[:10]
    base={'cell_id':cell_id,'product':'philippines_experimental_heat_24h','public_label':'Satellite heat in the next 24 hours',
          'probability':None,'probability_percent':None,'ph_today':today,'issue_date_ph':day,
          'target':TARGET,'experimental':True,'calibrated':False,'polygon_probability':None}
    if not _supported(cell_id): return {**base,'status':'unsupported','calendar_state':'unsupported_location','reason':'Outside the Philippine land boundary. Draw or select land in the Philippines.'}
    if day != today:
        existing=_existing(cell_id,day,archive_path) if day<today else None
        if existing: return {**existing,'issuance_kind':'preserved_archive'}
        return {**base,'status':'upcoming' if day>today else 'unavailable','calendar_state':'upcoming' if day>today else 'not_issued','reason':'No genuinely issued estimate is archived for this square and date.'}
    try:
        selection,bundle,prior,audit,comparison=model_artifacts((load_selection() or {}).get('model_hash',''))
    except (OSError,ValueError,KeyError) as exc:
        return {**base,'status':'unavailable','reason':'Missing model artifact or historical-prior audit. Restore the versioned model files and retry.'}
    data,signature=snapshot or inputs(store)
    key=hashlib.sha256(json.dumps([cell_id,now.strftime('%Y-%m-%dT%H'),signature,selection.get('model_hash'),(audit or {}).get('model_hash'),'national_v1']).encode()).hexdigest()
    with _archive(archive_path) as c:
        row=c.execute('SELECT payload FROM issues WHERE issue_key=?',(key,)).fetchone()
    if row: return {**json.loads(row[0]),'issuance_kind':'preserved_archive'}
    available=[r for cid in [cell_id,*neighbor_ids(cell_id)] for r in data.get(cid,[]) if r['_acq_utc']<now and r['retrieved_at']<=now.isoformat()]
    covpath=DATA_DIR / 'processed' / 'philippines_hotspot_coverage_cell_days.parquet'
    coverage=coverage_snapshot(covpath.stat().st_mtime_ns if covpath.exists() else 0)
    local_days=coverage.get(cell_id,set())
    recent_days={(now.astimezone(PH).date()-timedelta(days=i)).isoformat() for i in range(1,8)}
    missing=[]
    if not recent_days.issubset(local_days): missing.append('Seven days of measured local fire-mask/geolocation coverage')
    if now.astimezone(PH).month not in {2,3,8}: missing.append('Season within the evaluated February/March/August distribution')
    if bundle is None: missing.append('Hash-verified classifier artifact and its matching evaluation run')
    features=None
    if not missing and bundle:
        # Preserve the artifact's study-wide proxy definitions. Local measured
        # coverage above is an additional serving gate, not a replacement feature.
        box=STUDY['bbox'];nearby={cell_id,*neighbor_ids(cell_id)}
        feature_detections=[r for rows in data.values() for r in rows
            if r['_acq_utc']<now and r['retrieved_at']<=now.isoformat()
            and (r['_cell_id'] in nearby or (box['west']<=r['lon']<=box['east'] and box['south']<=r['lat']<=box['north']))]
        regional_days=set().union(*coverage.values()) if coverage else set()
        features=build_feature_row(cell_id=cell_id,issue_date_ph=today,detections=feature_detections,coverage_days=regional_days)
        if any(features.get(name) is None or not math.isfinite(float(features[name])) for name in FEATURE_NAMES): missing.append('Complete issue-time history for every frozen model feature')
    if missing or bundle is None:
        if prior is None:
            return {**base,'status':'unavailable','reason':f"Missing: {'; '.join(missing)}. The audited historical-prior artifact is also missing. Restore the versioned inputs, then retry."}
        probability=float(prior['global_rate']); model='regional_seasonal_detection_rate'; model_hash=audit['model_hash']
        metrics={'run_id':audit['run_id'],'validation':audit['splits']['validation'],'test':audit['splits']['test'],'threshold':audit['threshold']}
        method={'kind':'historical_prior','numerator':audit['numerator'],'denominator':audit['denominator'],
                'formula':f"{audit['numerator']} qualifying positive training square-days / {audit['denominator']} eligible training square-days",
                'missing_inputs':missing,'assumptions':'Transfer of the covered-day training event rate; no current clear-view coverage is assumed. No local heat detections are imputed.',
                'f1_limit':'At threshold 0.5 this constant prior predicts no positives, so F1 is 0. It is a base rate, not a locally discriminating model.'}
    else:
        probability=_predict_probability(bundle,features);model=selection['chosen_model'];model_hash=selection['model_hash']
        metrics={'run_id':comparison['data_version'],'validation':comparison['winner']['validation_metrics'],'test':comparison['holdout']['metrics'],'threshold':selection['threshold']}
        method={'kind':'classifier','features':features,'missing_inputs':[], 'assumptions':'Frozen HGB uses midnight-history features, including study-wide detection-time and coverage-date proxies, not local clear-pass measurements. Transfer to a rolling 24-hour issue and national geography is experimental; calibration remains unvalidated.'}
    regional=cell_id in _eval_set()
    payload={**base,'status':'issued','calendar_state':'forecast_available','probability':probability,'probability_percent':round(probability*100,1),
        'model_version':model,'model_hash':model_hash,'evaluation':metrics,'method':method,'issued_at_utc':now.isoformat(),
        'issue_time_manila':now.astimezone(PH).isoformat(),'valid_interval':{'start_manila':now.astimezone(PH).isoformat(),'end_manila':(now+timedelta(hours=24)).astimezone(PH).isoformat()},
        'issuance_kind':'newly_issued','release_tier':'experimental','scope':{'serving':'Philippine land squares','evaluated':MAGUINDANAO_EVALUATED['label'],'in_evaluated_geography':regional},
        'input_provenance':{'historical_record_count':len(available),'latest_local_record_utc':max((r['_acq_utc'].isoformat() for r in available if r['_cell_id']==cell_id),default=None),'clear_view_coverage':'measured_history' if recent_days.issubset(local_days) else 'unknown','data_watermark':signature[1]},
        'limitation':'Experimental estimate. Not calibrated for national transfer or the current coverage/season; not a wildfire probability.'}
    with _archive(archive_path) as c:
        c.execute('INSERT OR IGNORE INTO issues VALUES (?,?,?,?,?)',(key,cell_id,today,now.isoformat(),json.dumps(payload)));c.commit()
        stored=c.execute('SELECT payload FROM issues WHERE issue_key=?',(key,)).fetchone()
    return json.loads(stored[0])


def month(cell_id,year_month, *, archive_path=None, now=None):
    from calendar import monthrange
    year,number=map(int,year_month.split('-'));today=(now or datetime.now(PH)).astimezone(PH).date().isoformat()
    with _archive(archive_path) as c:
        rows=c.execute('SELECT payload FROM issues WHERE cell_id=? AND ph_day LIKE ? ORDER BY issued_at',(cell_id,year_month+'%')).fetchall()
    issued={json.loads(r[0])['issue_date_ph']:json.loads(r[0]) for r in rows}
    return {'cell_id':cell_id,'year_month':year_month,'ph_today':today,'days':[
        {**issued[day], 'date':day,'issuance_kind':'preserved_archive'} if day in issued else
        {'date':day,'probability_percent':None,'calendar_state':'upcoming' if day>today else 'not_issued','issuance_kind':None}
        for i in range(1,monthrange(year,number)[1]+1) for day in [f'{year_month}-{i:02d}']]}


def overlay(ring, issue_date=None, boundary_preset=None, limit=256):
    from vela.land_check import normalize_ring,polygon_bbox,point_in_ring
    if boundary_preset:
        preset=load_preset(boundary_preset);box=preset['bbox'];geometry=preset['geometry']
        prepared_geometry = _prepared_preset(boundary_preset)
        west,south,east,north=[box[k] for k in ['west','south','east','north']]
    else:
        ring=normalize_ring(ring);west,south,east,north=polygon_bbox(ring);geometry=None
    # Restrict iteration to the country before enumerating squares.
    west=max(west,116);east=min(east,127);south=max(south,4);north=min(north,22)
    if west>=east or south>=north:return {'status':'unsupported','cells':[],'polygon_probability':None}
    x0,y0=indices(west,south);x1,y1=indices(east,north);cells=[]
    for x in range(int(x0),int(x1)+1):
        for y in range(int(y0),int(y1)+1):
            cid=f'{x}:{y}';lon,lat=center(x,y)
            if (prepared_geometry.covers(Point(lon,lat)) if geometry else point_in_ring(lon,lat,ring)) and _supported(cid): cells.append((cid,lon,lat))
    total=len(cells)
    if total>limit:
        # Deterministic spatial sample; report the partial scope, never imply full-land coverage.
        cells=[cells[round(i*(total-1)/(limit-1))] for i in range(limit)]
    snapshot=inputs();now=datetime.now(timezone.utc);rows=[];first_issue=None;unavailable_reason=None
    for cid,lon,lat in cells:
        issue=forecast(cid,issue_date,now=now,snapshot=snapshot)
        if issue['probability'] is None:
            unavailable_reason=unavailable_reason or issue.get('reason')
            continue
        if first_issue is None:first_issue=issue
        w,s,e,n=geographic_bounds(*map(int,cid.split(':')))
        rows.append({'cell_id':cid,'center':{'lon':lon,'lat':lat},'bounds':{'west':w,'south':s,'east':e,'north':n},'probability':issue['probability'],'probability_percent':issue['probability_percent'],'issuance_kind':'preserved_archive','experimental':True})
    values=[r['probability'] for r in rows]
    return {'status':'ok' if rows else 'unavailable','reason':unavailable_reason if rows else unavailable_reason or 'No Philippine 5 km square centers inside this boundary. Select a land square or expand the boundary.', 'cells':rows,'representative_issue':first_issue,'issue_date_ph':now.astimezone(PH).date().isoformat(),'polygon_probability':None,
        'summary':{'forecast_squares':len(rows),'eligible_land_squares':total,'partial':total>limit or len(rows)<total,'min_percent':min(values)*100 if values else None,'max_percent':max(values)*100 if values else None,'expected_heat_squares':sum(values) if values else None,'calculation':'Sum of per-square estimates for the displayed squares only; expected count, not probability of any fire or heat event anywhere in the polygon.'},
        'extent':{'west':west,'south':south,'east':east,'north':north},'note':f'Experimental estimates. {len(rows)} of {total} Philippine land squares shown. Draw a smaller boundary to forecast every square.'}
