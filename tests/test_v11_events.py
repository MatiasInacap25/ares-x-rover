"""v1.1: heat wave (F8), per-event metrics (F4) and immediate replanning (F9)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ares.api import Session  # noqa: E402
from ares.mission import HybridMission  # noqa: E402


def pair(steps=3, **config):
    """Two identical prepared missions advanced the same number of steps."""
    config.setdefault('seed', 42)
    missions = [HybridMission(**config).prepare() for _ in range(2)]
    for mission in missions:
        for _ in range(steps):
            mission.step()
    return missions


# ------------------------------------------------------------------ F8
def test_heat_wave_on_mars_raises_temperatures_and_slows_the_rover():
    base, hot = pair()
    cool_cost = hot.cell_cost(.5)
    hot.inject('ola_calor')
    assert hot.temperature_internal == pytest.approx(base.temperature_internal + 35.)
    assert hot.cell_cost(.5) == pytest.approx(1.2 * cool_cost)
    a, b = base.step(), hot.step()
    assert b['sensors']['temperature_external'] == pytest.approx(a['sensors']['temperature_external'] + 40., abs=1.)
    assert b['crisp_speed'] < a['crisp_speed']
    assert b['reason'] != 'R01_LIMITE_TERMICO' and not hot.finished


def test_heat_wave_ends_after_twelve_steps():
    base, hot = pair()
    hot.inject('ola_calor')
    for _ in range(12):
        assert hot.timers['heat'] > 0
        hot.step()
    assert hot.timers['heat'] == 0
    assert hot.temperature_internal == pytest.approx(base.temperature_internal)
    assert hot.cell_cost(.5) == pytest.approx(base.cell_cost(.5))


def test_heat_wave_on_venus_exceeds_the_thermal_limit():
    mission = HybridMission(planet='Venus', seed=42).prepare()
    mission.step()
    mission.inject('ola_calor')
    record = mission.step()
    assert record['reason'] == 'R01_LIMITE_TERMICO'
    assert mission.finished and mission.state == 'MODO_SEGURO'


def test_heat_wave_is_available_from_the_panel_api():
    session = Session(seed=42)
    assert 'ola_calor' in session.dispatch('meta')['events']
    session.dispatch('step', {'n': 2})
    snapshot = session.dispatch('inject', {'kind': 'ola_calor'})
    assert snapshot['status']['heat'] == 12


# ------------------------------------------------------------------ F4
def test_quake_shakes_and_damages():
    base, shaken = pair()
    shaken.inject('sismo')
    assert shaken.health == pytest.approx(base.health - 3.)
    assert shaken.vibration_level > base.vibration_level == 0


def test_meteorite_damages_only_when_it_lands_next_to_the_rover():
    base, near = pair()
    row, col = near.position
    adjacent = next(c for c in ((row, col + 1), (row + 1, col), (row, col - 1), (row - 1, col))
                    if near.world.in_bounds(c) and c not in near.world.refuges)
    near.inject('meteorito', position=list(adjacent))
    assert near.health == pytest.approx(base.health - 5.)
    assert near.vibration_level > 0
    _, far = pair()
    far.inject('meteorito', position=[11, 15] if far.position != (11, 15) else [11, 14])
    assert far.health == pytest.approx(base.health)


def test_biosignal_costs_analysis_energy_and_never_claims_life():
    base, probe = pair()
    entry = probe.inject('biosenal_anomala')
    assert probe.battery == pytest.approx(base.battery - 1.)
    assert probe.summary()['anomalies'] == 1
    assert 'no confirma vida' in entry['message']


def test_alien_contact_is_counted():
    _, mission = pair()
    mission.inject('alienigena')
    assert mission.summary()['contacts'] == 1


def test_link_loss_reports_latency_and_queued_orders():
    _, mission = pair()
    assert mission.link_latency == 0 and mission.queued_orders == 0
    mission.inject('perdida_enlace')
    mission.step(), mission.step()
    assert mission.link_latency > 0
    mission.inject('dia')                    # operator order issued while the link is down
    assert mission.queued_orders == 1
    for _ in range(12):
        mission.step()
    assert mission.link_latency == 0 and mission.queued_orders == 0
    assert mission.summary()['link_outage_steps'] == 10


@pytest.mark.parametrize('planet,mode', [('Marte', 'rover'), ('Júpiter', 'sonda')])
def test_wind_raises_consumption_for_five_steps(planet, mode):
    base, windy = pair(planet=planet, mode=mode)
    windy.inject('viento')
    assert windy.wind_speed > base.wind_speed == 0
    assert windy.cell_cost(.5) == pytest.approx(1.3 * base.cell_cost(.5))
    for _ in range(6):
        windy.step()
    assert windy.wind_speed == 0 and windy.cell_cost(.5) == pytest.approx(base.cell_cost(.5))


def test_sensor_failure_counts_degraded_steps():
    _, mission = pair()
    mission.inject('falla_sensor', sensor='distance')
    for _ in range(4):
        mission.step()
    assert mission.summary()['degraded_steps'] >= 3


def test_summary_and_exports_count_events_by_kind():
    _, mission = pair()
    for kind in ('sismo', 'sismo', 'tormenta_polvo'):
        mission.inject(kind)
    for _ in range(4):
        mission.step()
    summary = mission.summary()
    assert summary['events']['sismo'] == 2 and summary['events']['tormenta_polvo'] == 1
    assert summary['events_total'] == 3 and summary['wait_steps'] >= 2
    exported = mission.export_json()
    assert exported['summary']['events_total'] == 3
    assert json.dumps(exported, allow_nan=False)
    assert 'event_count' in mission.export_csv().splitlines()[0]


def test_panel_status_exposes_event_metrics():
    session = Session(seed=42)
    session.dispatch('step', {'n': 2})
    status = session.dispatch('inject', {'kind': 'sismo'})['status']
    assert status['vibration'] > 0 and status['events_total'] == 1
    assert {'wind', 'link_latency', 'queued_orders', 'heat'} <= set(status)


# ------------------------------------------------------------------ F9
def test_perceivable_event_replans_immediately_without_a_step():
    _, mission = pair(steps=2)
    step, runs = mission.step_index, len(mission.ga_runs)
    target = tuple(mission.route[3])
    mission.inject('meteorito')
    assert mission.step_index == step
    assert target not in [tuple(c) for c in mission.route]
    assert len(mission.ga_runs) == runs + 1
    record = mission.step()
    assert len(mission.ga_runs) == runs + 1          # the AG does not run twice for one event
    assert record['ga'] is not None and record['ga']['reason'].startswith('METEORITO')


@pytest.mark.parametrize('kind', ['sismo', 'viento', 'bateria_baja', 'ola_calor', 'tormenta_polvo'])
def test_other_perceivable_events_also_replan_at_once(kind):
    _, mission = pair(steps=2)
    replans = mission.metrics['replans']
    mission.inject(kind)
    assert mission.metrics['replans'] > replans and mission.replan_reason is None


def test_hidden_hazard_does_not_replan_until_sensed():
    _, mission = pair(steps=2)
    before, replans = [tuple(c) for c in mission.route], mission.metrics['replans']
    cliff = tuple(mission.inject('barranco')['position'])
    assert [tuple(c) for c in mission.route] == before and mission.metrics['replans'] == replans
    assert mission.step()['reason'] == 'R04_VETO_BARRANCO_CONFIRMADO'
    assert cliff not in [tuple(c) for c in mission.route]


def test_event_sequences_remain_reproducible():
    traces = []
    for _ in range(2):
        _, mission = pair(steps=2)
        for kind in ('meteorito', 'ola_calor', 'viento'):
            mission.inject(kind)
            mission.step()
        mission.run()
        traces.append(json.dumps(mission.logger.trace, sort_keys=True))
    assert traces[0] == traces[1]
