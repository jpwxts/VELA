"""Audit the frozen historical fallback without fitting or tuning.

Run: python -m scripts.evaluate_national_prior
This reuses the already-inspected v2.1 splits; it is not a new national holdout.
"""
import hashlib
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score, recall_score

from vela.settings import DATA_DIR


def main():
    relative = Path('data/models/philippines_hotspot_models/baseline_regional_seasonal_detection_rate.joblib')
    artifact = DATA_DIR / 'models' / 'philippines_hotspot_models' / relative.name
    rate = joblib.load(artifact)['global_rate']
    frame = pd.read_parquet(DATA_DIR / 'processed' / 'philippines_hotspot_cell_days.parquet')
    train = frame.loc[frame['split'] == 'train', 'label']
    assert rate == train.sum() / len(train), 'Frozen prior differs from training counts'
    out = {
        'run_id': 'ph_national_prior_audit_v1', 'model_name': 'regional_seasonal_detection_rate',
        'artifact': str(relative), 'model_hash': hashlib.sha256(artifact.read_bytes()).hexdigest()[:16],
        'protocol': 'Persisted global_rate fallback for an unseen season. Fixed artifact, no fitting or tuning. Existing already-inspected validation/test rows; not a fresh independent national holdout.',
        'probability': rate, 'numerator': int(train.sum()), 'denominator': len(train), 'threshold': 0.5,
        'target': 'At least one qualifying MODIS/VIIRS heat detection in a 5 km square during 24 hours; eligible negative labels require measured fire-mask coverage.',
        'splits': {},
    }
    for split in ['validation', 'test']:
        labels = frame.loc[frame['split'] == split, 'label'].to_numpy()
        probabilities = [rate] * len(labels)
        predictions = [int(rate >= 0.5)] * len(labels)
        out['splits'][split] = {
            'n': len(labels), 'positives': int(labels.sum()),
            'f1': f1_score(labels, predictions, zero_division=0),
            'recall': recall_score(labels, predictions, zero_division=0),
            'brier': brier_score_loss(labels, probabilities),
            'pr_auc': average_precision_score(labels, probabilities),
        }
    (DATA_DIR / 'metrics' / 'philippines_national_prior_audit.json').write_text(json.dumps(out, indent=2) + '\n')
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
