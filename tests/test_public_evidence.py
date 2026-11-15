"""Public evidence boundaries: missing coverage, failed feeds and archived scores."""
from fastapi.testclient import TestClient
from app import main
from vela.land_check import classify_detections, normalize_ring
from vela.hotspot_forecast_serve import forecast_for_cell, month_forecasts_for_cell

RING = normalize_ring([[123.95727, 6.78538], [124.10909, 6.78538],
                       [124.10909, 6.92485], [123.95727, 6.92485]])


def test_suspended_policy_also_blocks_preserved_mixed_model_archives():
    for cid in ['2393:174', '2397:180']:
        issue = forecast_for_cell(cell_id=cid, issue_date_ph='2026-11-07')
        assert issue['probability'] is None
        assert issue['probability_percent'] is None
        assert issue['issuance_kind'] is None
        assert 'Calibration' in issue['reason']
    month = month_forecasts_for_cell('2393:174', '2026-11', ph_today='2026-11-15')
    assert all(row.get('probability_percent') is None for row in month['days'])
    assert all(row.get('issuance_kind') is None for row in month['days'])


def test_failed_feed_is_not_a_measured_empty_search():
    failed = classify_detections({'results': [{'platform': 'Aqua', 'status': 'request_failed', 'hotspots': []}]}, RING)
    assert failed['status'] == 'unavailable'
    assert not failed['search_complete']
    assert failed['failed_feeds'] == ['Aqua']
    assert 'No satellite heat readings returned' not in failed['lead']
    empty = classify_detections({'results': [{'platform': 'Aqua', 'status': 'no_hotspots', 'hotspots': []}]}, RING)
    assert empty['status'] == 'none_unknown'
    assert empty['search_complete']
    assert 'Clear-view coverage is unknown' in empty['lead']


def test_heat_only_endpoint_never_calls_weather(monkeypatch, tmp_path):
    from vela.observation_store import ObservationStore
    isolated = ObservationStore(tmp_path / "observations.sqlite")
    monkeypatch.setattr("vela.observation_store.ObservationStore", lambda: isolated)
    def forbidden(*args, **kwargs):
        raise AssertionError('weather gated heat')
    monkeypatch.setattr(main, 'build_forecast', forbidden)
    monkeypatch.setattr('vela.firms_day.fetch_firms_for_ph_day', lambda *args, **kwargs: {
        'results': [{'platform': 'Aqua', 'status': 'no_hotspots', 'hotspots': [], 'coverage': 'unknown'}]})
    response = TestClient(main.app).post('/api/check-land', json={
        'coordinates': RING, 'date': '2026-11-07', 'include_weather': False})
    assert response.status_code == 200
    payload = response.json()
    assert payload['heat']['search_complete']
    assert payload['heat']['inside_count'] == 0
    assert payload['activity']['activity_rate'] is None
    assert 'fire-mask' in payload['activity']['missing_input']


def test_snapshot_counts_and_pass_times_agree():
    payload = TestClient(main.app).get('/api/public/philippines/2026-11-07?region=mindanao').json()
    assert payload['saved'] and payload['public_snapshot']
    assert payload['heat']['inside_count'] == 12
    assert payload['heat']['hotspot_areas']['area_count'] == 11
    assert len(payload['heat']['platforms_inside']) == 3
    assert '+08:00' in payload['heat']['latest_pass_ph']
    areas = {row['cell_id']: row for row in payload['heat']['hotspot_areas']['areas']}
    for cid in ['2393:174', '2397:180']:
        assert len(areas[cid]['members']) == 1
        assert areas[cid]['members'][0]['platform'] == 'NOAA-21'


def test_public_issues_must_match_model_and_precede_window():
    from vela.hotspot_forecast_serve import _timely_selected_issue
    selection = {'model_hash':'approved-hash','chosen_model':'candidate'}
    row = {'model_hash':'approved-hash','model_version':'candidate',
           'issued_at_utc':'2026-11-06T15:59:00Z', 'probability':0.25}
    assert _timely_selected_issue(row, selection, '2026-11-07')
    assert not _timely_selected_issue({**row,'model_hash':'old-hash'}, selection, '2026-11-07')
    assert not _timely_selected_issue({**row,'issued_at_utc':'2026-11-14T13:43:56Z'}, selection, '2026-11-07')
    assert not _timely_selected_issue({**row,'historical_simulation':True}, selection, '2026-11-07')
    assert not _timely_selected_issue({**row,'probability':float('nan')}, selection, '2026-11-07')


def test_square_check_uses_same_philippine_day_path(monkeypatch):
    calls = []
    def fetch(*args, **kwargs):
        calls.append(args[2])
        return {'results': []}
    monkeypatch.setattr('vela.firms_day.fetch_firms_for_ph_day', fetch)
    response = TestClient(main.app).post('/api/observation-ask', json={
        'west':123.95727,'south':6.78538,'east':124.10909,'north':6.92485,
        'lat':6.85779,'lon':124.05852,'date':'2026-11-07','platforms':['NOAA-21']})
    assert response.status_code == 200
    assert calls == ['2026-11-07']
    assert response.json()['kind'] == 'unknown'


def test_named_mindanao_scope_reaches_both_land_and_history(monkeypatch, tmp_path):
    from vela.observation_store import ObservationStore
    isolated = ObservationStore(tmp_path / 'observations.sqlite')
    monkeypatch.setattr('vela.observation_store.ObservationStore', lambda: isolated)
    monkeypatch.setattr('vela.firms_day.fetch_firms_for_ph_day', lambda *args, **kwargs: {'results':[]})
    response = TestClient(main.app).post('/api/check-land', json={
        'coordinates':RING,'date':'2026-11-07','include_weather':False,'boundary_preset':'mindanao'})
    assert response.status_code == 200
    assert response.json()['bbox']['west'] < 118
    captured = []
    def history(*args, **kwargs):
        captured.append(kwargs['geometry'])
        return {'days':[]}
    monkeypatch.setattr(main, 'build_monthly_history', history)
    response = TestClient(main.app).post('/api/history/month', json={
        'coordinates':RING,'year':2026,'month':11,'boundary_preset':'mindanao'})
    assert response.status_code == 200
    assert captured[0]['type'] == 'MultiPolygon'


def test_fast_heat_response_does_not_process_coverage(monkeypatch, tmp_path):
    from vela.observation_store import ObservationStore
    isolated = ObservationStore(tmp_path / 'observations.sqlite')
    monkeypatch.setattr('vela.observation_store.ObservationStore', lambda: isolated)
    monkeypatch.setattr('vela.firms_day.fetch_firms_for_ph_day', lambda *args, **kwargs: {'results':[]})
    def forbidden(*args, **kwargs):
        raise AssertionError('coverage processing gated heat')
    monkeypatch.setattr('vela.history.build_monthly_history', forbidden)
    response = TestClient(main.app).post('/api/check-land', json={
        'coordinates':RING, 'date':'2026-11-07', 'include_weather':False, 'include_activity':False})
    assert response.status_code == 200
    assert response.json()['activity']['status'] == 'loading'


def test_policy_does_not_promote_hotspot_as_wildfire():
    policy = TestClient(main.app).get('/api/status').json()['prediction']
    assert policy['wildfire_validated'] is False
    assert policy['calibrated'] is False
    assert policy['approved'] is False
    assert 'Satellite-detected heat' in policy['target']


def test_point_prediction_does_not_query_heat_or_weather(monkeypatch):
    monkeypatch.setattr(main, 'build_forecast', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('weather called')))
    response = TestClient(main.app).get('/api/hotspot-forecast/point?lat=6.85779&lon=124.05852&issue_date=2026-11-07')
    assert response.status_code == 200
    assert response.json()['cell_id'] == '2393:174'
    assert response.json()['probability_percent'] is None
    assert TestClient(main.app).get('/api/hotspot-forecast/point?lat=91&lon=124').status_code == 422
