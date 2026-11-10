"""Inspectable Mamdani controller; all operational thresholds are assumptions."""
import math

import numpy as np

from .planet import ASSUMPTION


def triangular(value, a, b, c):
    """Triangular membership, including degenerate shoulder endpoints."""
    if value < a or value > c:
        return 0.0
    if value == b:
        return 1.0
    return float((value - a) / (b - a) if value < b else (c - value) / (c - b))


def trapezoidal(value, a, b, c, d):
    """Trapezoidal membership with closed left/right shoulders."""
    if value < a or value > d:
        return 0.0
    if b <= value <= c:
        return 1.0
    return float((value - a) / (b - a) if value < b else (d - value) / (d - c))


class FuzzyController:
    """Speed is advisory, not a physical veto; H3 supplies hard safety limits.

    Invalid input or zero aggregate area produces speed 0 and caution 1.
    Temperature uses hypothetical hardware-relative thresholds, not planetary
    engineering limits. Min implements AND, max implements union of rules.
    """

    operational_label = ASSUMPTION
    membership_sets = {
        'distance': {'cerca': ('trap', 0, 0, 2, 6),
                     'media': ('tri', 2, 9, 15), 'lejos': ('trap', 10, 15, 20, 20)},
        'battery': {'critica': ('trap', 0, 0, 8, 18),
                    'baja': ('tri', 10, 30, 55), 'alta': ('trap', 40, 65, 100, 100)},
        'slope': {'plana': ('trap', 0, 0, 4, 12),
                  'media': ('tri', 5, 20, 32), 'fuerte': ('trap', 25, 35, 45, 45)},
        'temperature': {'fria': ('trap', -273.15, -273.15, -60, 0),
                        'templada': ('tri', -30, 20, 70),
                        'caliente': ('trap', 40, 90, 1000, 1000)},
    }
    output_sets = {
        'parar': ('trap', 0, 0, .01, .06),
        'lenta': ('tri', .03, .18, .35),
        'moderada': ('tri', .25, .5, .75),
        'rapida': ('trap', .6, .85, 1, 1),
    }
    # Each tuple is an AND antecedent and its speed consequent.
    rule_specs = (
        ('Barranco o riesgo cercano: parar.', (('distance', 'cerca'),), 'parar'),
        ('Batería crítica: avance lento.', (('battery', 'critica'),), 'lenta'),
        ('Pendiente fuerte y batería alta: avance lento.', (('slope', 'fuerte'), ('battery', 'alta')), 'lenta'),
        ('Pendiente media y distancia media: avance lento.', (('slope', 'media'), ('distance', 'media')), 'lenta'),
        ('Batería alta, terreno plano y riesgo lejano: rápido.', (('battery', 'alta'), ('slope', 'plana'), ('distance', 'lejos')), 'rapida'),
        ('Batería baja y distancia media: lento.', (('battery', 'baja'), ('distance', 'media')), 'lenta'),
        ('Distancia media y terreno plano: moderado.', (('distance', 'media'), ('slope', 'plana')), 'moderada'),
        ('Temperatura caliente: parar y evaluar protección.', (('temperature', 'caliente'),), 'parar'),
        ('Temperatura fría: lento para proteger equipos.', (('temperature', 'fria'),), 'lenta'),
        ('Batería alta, distancia media y temperatura templada: moderado.', (('battery', 'alta'), ('distance', 'media'), ('temperature', 'templada')), 'moderada'),
        ('Batería baja y riesgo lejano: moderado para conservar energía.', (('battery', 'baja'), ('distance', 'lejos')), 'moderada'),
        ('Riesgo lejano y pendiente media: moderado.', (('distance', 'lejos'), ('slope', 'media')), 'moderada'),
    )

    def __init__(self, rules=None):
        self.rules = [
            {'id': index + 1, 'description': description,
             'antecedents': antecedents, 'consequent': consequent}
            for index, (description, antecedents, consequent) in enumerate(self.rule_specs)
        ] if rules is None else list(rules)
        self.universe = np.linspace(0, 1, 201)

    @staticmethod
    def membership(value, specification):
        kind, *points = specification
        return triangular(value, *points) if kind == 'tri' else trapezoidal(value, *points)

    def infer(self, distance, battery, slope, temperature=20):
        values = dict(distance=distance, battery=battery, slope=slope, temperature=temperature)
        limits = {'distance': (0, 20), 'battery': (0, 100),
                  'slope': (0, 45), 'temperature': (-273.15, 1000)}
        aggregate = np.zeros_like(self.universe)
        result = {'speed': 0.0, 'caution': 1.0, 'centroid': 0.0,
                  'membership_degrees': {}, 'activated_rules': [],
                  'universe': self.universe.tolist(), 'aggregated_curve': aggregate.tolist(),
                  'reason': 'ENTRADA_INVALIDA', 'operational_label': ASSUMPTION}
        if any(not isinstance(value, (int, float, np.number)) or not math.isfinite(value)
               or not limits[name][0] <= value <= limits[name][1]
               for name, value in values.items()):
            return result
        degrees = {name: {label: self.membership(values[name], spec)
                          for label, spec in sets.items()}
                   for name, sets in self.membership_sets.items()}
        result['membership_degrees'] = degrees
        for rule in self.rules:
            strength = min(degrees[name][label] for name, label in rule['antecedents'])
            if strength > 0:
                curve = np.array([self.membership(x, self.output_sets[rule['consequent']])
                                  for x in self.universe])
                aggregate = np.maximum(aggregate, np.minimum(strength, curve))
                result['activated_rules'].append({**rule, 'strength': strength})
        integrate = getattr(np, 'trapezoid', None) or np.trapz  # numpy < 2 compatibility
        area = integrate(aggregate, self.universe)
        centroid = float(integrate(self.universe * aggregate, self.universe) / area) if area > 0 else 0.0
        result.update(speed=centroid, centroid=centroid, caution=1.0 - centroid,
                      aggregated_curve=aggregate.tolist(),
                      reason='INFERENCIA_MAMDANI' if area > 0 else 'SIN_REGLAS_ACTIVAS')
        return result
