"""The packaged native-mask contributions must reach daily/weekly/monthly UI APIs."""
from datetime import date
import pandas as pd
import pytest
from vela import activity_store as activity
from vela.observation_store import ObservationStore
from vela.history import build_monthly_history

RING=[[123.6,6.3],[124.7,6.3],[124.7,7.4],[123.6,7.4],[123.6,6.3]]


def test_packaged_native_aqua_reaches_all_periods(tmp_path, monkeypatch):
    store=ObservationStore(tmp_path/'activity.sqlite')
    activity.ensure_packaged_activity(store)
    monkeypatch.setattr(activity,'ObservationStore',lambda:store)
    frame=pd.read_parquet(activity.PACKAGE)
    assert len(frame)==2458
    assert frame.activity_value.sum()==35
    assert set(frame.platform)=={'Aqua'}
    assert not frame.model_applied.any()
    result=activity.selection(RING,'2024-03-11')
    assert result['activity_numerator']==21
    assert result['activity_denominator']==309
    assert result['activity_rate']==pytest.approx(21/309)
    assert len(result['cells'])==309
    assert sum(c['activity_value'] for c in result['cells'])==21
    assert all(c['fire_file'].startswith('MYD14.') for c in result['cells'])
    assert activity.selection(RING,'2024-03-09')['activity_rate']==0
    assert activity.selection(RING,'2024-03-02')['activity_rate'] is None
    assert activity.selection(RING,'2024-03-11',today=date(2024,3,10))['activity_rate'] is None
    history=build_monthly_history(RING,2024,3)
    march=history['months'][2]
    assert (march['activity_numerator'],march['activity_denominator'],march['usable_days'])==(28,1209,7)
    assert march['activity_rate']==pytest.approx(28/1209)
    for week in history['weeks']:
        rows=frame[frame.ph_date.between(week['period_start'],week['period_end'])]
        assert week['activity_denominator']==(len(rows) or None)
        if len(rows): assert week['activity_rate']==pytest.approx(rows.activity_value.sum()/len(rows))
    for month in history['months']:
        rows=frame[frame.ph_date.str.startswith(month['month'])]
        assert month['activity_denominator']==(len(rows) or None)
        if len(rows): assert month['activity_rate']==pytest.approx(rows.activity_value.sum()/len(rows))


def test_new_cell_day_invalidates_cache_without_creating_missing_zero(tmp_path,monkeypatch):
    monkeypatch.setattr(activity,'PACKAGE',tmp_path/'absent.parquet')
    store=ObservationStore(tmp_path/'test.sqlite')
    empty=activity.selection(RING,'2024-03-11',store=store)
    row={'cell_id':'2393:174','ph_date':'2024-03-11','platform':'Aqua','method':'observed Aqua activity','coverage_status':'usable','activity_value':0}
    store.upsert_activity_rows([row])
    zero=activity.selection(RING,'2024-03-11',store=store)
    assert zero['data_version']!=empty['data_version']
    assert zero['clear_zero'] and zero['activity_denominator']==1
    store.upsert_activity_rows([{**row,'activity_value':1}])
    active=activity.selection(RING,'2024-03-11',store=store)
    assert active['data_version']!=zero['data_version']
    assert active['activity_rate']==1
    store.upsert_activity_rows([{**row,'method':'hotspot_points_only'}])
    assert activity.selection(RING,'2024-03-11',store=store)['activity_rate'] is None


def test_activity_endpoint_rejects_invalid_dates_and_boundaries():
    from fastapi.testclient import TestClient
    from app.main import app
    client=TestClient(app)
    assert client.post('/api/activity/selection',json={'coordinates':RING,'date':'wrong'}).status_code==400
    assert client.post('/api/activity/selection',json={'coordinates':[[0,0],[1,1],[2,2]],'date':'2024-03-11'}).status_code==400


def test_ph_calendar_groups_two_utc_pass_dates_as_one_square():
    from vela.hotspot_areas import group_hotspot_areas
    a={'lat':6.85,'lon':124.05,'platform':'Aqua','acq_date':'2024-03-10','acq_time':'17:00'}
    b={**a,'acq_date':'2024-03-11','acq_time':'05:35'}
    payload={'date':'2024-03-11','ph_day':'2024-03-11','results':[{'hotspots':[a,b]}]}
    assert group_hotspot_areas(payload)['area_count']==1
    del payload['ph_day']
    assert group_hotspot_areas(payload)['area_count']==2 # existing UTC snapshot contract
