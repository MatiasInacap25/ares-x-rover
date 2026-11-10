"""Public genetic-planner behavior and observable evolutionary operations."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import numpy as np
import pytest

from ares.genetic import GeneticPlanner
from ares.world import World


def flat(width=6, height=5):
    world = World(width=width, height=height, science_count=0)
    world.obstacles.clear()
    world.cliffs.clear()
    world.science_sites = {(0, 3), (3, 3)}
    return world


def test_population_candidates_history_and_determinism():
    world = flat()
    first = GeneticPlanner(seed=7).plan(world, (0, 0), (4, 5))
    second = GeneticPlanner(seed=7).plan(world, (0, 0), (4, 5))
    assert first == second
    assert first['feasible'] and len(first['candidates']) >= 3
    assert len({tuple(c['route']) for c in first['candidates']}) >= 3
    assert len(first['history'][0]['chromosomes']) >= 30
    for candidate in first['candidates']:
        assert set(candidate['components']) == {'science', 'distance', 'energy', 'predicted_risk', 'time'}
        assert all(0 <= value <= 1 for value in candidate['components'].values())
        assert all(abs(a[0]-b[0]) + abs(a[1]-b[1]) == 1 for a, b in zip(candidate['route'], candidate['route'][1:]))
    assert any(h['crossovers'] > 0 and h['mutations'] > 0 for h in first['history'][1:])
    assert any(h['tournaments'] > 0 for h in first['history'][1:])


def test_elitism_preserves_best_chromosome():
    result = GeneticPlanner(seed=4, early_stop=False).plan(flat(), (0, 0), (4, 5))
    history = result['history']
    assert len(history) == 31
    for previous, current in zip(history, history[1:]):
        assert previous['best_chromosome'] in current['chromosomes']
        assert current['best_fitness'] >= previous['best_fitness']


def test_early_stop_retains_best_feasible():
    result = GeneticPlanner(seed=4, mutation_rate=0, crossover_rate=0).plan(flat(), (0, 0), (4, 5))
    assert result['stopped_early'] and result['generations_run'] == 10
    assert result['feasible']
    assert result['fitness'] == max(h['best_feasible_fitness'] for h in result['history'])


def test_invalid_mutation_is_repaired_and_penalty_is_inspectable():
    world = flat()
    planner = GeneticPlanner(seed=1, waypoints=3)
    invalid = [(900, -40), (float('nan'), 0), None]
    repaired = planner.repair(invalid, world)
    assert len(repaired) == 3 and all(world.traversable(p) for p in repaired)
    mutated = planner.mutate(invalid, world)
    assert all(world.traversable(p) for p in mutated)
    candidate = planner.evaluate(invalid, world, (0, 0), (4, 5))
    assert candidate['repaired'] and candidate['feasible']


@pytest.mark.parametrize('kind', ['obstacle', 'cliff'])
def test_maze_avoids_hard_barriers(kind):
    world = flat()
    barrier = {(r, 2) for r in range(4)}
    getattr(world, 'obstacles' if kind == 'obstacle' else 'cliffs').update(barrier)
    result = GeneticPlanner(seed=2).plan(world, (0, 0), (0, 5))
    assert result['feasible'] and not (set(result['route']) & barrier)
    assert (4, 2) in result['route']


@pytest.mark.parametrize('kwargs', [{'battery': 0}, {'battery': 1}, {'temperature': 81}, {'thermal_limit': 10}])
def test_energy_thermal_and_safe_return(kwargs):
    result = GeneticPlanner(seed=3).plan(flat(), (0, 0), (4, 5), **kwargs)
    assert not result['feasible'] and result['route'] == []
    assert 'sin solución' in result['message'].lower()
    assert all(c['penalty'] > 0 for c in result['candidates'])


def test_safe_return_is_included_not_only_outbound_energy():
    world = flat()
    planner = GeneticPlanner(seed=1, waypoints=1)
    candidate = planner.evaluate([(0, 0)], world, (0, 0), (0, 5), battery=7)
    assert candidate['energy_required'] == 10
    assert not candidate['feasible'] and 'battery' in candidate['violations']


def test_unreachable_and_bounds_are_explicit():
    world = flat()
    world.obstacles.update({(r, 2) for r in range(5)})
    planner = GeneticPlanner(seed=1)
    result = planner.plan(world, (0, 0), (0, 5))
    assert not result['feasible'] and 'sin solución' in result['message'].lower()
    assert not planner.plan(world, (-1, 0), (0, 5))['feasible']


def test_risk_weights_and_scientific_visit_order():
    world = flat()
    planner = GeneticPlanner(waypoints=2, weights={'science': 5, 'distance': 1, 'energy': 1, 'predicted_risk': 10, 'time': 1})
    world.science_sites = {(3, 0), (0, 3)}
    risk = np.zeros((5, 6))
    risk[0, 3] = 1
    candidate = planner.evaluate([(3, 0), (0, 3)], world, (0, 0), (0, 5), estimated_risk=risk)
    assert candidate['science_order'] == [(3, 0), (0, 3)]
    assert candidate['components']['science'] == 1
    without_risk = planner.evaluate([(3, 0), (0, 3)], world, (0, 0), (0, 5))
    assert candidate['fitness'] < without_risk['fitness']
    world.science_sites.clear()
    assert planner.evaluate([(0, 0)] * 2, world, (0, 0), (0, 5))['components']['science'] == 0


@pytest.mark.parametrize('kwargs', [{'population_size': 29}, {'generations': 29}, {'mutation_rate': float('nan')}, {'weights': {'science': -1}}])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        GeneticPlanner(**kwargs)


def test_disconnected_waypoint_is_repaired_without_losing_reachable_goal():
    world = flat()
    world.obstacles.update({(r, 2) for r in range(5)})
    candidate = GeneticPlanner(waypoints=1).evaluate([(0, 5)], world, (0, 0), (4, 0))
    assert candidate['feasible'] and candidate['repaired']
    assert candidate['chromosome'] == [(0, 0)]
    assert candidate['route'][-1] == (4, 0)


def test_physical_cliff_edges_rejected_outbound_and_on_safe_return():
    world = flat(width=3, height=1)
    world.science_sites.clear()
    world.elevation[:] = [[0, -10, 0]]
    result = GeneticPlanner(seed=2).plan(world, (0, 0), (0, 2))
    assert not result['feasible'] and result['route'] == []
    assert 'sin solución' in result['message'].lower()
    assert all(not c['feasible'] and c['penalty'] > 0 for c in result['candidates'])

    # Uphill travel is permitted, but its return edge is a forbidden descent.
    world.elevation[:] = [[0, 10, 0]]
    candidate = GeneticPlanner(waypoints=1).evaluate([(0, 0)], world, (0, 0), (0, 1))
    assert candidate['route'] == [(0, 0), (0, 1)]
    assert not candidate['feasible'] and candidate['energy_required'] == float('inf')
    assert 'battery' in candidate['violations']
