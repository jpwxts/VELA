from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from vela.ph_prediction import forecast,month
from vela.observation_store import ObservationStore,_connect

NOW=datetime(2026,11,15,2,0,tzinfo=timezone.utc)

def test_national_prior_is_computed_not_invented_and_has_own_f1(tmp_path):
    store=ObservationStore(tmp_path/'obs.sqlite'); archive=tmp_path/'issues.sqlite'
    for cid in ['2393:174','2334:368']:
        p=forecast(cid,now=NOW,store=store,archive_path=archive)
        assert p['status']=='issued'
        assert p['model_version']=='regional_seasonal_detection_rate'
        assert p['probability']==119/589
        assert p['probability_percent']==20.2
        assert p['experimental'] and not p['calibrated']
        assert p['evaluation']['test']['f1']==0.0
        assert p['evaluation']['test']['n']==1808
        assert p['evaluation']['run_id']=='ph_national_prior_audit_v1'
        assert p['method']['missing_inputs']
        assert p['input_provenance']['historical_record_count']==0
        assert p['polygon_probability'] is None
        assert datetime.fromisoformat(p['valid_interval']['end_manila'])-datetime.fromisoformat(p['valid_interval']['start_manila'])==timedelta(hours=24)
    with _connect(store.path) as c:
        assert c.execute('SELECT COUNT(*) FROM detections').fetchone()[0]==0


def test_issue_is_immutable_cached_and_history_never_backfills(tmp_path):
    store=ObservationStore(tmp_path/'obs.sqlite'); archive=tmp_path/'issues.sqlite'
    p=forecast('2393:174',now=NOW,store=store,archive_path=archive)
    cached=forecast('2393:174',now=NOW+timedelta(minutes=10),store=store,archive_path=archive)
    assert cached['issued_at_utc']==p['issued_at_utc']
    assert cached['issuance_kind']=='preserved_archive'
    future=forecast('2393:174','2026-11-20',now=NOW,store=store,archive_path=archive)
    assert future['probability_percent'] is None and future['status']=='upcoming'
    past=forecast('2393:174','2026-11-07',now=NOW,store=store,archive_path=archive)
    assert past['probability_percent'] is None
    rows=month('2393:174','2026-11',archive_path=archive,now=NOW)['days']
    assert len([r for r in rows if r.get('probability_percent') is not None])==1
    assert next(r for r in rows if r['date']=='2026-11-15')['probability_percent']==20.2


def test_outside_country_is_not_national_transfer(tmp_path):
    p=forecast('2100:200',now=NOW,archive_path=tmp_path/'issues.sqlite')
    assert p['status']=='unsupported'
    assert p['probability_percent'] is None


def test_missing_classifier_still_uses_the_audited_prior(tmp_path, monkeypatch):
    from vela import ph_prediction as serving
    selection, _, prior, audit, comparison = serving.model_artifacts('test')
    monkeypatch.setattr(serving, 'model_artifacts', lambda _: (selection, None, prior, audit, comparison))
    p=forecast('2334:368',now=NOW,store=ObservationStore(tmp_path/'obs.sqlite'),archive_path=tmp_path/'issues.sqlite')
    assert p['status']=='issued'
    assert p['evaluation']['test']['f1']==0
    assert 'classifier artifact' in ' '.join(p['method']['missing_inputs'])


def test_polygon_summary_defines_its_scope_without_an_any_event_probability(monkeypatch):
    from vela import ph_prediction as serving
    monkeypatch.setattr(serving, 'inputs', lambda: ({}, (0, None)))
    monkeypatch.setattr(serving, 'forecast', lambda cid, *args, **kwargs: {
        'probability':119/589, 'probability_percent':20.2, 'cell_id':cid,
    })
    p=serving.overlay([[123.95727,6.78538],[124.10909,6.78538],[124.10909,6.92485],[123.95727,6.92485]])
    assert p['polygon_probability'] is None
    assert p['summary']['forecast_squares']==len(p['cells'])>1
    assert abs(p['summary']['expected_heat_squares']-len(p['cells'])*119/589)<1e-10
    assert not p['summary']['partial']
    assert 'displayed squares only' in p['summary']['calculation']
