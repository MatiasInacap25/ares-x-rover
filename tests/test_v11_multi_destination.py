"""v1.1 F13: several operator destinations visited in the best order."""
import itertools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ares.api import Session  # noqa: E402
from ares.genetic import optimize_visit_order  # noqa: E402
from ares.mission import MAX_DESTINATIONS, HybridMission  # noqa: E402


def started(steps=2, **config):
    config.setdefault('seed', 42)
    mission = HybridMission(**config).prepare()
    for _ in range(steps):
        mission.step()
    return mission


def spread_cells(mission, count):
    """Reachable free cells far apart from each other, in a deliberately bad order."""
    cells = [c for c in sorted(mission._free_cells())
             if c != mission.position and c not in mission.world.cliffs and c not in mission.world.obstacles
             and mission._bfs(mission.position, c)]
    picked = [max(cells, key=lambda c: c[0] + c[1])]
    while len(picked) < count:
        picked.append(max((c for c in cells if c not in picked),
                          key=lambda c: min(abs(c[0] - p[0]) + abs(c[1] - p[1]) for p in picked)))
    return picked


def brute_force(leg, closing):
    stops = range(1, len(leg))
    cost = lambda order: (leg[0][order[0]] + sum(leg[a][b] for a, b in zip(order, order[1:])) + closing[order[-1]])
    return min(cost(order) for order in itertools.permutations(stops))


@pytest.mark.parametrize('seed', range(5))
def test_the_genetic_order_matches_the_exact_optimum(seed):
    import random
    rng = random.Random(seed)
    points = [(rng.randrange(12), rng.randrange(16)) for _ in range(8)]   # start + 7 stops
    leg = [[abs(a[0] - b[0]) + abs(a[1] - b[1]) for b in points] for a in points]
    closing = [p[0] + p[1] for p in points]
    result = optimize_visit_order(leg, closing, seed=seed)
    assert sorted(result['order']) == list(range(7))
    assert result['cost'] == brute_force(leg, closing)
    assert result['history'][-1] <= result['history'][0]


def test_the_genetic_order_is_reproducible_and_handles_trivial_cases():
    leg = [[0, 4, 9], [4, 0, 3], [9, 3, 0]]
    assert optimize_visit_order(leg, [4, 9, 0], seed=1) == optimize_visit_order(leg, [4, 9, 0], seed=1)
    assert optimize_visit_order([[0, 5], [5, 0]], [0, 5])['order'] == [0]
    assert optimize_visit_order([[0]], [0])['order'] == []


def test_several_destinations_are_kept_and_all_are_visited():
    mission = started()
    targets = spread_cells(mission, 3)
    for cell in targets:
        mission.set_destination(list(cell))
    assert sorted(mission.destinations) == sorted(targets)
    assert mission.destination == mission.destinations[0] == tuple(mission.route[-1])
    summary = mission.run()
    assert all(cell in mission.path for cell in targets)
    assert mission.destinations == [] and summary['safety_violations'] == 0
    assert sum(e['kind'] == 'destino_alcanzado' for e in mission.event_log) == 3


def test_the_visit_order_is_the_shortest_tour_not_the_order_of_entry():
    mission = started()
    targets = spread_cells(mission, 4)
    for cell in targets:
        mission.set_destination(list(cell))
    nodes = [mission.position] + targets
    dist = lambda a, b: len(mission._bfs(a, b)) - 1
    leg = [[dist(a, b) for b in nodes] for a in nodes]
    closing = [len(mission._bfs(n, goals=set(mission.world.refuges))) - 1 for n in nodes]
    order = [nodes.index(cell) for cell in mission.destinations]
    cost = leg[0][order[0]] + sum(leg[a][b] for a, b in zip(order, order[1:])) + closing[order[-1]]
    assert cost == brute_force(leg, closing)
    assert any(e['kind'] == 'orden_destinos' for e in mission.event_log)


def test_a_destination_crossed_on_the_way_counts_as_visited():
    mission = started()
    far = spread_cells(mission, 1)[0]
    mission.set_destination(list(far))
    on_the_way = tuple(mission.route[len(mission.route) // 2])
    mission.set_destination(list(on_the_way))
    assert mission.destinations[0] == on_the_way
    mission.run()
    assert mission.destinations == [] and on_the_way in mission.path and far in mission.path


def test_one_destination_can_be_removed_and_none_clears_all():
    mission = started()
    a, b, c = spread_cells(mission, 3)
    for cell in (a, b, c):
        mission.set_destination(list(cell))
    mission.remove_destination(list(b))
    assert sorted(mission.destinations) == sorted([a, c])
    with pytest.raises(ValueError, match='No hay un destino'):
        mission.remove_destination(list(b))
    mission.set_destination(None)
    assert mission.destinations == [] and mission.destination is None


def test_duplicates_and_too_many_destinations_are_rejected():
    mission = started()
    cells = spread_cells(mission, MAX_DESTINATIONS + 1)
    mission.battery = 1e6                                # energy is not the subject here
    mission.set_destination(list(cells[0]))
    with pytest.raises(ValueError, match='ya está fijado'):
        mission.set_destination(list(cells[0]))
    for cell in cells[1:MAX_DESTINATIONS]:
        mission.set_destination(list(cell))
    with pytest.raises(ValueError, match='Máximo'):
        mission.set_destination(list(cells[-1]))
    assert len(mission.destinations) == MAX_DESTINATIONS


def test_a_destination_that_makes_the_whole_tour_too_expensive_is_rejected():
    mission = started()
    a, b = spread_cells(mission, 2)
    out = len(mission._bfs(mission.position, a)) - 1
    back = len(mission._bfs(a, goals=set(mission.world.refuges))) - 1
    from ares.mission import PLAN_SPEED
    mission.battery = (out + back) * mission.cell_cost(PLAN_SPEED) + .01   # enough for a alone
    mission.set_destination(list(a))
    with pytest.raises(ValueError, match='retorno seguro'):
        mission.set_destination(list(b))
    assert mission.destinations == [a]


def test_same_seed_gives_the_same_tour():
    def tour():
        mission = started()
        for cell in spread_cells(mission, 4):
            mission.set_destination(list(cell))
        return list(mission.destinations), mission.run()['distance']
    assert tour() == tour()


def test_panel_api_adds_toggles_and_reports_the_tour():
    session = Session(seed=42)
    session.dispatch('step', {})
    a, b = (list(c) for c in spread_cells(session.mission, 2))
    session.dispatch('destination', {'position': a})
    snapshot = session.dispatch('destination', {'position': b})
    assert sorted(snapshot['map']['destinations']) == sorted([a, b])
    assert snapshot['map']['destination'] == snapshot['map']['destinations'][0]
    assert snapshot['map']['tour'][0] == snapshot['map']['destinations'][0]
    assert snapshot['map']['tour'][-1] == snapshot['map']['destinations'][-1]
    assert snapshot['status']['destinations_left'] == 2 and snapshot['status']['tour_cells'] > 0
    snapshot = session.dispatch('destination', {'position': a})          # same cell again removes it
    assert snapshot['map']['destinations'] == [b]
    assert session.dispatch('destination', {'position': None})['map']['destinations'] == []
