"""v1.2 F16: scout drone that flies ahead and shares hazards with the rover."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ares.api import Session  # noqa: E402
from ares.mission import DRONE_AHEAD, DRONE_ENERGY, HybridMission, validate_config  # noqa: E402


def started(steps=2, **config):
    config.setdefault('seed', 42)
    mission = HybridMission(**config).prepare()
    for _ in range(steps):
        mission.step()
    return mission


def test_drone_is_off_by_default_and_leaves_the_trace_untouched():
    assert validate_config({})['drone'] is False
    plain, explicit = started(steps=0), started(steps=0, drone=False)
    timing = ('decision_ms', 'planning_s')          # wall-clock, not part of the trace
    a, b = plain.run(), explicit.run()
    assert {k: v for k, v in a.items() if k not in timing} == {k: v for k, v in b.items() if k not in timing}
    assert plain.drone is None and plain.metrics['drone_discoveries'] == 0


def test_drone_finds_a_hidden_cliff_on_the_route_before_the_edge_sensor():
    mission = started(drone=True)
    cliff = tuple(mission.inject('barranco')['position'])
    assert cliff not in mission.belief.cliffs            # still hidden from the rover
    record = mission.step()
    assert cliff in mission.belief.cliffs and cliff not in [tuple(c) for c in mission.route]
    assert record['reason'] != 'R04_VETO_BARRANCO_CONFIRMADO'
    assert mission.metrics['drone_discoveries'] >= 1
    found = [e for e in mission.event_log if e['kind'] == 'dron']
    assert found and list(cliff) in found[-1]['cells']


def test_drone_flies_ahead_on_the_route_and_its_energy_comes_from_the_rover():
    mission = started(drone=True, steps=3)
    assert mission.drone['flying'] and mission.drone['reason'] is None
    assert len(mission.drone['scanned']) >= 3
    assert mission.metrics['drone_steps'] == 3
    assert mission.metrics['drone_energy'] == pytest.approx(3 * DRONE_ENERGY)
    assert DRONE_AHEAD >= 2


@pytest.mark.parametrize('event', ['tormenta_polvo', 'viento'])
def test_drone_stays_grounded_in_bad_weather(event):
    mission = started(drone=True)
    flown = mission.metrics['drone_steps']
    mission.inject(event)
    mission.step()
    assert not mission.drone['flying'] and mission.drone['reason']
    assert mission.metrics['drone_steps'] == flown


def test_drone_is_grounded_below_the_battery_reserve_and_absent_in_probe_mode():
    mission = started(drone=True)
    mission.battery = 10.
    mission.step()
    assert not mission.drone['flying'] and 'reserva' in mission.drone['reason']
    probe = started(drone=True, planet='Júpiter', mode='sonda')
    assert not probe.drone['flying'] and probe.metrics['drone_steps'] == 0


def test_drone_never_costs_safety_and_helps_over_several_seeds():
    discoveries = 0
    for seed in range(6):
        summary = HybridMission(seed=seed, drone=True).prepare().run()
        assert summary['safety_violations'] == 0 and summary['collisions'] == 0
        discoveries += summary['drone_discoveries']
    assert discoveries > 0


def test_drone_through_the_panel_api():
    session = Session(seed=42)
    assert session.dispatch('state')['drone'] is None
    snapshot = session.dispatch('configure', {'drone': True})
    assert snapshot['config']['drone'] is True
    snapshot = session.dispatch('step', {})
    assert snapshot['drone']['flying'] and len(snapshot['drone']['position']) == 2
    assert 'error' in session.dispatch('configure', {'drone': 'quizás'})
