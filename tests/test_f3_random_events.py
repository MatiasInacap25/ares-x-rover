"""v1.1 F3: random events drawn per step from a seed-derived generator."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ares.api import Session  # noqa: E402
from ares.mission import HybridMission, validate_config  # noqa: E402


def run(steps=200, **config):
    config.setdefault('seed', 42)
    mission = HybridMission(**config).prepare()
    for _ in range(steps):
        if mission.finished:
            break
        mission.step()
    return mission


def random_events(mission):
    return [e for e in mission.event_log if e.get('origin') == 'aleatorio']


def test_event_rate_defaults_to_zero_and_is_validated():
    assert validate_config({})['event_rate'] == 0.
    assert validate_config({'event_rate': .05})['event_rate'] == .05
    for bad in (-.01, .11, 'x', float('nan')):
        with pytest.raises(ValueError, match='event_rate'):
            validate_config({'event_rate': bad})


def test_rate_zero_keeps_the_trace_identical_to_the_default():
    base, zero = run(60), run(60, event_rate=0)
    assert base.export_csv() == zero.export_csv()
    assert not random_events(zero)


def test_same_seed_and_rate_reproduce_the_same_events_and_trace():
    a, b = run(200, event_rate=.05), run(200, event_rate=.05)
    assert [(e['step'], e['kind']) for e in random_events(a)] == [(e['step'], e['kind']) for e in random_events(b)]
    assert a.export_csv() == b.export_csv()


def test_two_hundred_steps_at_five_percent_give_between_2_and_25_events():
    counts = []
    for seed in (1, 7, 42):
        mission = HybridMission(seed=seed, event_rate=.05).prepare()
        drawn = 0
        for _ in range(200):
            before = len(random_events(mission))
            mission.step()
            drawn += len(random_events(mission)) - before
            if mission.finished:  # keep drawing on a fresh copy so the window is 200 steps
                mission = HybridMission(seed=seed + 1000 + mission.step_index, event_rate=.05).prepare()
        counts.append(drawn)
    assert all(2 <= c <= 25 for c in counts), counts


def test_random_events_are_valid_for_the_mode_and_marked_as_random():
    probe = run(200, planet='Saturno', mode='sonda', event_rate=.1)
    kinds = {e['kind'] for e in random_events(probe)}
    assert kinds and 'barranco' not in kinds
    assert all(e['label'] and e['message'] for e in random_events(probe))
    rover = run(80, event_rate=.1)
    operator = rover.inject('sismo') if not rover.finished else None
    assert operator is None or operator['origin'] == 'operador'


def test_no_events_after_the_mission_has_finished():
    mission = run(400, event_rate=.1)
    assert mission.finished
    count = len(mission.event_log)
    for _ in range(20):
        mission.step()
    assert len(mission.event_log) == count


def test_random_events_do_not_count_as_queued_operator_orders():
    mission = HybridMission(seed=42, event_rate=.1).prepare()
    mission.step()
    mission.inject('perdida_enlace')
    queued = mission.queued_orders
    for _ in range(4):
        mission.step()
    assert mission.queued_orders == queued


def test_session_accepts_event_rate_in_configure():
    session = Session()
    snap = session.dispatch('configure', {'seed': 3, 'event_rate': .1})
    assert 'error' not in snap, snap
    assert snap['config']['event_rate'] == .1


def test_panel_entry_points_start_at_three_percent():
    from ares.dashboard import Dashboard
    assert Dashboard().session.config['event_rate'] == .03
    root = Path(__file__).resolve().parents[1]
    assert 'Session(event_rate=.03)' in (root / 'server.py').read_text()
    assert 'Session(event_rate=0.03)' in (root / 'build_site.py').read_text()


def test_feed_and_log_tell_random_events_apart():
    session = Session(seed=42, event_rate=.1)
    snap = None
    for _ in range(60):
        snap = session.dispatch('step', {'n': 1})
        if any(e['origin'] == 'aleatorio' for e in snap['event_feed']['recent']):
            break
    assert any(e['origin'] == 'aleatorio' for e in snap['event_feed']['recent'])
    assert any('(aleatorio)' in label for row in snap['log'] for label in row['events'])
    snap = session.dispatch('inject', {'kind': 'sismo'})
    assert snap['event_feed']['recent'][-1]['origin'] == 'operador'
