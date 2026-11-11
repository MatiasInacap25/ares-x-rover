"""v1.1 F6: operator-defined destination."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ares.api import Session  # noqa: E402
from ares.mission import HybridMission  # noqa: E402


def started(steps=2, **config):
    config.setdefault('seed', 42)
    mission = HybridMission(**config).prepare()
    for _ in range(steps):
        mission.step()
    return mission


def free_cell_off_route(mission):
    route = {tuple(c) for c in mission.route}
    return next(c for c in sorted(mission._free_cells(), key=lambda c: -(c[0] + c[1]))
                if c not in route and c not in mission.world.cliffs and c not in mission.world.obstacles
                and mission._bfs(mission.position, c))


def test_valid_destination_replans_at_once_and_the_rover_reaches_it():
    mission = started()
    target = free_cell_off_route(mission)
    step = mission.step_index
    entry = mission.set_destination(list(target))
    assert mission.step_index == step and entry['kind'] == 'destino'
    assert tuple(mission.route[-1]) == target and mission.destination == target
    summary = mission.run()
    assert target in mission.path
    assert any(e['kind'] == 'destino_alcanzado' for e in mission.event_log)
    assert mission.destination is None and summary['safety_violations'] == 0


def test_mission_continues_after_reaching_the_destination():
    mission = started()
    target = free_cell_off_route(mission)
    mission.set_destination(list(target))
    while mission.destination is not None and not mission.finished:
        mission.step()
    assert not mission.finished                      # arriving is not the end of the mission
    summary = mission.run()
    assert summary['state'] in ('EXITO', 'MODO_SEGURO')


def test_destination_on_a_known_hazard_is_rejected_without_changing_the_route():
    mission = started()
    cliff = tuple(mission.inject('barranco')['position'])
    mission.step()                                   # edge sensor confirms it
    before = [tuple(c) for c in mission.route]
    with pytest.raises(ValueError, match='obstáculo o barranco'):
        mission.set_destination(list(cliff))
    assert [tuple(c) for c in mission.route] == before and mission.destination is None


def test_destination_without_energy_for_a_safe_return_is_rejected():
    mission = started()
    target = free_cell_off_route(mission)
    mission.battery = 3.
    with pytest.raises(ValueError, match='retorno seguro'):
        mission.set_destination(list(target))
    assert mission.destination is None


@pytest.mark.parametrize('cell', [[-1, 0], [0, 99], [12, 3]])
def test_destination_outside_the_map_is_rejected(cell):
    with pytest.raises(ValueError, match='fuera del mapa'):
        started().set_destination(cell)


def test_destination_can_be_cancelled():
    mission = started()
    mission.set_destination(list(free_cell_off_route(mission)))
    mission.set_destination(None)
    assert mission.destination is None and mission.run()['state'] in ('EXITO', 'MODO_SEGURO')


def test_destination_never_overrides_a_safety_veto():
    mission = started()
    target = free_cell_off_route(mission)
    mission.set_destination(list(target))
    cliff = tuple(mission.inject('barranco')['position'])
    record = mission.step()
    assert record['reason'] == 'R04_VETO_BARRANCO_CONFIRMADO' and mission.position != cliff
    assert mission.run()['safety_violations'] == 0


def test_destination_through_the_panel_api():
    session = Session(seed=42)
    session.dispatch('step', {'n': 2})
    target = list(free_cell_off_route(session.mission))
    snapshot = session.dispatch('destination', {'position': target})
    assert snapshot['map']['destination'] == target and snapshot['status']['destination_distance'] > 0
    assert 'error' in session.dispatch('destination', {'position': [99, 99]})
    assert session.dispatch('destination', {'position': None})['map']['destination'] is None
