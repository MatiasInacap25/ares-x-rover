"""v1.2 F14: ghost race, the other policies run the same map and seed alongside."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ares.api import Session  # noqa: E402


def test_snapshot_feeds_new_events_to_the_alert_strip():
    session = Session(seed=42)
    before = session.dispatch('step', {})['event_feed']['total']
    feed = session.dispatch('inject', {'kind': 'tormenta_polvo'})['event_feed']
    assert feed['total'] == before + 1
    assert feed['recent'][-1]['kind'] == 'tormenta_polvo' and feed['recent'][-1]['label'] and feed['recent'][-1]['message']


def test_ghost_mode_is_off_by_default():
    assert Session(seed=42).dispatch('state')['ghosts'] == []


def test_enabling_ghosts_restarts_the_mission_with_the_three_ablations():
    session = Session(seed=42)
    session.dispatch('step', {'n': 3})
    snapshot = session.dispatch('ghosts', {'enabled': True})
    assert snapshot['status']['step'] == 0
    assert [g['policy'] for g in snapshot['ghosts']] == ['sin_rna', 'sin_difuso', 'sin_ag']
    assert all(g['position'] == snapshot['status']['position'] and g['step'] == 0 for g in snapshot['ghosts'])
    assert all(g['label'] and g['path'] for g in snapshot['ghosts'])


def test_ghosts_advance_with_the_main_rover_on_the_same_world():
    session = Session(seed=42)
    session.dispatch('ghosts', {'enabled': True})
    snapshot = session.dispatch('step', {'n': 5})
    assert all(g['step'] == snapshot['status']['step'] == 5 for g in snapshot['ghosts'])
    main = session.mission
    for ghost in session.ghosts.values():
        assert ghost.world.obstacles == main.world.obstacles and ghost.seed == main.seed


def test_the_main_policy_is_replaced_by_the_hybrid_among_the_ghosts():
    session = Session(seed=42, policy='sin_ag')
    snapshot = session.dispatch('ghosts', {'enabled': True})
    assert [g['policy'] for g in snapshot['ghosts']] == ['hibrido', 'sin_rna', 'sin_difuso']


def test_events_and_terrain_edits_reach_every_ghost():
    session = Session(seed=42)
    session.dispatch('ghosts', {'enabled': True})
    session.dispatch('step', {})
    session.dispatch('inject', {'kind': 'tormenta_polvo'})
    session.dispatch('place', {'position': [6, 6], 'kind': 'obstaculo'})
    for ghost in session.ghosts.values():
        assert ghost.timers['storm'] > 0 and (6, 6) in ghost.world.obstacles


def test_ghosts_survive_reset_and_configure_and_can_be_turned_off():
    session = Session(seed=42)
    session.dispatch('ghosts', {'enabled': True})
    session.dispatch('step', {'n': 2})
    assert all(g['step'] == 0 for g in session.dispatch('reset')['ghosts'])
    snapshot = session.dispatch('configure', {'seed': 7})
    assert len(snapshot['ghosts']) == 3 and all(g.seed == 7 for g in session.ghosts.values())
    assert session.dispatch('ghosts', {'enabled': False})['ghosts'] == []


def test_the_race_reports_a_result_for_every_runner_when_it_ends():
    session = Session(seed=42)
    session.dispatch('ghosts', {'enabled': True})
    for _ in range(8):
        snapshot = session.dispatch('step', {'n': 50})
    assert snapshot['status']['finished'] and all(g['finished'] and g['outcome'] for g in snapshot['ghosts'])
    assert all({'battery', 'science', 'distance', 'collisions', 'state'} <= set(g) for g in snapshot['ghosts'])
