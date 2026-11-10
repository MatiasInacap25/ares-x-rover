"""Standalone Mamdani inference and diagnostic contract."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ares.fuzzy import FuzzyController, triangular, trapezoidal


def test_sets_and_documented_rules():
    controller = FuzzyController()
    assert len(controller.rules) >= 8
    assert all(len(sets) >= 3 for sets in controller.membership_sets.values())
    assert all(rule['description'] for rule in controller.rules)


def test_distance_changes_crisp_and_centroid():
    controller = FuzzyController()
    near = controller.infer(distance=1, battery=80, slope=0, temperature=20)
    medium = controller.infer(distance=10, battery=80, slope=0, temperature=20)
    assert near['speed'] < medium['speed']
    assert near['caution'] > medium['caution']
    assert len(medium['activated_rules']) > 1
    x = np.asarray(medium['universe'])
    curve = np.asarray(medium['aggregated_curve'])
    assert medium['centroid'] == pytest.approx(np.trapezoid(x * curve, x) / np.trapezoid(curve, x))
    assert medium['speed'] == medium['centroid']


def test_no_rule_fallback():
    result = FuzzyController(rules=[]).infer(10, 80, 0, 20)
    assert result['speed'] == 0
    assert result['reason'] == 'SIN_REGLAS_ACTIVAS'
    assert not any(result['aggregated_curve'])


@pytest.mark.parametrize('values', [(float('nan'),80,0,20), (float('inf'),80,0,20),
                                   (-1,80,0,20), (10,101,0,20), (10,80,46,20)])
def test_invalid_inputs_safe(values):
    result = FuzzyController().infer(*values)
    assert result['speed'] == 0
    assert result['reason'] == 'ENTRADA_INVALIDA'


def test_membership_shoulders_and_triangle():
    assert trapezoidal(0, 0, 0, 2, 4) == 1
    assert trapezoidal(4, 0, 2, 4, 4) == 1
    assert triangular(2, 0, 2, 4) == 1
    assert triangular(1, 0, 2, 4) == .5


def test_temperature_and_boundaries():
    controller = FuzzyController()
    normal = controller.infer(20, 100, 0, 20)
    hot = controller.infer(20, 100, 0, 450)
    assert hot['speed'] < normal['speed']
    for distance in (0, 20):
        result = controller.infer(distance, 0, 45, -200)
        assert 0 <= result['speed'] <= 1
        assert 0 <= result['caution'] <= 1
