"""Small API timing samples, not population latency estimates.

Run in the vela environment: python -m scripts.measure_public_experience --output /tmp/timings.json
Use --combined for the compatibility endpoint that still includes weather.
The first sample is process-cold, not provider-cache-cold; caches are never erased.
"""
import argparse
import json
from time import perf_counter
from pathlib import Path
from statistics import median
import numpy as np
from fastapi.testclient import TestClient
from app.main import app
from datetime import datetime
from zoneinfo import ZoneInfo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='/tmp/vela-timings.json')
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--combined', action='store_true')
    args = parser.parse_args()
    today = datetime.now(ZoneInfo('Asia/Manila')).date().isoformat()
    ring = [[123.95727,6.78538],[124.10909,6.78538],[124.10909,6.92485],[123.95727,6.92485]]
    box = 'west=123.95727&south=6.78538&east=124.10909&north=6.92485'
    cases = [
        ('land', 'post', '/api/check-land', {'coordinates':ring, 'date':'2026-11-07', 'include_weather':args.combined, 'include_activity':args.combined}),
        ('weather', 'get', '/api/preparedness?' + box, None),
        ('forecast', 'get', f'/api/hotspot-forecast?cell_id=2397:180&issue_date={today}', None),
        ('forecast_manila', 'get', f'/api/hotspot-forecast?cell_id=2334:368&issue_date={today}', None),
        ('forecast_layer', 'post', '/api/hotspot-forecast/overlay', {'coordinates':ring,'issue_date':today}),
        ('history', 'post', '/api/history/month', {'coordinates':ring, 'year':2026, 'month':11}),
        ('chart', 'get', '/api/calendar?' + box + '&year=2026', None),
    ]
    client = TestClient(app)
    results = {'note':'Sample measurements through TestClient; first call process-cold, existing provider/store caches retained. Inspect feed statuses; failed external calls are not successful live benchmarks.', 'samples':{}}
    for name, method, url, body in cases:
        samples = []
        for _ in range(args.samples):
            t = perf_counter()
            response = getattr(client,method)(url, **({'json':body} if body else {}))
            samples.append(round((perf_counter()-t)*1000,2))
            response.raise_for_status()
            payload = response.json()
            if name == 'weather':
                results['weather_ok'] = payload.get('ok')
                results['weather_headline'] = payload.get('headline')
            if name == 'land':
                results['feed_statuses'] = {r['platform']:r['status'] for r in payload['heat']['feeds']}
                results.setdefault('firms_ms', []).append(payload.get('firms_timing',{}).get('elapsed_ms'))
                results['observed_readings'] = payload['heat']['inside_count']
                results['observed_areas'] = payload['heat']['hotspot_areas']['area_count']
            if name.startswith('forecast'):
                results.setdefault('forecasts',{})[name] = {key:payload.get(key) for key in ['status','model_version','model_hash','probability_percent','evaluation','summary']}
        results['samples'][name] = {'ms':samples, 'first_ms':samples[0], 'warm_median_ms':median(samples[1:] or samples), 'p50_ms':float(np.percentile(samples,50)), 'p95_ms':float(np.percentile(samples,95))}
        print(name, results['samples'][name], flush=True)
    Path(args.output).write_text(json.dumps(results,indent=2)+'\n')

if __name__ == '__main__':
    main()
