"""Leakage, reproducibility and inspectable neural perception contracts."""
import numpy as np
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ares.neural import FEATURES, LABELS, NeuralPerception, generate_training_data


@pytest.fixture(scope='module')
def fitted():
    model = NeuralPerception(seed=17)
    model.train(map_count=12, samples_per_map=100)
    return model


def test_synthetic_truth_and_group_separation(fitted):
    data = generate_training_data(seed=17, map_count=12, samples_per_map=100)
    assert set(data['y']) == set(LABELS)
    assert data['X'].shape == (1200, len(FEATURES))
    assert np.isfinite(data['X']).all()
    assert 'cliff' not in FEATURES
    assert len(np.unique(data['X'][:, 0])) > 100
    splits = fitted.split_indices_
    groups = [set(data['groups'][splits[key]]) for key in ('train', 'validation', 'test')]
    assert not groups[0] & groups[1] and not groups[0] & groups[2] and not groups[1] & groups[2]
    assert set.union(*groups) == set(data['groups'])
    np.testing.assert_allclose(fitted.scaler.mean_, data['X'][splits['train']].mean(axis=0))
    assert fitted.scaler.n_samples_seen_ == len(splits['train'])
    assert not np.allclose(fitted.scaler.mean_, data['X'].mean(axis=0))
    assert fitted.model.hidden_layer_sizes == (32, 16)
    assert fitted.model.activation == 'relu'
    assert fitted.model.out_activation_ == 'softmax'
    assert fitted.model.early_stopping is False


def test_probability_trace_confidence_and_actual_network(fitted):
    row = dict(distance=9., slope=4., elevation_delta=1., texture=.2, visibility=.8, vibration=.1)
    result = fitted.predict(row)
    probabilities = list(result['probabilities'].values())
    assert list(result['probabilities']) == list(LABELS)
    assert np.isfinite(probabilities).all() and sum(probabilities) == pytest.approx(1.)
    assert result['confidence'] == max(probabilities)
    assert result['low_confidence'] == (result['confidence'] < fitted.confidence_threshold)
    assert 0 <= result['risk'] <= 1
    transformed = fitted.scaler.transform([[row[key] for key in FEATURES]])
    np.testing.assert_allclose(result['normalized_input'], transformed[0])
    direct = fitted.model.predict_proba(transformed)[0]
    for label, probability in zip(fitted.model.classes_, direct):
        assert result['probabilities'][label] == pytest.approx(probability)
    assert [layer['neurons'] for layer in result['activation_summaries']] == [32, 16]
    assert all(0 <= layer['active_fraction'] <= 1 for layer in result['activation_summaries'])
    old_threshold = fitted.confidence_threshold
    fitted.confidence_threshold = 1.
    try:
        assert fitted.predict(row)['low_confidence']
    finally:
        fitted.confidence_threshold = old_threshold


def test_metrics_are_heldout_and_have_calibration(fitted):
    for split in ('validation', 'test'):
        metrics = fitted.report_[split]
        assert np.asarray(metrics['confusion_matrix']).shape == (3, 3)
        assert np.asarray(metrics['confusion_matrix']).sum() == metrics['samples']
        for key in ('accuracy', 'majority_baseline', 'macro_f1', 'barranco_recall', 'calibration_error'):
            assert 0 <= metrics[key] <= 1
        assert metrics['macro_f1'] > .65
        assert metrics['accuracy'] > metrics['majority_baseline']
    assert fitted.operational_label == 'supuesto de simulación'


def test_deterministic_data_training_and_predictions(fitted):
    other = NeuralPerception(seed=17)
    other.train(map_count=12, samples_per_map=100)
    row = [8., 3., -1., .4, .8, .05]
    assert other.predict(row) == fitted.predict(row)
    assert other.report_ == fitted.report_


@pytest.mark.parametrize('value', [None, [], [1] * 5, [np.nan] * 6,
    [np.inf] * 6, [0., 3., 0., .5, 1., 0.], [21., 3., 0., .5, 1., 0.],
    [1e308] * 6, {}, {'distance': 4.}, ['x'] * 6])
def test_invalid_input_is_rejected(fitted, value):
    with pytest.raises(ValueError, match='Entrada|sensor'):
        fitted.predict(value)


def test_untrained_and_invalid_configuration():
    with pytest.raises(ValueError, match='entren'):
        NeuralPerception().predict([8., 3., -1., .4, .8, .05])
    for threshold in (np.nan, 0, 1.1, 'x'):
        with pytest.raises(ValueError, match='confianza'):
            NeuralPerception(confidence_threshold=threshold)
    with pytest.raises(ValueError, match='mapas'):
        generate_training_data(map_count=2)


def test_invalid_training_data_rejected():
    data = generate_training_data(seed=3, map_count=8, samples_per_map=40)
    data['X'][0, 0] = np.nan
    with pytest.raises(ValueError, match='Entrada|datos'):
        NeuralPerception().train(data)
