"""Inspectable CPU perception trained on noisy, map-separated synthetic data.

Ground truth is a simulator property: cliff membership or a physical drop below
-5 m takes precedence over obstacle membership. Neither membership nor the
deterministic edge flag is passed to the MLP. Observations are noisy proxies;
confidence is not a safety guarantee and never replaces the edge-sensor veto.
"""
from collections.abc import Mapping
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

from .planet import ASSUMPTION, PlanetProfile
from .sensors import SensorSuite
from .world import World


FEATURES = ('distance', 'slope', 'elevation_delta', 'texture', 'visibility', 'vibration')
LABELS = ('libre', 'obstaculo', 'barranco')
BOUNDS = ((.000001, 20.), (0., 45.), (-1e6, 1e6), (0., 1.), (0., 1.), (0., 20.))


def _integer(value, minimum, message):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(message)
    return int(value)


def _matrix(values):
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('Entrada de sensores inválida: se requieren números finitos') from error
    if array.ndim != 2 or array.shape[1] != len(FEATURES) or not len(array) or not np.isfinite(array).all():
        raise ValueError('Entrada de sensores inválida: se requieren seis valores finitos')
    lower, upper = np.asarray(BOUNDS).T
    if np.any(array < lower) or np.any(array > upper):
        raise ValueError('Entrada de sensores fuera de rango físico; distancia cero requiere frenado')
    return array


def generate_training_data(seed=0, map_count=18, samples_per_map=120):
    """Generate map-grouped observations with simulator-owned terrain labels.

    Distance, slope, elevation and texture include observation noise and map
    biases. Cliffs are added as synthetic simulator terrain (not sensor labels).
    Distances below sensor resolution are represented as a small positive
    return here; a literal zero from the live sensor is separately invalid.
    """
    seed = _integer(seed, 0, 'Semilla inválida')
    map_count = _integer(map_count, 5, 'Se requieren al menos cinco mapas')
    samples_per_map = _integer(samples_per_map, 10, 'Se requieren al menos diez muestras por mapa')
    rng = np.random.default_rng(seed)
    profile = PlanetProfile.for_body('Marte')
    rows, labels, groups = [], [], []
    for group in range(map_count):
        map_seed = int(rng.integers(0, 2**31 - 1))
        world = World(width=12, height=10, seed=map_seed, difficulty=('low', 'medium', 'high')[group % 3])
        sensors = SensorSuite(seed=map_seed, noise=.12)
        cells = [(r, c) for r in range(world.height) for c in range(world.width) if (r, c) != (0, 0)]
        cliff_indices = rng.choice(len(cells), size=12, replace=False)
        world.cliffs.update(cells[index] for index in cliff_indices)
        for cell in world.cliffs:
            world.elevation[cell] = rng.uniform(-12, -7)
        edges = [(position, (position[0] + dr, position[1] + dc))
                 for position in cells for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0))
                 if world.in_bounds((position[0] + dr, position[1] + dc))]
        distance_bias = rng.normal(0, .3)
        for index in rng.integers(0, len(edges), size=samples_per_map):
            position, target = edges[index]
            delta = float(world.elevation[target] - world.elevation[position])
            label = ('barranco' if target in world.cliffs or delta < -5 else
                     'obstaculo' if target in world.obstacles else 'libre')
            observation = sensors.observe(world, position, target, 80., profile,
                                          visibility=float(rng.uniform(.35, 1.)))
            observation['distance'] = float(np.clip(observation['distance'] + distance_bias + rng.normal(0, .8), .01, 20))
            observation['elevation_delta'] = delta + rng.normal(0, 1.3)
            observation['slope'] = float(np.clip(observation['slope'] + rng.normal(0, 2.), 0, 45))
            observation['texture'] = float(np.clip(.25 + .3 * (target in world.obstacles) + rng.normal(0, .22), 0, 1))
            observation['vibration'] = float(np.clip(abs(delta) * .15 + rng.normal(0, .15), 0, 20))
            rows.append([observation[name] for name in FEATURES])
            labels.append(label)
            groups.append(group)
    return {'X': np.asarray(rows), 'y': np.asarray(labels), 'groups': np.asarray(groups),
            'operational_label': ASSUMPTION}


def _calibration_error(truth, probabilities, predictions):
    """Ten-bin expected calibration error, measured only on the named split."""
    confidence = probabilities.max(axis=1)
    correct = truth == predictions
    bins = np.minimum((confidence * 10).astype(int), 9)
    return float(sum(np.mean(bins == index) * abs(correct[bins == index].mean() - confidence[bins == index].mean())
                     for index in range(10) if np.any(bins == index)))


class NeuralPerception:
    """MLP (32, 16), training-only scaling, and transparent held-out metrics.

    ``train`` returns validation/test metrics and split provenance. Validation
    is reserved for inspection, not mixed into fitting. ``predict`` accepts a
    sensor mapping or a row ordered by FEATURES; malformed critical input
    raises ValueError so the caller must brake/degrade rather than infer blind.
    """
    operational_label = ASSUMPTION

    def __init__(self, seed=0, confidence_threshold=.65):
        self.seed = _integer(seed, 0, 'Semilla inválida')
        try:
            threshold = float(confidence_threshold)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError('Umbral de confianza inválido') from error
        if not np.isfinite(threshold) or not 0 < threshold <= 1:
            raise ValueError('Umbral de confianza inválido')
        self.confidence_threshold = threshold
        self.model = None
        self.scaler = None

    def train(self, dataset=None, map_count=18, samples_per_map=120, max_iter=200):
        max_iter = _integer(max_iter, 1, 'Cantidad de iteraciones inválida')
        data = generate_training_data(self.seed, map_count, samples_per_map) if dataset is None else dataset
        try:
            rows = _matrix(data['X'])
            truth = np.asarray(data['y'], dtype=str)
            groups = np.asarray(data['groups'])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('Entrada de datos de entrenamiento inválida') from error
        if (truth.shape != (len(rows),) or groups.shape != (len(rows),)
                or set(truth) != set(LABELS) or groups.dtype.kind not in 'iu'):
            raise ValueError('Los datos requieren tres clases y grupos de mapa enteros')
        unique = np.unique(groups)
        if len(unique) < 5:
            raise ValueError('Se requieren al menos cinco mapas independientes')
        ordered = np.random.default_rng(self.seed).permutation(unique)
        train_end, valid_end = int(.6 * len(ordered)), int(.8 * len(ordered))
        map_splits = dict(zip(('train', 'validation', 'test'), np.split(ordered, (train_end, valid_end))))
        indices = {key: np.flatnonzero(np.isin(groups, maps)) for key, maps in map_splits.items()}
        if set(truth[indices['train']]) != set(LABELS):
            raise ValueError('Los mapas de entrenamiento deben contener las tres clases')
        scaler = StandardScaler().fit(rows[indices['train']])
        model = MLPClassifier(hidden_layer_sizes=(32, 16), activation='relu',
                              early_stopping=False, random_state=self.seed,
                              max_iter=max_iter, learning_rate_init=.003)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always', ConvergenceWarning)
            model.fit(scaler.transform(rows[indices['train']]), truth[indices['train']])
        majority = max(LABELS, key=lambda label: np.sum(truth[indices['train']] == label))
        report = {'operational_label': ASSUMPTION,
                  'split_maps': {key: maps.tolist() for key, maps in map_splits.items()},
                  'training_samples': len(indices['train']),
                  'converged': not any(issubclass(item.category, ConvergenceWarning) for item in caught),
                  'iterations': int(model.n_iter_), 'majority_label': majority,
                  'confidence_note': 'Probabilidad del modelo; no es garantía de seguridad'}
        for name in ('validation', 'test'):
            selection = indices[name]
            expected = truth[selection]
            probabilities = model.predict_proba(scaler.transform(rows[selection]))
            predicted = model.classes_[probabilities.argmax(axis=1)]
            report[name] = {
                'samples': len(selection), 'labels': list(LABELS),
                'accuracy': float(accuracy_score(expected, predicted)),
                'majority_baseline': float(np.mean(expected == majority)),
                'confusion_matrix': confusion_matrix(expected, predicted, labels=LABELS).tolist(),
                'macro_f1': float(f1_score(expected, predicted, labels=LABELS, average='macro', zero_division=0)),
                'barranco_recall': float(recall_score(expected, predicted, labels=['barranco'], average='macro', zero_division=0)),
                'calibration_error': _calibration_error(expected, probabilities, predicted),
            }
        # RF-11: per-iteration replay of the same training (same seed and data) to
        # expose loss and accuracy curves; partial_fit runs one epoch per call.
        probe = MLPClassifier(hidden_layer_sizes=(32, 16), activation='relu', early_stopping=False,
                              random_state=self.seed, learning_rate_init=.003)
        train_x, train_y = scaler.transform(rows[indices['train']]), truth[indices['train']]
        valid_x, valid_y = scaler.transform(rows[indices['validation']]), truth[indices['validation']]
        history = []
        for iteration in range(1, int(model.n_iter_) + 1):
            probe.partial_fit(train_x, train_y, classes=model.classes_)
            history.append({'iteration': iteration, 'loss': float(probe.loss_),
                            'train_accuracy': float(accuracy_score(train_y, probe.predict(train_x))),
                            'validation_accuracy': float(accuracy_score(valid_y, probe.predict(valid_x)))})
        report['history'] = history
        report['loss_curve'] = [float(v) for v in model.loss_curve_]
        self.model, self.scaler = model, scaler
        self.split_indices_, self.report_ = indices, report
        return report

    def predict(self, readings):
        if self.model is None:
            raise ValueError('La red debe entrenarse antes de predecir')
        if isinstance(readings, Mapping):
            try:
                values = [readings[key] for key in FEATURES]
            except KeyError as error:
                raise ValueError(f'Entrada de sensor incompleta: falta {error.args[0]}') from error
        else:
            values = readings
        row = _matrix([values])
        normalized = self.scaler.transform(row)
        probabilities = dict(zip(self.model.classes_, self.model.predict_proba(normalized)[0].tolist()))
        probabilities = {label: float(probabilities[label]) for label in LABELS}
        activation = normalized
        summaries = []
        for weights, bias in zip(self.model.coefs_[:-1], self.model.intercepts_[:-1]):
            activation = np.maximum(0., activation @ weights + bias)
            summaries.append({'neurons': activation.shape[1], 'mean': float(activation.mean()),
                              'max': float(activation.max()), 'min': float(activation.min()),
                              'active_fraction': float(np.mean(activation > 0))})
        label = max(probabilities, key=probabilities.get)
        confidence = probabilities[label]
        return {'label': label, 'probabilities': probabilities, 'confidence': confidence,
                'low_confidence': confidence < self.confidence_threshold,
                'raw_input': row[0].tolist(), 'normalized_input': normalized[0].tolist(),
                'feature_names': list(FEATURES), 'activation_summaries': summaries,
                'risk': .7 * probabilities['obstaculo'] + probabilities['barranco'],
                'operational_label': ASSUMPTION}
