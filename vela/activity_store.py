"""Coverage-backed activity from the same durable cell-day store as History.

Only observed Aqua or the frozen calibrated Suomi-NPP method can contribute.
FIRMS queries and the next-day heat classifier never create coverage or values.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from vela.observation_store import ObservationStore, _connect
from vela.settings import DATA_DIR
from vela.grid import center, geographic_bounds

PACKAGE = DATA_DIR / 'processed' / 'philippines_burning_activity.parquet'
ELIGIBLE_SQL = "((platform='Aqua' AND method='observed Aqua activity') OR (platform='Suomi-NPP' AND method='calibrated VIIRS estimate')) AND coverage_status IN ('usable','ok','adequate') AND activity_value IS NOT NULL"
PH = ZoneInfo('Asia/Manila')


def ensure_packaged_activity(store=None):
    store = store or ObservationStore()
    if not PACKAGE.is_file(): return
    version = f'{PACKAGE.stat().st_mtime_ns}:{PACKAGE.stat().st_size}'
    with _connect(store.path) as c:
        saved = c.execute("SELECT value_json FROM checkpoints WHERE name='burning_activity_package'").fetchone()
    if saved and json.loads(saved[0]).get('version') == version: return
    import pandas as pd
    rows = pd.read_parquet(PACKAGE).to_dict('records')
    for i in range(0, len(rows), 500): store.upsert_activity_rows(rows[i:i+500])
    with _connect(store.path) as c:
        c.execute("INSERT OR REPLACE INTO checkpoints(name,value_json,updated_at) VALUES(?,?,?)",
                  ('burning_activity_package',json.dumps({'version':version}),datetime.now(PH).isoformat()))
        c.commit()


def data_version(store=None):
    store = store or ObservationStore()
    ensure_packaged_activity(store)
    with _connect(store.path) as c:
        row = c.execute(f'SELECT COUNT(*),MAX(processed_at) FROM activity_cell_days WHERE {ELIGIBLE_SQL}').fetchone()
    return (str(store.path), row[0], row[1])


@lru_cache(maxsize=4)
def _records(version):
    with _connect(Path(version[0])) as c:
        rows=c.execute(f'SELECT * FROM activity_cell_days WHERE {ELIGIBLE_SQL}').fetchall()
    out=[]
    for row in rows:
        item={**json.loads(row['payload_json'] or '{}'),**dict(row)}
        item.pop('payload_json',None)
        lon,lat=center(*map(int,item['cell_id'].split(':')))
        item.update(center_lon=lon,center_lat=lat)
        item['numerator']=float(item['activity_value'])
        item['denominator']=1
        out.append(item)
    return out


@lru_cache(maxsize=128)
def _selection(version, ring_json, geometry_json):
    from shapely.geometry import Point, shape, Polygon
    from shapely.prepared import prep
    geometry=json.loads(geometry_json) if geometry_json else None
    prepared=prep(shape(geometry) if geometry else Polygon(json.loads(ring_json)))
    return tuple(row for row in _records(version) if prepared.covers(Point(row['center_lon'],row['center_lat'])))


def selected_rows(ring, geometry=None, store=None):
    version=data_version(store)
    rows=_selection(version,json.dumps(ring),json.dumps(geometry,sort_keys=True) if geometry else '')
    return rows, hashlib.sha256(repr(version).encode()).hexdigest()[:16]


def aggregate(rows, *, expected_days=None):
    rows=list(rows)
    denominator=len(rows)
    numerator=sum(float(row['activity_value']) for row in rows)
    days={str(row['ph_date'])[:10] for row in rows}
    methods=Counter(row['method'] for row in rows)
    return {
        'activity_rate':numerator/denominator if denominator else None,
        'activity_numerator':numerator if denominator else None,
        'activity_denominator':denominator or None,
        'usable_days':len(days),'days_with_estimates':len(days),
        'activity_status':'partial' if denominator else 'not_processed',
        'clear_zero':bool(denominator and numerator==0),
        'method_counts':dict(methods),
        'satellites':sorted({row['platform'] for row in rows}),
        'source_products':sorted({str(row[key]) for row in rows for key in ('fire_file','geo_file') if row.get(key)}),
        'observation_times_utc':sorted({row['pass_time_utc'] for row in rows if row.get('pass_time_utc')}),
        'aqua_contributions':methods.get('observed Aqua activity',0),
        'suomi_contributions':methods.get('calibrated VIIRS estimate',0),
        'scope_note':'Share of adequately observed 5 km squares showing burning activity. Denominator includes only usable square-days; spatial/time coverage is partial.',
    }


def selection(ring, ph_date, geometry=None, store=None, today=None):
    today=today or datetime.now(PH).date()
    day=str(ph_date)[:10]
    rows,version=selected_rows(ring,geometry,store)
    chosen=[row for row in rows if row['ph_date']==day and day<=today.isoformat()]
    summary=aggregate(chosen)
    cells=[]
    for row in chosen:
        w,s,e,n=geographic_bounds(*map(int,row['cell_id'].split(':')))
        cells.append({**row,'bounds':{'west':w,'south':s,'east':e,'north':n}})
    reason=None
    if not chosen:
        reason='No adequately observed Aqua cell-days or complete calibrated Suomi-NPP inputs are processed for this boundary and date. FIRMS heat points cannot supply this denominator.'
    if day>today.isoformat():
        summary['activity_status']='future';reason='Future day: no observed burning activity exists yet.'
    return {**summary,'date':day,'status':'ok' if chosen else summary['activity_status'],'reason':reason,
            'data_version':version,'cells':cells,'processed_dates':sorted({row['ph_date'] for row in rows}),
            'date_basis':'Asia/Manila','target':'Observed or Aqua-comparable activity on the selected date; not next-day heat probability or wildfire probability.'}


def fill_history(days, ring, geometry=None):
    rows,version=selected_rows(ring,geometry)
    by_day={}
    for row in rows: by_day.setdefault(row['ph_date'],[]).append(row)
    for entry in days:
        if entry.get('activity_status')=='future':continue
        items=by_day.get(entry['date'],[])
        if items and entry.get('activity_rate') is None:
            entry.update(aggregate(items))
            entry['eligible_cell_days']=len(items)
            entry['estimated_cell_days']=len(items)
            entry['activity_source']='eligible_aqua_suomi_store'
        if entry.get('activity_rate') is not None:
            entry['activity_numerator']=entry['activity_rate']*entry['activity_denominator']
            entry['usable_days']=1
    return version


def aggregate_days(days):
    valid=[row for row in days if row.get('activity_rate') is not None and row.get('activity_denominator')]
    denominator=sum(row['activity_denominator'] for row in valid)
    numerator=sum(row.get('activity_numerator',row['activity_rate']*row['activity_denominator']) for row in valid)
    methods=Counter()
    for row in valid:methods.update(row.get('method_counts') or {})
    return {'activity_rate':numerator/denominator if denominator else None,
            'activity_numerator':numerator if denominator else None,'activity_denominator':denominator or None,
            'usable_days':len(valid),'days_with_estimates':len(valid),'method_counts':dict(methods),
            'aqua_contributions':methods.get('observed Aqua activity',0),'suomi_contributions':methods.get('calibrated VIIRS estimate',0),
            'activity_status':'partial' if denominator else 'future' if all(row.get('activity_status')=='future' for row in days) else 'not_processed',
            'clear_zero':bool(denominator and numerator==0)}
